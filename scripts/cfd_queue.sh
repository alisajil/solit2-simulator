#!/usr/bin/env bash
# Runs a batch of FDS run directories through `solit2 fds-exec`, at most
# SOLIT2_CFD_PARALLEL at a time (default 3 -- three ten-mesh runs is the
# whole 32 vCPU this deployment's server carries, spent once; see
# docs/cloud-compute.md for the box this was sized against).
#
# Safe to re-run, which is the whole point of it: a run directory
# `solit2 fds-status` already reads as `done` is skipped untouched, and one
# still running/stopped/failed -- because a reboot or an SSH drop cut it off
# mid-flight -- goes through `fds-exec` again, which resumes it from its own
# restart files (see solit2/engines/fds/exec_run.py). Nothing here decides
# WHETHER to resume; that is `fds-exec`'s call, made from what is actually on
# disk, not from anything this script remembers between runs.
#
# Two more guards on top of that: an `flock` per run dir means two
# overlapping invocations of this script (a hand-run one and the systemd
# unit's, say) never call `fds-exec` on the same run dir at once, and a
# per-run-dir failure counter (`.fds-exec.failures`) stops retrying a run
# that has failed MAX_FAILURES times in a row -- a bad deck is a reason to
# stop and look, not a reason to keep spending the server's time.
#
# Usage:
#   scripts/cfd_queue.sh RUN_DIR [RUN_DIR ...]
#
# Every run dir must already hold deck.fds (and design.json, if it may ever
# need to resume). Meant to run under deploy/systemd/solit2-cfd.service so a
# queue survives an SSH disconnect and a reboot; running it directly from an
# interactive shell works the same way, just without either guarantee.
set -euo pipefail

# Resolved once, up front, so the worker re-invocation below finds this same
# script regardless of the caller's cwd or whether `$0` was relative.
SCRIPT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"
PARALLEL="${SOLIT2_CFD_PARALLEL:-3}"
# A run dir gets this many `fds-exec` attempts before the queue stops
# retrying it automatically -- a run that fails for a reason `fds-exec`
# itself cannot fix (a bad deck, a dead disk) must not burn the whole
# server's time forever; see the systemd unit's own StartLimitBurst for the
# matching guard one level up.
MAX_FAILURES=3
# `flock`'s own exit code when `-n` finds the lock already held, distinct
# from any exit code `fds-exec` itself could return -- this is what tells
# "another process already has this run dir" apart from "fds-exec ran and
# failed with this same number".
LOCK_BUSY_CODE=99

# IST, explicit offset, never naive local time -- matches every other
# timestamp this deployment writes (exec.log, docs/cloud-compute.md). The
# offset is appended literally rather than read from `date %z`/`%:z`: IST
# carries no daylight-saving shift, so it is always +05:30, and `%:z` is a
# GNU extension this must not depend on (BSD/macOS `date`, used to run this
# script's own tests, does not have it).
_stamp() {
  echo "$(TZ="Asia/Kolkata" date +"%Y-%m-%dT%H:%M:%S")+05:30"
}

# Writes one line to both stdout (so `journalctl -u solit2-cfd` shows it
# live) and the run's own queue.log (so it is still there after the unit
# has moved on to the next run, or the whole box rebooted).
_log() {
  local run_dir="$1"; shift
  local line
  line="$(_stamp)  $*"
  echo "$line"
  echo "$line" >> "$run_dir/queue.log"
}

_is_done() {
  # `solit2 fds-status` prints "<state>  <progress>%  <detail>"; only the
  # state word is read here, deliberately reusing runner.status()'s own
  # definition of "done" instead of re-reading FDS's log a second,
  # potentially divergent way.
  local run_dir="$1"
  local state
  state="$(uv run solit2 fds-status "$run_dir" 2>/dev/null | awk '{print $1}')"
  [[ "$state" == "done" ]]
}

_failure_count() {
  local run_dir="$1"
  if [[ -f "$run_dir/.fds-exec.failures" ]]; then
    cat "$run_dir/.fds-exec.failures"
  else
    echo 0
  fi
}

_run_one() {
  local run_dir="$1"
  if _is_done "$run_dir"; then
    _log "$run_dir" "skip: already done"
    return 0
  fi
  local failures
  failures="$(_failure_count "$run_dir")"
  if (( failures >= MAX_FAILURES )); then
    _log "$run_dir" "failed ${MAX_FAILURES} times, skipped; inspect run.out"
    return 0
  fi
  _log "$run_dir" "start"
  set +e
  # `flock -n` on a lock file INSIDE the run dir: two invocations of this
  # script pointed at the same run dir -- a manual run overlapping the
  # systemd unit's, or two queue files that both name it -- must never run
  # `fds-exec` on it twice at once. `-E "$LOCK_BUSY_CODE"` makes a lock
  # conflict distinguishable from `fds-exec` itself exiting non-zero, which
  # a bare exit-code check could not tell apart otherwise.
  flock -n -E "$LOCK_BUSY_CODE" "$run_dir/.fds-exec.lock" \
    uv run solit2 fds-exec "$run_dir" >> "$run_dir/queue.log" 2>&1
  local code=$?
  set -e
  if [[ "$code" -eq "$LOCK_BUSY_CODE" ]]; then
    _log "$run_dir" "already running, skipped"
    return 0
  fi
  _log "$run_dir" "finish: exit=$code"
  if [[ "$code" -eq 0 ]]; then
    # A success clears the counter: three failures followed by a resumed
    # success is a recovered run, not one still on probation.
    rm -f "$run_dir/.fds-exec.failures"
  else
    echo "$((failures + 1))" > "$run_dir/.fds-exec.failures"
  fi
  return "$code"
}

if [[ "${1:-}" == "--worker" ]]; then
  # Re-invoked by xargs below, one run dir per call -- this is the
  # parallelism cap, enforced by xargs itself rather than by a second
  # language or a job runner this deployment would then have to install too.
  _run_one "$2"
  exit $?
fi

if [[ $# -eq 0 ]]; then
  echo "usage: scripts/cfd_queue.sh RUN_DIR [RUN_DIR ...]" >&2
  exit 1
fi

# NUL-delimited rather than one-per-line: this must not exist as two
# competing ideas of "what separates one run dir from the next". A GNU
# `xargs -d '\n'` would say the same thing more directly, but BSD/macOS
# `xargs` -- what runs this script's own tests -- has no `-d`; `-0` is the
# one delimiter flag both implementations share, so `--worker` never sees a
# run dir split apart by a space in its own path.
printf '%s\0' "$@" | xargs -0 -I{} -P "$PARALLEL" "$SCRIPT" --worker {}

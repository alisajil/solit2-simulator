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

_run_one() {
  local run_dir="$1"
  if _is_done "$run_dir"; then
    _log "$run_dir" "skip: already done"
    return 0
  fi
  _log "$run_dir" "start"
  set +e
  uv run solit2 fds-exec "$run_dir" >> "$run_dir/queue.log" 2>&1
  local code=$?
  set -e
  _log "$run_dir" "finish: exit=$code"
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

printf '%s\n' "$@" | xargs -I{} -P "$PARALLEL" "$SCRIPT" --worker {}

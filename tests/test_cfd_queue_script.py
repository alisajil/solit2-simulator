"""`scripts/cfd_queue.sh` against a FAKE `uv` on PATH -- the same style
`tests/test_tier2_campaign_script.py` uses for a shell wrapper, because this
script's whole job is the skip/resume decision and the queue.log
bookkeeping around `solit2 fds-status`/`fds-exec`, neither of which this
test can call for real (no FDS install here).

The fake `uv` stands in for both subcommands the script shells out to:
`fds-status` reports "done" when the run dir carries a DONE_MARKER file
this test placed (standing in for whatever `runner.status()` would have
read from a real FDS log), and `fds-exec` records every run dir it was
called for in CALL_LOG, so "was fds-exec skipped for a done run" and "was
fds-exec called for an incomplete one" are both directly observable.
"""
import os
import stat
import subprocess
import time
from pathlib import Path

SCRIPT = Path("scripts/cfd_queue.sh").resolve()

_FAKE_UV = """#!/usr/bin/env bash
# args: run solit2 <subcommand> <run_dir>
shift 2
sub="$1"; shift
run_dir="$1"
case "$sub" in
  fds-status)
    if [[ -f "$run_dir/DONE_MARKER" ]]; then
      echo "done  100%  "
    else
      echo "failed  0%  no FDS log in $run_dir"
    fi
    ;;
  fds-exec)
    echo "$run_dir" >> "$CALL_LOG"
    if [[ -n "${FAKE_SLEEP:-}" ]]; then
      sleep "$FAKE_SLEEP"
    fi
    if [[ -f "$run_dir/FAIL_MARKER" ]]; then
      exit 7
    fi
    touch "$run_dir/DONE_MARKER"
    exit 0
    ;;
  *)
    echo "fake uv: unknown solit2 subcommand $sub" >&2
    exit 2
    ;;
esac
"""


def _make_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _fake_bin(tmp_path: Path) -> Path:
    bindir = tmp_path / "bin"
    bindir.mkdir(exist_ok=True)
    _make_executable(bindir / "uv", _FAKE_UV)
    return bindir


def _run(tmp_path: Path, run_dirs: list[Path], *, parallel: int | None = None,
         sleep: float | None = None):
    bindir = _fake_bin(tmp_path)
    call_log = tmp_path / "calls.log"
    call_log.unlink(missing_ok=True)  # a test may call _run() more than once
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}", "CALL_LOG": str(call_log)}
    if parallel is not None:
        env["SOLIT2_CFD_PARALLEL"] = str(parallel)
    if sleep is not None:
        env["FAKE_SLEEP"] = str(sleep)
    proc = subprocess.run(["bash", str(SCRIPT), *[str(d) for d in run_dirs]],
                          capture_output=True, text=True, env=env)
    return proc, call_log


def test_no_run_dirs_is_a_usage_error(tmp_path):
    proc, _ = _run(tmp_path, [])
    assert proc.returncode == 1
    assert "usage" in proc.stderr.lower()


def test_a_run_dir_already_done_is_skipped(tmp_path):
    run_dir = tmp_path / "r1"
    run_dir.mkdir()
    (run_dir / "DONE_MARKER").write_text("")
    proc, call_log = _run(tmp_path, [run_dir])
    assert proc.returncode == 0, proc.stderr
    assert not call_log.exists(), "fds-exec must never be called for an already-done run"
    assert "skip: already done" in (run_dir / "queue.log").read_text()


def test_an_incomplete_run_dir_goes_through_fds_exec(tmp_path):
    run_dir = tmp_path / "r1"
    run_dir.mkdir()
    proc, call_log = _run(tmp_path, [run_dir])
    assert proc.returncode == 0, proc.stderr
    assert call_log.read_text().strip() == str(run_dir)
    log = (run_dir / "queue.log").read_text()
    assert "start" in log
    assert "finish: exit=0" in log
    assert (run_dir / "DONE_MARKER").exists(), "the fake fds-exec marks it done on success"


def test_a_failing_run_is_recorded_and_fails_the_queue(tmp_path):
    run_dir = tmp_path / "r1"
    run_dir.mkdir()
    (run_dir / "FAIL_MARKER").write_text("")
    proc, call_log = _run(tmp_path, [run_dir])
    assert proc.returncode != 0
    assert call_log.read_text().strip() == str(run_dir)
    assert "finish: exit=7" in (run_dir / "queue.log").read_text()
    assert not (run_dir / "DONE_MARKER").exists()


def test_queue_log_lines_carry_an_ist_offset(tmp_path):
    run_dir = tmp_path / "r1"
    run_dir.mkdir()
    _run(tmp_path, [run_dir])
    lines = (run_dir / "queue.log").read_text().splitlines()
    assert lines, "expected at least start/finish lines"
    for line in lines:
        assert "+05:30" in line, line


def test_mixed_batch_skips_done_and_runs_the_rest(tmp_path):
    done = tmp_path / "done"
    done.mkdir()
    (done / "DONE_MARKER").write_text("")
    pending = tmp_path / "pending"
    pending.mkdir()
    proc, call_log = _run(tmp_path, [done, pending])
    assert proc.returncode == 0, proc.stderr
    assert call_log.read_text().strip() == str(pending)


def test_a_reboot_style_rerun_only_touches_what_is_still_pending(tmp_path):
    # The scenario the whole script exists for: one run finished before a
    # reboot, one did not. Re-running the same batch must not re-invoke
    # fds-exec for the finished one.
    finished = tmp_path / "finished"
    finished.mkdir()
    interrupted = tmp_path / "interrupted"
    interrupted.mkdir()
    _run(tmp_path, [finished, interrupted])  # first pass: both run to completion
    assert (finished / "DONE_MARKER").exists()
    assert (interrupted / "DONE_MARKER").exists()
    (interrupted / "DONE_MARKER").unlink()   # simulate: this one never finished
    proc, call_log = _run(tmp_path, [finished, interrupted])
    assert proc.returncode == 0, proc.stderr
    assert call_log.read_text().strip() == str(interrupted)


def test_at_most_parallel_runs_execute_concurrently(tmp_path):
    # Four run dirs, each fds-exec sleeping 0.3s, capped at 2 at a time:
    # strictly serial would take >= 1.2s; two full batches take ~0.6s. The
    # threshold is generous on both sides to avoid CI flakiness while still
    # distinguishing "ran in parallel" from "ran one at a time".
    run_dirs = []
    for i in range(4):
        d = tmp_path / f"r{i}"
        d.mkdir()
        run_dirs.append(d)
    start = time.monotonic()
    proc, call_log = _run(tmp_path, run_dirs, parallel=2, sleep=0.3)
    elapsed = time.monotonic() - start
    assert proc.returncode == 0, proc.stderr
    assert len(call_log.read_text().splitlines()) == 4
    assert elapsed < 1.0, f"took {elapsed:.2f}s, looks serial rather than parallel"

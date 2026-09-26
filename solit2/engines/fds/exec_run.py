"""Foreground FDS execution for a run directory that already holds a deck --
the entry point `scripts/cfd_queue.sh` (and, through it,
`deploy/systemd/solit2-cfd.service`) calls once per run on the dedicated CFD
server (`solit2 fds-exec`). See docs/cloud-compute.md for the deployment
this is the entry point into.

Every other launcher in this package (`runner.run`, `runner.resume`) starts
FDS DETACHED and returns immediately, because the app that starts them keeps
running afterwards and polls `runner.status()` for progress. The run queue
has no such app: it is a shell loop over run directories, and it needs to
know when EACH ONE finishes before it can free up a slot for the next, so
blocking until FDS finishes is the correct behaviour here rather than a
limitation.

Everything that decides HOW to run -- one MPI rank per mesh, one OpenMP
thread per rank, the resume/mesh-change check -- is reused from `runner.py`
rather than re-implemented here; this module owns only the foreground wait,
the `design.json` handoff a resume needs, and the IST-stamped exec.log an
operator reads without needing a live SSH session into the server.
"""
from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from solit2.engines.fds import runner as runner_mod
from solit2.schema.design import Design

# Every result and log in the deployment tooling is timestamped in IST, never
# naive local time -- the server runs in a different timezone than whoever
# reads the log, and "10:32" with no offset is a guess about which one.
IST = ZoneInfo("Asia/Kolkata")
LOG_NAME = "exec.log"
# The design a run dir's deck was generated from. `deck.fds` alone is enough
# to launch a FRESH run, but resuming after an interruption (a reboot, an
# OOM kill) rebuilds the deck with RESTART=.TRUE. from the design (see
# runner.prepare_resume), and a design is not recoverable from the deck text
# alone -- so whatever put a run on the server (see docs/cloud-compute.md's
# rsync step) must copy the design JSON in beside deck.fds under this name.
DESIGN_NAME = "design.json"
# How a caller adds mpiexec flags the server needs (--oversubscribe, an
# Intel-MPI fabric flag) without a code change -- read once per invocation,
# never cached, so the systemd unit's own Environment= line is the single
# place that decides it.
MPIEXEC_ARGS_ENV = "SOLIT2_MPIEXEC_ARGS"


def _stamp() -> str:
    return datetime.now(IST).isoformat(timespec="seconds")


def _log(run_dir: Path, message: str) -> None:
    with (Path(run_dir) / LOG_NAME).open("a") as f:
        f.write(f"{_stamp()}  {message}\n")


def _mpiexec_extra_args() -> list[str]:
    raw = os.environ.get(MPIEXEC_ARGS_ENV, "")
    return shlex.split(raw) if raw else []


def _load_design(run_dir: Path) -> Design:
    design_path = Path(run_dir) / DESIGN_NAME
    if not design_path.exists():
        raise FileNotFoundError(
            f"{run_dir} holds restart files but no {DESIGN_NAME}, so there is no "
            f"design to regenerate the RESTART=.TRUE. deck from. Whatever submitted "
            f"this run must copy the design JSON in as {DESIGN_NAME} next to deck.fds "
            f"-- see docs/cloud-compute.md")
    return Design.load(design_path)


def run_foreground(run_dir: Path, t_end_s: float | None = None) -> int:
    """Run FDS for `run_dir` to completion, blocking the calling process.

    Resumes from restart files when present, by the same deck-regeneration
    and mesh-change check `runner.resume` uses (`runner.prepare_resume`) --
    which needs the design, read from `run_dir/design.json`. A directory with
    no restart files needs no design at all: it runs whatever `deck.fds`
    already holds, exactly as written.

    Returns FDS's own process exit code, or `1` if the process exited zero
    but `runner.status` still does not read the run as `done` (a deadlocked
    or truncated run can exit non-zero from mpiexec's own supervision without
    FDS itself ever printing a failure). Never raises for an FDS failure --
    only for a problem in the SETUP (missing binaries, missing design.json,
    a moved mesh) that means FDS was never launched at all.
    """
    run_dir = Path(run_dir)
    problems = runner_mod.preflight()
    if problems:
        message = "; ".join(problems)
        _log(run_dir, f"start: refused -- {message}")
        raise RuntimeError(message)
    resuming = runner_mod.has_restart_files(run_dir)
    _log(run_dir, f"start: t_end_s={t_end_s} resuming={resuming}")
    deck_path = run_dir / "deck.fds"
    if resuming:
        design = _load_design(run_dir)
        deck_path = runner_mod.prepare_resume(run_dir, design, t_end_s=t_end_s)
        _log(run_dir, f"resume: regenerated deck.fds with RESTART=.TRUE. from {DESIGN_NAME}")
    elif not deck_path.exists():
        raise FileNotFoundError(f"{run_dir} holds no deck.fds to run")
    ranks = max(runner_mod.mesh_count(deck_path), 1)
    env = {**os.environ}
    env.setdefault("OMP_NUM_THREADS", runner_mod.OMP_THREADS_PER_RANK)
    # `-np`, the same flag `runner.run` launches with -- one spelling for
    # "how many ranks" across this whole package, rather than two that
    # happen to mean the same thing on every MPI implementation FDS ships
    # against (Open MPI, MPICH, Intel MPI).
    argv = [shutil.which("mpiexec"), "-np", str(ranks), *_mpiexec_extra_args(),
            runner_mod._binary(), deck_path.name]
    _log(run_dir, f"launch: {shlex.join(str(a) for a in argv)}")
    # "w" on a fresh launch, exactly like runner.run's own log -- a first
    # attempt starts from a clean run.out. "a" on a resume: the whole point
    # of resuming is picking up after an earlier attempt, so that attempt's
    # own output stays on disk instead of being overwritten by this one.
    log_mode = "a" if resuming else "w"
    with (run_dir / runner_mod.LOG_NAME).open(log_mode) as log:
        completed = subprocess.run(argv, cwd=run_dir, stdout=log,
                                   stderr=subprocess.STDOUT, env=env)
    state = runner_mod.status(run_dir)["state"]
    ok = state == "done"
    _log(run_dir, f"end: mpiexec_exit={completed.returncode} state={state}")
    return 0 if ok else (completed.returncode or 1)

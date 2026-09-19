"""Pre-flight, launch and status for an FDS run.

Every check here is a filesystem or environment lookup, so the whole module is
testable by monkeypatching `shutil` and the environment -- which is the only way
it CAN be tested, since no FDS install exists yet.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

BIN_ENV = "SOLIT2_FDS_BIN"
REMOTE_ENV = "SOLIT2_FDS_HOST"
MIN_FREE_BYTES = 10 * 1024**3          # parent spec: 10 GB floor
LOG_NAME = "run.out"
_TOTAL_TIME = re.compile(r"Total Time:\s+([\d.]+)\s*s")
_T_END = re.compile(r"T_END\s*=\s*([\d.]+)")
_DONE = "STOP: FDS completed successfully"
# Anything FDS says that is not the success STOP means the run is over and did
# not finish. Without this, "no progress line yet" and "dead" look identical.
_ERROR = re.compile(r"^[ \t]*(?:ERROR|STOP: (?!FDS completed successfully))",
                    re.MULTILINE)
# FDS banners its build as "Revision : FDS6.9.1-0-g..." or "Version : FDS 6.7.0".
_VERSION = re.compile(r"(?:FDS|Version\s*:)\s*v?(\d+\.\d+(?:\.\d+)?)")


def _binary() -> str | None:
    explicit = os.environ.get(BIN_ENV)
    if explicit and Path(explicit).exists():
        return explicit
    return shutil.which("fds")


def preflight() -> list[str]:
    """Blocking problems, in the order a user should fix them. Empty = ready."""
    if os.environ.get(REMOTE_ENV):
        # Deliberate: guessing at SSH-vs-queue semantics with no host to test
        # against would be building against an imagined system.
        return [f"remote execution via {REMOTE_ENV} is not implemented; "
                f"unset it to run locally"]
    problems = []
    if _binary() is None:
        problems.append(f"the fds binary is not on PATH and {BIN_ENV} is not set")
    if shutil.which("mpiexec") is None:
        problems.append("mpiexec is not on PATH (FDS runs the mesh set under MPI)")
    if shutil.disk_usage(Path.cwd()).free < MIN_FREE_BYTES:
        problems.append(f"less than {MIN_FREE_BYTES // 1024**3} GB of free disk")
    return problems


def mesh_count(deck_path: Path) -> int:
    """How many `&MESH` lines the deck carries -- one MPI rank each."""
    return sum(1 for ln in Path(deck_path).read_text().splitlines()
               if ln.startswith("&MESH"))


def run(deck_path: Path, out_dir: Path) -> str:
    """Launch FDS detached, one MPI rank per mesh, and return immediately.

    A run is hours long; the Verify view polls `status()` rather than blocking
    on it, and the CLI does its own waiting.

    `mpiexec -np N` with N = the deck's mesh count is the standard FDS mapping:
    FDS assigns meshes to ranks in order. A bare `fds` invocation runs every
    mesh in one process, which is valid but serial -- measured at 2.1x slower
    than three ranks on a three-mesh deck on the machine this was built on.
    """
    problems = preflight()
    if problems:
        raise RuntimeError("; ".join(problems))
    out_dir.mkdir(parents=True, exist_ok=True)
    local_deck = out_dir / "deck.fds"
    if Path(deck_path).resolve() != local_deck.resolve():
        shutil.copy(deck_path, local_deck)
    ranks = max(mesh_count(local_deck), 1)
    with (out_dir / LOG_NAME).open("w") as log:
        subprocess.Popen([shutil.which("mpiexec"), "-np", str(ranks),
                          _binary(), local_deck.name],
                         cwd=out_dir, stdout=log, stderr=subprocess.STDOUT,
                         start_new_session=True)
    return out_dir.name


def log_path(run_dir: Path) -> Path | None:
    """FDS's own `<CHID>.out` if it is there, else the stdout `run()` captured.

    The progress and version lines this module parses are ones FDS writes to
    `<CHID>.out`. `run()` only captures the process's stdout, and whether that
    carries the same lines is install-dependent -- so FDS's own file wins and
    `run.out` is the fallback.
    """
    run_dir = Path(run_dir)
    own = sorted(p for p in run_dir.glob("*.out") if p.name != LOG_NAME)
    if own:
        return own[0]
    captured = run_dir / LOG_NAME
    return captured if captured.exists() else None


def fds_version(run_dir: Path) -> str | None:
    """The FDS that wrote this run, or None when the log does not say.

    Never guess: an unverified version in `Result.meta` is a provenance claim
    nothing measured.
    """
    log = log_path(run_dir)
    if log is None:
        return None
    found = _VERSION.search(log.read_text())
    return found.group(1) if found else None


def status(run_dir: Path) -> dict:
    """Progress from FDS's own log, against the deck's T_END."""
    log = log_path(run_dir)
    if log is None:
        return {"state": "failed", "progress": 0.0,
                "detail": f"no FDS log in {run_dir}"}
    text = log.read_text()
    if _DONE in text:
        return {"state": "done", "progress": 1.0, "detail": ""}
    if _ERROR.search(text):
        return {"state": "failed", "progress": 0.0,
                "detail": f"FDS reported an error in {log.name}"}
    deck = Path(run_dir) / "deck.fds"
    end = _T_END.search(deck.read_text()) if deck.exists() else None
    if end is None:
        return {"state": "failed", "progress": 0.0,
                "detail": "no deck.fds carrying a T_END to measure progress against"}
    elapsed = _TOTAL_TIME.findall(text)
    if not elapsed:
        # A run launched seconds ago has an open log and no time step in it yet.
        # Calling that "failed" made `run --engine fds` impossible to complete.
        return {"state": "running", "progress": 0.0,
                "detail": "launched; no simulated time reported yet"}
    return {"state": "running",
            "progress": min(float(elapsed[-1]) / float(end.group(1)), 1.0),
            "detail": ""}

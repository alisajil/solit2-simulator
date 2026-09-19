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


def run(deck_path: Path, out_dir: Path) -> str:
    """Launch FDS detached and return immediately.

    A run is hours long; the Verify view polls `status()` rather than blocking
    on it, and the CLI does its own waiting.
    """
    problems = preflight()
    if problems:
        raise RuntimeError("; ".join(problems))
    out_dir.mkdir(parents=True, exist_ok=True)
    local_deck = out_dir / "deck.fds"
    if Path(deck_path).resolve() != local_deck.resolve():
        shutil.copy(deck_path, local_deck)
    with (out_dir / LOG_NAME).open("w") as log:
        subprocess.Popen([_binary(), local_deck.name], cwd=out_dir,
                         stdout=log, stderr=subprocess.STDOUT,
                         start_new_session=True)
    return out_dir.name


def status(run_dir: Path) -> dict:
    """Progress from FDS's own log, against the deck's T_END."""
    log = Path(run_dir) / LOG_NAME
    deck = Path(run_dir) / "deck.fds"
    if not log.exists():
        return {"state": "failed", "progress": 0.0,
                "detail": f"no {LOG_NAME} in {run_dir}"}
    text = log.read_text()
    if _DONE in text:
        return {"state": "done", "progress": 1.0, "detail": ""}
    elapsed = _TOTAL_TIME.findall(text)
    end = _T_END.search(deck.read_text()) if deck.exists() else None
    if not elapsed or end is None:
        return {"state": "failed", "progress": 0.0,
                "detail": "the log carries no simulated time"}
    progress = min(float(elapsed[-1]) / float(end.group(1)), 1.0)
    return {"state": "running", "progress": progress, "detail": ""}

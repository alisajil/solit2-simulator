# solit2/reports/cfd_runs.py
"""Find the FDS run of a design and say what state it is in.

A run belongs to a design when its CHID is the design's SHA (`deck.chid`), so a
run is found by the design alone -- nobody links it by hand. Reading is I/O, so it
happens here and in the CLI; the report itself only formats a `CfdRun`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from solit2.engines.fds import deck, reader, runner
from solit2.schema.design import Design
from solit2.schema.result import Result

_T_END = re.compile(r"T_END\s*=\s*([\d.]+)")


@dataclass(frozen=True)
class CfdRun:
    # "not_run", "unreadable", or one of runner.status()'s states.
    state: str
    detail: str
    result: Result | None = None


NOT_RUN = CfdRun("not_run", "CFD not yet run")


def _t_end_s(deck_path: Path) -> float | None:
    # ponytail: regex on the deck text, as runner.status does; read T_END from the
    # design instead if the deck generator ever lets T_END drift from it.
    found = _T_END.search(deck_path.read_text())
    return float(found.group(1)) if found else None


def lookup(design: Design, runs_dir: Path | str) -> CfdRun:
    root = Path(runs_dir)
    run_dir = root / deck.chid(design)
    if not (run_dir / "deck.fds").exists():
        return NOT_RUN
    status = runner.status(run_dir)
    state = str(status["state"])
    if state in runner.RUNNING_STATES:
        t_end = _t_end_s(run_dir / "deck.fds")
        if t_end is None:
            return CfdRun(state, f"{state}, {float(status['progress']):.0%} complete")
        done = float(status["progress"]) * t_end
        return CfdRun(state, f"running, {done:.0f} of {t_end:.0f} s")
    if state != "done":
        return CfdRun(state, str(status.get("detail") or state))
    free_dir = root / deck.chid(design, suppression=False)
    try:
        result = reader.read(run_dir, design,
                             free_burn_dir=free_dir if (free_dir / "deck.fds").exists() else None)
    except (OSError, ValueError, KeyError) as exc:
        return CfdRun("unreadable", str(exc))
    return CfdRun("done", "", result)

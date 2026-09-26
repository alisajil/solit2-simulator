"""One run-state -> chip-class map, shared by the simulator's CFD panel
(`app/components/cfd_live.py`) and the runs manager (`app/views/runs.py`), so a
run's state reads the same status everywhere it appears (M-3).

`"running"` must never map to `"pass"`: a run that has not finished yet is not
a verdict, and the runs manager already treated it that way before the
simulator's own panel (wrongly) read it as one.
"""
from __future__ import annotations

CHIP_CLASS = {
    "done": "pass",
    "failed": "fail",
    "stopped": "fail",
    "paused": "unset",
    "running": "unset",
    "pausing": "unset",
    "pending": "unset",
    # `cfd_live.panel()`'s own state for a run whose files could not be read
    # (an OSError while parsing) -- not one of `fleet`'s run states, but a real
    # problem, not a neutral "not yet judged".
    "unreadable": "fail",
}


def chip_class(state: str) -> str:
    """The CSS chip class for a run's reported state. An unmapped state falls
    back to `"unset"` rather than risk a false pass."""
    return CHIP_CLASS.get(state, "unset")

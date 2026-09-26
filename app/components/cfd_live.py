"""The simulator's CFD panel: what an FDS run of this exact design is doing, read
from the run's own files. A run belongs to a design when its CHID is the design's
SHA (`deck.chid`) -- the CFD step names its run directories that way, so the
panel finds a run without anyone linking it by hand."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.views import cfd
from solit2.engines.fds import runner as fds_runner
from solit2.schema.design import Design

# How often the panel re-reads the run's files: the same cadence as the runs manager.
REFRESH_S = 10
# The four readings worth a glance beside the figure; the CFD step shows them all.
PANEL_METRICS = ("Simulated", "Speed", "Left, at this speed", "Heat release")


@dataclass(frozen=True)
class Panel:
    run_dir: Path
    state: str
    progress: float
    detail: str
    metrics: tuple[tuple[str, str, str | None], ...]


def panel(design: Design) -> Panel | None:
    """The run of this design, or None when there is none."""
    run_dir = cfd.run_dir_for(design)
    if not (run_dir / "deck.fds").exists():
        return None
    try:
        status = fds_runner.status(run_dir)
        live = fds_runner.live(run_dir)
    except OSError as exc:
        return Panel(run_dir, "unreadable", 0.0, f"{run_dir}: {exc}", ())
    metrics = tuple(m for m in cfd.live_metrics(live) if m[0] in PANEL_METRICS)
    return Panel(run_dir, str(status["state"]), float(status.get("progress") or 0.0),
                 str(status.get("detail") or ""), metrics)

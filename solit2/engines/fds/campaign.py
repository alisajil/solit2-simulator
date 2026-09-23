"""The Tier 2 credibility campaign: chains an E_COEFFICIENT sweep, a
grid-convergence study, and a full-duration run behind one command.

The supported entry point is `scripts/tier2_campaign.sh`, which refuses to
start on battery power and wraps the whole run in `caffeinate -i -s` --
both OS-level concerns that belong in shell, not here (see that script).
Calling `solit2 fds-campaign` directly, bypassing the wrapper, skips both
guards; this module does not repeat them.

Every step goes through `runner.run_or_resume` (a `done` run is skipped, one
with restart files is resumed, only a new one is launched fresh), so the
whole campaign survives being interrupted and re-run -- it is meant to run
for many hours unattended.
"""
from __future__ import annotations

import time
from pathlib import Path

from solit2.engines.fds import calibrate as calibrate_mod
from solit2.engines.fds import grid as grid_mod
from solit2.engines.fds import runner as runner_mod
from solit2.schema.design import Design
from validation.compare import load_anchors

FULL_RUN_DIR_NAME = "full"
POLL_S = 30.0


def estimate_rate(out: Path) -> float | None:
    """The most recently updated run's own measured rate (simulated seconds
    per wall second), from whichever `*_steps.csv` under `out` was written to
    most recently. None when no run under `out` has written one yet --
    NEVER a guessed or default number; a caller who wants a rate waits for a
    run's own log to produce one.
    """
    candidates = sorted(Path(out).rglob(f"*{runner_mod.STEPS_SUFFIX}"),
                        key=lambda p: p.stat().st_mtime, reverse=True)
    for path in candidates:
        rate = runner_mod.live(path.parent)["rate_s_per_s"]
        if rate is not None:
            return rate
    return None


def _wait(run_dir: Path, poll_s: float) -> None:
    while runner_mod.status(run_dir)["state"] == "running":
        time.sleep(poll_s)


def run_e_sweep(e_anchor_ids: tuple[str, ...], e_values: tuple[float, ...], dx_m: float,
                out: Path, poll_s: float = POLL_S) -> Path:
    """Step 1: the E_COEFFICIENT sweep on the named anchors, at `dx_m`."""
    anchors = load_anchors(e_anchor_ids)
    sweep_out = Path(out) / "ecal"
    calibrate_mod.write_decks(anchors, e_values, dx_m, sweep_out)
    for anchor in anchors:
        for e in e_values:
            run_dir = calibrate_mod.run_dir_for(sweep_out, anchor.id, e, dx_m)
            runner_mod.run_or_resume(run_dir / "deck.fds", run_dir, anchor.design)
            _wait(run_dir, poll_s)
    return sweep_out


def run_grid_study(design: Design, grid_dx: tuple[float, float, float], grid_t_end_s: float,
                   out: Path, poll_s: float = POLL_S) -> Path:
    """Step 2: the grid-convergence study on `design`, at the three `grid_dx`."""
    grid_out = Path(out) / "grid"
    grid_mod.write_decks(design, grid_dx, grid_t_end_s, grid_out)
    grid_mod.launch_and_wait(design, grid_dx, grid_out, t_end_s=grid_t_end_s, poll_s=poll_s)
    return grid_out


def run_full_duration(design: Design, out: Path, poll_s: float = POLL_S) -> Path:
    """Step 3: `design` run to its own `zones.duration_min` -- long enough,
    by the system's own sizing, to pass the fire's peak. This step only runs
    it; whether the peak was actually passed is for `reader.read` (deliverable
    A, `peaks['hrr_peak_passed']`) to say once it is read, not for this
    function to judge.
    """
    from solit2.engines.fds import deck as deck_mod
    run_dir = Path(out) / FULL_RUN_DIR_NAME / deck_mod.chid(design)
    run_dir.mkdir(parents=True, exist_ok=True)
    deck_path = run_dir / "deck.fds"
    if not deck_path.exists():
        deck_path.write_text(deck_mod.generate(design))
    runner_mod.run_or_resume(deck_path, run_dir, design)
    _wait(run_dir, poll_s)
    return run_dir


def run_campaign(design: Design, out: Path, *, e_anchor_ids: tuple[str, ...],
                 e_values: tuple[float, ...], dx_m: float,
                 grid_dx: tuple[float, float, float], grid_t_end_s: float,
                 poll_s: float = POLL_S, print_fn=print) -> dict[str, Path]:
    """The three steps, in order, with the up-front rate estimate first."""
    rate = estimate_rate(out)
    print_fn(f"estimated rate from the latest finished run under {out}: "
             f"{rate:.3f} simulated s / wall s" if rate is not None else
             f"no finished run under {out} yet -- the rate this machine will run at "
             f"is unknown until one completes")
    print_fn("step 1/3: E_COEFFICIENT sweep")
    ecal_dir = run_e_sweep(e_anchor_ids, e_values, dx_m, out, poll_s)
    print_fn("step 2/3: grid-convergence study")
    grid_dir = run_grid_study(design, grid_dx, grid_t_end_s, out, poll_s)
    print_fn("step 3/3: full-duration run")
    full_dir = run_full_duration(design, out, poll_s)
    return {"ecal": ecal_dir, "grid": grid_dir, "full": full_dir}

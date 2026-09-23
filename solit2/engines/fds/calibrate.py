"""FDS's `E_COEFFICIENT` calibration sweep: decks across a grid of E for the
published anchor fire tests (`validation.compare.load_anchors`), optionally
launched and waited on, and a report of which E lands closest to each
anchor's measured peak HRR.

This module NEVER writes a fitted E back into `deck.E_COEFFICIENT` or
anywhere else. Adopting a fitted value is a human decision informed by the
report, exactly like every other acceptance limit this tool refuses to set
for itself (INDEPENDENCE.md rule 2) -- the difference here is that E is a
model constant rather than an AHJ limit, but the same rule applies: this tool
computes, a person decides.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from pathlib import Path

from solit2.engines.fds import deck as deck_mod
from solit2.engines.fds import reader as reader_mod
from solit2.engines.fds import runner as runner_mod
from validation.compare import Anchor

MEASURED_KEY = "peak_hrr_mw"
# How often a launched run is polled between status checks -- the same
# cadence `solit2 run --engine fds` waits at.
POLL_S = 30.0


def run_dir_for(out: Path, anchor_id: str, e: float, dx_m: float) -> Path:
    """`<out>/<anchor>/e_<E:.3f>_dx_<dx:.2f>` -- one directory per sweep point."""
    return Path(out) / anchor_id / f"e_{e:.3f}_dx_{dx_m:.2f}"


@dataclass(frozen=True)
class SweepPoint:
    anchor_id: str
    e: float
    dx_m: float
    run_dir: Path
    # Set once the run has been read and its peak counts toward the fit.
    modelled_peak_hrr_mw: float | None = None
    # Set instead, naming why this point does NOT count -- never both.
    excluded_reason: str | None = None

    @property
    def included(self) -> bool:
        return self.modelled_peak_hrr_mw is not None


def write_decks(anchors: tuple[Anchor, ...], e_values: tuple[float, ...],
                 dx_m: float, out: Path) -> list[Path]:
    """Every deck the sweep needs. Deterministic and idempotent -- calling this
    again (as `--report` alone does, ahead of reading) rewrites byte-identical
    files for anything already on disk and touches nothing else in a run's
    directory."""
    written = []
    for anchor in anchors:
        for e in e_values:
            run_dir = run_dir_for(out, anchor.id, e, dx_m)
            run_dir.mkdir(parents=True, exist_ok=True)
            deck_path = run_dir / "deck.fds"
            deck_path.write_text(deck_mod.generate(anchor.design, dx_m=dx_m, e_coefficient=e))
            written.append(deck_path)
    return written


def launch_and_wait(anchors: tuple[Anchor, ...], e_values: tuple[float, ...],
                     dx_m: float, out: Path, poll_s: float = POLL_S) -> None:
    """Launch every sweep point, one at a time, waiting for each to finish
    before starting the next -- a sweep is several runs deep and this machine
    has one set of cores to give them.

    Each point goes through `runner.run_or_resume`: a point already `done` is
    left alone, one with restart files left behind (stopped or paused between
    two invocations) is resumed rather than restarted from zero, and only a
    genuinely new point is launched fresh. These runs are hours long, and
    calling `--run` again -- to pick up a point added to a later `--e` list,
    or after an interruption -- must not throw away compute an earlier pass
    already paid for.
    """
    for anchor in anchors:
        for e in e_values:
            run_dir = run_dir_for(out, anchor.id, e, dx_m)
            runner_mod.run_or_resume(run_dir / "deck.fds", run_dir, anchor.design)
            while runner_mod.status(run_dir)["state"] == "running":
                time.sleep(poll_s)


def read_points(anchors: tuple[Anchor, ...], e_values: tuple[float, ...],
                 dx_m: float, out: Path) -> list[SweepPoint]:
    """Every sweep point, read from whatever is finished on disk.

    Only a run that COMPLETED (`runner.status` reports `done`) and whose HRR
    peak was actually PASSED (`Result.peaks['hrr_peak_passed']`) counts toward
    the fit -- an incomplete run has nothing to read yet, and a run that never
    passed its peak has only measured a lower bound, which is not comparable
    to the anchor's measured peak. Everything else is kept, with the reason it
    was excluded, rather than silently dropped.
    """
    points = []
    for anchor in anchors:
        for e in e_values:
            run_dir = run_dir_for(out, anchor.id, e, dx_m)
            status = runner_mod.status(run_dir)
            if status["state"] != "done":
                detail = status.get("detail", "")
                points.append(SweepPoint(
                    anchor.id, e, dx_m, run_dir,
                    excluded_reason=f"not completed: {status['state']}"
                                    + (f" ({detail})" if detail else "")))
                continue
            try:
                result = reader_mod.read(run_dir, anchor.design)
            except (KeyError, ValueError, FileNotFoundError, OSError) as exc:
                points.append(SweepPoint(anchor.id, e, dx_m, run_dir,
                                         excluded_reason=f"could not be read: {exc}"))
                continue
            if not result.peaks.get("hrr_peak_passed"):
                points.append(SweepPoint(
                    anchor.id, e, dx_m, run_dir,
                    excluded_reason="the HRR peak was not passed within the simulated "
                                    "window (peaks.hrr_peak_passed is False): its peak HRR "
                                    "is a lower bound, not comparable to the anchor's "
                                    "measured peak"))
                continue
            points.append(SweepPoint(anchor.id, e, dx_m, run_dir,
                                     modelled_peak_hrr_mw=result.peaks["hrr_mw"]))
    return points


def weighted_error_by_e(anchors: tuple[Anchor, ...],
                        points: list[SweepPoint]) -> dict[float, float]:
    """The weight-averaged squared relative error at each E, over whichever
    anchors have an INCLUDED point at that E. An E with no included point at
    all is left out -- there is nothing to average."""
    weight = {a.id: a.weight for a in anchors}
    measured = {a.id: a.measured[MEASURED_KEY] for a in anchors}
    rows: dict[float, list[tuple[float, float]]] = {}
    for p in points:
        if not p.included:
            continue
        m = measured[p.anchor_id]
        relative = (p.modelled_peak_hrr_mw - m) / m
        rows.setdefault(p.e, []).append((weight[p.anchor_id], relative * relative))
    return {e: sum(w * sq for w, sq in weighted) / sum(w for w, _ in weighted)
            for e, weighted in rows.items()}


@dataclass(frozen=True)
class FitResult:
    best_e: float | None
    reason: str | None       # set (only) when best_e is None


def best_e(errors_by_e: dict[float, float]) -> FitResult:
    """The E minimising the weight-averaged squared relative error.

    The discrete sample with the lowest error is found first; if it sits at
    either end of the sampled E's there is no sample on one side to bracket
    it with, so the true minimum could lie outside the sampled range --
    reported as unbracketed, naming no best E, NEVER extrapolated to.

    When it is interior, the two sampled intervals either side of it --
    (E[m-1], E[m]) and (E[m], E[m+1]) -- are each a straight line of error
    against ln(E), with slopes `slope_left` (negative: error still falling
    into the minimum) and `slope_right` (positive: error rising back out).
    Treating each slope as the error's derivative at that interval's own
    midpoint and linearly interpolating between the two midpoints for where
    the derivative crosses zero gives a refined E between the sampled grid
    points, rather than reporting one of only a handful of coarse samples.
    """
    if not errors_by_e:
        return FitResult(None, "no sampled E has any usable run to compare")
    es = sorted(errors_by_e)
    ys = [errors_by_e[e] for e in es]
    m = min(range(len(ys)), key=lambda i: ys[i])
    if m == 0 or m == len(ys) - 1:
        return FitResult(None,
            f"the lowest-error sampled E is E={es[m]:g}, at a sampled end of the sweep "
            f"({es[0]:g}..{es[-1]:g}); the true minimum may lie beyond it and this fit "
            f"must never extrapolate to guess where")
    x = [math.log(e) for e in es]
    slope_left = (ys[m] - ys[m - 1]) / (x[m] - x[m - 1])
    slope_right = (ys[m + 1] - ys[m]) / (x[m + 1] - x[m])
    if slope_right == slope_left:
        return FitResult(es[m], None)          # perfectly flat either side: the sample stands
    x_a, x_b = (x[m - 1] + x[m]) / 2.0, (x[m] + x[m + 1]) / 2.0
    fraction = (0.0 - slope_left) / (slope_right - slope_left)
    return FitResult(math.exp(x_a + fraction * (x_b - x_a)), None)


def render(anchors: tuple[Anchor, ...], points: list[SweepPoint],
           errors_by_e: dict[float, float], fit: FitResult, dx_m: float) -> str:
    lines = [
        "# FDS E_COEFFICIENT calibration sweep", "",
        f"Cell size dx = {dx_m:.2f} m. **An E fitted here applies at this dx only** -- a "
        f"different dx is a different deck (different mesh, different HRRPUA snapping) "
        f"and needs its own sweep.", "",
    ]
    for anchor in anchors:
        measured = anchor.measured[MEASURED_KEY]
        lines += [f"## {anchor.id} ({anchor.source})", "",
                  f"Measured peak HRR: {measured:.1f} MW, weight {anchor.weight:g}", "",
                  "| E | modelled peak HRR (MW) | relative error | counted |",
                  "|---|---|---|---|"]
        for p in sorted((p for p in points if p.anchor_id == anchor.id), key=lambda p: p.e):
            if not p.included:
                lines.append(f"| {p.e:g} | — | — | no -- {p.excluded_reason} |")
            else:
                relative = (p.modelled_peak_hrr_mw - measured) / measured
                lines.append(f"| {p.e:g} | {p.modelled_peak_hrr_mw:.1f} | {relative:+.1%} | "
                             f"yes |")
        lines.append("")
    lines += ["## Weight-averaged squared relative error by E", "",
              "Over anchors {" + ", ".join(a.id for a in anchors) + "}, counted points only.",
              "", "| E | error |", "|---|---|"]
    for e in sorted(errors_by_e):
        lines.append(f"| {e:g} | {errors_by_e[e]:.4g} |")
    lines.append("")
    if fit.best_e is not None:
        lines += [
            f"**Fitted E = {fit.best_e:.4g}** at dx = {dx_m:.2f} m, by linear interpolation "
            f"of the error's slope in ln(E) between the sampled values bracketing the "
            f"minimum.", "",
            "This is a fitted value, not an acceptance limit, and this tool does not adopt "
            "it anywhere: `deck.E_COEFFICIENT` stays whatever it is until a person decides "
            "to change it and edits `solit2/engines/fds/deck.py` by hand.",
        ]
    else:
        lines.append(f"**No best E is reported.** {fit.reason}.")
    lines.append("")
    return "\n".join(lines)


def to_json(anchors: tuple[Anchor, ...], points: list[SweepPoint],
            errors_by_e: dict[float, float], fit: FitResult, dx_m: float) -> dict:
    """The same report, as data -- for a caller that wants the numbers rather
    than the prose."""
    return {
        "dx_m": dx_m,
        "anchors": {a.id: {"measured_peak_hrr_mw": a.measured[MEASURED_KEY],
                           "weight": a.weight, "source": a.source} for a in anchors},
        "points": [{"anchor_id": p.anchor_id, "e": p.e,
                    "modelled_peak_hrr_mw": p.modelled_peak_hrr_mw,
                    "included": p.included, "excluded_reason": p.excluded_reason}
                   for p in points],
        "error_by_e": errors_by_e,
        "fit": {"best_e": fit.best_e, "reason": fit.reason},
    }

"""Grid-convergence study: a design's own deck run at three cell sizes, and
the discretisation uncertainty that spread implies, by the procedure in

    Celik, I.B., Ghia, U., Roache, P.J., Freitas, C.J., Coleman, H. and
    Raad, P.E., "Procedure for Estimation and Reporting of Uncertainty Due to
    Discretization in CFD Applications", Journal of Fluids Engineering,
    130(7), 078001, 2008.

Three grids h1 < h2 < h3 (finest to coarsest; non-uniform refinement is
allowed, r21 = h2/h1 need not equal r32 = h3/h2). For a quantity phi:

    e21 = phi2 - phi1, e32 = phi3 - phi2
    s = sign(e32 / e21)
    p = | ln|e32/e21| + q(p) | / ln(r21),   q(p) = ln( (r21^p - s) / (r32^p - s) )
    phi_ext21 = (r21^p * phi1 - phi2) / (r21^p - 1)
    e_a21 = | (phi1 - phi2) / phi1 |
    GCI_fine21 = 1.25 * e_a21 / (r21^p - 1)

`p` is found by fixed-point iteration. A sign reversal between the two grid
pairs (s < 0) is oscillatory convergence and is reported as such, not as a
number; an iteration that fails to reach a positive order is reported as
non-convergent, likewise not as a number.
"""
from __future__ import annotations

import math
import time
from dataclasses import asdict, dataclass
from pathlib import Path

from solit2.engines.fds import deck as deck_mod
from solit2.engines.fds import reader as reader_mod
from solit2.engines.fds import runner as runner_mod
from solit2.engines.fds.exec_run import DESIGN_NAME
from solit2.schema.design import Design

# The quantities a grid study checks, in report order -- whichever of these
# the reader's Result actually carries for this run (D15/D100 depend on the
# design's own instrumentation kit and whether they fall inside the deck
# window). Heat flux at D15 is Annex 7's own instrument but the FDS reader
# does not surface a station's flux as a peak or a timeseries today, so it is
# not in this list -- "whatever the reader exposes" (see the module brief)
# rather than a claim this covers every quantity Annex 7 names.
QUANTITIES = ("hrr_mw", "ceiling_temp_c", "smoke_layer_temp_d15_c", "smoke_layer_temp_d100_c")

GCI_FS = 1.25                     # Celik et al.'s recommended fine-grid safety factor
FIXED_POINT_TOL = 1e-6
FIXED_POINT_MAX_ITER = 100
POLL_S = 30.0


def run_dir_for(out: Path, chid: str, dx_m: float) -> Path:
    """`<out>/<chid>/dx_<dx:.2f>` -- one directory per grid."""
    return Path(out) / chid / f"dx_{dx_m:.2f}"


def write_decks(design: Design, dx_values: tuple[float, ...], t_end_s: float,
                out: Path) -> list[Path]:
    """One suppressed deck per dx, all under the design's own CHID so the
    three grids of one study sit under a single parent directory. Each dx
    must be one `deck.generate` accepts (it validates tiling); its ValueError,
    naming which dx failed and why, is left to surface as-is.

    `design.json` is written beside every deck too -- the run manager and
    `runner.resume`/`prepare_resume` need it to regenerate a RESTART=.TRUE.
    deck if a grid point is ever paused or interrupted and resumed later.
    """
    chid = deck_mod.chid(design)
    written = []
    for dx_m in dx_values:
        run_dir = run_dir_for(out, chid, dx_m)
        run_dir.mkdir(parents=True, exist_ok=True)
        deck_path = run_dir / "deck.fds"
        deck_path.write_text(deck_mod.generate(design, dx_m=dx_m, t_end_s=t_end_s))
        # by_alias=True -- see fleet.adopt_design for why this must not be the bare
        # field-name dump: Design.load rejects it once a block sets a field with an
        # alias (Fire.fire_class / "class") explicitly.
        (run_dir / DESIGN_NAME).write_text(design.model_dump_json(indent=2, by_alias=True))
        written.append(deck_path)
    return written


def launch_and_wait(design: Design, dx_values: tuple[float, ...], out: Path,
                     t_end_s: float | None = None, poll_s: float = POLL_S) -> None:
    """Launch every grid, one at a time, waiting for each to finish -- three
    CFD runs deep, on one machine's worth of cores.

    Each grid goes through `runner.run_or_resume`: one already `done` is left
    alone, one with restart files left behind is resumed rather than
    restarted from zero, and only a genuinely new grid is launched fresh.
    """
    chid = deck_mod.chid(design)
    for dx_m in dx_values:
        run_dir = run_dir_for(out, chid, dx_m)
        runner_mod.run_or_resume(run_dir / "deck.fds", run_dir, design, t_end_s=t_end_s)
        while runner_mod.status(run_dir)["state"] == "running":
            time.sleep(poll_s)


@dataclass(frozen=True)
class GridPoint:
    dx_m: float
    run_dir: Path
    peaks: dict[str, float | bool] | None = None
    excluded_reason: str | None = None


def read_grids(design: Design, dx_values: tuple[float, ...], out: Path) -> list[GridPoint]:
    """Every grid, read from whatever is finished on disk. Only a run FDS
    reports `done` and that `reader.read` can parse counts; everything else is
    kept with the reason it does not, rather than dropped silently."""
    chid = deck_mod.chid(design)
    points = []
    for dx_m in dx_values:
        run_dir = run_dir_for(out, chid, dx_m)
        status = runner_mod.status(run_dir)
        if status["state"] != "done":
            detail = status.get("detail", "")
            points.append(GridPoint(
                dx_m, run_dir,
                excluded_reason=f"not completed: {status['state']}"
                                + (f" ({detail})" if detail else "")))
            continue
        try:
            result = reader_mod.read(run_dir, design)
        except (KeyError, ValueError, FileNotFoundError, OSError) as exc:
            points.append(GridPoint(dx_m, run_dir, excluded_reason=f"could not be read: {exc}"))
            continue
        points.append(GridPoint(dx_m, run_dir, peaks=result.peaks))
    return points


@dataclass(frozen=True)
class GCIResult:
    quantity: str
    h1: float
    h2: float
    h3: float
    phi1: float
    phi2: float
    phi3: float
    r21: float
    r32: float
    status: str                    # "ok" | "oscillatory" | "non_convergent"
    p: float | None = None
    phi_ext21: float | None = None
    e_a21: float | None = None
    gci_fine21: float | None = None
    detail: str | None = None


def _apparent_order(e21: float, e32: float, r21: float, r32: float) -> tuple[float | None, str]:
    """Celik et al.'s apparent order p, or None with the reason it could not
    be found -- oscillatory convergence (the sign flips between grid pairs)
    or an iteration that never settles on a positive order.

    Fixed-point iteration of p = |ln|e32/e21| + q(p)| / ln(r21),
    q(p) = ln((r21^p - s)/(r32^p - s)), starting from the q=0 estimate.
    """
    if e21 == 0.0 or e32 == 0.0:
        return None, ("one grid pair agrees EXACTLY on this quantity (a zero change); no "
                      "order can be estimated from a zero difference")
    ratio = e32 / e21
    if ratio < 0.0:
        return None, ("oscillatory convergence: the change reverses sign between the "
                      "fine-medium and medium-coarse grid pairs (e32/e21 < 0)")
    s = 1.0
    log_ratio, log_r21 = math.log(abs(ratio)), math.log(r21)
    p = abs(log_ratio) / log_r21
    for _ in range(FIXED_POINT_MAX_ITER):
        if p <= 0.0 or r21 ** p <= s or r32 ** p <= s:
            return None, ("the apparent-order iteration left the domain q(p) is defined "
                          "on (r^p <= s); no order could be estimated")
        q = math.log((r21 ** p - s) / (r32 ** p - s))
        p_next = abs(log_ratio + q) / log_r21
        if abs(p_next - p) < FIXED_POINT_TOL:
            return (p_next, "") if p_next > 0.0 else (
                None, "the iteration converged to a non-positive apparent order")
        p = p_next
    return None, f"the apparent-order iteration did not converge within {FIXED_POINT_MAX_ITER} steps"


def gci(quantity: str, h1: float, h2: float, h3: float,
        phi1: float, phi2: float, phi3: float) -> GCIResult:
    """One quantity's Celik et al. discretisation uncertainty across three
    grids h1 < h2 < h3 (finest to coarsest)."""
    if not h1 < h2 < h3:
        raise ValueError(f"grids must be ordered h1 < h2 < h3 (finest to coarsest); "
                         f"got {h1}, {h2}, {h3}")
    r21, r32 = h2 / h1, h3 / h2
    p, reason = _apparent_order(phi2 - phi1, phi3 - phi2, r21, r32)
    if p is None:
        status = "oscillatory" if "oscillatory" in reason else "non_convergent"
        return GCIResult(quantity, h1, h2, h3, phi1, phi2, phi3, r21, r32, status, detail=reason)
    if phi1 == 0.0:
        return GCIResult(quantity, h1, h2, h3, phi1, phi2, phi3, r21, r32, "non_convergent",
                         p=p, detail="phi1 is zero, so the relative error e_a21 is undefined")
    phi_ext21 = (r21 ** p * phi1 - phi2) / (r21 ** p - 1.0)
    e_a21 = abs((phi1 - phi2) / phi1)
    gci_fine21 = GCI_FS * e_a21 / (r21 ** p - 1.0)
    return GCIResult(quantity, h1, h2, h3, phi1, phi2, phi3, r21, r32, "ok",
                     p, phi_ext21, e_a21, gci_fine21)


def compute_all(points: list[GridPoint]) -> list[GCIResult]:
    """One `GCIResult` per quantity the reader exposed on EVERY usable grid.

    Needs exactly 3 usable (finished and readable) points -- Celik et al.'s
    procedure is a 3-grid one; fewer cannot be assessed by it, and more would
    mean silently picking three out of a larger set, which this refuses to do
    without being told which three.
    """
    usable = sorted((p for p in points if p.peaks is not None), key=lambda p: p.dx_m)
    if len(usable) != 3:
        missing = [p for p in points if p.peaks is None]
        detail = (" (" + "; ".join(f"dx={p.dx_m:g}: {p.excluded_reason}" for p in missing) + ")"
                  if missing else "")
        raise ValueError(
            f"a Celik et al. grid-convergence study needs exactly 3 finished, readable "
            f"grids; {len(usable)} of {len(points)} are usable{detail}")
    h1, h2, h3 = (p.dx_m for p in usable)
    quantities = [q for q in QUANTITIES if all(q in p.peaks for p in usable)]
    return [gci(q, h1, h2, h3, usable[0].peaks[q], usable[1].peaks[q], usable[2].peaks[q])
            for q in quantities]


def render(points: list[GridPoint], t_end_s: float) -> str:
    lines = [
        "# Grid-convergence study", "",
        "Celik, I.B., Ghia, U., Roache, P.J., Freitas, C.J., Coleman, H. and Raad, P.E., "
        "\"Procedure for Estimation and Reporting of Uncertainty Due to Discretization in "
        "CFD Applications\", Journal of Fluids Engineering, 130(7), 078001, 2008.", "",
        f"Simulated window: {t_end_s:.0f} s. A grid study need not run the design's full "
        f"discharge duration; every grid below was run to this window.", "",
        "## Grids", "", "| dx (m) | status |", "|---|---|",
    ]
    for p in sorted(points, key=lambda p: p.dx_m):
        lines.append(f"| {p.dx_m:g} | "
                     + ("done" if p.peaks is not None else f"excluded -- {p.excluded_reason}")
                     + " |")
    lines.append("")
    try:
        results = compute_all(points)
    except ValueError as exc:
        lines += [f"**No discretisation uncertainty could be computed.** {exc}", ""]
        return "\n".join(lines)
    lines += [
        "## Discretisation uncertainty (Celik et al. 2008)", "",
        "| quantity | phi1 (fine) | phi2 | phi3 (coarse) | p | GCI_fine21 | phi_ext21 |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in results:
        if r.status == "ok":
            lines.append(f"| {r.quantity} | {r.phi1:.4g} | {r.phi2:.4g} | {r.phi3:.4g} | "
                         f"{r.p:.3g} | {r.gci_fine21:.1%} | {r.phi_ext21:.4g} |")
        else:
            lines.append(f"| {r.quantity} | {r.phi1:.4g} | {r.phi2:.4g} | {r.phi3:.4g} | "
                         f"{r.status} -- {r.detail} | — | — |")
    lines.append("")
    return "\n".join(lines)


def to_json(points: list[GridPoint], t_end_s: float) -> dict:
    payload: dict = {
        "t_end_s": t_end_s,
        "grids": [{"dx_m": p.dx_m, "included": p.peaks is not None,
                   "excluded_reason": p.excluded_reason}
                  for p in sorted(points, key=lambda p: p.dx_m)],
    }
    try:
        payload["results"] = [asdict(r) for r in compute_all(points)]
    except ValueError as exc:
        payload["results"] = []
        payload["error"] = str(exc)
    return payload

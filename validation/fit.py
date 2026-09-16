"""Least-squares fit of the engine's empirical constants against the anchors.

Only the constants named in `FITTED_KEYS` move. Everything else in
calibration.json -- the constants taken from published correlations, and the two
that pair with a fitted one -- is left exactly as it was, so a reader can tell
what was fitted from what was read off the literature.

A fit is only meaningful once the model's STRUCTURE is right. Fitting against a
structurally inadequate model drives the constants to extreme values to cover
the inadequacy, and they then look calibrated. `run` therefore reports which
constants finished resting on a bound: a pinned constant means the anchors
wanted something the model cannot supply, and that is a finding about the model
rather than a successful calibration.

`least_squares` is given `x_scale="jac"` because the fitted constants span eight
orders of magnitude -- `evaporation_k_ref_m2s` is bounded in [1e-8, 1e-6] while
`suppression_response_s` is bounded in [20, 300] -- and an unscaled trust region
would pin the small ones against a bound on the first step regardless of what
the data wanted.
"""
from __future__ import annotations

import json
import time
from collections.abc import Sequence
from dataclasses import dataclass

from scipy.optimize import least_squares

from solit2.schema.presets import PRESET_DIR, load_calibration, reload_calibration
from validation import compare

CALIBRATION_PATH = PRESET_DIR / "calibration.json"

# (group, constant, lower bound, upper bound).
FITTED_KEYS = (
    ("mist", "eta_max", 0.50, 0.98),
    ("mist", "w_ref_mm_min", 0.30, 8.00),
    ("mist", "chi_cool_max", 0.10, 0.70),
    ("mist", "evaporation_k_ref_m2s", 1.0e-8, 1.0e-6),
    ("mist", "flank_reach_factor", 0.10, 2.00),
    ("mist", "flank_efficiency", 0.05, 1.00),
    ("fire", "suppression_response_s", 20.0, 300.0),
    ("fire", "cover_shielding_factor", 1.0, 6.0),
    ("fire", "pool_ventilation_factor", 0.8, 2.5),
    ("fire", "pool_burning_rate_reduction", 0.1, 0.9),
    ("fire", "pool_extinction_flux_mm_min", 0.5, 5.0),
    ("ventilation", "throttling_coefficient", 0.0, 1.0),
    # One order of magnitude either side of the 0.05 starting value,
    # symmetric in log space (0.05/0.005 == 0.50/0.05 == 10).
    ("mist", "shielding_reference_loading_kgm3", 0.005, 0.50),
    ("thermal", "ceiling_excess_coefficient", 0.3, 2.0),
    # C_f, the multiplier on the flame that cannot rise into the headroom and is
    # deflected downstream instead. It decides whether the Annex 7 section 7.2.1
    # target is in flame contact, and so whether the standard's one absolute
    # criterion can ever pass; at its former fixed 4.3 a 10 m mock-up threw a
    # 34 m horizontal flame at 32 MW and the criterion failed everywhere. The
    # range spans a tip from half the unclipped excess to five times it.
)

# Relative finite-difference step for the numerical Jacobian.
DIFF_STEP = 0.05
# How close to a bound counts as resting on it, as a fraction of the bound span.
PINNED_FRACTION = 1e-3


@dataclass(frozen=True)
class FitOutcome:
    cost_before: float
    cost_after: float
    fitted: dict[str, float]
    pinned: tuple[str, ...]
    nfev: int
    njev: int
    residual_calls: int
    seconds: float
    message: str


def current_vector() -> list[float]:
    """The present value of every fitted constant, in `FITTED_KEYS` order."""
    calibration = load_calibration()
    return [calibration[group][name]["value"] for group, name, _, _ in FITTED_KEYS]


def _validated(values: Sequence[float]) -> list[float]:
    """Every value checked before any of them is written."""
    if len(values) != len(FITTED_KEYS):
        raise ValueError(
            f"expected {len(FITTED_KEYS)} values, one per fitted constant, got {len(values)}"
        )
    out = []
    for value, (group, name, low, high) in zip(values, FITTED_KEYS):
        number = float(value)
        if not low <= number <= high:
            raise ValueError(
                f"{group}.{name}={number} is outside its fitted bounds [{low}, {high}]"
            )
        out.append(number)
    return out


def _dump(calibration: dict) -> str:
    """Serialise one constant per line, the layout calibration.json already uses.

    Reformatting the whole file would bury what a fit actually moved in a diff
    that rewrites every line, and seeing which constants moved is the point.
    """
    groups = []
    for group, entries in calibration.items():
        lines = [f"    {json.dumps(key)}: {json.dumps(value)}"
                 for key, value in entries.items()]
        groups.append(f"  {json.dumps(group)}: {{\n" + ",\n".join(lines) + "\n  }")
    return "{\n" + ",\n".join(groups) + "\n}\n"


def apply_vector(values: Sequence[float]) -> None:
    """Write the vector to calibration.json and drop the memoised copy.

    The physics modules read their constants through `load_calibration`, which
    is memoised, so a fit that wrote the file without clearing that cache would
    move nothing and every residual would come back identical.
    """
    checked = _validated(values)
    calibration = json.loads(CALIBRATION_PATH.read_text())
    for value, (group, name, _, _) in zip(checked, FITTED_KEYS):
        calibration[group][name]["value"] = value
    CALIBRATION_PATH.write_text(_dump(calibration))
    reload_calibration()


def cost(residuals: Sequence[float]) -> float:
    """The objective `least_squares` minimises: half the sum of squares."""
    return 0.5 * sum(r * r for r in residuals)


def _pinned(values: Sequence[float]) -> tuple[str, ...]:
    """Constants that finished resting on a bound.

    Not a success: it means the reference cases wanted a value outside the range
    the model's structure allows, and the fit spent the constant trying to cover
    something the structure cannot supply.
    """
    out = []
    for value, (group, name, low, high) in zip(values, FITTED_KEYS):
        margin = PINNED_FRACTION * (high - low)
        if value - low <= margin:
            out.append(f"{group}.{name} = {value:.6g} at its LOWER bound {low:g}")
        elif high - value <= margin:
            out.append(f"{group}.{name} = {value:.6g} at its UPPER bound {high:g}")
    return tuple(out)


def run(max_nfev: int, anchors: tuple[compare.Anchor, ...] | None = None) -> FitOutcome:
    """Fit the constants in `FITTED_KEYS` against the anchors.

    `max_nfev` bounds the run: the numerical Jacobian costs one residual call
    per fitted constant on top of each trial point, so the total is roughly
    `max_nfev * (1 + len(FITTED_KEYS))` calls. Time one `compare.residuals` call
    and choose `max_nfev` to fit the budget rather than letting it run unbounded.
    """
    anchors = anchors if anchors is not None else compare.load_anchors()
    start_vector = current_vector()
    lower = [low for _, _, low, _ in FITTED_KEYS]
    upper = [high for _, _, _, high in FITTED_KEYS]
    calls = [0]

    def residual(vector):
        calls[0] += 1
        apply_vector(vector)
        return compare.residuals(anchors)

    started = time.perf_counter()
    cost_before = cost(residual(start_vector))
    solution = least_squares(residual, start_vector, bounds=(lower, upper),
                             diff_step=DIFF_STEP, max_nfev=max_nfev, x_scale="jac")
    apply_vector(solution.x)
    elapsed = time.perf_counter() - started

    fitted = {f"{group}.{name}": float(value)
              for value, (group, name, _, _) in zip(solution.x, FITTED_KEYS)}
    return FitOutcome(
        cost_before=cost_before,
        cost_after=float(solution.cost),
        fitted=fitted,
        pinned=_pinned(solution.x),
        nfev=int(solution.nfev),
        njev=int(solution.njev or 0),
        residual_calls=calls[0],
        seconds=elapsed,
        message=str(solution.message),
    )


def _main() -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="validation.fit",
        description="fit the engine's empirical constants against the anchor fire tests")
    parser.add_argument("--max-nfev", type=int, required=True,
                        help="evaluation budget; choose it from a timed residuals call")
    parser.add_argument("--anchor", action="append",
                        help="restrict the fit to these anchor ids")
    args = parser.parse_args()

    anchors = compare.load_anchors(tuple(args.anchor)) if args.anchor else None
    outcome = run(args.max_nfev, anchors)

    print(f"cost before      {outcome.cost_before:.6f}")
    print(f"cost after       {outcome.cost_after:.6f}")
    print(f"nfev {outcome.nfev}  njev {outcome.njev}  "
          f"residual calls {outcome.residual_calls}  {outcome.seconds:.1f} s")
    print(f"termination      {outcome.message}")
    print("\nfitted values")
    for name, value in outcome.fitted.items():
        print(f"  {name:<40} {value:.6g}")
    print("\npinned against a bound"
          if outcome.pinned else "\nno constant finished resting on a bound")
    for line in outcome.pinned:
        print(f"  {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())

"""Hard gates first, then a weighted objective over the things we want to minimise.

A design that fails any hard gate scores zero, but every component is still
reported so the optimiser can see how far off it is and in which direction.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from solit2.schema.result import Criterion

WEIGHTS = {"water": 0.30, "margin": 0.30, "cost": 0.20, "structural": 0.20}
# Mistelix DBR Rev 0 three-zone demand, the reference for the water component.
BASELINE_FLOW_LPM = 2174.3
SCORE_CLIP = 1.5
CEILING_TEMP_CAP_C = 1350.0
DENSITY_HEADROOM_MM_MIN = 3.8
DENSITY_PENALTY = 1.0
BACKLAYERING_PENALTY = 1.0
BACKLAYERING_TOLERANCE_S = 120.0


@dataclass(frozen=True)
class Score:
    total: float
    gates_passed: bool
    gates_failed: list[str]
    components: dict[str, float]
    penalties: list[str] = field(default_factory=list)


def _clipped_ratio(reference: float, actual: float) -> float:
    if actual <= 0:
        return 1.0
    return min(reference / actual, SCORE_CLIP) / SCORE_CLIP


def compute(criteria: dict[str, Criterion], hyd, cost, trace,
            peak_lining_c: float) -> Score:
    failed = [cid for cid, c in criteria.items() if c.hard and not c.passed]
    hard_margins = [c.margin for c in criteria.values() if c.hard]

    components = {
        "water": _clipped_ratio(BASELINE_FLOW_LPM, hyd.flow_lpm),
        "margin": sum(hard_margins) / len(hard_margins) if hard_margins else 0.0,
        "cost": _clipped_ratio(1.0, cost.index),
        "structural": max(1.0 - peak_lining_c / CEILING_TEMP_CAP_C, 0.0),
    }

    penalties: list[str] = []
    deductions = 0.0
    if hyd.density_mm_min > DENSITY_HEADROOM_MM_MIN:
        penalties.append(
            f"density {hyd.density_mm_min:.2f} mm/min exceeds the {DENSITY_HEADROOM_MM_MIN} "
            f"mm/min pump-power headroom"
        )
        deductions += DENSITY_PENALTY

    activated = trace.events.get("t_full_pressure_s") if trace.events else None
    if activated is not None:
        persistent = [s for s in trace.steps
                      if s.t_s >= activated and s.u_eff_ms < s.u_critical_ms]
        if len(persistent) > BACKLAYERING_TOLERANCE_S:
            penalties.append(
                f"airflow stays below the critical velocity for {len(persistent):.0f} s "
                f"after activation"
            )
            deductions += BACKLAYERING_PENALTY

    if failed:
        return Score(0.0, False, failed, components, penalties)

    total = 10.0 * sum(WEIGHTS[k] * components[k] for k in WEIGHTS) - deductions
    return Score(max(total, 0.0), True, [], components, penalties)

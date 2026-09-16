"""Hard gates first, then a weighted objective over the things we want to minimise.

A design that fails any hard gate scores zero, but every component is still
reported so the optimiser can see how far off it is and in which direction.

Penalties deduct from the total without zeroing it, so they are neither gates
nor acceptance criteria. The density penalty keys off the user's OWN declared
`constraints.max_application_density_mm_min`; an undeclared limit is not a
limit and earns no penalty at any density.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from solit2.schema.result import Criterion

WEIGHTS = {"water": 0.30, "margin": 0.30, "cost": 0.20, "structural": 0.20}
# Reference three-zone water demand the `water` component is scored against. A
# fixed normalisation constant inherited from the worked example, not a target
# and not a limit: it sets the scale of the score, never whether a design passes.
BASELINE_FLOW_LPM = 2174.3
SCORE_CLIP = 1.5
CEILING_TEMP_CAP_C = 1350.0
# How much a breach of the user's declared density limit deducts. A scoring
# choice -- how heavily the score weighs a breach -- and deliberately not a
# threshold: the threshold is the user's own number and has no default.
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
    # Criteria whose limit the authority having jurisdiction has not set
    # (SOLIT2 Annex 7 section 7.1). A design that passes only because nobody has
    # set a limit is not a passing design, it is an unassessed one, and this
    # list is what keeps `gates_passed` from being read as approval.
    criteria_unset: list[str] = field(default_factory=list)


def _clipped_ratio(reference: float, actual: float) -> float:
    if actual <= 0:
        return 1.0
    return min(reference / actual, SCORE_CLIP) / SCORE_CLIP


def compute(criteria: dict[str, Criterion], hyd, cost, trace,
            peak_lining_c: float,
            density_limit_mm_min: float | None = None) -> Score:
    """`density_limit_mm_min` is the user's `constraints.max_application_density_mm_min`.

    It defaults to `None` for the same reason the schema field does: until the
    user declares a limit there is no limit to breach, so no penalty applies.
    """
    failed = [cid for cid, c in criteria.items() if c.hard and not c.passed]
    unset = [cid for cid, c in criteria.items() if c.status == "unset"]
    # An unset limit has no margin to average -- its 0.0 is an absence, not a
    # thin pass -- so it is excluded rather than allowed to drag the component
    # down and make an unassessed design look like a marginal one.
    hard_margins = [c.margin for c in criteria.values()
                    if c.hard and c.status != "unset"]

    components = {
        "water": _clipped_ratio(BASELINE_FLOW_LPM, hyd.flow_lpm),
        "margin": sum(hard_margins) / len(hard_margins) if hard_margins else 0.0,
        "cost": _clipped_ratio(1.0, cost.index),
        "structural": max(1.0 - peak_lining_c / CEILING_TEMP_CAP_C, 0.0),
    }

    penalties: list[str] = []
    deductions = 0.0
    if density_limit_mm_min is not None and hyd.density_mm_min > density_limit_mm_min:
        penalties.append(
            f"density {hyd.density_mm_min:.2f} mm/min exceeds the declared limit "
            f"of {density_limit_mm_min:g} mm/min"
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
        return Score(0.0, False, failed, components, penalties, unset)

    total = 10.0 * sum(WEIGHTS[k] * components[k] for k in WEIGHTS) - deductions
    return Score(max(total, 0.0), True, [], components, penalties, unset)

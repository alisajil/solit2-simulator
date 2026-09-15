"""Criterion definitions and their evaluation against a completed run.

The governing source is SOLIT2 Engineering Guidance Annex 7 section 7, "Minimum
acceptance criteria", whose own opening statement is that it "gives some guidance
for selecting minimum acceptance requirements but do[es] not specify in detail
absolute values", and that "the detailed acceptance criteria shall be defined by
authorities having jurisdiction based on the risk analysis of every individual
tunnel".

So Annex 7 mandates exactly one absolute rule -- section 7.2.1, that the target
must not ignite -- and four CATEGORIES of criteria whose numbers belong to the
authority having jurisdiction. Every limit below is therefore read off
`design.ahj` and reported as unset until an authority sets it.

Nothing else belongs here. A limit that comes from a project's electrical
supply or a manufacturer's design margin is not an acceptance criterion, and
putting one in this table would let a local circumstance be reported as a
SOLIT2 failure. Those live in `design.constraints` and are evaluated by
`solit2.engines.reduced.constraints` into their own block of the result.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from solit2.engines.reduced.cost import CostResult
from solit2.engines.reduced.hydraulics import HydraulicsResult
from solit2.engines.reduced.state import RunTrace
from solit2.schema.design import Design
from solit2.schema.result import Criterion

# Station chainage relative to the fire centre; negative is upstream. Annex 7
# section 7.2.2 asks for life safety upstream AND downstream, so the life-safety
# criteria below take their worst value across all of these, not upstream only.
STATIONS = {"U35": -35.0, "U15": -15.0, "U5": -5.0,
            "D5": 5.0, "D15": 15.0, "D20": 20.0, "D35": 35.0, "D100": 100.0}
BREATHING_HEIGHT_M = 1.8
# Piloted ignition of wood, Babrauskas; the flux the target must stay under.
WOOD_PILOTED_IGNITION_KWM2 = 12.5
# Sustained exposure needed before piloted ignition is predicted.
IGNITION_EXPOSURE_S = 60.0
# A gauge the flame has reached is not reading a view factor any more, so a
# target at this flux is in flame contact and has ignited without waiting out
# the exposure clock. `sim` clamps the target flux to this on flame contact.
FLAME_CONTACT_FLUX_KWM2 = 50.0
DEFAULT_STEP_INTERVAL_S = 1.0


@dataclass(frozen=True)
class CriterionSpec:
    """One acceptance criterion.

    `limit` is a function of the design rather than a constant because Annex 7
    section 7.1 defers the absolute values to the authority having jurisdiction:
    most of them resolve to a `design.ahj` field that is `None` until set.
    """
    id: str
    limit: Callable[[Design], float | tuple[float, float] | None]
    op: str
    hard: bool
    extract: Callable[[RunTrace, HydraulicsResult, CostResult, Design], float | bool]


def _peak_after_activation(trace: RunTrace, attribute: str) -> float:
    """Peak once the system is at full pressure.

    Annex 7 section 7.4 requires the system's response delay after triggering to
    be accounted for when judging when target values are achieved; the pre-
    activation fire is not what the system is being assessed on.
    """
    steps = trace.after(trace.events.get("t_full_pressure_s") or 0.0)
    if not steps:
        steps = trace.steps
    return max(getattr(s, attribute) for s in steps)


def _worst_station_value(trace: RunTrace, field: str, worst) -> float:
    """The worst value of `field` over every station and every step.

    `worst` is `max` or `min`. Annex 7 section 7.2.2 asks for the life-safety
    quantities upstream and downstream both, so every station counts.
    """
    return worst(worst(getattr(sample, field) for sample in step.stations.values())
                 for step in trace.steps)


def _step_interval_s(trace: RunTrace) -> float:
    if len(trace.steps) < 2:
        return DEFAULT_STEP_INTERVAL_S
    return trace.steps[1].t_s - trace.steps[0].t_s


def _target_ignited(trace: RunTrace) -> bool:
    """Annex 7 section 7.2.1: did fire spread reach the target 5 m downstream.

    A test observes this; a simulation predicts it. The target counts as ignited
    on flame contact, or on sustained exposure above the piloted-ignition flux --
    the second being a duration rule, not a peak rule, so a flux that crosses the
    threshold briefly and repeatedly is not ignition.
    """
    return any(step.target_flux_kwm2 >= FLAME_CONTACT_FLUX_KWM2
               or step.target_exposure_s >= IGNITION_EXPOSURE_S
               for step in trace.steps)


def _structure_exposure_duration_s(trace: RunTrace) -> float:
    """Total time for which any length of ceiling was above the AHJ threshold."""
    interval = _step_interval_s(trace)
    return sum(interval for s in trace.steps if s.structure_exposure_length_m > 0.0)


DEFAULT_CRITERIA: tuple[CriterionSpec, ...] = (
    # 7.2.1 -- the one absolute rule. "Prevention of fire spread is essential in
    # every case and fire target shall not have ignited during the test. FFFS has
    # failed if fire spread has spread to the target 5 m downstream behind the
    # mock-up." Mandated outright, so it carries no limit and no AHJ dependency.
    CriterionSpec("target_ignited", lambda d: None, "is_false", True,
                  lambda t, h, c, d: _target_ignited(t)),
    # 7.3.1 Class B -- "if the ventilation system is designed for certain
    # unsuppressed fire size, FFFS shall be able to suppress increased design
    # fire under this size". The suppression target is the tunnel's own
    # ventilation design fire size, which only the AHJ can name.
    CriterionSpec("hrr_below_tvs_design_mw", lambda d: d.ahj.tvs_design_fire_mw,
                  "<=", True, lambda t, h, c, d: _peak_after_activation(t, "hrr_mw")),
    # 7.2.2 life safety -- temperature, heat radiation, visibility and gas
    # concentrations, upstream AND downstream, with CO called out specially.
    # Every limit is the AHJ's to set.
    CriterionSpec("max_air_temp_c", lambda d: d.ahj.max_air_temp_c, "<=", True,
                  lambda t, h, c, d: _worst_station_value(t, "temp_c", max)),
    CriterionSpec("max_heat_flux_kwm2", lambda d: d.ahj.max_heat_flux_kwm2, "<=", True,
                  lambda t, h, c, d: _worst_station_value(t, "flux_kwm2", max)),
    CriterionSpec("min_visibility_m", lambda d: d.ahj.min_visibility_m, ">=", True,
                  lambda t, h, c, d: _worst_station_value(t, "visibility_m", min)),
    CriterionSpec("max_fed", lambda d: d.ahj.max_fed, "<=", True,
                  lambda t, h, c, d: _worst_station_value(t, "fed_tox", max)),
    CriterionSpec("max_co_ppm", lambda d: d.ahj.max_co_ppm, "<=", True,
                  lambda t, h, c, d: _worst_station_value(t, "co_ppm", max)),
    # 7.2.4 tunnel structure -- "the minimum criterion is that high temperature
    # exposure areas will be limited to a small area, directly above fire loads
    # or slightly downstream", and ">500 C are allowed if exposure time is short
    # and area is small". So: how long a run of tunnel, and for how long. Both
    # absolute limits are the AHJ's.
    CriterionSpec("structure_exposure_length_m",
                  lambda d: d.ahj.max_structure_exposure_length_m, "<=", True,
                  lambda t, h, c, d: max(s.structure_exposure_length_m for s in t.steps)),
    CriterionSpec("structure_exposure_duration_s",
                  lambda d: d.ahj.max_structure_exposure_duration_s, "<=", True,
                  lambda t, h, c, d: _structure_exposure_duration_s(t)),
)


def evaluate(trace: RunTrace, hyd: HydraulicsResult, cost: CostResult,
             design: Design) -> dict[str, Criterion]:
    """Apply every criterion, letting `design.criteria` override limits and hardness."""
    out: dict[str, Criterion] = {}
    for spec in DEFAULT_CRITERIA:
        override = design.criteria.get(spec.id, {})
        # `in` rather than `.get`, so a design can deliberately override a limit
        # back to None ("the authority has not ruled on this after all").
        limit = override["limit"] if "limit" in override else spec.limit(design)
        if isinstance(limit, list):
            limit = tuple(limit)
        out[spec.id] = Criterion.build(
            value=spec.extract(trace, hyd, cost, design),
            limit=limit,
            op=override.get("op", spec.op),
            hard=override.get("hard", spec.hard),
        )
    return out

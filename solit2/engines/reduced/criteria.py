"""Criterion definitions and their evaluation against a completed run.

Hard criteria come from the tender (`HPWM-TECHNICAL SPEC_R2` sections 5 and 6)
and from the SOLIT2/APPLUS+TST performance criteria. Soft criteria are reported
but do not reject a design.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from solit2.engines.reduced.cost import CostResult
from solit2.engines.reduced.hydraulics import HydraulicsResult
from solit2.engines.reduced.state import RunTrace
from solit2.schema.design import Design
from solit2.schema.result import Criterion

# Station chainage relative to the fire centre; negative is upstream.
STATIONS = {"U35": -35.0, "U15": -15.0, "U5": -5.0,
            "D5": 5.0, "D15": 15.0, "D20": 20.0, "D35": 35.0, "D100": 100.0}
BREATHING_HEIGHT_M = 1.8
# Piloted ignition of wood; the downstream target must stay below this.
WOOD_PILOTED_IGNITION_KWM2 = 12.5
NO_EXTINCTION_SENTINEL_S = 1e9


@dataclass(frozen=True)
class CriterionSpec:
    id: str
    limit: float | tuple[float, float]
    op: str
    hard: bool
    extract: Callable[[RunTrace, HydraulicsResult, CostResult, Design], float]


def _peak_after_activation(trace: RunTrace, attribute: str) -> float:
    steps = trace.after(trace.events.get("t_full_pressure_s", 0.0))
    if not steps:
        steps = trace.steps
    return max(getattr(s, attribute) for s in steps)


def _station_peak(trace: RunTrace, station: str, field: str) -> float:
    return max(getattr(s.stations[station], field) for s in trace.steps)


def _station_min(trace: RunTrace, station: str, field: str) -> float:
    return min(getattr(s.stations[station], field) for s in trace.steps)


def _station_final(trace: RunTrace, station: str, field: str) -> float:
    return getattr(trace.steps[-1].stations[station], field)


DEFAULT_CRITERIA: tuple[CriterionSpec, ...] = (
    CriterionSpec("hrr_control_mw", 50.0, "<=", True,
                  lambda t, h, c, d: _peak_after_activation(t, "hrr_mw")),
    CriterionSpec("power_kw", 650.0, "<=", True, lambda t, h, c, d: h.power_kw),
    CriterionSpec("target_hf_kwm2", WOOD_PILOTED_IGNITION_KWM2, "<=", True,
                  lambda t, h, c, d: _peak_after_activation(t, "target_flux_kwm2")),
    CriterionSpec("remote_nozzle_bar", (45.0, 60.0), "in", True,
                  lambda t, h, c, d: d.nozzles.pressure_bar),
    CriterionSpec("u35_temp_c", 60.0, "<=", True,
                  lambda t, h, c, d: _station_peak(t, "U35", "temp_c")),
    CriterionSpec("hf_u15_kwm2", 5.0, "<=", True,
                  lambda t, h, c, d: _station_peak(t, "U15", "flux_kwm2")),
    CriterionSpec("hf_u35_kwm2", 2.5, "<=", True,
                  lambda t, h, c, d: _station_peak(t, "U35", "flux_kwm2")),
    CriterionSpec("visibility_u35_m", 10.0, ">=", True,
                  lambda t, h, c, d: _station_min(t, "U35", "visibility_m")),
    CriterionSpec("fed_d35", 0.3, "<=", True,
                  lambda t, h, c, d: _station_final(t, "D35", "fed_tox")),
    CriterionSpec("ff_u5_hf_kwm2", 5.0, "<=", False,
                  lambda t, h, c, d: _station_peak(t, "U5", "flux_kwm2")),
    CriterionSpec("ff_d20_temp_c", 60.0, "<=", False,
                  lambda t, h, c, d: _station_peak(t, "D20", "temp_c")),
    CriterionSpec("density_mm_min", 3.8, "<=", False,
                  lambda t, h, c, d: h.density_mm_min),
    CriterionSpec("pools_extinguished_s", 600.0, "<=", False,
                  lambda t, h, c, d: t.events.get("pools_extinguished_at_s")
                  or (0.0 if d.fire.fire_class == "A" else NO_EXTINCTION_SENTINEL_S)),
)


def evaluate(trace: RunTrace, hyd: HydraulicsResult, cost: CostResult,
             design: Design) -> dict[str, Criterion]:
    """Apply every criterion, letting `design.criteria` override limits and hardness."""
    out: dict[str, Criterion] = {}
    for spec in DEFAULT_CRITERIA:
        override = design.criteria.get(spec.id, {})
        limit = override.get("limit", spec.limit)
        if isinstance(limit, list):
            limit = tuple(limit)
        out[spec.id] = Criterion.build(
            value=spec.extract(trace, hyd, cost, design),
            limit=limit,
            op=override.get("op", spec.op),
            hard=override.get("hard", spec.hard),
        )
    return out

"""Run the section x velocity grid and keep the worst case per criterion."""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone

from solit2.engines.reduced import criteria as criteria_mod
from solit2.engines.reduced import score as score_mod
from solit2.engines.reduced import sim
from solit2.engines.reduced.cost import CostResult, cost_index
from solit2.engines.reduced.geometry import section_geometry
from solit2.engines.reduced.hydraulics import HydraulicsResult, size_system
from solit2.engines.reduced.state import RunTrace, StepRecord
from solit2.schema.design import Design
from solit2.schema.result import Criterion, Result

ENGINE = "reduced"
ENGINE_VERSION = "reduced-1.0.0"
CRITICAL_VELOCITY_WARNING_MARGIN = 0.10
TIMESERIES_STRIDE_S = 10
DESIGN_SHA_CHARS = 12


@dataclass(frozen=True)
class _Case:
    """One completed run of the grid and everything scored off it."""
    trace: RunTrace
    hydraulics: HydraulicsResult
    cost: CostResult
    criteria: dict[str, Criterion]


def _velocities(design: Design) -> tuple[float, ...]:
    if design.ventilation.velocity_ms is not None:
        return (design.ventilation.velocity_ms,)
    low, high = design.ventilation.velocity_range_ms
    return (low,) if low == high else (low, high)


def _evaluate_case(design: Design, section: str, velocity_ms: float) -> _Case:
    trace = sim.run_once(design, section, velocity_ms)
    scoped = design.model_copy(update={"tunnel": design.tunnel.model_copy(
        update={"section": section})})
    geom = section_geometry(scoped)
    hyd = size_system(scoped, geom)
    cost = cost_index(scoped, hyd)
    return _Case(trace, hyd, cost, criteria_mod.evaluate(trace, hyd, cost, scoped))


def _worst_per_criterion(cases: list[_Case]) -> dict[str, Criterion]:
    return {cid: min((case.criteria[cid] for case in cases), key=lambda c: c.margin)
            for cid in cases[0].criteria}


def _worst_case(cases: list[_Case]) -> _Case:
    """The run that owns the thinnest hard margin; its trace is the one reported."""
    return min(cases, key=lambda case: min(c.margin for c in case.criteria.values() if c.hard))


def _critical_velocity_warnings(trace: RunTrace) -> list[str]:
    thin = [s for s in trace.steps
            if s.u_critical_ms > 0
            and (s.u_eff_ms - s.u_critical_ms) / s.u_critical_ms < CRITICAL_VELOCITY_WARNING_MARGIN]
    if not thin:
        return []
    worst = min(thin, key=lambda s: s.u_eff_ms - s.u_critical_ms)
    return [
        f"airflow {worst.u_eff_ms:.2f} m/s is within "
        f"{CRITICAL_VELOCITY_WARNING_MARGIN:.0%} of the critical velocity "
        f"{worst.u_critical_ms:.2f} m/s at t={worst.t_s:.0f} s"
    ]


def _peaks(trace: RunTrace, peak_lining_c: float) -> dict[str, float]:
    return {"hrr_mw": max(s.hrr_mw for s in trace.steps),
            "hrr_free_burn_mw": max(s.hrr_free_mw for s in trace.steps),
            "ceiling_temp_c": max(s.ceiling_temp_c for s in trace.steps),
            "lining_temp_c": peak_lining_c,
            "pipe_surface_temp_c": max(s.pipe_temp_c for s in trace.steps),
            "smoke_layer_temp_d15_c": max(s.stations["D15"].temp_c for s in trace.steps)}


def _timeseries(sampled: tuple[StepRecord, ...]) -> dict[str, list[float]]:
    return {
        "t_s": [s.t_s for s in sampled],
        "hrr_mw": [s.hrr_mw for s in sampled],
        "ceiling_temp_c": [s.ceiling_temp_c for s in sampled],
        "u35_temp_c": [s.stations["U35"].temp_c for s in sampled],
        "d15_temp_c": [s.stations["D15"].temp_c for s in sampled],
        "hf_u15_kwm2": [s.stations["U15"].flux_kwm2 for s in sampled],
        "fed_d35": [s.stations["D35"].fed_tox for s in sampled],
        "backlayering_m": [s.backlayer_m for s in sampled],
        "velocity_ms": [s.u_eff_ms for s in sampled],
        "water_lpm": [s.water_lpm for s in sampled],
    }


def _design_sha(design: Design) -> str:
    payload = json.dumps(design.model_dump(mode="json"), sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:DESIGN_SHA_CHARS]


def run(design: Design, sections: tuple[str, ...] | None = None,
        velocities: tuple[float, ...] | None = None) -> Result:
    started = time.perf_counter()
    sections = sections or (design.tunnel.section,)
    velocities = velocities or _velocities(design)

    cases = [_evaluate_case(design, section, velocity)
             for section in sections for velocity in velocities]

    merged = _worst_per_criterion(cases)
    worst = _worst_case(cases)
    trace, hyd, cost = worst.trace, worst.hydraulics, worst.cost

    peak_lining = max(s.lining_temp_c for s in trace.steps)
    scored = score_mod.compute(merged, hyd, cost, trace, peak_lining)
    warnings = _critical_velocity_warnings(trace) + list(scored.penalties)
    final_mist = max(trace.steps, key=lambda s: s.mist.w_fuel_mm_min).mist

    return Result(
        meta={"design_name": design.meta.name, "design_sha": _design_sha(design),
              "engine": ENGINE, "engine_version": ENGINE_VERSION,
              "runtime_s": round(time.perf_counter() - started, 3),
              "timestamp": datetime.now(timezone.utc).isoformat()},
        envelope=[{"section": case.trace.section, "velocity_ms": case.trace.velocity_ms}
                  for case in cases],
        worst_case={"section": trace.section, "velocity_ms": trace.velocity_ms},
        events=trace.events,
        criteria=merged,
        peaks=_peaks(trace, peak_lining),
        mist={"w_fuel_mm_min": final_mist.w_fuel_mm_min, "f_cov": final_mist.f_cov,
              "chi_cool": final_mist.chi_cool, "tau_mist": final_mist.tau_mist},
        hydraulics=hyd.__dict__,
        cost=cost.__dict__,
        score={"total": scored.total, "gates_passed": scored.gates_passed,
               "gates_failed": scored.gates_failed, "components": scored.components,
               "penalties": scored.penalties},
        timeseries=_timeseries(trace.steps[::TIMESERIES_STRIDE_S]),
        warnings=warnings,
    )

"""Run the section x velocity grid and keep the worst case per criterion."""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

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


def _case_id(trace: RunTrace) -> dict[str, Any]:
    """How a run is named in the envelope, the worst case and a criterion's provenance."""
    return {"section": trace.section, "velocity_ms": trace.velocity_ms}


def _severity(criterion: Criterion) -> tuple[float, float]:
    """Sort key putting the worst case first, for `min`.

    Margin ranks a criterion whose limit is set. An UNSET limit has margin 0.0
    in every case (SOLIT2 Annex 7 section 7.1 leaves the number to the AHJ), so
    the raw value breaks the tie -- otherwise an unset criterion would report
    whichever case happened to be evaluated first rather than the worst one.
    """
    value = float(criterion.value)
    worse_when_larger = criterion.op in ("<=", "is_false")
    return (criterion.margin, -value if worse_when_larger else value)


def _assessed_hard(criteria) -> list[Criterion]:
    """Hard criteria that actually have a limit to be judged against."""
    return [c for c in criteria if c.hard and c.status != "unset"]


def _worst_per_criterion(cases: list[_Case]) -> tuple[dict[str, Criterion],
                                                      dict[str, dict[str, Any]]]:
    """Each criterion's worst value across the envelope, and the case it came from.

    This is a per-criterion selection, so the case behind one criterion need not be
    the case behind another, nor the `worst_case` whose trace is reported in full.
    """
    merged: dict[str, Criterion] = {}
    provenance: dict[str, dict[str, Any]] = {}
    for cid in cases[0].criteria:
        owner = min(cases, key=lambda case: _severity(case.criteria[cid]))
        merged[cid] = owner.criteria[cid]
        provenance[cid] = _case_id(owner.trace)
    return merged, provenance


def _worst_case(cases: list[_Case]) -> _Case:
    """The run that owns the thinnest hard margin; its trace is the one reported.

    Unset criteria are skipped: their margin is 0.0 in every case, so counting
    them would tie every case together and make the selection arbitrary. If the
    AHJ has set nothing at all, the absolutely-mandated criteria still rank.
    """
    def thinnest(case: _Case) -> float:
        assessed = _assessed_hard(case.criteria.values())
        return min(c.margin for c in assessed) if assessed else 0.0

    return min(cases, key=thinnest)


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
            "smoke_layer_temp_d15_c": max(s.stations["D15"].temp_c for s in trace.steps),
            "smoke_layer_temp_d100_c": max(s.stations["D100"].temp_c for s in trace.steps),
            # Non-gating context for `target_ignited`: how hot the target got and
            # the longest unbroken run it spent above the piloted-ignition flux,
            # so a reader can see how close the section 7.2.1 call was.
            "target_peak_flux_kwm2": max(s.target_flux_kwm2 for s in trace.steps),
            "target_max_exposure_s": max(s.target_exposure_s for s in trace.steps),
            "structure_exposure_length_m": max(s.structure_exposure_length_m
                                               for s in trace.steps)}


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

    merged, criteria_cases = _worst_per_criterion(cases)
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
        envelope=[_case_id(case.trace) for case in cases],
        worst_case=_case_id(trace),
        events=trace.events,
        criteria=merged,
        criteria_cases=criteria_cases,
        peaks=_peaks(trace, peak_lining),
        mist={"w_fuel_mm_min": final_mist.w_fuel_mm_min, "f_cov": final_mist.f_cov,
              "chi_cool": final_mist.chi_cool, "tau_mist": final_mist.tau_mist},
        hydraulics=hyd.__dict__,
        cost=cost.__dict__,
        score={"total": scored.total, "gates_passed": scored.gates_passed,
               "gates_failed": scored.gates_failed, "components": scored.components,
               "penalties": scored.penalties,
               "criteria_unset": scored.criteria_unset},
        timeseries=_timeseries(trace.steps[::TIMESERIES_STRIDE_S]),
        warnings=warnings,
    )

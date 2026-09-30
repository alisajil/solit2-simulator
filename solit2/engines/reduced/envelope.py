"""Run the section x velocity grid and keep the worst case per criterion."""
from __future__ import annotations

import hashlib
import json
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from solit2.engines.reduced import constraints as constraints_mod
from solit2.engines.reduced import criteria as criteria_mod
from solit2.engines.reduced import score as score_mod
from solit2.engines.reduced import sim
from solit2.engines.reduced.cost import CostResult, cost_index
from solit2.engines.reduced.geometry import section_geometry
from solit2.engines.reduced.hydraulics import HydraulicsResult, size_system
from solit2.engines.reduced.state import RunTrace, StepRecord
from solit2.schema.design import Design
from solit2.schema.presets import load_calibration
from solit2.schema.result import Criterion, Result

ENGINE = "reduced"
ENGINE_VERSION = "reduced-1.1.0"
CRITICAL_VELOCITY_WARNING_MARGIN = 0.10
TIMESERIES_STRIDE_S = 10
DESIGN_SHA_CHARS = 12
# The name every shipped placeholder preset carries. A result computed from one
# is arithmetic, not an assessment, and has to say so in its own output.
TEMPLATE_PRESET = "template"
NO_ANCHOR = "none"
# Provenance paths are recorded relative to the repository, where designs/ lives.
REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class _Case:
    """One completed run of the grid and everything scored off it."""
    trace: RunTrace
    hydraulics: HydraulicsResult
    cost: CostResult
    criteria: dict[str, Criterion]
    constraints: dict[str, Criterion]


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
    return _Case(trace, hyd, cost,
                 criteria_mod.evaluate(trace, hyd, cost, scoped),
                 constraints_mod.evaluate(hyd, scoped))


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


def _worst_per_id(cases: list[_Case], block: str) -> tuple[dict[str, Criterion],
                                                           dict[str, dict[str, Any]]]:
    """Each entry's worst value across the envelope, and the case it came from.

    `block` is "criteria" or "constraints"; both are judged the same way and
    reported separately. This is a per-entry selection, so the case behind one
    entry need not be the case behind another, nor the `worst_case` whose trace
    is reported in full.
    """
    merged: dict[str, Criterion] = {}
    provenance: dict[str, dict[str, Any]] = {}
    for cid in getattr(cases[0], block):
        owner = min(cases, key=lambda case: _severity(getattr(case, block)[cid]))
        merged[cid] = getattr(owner, block)[cid]
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


def _destratification_warnings(trace: RunTrace, half_active_length_m: float) -> list[str]:
    """Say so when the spray runs over a layer the engine holds stratified AND a
    reported station reads inside the spray zone.

    The spray mixes the smoke layer down toward breathing height; the engine's
    stratification factor never sees it. Visibility and dose at a station inside
    the zone are therefore optimistic. No magnitude is applied: a factor chosen to
    look right would be a fitted barrier term, and the size of the effect has to
    come from a CFD case or measured data. A station outside the zone is not
    reached by the spray, so a design whose zone contains none has nothing to warn
    about.
    """
    in_zone = tuple(name for name, x_m in criteria_mod.STATIONS.items()
                    if abs(x_m) <= half_active_length_m)
    for step in trace.steps:
        if step.mist.kappa_visible_per_m <= 0.0 or step.strat_factor >= 1.0:
            continue
        if any(step.stations[name].visibility_m is not None
               or step.stations[name].fed_tox is not None for name in in_zone):
            return ["mist de-stratification is not modelled: visibility and dose at "
                    "breathing height at stations inside the spray zone may be worse than "
                    "reported"]
    return []


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
        "hrr_free_burn_mw": [s.hrr_free_mw for s in sampled],
        "ceiling_temp_c": [s.ceiling_temp_c for s in sampled],
        # U45 and D45 replace the retired U35/D35: Annex 7 Table 5 has no station
        # at 35 m, and puts the O2/CO2/CO, humidity and visibility instruments
        # that the section 7.2.2 life-safety evidence rests on at U45 and D45.
        # Section 5.2.7 measures the ventilation velocity at U45 as well.
        "u45_temp_c": [s.stations["U45"].temp_c for s in sampled],
        "u15_temp_c": [s.stations["U15"].temp_c for s in sampled],
        "d15_temp_c": [s.stations["D15"].temp_c for s in sampled],
        "d100_temp_c": [s.stations["D100"].temp_c for s in sampled],
        "hf_u15_kwm2": [s.stations["U15"].flux_kwm2 for s in sampled],
        "hf_d15_kwm2": [s.stations["D15"].flux_kwm2 for s in sampled],
        "fed_d45": [s.stations["D45"].fed_tox for s in sampled],
        "backlayering_m": [s.backlayer_m for s in sampled],
        "velocity_ms": [s.u_eff_ms for s in sampled],
        "water_lpm": [s.water_lpm for s in sampled],
    }


def design_sha(design: Design) -> str:
    payload = json.dumps(design.model_dump(mode="json"), sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:DESIGN_SHA_CHARS]


def _placeholder_warnings(design: Design) -> list[str]:
    """Say, in the result itself, that a shipped placeholder is standing in for data."""
    blocks = (("nozzle", design.nozzles.preset),
              ("tunnel", design.tunnel.preset),
              ("hydraulics", design.hydraulics.preset))
    return [
        f"the {name} block uses the shipped placeholder template, not measured "
        f"data; this result is an illustration and not an assessment"
        for name, preset in blocks if preset == TEMPLATE_PRESET
    ]


def _head_count_warnings(design: Design) -> list[str]:
    """A declared head count that its own layout does not support.

    `zones.heads_per_zone`, when set, wins over rows x pitch outright -- see
    `Design.heads_per_zone`. That is deliberate: a real installation's head
    count is a procurement fact, not something to be re-derived. But it means
    changing `mounting.rows` alone moves the spray pattern and leaves flow,
    pump power and tank size costing the old layout, with nothing in the
    result to show for it. Silence there is the tool reporting a system nobody
    specified.

    Not an error and not a penalty. The declared figure still governs; this
    only says the two disagree and by how much.
    """
    declared = design.zones.heads_per_zone
    if declared is None:
        return []
    mount = design.nozzles.mounting
    implied = round(design.zones.section_length_m / (mount.pitch_m / mount.rows))
    if declared == implied:
        return []
    return [
        f"zones.heads_per_zone declares {declared} head(s) per section, but "
        f"{mount.rows} row(s) at {mount.pitch_m:g} m pitch over a "
        f"{design.zones.section_length_m:g} m section implies {implied}. The "
        f"declared figure governs, so flow, pump power and tank size follow "
        f"{declared}, not the layout drawn"
    ]


def _constraint_warnings(constraints: dict[str, Criterion]) -> list[str]:
    """A declared limit that is exceeded. Visible, but never a SOLIT2 gate."""
    return [
        f"user-declared constraint {cid} is breached: {constraints[cid].value:.4g} "
        f"against a declared limit of {constraints[cid].limit:.4g}; this is a "
        f"project constraint, not a SOLIT2 acceptance criterion"
        for cid in constraints_mod.breached(constraints)
    ]


def _calibration_meta() -> dict[str, Any]:
    """What the engine's constants rest on, stated in the engine's own output.

    `fitted` is declared in calibration.json rather than inferred: naming an
    anchor records where a constant came from, which is not the same as having
    run a fit. The anchor list, by contrast, is read back off the entries so it
    cannot drift from what they actually cite.
    """
    calibration = load_calibration()
    declared = calibration.get("provenance", {})
    anchors: set[str] = set()
    for group, entries in calibration.items():
        if group == "provenance":
            continue
        for entry in entries.values():
            cited = str(entry.get("anchor", NO_ANCHOR)).split(",")
            anchors.update(a.strip() for a in cited if a.strip() not in ("", NO_ANCHOR))
    reference = declared.get("fit", {}).get("reference_nozzle", {})
    return {"calibration_fitted": bool(declared.get("fitted", False)),
            "calibration_anchors": sorted(anchors),
            "calibration_note": declared.get("note", ""),
            "calibration_reference_nozzle": reference.get("data_status")}


def calibration_warnings() -> list[str]:
    """Say, in every result, when the constants cannot be shown to rest on measured data.

    Read from the provenance `validation/fit.py` writes, and checked against the
    reference nozzle file itself, so an edit to that file after the fit -- or a
    hand-edited calibration -- shows up in the result instead of passing silently.
    """
    fit = load_calibration().get("provenance", {}).get("fit")
    if not fit:
        return ["calibration: calibration.json records no fit provenance, so this result "
                "cannot state what its constants rest on; refit with validation.fit"]
    reference = fit["reference_nozzle"]
    out = []
    if reference["data_status"] != "measured":
        out.append(
            f"calibration: the fitted constants rest on a reference nozzle declared "
            f"{reference['data_status']!r}, not the SOLIT2 test system's measured nozzle; no "
            f"figure in this result is independent evidence (meta.calibration_note, "
            f"`solit2 validate`)")
    path = REPO_ROOT / reference["path"]
    if not path.exists():
        out.append(f"calibration: {reference['path']}, the reference nozzle the constants "
                   f"were fitted on, is not present, so this result cannot show they match it")
    elif hashlib.sha256(path.read_bytes()).hexdigest() != reference["sha256"]:
        out.append(f"calibration: {reference['path']} has changed since the constants were "
                   f"fitted on it; refit before trusting any figure (uv run python -m "
                   f"validation.fit --reference-nozzle {reference['path']} --max-nfev N)")
    return out


def run(design: Design, sections: tuple[str, ...] | None = None,
        velocities: tuple[float, ...] | None = None) -> Result:
    started = time.perf_counter()
    sections = sections or (design.tunnel.section,)
    velocities = velocities or _velocities(design)

    cases = [_evaluate_case(design, section, velocity)
             for section in sections for velocity in velocities]

    merged, criteria_cases = _worst_per_id(cases, "criteria")
    # Judged alongside the criteria, reported apart from them, and never passed
    # to `score.compute` as criteria -- a local limit must not read as a SOLIT2
    # failure.
    constraints, _ = _worst_per_id(cases, "constraints")
    worst = _worst_case(cases)
    trace, hyd, cost = worst.trace, worst.hydraulics, worst.cost

    peak_lining = max(s.lining_temp_c for s in trace.steps)
    # The declared density limit's VALUE does reach the score, for a penalty.
    # A penalty deducts from the total; only a hard criterion can zero it, so
    # this still cannot turn a local limit into a SOLIT2 failure.
    scored = score_mod.compute(merged, hyd, cost, trace, peak_lining,
                               design.constraints.max_application_density_mm_min)
    warnings = (calibration_warnings()
                + _placeholder_warnings(design)
                + _head_count_warnings(design)
                + _critical_velocity_warnings(trace)
                + _destratification_warnings(trace, design.active_length_m / 2.0)
                + _constraint_warnings(constraints)
                + list(scored.penalties))
    final_mist = max(trace.steps, key=lambda s: s.mist.w_fuel_mm_min).mist

    return Result(
        meta={"design_name": design.meta.name, "design_sha": design_sha(design),
              "engine": ENGINE, "engine_version": ENGINE_VERSION,
              "runtime_s": round(time.perf_counter() - started, 3),
              "timestamp": datetime.now(timezone.utc).isoformat(),
              **_calibration_meta()},
        envelope=[_case_id(case.trace) for case in cases],
        worst_case=_case_id(trace),
        events=trace.events,
        criteria=merged,
        criteria_cases=criteria_cases,
        constraints=constraints,
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

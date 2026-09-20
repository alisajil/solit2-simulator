"""FDS device output -> the same `Result` Tier 1 produces.

The point of this module is that it does NOT re-score anything. It rebuilds the
frozen dataclasses Tier 1's own engine produces (`RunTrace` of `StepRecord` of
`StationSample`) out of what FDS measured, then hands them to Tier 1's
`criteria.evaluate` untouched -- so an FDS result is judged by identical Annex 7
logic and is interchangeable with a Tier 1 result everywhere downstream.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np

from solit2.engines.fds import deck as deck_mod
from solit2.engines.fds import runner as runner_mod
from solit2.engines.reduced.constraints import evaluate as evaluate_constraints
from solit2.engines.reduced.cost import cost_index
from solit2.engines.reduced.criteria import (BREATHING_HEIGHT_M, INSTRUMENTS, STATIONS,
                                             evaluate, thermocouple_heights_m)
from solit2.engines.reduced.geometry import SectionGeometry, section_geometry
from solit2.engines.reduced.hydraulics import size_system
from solit2.engines.reduced.score import compute as compute_score
from solit2.engines.reduced.sim import target_exposure_s
from solit2.engines.reduced.state import MistEffect, RunTrace, StationSample, StepRecord
from solit2.schema.design import Design
from solit2.schema.result import Result

ENGINE = "fds"
# Not a constant: a hardcoded version is a provenance claim nothing measured.
ENGINE_VERSION_UNKNOWN = "fds-unknown"
DETECT_CTRL = "DETECT"
ACT_CTRL = "ACT"


def _read_csv(path: Path) -> tuple[list[str], list[list[float]]]:
    """FDS CSV: row 1 is units, row 2 is device IDs, the rest is data."""
    lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
    ids = [c.strip() for c in lines[1].split(",")]
    rows = [[float(c) for c in ln.split(",")] for ln in lines[2:]]
    return ids, rows


def _at(ids: list[str], row: list[float], device: str) -> float:
    """A device the deck promised and the output does not carry is fatal.

    The parent spec makes a missing device column fatal on purpose: a default
    here would let a deck/reader mismatch through as a plausible-looking result.
    """
    if device not in ids:
        raise KeyError(device)
    return row[ids.index(device)]


def _control_times(run_dir: Path, chid: str) -> dict[str, float | None]:
    """When FDS's own controls changed state: `<CHID>_ctrl.csv`, status -1 -> 1.

    The deck opens the heads through the ACT control (detection, then the
    activation delay), so the moment water actually left the nozzles is a
    fact FDS recorded -- not the design's timetable measured from t=0, which
    is what the reader used to assume and which is wrong by the whole time the
    fire takes to reach the detector.
    """
    ids, rows = _read_csv(run_dir / f"{chid}_ctrl.csv")
    times = {}
    for name in (DETECT_CTRL, ACT_CTRL):
        if name not in ids:
            raise KeyError(name)
        col = ids.index(name)
        times[name] = next((r[0] for r in rows if r[col] > 0), None)
    return times


def _flow_fraction(t_s: float, t_activate_s: float | None, ramp_s: float) -> float:
    """Tier 1's `_flow_fraction`: nothing before the valves open, then the pumps
    ramp linearly -- the same FLOW_RAMP the deck hands FDS."""
    if t_activate_s is None or t_s < t_activate_s:
        return 0.0
    return min((t_s - t_activate_s) / ramp_s, 1.0) if ramp_s > 0 else 1.0


def _station(ids: list[str], row: list[float], name: str,
             heights: tuple[float, ...]) -> StationSample:
    """One Table 5 location's readings. Absent where Table 5 has no sensor."""
    kit = INSTRUMENTS[name]
    temps = tuple(_at(ids, row, f"{name}_TC{i}") for i in range(kit.thermocouples))
    breathing = min(range(len(heights)), key=lambda i: abs(heights[i] - BREATHING_HEIGHT_M))
    return StationSample(
        temp_c=temps[breathing],
        flux_kwm2=_at(ids, row, f"{name}_HF") if kit.heat_flux else None,
        visibility_m=_at(ids, row, f"{name}_VIS") if kit.visibility else None,
        # FDS's FED device is the asphyxiant dose; the thermal dose has no
        # single FDS device, so it stays absent rather than being invented.
        fed_tox=_at(ids, row, f"{name}_FED") if kit.toxic_gas else None,
        fed_heat=None,
        co_ppm=_at(ids, row, f"{name}_CO") if kit.toxic_gas else None,
        air_velocity_ms=_at(ids, row, f"{name}_U") if kit.air_velocity else None,
        temps_c=temps,
        heights_m=heights,
    )


def _engine_version(run_dir: Path) -> str:
    """The FDS build that wrote this output, or an explicit 'unknown'.

    Parsed from FDS's own log. Where the log does not name a build, the result
    says so rather than asserting a version nobody verified.
    """
    version = runner_mod.fds_version(run_dir)
    return f"fds-{version}" if version else ENGINE_VERSION_UNKNOWN


def _in_window(x_m: float) -> bool:
    return deck_mod.WINDOW_M[0] <= x_m <= deck_mod.WINDOW_M[1]


def _ceiling_ids(ids: list[str]) -> list[str]:
    return [i for i in ids if i.startswith(deck_mod.CEILING_TC_PREFIX)]


def free_burn_hrr_mw(free_burn_dir: Path, design: Design, t_s: list[float]) -> list[float]:
    """The free-burn run's measured HRR on the mist run's clock.

    Only a run that reaches every instant asked for can supply it: reading past
    the free run's last sample would hold its final value flat, which is a
    number nothing measured.
    """
    ids, rows = _read_csv(Path(free_burn_dir)
                          / f"{deck_mod.chid(design, suppression=False)}_hrr.csv")
    times = np.array([r[0] for r in rows])
    if t_s and times[-1] < t_s[-1] - 1.0:
        raise ValueError(
            f"the free-burn run covers 0-{times[-1]:.0f} s and the mist run reaches "
            f"{t_s[-1]:.0f} s; the two are not comparable until the free burn has run "
            f"as far")
    return [float(v) for v in np.interp(t_s, times, _hrr_mw(ids, rows))]


HRR_COLUMN = "HRR"


def _hrr_mw(ids: list[str], rows: list[list[float]]) -> list[float]:
    """The run's heat release, by column NAME. FDS's `_hrr.csv` carries a
    different column count with and without particles, so a fixed index is a
    guess that happens to hold."""
    if HRR_COLUMN not in ids:
        raise KeyError(HRR_COLUMN)
    col = ids.index(HRR_COLUMN)
    return [r[col] / 1000.0 for r in rows]


def _step_records(devc_ids: list[str], devc_rows: list[list[float]],
                  hrr_mw_series: list[float], design: Design,
                  heights: dict[str, tuple[float, ...]], t_activate_s: float | None,
                  hrr_free_mw: list[float] | None) -> list[StepRecord]:
    """One StepRecord per sample. `heights` keys the stations this deck models."""
    ceiling = _ceiling_ids(devc_ids)
    fire_ceiling = deck_mod.fire_ceiling_device_id()
    threshold_c = design.ahj.structure_temp_threshold_c

    steps: list[StepRecord] = []
    exposure_s = 0.0
    for i, row in enumerate(devc_rows):
        t_s = row[0]
        dt_s = t_s - devc_rows[i - 1][0] if i else 0.0
        hrr_mw = hrr_mw_series[i] if i < len(hrr_mw_series) else hrr_mw_series[-1]
        ceiling_temps = [_at(devc_ids, row, c) for c in ceiling]
        target_flux = _at(devc_ids, row, deck_mod.TARGET_GAUGE_ID)
        exposure_s = target_exposure_s(exposure_s, target_flux, dt_s)
        hot = sum(1 for t in ceiling_temps if t > threshold_c)
        steps.append(StepRecord(
            t_s=t_s,
            hrr_mw=hrr_mw,
            # The separate free-burn FDS run where one exists; otherwise this
            # run's own HRR, because deriving a free-burn curve here would be a
            # Tier 1 number wearing a Tier 2 label.
            hrr_free_mw=hrr_free_mw[i] if hrr_free_mw is not None else hrr_mw,
            ceiling_temp_c=max(ceiling_temps),
            # Tier 1's own definition: the ceiling gas above the fire -- read by
            # device ID, not by position, so a reordered CSV cannot silently
            # move the measurement somewhere else.
            lining_temp_c=_at(devc_ids, row, fire_ceiling),
            # No pipe in the deck. A water-filled pipe that nothing has heated
            # reads ambient; 0.0 would be a colder-than-air measurement.
            pipe_temp_c=design.tunnel.ambient_temp_c,
            target_flux_kwm2=target_flux,
            u_eff_ms=_at(devc_ids, row, "D45_U"),
            # Tier 1 correlation outputs with no FDS equivalent. No criterion
            # reads either, and FDS resolves backlayering in the slice files.
            u_critical_ms=0.0,
            backlayer_m=0.0,
            water_lpm=design.flow_lpm * _flow_fraction(t_s, t_activate_s,
                                                      design.zones.pump_ramp_s),
            pools_remaining=design.fire.pools.count if design.fire.pools else 0,
            # Every MistEffect field is a reduced-order construct: efficiency,
            # coverage fraction, cooling fraction, transmissivity. FDS computes
            # droplets, not these.
            mist=MistEffect.none(),
            stations={n: _station(devc_ids, row, n, h) for n, h in heights.items()},
            target_exposure_s=exposure_s,
            structure_exposure_length_m=hot * deck_mod.CEILING_TC_SPACING_M,
        ))
    return steps


def _trace(design: Design, steps: list[StepRecord], ctrl: dict[str, float | None]) -> RunTrace:
    """Tier 1's RunTrace, carrying the event clock its criteria, timeline and
    HMI read -- under Tier 1's own key names, from FDS's own control log."""
    activate = ctrl[ACT_CTRL]
    velocity = design.ventilation.velocity_ms or max(design.ventilation.velocity_range_ms)
    return RunTrace(steps=tuple(steps),
                    events={"t_detect_s": ctrl[DETECT_CTRL],
                            "t_activate_s": activate,
                            "t_full_pressure_s": (None if activate is None
                                                  else activate + design.zones.pump_ramp_s)},
                    section=design.tunnel.section, velocity_ms=velocity)


def _peaks_of(steps: list[StepRecord], modelled: list[str],
              peak_lining_c: float) -> dict[str, float]:
    peaks = {"hrr_mw": max(s.hrr_mw for s in steps),
             "hrr_free_burn_mw": max(s.hrr_free_mw for s in steps),
             "ceiling_temp_c": max(s.ceiling_temp_c for s in steps),
             "lining_temp_c": peak_lining_c,
             "pipe_surface_temp_c": max(s.pipe_temp_c for s in steps),
             "target_peak_flux_kwm2": max(s.target_flux_kwm2 for s in steps),
             "target_max_exposure_s": max(s.target_exposure_s for s in steps),
             "structure_exposure_length_m": max(s.structure_exposure_length_m
                                                for s in steps)}
    # smoke_layer_temp_d15_c and smoke_layer_temp_d100_c: only if the station
    # is in the modelled set (within the window); else omit to avoid KeyError
    for station, key in (("D15", "smoke_layer_temp_d15_c"),
                         ("D100", "smoke_layer_temp_d100_c")):
        if station in modelled:
            peaks[key] = max(s.stations[station].temp_c for s in steps)
    return peaks


def _warnings(design: Design, geom: SectionGeometry, velocity_ms: float, engine_version: str,
              skipped: list[str], free_burn: bool, deck_current: bool | None) -> list[str]:
    """Everything a reader must know that the numbers do not say themselves.

    A Tier 2 result is interchangeable with a Tier 1 one downstream, so every
    quantity that is a stand-in rather than a measurement has to be visible
    here -- not in a source comment where no report will ever show it.
    """
    stepped_m2 = deck_mod.stepped_free_area_m2(geom)
    gap_pct = (stepped_m2 - geom.free_area_m2) / geom.free_area_m2 * 100.0
    fp = design.fire.footprint
    fuel, target = deck_mod.fuel_box(design, geom), deck_mod.target_box(design, geom)
    ceiling_y = fuel.y_centre_m
    warnings = [
        (f"hrr_free_mw is the separate free-burn FDS run "
         f"{deck_mod.chid(design, suppression=False)}: the same deck with no mist system"
         if free_burn else
         "hrr_free_mw mirrors hrr_mw -- FDS ran the suppressed fire only, and no "
         "free-burn run exists to report; run the free-burn scenario for the difference"),
        f"deck geometry: the stair-stepped section's free area is "
        f"{stepped_m2:.1f} m2 against Tier 1's {geom.free_area_m2:.1f} m2 "
        f"({gap_pct:+.1f}%); a {deck_mod.DX_M} m stair-step cannot match a "
        f"smooth circle, and no attempt is made to make it",
        f"the mock-up is emitted snapped to the {deck_mod.DX_M} m mesh: x {fuel.x0:.1f} to "
        f"{fuel.x1:.1f} m, y {fuel.y0:.1f} to {fuel.y1:.1f} m, z {fuel.z0:.1f} to {fuel.z1:.1f} m "
        f"against the design's {fp.length_m:g} x {fp.width_m:g} m footprint at "
        f"{fp.base_height_m:g}-{fp.top_height_m:g} m; HRRPUA is normalised to the snapped top "
        f"face so the total HRR is the design's exactly",
        f"the target flux gauge sits on the solid target's face at x = {target.x0:.1f} m; "
        f"Tier 1 evaluates its flux at x = {design.fire.target_x_m:.1f} m",
        f"suppression of the prescribed burner is FDS's E_COEFFICIENT = "
        f"{deck_mod.E_COEFFICIENT}, an empirical extinguishing coefficient not fitted to "
        f"this nozzle or this fuel; the suppressed HRR scales directly with it",
        "fire growth is the design's free-burn curve distributed over burner segments "
        "lit in turn from the upstream end, so the total follows the curve exactly and "
        "the front moves downstream; a prescribed burner models neither pyrolysis nor "
        "ignition at the base of the load",
        f"the ceiling thermocouple line runs over the fuel load at y = {ceiling_y:.1f} m, "
        f"{deck_mod.CEILING_OFFSET_M} m under the stair-stepped ceiling there; the heat "
        f"detector line runs at the crown centre",
        # score.py deducts for airflow below u_critical_ms and envelope warns
        # near it. Both read a Tier 1 correlation output that FDS has no
        # equivalent for, so both are unreachable here -- and a leaderboard
        # ranking Tier 1 and Tier 2 together must not read that as a clean run.
        "the critical-velocity penalty cannot apply to a Tier 2 result: FDS "
        "resolves backlayering directly and the Tier 1 correlation input "
        "u_critical_ms is not computed, so it is recorded as 0.0 rather than "
        "measured",
        f"this result covers the single ventilation velocity "
        f"{velocity_ms:.2f} m/s, not Tier 1's section x velocity envelope; "
        f"criteria_cases is empty for the same reason",
    ]
    if deck_current is False:
        warnings.append(
            "this run's own deck is NOT the deck this design generates now: the run "
            "directory is named after the design, so a run made before the deck changed "
            "keeps its name while describing a different experiment. Re-run before "
            "reporting these numbers as this design's.")
    elif deck_current is None:
        warnings.append("this run kept no deck.fds, so what it actually simulated "
                        "cannot be checked against this design")
    if engine_version == ENGINE_VERSION_UNKNOWN:
        warnings.append("the FDS log does not name a build, so the engine "
                        "version on this result is unverified")
    if skipped:
        warnings.append(f"stations outside the {deck_mod.WINDOW_M} m deck window "
                        f"were not modelled: {', '.join(skipped)}")
    return warnings


def read(run_dir: Path, design: Design, *, free_burn_dir: Path | None = None) -> Result:
    """The mist run's Result. `free_burn_dir` is the same design's free-burn run,
    which supplies the free-burn HRR the mist run is otherwise unable to report."""
    run_dir = Path(run_dir)
    chid = deck_mod.chid(design)
    devc_ids, devc_rows = _read_csv(run_dir / f"{chid}_devc.csv")
    hrr_ids, hrr_rows = _read_csv(run_dir / f"{chid}_hrr.csv")
    ctrl = _control_times(run_dir, chid)
    if ctrl[ACT_CTRL] is None:
        # Tier 1 refuses the same case (`sim._require_detection`): a run in
        # which the heads never opened has not modelled the system at all, and
        # scoring it as a mist run would pass off a free burn as suppression.
        raise ValueError(
            "the FDS run's heat detectors never tripped, so the mist never discharged: "
            "this is not a suppressed-fire result. Either the simulated window ends "
            "before detection, or the detector devices are not in gas")

    geom = section_geometry(design)
    modelled = [n for n, x in STATIONS.items() if _in_window(x)]
    heights = {n: thermocouple_heights_m(INSTRUMENTS[n].thermocouples, geom.crown_height_m)
               for n in modelled}
    times = [r[0] for r in devc_rows]
    free = free_burn_hrr_mw(free_burn_dir, design, times) if free_burn_dir else None
    steps = _step_records(devc_ids, devc_rows, _hrr_mw(hrr_ids, hrr_rows), design, heights,
                          ctrl[ACT_CTRL], free)
    trace = _trace(design, steps, ctrl)
    engine_version = _engine_version(run_dir)

    hyd = size_system(design, geom)
    cost = cost_index(design, hyd)
    criteria = evaluate(trace, hyd, cost, design)
    peak_lining = max(s.lining_temp_c for s in trace.steps)
    scored = compute_score(criteria, hyd, cost, trace, peak_lining,
                           design.constraints.max_application_density_mm_min)

    return Result(
        # No calibration_* keys: Tier 1 carries them because it is fitted to the
        # anchors. FDS is not, and claiming that provenance would be a lie.
        meta={"design_name": design.meta.name, "design_sha": chid,
              "engine": ENGINE, "engine_version": engine_version,
              "timestamp": datetime.now(timezone.utc).isoformat(),
              "window_m": list(deck_mod.WINDOW_M)},
        envelope=[{"section": trace.section, "velocity_ms": trace.velocity_ms}],
        worst_case={"section": trace.section, "velocity_ms": trace.velocity_ms},
        events=trace.events,
        criteria=criteria,
        criteria_cases={},
        constraints=evaluate_constraints(hyd, design),
        peaks=_peaks_of(steps, modelled, peak_lining),
        mist={},
        hydraulics=hyd.__dict__,
        cost=cost.__dict__,
        score={"total": scored.total, "gates_passed": scored.gates_passed,
               "gates_failed": scored.gates_failed, "components": scored.components,
               "penalties": scored.penalties, "criteria_unset": scored.criteria_unset},
        timeseries={"t_s": [s.t_s for s in steps],
                    "hrr_mw": [s.hrr_mw for s in steps],
                    "hrr_free_mw": [s.hrr_free_mw for s in steps],
                    "ceiling_temp_c": [s.ceiling_temp_c for s in steps]},
        warnings=_warnings(design, geom, trace.velocity_ms, engine_version,
                           sorted(set(STATIONS) - set(modelled)), free is not None,
                           deck_mod.matches_design(run_dir, design)),
    )

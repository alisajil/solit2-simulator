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
# How far the HRR must have fallen from its own maximum, within the simulated
# window, before that maximum is reported as the fire's PEAK rather than as a
# lower bound on it. A 10% fall sits outside LES's own turbulent HRR noise
# (a few percent, run to run, at fixed conditions -- see the deck's own
# convergence study on droplet sampling for the scale of that noise), so a
# drop this size means the fire has actually turned over, not that the run
# merely stopped sampling a still-rising or still-plateaued curve. A run whose
# HRR sits at its maximum when it stops has measured a lower bound on the
# peak, not the peak itself -- and everything computed FROM that peak (ceiling
# and lining temperature, target flux and exposure) inherits the same bound.
PEAK_PASSED_DROP_FRACTION = 0.10
# The rule above is applied to a centred moving average, not to the raw HRR.
# "A few percent" is the run-to-run scatter of a PEAK; the instantaneous LES
# HRR of one run swings far more than that about its own mean -- the c4 test's
# oxygen-calorimetry trace (SOLIT2 Annex 2 Figure 9) spikes to 34 MW on a
# 30 MW plateau -- so a raw maximum is usually a spike, and a plateau that
# merely ends below one spike would be declared "passed". 31 samples is 30 s at
# the deck's 1 s output interval (`deck.DEVC_DT_S`): longer than a turbulent
# puff, far shorter than the minutes over which a fire turns over.
PEAK_SMOOTHING_SAMPLES = 31


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


def hottest_ceiling(devc_ids: list[str], devc_rows: list[list[float]]) -> tuple[str, float]:
    """(device, peak temperature) over the whole ceiling line and the whole run."""
    ceiling = _ceiling_ids(devc_ids)
    peaks = {c: max(_at(devc_ids, row, c) for row in devc_rows) for c in ceiling}
    hottest = max(peaks, key=peaks.get)
    return hottest, peaks[hottest]


def ceiling_device_x_m(device: str) -> float:
    """The x position the deck laid this ceiling device out at."""
    index = int(device[len(deck_mod.CEILING_TC_PREFIX):])
    return deck_mod.CORE_M[0] + index * deck_mod.CEILING_TC_SPACING_M


def _step_records(devc_ids: list[str], devc_rows: list[list[float]],
                  hrr_mw_series: list[float], design: Design,
                  heights: dict[str, tuple[float, ...]], t_activate_s: float | None,
                  hrr_free_mw: list[float] | None) -> list[StepRecord]:
    """One StepRecord per sample. `heights` keys the stations this deck models."""
    ceiling = _ceiling_ids(devc_ids)
    threshold_c = design.ahj.structure_temp_threshold_c

    steps: list[StepRecord] = []
    exposure_s = 0.0
    for i, row in enumerate(devc_rows):
        t_s = row[0]
        dt_s = t_s - devc_rows[i - 1][0] if i else 0.0
        hrr_mw = hrr_mw_series[i] if i < len(hrr_mw_series) else hrr_mw_series[-1]
        ceiling_temps = [_at(devc_ids, row, c) for c in ceiling]
        # Annex 7 5.2.6: no target in a Class B run, so no gauge and no flux to read.
        target_flux = (_at(devc_ids, row, deck_mod.TARGET_GAUGE_ID)
                       if deck_mod.has_target(design) else 0.0)
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
            # The HOTTEST ceiling this run resolved, which is Tier 1's own
            # identity: there `ceiling_temp_c` and `lining_temp_c` are the same
            # variable, a correlation evaluated at x=0 whose longitudinal decay
            # peaks there, so above-the-fire IS its hottest point.
            #
            # FDS is not obliged to agree about WHERE that is, and does not:
            # longitudinal ventilation leans the plume downstream, so the
            # hottest lining sits past the fire. Measured on a real 6.8 MW run
            # at 5.08 m/s, the ceiling above the fire read 78.1 C while the
            # device 5 m downstream read 132.6 C. Pinning the lining to x=0
            # reported the cooler of the two into the structural score, which
            # measures how far the peak lining sits below 1350 C -- overstating
            # the margin, and growing with fire size. Where the peak actually
            # sat is reported in `warnings` rather than thrown away.
            lining_temp_c=max(ceiling_temps),
            # No pipe in the deck. A water-filled pipe that nothing has heated
            # reads ambient; 0.0 would be a colder-than-air measurement.
            pipe_temp_c=design.tunnel.ambient_temp_c,
            target_flux_kwm2=target_flux,
            # The Annex 7 reference station, upstream of the fire: U45 (Class A,
            # 5.2.7) or U20 (Class B, 5.3.6). This was D45, on the far side of the
            # fire, where the expanded hot gas reads faster than the air the fire
            # is fed by.
            u_eff_ms=_at(devc_ids, row, f"{deck_mod.velocity_station(design)}_U"),
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


def _centred_mean(values: list[float], window: int) -> list[float]:
    """Moving average over `window` samples centred on each one, truncated at
    the ends rather than padded, so no sample is invented."""
    half = window // 2
    return [sum(values[max(i - half, 0):i + half + 1])
            / len(values[max(i - half, 0):i + half + 1]) for i in range(len(values))]


def hrr_peak_passed(hrr_mw: list[float],
                    smoothing_samples: int = PEAK_SMOOTHING_SAMPLES) -> bool:
    """Whether the run's simulated window actually passed the HRR's peak.

    On the HRR averaged over `smoothing_samples` (see PEAK_SMOOTHING_SAMPLES):
    passed iff the time of the maximum is before the last sample AND the HRR
    at the last sample has fallen to at most
    `(1 - PEAK_PASSED_DROP_FRACTION)` of that maximum -- see the constant's own
    comment for why 10%. A curve that never rises above zero (no fire, or read
    before ignition) has no peak to have passed, so that is False too rather
    than a vacuous True from `0 <= 0`.
    """
    if smoothing_samples < 1:
        raise ValueError(f"smoothing_samples must be at least 1, got {smoothing_samples}")
    smooth = _centred_mean(hrr_mw, smoothing_samples)
    peak_i = max(range(len(smooth)), key=lambda i: smooth[i])
    peak_mw = smooth[peak_i]
    if peak_mw <= 0.0 or peak_i >= len(smooth) - 1:
        return False
    return smooth[-1] <= peak_mw * (1.0 - PEAK_PASSED_DROP_FRACTION)


def _peaks_of(steps: list[StepRecord], modelled: list[str],
              peak_lining_c: float, peak_passed: bool) -> dict[str, float | bool]:
    peaks: dict[str, float | bool] = {
             "hrr_mw": max(s.hrr_mw for s in steps),
             "hrr_free_burn_mw": max(s.hrr_free_mw for s in steps),
             "ceiling_temp_c": max(s.ceiling_temp_c for s in steps),
             "lining_temp_c": peak_lining_c,
             "pipe_surface_temp_c": max(s.pipe_temp_c for s in steps),
             "target_peak_flux_kwm2": max(s.target_flux_kwm2 for s in steps),
             "target_max_exposure_s": max(s.target_exposure_s for s in steps),
             "structure_exposure_length_m": max(s.structure_exposure_length_m
                                                for s in steps),
             # Whether the window above actually passed the HRR's turnover --
             # see `hrr_peak_passed`. When False every peak here is a lower
             # bound, not the run's true peak, and `_warnings` says so.
             "hrr_peak_passed": peak_passed}
    # smoke_layer_temp_d15_c and smoke_layer_temp_d100_c: only if the station
    # is in the modelled set (within the window); else omit to avoid KeyError
    for station, key in (("D15", "smoke_layer_temp_d15_c"),
                         ("D100", "smoke_layer_temp_d100_c")):
        if station in modelled:
            peaks[key] = max(s.stations[station].temp_c for s in steps)
    return peaks


def _rake_note(design: Design, geom: SectionGeometry) -> str:
    """Whether any Annex 7 thermocouple had to be moved down into gas."""
    from solit2.engines.reduced.criteria import INSTRUMENTS, thermocouple_heights_m
    moved = []
    for name, kit in INSTRUMENTS.items():
        for rung, z in enumerate(thermocouple_heights_m(kit.thermocouples, geom.crown_height_m)):
            placed = deck_mod.gas_z_m(geom, 0.0, z)
            if abs(placed - z) > 1e-9:
                moved.append(f"{name}_TC{rung} {z:.2f}->{placed:.2f} m")
    if not moved:
        return ("every Annex 7 thermocouple sits at the height Tier 1 computes for it, "
                "in gas")
    return (f"{len(moved)} thermocouple(s) were lowered to stay in gas: the stair-stepped "
            f"ceiling is below the section's true crown, so the top of the ladder would sit "
            f"inside the lining and read ambient forever ({', '.join(moved)})")


def _warnings(design: Design, geom: SectionGeometry, velocity_ms: float, engine_version: str,
              skipped: list[str], free_burn: bool, deck_current: bool | None,
              hottest: tuple[str, float], above_fire_c: float,
              events: dict[str, float | None], last_t_s: float,
              peak_passed: bool, e_coefficient: float) -> list[str]:
    """Everything a reader must know that the numbers do not say themselves.

    A Tier 2 result is interchangeable with a Tier 1 one downstream, so every
    quantity that is a stand-in rather than a measurement has to be visible
    here -- not in a source comment where no report will ever show it.
    """
    stepped_m2 = deck_mod.stepped_free_area_m2(geom)
    gap_pct = (stepped_m2 - geom.free_area_m2) / geom.free_area_m2 * 100.0
    fp = design.fire.footprint
    fuel = deck_mod.fuel_box(design, geom)
    ceiling_y = fuel.y_centre_m
    warnings = [
        (f"hrr_free_mw is the separate free-burn FDS run "
         f"{deck_mod.chid(design, suppression=False)}: the same deck with no mist system"
         if free_burn else
         "hrr_free_mw mirrors hrr_mw -- FDS ran the suppressed fire only, and no "
         "free-burn run exists to report; run the free-burn scenario for the difference"),
        (f"deck geometry: the emitted section's free area is {stepped_m2:.1f} m2 "
         f"against Tier 1's {geom.free_area_m2:.1f} m2, so both engines model the same "
         f"cross-section"
         if abs(gap_pct) < 0.5 else
         f"deck geometry: the emitted section's free area is {stepped_m2:.1f} m2 against "
         f"Tier 1's {geom.free_area_m2:.1f} m2 ({gap_pct:+.1f}%); the two engines are not "
         f"modelling the same cross-section and the difference carries into every "
         f"velocity and every gas concentration"),
        f"the mock-up is emitted snapped to the {deck_mod.DX_M} m mesh: x {fuel.x0:.1f} to "
        f"{fuel.x1:.1f} m, y {fuel.y0:.1f} to {fuel.y1:.1f} m, z {fuel.z0:.1f} to {fuel.z1:.1f} m "
        f"against the design's {fp.length_m:g} x {fp.width_m:g} m footprint at "
        f"{fp.base_height_m:g}-{fp.top_height_m:g} m; HRRPUA is normalised to the snapped top "
        f"face so the total HRR is the design's exactly",
        (f"the target flux gauge sits on the solid target's face at "
         f"x = {deck_mod.target_box(design, geom).x0:.1f} m; Tier 1 evaluates its flux at "
         f"x = {design.fire.target_x_m:.1f} m"
         if deck_mod.has_target(design) else
         "no fire target in this run (Annex 7 5.2.6 sites one for Class A only); "
         "target_flux_kwm2 is 0 throughout, not a measurement"),
        f"suppression of the prescribed burner is FDS's E_COEFFICIENT = "
        f"{e_coefficient}, an empirical extinguishing coefficient not fitted to "
        f"this nozzle or this fuel; the suppressed HRR scales directly with it",
        "fire growth is the design's free-burn curve distributed over burner segments "
        "lit in turn from the upstream end, so the total follows the curve exactly and "
        "the front moves downstream; a prescribed burner models neither pyrolysis nor "
        "ignition at the base of the load",
        _rake_note(design, geom),
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
    if not peak_passed:
        warnings.append(
            f"the HRR never fell back by {PEAK_PASSED_DROP_FRACTION * 100:.0f}% from its "
            f"maximum within the simulated window: the peak HRR reported here, and every "
            f"peak derived from it (ceiling and lining temperature, target flux and "
            f"exposure, structure exposure length), is a LOWER BOUND on the run's true "
            f"peak, not the peak itself. Extend the simulated window until the HRR has "
            f"turned over.")
    activate, full = events["t_activate_s"], events["t_full_pressure_s"]
    if activate is not None and last_t_s < (full or activate):
        # Measured on a 250 s pair: the mist had 22 s at up to 72 % of flow, and
        # the suppressed and free-burn HRR agreed to 0.3 % while the ceiling
        # above the fire differed by 119 C. FDS's E_COEFFICIENT lowers a
        # prescribed burner only as water lands and stays ON the fuel, whereas
        # the droplets cool the gas immediately -- so a run cut off here shows
        # the cooling and not the suppression, and reads as "the mist did
        # nothing to the fire" when it has barely had a chance to.
        warnings.append(
            f"the run ends at {last_t_s:.0f} s, before the pumps reach full pressure at "
            f"{full or activate:.0f} s: the mist ran for {last_t_s - activate:.0f} s at "
            f"partial flow. Gas and ceiling temperatures already respond, but the burning "
            f"rate barely does, so this run must not be read as the suppression this "
            f"system achieves")
    hottest_device, hottest_c = hottest
    offset_m = ceiling_device_x_m(hottest_device) - deck_mod.FIRE_X_M
    if abs(offset_m) > deck_mod.CEILING_TC_SPACING_M / 2.0:
        warnings.append(
            f"the hottest lining sat {offset_m:+.0f} m from the mock-up centre at "
            f"{hottest_c:.0f} C, not above it, where the ceiling reached {above_fire_c:.0f} C: "
            f"longitudinal ventilation leans the plume downstream. Tier 1 cannot place it "
            f"anywhere but above the fire, so the two tiers agree on the value and not on "
            f"where it is")
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
        warnings.append("the FDS log names neither a release nor a source revision, "
                        "so the engine version on this result is unverified")
    elif "@" in engine_version:
        warnings.append(
            f"the engine is a build from source ({engine_version.removeprefix('fds-')}), "
            f"not a numbered FDS release: it identifies the code that ran, and it is not "
            f"a version anyone else can request by name")
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
    peak_passed = hrr_peak_passed([s.hrr_mw for s in trace.steps])
    e_used = deck_mod.stored_e_coefficient(run_dir)
    if e_used is None:
        e_used = deck_mod.E_COEFFICIENT
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
        peaks=_peaks_of(steps, modelled, peak_lining, peak_passed),
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
                           deck_mod.matches_design(run_dir, design),
                           hottest_ceiling(devc_ids, devc_rows),
                           max(_at(devc_ids, row, deck_mod.fire_ceiling_device_id())
                               for row in devc_rows),
                           trace.events, steps[-1].t_s,
                           peak_passed, e_used),
    )

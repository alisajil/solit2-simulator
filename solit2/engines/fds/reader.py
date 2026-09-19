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

from solit2.engines.fds import deck as deck_mod
from solit2.engines.reduced.constraints import evaluate as evaluate_constraints
from solit2.engines.reduced.cost import cost_index
from solit2.engines.reduced.criteria import (BREATHING_HEIGHT_M, INSTRUMENTS, STATIONS,
                                             evaluate, thermocouple_heights_m)
from solit2.engines.reduced.envelope import _design_sha
from solit2.engines.reduced.geometry import section_geometry
from solit2.engines.reduced.hydraulics import size_system
from solit2.engines.reduced.score import compute as compute_score
from solit2.engines.reduced.sim import target_exposure_s
from solit2.engines.reduced.state import MistEffect, RunTrace, StationSample, StepRecord
from solit2.schema.design import Design
from solit2.schema.result import Result

ENGINE = "fds"
ENGINE_VERSION = "fds-6.11.1"


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


def _in_window(x_m: float) -> bool:
    return deck_mod.WINDOW_M[0] <= x_m <= deck_mod.WINDOW_M[1]


def _ceiling_ids(ids: list[str]) -> list[str]:
    return [i for i in ids if i.startswith(deck_mod.CEILING_TC_PREFIX)]


def read(run_dir: Path, design: Design) -> Result:
    run_dir = Path(run_dir)
    chid = _design_sha(design)
    devc_ids, devc_rows = _read_csv(run_dir / f"{chid}_devc.csv")
    _, hrr_rows = _read_csv(run_dir / f"{chid}_hrr.csv")

    geom = section_geometry(design)
    modelled = [n for n, x in STATIONS.items() if _in_window(x)]
    heights = {n: thermocouple_heights_m(INSTRUMENTS[n].thermocouples, geom.crown_height_m)
               for n in modelled}
    ceiling = _ceiling_ids(devc_ids)
    threshold_c = design.ahj.structure_temp_threshold_c
    activation_s = design.zones.activation_delay_s
    full_pressure_s = activation_s + design.zones.pump_ramp_s

    steps: list[StepRecord] = []
    exposure_s = 0.0
    for i, row in enumerate(devc_rows):
        t_s = row[0]
        dt_s = t_s - devc_rows[i - 1][0] if i else 0.0
        hrr_mw = (hrr_rows[i][1] if i < len(hrr_rows) else hrr_rows[-1][1]) / 1000.0
        ceiling_temps = [_at(devc_ids, row, c) for c in ceiling]
        target_flux = _at(devc_ids, row, deck_mod.TARGET_GAUGE_ID)
        exposure_s = target_exposure_s(exposure_s, target_flux, dt_s)
        hot = sum(1 for t in ceiling_temps if t > threshold_c)
        steps.append(StepRecord(
            t_s=t_s,
            hrr_mw=hrr_mw,
            # FDS ran the SUPPRESSED fire. There is no free-burn curve to read,
            # and deriving one would be a Tier 1 number wearing a Tier 2 label.
            hrr_free_mw=hrr_mw,
            ceiling_temp_c=max(ceiling_temps),
            # Tier 1's own definition: the ceiling gas above the fire.
            lining_temp_c=ceiling_temps[len(ceiling_temps) // 2],
            # No pipe in the deck. A water-filled pipe that nothing has heated
            # reads ambient; 0.0 would be a colder-than-air measurement.
            pipe_temp_c=design.tunnel.ambient_temp_c,
            target_flux_kwm2=target_flux,
            u_eff_ms=_at(devc_ids, row, "D45_U"),
            # Tier 1 correlation outputs with no FDS equivalent. No criterion
            # reads either, and FDS resolves backlayering in the slice files.
            u_critical_ms=0.0,
            backlayer_m=0.0,
            water_lpm=design.flow_lpm if t_s >= full_pressure_s else 0.0,
            pools_remaining=design.fire.pools.count if design.fire.pools else 0,
            # Every MistEffect field is a reduced-order construct: efficiency,
            # coverage fraction, cooling fraction, transmissivity. FDS computes
            # droplets, not these.
            mist=MistEffect.none(),
            stations={n: _station(devc_ids, row, n, heights[n]) for n in modelled},
            target_exposure_s=exposure_s,
            structure_exposure_length_m=hot * deck_mod.CEILING_TC_SPACING_M,
        ))

    velocity = design.ventilation.velocity_ms or max(design.ventilation.velocity_range_ms)
    trace = RunTrace(steps=tuple(steps),
                     events={"t_activation_s": activation_s,
                             "t_full_pressure_s": full_pressure_s},
                     section=design.tunnel.section, velocity_ms=velocity)

    hyd = size_system(design, geom)
    cost = cost_index(design, hyd)
    criteria = evaluate(trace, hyd, cost, design)
    peak_lining = max(s.lining_temp_c for s in trace.steps)
    scored = compute_score(criteria, hyd, cost, trace, peak_lining,
                           design.constraints.max_application_density_mm_min)
    skipped = sorted(set(STATIONS) - set(modelled))

    peaks = {"hrr_mw": max(s.hrr_mw for s in steps),
             "hrr_free_burn_mw": max(s.hrr_free_mw for s in steps),
             "ceiling_temp_c": max(s.ceiling_temp_c for s in steps),
             "lining_temp_c": peak_lining,
             "pipe_surface_temp_c": max(s.pipe_temp_c for s in steps),
             "target_peak_flux_kwm2": max(s.target_flux_kwm2 for s in steps),
             "target_max_exposure_s": max(s.target_exposure_s for s in steps),
             "structure_exposure_length_m": max(s.structure_exposure_length_m
                                                for s in steps)}
    # smoke_layer_temp_d15_c and smoke_layer_temp_d100_c: only if the station
    # is in the modelled set (within the window); else omit to avoid KeyError
    if "D15" in modelled:
        peaks["smoke_layer_temp_d15_c"] = max(s.stations["D15"].temp_c for s in steps)
    if "D100" in modelled:
        peaks["smoke_layer_temp_d100_c"] = max(s.stations["D100"].temp_c for s in steps)

    return Result(
        # No calibration_* keys: Tier 1 carries them because it is fitted to the
        # anchors. FDS is not, and claiming that provenance would be a lie.
        meta={"design_name": design.meta.name, "design_sha": chid,
              "engine": ENGINE, "engine_version": ENGINE_VERSION,
              "timestamp": datetime.now(timezone.utc).isoformat(),
              "window_m": list(deck_mod.WINDOW_M)},
        envelope=[{"section": trace.section, "velocity_ms": trace.velocity_ms}],
        worst_case={"section": trace.section, "velocity_ms": trace.velocity_ms},
        events=trace.events,
        criteria=criteria,
        criteria_cases={},
        constraints=evaluate_constraints(hyd, design),
        peaks=peaks,
        mist={},
        hydraulics=hyd.__dict__,
        cost=cost.__dict__,
        score={"total": scored.total, "gates_passed": scored.gates_passed,
               "gates_failed": scored.gates_failed, "components": scored.components,
               "penalties": scored.penalties, "criteria_unset": scored.criteria_unset},
        timeseries={"t_s": [s.t_s for s in steps],
                    "hrr_mw": [s.hrr_mw for s in steps],
                    "ceiling_temp_c": [s.ceiling_temp_c for s in steps]},
        warnings=(["hrr_free_mw mirrors hrr_mw -- FDS ran the suppressed fire, "
                   "so no free-burn curve exists to report"]
                  + ([f"stations outside the {deck_mod.WINDOW_M} m deck window were "
                      f"not modelled: {', '.join(skipped)}"] if skipped else [])),
    )

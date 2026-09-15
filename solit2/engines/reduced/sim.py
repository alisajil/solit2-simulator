"""The one-second time loop.

Order within a step: the fire grows against last step's mist, the ventilation
responds to the new convective heat, the thermal field follows, the mist is
re-evaluated in that field, then the stations are sampled.
"""
from __future__ import annotations

from dataclasses import dataclass

from solit2.engines.reduced import fire as fire_mod
from solit2.engines.reduced import mist as mist_mod
from solit2.engines.reduced import tenability, thermal, ventilation
from solit2.engines.reduced.criteria import BREATHING_HEIGHT_M, STATIONS
from solit2.engines.reduced.geometry import (NozzlePosition, SectionGeometry,
                                             nozzle_positions, section_geometry)
from solit2.engines.reduced.state import (FireState, MistEffect, RunTrace, StationSample,
                                          StepRecord)
from solit2.engines.reduced.thermal import ThermalField
from solit2.engines.reduced.ventilation import VentilationState
from solit2.schema.design import Design, Zones

DT_S = 1.0
PIPE_WATER_FILLED_CAP_C = 100.0
PIPE_TIME_CONSTANT_S = 300.0
# A gauge the flame has reached is not reading a view factor any more.
FLAME_CONTACT_FLUX_KWM2 = 50.0
# Upstream of the backlayering front the air is still tunnel air.
AMBIENT_SPECIES = tenability.Species(0.0, 0.0, 0.0, tenability.AMBIENT_O2_PCT)


@dataclass(frozen=True)
class _Scene:
    """Everything a run needs that does not change from one step to the next.

    `positions` and `halo` are built once and reused for every step so that the
    mist module's geometry cache sees the same key, not an equal-but-new one.
    """
    design: Design
    geom: SectionGeometry
    positions: tuple[NozzlePosition, ...]
    halo: mist_mod.Halo
    model: fire_mod.FireModel
    fire_top_m: float
    h_ef_m: float
    ambient_c: float
    air_m3s: float
    half_active_length_m: float


def _build_scene(design: Design, section: str, velocity_ms: float) -> _Scene:
    tunnel = design.tunnel.model_copy(update={"section": section})
    scoped = design.model_copy(update={"tunnel": tunnel})
    geom = section_geometry(scoped)
    fire_y = scoped.fire.lane_centre_offset_from_wall_m - geom.road_width_m / 2.0
    fire_top = scoped.fire.footprint.top_height_m
    return _Scene(
        design=scoped,
        geom=geom,
        positions=nozzle_positions(scoped, geom, fire_x_m=0.0),
        halo=mist_mod.halo_around(0.0, fire_y, scoped.fire.footprint.length_m,
                                  scoped.fire.footprint.width_m),
        model=fire_mod.build_model(scoped),
        fire_top_m=fire_top,
        h_ef_m=geom.crown_height_m - fire_top,
        ambient_c=scoped.tunnel.ambient_temp_c,
        air_m3s=geom.free_area_m2 * velocity_ms,
        half_active_length_m=scoped.active_length_m / 2.0,
    )


def _initial_events() -> dict:
    return {"t_detect_s": None, "t_activate_s": None, "t_full_pressure_s": None,
            "t_peak_hrr_s": None, "pools_extinguished_at_s": None,
            "backlayering": {"occurred": False, "max_length_m": 0.0, "cleared_at_s": None}}


def _detector_excess_k(hrr_kw: float, design: Design, h_ef_m: float) -> float:
    radius = design.detection.sensor_spacing_m / 2.0
    return thermal.alpert_ceiling_excess_k(hrr_kw, radius, h_ef_m)


def _detect(scene: _Scene, events: dict, hrr_mw: float, t_s: float) -> None:
    """Trip the linear heat detector, and with it the activation timetable."""
    if events["t_detect_s"] is not None:
        return
    design = scene.design
    excess = _detector_excess_k(hrr_mw * 1000.0, design, scene.h_ef_m)
    if excess < design.detection.threshold_c - scene.ambient_c:
        return
    events["t_detect_s"] = t_s
    events["t_activate_s"] = t_s + design.zones.activation_delay_s
    events["t_full_pressure_s"] = events["t_activate_s"] + design.zones.pump_ramp_s


def _flow_fraction(zones: Zones, events: dict, t_s: float) -> float:
    """Zero until the valves open, then the pumps ramp linearly to full flow."""
    activate = events["t_activate_s"]
    if activate is None or t_s < activate:
        return 0.0
    ramp = zones.pump_ramp_s
    return min((t_s - activate) / ramp, 1.0) if ramp > 0 else 1.0


def _sample_stations(scene: _Scene, field: ThermalField, mist: MistEffect,
                     vent: VentilationState, species: tenability.Species,
                     fed_tox: dict[str, float],
                     fed_heat: dict[str, float]) -> dict[str, StationSample]:
    """Conditions at every station. `fed_tox` and `fed_heat` are the run's
    dose accumulators and are advanced here by this step's increment."""
    kappa_mist = (1.0 - mist.tau_mist) / max(scene.half_active_length_m, 1.0)
    samples: dict[str, StationSample] = {}
    for name, x_m in STATIONS.items():
        upstream_clear = x_m < 0 and abs(x_m) > vent.backlayer_m
        temp = scene.ambient_c if upstream_clear else field.gas_temp_c(x_m, BREATHING_HEIGHT_M)
        flux = field.radiant_flux_kwm2(x_m, BREATHING_HEIGHT_M, mist.tau_mist)
        local = AMBIENT_SPECIES if upstream_clear else species
        fed_tox[name] += tenability.fed_tox_increment(local, DT_S)
        fed_heat[name] += tenability.fed_heat_increment(temp, flux, DT_S)
        in_zone = abs(x_m) <= scene.half_active_length_m
        samples[name] = StationSample(
            temp_c=temp, flux_kwm2=flux,
            visibility_m=tenability.visibility_m(local.soot_gm3,
                                                 kappa_mist if in_zone else 0.0),
            fed_tox=fed_tox[name], fed_heat=fed_heat[name])
    return samples


def _target_flux_kwm2(scene: _Scene, field: ThermalField, mist: MistEffect) -> float:
    distance = scene.design.fire.target_distance_m
    flux = field.radiant_flux_kwm2(distance, scene.fire_top_m / 2.0, mist.tau_mist)
    if field.flame_tip_x_m >= distance:
        return max(flux, FLAME_CONTACT_FLUX_KWM2)
    return flux


def _note_events(scene: _Scene, events: dict, state: FireState, vent: VentilationState,
                 peak_hrr_mw: float) -> float:
    """Fold this step into the run's event log; returns the running peak HRR."""
    back = events["backlayering"]
    if vent.backlayer_m > 0:
        back["occurred"] = True
        back["max_length_m"] = max(back["max_length_m"], vent.backlayer_m)
    elif back["occurred"] and back["cleared_at_s"] is None:
        back["cleared_at_s"] = state.t_s

    if state.hrr_mw > peak_hrr_mw:
        peak_hrr_mw, events["t_peak_hrr_s"] = state.hrr_mw, state.t_s
    if (scene.model.fire_class == "B" and state.pools_remaining == 0
            and events["pools_extinguished_at_s"] is None):
        events["pools_extinguished_at_s"] = state.t_s
    return peak_hrr_mw


def run_once(design: Design, section: str, velocity_ms: float) -> RunTrace:
    scene = _build_scene(design, section, velocity_ms)
    state = fire_mod.initial_state(scene.model)
    mist = MistEffect.none()
    events = _initial_events()
    fed_tox = {name: 0.0 for name in STATIONS}
    fed_heat = {name: 0.0 for name in STATIONS}
    pipe_temp = scene.ambient_c
    steps: list[StepRecord] = []
    peak_hrr = 0.0

    total_steps = int(scene.design.zones.duration_min * 60 / DT_S)
    for _ in range(total_steps):
        state = fire_mod.step(scene.model, state, DT_S, mist)
        q_conv = fire_mod.convective_kw(scene.model, state.hrr_mw)
        vent = ventilation.evaluate(scene.geom, velocity_ms, q_conv)
        _detect(scene, events, state.hrr_mw, state.t_s)
        flow_fraction = _flow_fraction(scene.design.zones, events, state.t_s)

        field = thermal.field(scene.geom, scene.model, state, vent, mist, scene.fire_top_m,
                              scene.design.fire.footprint.length_m,
                              scene.design.fire.footprint.width_m, scene.ambient_c)
        mist = mist_mod.evaluate(scene.design, scene.geom, scene.positions, scene.halo,
                                 scene.fire_top_m, vent.u_eff_ms, field.ceiling_excess_k,
                                 q_conv, flow_fraction)

        species = tenability.species_at(scene.model, state.hrr_mw, scene.air_m3s,
                                        field.strat_factor)
        samples = _sample_stations(scene, field, mist, vent, species, fed_tox, fed_heat)

        ceiling = field.ceiling_temp_c(0.0)
        pipe_target = min(ceiling, PIPE_WATER_FILLED_CAP_C) if flow_fraction > 0 else ceiling
        pipe_temp += (pipe_target - pipe_temp) * DT_S / PIPE_TIME_CONSTANT_S

        peak_hrr = _note_events(scene, events, state, vent, peak_hrr)

        steps.append(StepRecord(
            t_s=state.t_s, hrr_mw=state.hrr_mw, hrr_free_mw=state.hrr_free_mw,
            ceiling_temp_c=ceiling, lining_temp_c=ceiling, pipe_temp_c=pipe_temp,
            target_flux_kwm2=_target_flux_kwm2(scene, field, mist), u_eff_ms=vent.u_eff_ms,
            u_critical_ms=vent.u_critical_ms, backlayer_m=vent.backlayer_m,
            water_lpm=scene.design.flow_lpm * flow_fraction,
            pools_remaining=state.pools_remaining, mist=mist, stations=samples))

    if events["t_detect_s"] is None:
        raise RuntimeError(
            f"the fire never reached the {design.detection.threshold_c} C detection "
            f"threshold within {design.zones.duration_min} minutes; check the fire preset"
        )
    return RunTrace(tuple(steps), events, section, velocity_ms)

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
from solit2.engines.reduced.criteria import (BREATHING_HEIGHT_M, FLAME_CONTACT_FLUX_KWM2,
                                             HEAT_FLUX_HEIGHT_M, INSTRUMENTS, STATIONS,
                                             WOOD_PILOTED_IGNITION_KWM2,
                                             thermocouple_heights_m)
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
# The span of ceiling walked for Annex 7 section 7.2.4, whose minimum criterion
# is "that high temperature exposure areas will be limited to a small area,
# directly above fire loads or slightly downstream".
#
# Stated explicitly rather than taken from the extremes of STATIONS. Table 5's
# outermost locations are U340 and D215 -- far-field air-velocity and smoke
# stations, 555 m apart -- and a 7.2.4 criterion swept over them would be
# measuring something the section does not ask about, at four times the cost of
# a per-timestep 1 m scan.
#
# The window is deliberately asymmetric, because 7.2.4's own wording is: the hot
# ceiling sits above the fire and is carried DOWNSTREAM by the longitudinal
# flow. Downstream it runs to D100, Table 5's furthest routinely-instrumented
# temperature station short of the far-field D215, so the reported length is a
# measurement and not a clip. Upstream it runs to U45, the furthest upstream
# full cross-section in Table 5 and the section where 5.2.7 has the ventilation
# velocity measured; the ceiling can only be hot upstream of the fire inside the
# backlayer, which is far shorter than that at every anchor geometry.
STRUCTURE_SCAN_MIN_M = -45.0
STRUCTURE_SCAN_MAX_M = 100.0
# Upstream of the backlayering front the air is still tunnel air.
AMBIENT_SPECIES = tenability.Species(0.0, 0.0, 0.0, tenability.AMBIENT_O2_PCT)
# Heat taken from the gas by one kg of spray water that evaporates completely:
# raising it from the inlet temperature to boiling, then the latent heat. This
# is exactly the denominator `mist._cooling_fraction` divides by, so dividing
# `chi_cool * q_conv` by it recovers the evaporated mass flow the mist module
# used, rather than modelling evaporation a second time.
MIST_EVAPORATION_ENTHALPY_KJKG = (
    mist_mod.WATER_CP_KJKGK * (mist_mod.WATER_BOILING_C - mist_mod.WATER_INLET_TEMP_C)
    + mist_mod.WATER_LATENT_HEAT_KJKG
)


@dataclass(frozen=True)
class _Tree:
    """One cross-section's thermocouple ladder, fixed for the whole run."""
    heights_m: tuple[float, ...]
    breathing_index: int


def _trees(geom: SectionGeometry) -> dict[str, _Tree]:
    """A ladder per Annex 7 Table 5 cross-section, built once per run.

    Ladders of the same size share one object, so a step's samples hold fifteen
    references to four tuples rather than fifteen copies of them. `index` is
    what enforces the contract that breathing height is ON the ladder: if the
    rule in `criteria.thermocouple_heights_m` ever stopped putting it there this
    raises at the start of the run instead of quietly reporting a neighbour.
    """
    by_count: dict[int, _Tree] = {}
    for kit in INSTRUMENTS.values():
        if kit.thermocouples not in by_count:
            heights = thermocouple_heights_m(kit.thermocouples, geom.crown_height_m)
            by_count[kit.thermocouples] = _Tree(heights,
                                                heights.index(BREATHING_HEIGHT_M))
    return {name: by_count[kit.thermocouples] for name, kit in INSTRUMENTS.items()}


@dataclass(frozen=True)
class _Scene:
    """Everything a run needs that does not change from one step to the next.

    `positions` and `envelope` are built once and reused for every step so that
    the mist module's geometry cache sees the same key, not an equal-but-new one.
    """
    design: Design
    geom: SectionGeometry
    positions: tuple[NozzlePosition, ...]
    envelope: mist_mod.FuelEnvelope
    model: fire_mod.FireModel
    fire_top_m: float
    fire_base_m: float
    h_ef_m: float
    ambient_c: float
    ambient_rh_pct: float
    air_m3s: float
    air_kgs: float
    half_active_length_m: float
    trees: dict[str, _Tree]


def _build_scene(design: Design, section: str, velocity_ms: float) -> _Scene:
    tunnel = design.tunnel.model_copy(update={"section": section})
    scoped = design.model_copy(update={"tunnel": tunnel})
    geom = section_geometry(scoped)
    fire_y = scoped.fire.lane_centre_offset_from_wall_m - geom.road_width_m / 2.0
    fire_top = scoped.fire.footprint.top_height_m
    fire_base = scoped.fire.footprint.base_height_m
    return _Scene(
        design=scoped,
        geom=geom,
        positions=nozzle_positions(scoped, geom, fire_x_m=0.0),
        envelope=mist_mod.fuel_envelope(0.0, fire_y, scoped.fire.footprint.length_m,
                                        scoped.fire.footprint.width_m,
                                        mist_mod.flank_reach_m(fire_top)),
        model=fire_mod.build_model(scoped),
        fire_top_m=fire_top,
        fire_base_m=fire_base,
        # The linear-heat detector's own Alpert ceiling-jet correlation is a
        # separate quantity from thermal.field()'s Li & Ingason h_ef and is out
        # of scope for Task 18: unchanged, still fuel-top-referenced.
        h_ef_m=geom.crown_height_m - fire_top,
        ambient_c=scoped.tunnel.ambient_temp_c,
        ambient_rh_pct=scoped.tunnel.ambient_rh_pct,
        air_m3s=geom.free_area_m2 * velocity_ms,
        air_kgs=geom.free_area_m2 * velocity_ms * tenability.AIR_DENSITY_KGM3,
        half_active_length_m=scoped.active_length_m / 2.0,
        trees=_trees(geom),
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
    manual = design.zones.manual_activation_s
    events["t_activate_s"] = (manual if manual is not None
                              else t_s + design.zones.activation_delay_s)
    events["t_full_pressure_s"] = events["t_activate_s"] + design.zones.pump_ramp_s


def _flow_fraction(zones: Zones, events: dict, t_s: float) -> float:
    """Zero until the valves open, then the pumps ramp linearly to full flow."""
    activate = events["t_activate_s"]
    if activate is None or t_s < activate:
        return 0.0
    ramp = zones.pump_ramp_s
    return min((t_s - activate) / ramp, 1.0) if ramp > 0 else 1.0


def _mist_water_ratio(mist: MistEffect, q_conv_kw: float, air_kgs: float) -> float:
    """kg of evaporated spray water per kg of air, from what the mist cooled.

    Recovered from `MistEffect.chi_cool` rather than modelled again, so the
    water reported as humidity is exactly the water charged for as cooling.
    `chi_cool` is capped by calibration's `chi_cool_max`, so where that cap
    binds this UNDER-states the evaporated mass -- an under-report of humidity,
    never an over-report.
    """
    if q_conv_kw <= 0 or air_kgs <= 0:
        return 0.0
    return mist.chi_cool * q_conv_kw / MIST_EVAPORATION_ENTHALPY_KJKG / air_kgs


def _sample_stations(scene: _Scene, field: ThermalField, mist: MistEffect,
                     vent: VentilationState, species: tenability.Species,
                     mist_water_ratio: float, fed_tox: dict[str, float],
                     fed_heat: dict[str, float]) -> dict[str, StationSample]:
    """What the instruments at each Annex 7 Table 5 location read this step.

    `criteria.INSTRUMENTS` decides which of the newly reported quantities exist
    at each: a quantity Table 5 does not instrument there is left absent, not
    zeroed, so it can never be silently averaged or compared as if it were a
    reading. `fed_tox` and `fed_heat` are the run's dose accumulators and are
    advanced here by this step's increment.

    Heights. The thermocouple ladder is `criteria.thermocouple_heights_m`; the
    flux gauge is at HEAT_FLUX_HEIGHT_M (section 6.4.2). ISO 13571's thermal
    dose sums a convective term from the gas temperature and a radiant term from
    the incident flux and names no height for either, so each term takes its own
    instrument's height -- which keeps the dose reproducible from the two
    numbers this run reports. The opacimeter height is VISIBILITY_HEIGHT_M
    (section 6.4.5); `local.soot_gm3` already carries the stratification factor,
    which `thermal` holds flat below breathing height, so a gauge at 1.5 m reads
    the same layer as one at 1.8 m -- asserted in tests/test_annex7_conformance
    rather than taken on trust from this comment.
    """
    kappa_mist = (1.0 - mist.tau_mist) / max(scene.half_active_length_m, 1.0)
    samples: dict[str, StationSample] = {}
    for name, x_m in STATIONS.items():
        kit, tree = INSTRUMENTS[name], scene.trees[name]
        upstream_clear = x_m < 0 and abs(x_m) > vent.backlayer_m
        temps = ((scene.ambient_c,) * len(tree.heights_m) if upstream_clear
                 else field.gas_temp_profile_c(x_m, tree.heights_m))
        temp = temps[tree.breathing_index]
        flux = field.radiant_flux_kwm2(x_m, HEAT_FLUX_HEIGHT_M, mist.tau_mist)
        local = AMBIENT_SPECIES if upstream_clear else species
        fed_tox[name] += tenability.fed_tox_increment(local, DT_S)
        fed_heat[name] += tenability.fed_heat_increment(temp, flux, DT_S)
        in_zone = abs(x_m) <= scene.half_active_length_m
        # Upstream of the backlayering front neither the fire's water nor the
        # spray's has reached the station; it is still tunnel air.
        water = local.h2o_ratio + (0.0 if upstream_clear else mist_water_ratio)
        samples[name] = StationSample(
            temp_c=temp, temps_c=temps, heights_m=tree.heights_m, flux_kwm2=flux,
            visibility_m=tenability.visibility_m(local.soot_gm3,
                                                 kappa_mist if in_zone else 0.0),
            fed_tox=fed_tox[name], fed_heat=fed_heat[name], co_ppm=local.co_ppm,
            co2_pct=local.co2_pct if kit.carbon_dioxide else None,
            o2_pct=local.o2_pct if kit.oxygen else None,
            relative_humidity_pct=(
                tenability.relative_humidity_pct(temp, scene.ambient_c,
                                                 scene.ambient_rh_pct, water)
                if kit.relative_humidity else None),
            # Section 6.4.4 measures air velocity "over whole cross-section" at
            # U340, U45, D45 and D215. This model is one-dimensional with a
            # single free area, so continuity gives it ONE velocity for the
            # whole tunnel: the fire-throttled `u_eff_ms`, not the fans'
            # undisturbed `u_fan_ms`. Buoyancy opposes the fans in the system
            # curve and so reduces the flow through every section including
            # U340, 340 m upstream; `u_fan_ms` is the fans' duty, not anything a
            # probe reads. The thermal expansion that would raise the true
            # velocity at D45 and D215 is NOT resolved -- there is no density
            # field to take it from, and the breathing-height gas temperature is
            # not the bulk mean -- so no profile is fabricated and the value is
            # a lower bound downstream, exact upstream.
            air_velocity_ms=vent.u_eff_ms if kit.air_velocity else None)
    return samples


def _target_flux_kwm2(scene: _Scene, field: ThermalField, mist: MistEffect) -> float:
    distance = scene.design.fire.target_distance_m
    flux = field.radiant_flux_kwm2(distance, scene.fire_top_m / 2.0, mist.tau_mist)
    if field.flame_tip_x_m >= distance:
        return max(flux, FLAME_CONTACT_FLUX_KWM2)
    return flux


def target_exposure_s(previous_s: float, target_flux_kwm2: float, dt_s: float) -> float:
    """Running time the target has spent CONTINUOUSLY above the ignition flux.

    SOLIT2 Annex 7 section 7.2.1 is a sustained-exposure rule, so this resets to
    zero the moment the flux falls back: a flux that crosses the threshold
    briefly and repeatedly never accumulates towards ignition, however high its
    peak. Accumulated the same way the fire model accumulates `wet_time_s`.
    """
    if target_flux_kwm2 > WOOD_PILOTED_IGNITION_KWM2:
        return previous_s + dt_s
    return 0.0


def _require_detection(design: Design, events: dict) -> None:
    """A run in which the detector never trips has not modelled the system at all."""
    if events["t_detect_s"] is not None:
        return
    raise RuntimeError(
        f"the fire never reached the {design.detection.threshold_c} C detection "
        f"threshold within {design.zones.duration_min} minutes; check the fire preset"
    )


def _pipe_temp_c(previous_c: float, ceiling_c: float, flow_fraction: float) -> float:
    """Pipe surface chases the ceiling, capped once water is flowing through it."""
    target = min(ceiling_c, PIPE_WATER_FILLED_CAP_C) if flow_fraction > 0 else ceiling_c
    return previous_c + (target - previous_c) * DT_S / PIPE_TIME_CONSTANT_S


def _structure_exposure_length_m(scene: _Scene, field: ThermalField) -> float:
    """Annex 7 section 7.2.4: how much ceiling this step held above the threshold."""
    return thermal.exposure_length_m(field, scene.design.ahj.structure_temp_threshold_c,
                                     STRUCTURE_SCAN_MIN_M, STRUCTURE_SCAN_MAX_M)


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
    exposure_s = 0.0

    total_steps = int(scene.design.zones.duration_min * 60 / DT_S)
    for _ in range(total_steps):
        state = fire_mod.step(scene.model, state, DT_S, mist)
        q_conv = fire_mod.convective_kw(scene.model, state.hrr_mw)
        vent = ventilation.evaluate(scene.geom, velocity_ms, q_conv)
        _detect(scene, events, state.hrr_mw, state.t_s)
        flow_fraction = _flow_fraction(scene.design.zones, events, state.t_s)

        field = thermal.field(scene.geom, scene.model, state, vent, mist, scene.fire_top_m,
                              scene.fire_base_m, scene.design.fire.footprint.length_m,
                              scene.design.fire.footprint.width_m, scene.ambient_c)
        mist = mist_mod.evaluate(scene.design, scene.geom, scene.positions, scene.envelope,
                                 scene.fire_top_m, vent.u_eff_ms, field.ceiling_excess_k,
                                 q_conv, flow_fraction)

        species = tenability.species_at(scene.model, state.hrr_mw, scene.air_m3s,
                                        field.strat_factor)
        water_ratio = _mist_water_ratio(mist, q_conv, scene.air_kgs)
        samples = _sample_stations(scene, field, mist, vent, species, water_ratio,
                                   fed_tox, fed_heat)

        ceiling = field.ceiling_temp_c(0.0)
        pipe_temp = _pipe_temp_c(pipe_temp, ceiling, flow_fraction)
        peak_hrr = _note_events(scene, events, state, vent, peak_hrr)

        target_flux = _target_flux_kwm2(scene, field, mist)
        exposure_s = target_exposure_s(exposure_s, target_flux, DT_S)

        steps.append(StepRecord(
            t_s=state.t_s, hrr_mw=state.hrr_mw, hrr_free_mw=state.hrr_free_mw,
            ceiling_temp_c=ceiling, lining_temp_c=ceiling, pipe_temp_c=pipe_temp,
            target_flux_kwm2=target_flux, u_eff_ms=vent.u_eff_ms,
            u_critical_ms=vent.u_critical_ms, backlayer_m=vent.backlayer_m,
            water_lpm=scene.design.flow_lpm * flow_fraction,
            pools_remaining=state.pools_remaining, mist=mist, stations=samples,
            target_exposure_s=exposure_s,
            structure_exposure_length_m=_structure_exposure_length_m(scene, field)))

    _require_detection(design, events)
    return RunTrace(tuple(steps), events, section, velocity_ms)

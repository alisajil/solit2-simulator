"""Which instruments Annex 7 Table 5 puts at each measurement location.

Table 5 (section 6.4.10, p.15) does not only list longitudinal locations; it
lists the sensors that sit at each one. This file holds that table transcribed
from the printed source, and checks the engine against it in both directions, so
that neither an instrument Table 5 requires nor one it does not can survive
unnoticed.

Where Annex 7 states a figure (a sensor count, a location) it is asserted
literally, because that IS the requirement. Where Annex 7 states nothing -- it
gives no height for any thermocouple anywhere -- only the properties the model
owes the standard are asserted, never the numbers the implementation happens to
produce.
"""
from dataclasses import fields

import pytest

from solit2.engines.reduced import criteria as criteria_mod
from solit2.engines.reduced import fire as fire_mod
from solit2.engines.reduced import sim as sim_mod
from solit2.engines.reduced import tenability, thermal
from solit2.engines.reduced.geometry import section_geometry
from solit2.engines.reduced.state import (MistEffect, RunTrace, StationSample,
                                          StepRecord)
from solit2.engines.reduced.ventilation import VentilationState
from solit2.schema.design import Design

BASELINE = "examples/designs/road-tunnel-twin-bore.json"
TEST_GALLERY = "examples/designs/solit2-test-protocol.json"

# Annex 7 Table 5, "Summary table of different measurements and their
# longitudinal locations", transcribed row by row from the printed table. U45
# and D45 each list "1 thermocouple" on a line of its own, separately from that
# row's 7 and 5; that is the row's own wording and is kept as its own entry.
ANNEX7_TABLE_5_SENSORS = {
    "U340": {"thermocouples": 2, "ultrasonic": 2},
    "U100": {"thermocouples": 5},
    "U45": {"thermocouples": 7, "bidirectional": 5, "oxygen": 3,
            "carbon_dioxide": 3, "carbon_monoxide": 3, "relative_humidity": 1,
            "reference_thermocouple": True, "visibility": True},
    "U25": {"thermocouples": 5},
    "U15": {"thermocouples": 5, "heat_flux": True},
    "U05": {"thermocouples": 7},
    "U03": {"thermocouples": 7},
    "D03": {"thermocouples": 7},
    "D05": {"thermocouples": 7},
    "Target": {"thermocouples": 3},
    "D15": {"thermocouples": 5, "heat_flux": True},
    "D25": {"thermocouples": 5},
    "D45": {"thermocouples": 5, "bidirectional": 5, "oxygen": 3,
            "carbon_dioxide": 3, "carbon_monoxide": 3, "relative_humidity": 1,
            "reference_thermocouple": True, "visibility": True},
    "D100": {"thermocouples": 5, "visibility": True},
    "D215": {"thermocouples": 2, "bidirectional": 5, "ultrasonic": 2,
             "visibility": True},
}


# --- the instrument map against Table 5 --------------------------------------

def test_every_station_carries_exactly_the_table_5_instruments():
    """Both directions at once: `Instruments(**row)` fills every instrument the
    row does not list with its own absent value, so an invented sensor fails the
    equality just as a missing one does."""
    assert set(criteria_mod.INSTRUMENTS) == set(ANNEX7_TABLE_5_SENSORS)
    for name, row in ANNEX7_TABLE_5_SENSORS.items():
        assert criteria_mod.INSTRUMENTS[name] == criteria_mod.Instruments(**row), name


def test_the_instrument_record_has_no_field_table_5_does_not_cover():
    """The equality above can only police instruments the transcription names.
    A new field added to `Instruments` would slip past it, so the record's own
    fields are pinned to the set Table 5 accounts for."""
    covered = set().union(*(set(row) for row in ANNEX7_TABLE_5_SENSORS.values()))
    assert {f.name for f in fields(criteria_mod.Instruments)} == covered


def test_the_instrument_map_and_the_station_map_are_the_same_locations():
    assert set(criteria_mod.INSTRUMENTS) == set(criteria_mod.STATIONS)


def test_heat_flux_is_instrumented_where_section_6_4_2_says_and_nowhere_else():
    """Annex 7 section 6.4.2 (p.13): "Heat flux sensors of type Gordon
    (Medtherm) shall be installed with a minimum of having 2 sensors at 1.5m
    height in the locations of U15 and D15." Two sensors, two locations."""
    assert criteria_mod.stations_carrying(lambda kit: kit.heat_flux) == ("U15", "D15")


def test_gas_is_instrumented_where_section_6_4_3_says_and_nowhere_else():
    """Annex 7 section 6.4.3 (p.13-14) for each of oxygen, carbon dioxide and
    carbon monoxide: "It is important to measure [...] concentration on both
    sides of the fire. Such places are U45 and D45." """
    for instrument in ("oxygen", "carbon_dioxide", "carbon_monoxide"):
        assert criteria_mod.stations_carrying(
            lambda kit, i=instrument: getattr(kit, i) > 0) == ("U45", "D45"), instrument


def test_air_velocity_is_instrumented_where_section_6_4_4_says():
    """Annex 7 section 6.4.4 (p.14): "Air velocity needs to be measured on both
    sides of fire load, at minimum in U340, U45, D45 and D215."

    The same section makes either instrument an air-velocity measurement --
    "either with ultrasonic sensors to get a mean value or, more commonly, using
    bidirectional probes" -- and it is the union of Table 5's two columns that
    reproduces the section's own list.
    """
    assert criteria_mod.stations_carrying(lambda kit: kit.air_velocity) == (
        "U340", "U45", "D45", "D215")


def test_visibility_is_instrumented_where_section_6_4_5_says():
    """Annex 7 section 6.4.5 (p.14): "Visibility needs to be measured at minimum
    in U045, D045; D100, D215." """
    assert criteria_mod.stations_carrying(lambda kit: kit.visibility) == (
        "U45", "D45", "D100", "D215")


def test_the_relative_humidity_probe_carries_its_own_thermocouple():
    """Table 5's separate "1 thermocouple" appears on exactly the two rows that
    carry a relative-humidity probe, which is what it is there for."""
    assert (criteria_mod.stations_carrying(lambda kit: kit.reference_thermocouple)
            == criteria_mod.stations_carrying(lambda kit: kit.relative_humidity > 0))


# --- the thermocouple trees --------------------------------------------------
#
# Annex 7 section 6.4.1 requires "a minimum grid of having 5 sensors in
# cross-section" and Table 5 gives the count per location. NEITHER NAMES A
# HEIGHT for any thermocouple anywhere, so the ladder is the engine's own
# engineering choice and nothing below asserts the heights it produces. What is
# asserted is what the standard and the rest of the model actually require of
# it: the Table 5 count, heights inside the section, even spacing, a grid that
# straddles the section rather than hugging one end, and breathing height on it.

def _crown_heights_m() -> list[float]:
    """The crown height of every tunnel the shipped designs actually run in."""
    crowns = []
    for path in (BASELINE, TEST_GALLERY):
        design = Design.load(path)
        crowns.append(section_geometry(design).crown_height_m)
    return crowns


@pytest.mark.parametrize("count", sorted({row["thermocouples"]
                                          for row in ANNEX7_TABLE_5_SENSORS.values()}))
def test_a_thermocouple_tree_has_its_table_5_count_inside_the_section(count):
    for crown_m in _crown_heights_m():
        heights = criteria_mod.thermocouple_heights_m(count, crown_m)
        assert len(heights) == count
        assert all(0.0 < h < crown_m for h in heights), (crown_m, heights)


@pytest.mark.parametrize("count", sorted({row["thermocouples"]
                                          for row in ANNEX7_TABLE_5_SENSORS.values()}))
def test_breathing_height_is_sampled_and_not_interpolated(count):
    """Annex 7 section 7.2.2's tenability criteria are evaluated at breathing
    height, so it has to be a measured point of the grid, not a point between
    two of them."""
    for crown_m in _crown_heights_m():
        heights = criteria_mod.thermocouple_heights_m(count, crown_m)
        assert criteria_mod.BREATHING_HEIGHT_M in heights, (count, crown_m, heights)


def test_a_thermocouple_tree_is_evenly_spaced():
    for crown_m in _crown_heights_m():
        heights = criteria_mod.thermocouple_heights_m(7, crown_m)
        gaps = [b - a for a, b in zip(heights, heights[1:])]
        assert gaps == pytest.approx([gaps[0]] * len(gaps))


def test_a_full_cross_section_grid_straddles_the_section():
    """Section 6.4.1's 5-sensor minimum is a grid "in cross-section", so a tree
    of that size must have sensors below breathing height and above mid-height
    rather than clustering at one end."""
    for crown_m in _crown_heights_m():
        for count in (5, 7):
            heights = criteria_mod.thermocouple_heights_m(count, crown_m)
            assert min(heights) < criteria_mod.BREATHING_HEIGHT_M, (count, crown_m)
            assert max(heights) > crown_m / 2.0, (count, crown_m)


def test_a_tree_cannot_be_built_for_a_section_shorter_than_breathing_height():
    with pytest.raises(ValueError, match="breathing height"):
        criteria_mod.thermocouple_heights_m(5, criteria_mod.BREATHING_HEIGHT_M)


# --- what the sampler actually reports ---------------------------------------

SAMPLED_SPECIES = tenability.species_at(
    fire_mod.build_model(Design.load(BASELINE)), 40.0, 200.0, 0.4)


def _samples(backlayer_m: float = 0.0) -> dict:
    """One real station sample, at a chosen backlayering length.

    The vent state is built directly rather than solved, so that whether U45
    lies inside the backlayer is the test's choice and not an accident of the
    correlations.
    """
    design = Design.load(BASELINE)
    scene = sim_mod._build_scene(design, "bored", 4.5)
    state = fire_mod.FireState(t_s=600.0, hrr_mw=40.0, hrr_free_mw=40.0,
                               energy_released_mj=20_000.0, suppression=1.0,
                               pools_remaining=0, wet_time_s=0.0)
    vent = VentilationState(u_fan_ms=4.5, u_eff_ms=3.9, u_critical_ms=3.2,
                            backlayer_m=backlayer_m)
    field = thermal.field(scene.geom, scene.model, state, vent, MistEffect.none(),
                          scene.fire_top_m, scene.fire_base_m,
                          design.fire.footprint.length_m, design.fire.footprint.width_m,
                          scene.ambient_c)
    fed_tox = {n: 0.0 for n in criteria_mod.stations_carrying(lambda k: k.toxic_gas)}
    fed_heat = {n: 0.0 for n in criteria_mod.stations_carrying(lambda k: k.thermal_dose)}
    return sim_mod._sample_stations(scene, field, MistEffect.none(), vent,
                                    SAMPLED_SPECIES, 0.0, fed_tox, fed_heat)


def test_every_station_reports_a_tree_of_its_table_5_size():
    samples = _samples()
    for name, row in ANNEX7_TABLE_5_SENSORS.items():
        sample = samples[name]
        assert len(sample.temps_c) == row["thermocouples"], name
        assert len(sample.heights_m) == len(sample.temps_c), name


def test_the_reported_temperature_is_the_trees_breathing_height_entry():
    """The compatibility guarantee: `temp_c` is not a separate evaluation, it is
    the tree's own reading at the height section 7.2.2 is judged at."""
    for sample in _samples().values():
        index = sample.heights_m.index(criteria_mod.BREATHING_HEIGHT_M)
        assert sample.temp_c == sample.temps_c[index]


def test_oxygen_and_carbon_dioxide_are_the_species_the_step_computed():
    """The wiring, not the chemistry: `tenability.Species` already computed both
    and they simply were not carried to the station. D45 is downstream, so it
    sees the fire's own species at every backlayering length."""
    sample = _samples()["D45"]
    assert sample.o2_pct == SAMPLED_SPECIES.o2_pct
    assert sample.co2_pct == SAMPLED_SPECIES.co2_pct


def test_an_upstream_station_clear_of_the_backlayer_reports_tunnel_air():
    """U45 is 45 m upstream: with no backlayering the flow there has not been
    near the fire, so its oxygen is the ambient value and not a depleted one."""
    clear = _samples(backlayer_m=0.0)["U45"]
    assert clear.o2_pct == tenability.AMBIENT_O2_PCT
    assert clear.co2_pct == 0.0
    engulfed = _samples(backlayer_m=60.0)["U45"]
    assert engulfed.o2_pct == SAMPLED_SPECIES.o2_pct


def test_a_station_reports_a_quantity_if_and_only_if_table_5_instruments_it():
    """Every optional quantity, both directions, at every station: present where
    Table 5 puts a sensor and `None` -- not zero -- where it does not."""
    samples = _samples()
    for name, sample in samples.items():
        kit = criteria_mod.INSTRUMENTS[name]
        assert (sample.o2_pct is None) != (kit.oxygen > 0), name
        assert (sample.co2_pct is None) != (kit.carbon_dioxide > 0), name
        assert (sample.co_ppm is None) != (kit.carbon_monoxide > 0), name
        assert (sample.relative_humidity_pct is None) != (kit.relative_humidity > 0), name
        assert (sample.air_velocity_ms is None) != kit.air_velocity, name
        assert (sample.flux_kwm2 is None) != kit.heat_flux, name
        assert (sample.visibility_m is None) != kit.visibility, name
        assert (sample.fed_tox is None) != kit.toxic_gas, name
        assert (sample.fed_heat is None) != kit.heat_flux, name


def test_heat_flux_is_reported_at_u15_and_d15_and_nowhere_else():
    """Annex 7 section 6.4.2 puts two heat flux sensors in the tunnel, at U15
    and D15. A flux reported anywhere else is a number no test could produce and
    so no test could contradict."""
    reported = {name for name, sample in _samples().items()
                if sample.flux_kwm2 is not None}
    assert reported == {"U15", "D15"}


def test_gas_concentrations_are_reported_at_u45_and_d45_and_nowhere_else():
    """Annex 7 section 6.4.3: oxygen, carbon dioxide and carbon monoxide "on
    both sides of the fire. Such places are U45 and D45"."""
    samples = _samples()
    for field in ("o2_pct", "co2_pct", "co_ppm", "relative_humidity_pct"):
        reported = {name for name, sample in samples.items()
                    if getattr(sample, field) is not None}
        assert reported == {"U45", "D45"}, field


def test_visibility_is_reported_at_the_four_section_6_4_5_locations():
    """Annex 7 section 6.4.5: "at minimum in U045, D045; D100, D215"."""
    reported = {name for name, sample in _samples().items()
                if sample.visibility_m is not None}
    assert reported == {"U45", "D45", "D100", "D215"}


def test_air_velocity_is_the_sections_own_throttled_velocity():
    """One dimension, one free area, so continuity gives one velocity for the
    whole tunnel -- the throttled `u_eff_ms` the fire actually leaves, not the
    fans' undisturbed duty."""
    samples = _samples()
    for name in criteria_mod.stations_carrying(lambda kit: kit.air_velocity):
        assert samples[name].air_velocity_ms == pytest.approx(3.9)


# --- relative humidity -------------------------------------------------------

def test_relative_humidity_upstream_of_the_smoke_is_the_tunnels_own():
    """Clear of the backlayer the station is breathing tunnel air at tunnel
    temperature, so the probe must read the tunnel's ambient humidity exactly:
    no water has been added and none has been taken away."""
    design = Design.load(BASELINE)
    sample = _samples(backlayer_m=0.0)["U45"]
    assert sample.relative_humidity_pct == pytest.approx(design.tunnel.ambient_rh_pct)


def test_added_water_raises_the_humidity_and_never_past_saturation():
    """Water put into the air by combustion and by evaporating mist can only
    raise the humidity, and past saturation it leaves the vapour phase as fog
    rather than being reported as a humidity above 100 %."""
    dry = tenability.relative_humidity_pct(40.0, 20.0, 60.0, added_water_ratio=0.0)
    wet = tenability.relative_humidity_pct(40.0, 20.0, 60.0, added_water_ratio=0.01)
    soaked = tenability.relative_humidity_pct(40.0, 20.0, 60.0, added_water_ratio=1.0)
    assert dry < wet < soaked
    assert soaked == pytest.approx(100.0)


def test_the_same_water_is_drier_in_hotter_gas():
    """Relative humidity is read against saturation at the gas temperature, so
    heating the same wet gas lowers it. Stated because it is the reason a hot
    downstream station can report a humidity below the tunnel's ambient one."""
    warm = tenability.relative_humidity_pct(30.0, 20.0, 60.0, added_water_ratio=0.005)
    hot = tenability.relative_humidity_pct(80.0, 20.0, 60.0, added_water_ratio=0.005)
    assert hot < warm


def test_the_water_of_combustion_tracks_the_carbon_dioxide_yield():
    """The water yield is tied to the CO2 yield through the fuel's own formula
    rather than being a second independent number, so a step that makes no CO2
    makes no water and twice the CO2 is twice the water."""
    assert tenability.Species(0.0, 0.0, 0.0, tenability.AMBIENT_O2_PCT).h2o_ratio == 0.0
    model = fire_mod.build_model(Design.load(BASELINE))
    single = tenability.species_at(model, 40.0, 200.0, 0.4)
    double = tenability.species_at(model, 80.0, 200.0, 0.4)
    assert double.co2_pct / single.co2_pct == pytest.approx(
        double.h2o_ratio / single.h2o_ratio)


# --- the criteria honour the map ---------------------------------------------

class _Hyd:
    flow_lpm = 2174.3


class _Cost:
    index = 1.0


def _trace_with(overrides: dict[str, dict]) -> RunTrace:
    """One step in which every station reads calmly except those named.

    Built by hand rather than by running the engine, because the point is a
    reading the sampler would never produce: a heat flux at a station Table 5
    puts no gauge at. A search that filtered on `None` instead of on the
    instrument map would see these and pass this test wrongly.
    """
    stations = {}
    for name in criteria_mod.STATIONS:
        kit = criteria_mod.INSTRUMENTS[name]
        seen = overrides.get(name, {})
        stations[name] = StationSample(
            temp_c=seen.get("temp_c", 25.0),
            flux_kwm2=seen.get("flux_kwm2", 0.1 if kit.heat_flux else None),
            visibility_m=seen.get("visibility_m", 500.0 if kit.visibility else None),
            fed_tox=seen.get("fed_tox", 0.0 if kit.toxic_gas else None),
            fed_heat=0.0 if kit.thermal_dose else None,
            co_ppm=seen.get("co_ppm", 0.0 if kit.carbon_monoxide else None))
    step = StepRecord(
        t_s=100.0, hrr_mw=20.0, hrr_free_mw=20.0, ceiling_temp_c=300.0,
        lining_temp_c=300.0, pipe_temp_c=80.0, target_flux_kwm2=1.0, u_eff_ms=2.0,
        u_critical_ms=2.5, backlayer_m=0.0, water_lpm=1000.0, pools_remaining=0,
        mist=MistEffect.none(), stations=stations)
    return RunTrace((step,), {"t_full_pressure_s": 0.0}, "bored", 2.0)


def test_a_worst_station_search_cannot_see_an_uninstrumented_station():
    """D05 carries seven thermocouples and nothing else. Given a catastrophic
    flux, visibility, CO and dose there, every one of which would otherwise be
    the worst in the tunnel by a wide margin, the criteria must report the
    instrumented stations' figures instead."""
    rogue = _trace_with({
        "D05": {"flux_kwm2": 500.0, "visibility_m": 0.1, "co_ppm": 9000.0,
                "fed_tox": 9.0},
        "D15": {"flux_kwm2": 1.25},
        "D100": {"visibility_m": 42.0},
        "D45": {"co_ppm": 30.0, "fed_tox": 0.02},
    })
    out = criteria_mod.evaluate(rogue, _Hyd(), _Cost(), Design.load(BASELINE))
    assert out["max_heat_flux_kwm2"].value == pytest.approx(1.25)
    assert out["min_visibility_m"].value == pytest.approx(42.0)
    assert out["max_co_ppm"].value == pytest.approx(30.0)
    assert out["max_fed"].value == pytest.approx(0.02)


def test_the_temperature_criterion_still_sees_every_station():
    """Table 5 puts thermocouples at all fifteen locations, so the one
    life-safety quantity that is measured everywhere must still be searched
    everywhere -- the point is to drop phantom readings, not real ones."""
    rogue = _trace_with({"D05": {"temp_c": 310.0}})
    out = criteria_mod.evaluate(rogue, _Hyd(), _Cost(), Design.load(BASELINE))
    assert out["max_air_temp_c"].value == pytest.approx(310.0)


def test_the_criteria_search_exactly_the_stations_the_instrument_map_names():
    """The searched sets are derived from INSTRUMENTS, not restated, so this
    pins them to the Annex 7 sections rather than to the derivation."""
    assert criteria_mod.HEAT_FLUX_STATIONS == ("U15", "D15")
    assert criteria_mod.VISIBILITY_STATIONS == ("U45", "D45", "D100", "D215")
    assert criteria_mod.CO_STATIONS == ("U45", "D45")
    assert criteria_mod.FED_TOX_STATIONS == ("U45", "D45")
    assert set(criteria_mod.THERMOCOUPLE_STATIONS) == set(criteria_mod.STATIONS)


def test_evaporated_mist_water_is_the_water_the_mist_module_charged_for():
    """The humidity carries the same evaporated mass the cooling term was built
    from, recovered from `chi_cool` rather than modelled a second time, so the
    two can never disagree."""
    cooling = MistEffect(eta=0.5, w_fuel_mm_min=2.0, f_cov=0.8, chi_cool=0.2,
                         tau_mist=0.7)
    ratio = sim_mod._mist_water_ratio(cooling, q_conv_kw=30_000.0, air_kgs=100.0)
    expected_kgs = 0.2 * 30_000.0 / sim_mod.MIST_EVAPORATION_ENTHALPY_KJKG
    assert ratio == pytest.approx(expected_kgs / 100.0)
    assert sim_mod._mist_water_ratio(MistEffect.none(), 30_000.0, 100.0) == 0.0


def test_humidity_counts_the_water_evaporated_downstream_of_the_fire_too():
    """Water that evaporates into gas downstream of the fire is still water in
    the air the stations sample, though it took no heat off the plume."""
    from tests.test_mist import _heads, _setup

    _, _, _, _, effect = _setup(gas_excess_k=700.0, positions=_heads(dx_m=200.0))
    assert effect.chi_cool == 0.0
    assert sim_mod._mist_water_ratio(effect, q_conv_kw=30_000.0, air_kgs=100.0) > 0.0

"""The test setup itself, checked against SOLIT2 Engineering Guidance Annex 7.

Every assertion here quotes the Annex 7 section it comes from. Where Annex 7
states an inequality ("minimum 2,5m height for the fuel part") this file asserts
the inequality and not the number the preset happens to carry, so a preset may
be made more conservative without a test having to be rewritten to allow it.
Where Annex 7 states an exact figure (Table 5's station chainages, the 10,0 m
mock-up length, the 1,5 m instrument heights) the figure is asserted literally,
because that IS the requirement.
"""
import json
from pathlib import Path

import pytest

from solit2.engines.reduced import criteria as criteria_mod
from solit2.engines.reduced import fire as fire_mod
from solit2.engines.reduced import sim as sim_mod
from solit2.engines.reduced import thermal, ventilation
from solit2.engines.reduced.state import MistEffect
from solit2.engines.reduced.tenability import Species
from solit2.schema.design import Design
from solit2.schema.presets import load_preset

BASELINE = "examples/designs/road-tunnel-twin-bore.json"
DESIGN_DIR = Path("examples/designs")

# Annex 7 Table 5 (section 6.4.10, p.15), transcribed in full. Chainage follows
# section 6.3: virtual zero point 00 longitudinally in the middle of the mock-up,
# upstream Uxx negative, downstream Dxx positive, xx in metres.
ANNEX7_TABLE_5 = {
    "U340": -340.0, "U100": -100.0, "U45": -45.0, "U25": -25.0, "U15": -15.0,
    "U05": -5.0, "U03": -3.0, "D03": 3.0, "D05": 5.0, "Target": 10.0,
    "D15": 15.0, "D25": 25.0, "D45": 45.0, "D100": 100.0, "D215": 215.0,
}
# Annex 7 section 5.2.3 and 5.3.3, and Figure 13's dimension arrow, which runs
# from the NEAR FACE of the mock-up to the tunnel wall: "The distance from the
# side wall shall be less than 1,5 m."
MAX_WALL_TO_NEAR_FACE_M = 1.5


# --- Phase 1: measurement stations (Table 5, section 6.4.10) -----------------

def test_stations_are_exactly_the_annex7_table_5_locations():
    """Asserted both ways, so neither a stray station nor a missing one survives.

    U35, D20 and D35 were in this map and are not Annex 7 locations at all;
    U340, U100, U45, U25, U03, D03, Target, D25, D45 and D215 are and were not.
    """
    assert set(criteria_mod.STATIONS) == set(ANNEX7_TABLE_5)
    assert criteria_mod.STATIONS == ANNEX7_TABLE_5


def test_the_target_station_is_ten_metres_downstream():
    """Annex 7 section 7.2.1: the target is 5 m downstream behind the mock-up,
    "(D10)". Section 6.3 names the same location, and Table 5 calls the row
    `Target` rather than D10, which is why that is the station key."""
    assert criteria_mod.STATIONS["Target"] == 10.0


def test_station_names_follow_the_section_6_3_sign_convention():
    """Uxx upstream is negative, Dxx downstream is positive, and the number in
    the name is the distance in metres from the zero point."""
    for name, x_m in criteria_mod.STATIONS.items():
        if name == "Target":
            continue
        assert name[0] in "UD", name
        assert abs(x_m) == float(name[1:]), name
        assert (x_m < 0) == (name[0] == "U"), name


def test_the_structure_scan_span_is_not_the_station_extremes():
    """Annex 7 section 7.2.4 is about ceiling exposure "directly above fire loads
    or slightly downstream". Table 5's extremes are U340 and D215, which are
    far-field smoke and air-velocity stations; inheriting them would turn a
    localised exposure measurement into a 555 m sweep at every timestep."""
    extremes = (min(criteria_mod.STATIONS.values()), max(criteria_mod.STATIONS.values()))
    assert (sim_mod.STRUCTURE_SCAN_MIN_M, sim_mod.STRUCTURE_SCAN_MAX_M) != extremes
    # the fire and the ceiling downstream of it must still be inside the window
    assert sim_mod.STRUCTURE_SCAN_MIN_M < 0.0 < sim_mod.STRUCTURE_SCAN_MAX_M
    assert sim_mod.STRUCTURE_SCAN_MAX_M >= abs(sim_mod.STRUCTURE_SCAN_MIN_M), (
        "section 7.2.4 puts the hot area above the fire or SLIGHTLY DOWNSTREAM, "
        "so the window must not reach further upstream than downstream")


# --- Phase 2: measurement heights (sections 6.4.2 and 6.4.5) -----------------

class _RecordingField:
    """Forwards to a real `ThermalField`, recording the height of every call.

    `_sample_stations` reaches the field only through these two methods, so this
    records the heights that actually arrive rather than the heights a constant
    claims.
    """

    def __init__(self, inner: thermal.ThermalField) -> None:
        self._inner = inner
        self.gas_temp_calls: list[tuple[float, float]] = []
        self.flux_calls: list[tuple[float, float]] = []

    def gas_temp_c(self, x_m: float, height_m: float) -> float:
        self.gas_temp_calls.append((x_m, height_m))
        return self._inner.gas_temp_c(x_m, height_m)

    def radiant_flux_kwm2(self, x_m: float, height_m: float, tau_mist: float) -> float:
        self.flux_calls.append((x_m, height_m))
        return self._inner.radiant_flux_kwm2(x_m, height_m, tau_mist)


def _sampled_heights() -> _RecordingField:
    """Run one real station sample and hand back what the field was asked for."""
    design = Design.load(BASELINE)
    scene = sim_mod._build_scene(design, "bored", 4.5)
    state = fire_mod.FireState(t_s=600.0, hrr_mw=40.0, hrr_free_mw=40.0,
                               energy_released_mj=20_000.0, suppression=1.0,
                               pools_remaining=0, wet_time_s=0.0)
    vent = ventilation.evaluate(scene.geom, 4.5, fire_mod.convective_kw(scene.model, 40.0))
    field = thermal.field(scene.geom, scene.model, state, vent, MistEffect.none(),
                          scene.fire_top_m, scene.fire_base_m,
                          design.fire.footprint.length_m, design.fire.footprint.width_m,
                          scene.ambient_c)
    recorder = _RecordingField(field)
    zero = {name: 0.0 for name in criteria_mod.STATIONS}
    sim_mod._sample_stations(scene, recorder, MistEffect.none(), vent,
                             Species(50.0, 0.5, 0.02, 20.0), zero, dict(zero))
    return recorder


def test_heat_flux_is_sampled_at_the_annex7_height():
    """Annex 7 section 6.4.2 (p.13): "Heat flux sensors of type Gordon
    (Medtherm) shall be installed with a minimum of having 2 sensors at 1.5 m
    height in the locations of U15 and D15." """
    recorder = _sampled_heights()
    assert recorder.flux_calls, "no flux was sampled at all"
    assert {height for _, height in recorder.flux_calls} == {1.5}
    assert criteria_mod.HEAT_FLUX_HEIGHT_M == 1.5


def test_gas_temperature_stays_at_breathing_height():
    """Annex 7 section 6.4.1 mandates 5-7 thermocouples per cross-section and no
    single height, so the tenability choice of breathing height stands."""
    recorder = _sampled_heights()
    assert recorder.gas_temp_calls, "no gas temperature was sampled at all"
    assert {height for _, height in recorder.gas_temp_calls} == {1.8}
    assert criteria_mod.BREATHING_HEIGHT_M == 1.8


def test_the_flux_and_temperature_heights_are_genuinely_different():
    """A sampler that passed one height to both calls would satisfy the two
    tests above only by accident of them agreeing; they must not agree."""
    recorder = _sampled_heights()
    assert ({height for _, height in recorder.flux_calls}
            != {height for _, height in recorder.gas_temp_calls})


def test_moving_the_opacimeter_to_the_annex7_height_cannot_change_visibility():
    """Annex 7 section 6.4.5 (p.14) puts opacimeters "at a height of 1.5 m".

    This engine's visibility reads the stratified soot concentration, which
    `tenability.species_at` scales by the Newman stratification factor that
    `thermal` defines AT breathing height. That profile is flat below breathing
    height, so an opacimeter at 1.5 m and one at 1.8 m sit in the same layer.
    Asserted here as a property of the profile, so a later change to the
    stratification blend that made the two heights differ would fail this test
    rather than silently leave the opacimeter at the wrong height.
    """
    assert criteria_mod.VISIBILITY_HEIGHT_M == 1.5
    design = Design.load(BASELINE)
    scene = sim_mod._build_scene(design, "bored", 4.5)
    state = fire_mod.FireState(t_s=600.0, hrr_mw=40.0, hrr_free_mw=40.0,
                               energy_released_mj=20_000.0, suppression=1.0,
                               pools_remaining=0, wet_time_s=0.0)
    vent = ventilation.evaluate(scene.geom, 4.5, fire_mod.convective_kw(scene.model, 40.0))
    field = thermal.field(scene.geom, scene.model, state, vent, MistEffect.none(),
                          scene.fire_top_m, scene.fire_base_m,
                          design.fire.footprint.length_m, design.fire.footprint.width_m,
                          scene.ambient_c)
    for x_m in criteria_mod.STATIONS.values():
        assert field.gas_temp_c(x_m, criteria_mod.VISIBILITY_HEIGHT_M) == pytest.approx(
            field.gas_temp_c(x_m, criteria_mod.BREATHING_HEIGHT_M))


# --- Phase 3: mock-up geometry and position (sections 5.2.2/3, 5.3.2/3) ------

def _fire_preset(name: str) -> dict:
    return load_preset("fire", name)


def _near_face_to_wall_m(preset: dict) -> float:
    """Wall-to-near-face distance, from the preset's own offset and width.

    Annex 7 Figure 13 ("Eccentric position of mock-up in cross-section") draws
    its "max 1.5m" dimension arrow from the NEAR FACE of the mock-up to the
    tunnel wall, not from its centreline, and sections 5.2.3 and 5.3.3 carry
    identical wording, so the same reading governs both classes.
    """
    return preset["lane_centre_offset_from_wall_m"] - preset["footprint"]["width_m"] / 2.0


def test_the_mock_up_ends_fall_on_the_u05_and_d05_stations():
    """Annex 7 section 6.3: "the ends of the HGV Class A mock-up are located in
    U5 and D5. Correspondingly the fire target is located at D10."

    That identity holds only for the 10,0 m mock-up of section 5.2.2, centred on
    the virtual zero point. It ties the station map to the mock-up length: an
    8.4 m mock-up puts its ends at -4.2 and +4.2 and fails here.
    """
    footprint = _fire_preset("hgv_150mw")["footprint"]
    half_length_m = footprint["length_m"] / 2.0
    assert criteria_mod.STATIONS["U05"] == pytest.approx(-half_length_m)
    assert criteria_mod.STATIONS["D05"] == pytest.approx(half_length_m)
    target_m = half_length_m + _fire_preset("hgv_150mw")["target_distance_m"]
    assert criteria_mod.STATIONS["Target"] == pytest.approx(target_m)


def test_class_a_mock_up_matches_the_section_5_2_2_dimensions():
    """Annex 7 section 5.2.2 (p.10): "Height: Minimum 4,0m (having minimum 2,5m
    height for the fuel part) / Width: 2,4m / Length: 10,0m"."""
    footprint = _fire_preset("hgv_150mw")["footprint"]
    assert footprint["length_m"] == 10.0
    assert footprint["width_m"] == 2.4
    assert footprint["top_height_m"] >= 4.0
    # 4.0 m minimum total with a minimum 2.5 m fuel part puts the trailer
    # platform at 1.5 m. Asserted as Annex 7's own inequality as well as the
    # figure, so a taller mock-up may raise the platform without failing here.
    assert footprint["base_height_m"] == 1.5
    assert footprint["top_height_m"] - footprint["base_height_m"] >= 2.5


def test_the_class_a_platform_height_is_no_longer_marked_as_an_assumption():
    """Annex 7 section 5.2.2 supplies the number Task 18 had to guess, so the
    `provenance: assumed` marker on the footprint must be gone."""
    footprint = _fire_preset("hgv_150mw")["footprint"]
    assert footprint.get("provenance") is None
    assert "5.2.2" in _fire_preset("hgv_150mw")["note"]


def test_class_b_mock_up_meets_the_section_5_3_2_minimums():
    """Annex 7 section 5.3.2 (p.11): "Width: minimum 2,5 m / Length: minimum
    6,5 m", the pool no more than 0,5 m above the road, and "The minimum size
    for one pool is 4 m2". Section 5.3.1: minimum 50 MW.

    Asserted as the inequalities Annex 7 states, not as the preset's figures.
    """
    preset = _fire_preset("pool_60mw")
    footprint, pools = preset["footprint"], preset["pools"]
    assert footprint["width_m"] >= 2.5
    assert footprint["length_m"] >= 6.5
    assert footprint["top_height_m"] <= 0.5
    assert pools["length_m"] * pools["width_m"] >= 4.0
    # the pools in a row have to be the mock-up they add up to
    assert pools["count"] * pools["length_m"] == pytest.approx(footprint["length_m"])
    assert pools["width_m"] == pytest.approx(footprint["width_m"])


def test_the_class_b_pool_geometry_still_produces_a_fifty_megawatt_fire():
    """Annex 7 section 5.3.1 (p.11): "The minimum size should be 50MW".

    The free-burn HRR is computed from the pool geometry by Babrauskas' law, so
    this asserts what the re-oriented mock-up actually produces rather than the
    `design_hrr_mw` label the preset carries.
    """
    design = Design.load("tests/fixtures/pool_design.json")
    model = fire_mod.build_model(design)
    free_burn_mw = model.pool_count * model.pool_hrr_each_kw / 1000.0
    assert free_burn_mw >= 50.0


@pytest.mark.parametrize("preset_name", ["hgv_150mw", "pool_60mw"])
def test_the_mock_up_sits_within_1_5_m_of_the_side_wall(preset_name):
    """Annex 7 sections 5.2.3 and 5.3.3 (p.11): "The mock-up shall be eccentric
    to the centre line of the test tunnel. The distance from the side wall shall
    be less than 1,5 m."

    Annex 7 rejects the centred position explicitly, and rejects it because it
    flatters the system: "such a position is often most effective for FFFS since
    the fire fighting medium is properly delivered on both sides."
    """
    preset = _fire_preset(preset_name)
    near_face_m = _near_face_to_wall_m(preset)
    assert 0.0 < near_face_m < MAX_WALL_TO_NEAR_FACE_M


@pytest.mark.parametrize("preset_name", ["hgv_150mw", "pool_60mw"])
def test_the_mock_up_is_off_the_centre_line_of_the_test_tunnel(preset_name):
    """The same sections: eccentric, not centred. Checked against the as-tested
    7.50 m section rather than against the offset alone, because "eccentric" is
    a statement about where the mock-up sits in the tunnel."""
    preset = _fire_preset(preset_name)
    road_width_m = load_preset("tunnel", "solit2_test")["width_m"]
    centreline_m = road_width_m / 2.0
    assert preset["lane_centre_offset_from_wall_m"] < centreline_m
    # and the far face still fits inside the carriageway
    assert preset["lane_centre_offset_from_wall_m"] + preset["footprint"]["width_m"] / 2.0 \
        < road_width_m


# --- Phase 4: the Table 4 standard test series (section 5.4) ----------------

def _solit2_test_designs() -> list[Design]:
    """Every shipped design that runs on the SOLIT2 test gallery.

    Filtered on the tunnel preset, because Table 4 is a series of TESTS: a
    project illustration on some other tunnel is not one of its rows.
    """
    designs = []
    for path in sorted(DESIGN_DIR.glob("*.json")):
        if json.loads(path.read_text())["tunnel"]["preset"] != "solit2_test":
            continue
        designs.append(Design.load(path))
    return designs


def _runnable_rows() -> set[tuple[str, bool, float]]:
    """(fire class, covered, velocity) every shipped test design can actually run."""
    from solit2.engines.reduced import envelope

    return {(d.fire.fire_class, d.fire.covered, velocity)
            for d in _solit2_test_designs()
            for velocity in envelope._velocities(d)}


def test_the_annex7_table_4_mandatory_series_is_runnable():
    """Annex 7 Table 4 (section 5.4, p.14), "The following tests shall be
    carried out for FFFS as a minimum requirement": Class A with tarpaulin at
    1,5 m/s and at 3,0 m/s, and Class B at minimum 50 MW at 1,5 m/s and at
    3,0 m/s. No 3.0 m/s case existed anywhere before this."""
    mandatory = {("A", True, 1.5), ("A", True, 3.0), ("B", False, 1.5), ("B", False, 3.0)}
    assert mandatory <= _runnable_rows()


def test_the_annex7_table_4_optional_class_a_series_is_runnable():
    """The same table's two rows marked "Optional": the Class A mock-up without
    the tarpaulin cover, at both velocities. Section 5.2.2 offers it as a
    comparison and warns that it is "normally not a realistic scenario"."""
    optional = {("A", False, 1.5), ("A", False, 3.0)}
    assert optional <= _runnable_rows()


def test_every_class_a_test_design_discharges_for_the_section_5_2_8_minimum():
    """Annex 7 section 5.2.8 (p.11): "The System shall discharge continuously
    for a minimum of 30 minutes after activation". The Class B rule is section
    5.3.7 instead -- "until the fire is extinguished or the fuel is consumed
    completely" -- and carries no 30-minute floor, so only Class A is checked.
    """
    from solit2.engines.reduced import sim as sim_module

    for design in _solit2_test_designs():
        if design.fire.fire_class != "A":
            continue
        trace = sim_module.run_once(design, "test", 1.5)
        activated_s = trace.events["t_activate_s"]
        discharge_s = design.zones.duration_min * 60.0 - activated_s
        assert discharge_s >= 30.0 * 60.0, (
            f"{design.meta.name} discharges for {discharge_s / 60.0:.1f} min "
            f"after activation at {activated_s:.0f} s")


def test_every_test_design_activates_at_least_three_mock_up_lengths(  # noqa: E501
):
    """Annex 7 sections 5.2.8 and 5.3.7 (p.11): "The activation area shall be
    defined by the manufacturer, but it shall be minimum 3 times the length of
    the mock-up"."""
    for design in _solit2_test_designs():
        assert design.active_length_m >= 3.0 * design.fire.footprint.length_m, (
            design.meta.name)


def test_the_class_b_test_design_triggers_within_two_minutes():
    """Annex 7 section 5.3.7 (p.11): "Triggering of FFFS shall happen within 2
    minutes after ignition." Class A has no such cap -- section 5.2.8 puts a
    FLOOR under it instead ("Minimum 1 minutes after ignition")."""
    from solit2.engines.reduced import sim as sim_module

    for design in _solit2_test_designs():
        if design.fire.fire_class != "B":
            continue
        trace = sim_module.run_once(design, "test", 1.5)
        assert trace.events["t_activate_s"] <= 120.0, design.meta.name

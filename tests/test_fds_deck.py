from solit2.engines.fds import deck
from solit2.schema.design import Design

BASELINE = "designs/og-dbr-rev0.json"
TEST_RIG = "examples/designs/solit2-test-protocol.json"


def test_the_deck_opens_with_head_and_closes_with_tail():
    text = deck.generate(Design.load(BASELINE))
    assert text.startswith("&HEAD")
    assert text.rstrip().endswith("&TAIL /")


def test_the_deck_is_deterministic():
    design = Design.load(BASELINE)
    assert deck.generate(design) == deck.generate(design)


def test_the_chid_is_the_design_sha():
    from solit2.engines.reduced.envelope import _design_sha
    design = Design.load(BASELINE)
    assert f"CHID='{_design_sha(design)}'" in deck.generate(design)


def test_the_domain_holds_every_station_the_criteria_read():
    from solit2.engines.reduced.criteria import STATIONS
    text = deck.generate(Design.load(BASELINE))
    mesh_lines = [ln for ln in text.splitlines() if ln.startswith("&MESH")]
    assert len(mesh_lines) == 3, "far upstream, core, far downstream"
    assert str(deck.WINDOW_M[0]) in mesh_lines[0]
    assert str(deck.WINDOW_M[1]) in mesh_lines[-1]
    for x_m in STATIONS.values():
        assert deck.WINDOW_M[0] <= x_m <= deck.WINDOW_M[1]


def test_the_core_mesh_is_finer_than_the_far_field():
    text = deck.generate(Design.load(BASELINE))
    mesh_lines = [ln for ln in text.splitlines() if ln.startswith("&MESH")]

    def i_cells(line: str) -> int:
        return int(line.split("IJK=")[1].split(",")[0])

    # the core spans 180 m against the far upstream's 300 m, and still has more
    # cells along x -- that is what "finer" means here
    assert i_cells(mesh_lines[1]) > i_cells(mesh_lines[0])


def test_the_cell_count_stays_inside_the_planned_budget():
    # the plan budgets about 180k cells; rounding j and k up for interface
    # alignment costs cells, and a silent jump past the budget turns an
    # overnight run into a week. The goldens pin the exact mesh set.
    for design_path in (BASELINE, TEST_RIG):
        total = sum(i * j * k for i, j, k in
                    _mesh_ijk(deck.generate(Design.load(design_path))))
        assert total < 180_000, (design_path, total)


def _mesh_ijk(text: str) -> list[tuple[int, int, int]]:
    return [tuple(int(n) for n in ln.split("IJK=")[1].split(",")[:3])
            for ln in text.splitlines() if ln.startswith("&MESH")]


def test_mesh_interfaces_are_aligned_in_x_y_and_z():
    # misaligned interfaces are the classic multi-mesh FDS bug
    core_span = deck.CORE_M[1] - deck.CORE_M[0]
    up_span = deck.CORE_M[0] - deck.WINDOW_M[0]
    down_span = deck.WINDOW_M[1] - deck.CORE_M[1]
    coarse = deck.FINE_DX_M * deck.COARSE_RATIO
    assert core_span % deck.FINE_DX_M == 0
    assert up_span % coarse == 0
    assert down_span % coarse == 0
    # y and z: all three meshes share ONE y extent and ONE z extent, so an
    # aligned interface means the core's j and k are exactly COARSE_RATIO times
    # the far meshes'. j=20 against j=7 (ratio 2.857) is the bug this catches.
    for design_path in (BASELINE, TEST_RIG):
        up, core, down = _mesh_ijk(deck.generate(Design.load(design_path)))
        for axis, name in ((1, "j"), (2, "k")):
            assert core[axis] == up[axis] * deck.COARSE_RATIO, (design_path, name)
            assert core[axis] == down[axis] * deck.COARSE_RATIO, (design_path, name)


def test_the_portals_supply_upstream_and_open_downstream():
    text = deck.generate(Design.load(BASELINE))
    assert "MB='XMIN'" in text and "SURF_ID='SUPPLY'" in text
    assert "MB='XMAX'" in text and "SURF_ID='OPEN'" in text
    # inflow is a NEGATIVE velocity on XMIN
    assert "VEL=-" in text


def test_a_bored_tunnel_is_stair_stepped_and_a_test_rig_is_a_box():
    bored = deck.generate(Design.load(BASELINE))
    boxed = deck.generate(Design.load(TEST_RIG))
    # the circular bore needs many OBST rows to approximate the arc;
    # the rectangular rig needs only its walls
    assert bored.count("&OBST") > boxed.count("&OBST")


def test_every_annex_7_station_gets_its_thermocouple_tree():
    from solit2.engines.reduced.criteria import INSTRUMENTS, STATIONS
    text = deck.generate(Design.load(BASELINE))
    for name, x_m in STATIONS.items():
        if not (deck.WINDOW_M[0] <= x_m <= deck.WINDOW_M[1]):
            continue
        for rung in range(INSTRUMENTS[name].thermocouples):
            assert f"ID='{name}_TC{rung}'" in text


def test_only_the_stations_table_5_instruments_get_a_flux_gauge():
    from solit2.engines.reduced.criteria import INSTRUMENTS, STATIONS
    text = deck.generate(Design.load(BASELINE))
    for name, x_m in STATIONS.items():
        if not (deck.WINDOW_M[0] <= x_m <= deck.WINDOW_M[1]):
            continue
        present = f"ID='{name}_HF'" in text
        assert present == INSTRUMENTS[name].heat_flux, name


def test_the_target_carries_its_own_flux_gauge():
    # Table 5 lists no gauge at the target -- a real test observes ignition.
    # A simulation has to measure it, so the deck adds one.
    assert f"ID='{deck.TARGET_GAUGE_ID}'" in deck.generate(Design.load(BASELINE))


def test_a_ceiling_thermocouple_line_spans_the_core():
    # structure exposure is a near-fire quantity; the far meshes exist only so
    # the three far stations are measured, not to resolve a hot ceiling
    text = deck.generate(Design.load(BASELINE))
    assert f"ID='{deck.CEILING_TC_PREFIX}0'" in text
    span = deck.CORE_M[1] - deck.CORE_M[0]
    expected = int(span / deck.CEILING_TC_SPACING_M)
    assert text.count(f"ID='{deck.CEILING_TC_PREFIX}") == expected


def test_one_devc_per_head_and_exactly_one_particle_class():
    design = Design.load(BASELINE)
    text = deck.generate(design)
    assert text.count("PROP_ID='NOZ_FINE'") == design.active_heads
    # single-mode: one PART, one PROP, for the whole deck
    assert text.count("&PART ID=") == 1
    assert text.count("&PROP ID=") == 1
    assert "NOZ_COARSE" not in text


def test_the_nozzle_flow_rate_is_k_root_p():
    design = Design.load(BASELINE)
    text = deck.generate(design)
    assert f"FLOW_RATE={design.nozzles.flow_per_head_lpm:.2f}" in text


def test_detection_drives_activation_through_a_time_delay_control():
    design = Design.load(BASELINE)
    text = deck.generate(design)
    assert f"SETPOINT={design.detection.threshold_c:.1f}" in text
    assert "FUNCTION_TYPE='TIME_DELAY'" in text
    assert f"DELAY={design.zones.activation_delay_s:.1f}" in text
    assert "&CTRL ID='ACT'" in text


def test_the_fire_ramps_to_the_design_hrr():
    design = Design.load(BASELINE)
    text = deck.generate(design)
    assert "&SURF ID='FIRE'" in text
    assert "RAMP_Q='FIRE_RAMP'" in text
    assert "E_COEFFICIENT" in text


def test_the_fire_surface_has_a_reac_line():
    # FDS ERROR 314: a SURF using HRRPUA is rejected outright without a REAC
    # line to define the fuel's chemistry -- verified against a real FDS run.
    text = deck.generate(Design.load(BASELINE))
    assert "&REAC" in text
    reac = next(ln for ln in text.splitlines() if ln.startswith("&REAC"))
    assert "HEAT_OF_COMBUSTION" in reac
    assert "SOOT_YIELD" in reac
    assert "CO_YIELD" in reac


def test_the_reac_chemistry_matches_tier_1s_own_constants():
    from solit2.engines.reduced.fire import WOOD_HEAT_OF_COMBUSTION_MJKG
    from solit2.engines.reduced.tenability import YIELDS
    text = deck.generate(Design.load(BASELINE))  # Class A
    reac = next(ln for ln in text.splitlines() if ln.startswith("&REAC"))
    assert f"HEAT_OF_COMBUSTION={WOOD_HEAT_OF_COMBUSTION_MJKG * 1000.0:.1f}" in reac
    assert f"SOOT_YIELD={YIELDS['A']['soot']:.3f}" in reac
    assert f"CO_YIELD={YIELDS['A']['co']:.3f}" in reac


def test_a_class_b_design_gets_diesel_reac_chemistry():
    from solit2.engines.reduced.fire import DIESEL_HEAT_OF_COMBUSTION_MJKG
    from solit2.engines.reduced.tenability import YIELDS
    class_b = Design.load("examples/designs/solit2-test-protocol-class-b.json")
    text = deck.generate(class_b)
    reac = next(ln for ln in text.splitlines() if ln.startswith("&REAC"))
    assert f"HEAT_OF_COMBUSTION={DIESEL_HEAT_OF_COMBUSTION_MJKG * 1000.0:.1f}" in reac
    assert f"SOOT_YIELD={YIELDS['B']['soot']:.3f}" in reac


def test_the_deck_matches_its_golden_file():
    from pathlib import Path
    golden = Path("tests/fixtures/fds/og-dbr-rev0.fds")
    assert deck.generate(Design.load(BASELINE)) == golden.read_text()


def test_the_test_rig_deck_matches_its_golden_file():
    from pathlib import Path
    golden = Path("tests/fixtures/fds/solit2-test-protocol.fds")
    assert deck.generate(Design.load(TEST_RIG)) == golden.read_text()


def test_the_co_device_is_converted_to_ppm():
    # FDS's VOLUME FRACTION is mol/mol; `max_co_ppm` is an Annex 7 life-safety
    # criterion in ppm. Without the conversion the gate compares ~2e-4 against a
    # limit of several hundred and structurally cannot fail.
    from solit2.engines.reduced.criteria import INSTRUMENTS, STATIONS
    text = deck.generate(Design.load(BASELINE))
    co_lines = [ln for ln in text.splitlines() if "_CO'" in ln]
    expected = sum(1 for n, x in STATIONS.items()
                   if deck.WINDOW_M[0] <= x <= deck.WINDOW_M[1]
                   and INSTRUMENTS[n].toxic_gas)
    assert co_lines and len(co_lines) == expected
    for line in co_lines:
        assert f"CONVERSION_FACTOR={deck.CO_PPM_CONVERSION}" in line
        assert "UNITS='ppm'" in line


def test_the_fire_ceiling_device_sits_directly_above_the_fire():
    # `reader` reads lining_temp_c from this device. The MIDDLE of the ceiling
    # line is 30 m downstream of the fire on the current window, not above it.
    text = deck.generate(Design.load(BASELINE))
    device = deck.fire_ceiling_device_id()
    line = next(ln for ln in text.splitlines() if f"ID='{device}'" in ln)
    x_m = float(line.split("XYZ=")[1].split(",")[0])
    assert x_m == deck.FIRE_X_M


def test_the_stepped_free_area_is_the_area_the_deck_actually_emits():
    from solit2.engines.reduced.geometry import section_geometry
    # a box is emitted exactly, so there is no gap to report
    rig = section_geometry(Design.load(TEST_RIG))
    assert deck.stepped_free_area_m2(rig) == rig.road_width_m * rig.crown_height_m
    # a stair-stepped bore cannot be, and loses area against the smooth circle
    bore = section_geometry(Design.load(BASELINE))
    assert deck.stepped_free_area_m2(bore) < bore.free_area_m2


def test_the_wall_surface_carries_a_thickness_with_its_material():
    # FDS requires THICKNESS wherever a SURF names a MATL
    for design_path in (BASELINE, TEST_RIG):
        line = next(ln for ln in deck.generate(Design.load(design_path)).splitlines()
                    if ln.startswith("&SURF ID='WALL'"))
        assert "MATL_ID=" in line and f"THICKNESS={deck.WALL_THICKNESS_M:.2f}" in line

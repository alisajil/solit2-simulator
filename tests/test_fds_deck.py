import pytest

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
    assert len(mesh_lines) == deck.MESH_COUNT
    assert f"XB={deck.WINDOW_M[0]:.1f}," in mesh_lines[0]
    assert f",{deck.WINDOW_M[1]:.1f}," in mesh_lines[-1]
    for x_m in STATIONS.values():
        assert deck.WINDOW_M[0] <= x_m <= deck.WINDOW_M[1]


def _mesh_ijk(text: str) -> list[tuple[int, int, int]]:
    return [tuple(int(n) for n in ln.split("IJK=")[1].split(",")[:3])
            for ln in text.splitlines() if ln.startswith("&MESH")]


def _mesh_xb(text: str) -> list[tuple[float, ...]]:
    return [tuple(float(n) for n in ln.split("XB=")[1].split(" /")[0].split(","))
            for ln in text.splitlines() if ln.startswith("&MESH")]


def test_meshes_are_uniform_and_tile_the_window_exactly():
    # Nested meshes (fine core, coarse far field) were built first and failed
    # against real FDS: the pressure solver never converged at the interfaces
    # and the run went unstable at ignition, at 3:1 and again at 2:1. Uniform
    # meshes are the fix, so every mesh must be identical and the tiling exact.
    for design_path in (BASELINE, TEST_RIG):
        text = deck.generate(Design.load(design_path))
        ijk, xb = _mesh_ijk(text), _mesh_xb(text)
        assert len(set(ijk)) == 1, (design_path, "meshes differ in IJK")
        assert len({b[2:] for b in xb}) == 1, (design_path, "meshes differ in y/z")
        span = (deck.WINDOW_M[1] - deck.WINDOW_M[0]) / deck.MESH_COUNT
        for (x0, x1, *_), (i, _, _) in zip(xb, ijk):
            assert x1 - x0 == pytest.approx(span)
            assert i * deck.DX_M == pytest.approx(span), "x-span is not whole cells"
        for a, b in zip(xb, xb[1:]):
            assert a[1] == pytest.approx(b[0]), "gap or overlap between meshes"


def test_the_mesh_is_padded_to_whole_cells_and_the_wall_fills_the_padding():
    # the mesh's y and z extents are ceil(section/dx) cells, so the solid
    # boundary lands on a cell face; the tunnel OBSTs must reach that edge
    from solit2.engines.reduced.geometry import section_geometry
    design = Design.load(BASELINE)
    geom = section_geometry(design)
    text = deck.generate(design)
    _, _, y0, y1, _, z1 = _mesh_xb(text)[0]
    assert y1 - y0 >= geom.road_width_m and z1 >= geom.crown_height_m
    assert (y1 - y0) / deck.DX_M == pytest.approx(round((y1 - y0) / deck.DX_M))
    assert z1 / deck.DX_M == pytest.approx(round(z1 / deck.DX_M))
    walls = [ln for ln in text.splitlines() if "SURF_ID='WALL'" in ln and ln.startswith("&OBST")]
    assert any(f",{y1:.2f}," in ln for ln in walls), "no wall reaches the +y mesh edge"


def test_the_deck_asks_for_the_global_pressure_solver():
    # The default block-wise FFT solver treats each mesh's pressure separately
    # and iterates to reconcile the interfaces. On a 10-mesh proxy of this
    # topology it capped out at 10 iterations on half the steps and still left
    # 0.4-0.7 m/s of interface velocity error; UGLMAT solves one global matrix
    # and left ~1e-15, in less wall time. A 600 m tunnel is one duct.
    text = deck.generate(Design.load(BASELINE))
    assert "&PRES" in text
    pres = next(ln for ln in text.splitlines() if ln.startswith("&PRES"))
    assert "UGLMAT" in pres


def test_the_default_cell_size_is_inside_the_resolution_band():
    # D* = 7.1 m at 150 MW; the design spec's screening band is D*/dx in [10, 16]
    assert 10 <= 7.1 / deck.DX_M <= 16


def test_a_cell_size_that_does_not_tile_the_window_is_rejected():
    with pytest.raises(ValueError, match="does not tile"):
        deck.generate(Design.load(BASELINE), dx_m=0.9)


def test_the_cell_count_stays_inside_the_planned_budget():
    # 0.6 m uniform over 600 m is about 221k cells; the earlier 180k figure
    # belonged to the nested design that could not run. A silent jump past this
    # turns an overnight run into a week. The goldens pin the exact mesh set.
    for design_path in (BASELINE, TEST_RIG):
        total = sum(i * j * k for i, j, k in
                    _mesh_ijk(deck.generate(Design.load(design_path))))
        assert total < 250_000, (design_path, total)


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


def test_flux_gauges_are_gas_phase_with_an_orientation_not_a_boundary_ior():
    # FDS ERROR 427: a free-floating 'GAUGE HEAT FLUX' DEVC with IOR needs a
    # solid boundary and is rejected outright -- verified against a real FDS
    # run. 'GAUGE HEAT FLUX GAS' is the gas-phase equivalent Table 5's
    # stations need (a person or a target, not a wall).
    text = deck.generate(Design.load(BASELINE))
    gauge_lines = [ln for ln in text.splitlines()
                  if "QUANTITY='GAUGE HEAT FLUX" in ln]
    assert gauge_lines, "no heat-flux gauges in the deck"
    for ln in gauge_lines:
        assert "GAUGE HEAT FLUX GAS" in ln
        assert "ORIENTATION=" in ln
        assert "IOR=" not in ln


def test_a_gauge_orients_toward_the_fire():
    # U-side gauges (negative x) face +x toward the fire at x=0; D-side
    # gauges face -x. Getting the sign backward reads the WRONG direction's
    # incident flux -- away from the fire instead of toward it.
    assert deck._gauge_orientation(-15.0) == "1.0,0.0,0.0"
    assert deck._gauge_orientation(15.0) == "-1.0,0.0,0.0"


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


def test_nozzles_wait_for_the_activation_control():
    # QUANTITY='TIME', SETPOINT=0.0 self-triggers every head at t=0 whatever
    # CTRL_ID says: a real FDS run had 22,781 droplets in one mesh by t=0.5 s,
    # with detection and the activation delay never applied, which makes
    # suppression look instantaneous. FDS's own activate_sprinklers.fds uses
    # QUANTITY='CONTROL' for a head opened by an external control.
    text = deck.generate(Design.load(BASELINE))
    heads = [ln for ln in text.splitlines() if "PROP_ID='NOZ_FINE'" in ln]
    assert heads
    for ln in heads:
        assert "QUANTITY='CONTROL'" in ln
        assert "CTRL_ID='ACT'" in ln
        assert "SETPOINT" not in ln, "a setpoint on the head bypasses the control"


def test_the_simulated_window_is_separate_from_the_discharge_duration():
    # zones.duration_min sizes the water tank and the cost index, so it must
    # not be edited to shorten a CFD run: 60 -> 20 min takes the Orange Gate
    # baseline's tank from 92.4 m3 to 30.8 m3 and breaks Annex 7 5.2.8's
    # 30-minute minimum discharge.
    design = Design.load(BASELINE)
    full = deck.generate(design)
    short = deck.generate(design, t_end_s=1200.0)
    assert f"T_END={design.zones.duration_min * 60.0:.1f}" in full
    assert "T_END=1200.0" in short


def test_the_spray_particle_count_is_set_and_far_below_the_fds_default():
    # FDS defaults to 5000 droplets per head per second; on a 54-head deck that
    # is 270,000 a second. A 66k-cell test case accumulated over a million,
    # took ~4 GB and never finished. A convergence study over 250/500/1000
    # agreed to 0.12% on suppressed HRR, so the sampling is converged here.
    text = deck.generate(Design.load(BASELINE))
    prop = next(ln for ln in text.splitlines() if ln.startswith("&PROP"))
    assert f"PARTICLES_PER_SECOND={deck.PARTICLES_PER_SECOND}" in prop
    assert deck.PARTICLES_PER_SECOND < 5000, "must stay below the FDS default"


def test_output_carries_centreline_slices_for_temperature_smoke_and_mist():
    text = deck.generate(Design.load("examples/designs/road-tunnel-twin-bore.json"))
    assert "&SLCF PBY=0.0, QUANTITY='TEMPERATURE' /" in text
    assert "&SLCF PBY=0.0, QUANTITY='SOOT DENSITY' /" in text
    assert "&SLCF PBY=0.0, QUANTITY='MPUV', PART_ID='FINE' /" in text

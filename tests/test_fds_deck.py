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


def _mesh_dx(xb, ijk) -> list[float]:
    return [(x1 - x0) / i for (x0, x1, *_), (i, _, _) in zip(xb, ijk)]


def test_meshes_are_fine_around_the_fire_and_coarser_along_x_in_the_far_field():
    # The fire, the Figure 16 station set and the +-100 m stations sit inside
    # FIRE_X_M +- FINE_HALF_LENGTH_M at DX_M. Beyond that the flow is a
    # stratified duct and the cells are COARSE_FACTOR longer along x ONLY:
    # across and up they stay DX_M, so a head-height reading at a far station
    # keeps its vertical resolution. Wall time per step follows the largest
    # mesh, so the point is to shrink it: measured 119 s -> 90 s on a 20 s deck
    # with no station more than 5 % from the uniform mesh.
    for design_path in (BASELINE, TEST_RIG):
        text = deck.generate(Design.load(design_path))
        ijk, xb = _mesh_ijk(text), _mesh_xb(text)
        assert len({b[2:] for b in xb}) == 1, (design_path, "meshes differ in y/z")
        assert len({(j, k) for _, j, k in ijk}) == 1, (design_path, "meshes differ in JK")
        fine_lo = deck.FIRE_X_M - deck.FINE_HALF_LENGTH_M
        fine_hi = deck.FIRE_X_M + deck.FINE_HALF_LENGTH_M
        for (x0, x1, *_), dx in zip(xb, _mesh_dx(xb, ijk)):
            inside = fine_lo - 1e-9 <= x0 and x1 <= fine_hi + 1e-9
            outside = x1 <= fine_lo + 1e-9 or x0 >= fine_hi - 1e-9
            assert inside or outside, (design_path, "a mesh straddles the fine/coarse boundary")
            expected = deck.DX_M if inside else deck.COARSE_FACTOR * deck.DX_M
            assert dx == pytest.approx(expected), (design_path, x0, x1, dx)
        assert any(x0 == pytest.approx(fine_lo) for x0, *_ in xb), "fine region does not start on a mesh edge"
        assert any(x1 == pytest.approx(fine_hi) for _, x1, *_ in xb), "fine region does not end on a mesh edge"


def test_meshes_tile_the_window_exactly_on_nested_lattices():
    # No gaps, no overlaps, and every mesh edge on the lattice of its own cell
    # size counted from the window origin. Because COARSE_FACTOR is an integer
    # the coarse lattice is a subset of the fine one, so the fine/coarse
    # interfaces are conforming -- the condition UGLMAT's refinement needs.
    for design_path in (BASELINE, TEST_RIG):
        text = deck.generate(Design.load(design_path))
        ijk, xb = _mesh_ijk(text), _mesh_xb(text)
        assert xb[0][0] == pytest.approx(deck.WINDOW_M[0])
        assert xb[-1][1] == pytest.approx(deck.WINDOW_M[1])
        for a, b in zip(xb, xb[1:]):
            assert a[1] == pytest.approx(b[0]), "gap or overlap between meshes"
        for (x0, x1, *_), dx in zip(xb, _mesh_dx(xb, ijk)):
            for edge in (x0, x1):
                n = (edge - deck.WINDOW_M[0]) / dx
                assert n == pytest.approx(round(n)), (design_path, edge, dx, "edge off its lattice")


def test_the_stations_within_100_m_of_the_fire_read_from_fine_cells():
    # The promise behind the split: everything Annex 7 reads within +-100 m is
    # in DX_M cells. Only the far stations (U340, D215) sit in coarse cells.
    from solit2.engines.reduced.criteria import STATIONS
    near = [x for x in STATIONS.values() if abs(x - deck.FIRE_X_M) <= 100.0]
    assert len(near) >= 10
    for x in near:
        assert abs(x - deck.FIRE_X_M) < deck.FINE_HALF_LENGTH_M, x


def test_the_fire_and_its_target_each_sit_inside_one_fine_mesh():
    # An obstruction may span meshes, but the burner and the target are where
    # the solution is sharpest. Keep the interface out of both.
    from solit2.engines.reduced.geometry import section_geometry
    design = Design.load(BASELINE)
    geom = section_geometry(design)
    xb = _mesh_xb(deck.generate(design))
    for box in (deck.fuel_box(design, geom), deck.target_box(design, geom)):
        assert any(x0 <= box.x0 and box.x1 <= x1 for x0, x1, *_ in xb), box


def test_the_largest_mesh_is_well_below_what_a_uniform_split_would_carry():
    # Wall time per step follows the largest mesh. This is the whole point.
    text = deck.generate(Design.load(BASELINE))
    ijk = _mesh_ijk(text)
    _, j, k = ijk[0]
    uniform_per_mesh = (deck.WINDOW_M[1] - deck.WINDOW_M[0]) / deck.DX_M * j * k / len(ijk)
    assert max(i * j * k for i, j, k in ijk) <= 0.75 * uniform_per_mesh


def test_every_obstruction_face_lies_on_a_cell_face_of_its_mesh():
    # FDS snaps an obstruction to the nearest cell face without a word. A face
    # that already sits on one moves nowhere; a fine-lattice face inside a
    # coarse mesh would shift by up to half a coarse cell.
    text = deck.generate(Design.load(BASELINE))
    ijk, xb = _mesh_ijk(text), _mesh_xb(text)
    meshes = list(zip((b[0] for b in xb), (b[1] for b in xb), _mesh_dx(xb, ijk)))

    def on_a_face(x: float) -> bool:
        for x0, x1, dx in meshes:
            if x0 - 1e-6 <= x <= x1 + 1e-6:
                n = (x - x0) / dx
                if abs(n - round(n)) < 1e-6:
                    return True
        return False

    faces = [float(v) for ln in text.splitlines() if ln.startswith("&OBST")
             for v in ln.split("XB=")[1].split(",")[:2]]
    assert faces
    assert all(on_a_face(x) for x in faces), sorted({x for x in faces if not on_a_face(x)})


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



def test_the_target_is_a_solid_with_its_gauge_on_the_face_toward_the_fire():
    # Table 5 lists no gauge at the target -- a real test observes ignition.
    # A simulation has to measure it, and the measurement Tier 1 makes is the
    # flux ON the target's face at half the fuel top height (`sim`), not at a
    # point in free gas the flow passes straight through. So the target is a
    # solid the flow goes round, and the gauge is FDS's boundary gauge on it.
    from solit2.engines.reduced.geometry import section_geometry
    design = Design.load(BASELINE)
    text = deck.generate(design)
    box = deck.target_box(design, section_geometry(design))
    assert f"&OBST XB={box.xb()}, SURF_ID='INERT' /" in text
    gauge = next(ln for ln in text.splitlines() if f"ID='{deck.TARGET_GAUGE_ID}'" in ln)
    assert "QUANTITY='GAUGE HEAT FLUX'," in gauge and "IOR=-1" in gauge
    x, y, z = (float(v) for v in gauge.split("XYZ=")[1].split(",")[:3])
    assert x == pytest.approx(box.x0), "the gauge must sit on the upstream face"
    assert y == pytest.approx(box.y_centre_m)
    assert box.z0 < z < box.z1



def test_station_gauges_are_gas_phase_and_only_the_target_gauge_is_a_boundary_one():
    # FDS ERROR 427: a 'GAUGE HEAT FLUX' DEVC needs a solid to sit on. The Table 5
    # station gauges stand where a person would, in free gas, so they are the
    # gas-phase 'GAUGE HEAT FLUX GAS' with an ORIENTATION. The target gauge is
    # the one boundary gauge, and it has the solid target under it.
    text = deck.generate(Design.load(BASELINE))
    gauge_lines = [ln for ln in text.splitlines() if "QUANTITY='GAUGE HEAT FLUX" in ln]
    assert gauge_lines, "no heat-flux gauges in the deck"
    for ln in gauge_lines:
        if f"ID='{deck.TARGET_GAUGE_ID}'" in ln:
            assert "GAUGE HEAT FLUX'" in ln and "IOR=" in ln
        else:
            assert "GAUGE HEAT FLUX GAS" in ln and "ORIENTATION=" in ln and "IOR=" not in ln


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



def test_the_fire_releases_exactly_the_design_hrr_on_the_area_it_actually_emits():
    # FDS snaps OBST bounds to cell faces and burns HRRPUA x the SNAPPED area. A
    # 10 x 2.4 m footprint on a 0.6 m mesh is not 24 m2 once snapped, so a
    # HRRPUA sized on the design footprint gives the wrong total. The deck
    # snaps first and normalises to what it emits.
    from solit2.engines.reduced.geometry import section_geometry
    design = Design.load(BASELINE)
    text = deck.generate(design)
    box = deck.fuel_box(design, section_geometry(design))
    surfs = [ln for ln in text.splitlines() if ln.startswith("&SURF ID='FIRE")]
    hrrpua = float(surfs[0].split("HRRPUA=")[1].split(",")[0])
    assert hrrpua * box.top_area_m2 == pytest.approx(design.fire.design_hrr_mw * 1000.0, rel=1e-4)
    assert all("E_COEFFICIENT" in ln for ln in surfs)
    ramps = [float(ln.split("F=")[1].split(" /")[0]) for ln in text.splitlines()
             if ln.startswith("&RAMP ID='FIRE_RAMP")]
    assert max(ramps) == pytest.approx(1.0) and min(ramps) >= 0.0


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


def test_the_emitted_section_carries_the_same_free_area_tier_1_computes():
    """It did not. A mesh sized to the CARRIAGEWAY clipped the bore where it is
    widest (11.00 m against a 10.15 m road), and every stair-step took its width
    at the top of its layer, which is narrowest where the crown turns over.
    Together they lost 7.6 % of the section, so the two engines were pushing air
    through different tunnels."""
    from solit2.engines.reduced.geometry import section_geometry
    for path in (BASELINE, TEST_RIG):
        geom = section_geometry(Design.load(path))
        assert deck.stepped_free_area_m2(geom) == pytest.approx(geom.free_area_m2, rel=1e-3), path


def test_the_mesh_spans_the_widest_part_of_the_section_not_the_carriageway():
    from solit2.engines.reduced.geometry import section_geometry
    bore = section_geometry(Design.load(BASELINE))
    assert bore.max_width_m > bore.road_width_m, "a bored tunnel widens above its deck"
    j, _ = deck._mesh_extent(bore, deck.DX_M)
    assert j * deck.DX_M >= bore.max_width_m
    # a box is its own widest point, so nothing is padded for it
    rig = section_geometry(Design.load(TEST_RIG))
    assert rig.max_width_m == rig.road_width_m


def test_the_open_area_the_obstructions_leave_is_the_area_reported():
    """The reported figure has to be a measurement of the emitted geometry, not
    an assertion about it, or a future change to the stepping could reopen a gap
    silently."""
    import re
    from solit2.engines.reduced.geometry import section_geometry
    design = Design.load(BASELINE)
    geom = section_geometry(design)
    text = deck.generate(design)
    j, k = deck._mesh_extent(geom, deck.DX_M)
    half, top = j * deck.DX_M / 2, k * deck.DX_M
    walls = [[float(v) for v in m.group(1).split(",")[:6]]
             for m in re.finditer(r"&OBST XB=([-\d.,]+),\s*SURF_ID='WALL'", text)]
    assert walls
    n_y, n_z = 400, 300
    cells = sum(1 for iy in range(n_y) for iz in range(n_z)
                if not any(w[2] <= -half + (iy + 0.5) * 2 * half / n_y <= w[3]
                           and w[4] <= (iz + 0.5) * top / n_z <= w[5] for w in walls))
    measured = cells * (2 * half / n_y) * (top / n_z)
    assert measured == pytest.approx(deck.stepped_free_area_m2(geom), rel=0.01)


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



def test_output_slices_cut_through_the_fire_not_the_empty_centreline():
    from solit2.engines.reduced.geometry import section_geometry
    design = Design.load("examples/designs/road-tunnel-twin-bore.json")
    text = deck.generate(design)
    y = deck.fuel_box(design, section_geometry(design)).y_centre_m
    assert y != 0.0, "the fixture fire is eccentric, so a y=0 slice would miss it"
    assert f"&SLCF PBY={y:.2f}, QUANTITY='TEMPERATURE' /" in text
    # FDS 6.11 rejected QUANTITY='SOOT DENSITY' outright (ERROR 1042 in a real
    # run); a species' mass per unit volume is DENSITY with its SPEC_ID.
    assert f"&SLCF PBY={y:.2f}, QUANTITY='DENSITY', SPEC_ID='SOOT' /" in text
    assert "SOOT DENSITY" not in text
    assert f"&SLCF PBY={y:.2f}, QUANTITY='MPUV', PART_ID='FINE' /" in text

def _device_xyz(text: str, device: str) -> tuple[float, float, float]:
    line = next(ln for ln in text.splitlines() if f"ID='{device}'" in ln)
    return tuple(float(v) for v in line.split("XYZ=")[1].split(",")[:3])


def _open_ceiling_m(geom, y_m: float) -> float:
    """Top of the highest stair-step layer still open at lateral position y."""
    return max(z_hi for _, z_hi, clear in deck._bore_layers(geom, deck.DX_M) if clear > abs(y_m))


def test_ceiling_thermocouples_and_heat_detectors_sit_in_gas_not_inside_the_crown_slab():
    # The bore's topmost stair-step layer is solid across the full width
    # (width_at(crown) is 0). Devices at crown - 0.15 m sat INSIDE it: in a real
    # 147 MW run every CEIL and LHD device read 30.0 C for 936 s while D05 read
    # 1094 C, the detector never tripped, and the "mist" run was a free burn.
    from solit2.engines.reduced.geometry import section_geometry
    design = Design.load(BASELINE)
    geom = section_geometry(design)
    text = deck.generate(design)
    for device in ("LHD0", deck.fire_ceiling_device_id()):
        _, y, z = _device_xyz(text, device)
        open_top = _open_ceiling_m(geom, y)
        assert z < open_top, f"{device} at z={z} is inside the solid layer above {open_top}"
        assert z > open_top - deck.DX_M, f"{device} is not just under the ceiling that exists at y={y}"
    # Never above the real crown: the topmost slab runs past it, because the
    # mesh is whole cells and the crown is not.
    for y in (0.0, -2.7, 2.7):
        assert deck.ceiling_z_at(geom, y) <= geom.crown_height_m - deck.CEILING_OFFSET_M


def test_the_fire_sits_where_tier_1_puts_it_eccentric_toward_the_near_wall():
    # Annex 7 5.2.3: the mock-up is offset toward one wall because a centred
    # load flatters the system. Tier 1's mist envelope already uses
    # `fire_lateral_m`; the deck burned the fire on the centreline instead, so
    # the two tiers were not the same experiment.
    from solit2.engines.reduced.geometry import fire_lateral_m, section_geometry
    design = Design.load(BASELINE)
    geom = section_geometry(design)
    box = deck.fuel_box(design, geom)
    assert abs(box.y_centre_m - fire_lateral_m(design, geom)) <= deck.DX_M / 2
    assert box.y_centre_m < 0 and box.y1 < 0, "the whole load lies on the near-wall side"
    assert deck.target_box(design, geom).y_centre_m == box.y_centre_m


def test_every_emitted_box_bound_lies_on_a_cell_face():
    from solit2.engines.reduced.geometry import section_geometry
    for path in (BASELINE, TEST_RIG):
        design = Design.load(path)
        geom = section_geometry(design)
        y_origin = deck._y_origin(geom, deck.DX_M)
        for box in (deck.fuel_box(design, geom), deck.target_box(design, geom)):
            for value, origin in ((box.x0, deck.WINDOW_M[0]), (box.x1, deck.WINDOW_M[0]),
                                  (box.y0, y_origin), (box.y1, y_origin), (box.z0, 0.0), (box.z1, 0.0)):
                cells = (value - origin) / deck.DX_M
                assert cells == pytest.approx(round(cells), abs=1e-6), (path, box)


def test_the_fire_ramp_is_tier_1s_free_burn_curve_and_burns_out():
    # The previous ramp sampled the growth every 30 s, missed the instant the
    # plateau was reached, then held F=1 to the end of the run: an hour at
    # 150 MW is 540 GJ from a 140 GJ pallet load. The ramp is now Tier 1's own
    # free-burn curve, decay included.
    from solit2.engines.reduced import fire as fire_mod
    from solit2.engines.reduced.state import MistEffect
    design = Design.load(BASELINE)
    horizon = design.zones.duration_min * 60.0
    curve = deck.free_burn_curve(design, horizon)
    model = fire_mod.build_model(design)
    state = fire_mod.initial_state(model)
    for _ in range(900):
        state = fire_mod.step(model, state, 1.0, MistEffect.none())
    assert deck._interp(curve, 900.0) == pytest.approx(state.hrr_free_mw * 1000 / model.design_hrr_kw, rel=1e-6)
    assert max(f for _, f in curve) == pytest.approx(1.0)
    assert curve[-1][1] < 0.2, "the fuel is spent long before the hour is up"


def test_segment_ramps_sum_to_the_curve_and_light_from_upstream_to_downstream():
    design = Design.load(BASELINE)
    curve = deck.free_burn_curve(design, design.zones.duration_min * 60.0)
    n = 16
    ramps = deck.segment_ramps(curve, n)
    assert len(ramps) == n

    def at(ramp, t):
        for (t0, f0), (t1, f1) in zip(ramp, ramp[1:]):
            if t0 <= t <= t1:
                return f0 + (f1 - f0) * (t - t0) / (t1 - t0) if t1 > t0 else f0
        return ramp[-1][1] if t >= ramp[-1][0] else ramp[0][1]

    for t in (100.0, 300.0, 600.0, 900.0, 1200.0, 1800.0):
        assert sum(at(r, t) for r in ramps) / n == pytest.approx(deck._interp(curve, t), abs=2e-3)
    first_full = next(t for t, f in ramps[0] if f >= 1.0)
    last_lit = next(t for t, f in ramps[-1] if f > 0.0)
    assert first_full <= last_lit, "the upstream segment is fully alight before the downstream one lights"
    for r in ramps:
        times = [t for t, _ in r]
        assert times == sorted(set(times)), "FDS needs strictly increasing T"


def test_the_fire_is_emitted_as_one_burner_segment_per_cell_along_the_load():
    from solit2.engines.reduced.geometry import section_geometry
    design = Design.load(BASELINE)
    text = deck.generate(design)
    box = deck.fuel_box(design, section_geometry(design))
    n = round((box.x1 - box.x0) / deck.DX_M)
    assert text.count("&SURF ID='FIRE") == n
    assert text.count("SURF_IDS='FIRE") == n
    assert all(f"&RAMP ID='FIRE_RAMP{k}'" in text for k in range(n))


def test_the_droplet_diameter_handed_to_fds_is_the_volume_median_not_the_sauter_mean():
    # PART DIAMETER is D_v,0.5 (User Guide); the design records D32. For FDS's
    # default distribution at GAMMA_D 2.4 the ratio is 1.14, so passing D32
    # straight through ran a spray 12% finer than specified.
    design = Design.load(BASELINE)
    smd = design.nozzles.modes[0].smd_um
    assert deck._dv50_over_d32(2.4) == pytest.approx(1.14, abs=0.005)
    assert f"DIAMETER={deck.volume_median_um(smd):.1f}" in deck.generate(design)
    assert deck.volume_median_um(smd) > smd


def test_the_pumps_ramp_to_full_flow_after_activation():
    design = Design.load(BASELINE)
    text = deck.generate(design)
    assert f"FLOW_RAMP='{deck.PUMP_RAMP_ID}'" in text
    assert f"&RAMP ID='{deck.PUMP_RAMP_ID}', T={design.zones.pump_ramp_s:.1f}, F=1.0 /" in text
    instant = design.model_copy(update={"zones": design.zones.model_copy(update={"pump_ramp_s": 0.0})})
    assert "FLOW_RAMP" not in deck.generate(instant)


def test_the_free_burn_deck_is_the_same_fire_with_no_mist_system():
    design = Design.load(BASELINE)
    mist, free = deck.generate(design), deck.generate(design, suppression=False)
    assert deck.chid(design, suppression=False) != deck.chid(design)
    assert f"CHID='{deck.chid(design, suppression=False)}'" in free
    for token in ("&PART", "&PROP", "PROP_ID='NOZ_FINE'", "MPUV"):
        assert token in mist and token not in free
    fire = lambda text: [ln for ln in text.splitlines() if "FIRE" in ln or ln.startswith("&OBST")]  # noqa: E731
    assert fire(mist) == fire(free), "same fire, same tunnel, same target"
    assert "&CTRL ID='DETECT'" in free, "detection is still timed in the free burn"


def test_a_run_knows_whether_its_deck_is_still_the_one_this_design_generates(tmp_path):
    """The run directory is named after the DESIGN, so a run made before this
    module changed keeps its name while describing a different experiment. That
    is how a result gets attributed to geometry it never simulated."""
    design = Design.load(BASELINE)
    assert deck.matches_design(tmp_path, design) is None, "no deck to compare"

    (tmp_path / "deck.fds").write_text(deck.generate(design))
    assert deck.matches_design(tmp_path, design) is True

    # a deliberately shortened window is the same deck, not a different one
    (tmp_path / "deck.fds").write_text(deck.generate(design, t_end_s=300.0))
    assert deck.matches_design(tmp_path, design) is True

    # the free-burn variant is compared against the free-burn deck
    (tmp_path / "deck.fds").write_text(deck.generate(design, suppression=False))
    assert deck.matches_design(tmp_path, design) is True

    # anything else is stale, however plausible it looks
    stale = deck.generate(design).replace("E_COEFFICIENT=0.4", "E_COEFFICIENT=0.9")
    (tmp_path / "deck.fds").write_text(stale)
    assert deck.matches_design(tmp_path, design) is False
    (tmp_path / "deck.fds").write_text(deck.generate(Design.load(TEST_RIG)))
    assert deck.matches_design(tmp_path, design) is False


def test_no_station_thermocouple_is_emitted_inside_the_lining():
    """Tier 1 lays its ladder out from the section's TRUE crown, but the deck
    emits a stair-stepped bore whose top layer is solid across the full width.
    Five Annex 7 stations had their uppermost thermocouple at 7.25 m with the
    highest open layer topping at 7.20 m: in a real run every one read exactly
    ambient for 250 s while the rung below it reached 80 C."""
    from solit2.engines.reduced.geometry import section_geometry
    for path in (BASELINE, TEST_RIG):
        design = Design.load(path)
        geom = section_geometry(design)
        text = deck.generate(design)
        open_top = (geom.crown_height_m if geom.shape == "box" else
                    max(z for _, z, clear in deck._bore_layers(geom, deck.DX_M) if clear > 0.0))
        rungs = [ln for ln in text.splitlines()
                 if ln.startswith("&DEVC ID='") and "_TC" in ln and "QUANTITY='THERMOCOUPLE'" in ln]
        assert rungs
        for line in rungs:
            z = float(line.split("XYZ=")[1].split(",")[2])
            assert z < open_top, f"{path}: {line.strip()} is inside the lining"


def test_a_thermocouple_already_in_gas_is_left_exactly_where_tier_1_puts_it():
    from solit2.engines.reduced.criteria import thermocouple_heights_m
    from solit2.engines.reduced.geometry import section_geometry
    design = Design.load(BASELINE)
    geom = section_geometry(design)
    heights = thermocouple_heights_m(7, geom.crown_height_m)
    # Since the mesh spans the whole bore, every Annex 7 rung now lands in gas
    # on this section and nothing is moved at all.
    for z in heights:
        assert deck.gas_z_m(geom, 0.0, z) == z, f"{z} m should need no adjustment"
    # the clamp still bites on anything asked for above the emitted ceiling
    assert deck.gas_z_m(geom, 0.0, geom.crown_height_m) < geom.crown_height_m
    assert deck.gas_z_m(geom, 0.0, 1.8) == 1.8, "breathing height is never moved"


def test_both_tiers_radiate_the_same_fraction_of_the_fire():
    """The radiative fraction decides every heat-flux reading and, through them,
    whether the target ignites. The deck left it to FDS's default, which happens
    to equal Tier 1's Class A figure and does not equal its Class B one: on a
    diesel pool the two tiers radiated differently, and the agreement on wood
    was a coincidence rather than a constraint."""
    from solit2.engines.reduced.fire import (RADIATIVE_FRACTION_CLASS_A,
                                             RADIATIVE_FRACTION_CLASS_B)
    assert RADIATIVE_FRACTION_CLASS_A != RADIATIVE_FRACTION_CLASS_B, "else this proves nothing"
    for path, expected in ((BASELINE, RADIATIVE_FRACTION_CLASS_A),
                           ("examples/designs/solit2-test-protocol-class-b.json",
                            RADIATIVE_FRACTION_CLASS_B)):
        reac = next(ln for ln in deck.generate(Design.load(path)).splitlines()
                    if ln.startswith("&REAC"))
        assert f"RADIATIVE_FRACTION={expected:.2f}" in reac, path


def test_every_instrument_table_5_counts_is_emitted_at_its_own_count():
    """The criteria read one value from each cross-section, so the deck emitted
    one. A real test records the whole profile, and a Tier 2 result that cannot
    be set beside a test data sheet column for column is harder to check than
    it needs to be."""
    from solit2.engines.reduced.criteria import INSTRUMENTS, STATIONS
    text = deck.generate(Design.load(BASELINE))
    for name, kit in INSTRUMENTS.items():
        if not (STATIONS[name] >= deck.WINDOW_M[0] and STATIONS[name] <= deck.WINDOW_M[1]):
            continue
        assert text.count(f"ID='{name}_O2_") == kit.oxygen, name
        assert text.count(f"ID='{name}_CO2_") == kit.carbon_dioxide, name
        assert text.count(f"ID='{name}_COP_") == kit.carbon_monoxide, name
        assert text.count(f"ID='{name}_UBI_") == kit.bidirectional, name
        assert text.count(f"ID='{name}_RH'") == (1 if kit.relative_humidity else 0), name
        assert text.count(f"ID='{name}_TCREF'") == (1 if kit.reference_thermocouple else 0), name
    # a station Table 5 gives no gas kit to keeps none
    assert "D25_O2_" not in text and "D25_UBI_" not in text


def test_the_profile_instruments_do_not_disturb_the_ones_the_criteria_read():
    """`_at` matches device IDs exactly, so `D45_CO` and `D45_COP_0` are
    different columns -- but only if the naming keeps them apart."""
    from solit2.engines.reduced.criteria import INSTRUMENTS
    text = deck.generate(Design.load(BASELINE))
    for name, kit in INSTRUMENTS.items():
        if kit.toxic_gas:
            assert f"ID='{name}_CO'," in text, "the breathing-height CO the criteria read"
            assert f"ID='{name}_FED'," in text
        if kit.air_velocity:
            assert f"ID='{name}_U'," in text, "the single velocity the reader reads"
    ids = [ln.split("ID='")[1].split("'")[0] for ln in text.splitlines()
           if ln.startswith("&DEVC ID='")]
    assert len(ids) == len(set(ids)), "every device id must be unique"


def test_profile_instruments_sit_in_gas_like_every_other_device():
    from solit2.engines.reduced.geometry import section_geometry
    geom = section_geometry(Design.load(BASELINE))
    text = deck.generate(Design.load(BASELINE))
    open_top = max(z for _, z, clear in deck._bore_layers(geom, deck.DX_M) if clear > 0.0)
    for line in text.splitlines():
        if line.startswith("&DEVC ID='") and any(t in line for t in ("_O2_", "_CO2_", "_COP_", "_UBI_")):
            assert float(line.split("XYZ=")[1].split(",")[2]) < open_top, line






def _devices(text: str) -> list[tuple[str, float, float, float]]:
    import re
    out = []
    for line in text.splitlines():
        m = re.match(r"&DEVC ID='([^']+)'.*XYZ=([-\d.]+),([-\d.]+),([-\d.]+)", line)
        if m:
            out.append((m.group(1), float(m.group(2)), float(m.group(3)), float(m.group(4))))
    return out


def _solid_boxes(text: str) -> list[tuple[list[float], str]]:
    import re
    out = []
    for line in text.splitlines():
        m = re.match(r"&OBST XB=([-\d.,]+),\s*SURF_IDS?=", line)
        if m:
            kind = "WALL" if "'WALL'" in line else ("FIRE" if "FIRE" in line else "TARGET")
            out.append(([float(v) for v in m.group(1).split(",")[:6]], kind))
    return out


ALL_DESIGNS = (BASELINE, TEST_RIG, "examples/designs/road-tunnel-twin-bore.json",
               "examples/designs/solit2-test-protocol-class-b.json")


def test_every_device_is_inside_the_mesh():
    from solit2.engines.reduced.geometry import section_geometry
    for path in ALL_DESIGNS:
        design = Design.load(path)
        geom = section_geometry(design)
        text = deck.generate(design)
        j, k = deck._mesh_extent(geom, deck.DX_M)
        half, z_top = j * deck.DX_M / 2, k * deck.DX_M
        devices = _devices(text)
        assert len(devices) > 100, path
        for name, x, y, z in devices:
            assert deck.WINDOW_M[0] <= x <= deck.WINDOW_M[1], (path, name, x)
            assert -half <= y <= half, (path, name, y)
            assert 0.0 <= z <= z_top, (path, name, z)


def test_no_device_is_buried_in_a_solid_except_the_gauge_that_must_be():
    """A device inside a solid reports ambient forever and reads as a
    measurement. It has happened three times in this deck: the ceiling
    thermocouples in the crown slab, the top rung of five Annex 7 station
    trees, and the load-side trees at the cross-sections that cut the mock-up.
    This walks every device against every obstruction so there is no fourth.

    The target's flux gauge is the one exception and not an oversight: FDS's
    boundary GAUGE HEAT FLUX must sit ON the surface it measures.
    """
    for path in ALL_DESIGNS:
        text = deck.generate(Design.load(path))
        solids = _solid_boxes(text)
        assert solids, path
        buried = []
        for name, x, y, z in _devices(text):
            if name == deck.TARGET_GAUGE_ID:
                continue
            for (x0, x1, y0, y1, z0, z1), kind in solids:
                if x0 <= x <= x1 and y0 <= y <= y1 and z0 <= z <= z1:
                    buried.append(f"{name} at ({x},{y},{z}) inside {kind}")
                    break
        assert not buried, f"{path}: " + "; ".join(buried)


def test_the_target_gauge_really_is_on_the_target_surface():
    """The one device allowed inside a solid has to actually be on one."""
    from solit2.engines.reduced.geometry import section_geometry
    design = Design.load(BASELINE)
    box = deck.target_box(design, section_geometry(design))
    name, x, y, z = next(d for d in _devices(deck.generate(design))
                         if d[0] == deck.TARGET_GAUGE_ID)
    assert x == pytest.approx(box.x0) and box.y0 <= y <= box.y1 and box.z0 < z < box.z1



def test_the_cross_section_is_laid_out_the_way_annex_7_figure_16_draws_it():
    """Figure 16 numbers seven thermocouples round a cross-section, and it is
    not the vertical rake on the centreline this engine's ladder builds: two on
    each side wall bracketing the load, one at the ceiling, and two on the load
    itself."""
    from solit2.engines.reduced.criteria import INSTRUMENTS
    from solit2.engines.reduced.geometry import section_geometry
    design = Design.load(BASELINE)
    geom = section_geometry(design)
    fuel = deck.fuel_box(design, geom)
    devices = {n: (x, y, z) for n, x, y, z in _devices(deck.generate(design))}

    at = {p: devices[deck.annex7_id("thermocouple", "D03", p)] for p in range(1, 8)}
    # the wall pair, bracketing the load between its platform and its top
    assert at[1][1] == at[2][1] < 0 and at[4][1] == at[5][1] > 0, "one pair per side wall"
    assert at[1][1] == pytest.approx(-at[5][1]), "and symmetric about the centreline"
    assert at[1][2] == at[5][2] == pytest.approx(fuel.z0), "lower pair at the fuel's base"
    assert at[2][2] == at[4][2] == pytest.approx(fuel.z1), "upper pair at the fuel's top"
    # the ceiling sensor, on the centreline
    assert at[3][1] == 0.0 and at[3][2] == pytest.approx(deck.ceiling_z_at(geom, 0.0), abs=0.005)
    # and the two on the load: beside its outboard face, and above its top
    assert fuel.y1 < at[6][1] < fuel.y1 + deck.DX_M, "06 stands off the load, not in it"
    assert at[7][2] > fuel.z1, "07 sits above the load's top"
    assert at[7][1] == pytest.approx(fuel.y_centre_m)

    # a five-thermocouple section gets the walls and the ceiling only
    assert INSTRUMENTS["D15"].thermocouples == 5
    assert deck.annex7_id("thermocouple", "D15", 5) in devices
    assert deck.annex7_id("thermocouple", "D15", 6) not in devices
    # and a two-thermocouple far-field section gets no Figure 16 layout at all
    assert INSTRUMENTS["D215"].thermocouples == 2
    assert deck.annex7_id("thermocouple", "D215", 1) not in devices


def test_figure_16_ids_follow_annex_7s_own_naming_scheme():
    """Section 6.4.10: "<type>-<location>-<position>", e.g. TC-D40-01."""
    assert deck.annex7_id("thermocouple", "D40", 1) == "TC-D40-01"
    assert deck.annex7_id("heat_flux", "U15", 2) == "HF-U15-02"
    assert f"ID='{deck.annex7_id('thermocouple', 'U05', 3)}'" in deck.generate(Design.load(BASELINE))


def test_the_load_positions_fall_back_to_the_centreline_where_there_is_no_load():
    """06 and 07 attach to the mock-up. U45 carries seven thermocouples and is
    45 m from it, so there is nothing there to attach them to."""
    design = Design.load(BASELINE)
    devices = {n: (x, y, z) for n, x, y, z in _devices(deck.generate(design))}
    for position in (6, 7):
        assert devices[deck.annex7_id("thermocouple", "U45", position)][1] == 0.0


def test_the_deck_writes_restart_files_so_a_run_can_be_picked_up():
    """FDS's own default is effectively never, which leaves a run stopped by
    anything but a graceful stop with nowhere to resume from."""
    text = deck.generate(Design.load(BASELINE))
    dump = next(ln for ln in text.splitlines() if ln.startswith("&DUMP"))
    assert f"DT_RESTART={deck.DT_RESTART_S:.1f}" in dump


def test_only_a_restart_deck_carries_the_restart_flag():
    design = Design.load(BASELINE)
    plain = next(ln for ln in deck.generate(design).splitlines() if ln.startswith("&MISC"))
    resumed = next(ln for ln in deck.generate(design, restart=True).splitlines()
                   if ln.startswith("&MISC"))
    assert "RESTART" not in plain
    assert "RESTART=.TRUE." in resumed
    # and nothing else about the run may drift between the two
    a = deck.generate(design).splitlines()
    b = deck.generate(design, restart=True).splitlines()
    assert [x for x in a if not x.startswith("&MISC")] == [x for x in b if not x.startswith("&MISC")]

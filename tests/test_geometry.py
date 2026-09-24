import json

import pytest
from solit2.schema.design import Design
from solit2.engines.reduced.geometry import SectionGeometry, section_geometry, nozzle_positions

BASELINE = "examples/designs/road-tunnel-twin-bore.json"


def test_bored_section_matches_the_ga_drawing():
    # 11.0 m internal diameter, carriageway 2.125 m below the centre
    geom = section_geometry(Design.load(BASELINE))
    assert geom.road_width_m == pytest.approx(10.146, abs=0.01)
    assert geom.crown_height_m == pytest.approx(7.625, abs=0.01)
    assert geom.free_area_m2 == pytest.approx(70.29, abs=0.1)
    assert geom.mean_height_m == pytest.approx(6.928, abs=0.02)


def test_bored_width_at_clearance_height():
    geom = section_geometry(Design.load(BASELINE))
    assert geom.width_at(5.5) == pytest.approx(8.686, abs=0.01)
    assert geom.width_at(0.0) == pytest.approx(10.146, abs=0.01)


def test_width_above_the_crown_is_zero():
    geom = section_geometry(Design.load(BASELINE))
    assert geom.width_at(7.7) == 0.0


def test_box_section_uses_plain_rectangle():
    d = Design.load(BASELINE).model_copy(
        update={"tunnel": Design.load(BASELINE).tunnel.model_copy(
            update={"section": "test", "shape": "box", "width_m": 9.5,
                    "height_m": 5.17, "area_m2": 48.0})})
    geom = section_geometry(d)
    assert geom.road_width_m == pytest.approx(9.5)
    assert geom.crown_height_m == pytest.approx(5.17)
    assert geom.free_area_m2 == pytest.approx(48.0)
    assert geom.width_at(3.0) == pytest.approx(9.5)


def test_nozzle_positions_are_staggered_and_cover_the_active_length():
    d = Design.load(BASELINE)
    geom = section_geometry(d)
    pos = nozzle_positions(d, geom, fire_x_m=0.0)
    assert len(pos) == d.active_heads == 75
    assert min(p.x_m for p in pos) == pytest.approx(-44.4, abs=0.1)
    assert max(p.x_m for p in pos) == pytest.approx(44.4, abs=0.1)
    # consecutive heads alternate rows
    assert pos[0].row != pos[1].row
    # spacing along the tunnel is pitch / rows
    assert pos[1].x_m - pos[0].x_m == pytest.approx(1.2, abs=0.01)
    assert all(p.z_m == pytest.approx(5.75) for p in pos)
    assert sorted({round(p.y_m, 2) for p in pos}) == [-2.5, 2.5]


def test_rows_must_fit_inside_the_section_at_mounting_height():
    d = Design.load(BASELINE)
    bad = d.model_copy(update={"nozzles": d.nozzles.model_copy(
        update={"mounting": d.nozzles.mounting.model_copy(
            update={"row_lateral_offsets_m": (-4.6, 4.6)})})})
    with pytest.raises(ValueError) as e:
        nozzle_positions(bad, section_geometry(bad), fire_x_m=0.0)
    # Width at 5.75m mounting height is 8.27m (8.69 is at 5.5m clearance height)
    assert "4.6" in str(e.value) and "8.27" in str(e.value)


def test_circular_hydraulic_diameter_uses_the_free_area_perimeter_not_the_full_circle():
    """`hydraulic_diameter_m` had no coverage and its circle branch used the
    full circumference, double-counting the arc below the deck (not wetted --
    it bounds ground/services, not the air space) and omitting the deck itself
    (which is wetted). Pinned against a value derived independently: the arc
    above the deck subtends 2*pi - 2*acos(d/r), the deck chord is `road_width_m`,
    and D_h = 4A / (that arc + that chord)."""
    import math
    r, d, free_area = 5.5, 2.125, 70.29
    geom = SectionGeometry("bored", 10.146, 7.625, free_area, "circle", r, d)

    major_arc = 2 * r * (math.pi - math.acos(d / r))
    expected = 4 * free_area / (major_arc + geom.road_width_m)
    assert geom.hydraulic_diameter_m == pytest.approx(expected)

    # and it must differ from the old (wrong) full-circumference answer --
    # a regression back to that formula must fail this test, not pass it by
    # coincidence.
    old_wrong = 4 * free_area / (2 * math.pi * r)
    assert geom.hydraulic_diameter_m != pytest.approx(old_wrong, rel=0.01)


def test_circular_hydraulic_diameter_matches_a_semicircle_at_the_centre_deck():
    """Sanity limit: a deck exactly at the circle's centre (d=0) is a true
    semicircle, whose wetted perimeter is unambiguous -- half the circumference
    (the arc) plus the full diameter (the flat deck) -- checkable independently
    of the general segment formula this property uses."""
    import math
    r = 5.0
    free_area = math.pi * r**2 / 2.0          # exact semicircle area
    geom = SectionGeometry("semicircular", 2 * r, r, free_area, "circle", r, 0.0)

    perimeter = math.pi * r + 2 * r           # half the circumference + the diameter
    assert geom.hydraulic_diameter_m == pytest.approx(4 * free_area / perimeter)


def test_box_hydraulic_diameter_is_unaffected():
    """Regression guard: the box branch is untouched by the circle-case fix."""
    geom = SectionGeometry("cut_cover", 9.0, 6.5, 58.5, "box")
    assert geom.hydraulic_diameter_m == pytest.approx(4 * 58.5 / (2 * (9.0 + 6.5)))


def test_the_fuel_load_must_fit_inside_the_carriageway_not_merely_its_centreline():
    """An offset under half the load's width puts its near face past the wall.

    Nothing downstream would say so: the FDS deck snaps the obstruction into the
    wall solid and burns a surface that is buried, which reads as a quietly weak
    fire rather than as an error. Annex 7 5.2.3 asks for under 1.5 m of clearance
    at the near FACE, so an offset in that range is the plausible misreading.
    """
    from solit2.engines.reduced.geometry import fire_lateral_m, section_geometry
    from solit2.schema.design import Design
    design = Design.load("designs/og-dbr-rev0.json")
    geom = section_geometry(design)
    half = design.fire.footprint.width_m / 2.0

    def with_offset(offset: float):
        fire = design.fire.model_copy(update={"lane_centre_offset_from_wall_m": offset})
        return design.model_copy(update={"fire": fire})

    # the design's own value is eccentric and fits
    y = fire_lateral_m(design, geom)
    assert y < 0.0 and y - half >= -geom.road_width_m / 2.0

    for bad in (half - 0.2, 0.5):
        with pytest.raises(ValueError, match="outside the"):
            fire_lateral_m(with_offset(bad), geom)
    # exactly against each wall is allowed: the load touches it but does not cross,
    # and Annex 7 sets no minimum clearance, only a 1.5 m maximum
    assert fire_lateral_m(with_offset(half), geom) == pytest.approx(
        half - geom.road_width_m / 2.0)
    assert fire_lateral_m(with_offset(geom.road_width_m - half), geom) == pytest.approx(
        geom.road_width_m / 2.0 - half)


def test_every_shipped_design_seats_its_fuel_load_inside_the_carriageway():
    """A guard on the guard: the check above is only worth having if the designs
    this repo ships actually pass it."""
    from pathlib import Path

    from solit2.engines.reduced.geometry import fire_lateral_m, section_geometry
    from solit2.schema.design import Design
    paths = sorted(Path("examples/designs").glob("*.json")) + sorted(Path("designs").glob("*.json"))
    assert len(paths) > 3
    for path in paths:
        raw = json.loads(path.read_text())
        # Compliance specs and project rule files live beside the designs but are
        # not designs; skip them by their own markers, never by catching an error.
        if "spec_version" in raw or {"rules", "source_document"} <= raw.keys():
            continue
        design = Design.load(path)
        fire_lateral_m(design, section_geometry(design))

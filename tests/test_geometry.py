import pytest
from solit2.schema.design import Design
from solit2.engines.reduced.geometry import section_geometry, nozzle_positions

BASELINE = "designs/og-dbr-rev0.json"


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

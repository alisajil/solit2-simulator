"""Pure builders: no Streamlit, no browser. Real data only -- see overview.py's
own docstring for what is deliberately left out (pump position, wall side)."""
import pytest
from plotly.basedatatypes import BaseTraceType

from app.components import overview
from solit2.engines.reduced.geometry import nozzle_positions, section_geometry
from solit2.schema.design import Design

EXAMPLE = "examples/designs/road-tunnel-twin-bore.json"


@pytest.fixture(scope="module")
def design():
    return Design.load(EXAMPLE)


@pytest.fixture(scope="module")
def geom(design):
    return section_geometry(design)


def test_tunnel_outline_is_the_real_road_width(design, geom):
    shape = overview.tunnel_outline(design, geom, (-50.0, 50.0))
    assert shape["y1"] - shape["y0"] == pytest.approx(geom.road_width_m)
    assert (shape["x0"], shape["x1"]) == (-50.0, 50.0)


def test_fire_and_target_use_the_footprints_own_dimensions(design, geom):
    fp = design.fire.footprint
    fire, target = overview.fire_and_target(design, geom)
    assert (fire["x0"], fire["x1"]) == (-fp.length_m / 2, fp.length_m / 2)
    assert fire["y1"] - fire["y0"] == pytest.approx(fp.width_m)
    assert target["x0"] == pytest.approx(design.fire.target_x_m)
    assert target["x1"] - target["x0"] == pytest.approx(fp.width_m), \
        "target length mirrors twin_canvas's own reasoning: width, not fp.length_m"


def test_fire_and_target_sit_where_both_engines_put_them_not_on_the_centreline(design, geom):
    # Annex 7 5.2.3: eccentric toward one wall. Tier 1's mist envelope and the
    # FDS deck both use `fire_lateral_m`; a centred drawing showed an experiment
    # neither engine runs.
    from solit2.engines.reduced.geometry import fire_lateral_m
    y = fire_lateral_m(design, geom)
    assert y != 0.0
    fire, target = overview.fire_and_target(design, geom)
    for shape in (fire, target):
        assert (shape["y0"] + shape["y1"]) / 2 == pytest.approx(y)
    # the near-wall clearance is the preset's own arithmetic: offset - width/2
    assert fire["y0"] - (-geom.road_width_m / 2) == pytest.approx(
        design.fire.lane_centre_offset_from_wall_m - design.fire.footprint.width_m / 2)


def test_nozzle_line_connects_each_rows_real_heads_in_x_order(design, geom):
    heads = nozzle_positions(design, geom, fire_x_m=0.0)
    rows = overview.nozzle_line(design, geom)
    assert len(rows) == len({h.row for h in heads})
    for trace in rows:
        xs = list(trace.x)
        assert xs == sorted(xs), "heads must be connected in x order, not insertion order"
        matching = [h for h in heads if h.y_m == trace.y[0]]
        assert len(xs) == len(matching)


def test_ventilation_arrow_names_the_real_configured_range(geom):
    arrow = overview.ventilation_arrow((-50.0, 50.0), geom, (1.5, 3.0))
    label = next(t for t in arrow.text if t)
    assert "1.5" in label and "3.0" in label and "downstream" in label
    # The label sits at the line's midpoint: an endpoint anchor runs longer text
    # straight off the plot's right edge (caught live in the browser).
    x0, x1 = arrow.x[0], arrow.x[-1]
    label_x = arrow.x[list(arrow.text).index(label)]
    assert label_x == pytest.approx((x0 + x1) / 2)


def test_figure_spans_every_head_the_fire_and_the_target(design, geom):
    fig = overview.figure(design, geom)
    heads = nozzle_positions(design, geom, fire_x_m=0.0)
    x0, x1 = fig.layout.xaxis.range
    for h in heads:
        assert x0 <= h.x_m <= x1
    assert x1 >= design.fire.target_x_m + design.fire.footprint.width_m
    assert all(isinstance(t, BaseTraceType) for t in fig.data)


def test_figure_keeps_a_true_aspect_ratio(design, geom):
    fig = overview.figure(design, geom)
    assert fig.layout.yaxis.scaleanchor == "x" and fig.layout.yaxis.scaleratio == 1

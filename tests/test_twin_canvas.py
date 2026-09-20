"""Layer functions are pure: every assertion here is on traces/shapes, no browser."""
import pytest
from plotly.basedatatypes import BaseTraceType

from app.components import twin_canvas as tc
from solit2.engines.reduced.criteria import STATIONS
from solit2.engines.reduced.geometry import nozzle_positions, section_geometry
from solit2.engines.reduced.sim import run_once
from solit2.schema.design import Design

EXAMPLE = "examples/designs/road-tunnel-twin-bore.json"


@pytest.fixture(scope="module")
def design():
    return Design.load(EXAMPLE)


@pytest.fixture(scope="module")
def trace(design):
    return run_once(design, design.tunnel.section, design.ventilation.velocity_range_ms[0])


@pytest.fixture(scope="module")
def geom(design):
    return section_geometry(design)


def _wet_step(trace):
    return next(s for s in trace.steps if s.water_lpm > 0)


def _shapes_of_type(shapes, kind):
    return [s for s in shapes if s["type"] == kind]


def test_tunnel_layer_places_mock_up_target_and_every_head(design, geom, trace):
    step = trace.steps[0]
    traces, shapes = tc.tunnel_layer(design, geom, tc.WINDOW_M, step)
    rects = _shapes_of_type(shapes, "rect")
    fp = design.fire.footprint
    assert (rects[0]["x0"], rects[0]["x1"]) == (-fp.length_m / 2, fp.length_m / 2)
    assert rects[1]["x0"] == pytest.approx(design.fire.target_x_m)
    heads = traces[0]
    assert len(heads.x) == len(nozzle_positions(design, geom, 0.0))
    assert len(traces) == 3


def test_tunnel_layer_fills_the_target_red_only_when_it_ignited(design, geom, trace):
    step = trace.steps[0]
    _, plain = tc.tunnel_layer(design, geom, tc.WINDOW_M, step)
    _, lit = tc.tunnel_layer(design, geom, tc.WINDOW_M, step, target_ignited=True)
    assert _shapes_of_type(plain, "rect")[1]["fillcolor"] == "rgba(0,0,0,0)"
    assert "196,69,43" in _shapes_of_type(lit, "rect")[1]["fillcolor"]


def test_nozzle_heads_light_up_when_water_flows(design, geom, trace):
    idle, _ = tc.tunnel_layer(design, geom, tc.WINDOW_M, trace.steps[0])
    wet, _ = tc.tunnel_layer(design, geom, tc.WINDOW_M, _wet_step(trace))
    assert idle[0].marker.color != wet[0].marker.color
    assert wet[0].marker.color == tc.MIST_COLOUR


def test_instrument_layer_has_one_mast_per_station_and_one_dot_per_thermocouple(design, geom, trace):
    step = trace.steps[len(trace.steps) // 2]
    traces, shapes = tc.instrument_layer(design, geom, step, tc.WINDOW_M, 400.0)
    in_window = [n for n, x in STATIONS.items() if tc.WINDOW_M[0] <= x <= tc.WINDOW_M[1]]
    assert len(_shapes_of_type(shapes, "line")) == len(in_window)
    assert len(traces[0].x) == sum(len(step.stations[n].heights_m) for n in in_window)
    assert len(traces) == 3 and list(traces[2].text) == sorted(in_window, key=STATIONS.get)


def test_fire_marker_grows_with_heat_release(design, geom, trace):
    cold = tc.fire_layer(design, geom, trace.steps[0], 400.0)[0][0]
    peak = max(trace.steps, key=lambda s: s.hrr_mw)
    hot = tc.fire_layer(design, geom, peak, 400.0)[0][0]
    assert hot.marker.size > cold.marker.size
    assert cold.marker.size >= tc.FIRE_MARKER_MIN_PX and hot.marker.size <= tc.FIRE_MARKER_MAX_PX


def test_mist_layer_is_one_trace_always_and_one_rectangle_only_when_discharging(design, geom, trace):
    dry_traces, dry_shapes = tc.mist_layer(design, geom, trace.steps[0])
    wet_traces, wet_shapes = tc.mist_layer(design, geom, _wet_step(trace))
    assert len(dry_traces) == 1 and dry_shapes == []
    assert len(wet_traces) == 1 and len(wet_shapes) == 1
    half = design.zones.section_length_m * design.zones.sections_simultaneous / 2
    assert (wet_shapes[0]["x0"], wet_shapes[0]["x1"]) == (-half, half)
    assert wet_shapes[0]["y1"] == design.nozzles.mounting.height_above_carriageway_m


def test_temp_max_rounds_the_peak_up_to_the_next_hundred_but_never_below_400(trace):
    assert tc.temp_max_c(trace) >= 400.0
    assert tc.temp_max_c(trace) % 100 == 0


def test_every_layer_returns_plotly_traces(design, geom, trace):
    step = trace.steps[-1]
    for traces, _ in (tc.tunnel_layer(design, geom, tc.WINDOW_M, step),
                      tc.instrument_layer(design, geom, step, tc.WINDOW_M, 400.0),
                      tc.fire_layer(design, geom, step, 400.0),
                      tc.mist_layer(design, geom, step)):
        assert all(isinstance(t, BaseTraceType) for t in traces)

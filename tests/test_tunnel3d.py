"""The 3D tunnel is the design's geometry and the engine's state, nothing more."""
from dataclasses import replace

import numpy as np
import pytest

from app import palette
from app.components import tunnel3d, twin_canvas
from solit2.engines.reduced import envelope
from solit2.engines.reduced.criteria import STATIONS
from solit2.engines.reduced.geometry import section_geometry
from solit2.engines.reduced.sim import run_once
from solit2.schema.design import Design

PROTOCOL = "examples/designs/solit2-test-protocol.json"


@pytest.fixture(scope="module")
def run():
    design = Design.load(PROTOCOL)
    result = envelope.run(design)
    trace = run_once(design, result.worst_case["section"], result.worst_case["velocity_ms"])
    return design, section_geometry(design), trace, twin_canvas.core_window_m(design)


def _dynamic(run, step):
    design, geom, trace, window = run
    return tunnel3d.dynamic_traces(design, geom, step, window,
                                   hrr_peak_mw=max(s.hrr_mw for s in trace.steps),
                                   cmax_c=twin_canvas.temp_max_c(trace))


def test_a_box_has_eight_corners_at_its_extents_and_twelve_triangles():
    b = tunnel3d.box((0.0, 2.0), (-1.0, 1.0), (0.0, 3.0), name="b", colour="#000000", opacity=1.0)
    assert sorted(set(b.x)) == [0.0, 2.0]
    assert sorted(set(b.y)) == [-1.0, 1.0]
    assert sorted(set(b.z)) == [0.0, 3.0]
    assert len(b.i) == len(b.j) == len(b.k) == 12


def test_the_fire_load_is_the_footprint(run):
    design, geom, _, window = run
    fire = next(t for t in tunnel3d.static_traces(design, geom, window) if t.name == "fire load")
    fp = design.fire.footprint
    assert (min(fire.x), max(fire.x)) == (-fp.length_m / 2, fp.length_m / 2)
    assert (min(fire.z), max(fire.z)) == (fp.base_height_m, fp.top_height_m)


def test_there_are_always_six_dynamic_traces_in_a_fixed_order(run):
    traces = _dynamic(run, run[2].steps[0])
    assert [t.type for t in traces] == ["scatter3d", "mesh3d", "scatter3d", "mesh3d",
                                        "surface", "cone"]


def test_heads_take_the_mist_colour_only_while_water_flows(run):
    design, geom, trace, window = run
    dry = next(s for s in trace.steps if s.water_lpm == 0)
    full = next(s for s in trace.steps if s.water_lpm >= design.flow_lpm)
    assert _dynamic(run, dry)[2].marker.color == palette.GREY
    assert _dynamic(run, full)[2].marker.color == palette.PRIMARY


def test_the_spray_is_invisible_before_discharge(run):
    design, geom, trace, window = run
    dry = next(s for s in trace.steps if s.water_lpm == 0)
    full = next(s for s in trace.steps if s.water_lpm >= design.flow_lpm)
    assert _dynamic(run, dry)[3].opacity == 0.0
    assert _dynamic(run, full)[3].opacity == pytest.approx(tunnel3d.SPRAY_OPACITY)


def test_heads_and_spray_ramp_with_pump_discharge(run):
    design, geom, trace, window = run
    ramp = next(s for s in trace.steps if 0 < s.water_lpm < design.flow_lpm)
    heads_colour = _dynamic(run, ramp)[2].marker.color
    spray_opacity = _dynamic(run, ramp)[3].opacity
    # Head colour during ramp is rgba with alpha between HEAD_RAMP_MIN_ALPHA and 1
    assert isinstance(heads_colour, str) and heads_colour.startswith("rgba(")
    # Extract alpha from "rgba(r,g,b,a)" format
    alpha_str = heads_colour.split(",")[-1].rstrip(")")
    alpha = float(alpha_str)
    assert 0 < alpha < 1
    # Spray opacity scales linearly during ramp
    assert 0 < spray_opacity < tunnel3d.SPRAY_OPACITY


def test_schematic_traces_show_in_legend(run):
    design, geom, trace, window = run
    step = trace.steps[0]
    static = tunnel3d.static_traces(design, geom, window)
    dynamic = tunnel3d.dynamic_traces(design, geom, step, window,
                                      hrr_peak_mw=max(s.hrr_mw for s in trace.steps),
                                      cmax_c=twin_canvas.temp_max_c(trace))
    all_traces = static + dynamic
    schematic_traces = [t for t in all_traces
                       if hasattr(t, 'name') and 'schematic' in t.name]
    assert len(schematic_traces) == 2, f"Expected 2 schematic traces, got {len(schematic_traces)}"
    for t in schematic_traces:
        assert t.showlegend is True, f"Schematic trace '{t.name}' must have showlegend=True"
        assert 'schematic' in t.name


def test_smoke_starts_at_the_backlayering_front(run):
    window = run[3]
    step = run[2].steps[len(run[2].steps) // 2]
    back = replace(step, backlayer_m=12.0)
    assert _dynamic(run, back)[4].x[0] == pytest.approx(max(-12.0, window[0]))
    none = replace(step, backlayer_m=0.0)
    assert _dynamic(run, none)[4].x[0] == pytest.approx(0.0)


def test_smoke_colour_at_a_station_is_that_stations_top_thermocouple(run):
    step = run[2].steps[len(run[2].steps) // 2]
    at_d15 = tunnel3d.smoke_profile(step, np.array([STATIONS["D15"]]))[0]
    assert at_d15 == pytest.approx(step.stations["D15"].temps_c[-1])


def test_the_flame_marker_grows_with_heat_release(run):
    steps = run[2].steps
    peak = max(steps, key=lambda s: s.hrr_mw)
    small = min((s for s in steps if s.hrr_mw > 0), key=lambda s: s.hrr_mw)
    assert _dynamic(run, peak)[0].marker.size == pytest.approx(twin_canvas.FIRE_MARKER_MAX_PX)
    assert _dynamic(run, small)[0].marker.size < _dynamic(run, peak)[0].marker.size

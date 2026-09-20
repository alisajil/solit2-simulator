"""Layer functions are pure: every assertion here is on traces/shapes, no browser."""
import numpy as np
import pytest
import plotly.graph_objects as go
from plotly.basedatatypes import BaseTraceType

from app.components import twin_canvas as tc
from solit2.engines.fds.slices import Slice
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


def _steaming_step(trace):
    return next(s for s in trace.steps if s.mist.chi_cool > tc.STEAM_MIN_CHI_COOL)


def _exposed_target_step(trace):
    return next(s for s in trace.steps
               if 0.0 < tc._target_ignition_progress(s) < 1.0)


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
    names = next(t for t in traces if t.name == "stations")
    assert list(names.text) == sorted(in_window, key=STATIONS.get)


def test_flux_gauges_draw_at_1_5_m_and_co_at_breathing_height_where_table_5_puts_them(design, geom, trace):
    # Annex 7 6.4.2: heat-flux gauges at 1.5 m (U15, D15); 6.4.5: opacimeters
    # at 1.5 m. CO and the toxic dose are breathing-height quantities. The FDS
    # deck measures at exactly these heights, so the drawing must too -- one
    # diamond at 1.8 m for everything was 0.3 m off for the flux gauges.
    from solit2.engines.reduced.criteria import HEAT_FLUX_HEIGHT_M, INSTRUMENTS
    step = trace.steps[len(trace.steps) // 2]
    traces, _ = tc.instrument_layer(design, geom, step, tc.WINDOW_M, 400.0)
    flux = next(t for t in traces if t.name.startswith("flux"))
    gas = next(t for t in traces if t.name.startswith("CO"))
    assert set(flux.y) == {HEAT_FLUX_HEIGHT_M} and set(gas.y) == {tc.BREATHING_HEIGHT_M}
    assert set(flux.x) == {STATIONS[n] for n, k in INSTRUMENTS.items() if k.heat_flux or k.visibility}
    assert set(gas.x) == {STATIONS[n] for n, k in INSTRUMENTS.items() if k.carbon_monoxide > 0}


def test_heat_detectors_draw_where_the_fds_deck_trips_on_them(design, geom, trace):
    from solit2.engines.fds import deck
    step = trace.steps[0]
    traces, _ = tc.instrument_layer(design, geom, step, tc.WINDOW_M, 400.0)
    det = next(t for t in traces if t.name == "heat detectors")
    assert list(det.x) == deck.detector_x_m(design)
    assert set(det.y) == {geom.crown_height_m - deck.CEILING_OFFSET_M}
    zoomed, _ = tc.instrument_layer(design, geom, step, (-20.0, 20.0), 400.0)
    assert all(-20.0 <= x <= 20.0 for x in next(t for t in zoomed if t.name == "heat detectors").x)


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


def test_temp_max_rounds_up_so_the_peak_is_never_off_the_scale():
    """`>= 400` and `% 100 == 0` hold for floor, round and ceil alike, so on their own
    they do not pin the direction. Rounding *down* would put the hottest cell past the
    top of the colour scale, where it reads as merely the hottest colour."""
    class _Step:
        def __init__(self, value):
            self.ceiling_temp_c = value

    class _Trace:
        def __init__(self, peak):
            self.steps = (_Step(20.0), _Step(peak))

    assert tc.temp_max_c(_Trace(401.0)) == 500.0     # a hair over -> the next hundred up
    assert tc.temp_max_c(_Trace(500.0)) == 500.0     # exactly on a boundary -> unchanged
    assert tc.temp_max_c(_Trace(899.1)) == 900.0
    assert tc.temp_max_c(_Trace(120.0)) == 400.0     # the floor still wins under 400


def test_every_layer_returns_plotly_traces(design, geom, trace):
    step = trace.steps[-1]
    for traces, _ in (tc.tunnel_layer(design, geom, tc.WINDOW_M, step),
                      tc.instrument_layer(design, geom, step, tc.WINDOW_M, 400.0),
                      tc.fire_layer(design, geom, step, 400.0),
                      tc.mist_layer(design, geom, step)):
        assert all(isinstance(t, BaseTraceType) for t in traces)


def _fake_slice(n_frames=30):
    x = np.linspace(-360.0, 240.0, 11)
    z = np.linspace(0.0, 7.0, 4)
    t = np.arange(n_frames, dtype=float) * 10.0
    frames = np.tile(z[:, None] * 10.0, (n_frames, 1, len(x))) + t[:, None, None]
    return Slice("TEMPERATURE", "C", x, z, t, frames)


def test_mmss_formats_the_test_clock():
    assert tc.mmss(0) == "00:00" and tc.mmss(90) == "01:30" and tc.mmss(3599.6) == "60:00"


def test_sample_steps_takes_one_step_per_stride_from_the_first_recorded_step(trace):
    steps = tc.sample_steps(trace, 30.0)
    t_end = trace.steps[-1].t_s
    # run_once advances by DT_S before recording, so the trace opens at t = 1 s, not 0.
    assert steps[0] is trace.steps[0]
    assert len(steps) == int(t_end // 30.0) + 1
    assert all(b.t_s - a.t_s == pytest.approx(30.0, abs=1.0) for a, b in zip(steps, steps[1:]))


def test_figure_has_one_frame_per_sample_and_a_constant_trace_count(design, trace):
    fig = tc.figure(design, trace)
    assert len(fig.frames) == len(tc.sample_steps(trace, tc.TWIN_FRAME_STRIDE_S))
    n = len(fig.data)
    assert all(len(f.data) == n and list(f.traces) == list(range(n)) for f in fig.frames)
    assert fig.frames[3].name == tc.mmss(90.0)
    assert fig.layout.updatemenus and fig.layout.sliders


def test_figure_with_a_slice_leads_with_a_heatmap_on_the_slice_time_base(design, trace):
    fig = tc.figure(design, trace, cfd=_fake_slice(30))
    assert isinstance(fig.data[0], go.Heatmap)
    assert len(fig.frames) == 30
    assert fig.frames[-1].name == tc.mmss(290.0)


def test_figure_caps_cfd_frames(design, trace):
    fig = tc.figure(design, trace, cfd=_fake_slice(500))
    assert len(fig.frames) <= tc.CFD_MAX_FRAMES


def test_figure_honours_the_window_and_initial_frame(design, trace):
    fig = tc.figure(design, trace, window_m=tc.CORE_WINDOW_M, initial_frame=2)
    assert list(fig.layout.xaxis.range) == list(tc.CORE_WINDOW_M)
    assert fig.layout.sliders[0].active == 2


def test_the_cfd_scale_starts_just_off_black():
    """Streamlit substitutes near-black in a dark theme, which repainted the coldest
    cells in an accent colour — an ambient tunnel then read as the hottest thing on
    screen. Starting a shade above black leaves nothing for it to rewrite."""
    stops = tc.cfd_scale("TEMPERATURE")
    positions = [p for p, _ in stops]
    assert positions == sorted(positions) and positions[0] == 0.0 and positions[-1] == 1.0
    assert not any(tc._is_near_black(c) for _, c in stops)
    assert stops[-1][1] == "#fcffa4", "the warm end of Inferno must be untouched"


def test_fire_marker_sits_at_the_fuel_base_not_floating_above_it(design, geom, trace):
    """A fire starts at the base of its fuel load, not at the top of the stack."""
    traces, _ = tc.fire_layer(design, geom, trace.steps[0], 400.0)
    assert traces[0].y[0] == design.fire.footprint.base_height_m


def test_the_flame_glow_grows_from_the_base_with_heat_release(design, geom, trace):
    cold = tc.fire_layer(design, geom, trace.steps[0], 400.0)[1][0]
    peak = max(trace.steps, key=lambda s: s.hrr_mw)
    hot = tc.fire_layer(design, geom, peak, 400.0)[1][0]
    base = design.fire.footprint.base_height_m
    assert cold["y0"] == base and hot["y0"] == base
    assert hot["y1"] > cold["y1"], "more heat release must reach higher, not just glow brighter"
    assert hot["y1"] <= geom.crown_height_m - tc.FLAME_GLOW_CEILING_MARGIN_M


def test_target_fill_builds_up_with_real_exposure_before_it_fully_ignites(design, geom, trace):
    """The box must not sit invisible right up to the instant it snaps to solid red --
    a fire genuinely closing in on the wood target has to read as closing in."""
    step = _exposed_target_step(trace)
    _, shapes = tc.tunnel_layer(design, geom, tc.WINDOW_M, step)
    target_fill = shapes[1]["fillcolor"]
    assert target_fill != "rgba(0,0,0,0)"
    assert "196,69,43" in target_fill, target_fill

    progress = tc._target_ignition_progress(step)
    assert 0.0 < progress < 1.0
    # An explicit override still wins outright, regardless of the step's own progress.
    _, forced = tc.tunnel_layer(design, geom, tc.WINDOW_M, step, target_ignited=True)
    assert forced[1]["fillcolor"] == "rgba(196,69,43,0.5)"


def test_the_spray_zone_has_a_visible_border(design, geom, trace):
    _, shapes = tc.mist_layer(design, geom, _wet_step(trace))
    assert shapes[0]["line"]["width"] > 0
    assert shapes[0]["line"]["color"] == tc.MIST_COLOUR


def test_steam_appears_above_the_spray_zone_once_evaporation_is_real(design, geom, trace):
    dry_shapes = tc.mist_layer(design, geom, trace.steps[0])[1]
    barely_wet_shapes = tc.mist_layer(design, geom, _wet_step(trace))[1]
    steaming_shapes = tc.mist_layer(design, geom, _steaming_step(trace))[1]

    assert dry_shapes == []
    assert len(barely_wet_shapes) == 1, "no meaningful evaporation yet -- no steam shape"
    assert len(steaming_shapes) == 2

    spray, steam = steaming_shapes
    top = design.nozzles.mounting.height_above_carriageway_m
    assert steam["y0"] == top and steam["y1"] > top
    assert steam["y1"] <= geom.crown_height_m
    assert steam["fillcolor"].startswith("rgba(216,238,236"), steam["fillcolor"]  # palette.STEAM


def test_core_window_grows_with_the_configured_active_zone(design):
    """`CORE_WINDOW_M` is a fixed constant borrowed from the FDS deck's simulation
    domain; a design with a wider active zone than that constant assumes must not
    have its own heads and mist clipped by a window that never moved to match it."""
    bigger = design.model_copy(update={
        "zones": design.zones.model_copy(update={"section_length_m": 60.0})})
    assert bigger.active_length_m == 180.0

    default_window = tc.core_window_m(design)
    bigger_window = tc.core_window_m(bigger)
    half_active = bigger.active_length_m / 2.0

    assert bigger_window[0] < default_window[0] and bigger_window[1] > default_window[1]
    assert bigger_window[0] <= -half_active and bigger_window[1] >= half_active
    # The fixed constant would have clipped this design's own active zone.
    assert tc.CORE_WINDOW_M[0] > -half_active


def test_core_window_always_reaches_the_target(design):
    """A target far downstream of the active zone must still be inside the window --
    zooming to the fire zone should never hide the thing the fire is aimed at."""
    far = design.model_copy(update={
        "fire": design.fire.model_copy(update={"target_distance_m": 200.0})})
    window = tc.core_window_m(far)
    target_far_edge = far.fire.target_x_m + far.fire.footprint.length_m
    assert window[1] >= target_far_edge


def test_core_window_is_symmetric_for_the_default_design(design):
    x0, x1 = tc.core_window_m(design)
    half_active = design.active_length_m / 2.0
    assert x0 == -half_active - tc.CORE_WINDOW_MARGIN_M
    assert x1 == half_active + tc.CORE_WINDOW_MARGIN_M


def test_the_target_box_is_drawn_the_targets_own_width_not_the_fire_loads_length(design, geom, trace):
    """Annex 7 5.2.6 states the target's width, height and combustibility as the
    mock-up's own -- never its along-tunnel length, and the engine itself never
    models one either (target_x_m feeds a single-point flux check). Drawing the
    box fp.length_m long would silently claim a second 10 m mock-up that nothing
    in the standard or the engine supports.
    """
    fp = design.fire.footprint
    step = trace.steps[0]
    _, shapes = tc.tunnel_layer(design, geom, tc.WINDOW_M, step)
    target = _shapes_of_type(shapes, "rect")[1]
    width = target["x1"] - target["x0"]
    assert width == pytest.approx(fp.width_m)
    assert width < fp.length_m
    assert target["x0"] == pytest.approx(design.fire.target_x_m)


def test_core_window_reaches_the_target_by_its_own_width(design):
    """core_window_m's target-visibility margin must track the same width the
    target is actually drawn with, not the fire load's length."""
    fp = design.fire.footprint
    window = tc.core_window_m(design)
    assert window[1] >= design.fire.target_x_m + fp.width_m

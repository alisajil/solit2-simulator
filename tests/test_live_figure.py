"""One figure, one clock: every gauge, the 3D scene and the chart cursors share a frame."""
import pytest

from app.components import live_figure, readings, twin_canvas
from solit2.engines.reduced import envelope
from solit2.engines.reduced.sim import run_once
from solit2.schema.design import Design

PROTOCOL = "examples/designs/solit2-test-protocol.json"


def _build(design: Design):
    result = envelope.run(design)
    trace = run_once(design, result.worst_case["section"], result.worst_case["velocity_ms"])
    fig = live_figure.figure(design, result, trace, window_m=twin_canvas.core_window_m(design))
    steps = twin_canvas.sample_steps(trace, twin_canvas.TWIN_FRAME_STRIDE_S)
    return result, trace, fig, steps


@pytest.fixture(scope="module")
def built():
    return _build(Design.load(PROTOCOL))


def _indicators(data):
    return [d for d in data if d.type == "indicator"]


def test_one_frame_per_sampled_step(built):
    _, _, fig, steps = built
    assert len(fig.frames) == len(steps)


def test_frame_gauges_are_the_engines_readings_at_that_instant(built):
    _, _, fig, steps = built
    for k in (0, len(steps) // 2, len(steps) - 1):
        values = [d.value for d in _indicators(fig.frames[k].data)]
        wanted = [readings.reading(steps[k], g.key) for g in readings.GAUGES]
        assert values == pytest.approx(wanted)


def test_the_chart_cursors_sit_on_the_frames_instant(built):
    _, _, fig, steps = built
    k = len(steps) // 2
    cursors = [d for d in fig.frames[k].data if d.type == "scatter"]
    assert len(cursors) == 3
    assert all(list(c.x) == [steps[k].t_s, steps[k].t_s] for c in cursors)


def test_frames_update_exactly_the_dynamic_traces(built):
    _, _, fig, _ = built
    indices = list(fig.frames[0].traces)
    assert len(indices) == len(fig.frames[0].data)
    assert indices == list(range(len(fig.data) - len(indices), len(fig.data)))


def test_a_gauge_has_a_band_only_where_its_limit_is_set(built):
    result, _, fig, _ = built
    for d, gauge in zip(_indicators(fig.data), readings.GAUGES):
        lim = readings.limit(result, gauge)
        if lim is None:
            assert not d.gauge.steps and d.gauge.threshold.value is None
        else:
            assert d.gauge.threshold.value == lim


def test_a_set_limit_draws_its_band_from_the_limit_up():
    raw = Design.load(PROTOCOL).model_dump(by_alias=True, mode="json")
    raw["ahj"]["max_heat_flux_kwm2"] = 5.0   # a synthetic limit, set by this test only
    _, _, fig, _ = _build(Design.from_dict(raw))
    flux = _indicators(fig.data)[[g.key for g in readings.GAUGES].index("heat_flux_kwm2")]
    assert flux.gauge.threshold.value == 5.0
    assert flux.gauge.steps[0].range[0] == 5.0


def test_the_figure_stays_inside_its_size_budget(built):
    assert len(built[2].to_json()) < live_figure.FIGURE_BUDGET_BYTES

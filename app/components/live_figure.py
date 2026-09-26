"""The simulator's animated figure: gauges, the 3D tunnel and three charts in ONE
Plotly figure, so a single Play button and a single time slider keep every
element on the same instant -- entirely in the browser, with no server round
trip per frame, so playback is as smooth on the remote server as it is locally.

Frames update only the dynamic traces, which sit after every static one; the
frames' `traces` list names their indices.
"""
from __future__ import annotations

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from app import palette
from app.components import readings, tunnel3d, twin_canvas
from solit2.engines.reduced.geometry import SectionGeometry, section_geometry
from solit2.engines.reduced.state import RunTrace, StepRecord
from solit2.schema.design import Design
from solit2.schema.result import Result

# Tall enough to give six gauges, a readable 3D scene and a chart row their own
# space on a laptop screen without the page scrolling mid-row.
FIGURE_HEIGHT_PX = 1180
# The 3D scene is what a viewer watches most, so it takes most of the height;
# gauges and charts share the rest.
ROW_HEIGHTS = (0.16, 0.56, 0.28)
CHART_COLUMNS = (1, 3, 5)          # each chart spans two of the six columns
CHART_TITLES = ("Heat release (MW)", "Breathing-height air (°C)", "Heat flux (kW/m²)")
CHART_STATIONS = ("U45", "U15", "D15", "D45", "D100")
# 5 % above the highest curve on a chart, so its peak never touches the top edge.
CHART_HEADROOM = 1.05
# A whole run's figure, every frame included, stays under this many bytes of JSON:
# a 45 min test at the twin's 30 s stride is about 90 frames.
FIGURE_BUDGET_BYTES = 6_000_000
# Translucent enough that the needle is still readable once it sits over the red zone.
GAUGE_BAND_ALPHA = 0.35


def _bands(limit: readings.Band, top: float) -> list[list[float]]:
    """Where the red zone sits, from the criterion's own comparison (I-4) --
    never assumed from the gauge: `<=` bands from the limit up to the axis top,
    `>=` bands from zero up to the limit, and a two-sided `"in"` limit bands
    BOTH outside sides of its `(lo, hi)` range."""
    if limit.op == "<=":
        return [[limit.limit, top]]
    if limit.op == ">=":
        return [[0.0, limit.limit]]
    lo, hi = limit.limit
    return [[0.0, lo], [hi, top]]


def _threshold(limit: readings.Band) -> float | None:
    """The one value a threshold LINE can mark -- none for a two-sided limit,
    where a single line would misstate which of its two edges it is."""
    return None if limit.op == "in" else limit.limit


def _gauge(gauge: readings.Gauge, value: float, top: float,
           limit: readings.Band | None) -> go.Indicator:
    """One indicator trace for `gauge`'s reading, with a red band and threshold
    line where `limit` is set, and none where it is not."""
    spec: dict = {"axis": {"range": [0.0, top]}, "bar": {"color": palette.PRIMARY}}
    if limit is not None:
        spec["steps"] = [{"range": band, "color": palette.rgba(palette.FAIL, GAUGE_BAND_ALPHA)}
                         for band in _bands(limit, top)]
        threshold = _threshold(limit)
        if threshold is not None:
            spec["threshold"] = {"line": {"color": palette.FAIL, "width": 3}, "value": threshold}
    return go.Indicator(mode="gauge+number", value=value, gauge=spec,
                        number={"suffix": f" {gauge.unit}", "valueformat": ".1f"},
                        title={"text": gauge.label.upper(), "font": {"size": 12}})


def _series(trace: RunTrace) -> list[tuple[int, go.Scatter]]:
    """(chart column, line) for every static chart line."""
    t = [s.t_s for s in trace.steps]
    lines = [
        (1, go.Scatter(x=t, y=[s.hrr_mw for s in trace.steps], name="heat release",
                       mode="lines", line={"color": palette.FLAME})),
        (1, go.Scatter(x=t, y=[s.hrr_free_mw for s in trace.steps],
                       name="free burn (engine)", mode="lines",
                       line={"color": palette.GREY, "dash": "dash"})),
    ]
    for name in CHART_STATIONS:
        lines.append((3, go.Scatter(x=t, y=[s.stations[name].temp_c for s in trace.steps],
                                    name=f"{name} air", mode="lines")))
    lines.append((5, go.Scatter(x=t, y=[readings.reading(s, "heat_flux_kwm2")
                                        for s in trace.steps],
                                name="worst station flux", mode="lines")))
    lines.append((5, go.Scatter(x=t, y=[s.target_flux_kwm2 for s in trace.steps],
                                name="flux at the target", mode="lines",
                                line={"dash": "dot"})))
    return lines


def _cursor(t_s: float, top: float) -> go.Scatter:
    """A vertical line at `t_s`, from the axis floor to `top`, marking the
    frame's instant on one chart."""
    return go.Scatter(x=[t_s, t_s], y=[0.0, top], mode="lines", showlegend=False,
                      hoverinfo="skip", line={"color": palette.UNSET, "width": 2})


def _finish_layout(fig: go.Figure, geom: SectionGeometry, window_m: tuple[float, float],
                   names: list[str], template: go.layout.Template | str | None) -> None:
    """Sets the figure's height, 3D scene, legend, play controls and chart axis titles."""
    fig.update_layout(
        height=FIGURE_HEIGHT_PX, template=template,
        margin={"l": 40, "r": 20, "t": 170, "b": 150},
        scene=tunnel3d.scene_layout(geom, window_m),
        legend={"orientation": "h", "y": -0.16},
        updatemenus=[twin_canvas.play_menu(y=1.22)],
        sliders=[twin_canvas.time_slider(names, 0, y=1.165)])
    for col, title in zip(CHART_COLUMNS, CHART_TITLES):
        fig.update_xaxes(title_text="test clock (s)", row=3, col=col)
        fig.update_yaxes(title_text=title, row=3, col=col)


def figure(design: Design, result: Result, trace: RunTrace, *,
           window_m: tuple[float, float],
           stride_s: float = twin_canvas.TWIN_FRAME_STRIDE_S,
           template: go.layout.Template | str | None = None) -> go.Figure:
    """The one animated figure: six gauges, the 3D tunnel and three charts, all
    keyed to the same frames so a single Play button and slider move them together."""
    geom = section_geometry(design)
    steps = twin_canvas.sample_steps(trace, stride_s)
    names = [twin_canvas.mmss(s.t_s) for s in steps]
    hrr_peak = max(s.hrr_mw for s in trace.steps)
    cmax = twin_canvas.temp_max_c(trace)
    limits = [readings.limit(result, g) for g in readings.GAUGES]
    tops = [readings.axis_max(trace, g, lim) for g, lim in zip(readings.GAUGES, limits)]

    fig = make_subplots(
        rows=3, cols=6, row_heights=list(ROW_HEIGHTS), vertical_spacing=0.05,
        specs=[[{"type": "indicator"}] * 6,
               [{"type": "scene", "colspan": 6}] + [None] * 5,
               [{"type": "xy", "colspan": 2}, None, {"type": "xy", "colspan": 2}, None,
                {"type": "xy", "colspan": 2}, None]])

    # Static traces first: the geometry and the chart lines never change.
    for static in tunnel3d.static_traces(design, geom, window_m):
        fig.add_trace(static, row=2, col=1)
    series = _series(trace)
    for col, line in series:
        fig.add_trace(line, row=3, col=col)
    chart_top = {col: (max(max(line.y) for c, line in series if c == col) * CHART_HEADROOM
                       or 1.0) for col in CHART_COLUMNS}

    def dynamic(step: StepRecord) -> list[tuple[object, int, int]]:
        out: list[tuple[object, int, int]] = [
            (_gauge(g, readings.reading(step, g.key), top, lim), 1, i + 1)
            for i, (g, lim, top) in enumerate(zip(readings.GAUGES, limits, tops))]
        out += [(t, 2, 1) for t in tunnel3d.dynamic_traces(
            design, geom, step, window_m, hrr_peak_mw=hrr_peak, cmax_c=cmax)]
        out += [(_cursor(step.t_s, chart_top[col]), 3, col) for col in CHART_COLUMNS]
        return out

    first = len(fig.data)
    for trace_, row, col in dynamic(steps[0]):
        fig.add_trace(trace_, row=row, col=col)
    indices = list(range(first, len(fig.data)))
    fig.frames = [go.Frame(name=names[k], traces=indices,
                           data=[t for t, _, _ in dynamic(step)])
                  for k, step in enumerate(steps)]

    _finish_layout(fig, geom, window_m, names, template)
    return fig

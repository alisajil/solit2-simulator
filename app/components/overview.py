"""A plan-view (from above) summary of the whole test setup as configured --
the same information Annex 7's own system schematics carry (nozzle line,
fire load, target, ventilation direction), drawn flat rather than as a true
3-D isometric render.

A full 3-D extruded bore was already weighed and deliberately set aside for
the animated twin (`docs/superpowers/plans/2026-09-17-solit2-streamlit-ui.md`:
"a substantial, separate graphics effort with real risk of an under-baked
result"). The same trade-off applies here, so this view gives the same
overview a 3-D schematic would, without the 3-D risk.

Static and design-only: nothing here depends on a `RunTrace` or a test-clock
instant, only on what the design itself specifies.

The fuel load and the target are drawn where the engine puts them: eccentric
toward one side wall, at `fire_lateral_m` -- the same lateral position the
Tier 1 mist envelope and the FDS deck use, so this picture and both engines
describe one experiment (Annex 7 5.2.3 sites the mock-up off-centre on
purpose; the -y side is this repo's convention, see `geometry.fire_lateral_m`).

One thing this repo has no source for is left out rather than guessed: the
pump's own position. The schema records its flow rate and ramp time, never a
location, so no pump marker is drawn.
"""
from __future__ import annotations

import plotly.graph_objects as go

from app import palette
from solit2.engines.reduced.geometry import SectionGeometry, fire_lateral_m, nozzle_positions
from solit2.schema.design import Design

MARGIN_M = 15.0


def _rect(x0: float, x1: float, y0: float, y1: float, **style) -> dict:
    return {"type": "rect", "x0": x0, "x1": x1, "y0": y0, "y1": y1, "layer": "below", **style}


def tunnel_outline(design: Design, geom: SectionGeometry, x_range: tuple[float, float]) -> dict:
    """The carriageway, seen from above -- its real width, however long the view is."""
    half = geom.road_width_m / 2.0
    return _rect(x_range[0], x_range[1], -half, half,
                line={"color": palette.GREY, "width": 1},
                fillcolor=palette.rgba(palette.GREY, 0.06))


def fire_and_target(design: Design, geom: SectionGeometry) -> list[dict]:
    """Real footprints, real position -- the same figures `twin_canvas.tunnel_layer`
    draws, in plan instead of elevation, at the lateral position both engines burn
    the fire. `target_length_m` mirrors that module's own reasoning: Annex 7 gives
    the target's width, never its along-tunnel length."""
    fp = design.fire.footprint
    y = fire_lateral_m(design, geom)
    target_length_m = fp.width_m
    return [
        _rect(-fp.length_m / 2, fp.length_m / 2, y - fp.width_m / 2, y + fp.width_m / 2,
              line={"color": palette.GREY}, fillcolor=palette.rgba(palette.GREY, 0.35)),
        _rect(design.fire.target_x_m, design.fire.target_x_m + target_length_m,
              y - fp.width_m / 2, y + fp.width_m / 2,
              line={"color": palette.FAIL, "dash": "dot"}, fillcolor=palette.TRANSPARENT),
    ]


def nozzle_line(design: Design, geom: SectionGeometry) -> list[go.Scatter]:
    """One trace per row: the row's real heads, connected in x order.

    The connecting line joins real head positions only -- it does not assert a
    specific pipe route, which this schema does not record.
    """
    heads = nozzle_positions(design, geom, fire_x_m=0.0)
    traces = []
    for row in sorted({h.row for h in heads}):
        in_row = sorted((h for h in heads if h.row == row), key=lambda h: h.x_m)
        traces.append(go.Scatter(
            x=[h.x_m for h in in_row], y=[h.y_m for h in in_row], mode="lines+markers",
            name=f"row {row}", line={"color": palette.PRIMARY, "width": 1},
            marker={"symbol": "triangle-down", "size": 8, "color": palette.PRIMARY},
            hoverinfo="text", text=[f"head · x {h.x_m:.1f} m · y {h.y_m:+.2f} m" for h in in_row]))
    return traces


def ventilation_arrow(x_range: tuple[float, float], geom: SectionGeometry,
                      velocity_range_ms: tuple[float, float]) -> go.Scatter:
    """Longitudinal ventilation pushes toward the downstream portal by definition --
    that is what "downstream" means in this convention -- so the direction is not a
    guess even though no field states it explicitly."""
    y = geom.road_width_m / 2.0 + 2.0
    x0, x1 = x_range[0] + MARGIN_M, x_range[1] - MARGIN_M
    lo, hi = velocity_range_ms
    # The label sits at the midpoint, not the endpoint -- an endpoint anchor runs the
    # text straight off the plot's right edge for anything longer than a few words.
    return go.Scatter(x=[x0, (x0 + x1) / 2, x1], y=[y, y, y], mode="lines+markers+text",
                      showlegend=False, line={"color": palette.GREY, "width": 1.5},
                      marker={"symbol": ["circle", "circle", "triangle-right"],
                              "size": [1, 1, 10], "color": palette.GREY},
                      text=["", f"ventilation, {lo:.1f}–{hi:.1f} m/s toward downstream", ""],
                      textposition="top center", textfont={"size": 10, "color": palette.GREY},
                      hoverinfo="skip")


def figure(design: Design, geom: SectionGeometry) -> go.Figure:
    heads = nozzle_positions(design, geom, fire_x_m=0.0)
    x_min = min([h.x_m for h in heads] + [-design.fire.footprint.length_m / 2]) - MARGIN_M
    x_max = max([h.x_m for h in heads] +
               [design.fire.target_x_m + design.fire.footprint.width_m]) + MARGIN_M
    x_range = (x_min, x_max)

    fig = go.Figure(data=[*nozzle_line(design, geom), ventilation_arrow(x_range, geom,
                                                                        design.ventilation.velocity_range_ms)])
    half = geom.road_width_m / 2.0
    fig.update_layout(
        # 60 px clears the y-axis title and its tick labels; at 10 they overlap.
        height=300, margin={"l": 60, "r": 10, "t": 30, "b": 10},
        shapes=[tunnel_outline(design, geom, x_range), *fire_and_target(design, geom)],
        xaxis={"title": "distance from mock-up centre (m)", "range": list(x_range)},
        yaxis={"title": "across the tunnel (m)", "range": [-half - 4.0, half + 4.0],
              "scaleanchor": "x", "scaleratio": 1},
        legend={"orientation": "h", "y": -0.3},
        title={"text": "System layout (plan view)", "x": 0.02, "xanchor": "left",
              "font": {"size": 13}})
    return fig

"""A transverse slice of the tunnel at one instrument station: width x height,
in the style of Annex 7's own cross-sectional figures. The longitudinal twin
(`twin_canvas.py`) looks along the tunnel; this looks across it, at one
station, for one instant.

The reduced-order engine resolves gas temperature only as a vertical rake at
each station's centreline -- `StationSample.heights_m` / `temps_c` carry no
lateral position -- so thermocouples are drawn on the centreline here,
honestly, rather than spread across both walls the way a photographed rig
would show them. The tunnel outline and the nozzle rows ARE real lateral
data (`width_at`, `row_lateral_offsets_m`), so those are drawn to scale.

Annex 7 section 5.2.3 sites the fuel load eccentrically, offset toward one
side wall -- deliberately, so the fire-fighting medium is not delivered
evenly on both sides by a centred position. This view does not draw the
load's own cross-section: nothing in this schema records which wall it is
offset toward, and guessing a side would misrepresent the standard rather
than merely omit part of it.
"""
from __future__ import annotations

import plotly.graph_objects as go

from app import palette
from solit2.engines.reduced.criteria import INSTRUMENTS
from solit2.engines.reduced.geometry import SectionGeometry
from solit2.engines.reduced.state import StepRecord
from solit2.schema.design import Design

TEMP_SCALE = "Inferno"
TEMP_MIN_C = 20.0
BREATHING_HEIGHT_M = 1.8
OUTLINE_SAMPLES = 40
MARGIN_M = 0.6


def tunnel_outline(geom: SectionGeometry) -> go.Scatter:
    """The clear-air boundary, sampled from the same `width_at(height)` the
    engine's own hydraulic-diameter calculation uses -- a box or an arch,
    whichever the design actually is, never a decorative curve."""
    heights = [geom.crown_height_m * i / OUTLINE_SAMPLES for i in range(OUTLINE_SAMPLES + 1)]
    right = [(geom.width_at(z) / 2.0, z) for z in heights]
    left = [(-x, z) for x, z in reversed(right)]
    xs, zs = zip(*(right + left + [right[0]]))
    return go.Scatter(x=list(xs), y=list(zs), mode="lines", fill="toself",
                      line={"color": palette.GREY, "width": 2},
                      fillcolor=palette.rgba(palette.GREY, 0.06),
                      showlegend=False, hoverinfo="skip", name="tunnel")


def thermocouple_rake(name: str, step: StepRecord, cmax_c: float) -> go.Scatter:
    sample = step.stations[name]
    return go.Scatter(x=[0.0] * len(sample.heights_m), y=list(sample.heights_m), mode="markers",
                      name="thermocouples", hoverinfo="text",
                      text=[f"{z:.1f} m · {t:.0f} °C"
                            for z, t in zip(sample.heights_m, sample.temps_c)],
                      marker={"size": 12, "color": list(sample.temps_c), "colorscale": TEMP_SCALE,
                              "cmin": TEMP_MIN_C, "cmax": cmax_c,
                              "colorbar": {"title": {"text": "gas<br>°C", "side": "top"},
                                           "x": 1.02, "len": 0.8, "thickness": 14}})


def gas_marker(name: str, step: StepRecord) -> go.Scatter | None:
    """The flux/visibility/CO instrument cluster, where Table 5 puts one --
    breathing height, centreline, same placement as the longitudinal view.
    `None` where this station carries none of those instruments."""
    kit = INSTRUMENTS[name]
    sample = step.stations[name]
    readings = []
    if kit.heat_flux and sample.flux_kwm2 is not None:
        readings.append(f"{sample.flux_kwm2:.1f} kW/m²")
    if kit.visibility and sample.visibility_m is not None:
        readings.append(f"visibility {sample.visibility_m:.0f} m")
    if kit.carbon_monoxide > 0 and sample.co_ppm is not None:
        readings.append(f"CO {sample.co_ppm:.0f} ppm")
    if not readings:
        return None
    return go.Scatter(x=[0.0], y=[BREATHING_HEIGHT_M], mode="markers",
                      name="gas · flux · visibility", hoverinfo="text",
                      text=[f"{name} · " + " · ".join(readings)],
                      marker={"symbol": "diamond", "size": 13, "color": palette.PRIMARY,
                              "line": {"color": "#1C2432", "width": 1}})


def nozzle_rows(design: Design, step: StepRecord) -> go.Scatter:
    mount = design.nozzles.mounting
    discharging = step.water_lpm > 0
    colour = palette.PRIMARY if discharging else palette.GREY
    ys = list(mount.row_lateral_offsets_m)
    return go.Scatter(x=ys, y=[mount.height_above_carriageway_m] * len(ys), mode="markers",
                      name="nozzle rows",
                      marker={"symbol": "triangle-down", "size": 12, "color": colour},
                      hoverinfo="text",
                      text=[f"row at y {y:+.2f} m" + (" · discharging" if discharging else "")
                            for y in ys])


def figure(design: Design, geom: SectionGeometry, step: StepRecord, station: str,
          cmax_c: float) -> go.Figure:
    """A static cross-section at `station`, for the one instant `step` describes."""
    traces = [tunnel_outline(geom), nozzle_rows(design, step),
             thermocouple_rake(station, step, cmax_c)]
    gas = gas_marker(station, step)
    if gas is not None:
        traces.append(gas)
    half_width = geom.road_width_m / 2.0 + MARGIN_M
    fig = go.Figure(data=traces)
    fig.update_layout(
        height=420, margin={"l": 10, "r": 10, "t": 30, "b": 10},
        xaxis={"title": "across the tunnel (m)", "range": [-half_width, half_width],
              "scaleanchor": "y", "scaleratio": 1, "zeroline": False},
        yaxis={"title": "height (m)", "range": [-0.3, geom.crown_height_m + 0.6]},
        legend={"orientation": "h", "y": -0.15},
        title={"text": f"Cross-section at {station}", "x": 0.02, "xanchor": "left",
              "font": {"size": 13}})
    return fig

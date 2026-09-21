"""A transverse slice of the tunnel at one instrument station: width x height,
in the style of Annex 7's own cross-sectional figures. The longitudinal twin
(`twin_canvas.py`) looks along the tunnel; this looks across it, at one
station, for one instant.

Thermocouples are drawn where Annex 7 Figure 16 puts them -- two on each side
wall bracketing the load, one at the ceiling, two on the load -- at the exact
positions the FDS deck measures at, because both read the same
`deck.figure_16_positions` rather than each deriving its own.

Their COLOURS are a vertical profile. The reduced-order engine resolves gas
temperature as a rake against height and carries no lateral position at all
(`StationSample.heights_m` / `temps_c`), so two sensors at the same height on
opposite walls can only be shown the same temperature. The positions are the
standard's and the temperatures are Tier 1's, and the caption in
`app/views/fire_test.py` says so on screen rather than only here.

Annex 7 section 5.2.3 sites the fuel load eccentrically, offset toward one
side wall -- deliberately, so the fire-fighting medium is not delivered
evenly on both sides by a centred position. Where the station's plane cuts
the mock-up (U05 to D05) or the target, its section is drawn at
`fire_lateral_m`: the lateral position the Tier 1 mist envelope and the FDS
deck both use, so the picture shows the experiment the engines run.
"""
from __future__ import annotations

import plotly.graph_objects as go

from app import palette
from solit2.engines.reduced.criteria import HEAT_FLUX_HEIGHT_M, INSTRUMENTS, STATIONS
from solit2.engines.fds import deck as fds_deck
from solit2.engines.reduced.geometry import SectionGeometry, fire_lateral_m
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


def temperature_at(sample, z_m: float) -> float:
    """The station's gas temperature at a height, from its vertical rake.

    Tier 1 resolves height and nothing else, so this is the only answer it can
    give a sensor wherever that sensor sits laterally.
    """
    heights, temps = list(sample.heights_m), list(sample.temps_c)
    if z_m <= heights[0]:
        return temps[0]
    if z_m >= heights[-1]:
        return temps[-1]
    for lo, hi, t_lo, t_hi in zip(heights, heights[1:], temps, temps[1:]):
        if lo <= z_m <= hi:
            return t_lo + (t_hi - t_lo) * ((z_m - lo) / (hi - lo) if hi > lo else 0.0)
    return temps[-1]


def thermocouple_rake(design: Design, geom: SectionGeometry, name: str,
                      step: StepRecord, cmax_c: float) -> go.Scatter:
    """The station's thermocouples at Annex 7 Figure 16's own positions.

    The positions come from `deck.figure_16_positions`, the same call the FDS
    deck places its devices with, so the drawing and the measurement cannot
    drift apart. Where Figure 16 gives no layout -- a far-field section with
    two or three thermocouples -- the engine's vertical ladder is drawn
    instead, on the centreline, which is where those sensors are measured.
    """
    sample = step.stations[name]
    fuel = fds_deck.fuel_box(design, geom)
    solids = (fuel, fds_deck.target_box(design, geom))
    placed = fds_deck.figure_16_positions(INSTRUMENTS[name], STATIONS[name], geom,
                                          fds_deck.DX_M, fuel, solids)
    if placed:
        labels = [f"{fds_deck.annex7_id('thermocouple', name, p)} · "
                  f"y {y:+.2f} m · {z:.2f} m · {temperature_at(sample, z):.0f} °C"
                  for p, y, z in placed]
        ys = [y for _, y, _ in placed]
        zs = [z for _, _, z in placed]
    else:
        labels = [f"{name} · {z:.1f} m · {t:.0f} °C"
                  for z, t in zip(sample.heights_m, sample.temps_c)]
        ys = [0.0] * len(sample.heights_m)
        zs = list(sample.heights_m)
    return go.Scatter(x=ys, y=zs, mode="markers", name="thermocouples", hoverinfo="text",
                      text=labels,
                      marker={"size": 12, "color": [temperature_at(sample, z) for z in zs],
                              "colorscale": TEMP_SCALE,
                              "cmin": TEMP_MIN_C, "cmax": cmax_c,
                              "line": {"color": "#1C2432", "width": 1},
                              "colorbar": {"title": {"text": "gas<br>°C", "side": "top"},
                                           "x": 1.02, "len": 0.8, "thickness": 14}})


def gas_markers(name: str, step: StepRecord) -> list[go.Scatter]:
    """The instrument clusters where Table 5 puts them, at the heights it puts
    them: heat flux and visibility at 1.5 m (Annex 7 6.4.2, 6.4.5), CO and the
    toxic dose at breathing height -- the same heights the FDS deck measures.
    Empty where this station carries none of those instruments."""
    kit = INSTRUMENTS[name]
    sample = step.stations[name]
    flux = []
    if kit.heat_flux and sample.flux_kwm2 is not None:
        flux.append(f"{sample.flux_kwm2:.1f} kW/m²")
    if kit.visibility and sample.visibility_m is not None:
        flux.append(f"visibility {sample.visibility_m:.0f} m")
    gas = []
    if kit.carbon_monoxide > 0 and sample.co_ppm is not None:
        gas.append(f"CO {sample.co_ppm:.0f} ppm")
    if kit.toxic_gas and sample.fed_tox is not None:
        gas.append(f"FED {sample.fed_tox:.2f}")
    out = []
    if flux:
        out.append(go.Scatter(x=[0.0], y=[HEAT_FLUX_HEIGHT_M], mode="markers",
                              name="flux · visibility (1.5 m)", hoverinfo="text",
                              text=[f"{name} · " + " · ".join(flux)],
                              marker={"symbol": "diamond", "size": 13, "color": palette.PRIMARY,
                                      "line": {"color": "#1C2432", "width": 1}}))
    if gas:
        out.append(go.Scatter(x=[0.0], y=[BREATHING_HEIGHT_M], mode="markers",
                              name="CO · FED (1.8 m)", hoverinfo="text",
                              text=[f"{name} · " + " · ".join(gas)],
                              marker={"symbol": "square", "size": 11, "color": palette.PRIMARY,
                                      "line": {"color": "#1C2432", "width": 1}}))
    return out


def fuel_section(design: Design, geom: SectionGeometry, station: str) -> dict | None:
    """The mock-up's or the target's cross-section, where this station's plane
    cuts one; `None` where it cuts neither. Same footprint, same lateral position
    as the plan view and the FDS deck."""
    x = STATIONS[station]
    fp = design.fire.footprint
    tx = design.fire.target_x_m
    if -fp.length_m / 2 <= x <= fp.length_m / 2:
        colour, name = palette.GREY, "fuel load"
    elif tx <= x <= tx + fp.width_m:
        colour, name = palette.FAIL, "target"
    else:
        return None
    y = fire_lateral_m(design, geom)
    return {"type": "rect", "x0": y - fp.width_m / 2, "x1": y + fp.width_m / 2,
            "y0": fp.base_height_m, "y1": fp.top_height_m, "layer": "below", "name": name,
            "line": {"color": colour, "dash": "dot" if name == "target" else "solid"},
            "fillcolor": palette.rgba(colour, 0.25)}


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
             thermocouple_rake(design, geom, station, step, cmax_c),
             *gas_markers(station, step)]
    half_width = geom.road_width_m / 2.0 + MARGIN_M
    section = fuel_section(design, geom, station)
    fig = go.Figure(data=traces)
    fig.update_layout(
        shapes=[section] if section else [],
        # The left margin has to clear the y-axis title AND its tick labels:
        # at 10 px the title "height (m)" was drawn through the tick numbers.
        height=420, margin={"l": 60, "r": 10, "t": 30, "b": 10},
        xaxis={"title": "across the tunnel (m)", "range": [-half_width, half_width],
              "scaleanchor": "y", "scaleratio": 1, "zeroline": False},
        yaxis={"title": "height (m)", "range": [-0.3, geom.crown_height_m + 0.6]},
        legend={"orientation": "h", "y": -0.15},
        title={"text": f"Cross-section at {station}", "x": 0.02, "xanchor": "left",
              "font": {"size": 13}})
    return fig

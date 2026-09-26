"""The simulator's 3D tunnel: geometry from the design, state from one Tier 1 step.

Pure builders -- Plotly traces only, no Streamlit -- so every element can be
asserted on without a browser. x = 0 is the mock-up's longitudinal middle
(Annex 7 section 6.3), y = 0 the tunnel centreline, z the height above the
carriageway: the frame the engine, `STATIONS` and the FDS deck share.

Two elements are schematic and say so in their names: the smoke plane's height
(the engine computes no layer depth) and the spray volume (the engine models the
mist's effect, not its shape). The smoke's COLOUR is the engine's own gas
temperature at the stations, interpolated between them. Everything else is the
design's geometry or the engine's output.
"""
from __future__ import annotations

import numpy as np
import plotly.graph_objects as go

from app import palette
from app.components import cross_section, twin_canvas
from solit2.engines.reduced.criteria import STATIONS
from solit2.engines.reduced.geometry import SectionGeometry, fire_lateral_m, nozzle_positions
from solit2.engines.reduced.state import StationSample, StepRecord
from solit2.schema.design import Design

RING_SPACING_M = 20.0         # a wireframe cross-section ring every 20 m
EDGE_EVERY = 6                # a longitudinal edge through every 6th outline point
SMOKE_DEPTH_FRACTION = 0.1    # schematic: the smoke plane sits 10 % of the crown height below it
SMOKE_SAMPLE_M = 5.0          # the smoke colour is sampled every 5 m along the tunnel
SMOKE_OPACITY = 0.75
SPRAY_OPACITY = 0.12
SPRAY_SPREAD_M = 1.0          # schematic: the spray volume reaches 1 m beyond the outer rows
ROAD_OPACITY = 0.25
FIRE_LOAD_OPACITY = 0.6
TARGET_MIN_OPACITY, TARGET_MAX_OPACITY = 0.25, 0.85
AIR_ARROW_M = 3.0             # the airflow cone's length; its label carries the speed
POST_STATIONS = ("U45", "U15", "D15", "D45", "D100")
# Every station with a thermocouple tree along the tunnel. "Target" is the target's
# own thermocouples, not a cross-section, so it does not colour the smoke.
SMOKE_STATIONS = tuple(n for n in sorted(STATIONS, key=STATIONS.get) if n != "Target")

# A box's 8 corners: 0-3 the bottom face, 4-7 the top, each counter-clockwise.
# Two triangles per face, 12 in all.
_BOX_I = [0, 0, 4, 4, 0, 0, 3, 3, 0, 0, 1, 1]
_BOX_J = [1, 2, 5, 6, 1, 5, 2, 6, 3, 7, 2, 6]
_BOX_K = [2, 3, 6, 7, 5, 4, 6, 7, 7, 4, 6, 5]


def box(x: tuple[float, float], y: tuple[float, float], z: tuple[float, float], *,
        name: str, colour: str, opacity: float) -> go.Mesh3d:
    (x0, x1), (y0, y1), (z0, z1) = x, y, z
    return go.Mesh3d(x=[x0, x1, x1, x0, x0, x1, x1, x0],
                     y=[y0, y0, y1, y1, y0, y0, y1, y1],
                     z=[z0, z0, z0, z0, z1, z1, z1, z1],
                     i=_BOX_I, j=_BOX_J, k=_BOX_K, color=colour, opacity=opacity,
                     name=name, showlegend=True, hoverinfo="name", flatshading=True)


def _shell(geom: SectionGeometry, window_m: tuple[float, float]) -> go.Scatter3d:
    """Wireframe rings every RING_SPACING_M and a few longitudinal edges, from the
    same outline `cross_section.tunnel_outline` samples off `width_at(height)`."""
    outline = cross_section.tunnel_outline(geom)
    ys, zs = list(outline.x), list(outline.y)
    x0, x1 = window_m
    first = np.ceil(x0 / RING_SPACING_M) * RING_SPACING_M
    xs_all: list[float | None] = []
    ys_all: list[float | None] = []
    zs_all: list[float | None] = []
    for x in np.arange(first, x1 + 1e-9, RING_SPACING_M):
        xs_all += [float(x)] * len(ys) + [None]
        ys_all += ys + [None]
        zs_all += zs + [None]
    for idx in range(0, len(ys), EDGE_EVERY):
        xs_all += [x0, x1, None]
        ys_all += [ys[idx], ys[idx], None]
        zs_all += [zs[idx], zs[idx], None]
    return go.Scatter3d(x=xs_all, y=ys_all, z=zs_all, mode="lines", name="tunnel",
                        line={"color": palette.GREY, "width": 2}, hoverinfo="skip")


def _stations(window_m: tuple[float, float]) -> go.Scatter3d:
    names = [n for n in POST_STATIONS if window_m[0] <= STATIONS[n] <= window_m[1]]
    return go.Scatter3d(x=[STATIONS[n] for n in names], y=[0.0] * len(names),
                        z=[twin_canvas.BREATHING_HEIGHT_M] * len(names),
                        mode="markers+text", text=names, textposition="top center",
                        name="stations (breathing height)", hoverinfo="text",
                        marker={"size": 3, "color": palette.GREY, "symbol": "diamond"})


def static_traces(design: Design, geom: SectionGeometry,
                  window_m: tuple[float, float]) -> list:
    """Everything that does not change during the test."""
    x0, x1 = window_m
    half = geom.road_width_m / 2.0
    fp = design.fire.footprint
    y = fire_lateral_m(design, geom)
    return [
        _shell(geom, window_m),
        box((x0, x1), (-half, half), (0.0, 0.02), name="carriageway",
            colour=palette.GREY, opacity=ROAD_OPACITY),
        box((-fp.length_m / 2, fp.length_m / 2), (y - fp.width_m / 2, y + fp.width_m / 2),
            (fp.base_height_m, fp.top_height_m), name="fire load",
            colour=palette.GREY, opacity=FIRE_LOAD_OPACITY),
        _stations(window_m),
    ]


def _flame(design: Design, geom: SectionGeometry, step: StepRecord,
           hrr_peak_mw: float) -> go.Scatter3d:
    share = min(max(step.hrr_mw / hrr_peak_mw, 0.0), 1.0) if hrr_peak_mw > 0 else 0.0
    size = (twin_canvas.FIRE_MARKER_MIN_PX
            + (twin_canvas.FIRE_MARKER_MAX_PX - twin_canvas.FIRE_MARKER_MIN_PX) * share)
    return go.Scatter3d(x=[0.0], y=[fire_lateral_m(design, geom)],
                        z=[design.fire.footprint.top_height_m], mode="markers",
                        name="flame (size follows heat release)", hoverinfo="text",
                        hovertext=[f"{step.hrr_mw:.1f} MW"],
                        marker={"size": size, "color": palette.FLAME, "opacity": 0.85})


def _target(design: Design, geom: SectionGeometry, step: StepRecord) -> go.Mesh3d:
    """Annex 7 section 5.2.6 gives the target's width and height, not its length along
    the tunnel; like the 2D twin, its length is taken as its width."""
    fp = design.fire.footprint
    y = fire_lateral_m(design, geom)
    progress = twin_canvas.target_ignition_progress(step)
    x0 = design.fire.target_x_m
    return box((x0, x0 + fp.width_m), (y - fp.width_m / 2, y + fp.width_m / 2),
               (fp.base_height_m, fp.top_height_m), name="target (ignition progress)",
               colour=palette.FAIL if progress > 0 else palette.GREY,
               opacity=TARGET_MIN_OPACITY + (TARGET_MAX_OPACITY - TARGET_MIN_OPACITY) * progress)


def _heads(design: Design, geom: SectionGeometry, step: StepRecord) -> go.Scatter3d:
    heads = nozzle_positions(design, geom, fire_x_m=0.0)
    colour = palette.PRIMARY if step.water_lpm > 0.0 else palette.GREY
    return go.Scatter3d(x=[h.x_m for h in heads], y=[h.y_m for h in heads],
                        z=[h.z_m for h in heads], mode="markers",
                        name="nozzle heads (active length)", hoverinfo="skip",
                        marker={"size": 3, "color": colour})


def _spray(design: Design, geom: SectionGeometry, step: StepRecord) -> go.Mesh3d:
    mount = design.nozzles.mounting
    half_length = design.active_length_m / 2.0
    half_road = geom.road_width_m / 2.0
    y0 = max(min(mount.row_lateral_offsets_m) - SPRAY_SPREAD_M, -half_road)
    y1 = min(max(mount.row_lateral_offsets_m) + SPRAY_SPREAD_M, half_road)
    return box((-half_length, half_length), (y0, y1), (0.0, mount.height_above_carriageway_m),
               name="spray (schematic volume)", colour=palette.PRIMARY,
               opacity=SPRAY_OPACITY if step.water_lpm > 0.0 else 0.0)


def _top_rung(sample: StationSample) -> float:
    """The thermocouple nearest the ceiling (`temps_c` runs floor upwards)."""
    return sample.temps_c[-1] if sample.temps_c else sample.temp_c


def smoke_profile(step: StepRecord, xs: np.ndarray) -> np.ndarray:
    """Gas temperature under the ceiling along the tunnel: each station's top
    thermocouple, linearly interpolated between stations and held flat beyond
    the end ones."""
    station_x = np.array([STATIONS[n] for n in SMOKE_STATIONS])
    station_t = np.array([_top_rung(step.stations[n]) for n in SMOKE_STATIONS])
    return np.interp(xs, station_x, station_t)


def _smoke(geom: SectionGeometry, step: StepRecord, window_m: tuple[float, float],
           cmax_c: float) -> go.Surface:
    x0, x1 = window_m
    start = -step.backlayer_m if step.backlayer_m >= twin_canvas.BACKLAYER_MIN_M else 0.0
    start = max(start, x0)
    xs = np.arange(start, x1 + 1e-9, SMOKE_SAMPLE_M)
    if len(xs) < 2:
        xs = np.array([start, x1])
    temps = smoke_profile(step, xs)
    z = geom.crown_height_m * (1.0 - SMOKE_DEPTH_FRACTION)
    half = geom.width_at(z) / 2.0
    return go.Surface(x=xs, y=np.array([-half, half]), z=np.full((2, len(xs)), z),
                      surfacecolor=np.vstack([temps, temps]),
                      cmin=twin_canvas.TEMP_MIN_C, cmax=cmax_c,
                      colorscale=twin_canvas.TEMP_SCALE, opacity=SMOKE_OPACITY,
                      showscale=True, colorbar={"title": {"text": "gas °C"}, "len": 0.45},
                      name="smoke (engine temperature; height schematic)", hoverinfo="skip")


def _airflow(geom: SectionGeometry, step: StepRecord,
             window_m: tuple[float, float]) -> go.Cone:
    return go.Cone(x=[window_m[0] + AIR_ARROW_M], y=[0.0], z=[geom.crown_height_m / 2.0],
                   u=[1.0], v=[0.0], w=[0.0], sizemode="absolute", sizeref=AIR_ARROW_M,
                   anchor="tail", showscale=False,
                   colorscale=[[0.0, palette.PRIMARY], [1.0, palette.PRIMARY]],
                   name=f"air {step.u_eff_ms:.2f} m/s", hoverinfo="text",
                   hovertext=[f"air {step.u_eff_ms:.2f} m/s"])


def dynamic_traces(design: Design, geom: SectionGeometry, step: StepRecord,
                   window_m: tuple[float, float], *, hrr_peak_mw: float,
                   cmax_c: float) -> list:
    """The six traces that change from instant to instant, always in this order:
    flame, target, heads, spray, smoke, airflow. `live_figure` indexes frames by it."""
    return [_flame(design, geom, step, hrr_peak_mw), _target(design, geom, step),
            _heads(design, geom, step), _spray(design, geom, step),
            _smoke(geom, step, window_m, cmax_c), _airflow(geom, step, window_m)]


# Across the tunnel the picture is enlarged for legibility: a 150 m window drawn to
# true scale would leave a 10 m bore as a sliver. The screen's caption says so.
ASPECT = {"x": 3.0, "y": 1.0, "z": 0.7}


def scene_layout(geom: SectionGeometry, window_m: tuple[float, float]) -> dict:
    """Fixed axis ranges, so the scene never rescales between frames."""
    half = geom.road_width_m / 2.0 + 0.5
    return {"xaxis": {"title": {"text": "along the tunnel (m)"}, "range": list(window_m)},
            "yaxis": {"title": {"text": "across (m)"}, "range": [-half, half]},
            "zaxis": {"title": {"text": "height (m)"},
                      "range": [0.0, geom.crown_height_m + 0.5]},
            "aspectmode": "manual", "aspectratio": ASPECT,
            "camera": {"eye": {"x": -1.4, "y": -1.8, "z": 0.9}}}

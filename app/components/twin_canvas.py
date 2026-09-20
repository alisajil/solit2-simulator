"""Pure builders for the fire-test twin: a to-scale longitudinal section of the
tunnel with the mock-up, target, heads, Annex 7 station masts, fire and mist,
drawn for one instant of a Tier 1 `RunTrace`. Each layer returns Plotly traces
and layout shapes so the picture can be asserted on without a browser; Task 7
composes them into frames and a figure.

x = 0 is the longitudinal middle of the HGV mock-up (Annex 7 §6.3), the frame
the engine, `STATIONS` and the FDS deck share.
"""
from __future__ import annotations

import math
from typing import Any

import plotly.graph_objects as go

from solit2.engines.fds.deck import CORE_M, WINDOW_M
from solit2.engines.fds.slices import Slice
from solit2.engines.reduced.criteria import INSTRUMENTS, STATIONS
from solit2.engines.reduced.geometry import SectionGeometry, nozzle_positions, section_geometry
from solit2.engines.reduced.state import RunTrace, StepRecord
from solit2.schema.design import Design

Layer = tuple[list[Any], list[dict]]

TEMP_SCALE = "Inferno"
TEMP_MIN_C = 20.0
BREATHING_HEIGHT_M = 1.8
TWIN_FRAME_STRIDE_S = 30.0
BACKLAYER_MIN_M = 1.0
FIRE_MARKER_MIN_PX, FIRE_MARKER_MAX_PX = 6.0, 60.0
MIST_COLOUR = "#1D8F8A"
FAIL_COLOUR = "#C4452B"
STRUCTURE_COLOUR = "#8A94A6"
IDLE_HEAD_COLOUR = "#8A94A6"
TRANSPARENT = "rgba(0,0,0,0)"
CORE_WINDOW_M = CORE_M

__all__ = ["Layer", "WINDOW_M", "CORE_WINDOW_M", "TEMP_SCALE", "TEMP_MIN_C", "TWIN_FRAME_STRIDE_S",
           "temp_max_c", "tunnel_layer", "instrument_layer", "fire_layer", "mist_layer",
           "CFD_SCALES", "CFD_MAX_FRAMES", "mmss", "sample_steps", "nearest_step", "cfd_layer",
           "figure"]


def temp_max_c(trace: RunTrace) -> float:
    """Top of the shared temperature scale: the peak ceiling temperature rounded up
    to the next 100 °C, never below 400 °C so a cool run still reads as cool."""
    peak = max(s.ceiling_temp_c for s in trace.steps)
    return max(400.0, math.ceil(peak / 100.0) * 100.0)


def _rect(x0: float, x1: float, z0: float, z1: float, **style: Any) -> dict:
    return {"type": "rect", "x0": x0, "x1": x1, "y0": z0, "y1": z1, "layer": "below", **style}


def _line(x0: float, x1: float, z0: float, z1: float, **style: Any) -> dict:
    return {"type": "line", "x0": x0, "x1": x1, "y0": z0, "y1": z1, "layer": "below", **style}


def tunnel_layer(design: Design, geom: SectionGeometry, window_m: tuple[float, float],
                 step: StepRecord, target_ignited: bool = False) -> Layer:
    x0, x1 = window_m
    crown, fp = geom.crown_height_m, design.fire.footprint
    half_active = design.zones.section_length_m * design.zones.sections_simultaneous / 2.0
    structure = {"color": STRUCTURE_COLOUR}
    shapes = [
        _rect(-fp.length_m / 2, fp.length_m / 2, fp.base_height_m, fp.top_height_m,
              line=structure, fillcolor="rgba(138,148,166,0.35)"),
        _rect(design.fire.target_x_m, design.fire.target_x_m + fp.length_m,
              fp.base_height_m, fp.top_height_m,
              line={"color": FAIL_COLOUR if target_ignited else STRUCTURE_COLOUR, "dash": "dot"},
              fillcolor="rgba(196,69,43,0.5)" if target_ignited else TRANSPARENT),
        _line(x0, x1, 0.0, 0.0, line={**structure, "width": 2}),
        _line(x0, x1, crown, crown, line={**structure, "width": 2}),
        _line(-half_active, half_active, crown - 0.15, crown - 0.15,
              line={**structure, "width": 1, "dash": "dash"}),
    ]
    heads = nozzle_positions(design, geom, fire_x_m=0.0)
    head_colour = MIST_COLOUR if step.water_lpm > 0 else IDLE_HEAD_COLOUR
    vent_ok = step.u_eff_ms >= step.u_critical_ms
    traces = [
        go.Scatter(x=[h.x_m for h in heads], y=[h.z_m for h in heads], mode="markers",
                   name="nozzle heads", marker={"symbol": "triangle-down", "size": 7,
                                                "color": head_colour},
                   hovertemplate="head · x %{x:.1f} m · z %{y:.2f} m<extra></extra>"),
        go.Scatter(x=[design.fire.target_x_m + fp.length_m / 2, -half_active, x1 - 0.05 * (x1 - x0)],
                   y=[fp.top_height_m + 0.4, crown - 0.5, crown + 0.35], mode="text",
                   text=[f"target — {design.fire.target_distance_m:.0f} m",
                         f"{design.detection.type} {design.detection.threshold_c:.0f} °C",
                         f"gradient {design.tunnel.gradient_pct:+.1f} %"],
                   textfont={"size": 10, "color": STRUCTURE_COLOUR}, showlegend=False,
                   hoverinfo="skip", name="labels"),
        go.Scatter(x=[x0 + 0.04 * (x1 - x0)], y=[crown * 0.5], mode="text",
                   text=[f"→ u {step.u_eff_ms:.1f} m/s (critical {step.u_critical_ms:.1f})"],
                   textfont={"size": 11, "color": STRUCTURE_COLOUR if vent_ok else FAIL_COLOUR},
                   showlegend=False, hoverinfo="skip", name="ventilation"),
    ]
    return traces, shapes


def _gas_readings(sample, kit) -> list[str]:
    out = []
    if kit.heat_flux and sample.flux_kwm2 is not None:
        out.append(f"{sample.flux_kwm2:.1f} kW/m²")
    if kit.visibility and sample.visibility_m is not None:
        out.append(f"visibility {sample.visibility_m:.0f} m")
    if kit.carbon_monoxide > 0 and sample.co_ppm is not None:
        out.append(f"CO {sample.co_ppm:.0f} ppm")
    return out


def instrument_layer(design: Design, geom: SectionGeometry, step: StepRecord,
                     window_m: tuple[float, float], cmax_c: float) -> Layer:
    xs, zs, temps, hover = [], [], [], []
    gx, gz, ghover, names_x, names = [], [], [], [], []
    shapes = []
    for name, x in sorted(STATIONS.items(), key=lambda kv: kv[1]):
        if not window_m[0] <= x <= window_m[1]:
            continue
        sample = step.stations[name]
        shapes.append(_line(x, x, 0.0, geom.crown_height_m,
                            line={"color": STRUCTURE_COLOUR, "width": 1}))
        names_x.append(x)
        names.append(name)
        for z, t in zip(sample.heights_m, sample.temps_c):
            xs.append(x)
            zs.append(z)
            temps.append(t)
            hover.append(f"{name} · {z:.1f} m · {t:.0f} °C")
        readings = _gas_readings(sample, INSTRUMENTS[name])
        if readings:
            gx.append(x)
            gz.append(BREATHING_HEIGHT_M)
            ghover.append(f"{name} · " + " · ".join(readings))
    traces = [
        go.Scatter(x=xs, y=zs, mode="markers", name="thermocouples", text=hover, hoverinfo="text",
                   marker={"size": 8, "color": temps, "colorscale": TEMP_SCALE, "cmin": TEMP_MIN_C,
                           "cmax": cmax_c,
                           "colorbar": {"title": {"text": "gas<br>°C", "side": "top"},
                                        "x": 1.02, "len": 0.8, "thickness": 14}}),
        go.Scatter(x=gx, y=gz, mode="markers", name="gas · flux · visibility", text=ghover,
                   hoverinfo="text", marker={"symbol": "diamond", "size": 11, "color": MIST_COLOUR,
                                             "line": {"color": "#1C2432", "width": 1}}),
        go.Scatter(x=names_x, y=[geom.crown_height_m + 0.35] * len(names_x), mode="text",
                   text=names, textfont={"size": 10, "color": STRUCTURE_COLOUR},
                   showlegend=False, hoverinfo="skip", name="stations"),
    ]
    return traces, shapes


def fire_layer(design: Design, geom: SectionGeometry, step: StepRecord, cmax_c: float) -> Layer:
    fp = design.fire.footprint
    frac = min(step.hrr_mw / design.fire.design_hrr_mw, 1.0)
    size = FIRE_MARKER_MIN_PX + (FIRE_MARKER_MAX_PX - FIRE_MARKER_MIN_PX) * frac
    marker = go.Scatter(
        x=[0.0], y=[fp.top_height_m], mode="markers", name="fire", hoverinfo="text",
        text=[f"HRR {step.hrr_mw:.1f} MW (free burn {step.hrr_free_mw:.1f}) · "
              f"ceiling {step.ceiling_temp_c:.0f} °C"],
        marker={"symbol": "triangle-up", "size": size, "color": [step.ceiling_temp_c],
                "colorscale": TEMP_SCALE, "cmin": TEMP_MIN_C, "cmax": cmax_c, "showscale": False,
                "line": {"color": FAIL_COLOUR, "width": 1}})
    shapes = []
    if step.backlayer_m > BACKLAYER_MIN_M:
        shapes.append(_rect(-step.backlayer_m, 0.0, geom.crown_height_m * 2 / 3, geom.crown_height_m,
                            line={"width": 0}, fillcolor="rgba(138,148,166,0.25)"))
    return [marker], shapes


def mist_layer(design: Design, geom: SectionGeometry, step: StepRecord) -> Layer:
    """Always one (possibly empty) trace so frame trace indices stay stable."""
    half = design.zones.section_length_m * design.zones.sections_simultaneous / 2.0
    top = design.nozzles.mounting.height_above_carriageway_m
    if step.water_lpm <= 0:
        return [go.Scatter(x=[], y=[], mode="markers", name="mist", showlegend=False)], []
    alpha = min(max(0.10 + 0.40 * step.mist.chi_cool, 0.10), 0.50)
    hover = go.Scatter(x=[0.0], y=[top / 2], mode="markers", name="mist", showlegend=False,
                       marker={"size": 40, "opacity": 0.0}, hoverinfo="text",
                       text=[f"{step.water_lpm:.0f} L/min · cooling {step.mist.chi_cool:.0%} · "
                             f"radiant transmission {step.mist.tau_mist:.0%}"])
    return [hover], [_rect(-half, half, 0.0, top, line={"width": 0},
                           fillcolor=f"rgba(29,143,138,{alpha:.2f})")]


CFD_SCALES = {"TEMPERATURE": "Inferno", "SOOT DENSITY": "Greys", "MPUV": "Blues"}
CFD_MAX_FRAMES = 120
FRAME_MS = 150


def mmss(t_s: float) -> str:
    minutes, seconds = divmod(int(round(t_s)), 60)
    return f"{minutes:02d}:{seconds:02d}"


def sample_steps(trace: RunTrace, stride_s: float) -> list[StepRecord]:
    """One step per `stride_s`, starting at the trace's first record (t = 1 s: the
    engine steps every second and advances before it records)."""
    out, next_t = [], 0.0
    for step in trace.steps:
        if step.t_s + 1e-9 >= next_t:
            out.append(step)
            next_t += stride_s
    return out


def nearest_step(trace: RunTrace, t_s: float) -> StepRecord:
    return min(trace.steps, key=lambda s: abs(s.t_s - t_s))


def cfd_layer(slice_: Slice, frame_index: int) -> Layer:
    heat = go.Heatmap(
        x=slice_.x_m, y=slice_.z_m, z=slice_.frames[frame_index], name=slice_.quantity,
        colorscale=CFD_SCALES.get(slice_.quantity, "Viridis"),
        zmin=float(slice_.frames.min()), zmax=float(slice_.frames.max()),
        # Translucent so the mock-up, heads and instrument masts stay readable underneath:
        # the CFD field is laid over the twin, not in place of it.
        opacity=0.72, zsmooth="best",
        colorbar={"title": {"text": f"{slice_.quantity}<br>({slice_.unit})", "side": "top"},
                  "x": 1.16, "len": 0.8, "thickness": 14},
        hovertemplate="x %{x:.1f} m · z %{y:.1f} m · %{z:.3g}<extra></extra>")
    return [heat], []


def _instant(design: Design, geom: SectionGeometry, step: StepRecord, cmax_c: float,
             window_m: tuple[float, float], target_ignited: bool) -> Layer:
    """Every Tier 1 layer for one step, traces in a fixed order."""
    traces, shapes = [], []
    for layer in (tunnel_layer(design, geom, window_m, step, target_ignited),
                  instrument_layer(design, geom, step, window_m, cmax_c),
                  fire_layer(design, geom, step, cmax_c),
                  mist_layer(design, geom, step)):
        traces += layer[0]
        shapes += layer[1]
    return traces, shapes


def _cfd_indices(n_frames: int) -> list[int]:
    if n_frames <= CFD_MAX_FRAMES:
        return list(range(n_frames))
    return sorted({round(i * (n_frames - 1) / (CFD_MAX_FRAMES - 1)) for i in range(CFD_MAX_FRAMES)})


def _play_menu() -> dict:
    # Laid out horizontally and above the slider: stacked vertically they overlap it.
    return {"type": "buttons", "direction": "right", "showactive": False,
            "x": 0.0, "y": 1.30, "xanchor": "left", "yanchor": "top", "pad": {"b": 4},
            "buttons": [
                {"label": "▶ Play", "method": "animate",
                 "args": [None, {"frame": {"duration": FRAME_MS, "redraw": True},
                                 "fromcurrent": True, "transition": {"duration": 0}}]},
                {"label": "❚❚ Pause", "method": "animate",
                 "args": [[None], {"frame": {"duration": 0, "redraw": False},
                                   "mode": "immediate"}]}]}


def _slider(names: list[str], active: int) -> dict:
    return {"active": active, "x": 0.0, "len": 1.0, "y": 1.16, "pad": {"t": 0, "b": 0},
            "currentvalue": {"prefix": "t = ", "visible": True},
            "steps": [{"label": n, "method": "animate",
                       "args": [[n], {"frame": {"duration": 0, "redraw": True},
                                      "mode": "immediate"}]} for n in names]}


def figure(design: Design, trace: RunTrace, *, cfd: Slice | None = None, initial_frame: int = 0,
           window_m: tuple[float, float] = WINDOW_M, target_ignited: bool = False,
           stride_s: float = TWIN_FRAME_STRIDE_S) -> go.Figure:
    """The animated twin. Without `cfd` the frames are Tier 1 steps every `stride_s`;
    with it they follow the slice's own time base and each frame pairs a heatmap with
    the Tier 1 step nearest in time, so both tiers sit on one picture."""
    geom, cmax_c = section_geometry(design), temp_max_c(trace)
    if cfd is None:
        steps = sample_steps(trace, stride_s)
        times, cfd_idx = [s.t_s for s in steps], [None] * len(steps)
    else:
        cfd_idx = _cfd_indices(len(cfd.t_s))
        times = [float(cfd.t_s[i]) for i in cfd_idx]
        steps = [nearest_step(trace, t) for t in times]

    def instant(k: int) -> Layer:
        traces, shapes = _instant(design, geom, steps[k], cmax_c, window_m, target_ignited)
        if cfd is not None:
            traces = cfd_layer(cfd, cfd_idx[k])[0] + traces
        return traces, shapes

    k0 = min(max(initial_frame, 0), len(steps) - 1)
    traces0, shapes0 = instant(k0)
    names = [mmss(t) for t in times]
    frames = []
    for k in range(len(steps)):
        traces_k, shapes_k = instant(k)
        frames.append(go.Frame(data=traces_k, traces=list(range(len(traces_k))), name=names[k],
                               layout=go.Layout(shapes=shapes_k)))
    fig = go.Figure(data=traces0, frames=frames)
    fig.update_layout(
        shapes=shapes0, height=560, margin={"l": 10, "r": 10, "t": 110, "b": 10},
        xaxis={"title": "distance from mock-up centre (m)", "range": list(window_m), "zeroline": False},
        yaxis={"title": "height (m)", "range": [-0.3, geom.crown_height_m + 1.0]},
        legend={"orientation": "h", "y": -0.2}, updatemenus=[_play_menu()],
        sliders=[_slider(names, k0)])
    return fig

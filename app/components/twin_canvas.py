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
from solit2.engines.reduced.criteria import INSTRUMENTS, STATIONS
from solit2.engines.reduced.geometry import SectionGeometry, nozzle_positions
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
           "temp_max_c", "tunnel_layer", "instrument_layer", "fire_layer", "mist_layer"]


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
                           "cmax": cmax_c, "colorbar": {"title": "°C", "x": 1.02, "len": 0.8}}),
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

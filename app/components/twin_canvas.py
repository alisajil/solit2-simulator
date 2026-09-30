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

import plotly.colors as pcolors
import plotly.graph_objects as go

from app import palette
from app.components import cross_section
from solit2.engines.fds import deck as fds_deck
from solit2.engines.fds.deck import CEILING_OFFSET_M, CORE_M, WINDOW_M, detector_x_m
from solit2.engines.fds.slices import DIFFERENCE_PREFIX, Slice
from solit2.engines.reduced.criteria import (
    FLAME_CONTACT_FLUX_KWM2, HEAT_FLUX_HEIGHT_M, IGNITION_EXPOSURE_S, INSTRUMENTS, STATIONS,
)
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
FLAME_GLOW_REACH = 1.6              # illustrative flame length, in fuel-heights, at design HRR
FLAME_GLOW_CEILING_MARGIN_M = 0.3
FLAME_GLOW_WIDTH_FRACTION = 0.3     # half-width, as a fraction of the fuel footprint length
FLAME_GLOW_MIN_ALPHA, FLAME_GLOW_MAX_ALPHA = 0.12, 0.38
STEAM_MIN_CHI_COOL = 0.02           # below this, evaporation is too small to draw
STEAM_CEILING_MARGIN_M = 0.2
STEAM_BAND_MIN_ALPHA, STEAM_BAND_MAX_ALPHA = 0.10, 0.45
MIST_COLOUR = palette.PRIMARY
FAIL_COLOUR = palette.FAIL
STRUCTURE_COLOUR = palette.GREY
IDLE_HEAD_COLOUR = palette.GREY
TRANSPARENT = palette.TRANSPARENT
_OFF_BLACK = "#0B0614"          # dark enough to read as the cold end, light enough to keep
_NEAR_BLACK_SUM = 24            # observed: Streamlit rewrites #000004 but leaves #0B0614 alone
CORE_WINDOW_M = CORE_M      # fallback only -- callers zooming to a real design use core_window_m()
CORE_WINDOW_MARGIN_M = 10.0

__all__ = ["Layer", "WINDOW_M", "CORE_WINDOW_M", "core_window_m", "TEMP_SCALE", "TEMP_MIN_C",
           "BREATHING_HEIGHT_M", "BACKLAYER_MIN_M", "FIRE_MARKER_MIN_PX", "FIRE_MARKER_MAX_PX",
           "TWIN_FRAME_STRIDE_S", "temp_max_c", "tunnel_layer", "instrument_layer", "fire_layer",
           "mist_layer", "CFD_SCALES", "CFD_MAX_FRAMES", "mmss", "sample_steps", "nearest_step",
           "cfd_layer", "target_ignition_progress", "play_menu", "time_slider",
           "figure"]


def temp_max_c(trace: RunTrace) -> float:
    """Top of the shared temperature scale: the peak ceiling temperature rounded up
    to the next 100 °C, never below 400 °C so a cool run still reads as cool."""
    peak = max(s.ceiling_temp_c for s in trace.steps)
    return max(400.0, math.ceil(peak / 100.0) * 100.0)


def core_window_m(design: Design) -> tuple[float, float]:
    """The window a "zoom to the fire zone" toggle should actually show.

    `CORE_WINDOW_M` (borrowed from the FDS deck's fixed simulation domain) does not
    move with the design: a user who widens `section_length_m` or raises
    `sections_simultaneous` gets an active zone that no longer fits inside that fixed
    span, so the "zoomed" picture can clip the very heads and mist it exists to show.
    This derives the window from the design's own `active_length_m` and the target's
    position instead, so it always contains what it is meant to zoom to.
    """
    half_active = design.active_length_m / 2.0
    target_far_edge = (design.fire.target_x_m + design.fire.footprint.width_m
                       if design.fire.has_target else design.fire.footprint.length_m / 2.0)
    right = max(half_active, target_far_edge) + CORE_WINDOW_MARGIN_M
    return -half_active - CORE_WINDOW_MARGIN_M, right


def _rect(x0: float, x1: float, z0: float, z1: float, **style: Any) -> dict:
    return {"type": "rect", "x0": x0, "x1": x1, "y0": z0, "y1": z1, "layer": "below", **style}


def _line(x0: float, x1: float, z0: float, z1: float, **style: Any) -> dict:
    return {"type": "line", "x0": x0, "x1": x1, "y0": z0, "y1": z1, "layer": "below", **style}


def target_ignition_progress(step: StepRecord) -> float:
    """How close the wood target sits to Annex 7 section 7.2.1's ignition rule, right now.

    The same two paths `_target_ignited` checks trace-wide -- flame-contact flux, or
    sustained exposure above the piloted-ignition threshold -- read per step instead,
    so the target visibly builds toward ignition rather than flipping once at the end.
    `target_exposure_s` resets whenever the flux drops back (sim.py's own sustained-
    exposure rule), so this can fall as well as rise -- e.g. when mist knocks the flux
    down, which is an honest picture, not a bug.
    """
    return min(max(step.target_flux_kwm2 / FLAME_CONTACT_FLUX_KWM2,
                   step.target_exposure_s / IGNITION_EXPOSURE_S), 1.0)


def tunnel_layer(design: Design, geom: SectionGeometry, window_m: tuple[float, float],
                 step: StepRecord, target_ignited: bool = False) -> Layer:
    x0, x1 = window_m
    crown, fp = geom.crown_height_m, design.fire.footprint
    half_active = design.active_length_m / 2.0
    structure = {"color": STRUCTURE_COLOUR}
    progress = target_ignition_progress(step)
    if target_ignited:
        target_fill = palette.rgba(FAIL_COLOUR, 0.5)
    elif progress > 0:
        target_fill = palette.rgba(FAIL_COLOUR, 0.5 * progress)
    else:
        target_fill = TRANSPARENT
    # Annex 7 5.2.6 gives the target's width, height and combustibility as the
    # mock-up's own -- not its along-tunnel length, and the engine itself never
    # models one either (target_x_m feeds a single-point flux check, nothing wider).
    # Drawing it fp.width_m long -- the one figure the standard actually states for
    # it -- is an honest stand-in; drawing it fp.length_m long, as if it were a
    # second full mock-up, would have been the invented number.
    target_length_m = fp.width_m
    shapes = [
        _rect(-fp.length_m / 2, fp.length_m / 2, fp.base_height_m, fp.top_height_m,
              line=structure, fillcolor=palette.rgba(STRUCTURE_COLOUR, 0.35)),
        *([_rect(design.fire.target_x_m, design.fire.target_x_m + target_length_m,
                 fp.base_height_m, fp.top_height_m,
                 line={"color": FAIL_COLOUR if target_ignited else STRUCTURE_COLOUR,
                       "dash": "dot"},
                 fillcolor=target_fill)] if design.fire.has_target else []),
        _line(x0, x1, 0.0, 0.0, line={**structure, "width": 2}),
        _line(x0, x1, crown, crown, line={**structure, "width": 2}),
        _line(-half_active, half_active, crown - 0.15, crown - 0.15,
              line={**structure, "width": 1, "dash": "dash"}),
    ]
    heads = nozzle_positions(design, geom, fire_x_m=0.0)
    has_target = design.fire.has_target        # Annex 7 5.2.6: Class A only
    target_label_x = [design.fire.target_x_m + target_length_m / 2] if has_target else []
    target_label_y = [fp.top_height_m + 0.4] if has_target else []
    target_label_text = ([f"target — {design.fire.target_distance_m:.0f} m"]
                         if has_target else [])
    head_colour = MIST_COLOUR if step.water_lpm > 0 else IDLE_HEAD_COLOUR
    vent_ok = step.u_eff_ms >= step.u_critical_ms
    traces = [
        go.Scatter(x=[h.x_m for h in heads], y=[h.z_m for h in heads], mode="markers",
                   name="nozzle heads", marker={"symbol": "triangle-down", "size": 7,
                                                "color": head_colour},
                   hovertemplate="head · x %{x:.1f} m · z %{y:.2f} m<extra></extra>"),
        go.Scatter(x=[*target_label_x, -half_active, x1 - 0.05 * (x1 - x0)],
                   y=[*target_label_y, crown - 0.5, crown + 0.35], mode="text",
                   text=[*target_label_text,
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


def _flux_visibility_readings(sample, kit) -> list[str]:
    """The 1.5 m instruments: Annex 7 6.4.2 puts the heat-flux gauges at 1.5 m and
    6.4.5 the opacimeters at 1.5 m -- the same height the FDS deck measures them."""
    out = []
    if kit.heat_flux and sample.flux_kwm2 is not None:
        out.append(f"{sample.flux_kwm2:.1f} kW/m²")
    if kit.visibility and sample.visibility_m is not None:
        out.append(f"visibility {sample.visibility_m:.0f} m")
    return out


def _gas_readings(sample, kit) -> list[str]:
    """The breathing-height instruments: CO and the toxic dose, at 1.8 m in both tiers."""
    out = []
    if kit.carbon_monoxide > 0 and sample.co_ppm is not None:
        out.append(f"CO {sample.co_ppm:.0f} ppm")
    if kit.toxic_gas and sample.fed_tox is not None:
        out.append(f"FED {sample.fed_tox:.2f}")
    return out


def detector_layer(design: Design, geom: SectionGeometry, window_m: tuple[float, float]) -> go.Scatter:
    """The linear-heat sensors the FDS deck trips on: the same x positions
    (`deck.detector_x_m`), just under the crown on the design's own geometry.
    The deck places them under the STAIR-STEPPED ceiling, which sits lower."""
    xs = [x for x in detector_x_m(design) if window_m[0] <= x <= window_m[1]]
    z = geom.crown_height_m - CEILING_OFFSET_M
    return go.Scatter(x=xs, y=[z] * len(xs), mode="markers", name="heat detectors",
                      marker={"symbol": "line-ns", "size": 9, "color": STRUCTURE_COLOUR,
                              "line": {"width": 2, "color": STRUCTURE_COLOUR}},
                      hoverinfo="text",
                      text=[f"heat detector · x {x:.0f} m · {design.detection.threshold_c:.0f} °C"
                            for x in xs])


def _station_heights(design: Design, geom: SectionGeometry, name: str,
                     sample) -> list[tuple[float, list[str]]]:
    """The heights this station is measured at, and what sits at each.

    An elevation cannot show a lateral position, so Annex 7 Figure 16's two
    wall sensors at one height land on one point here and are listed together
    rather than drawn twice. The heights themselves come from
    `deck.figure_16_positions`, the same call that places the CFD devices, so
    the twin, the cross-section and the deck all mark the same sensors.
    """
    fuel = fds_deck.fuel_box(design, geom)
    placed = fds_deck.figure_16_positions(INSTRUMENTS[name], STATIONS[name], geom,
                                          fds_deck.DX_M, fuel,
                                          (fuel, fds_deck.target_box(design, geom)))
    if not placed:
        return [(z, []) for z in sample.heights_m]
    at: dict[float, list[str]] = {}
    for position, _, z in placed:
        at.setdefault(round(z, 3), []).append(f"{position:02d}")
    return sorted((z, names) for z, names in at.items())


def instrument_layer(design: Design, geom: SectionGeometry, step: StepRecord,
                     window_m: tuple[float, float], cmax_c: float) -> Layer:
    xs, zs, temps, hover = [], [], [], []
    fx, fhover, gx, ghover, names_x, names = [], [], [], [], [], []
    shapes = []
    for name, x in sorted(STATIONS.items(), key=lambda kv: kv[1]):
        if not window_m[0] <= x <= window_m[1]:
            continue
        sample = step.stations[name]
        shapes.append(_line(x, x, 0.0, geom.crown_height_m,
                            line={"color": STRUCTURE_COLOUR, "width": 1}))
        names_x.append(x)
        names.append(name)
        for z, positions in _station_heights(design, geom, name, sample):
            t = cross_section.temperature_at(sample, z)
            xs.append(x)
            zs.append(z)
            temps.append(t)
            hover.append(f"{name} · " + (", ".join(positions) + " · " if positions else "")
                         + f"{z:.2f} m · {t:.0f} °C")
        flux = _flux_visibility_readings(sample, INSTRUMENTS[name])
        if flux:
            fx.append(x)
            fhover.append(f"{name} · " + " · ".join(flux))
        gas = _gas_readings(sample, INSTRUMENTS[name])
        if gas:
            gx.append(x)
            ghover.append(f"{name} · " + " · ".join(gas))
    traces = [
        go.Scatter(x=xs, y=zs, mode="markers", name="thermocouples", text=hover, hoverinfo="text",
                   marker={"size": 8, "color": temps, "colorscale": TEMP_SCALE, "cmin": TEMP_MIN_C,
                           "cmax": cmax_c,
                           "colorbar": {"title": {"text": "gas<br>°C", "side": "top"},
                                        "x": 1.02, "len": 0.8, "thickness": 14}}),
        go.Scatter(x=fx, y=[HEAT_FLUX_HEIGHT_M] * len(fx), mode="markers",
                   name="flux · visibility (1.5 m)", text=fhover, hoverinfo="text",
                   marker={"symbol": "diamond", "size": 11, "color": MIST_COLOUR,
                           "line": {"color": "#1C2432", "width": 1}}),
        go.Scatter(x=gx, y=[BREATHING_HEIGHT_M] * len(gx), mode="markers",
                   name="CO · FED (1.8 m)", text=ghover, hoverinfo="text",
                   marker={"symbol": "square", "size": 9, "color": MIST_COLOUR,
                           "line": {"color": "#1C2432", "width": 1}}),
        detector_layer(design, geom, window_m),
        go.Scatter(x=names_x, y=[geom.crown_height_m + 0.35] * len(names_x), mode="text",
                   text=names, textfont={"size": 10, "color": STRUCTURE_COLOUR},
                   showlegend=False, hoverinfo="skip", name="stations"),
    ]
    return traces, shapes


def fire_layer(design: Design, geom: SectionGeometry, step: StepRecord, cmax_c: float) -> Layer:
    """The seat of the fire sits at the fuel bed, not floating above it.

    A fire starts at the base of its fuel load and the flame lengthens upward as HRR
    grows -- the marker and the glow beneath it both anchor at `base_height_m`. The
    glow's height is an illustrative scale from the real HRR fraction, not a computed
    flame-height field: the engine does not model flame geometry, only heat release.
    """
    fp = design.fire.footprint
    frac = min(step.hrr_mw / design.fire.design_hrr_mw, 1.0)
    size = FIRE_MARKER_MIN_PX + (FIRE_MARKER_MAX_PX - FIRE_MARKER_MIN_PX) * frac
    fuel_height = max(fp.top_height_m - fp.base_height_m, 0.5)
    glow_top = min(fp.base_height_m + frac * fuel_height * FLAME_GLOW_REACH,
                   geom.crown_height_m - FLAME_GLOW_CEILING_MARGIN_M)
    marker = go.Scatter(
        x=[0.0], y=[fp.base_height_m], mode="markers", name="fire", hoverinfo="text",
        text=[f"HRR {step.hrr_mw:.1f} MW (free burn {step.hrr_free_mw:.1f}) · "
              f"ceiling {step.ceiling_temp_c:.0f} °C"],
        marker={"symbol": "triangle-up", "size": size, "color": [step.ceiling_temp_c],
                "colorscale": TEMP_SCALE, "cmin": TEMP_MIN_C, "cmax": cmax_c, "showscale": False,
                "line": {"color": FAIL_COLOUR, "width": 1}})
    shapes = [_rect(-fp.length_m * FLAME_GLOW_WIDTH_FRACTION, fp.length_m * FLAME_GLOW_WIDTH_FRACTION,
                    fp.base_height_m, glow_top, line={"width": 0},
                    fillcolor=palette.rgba(FAIL_COLOUR, FLAME_GLOW_MIN_ALPHA + FLAME_GLOW_MAX_ALPHA * frac))]
    if step.backlayer_m > BACKLAYER_MIN_M:
        shapes.append(_rect(-step.backlayer_m, 0.0, geom.crown_height_m * 2 / 3, geom.crown_height_m,
                            line={"width": 0}, fillcolor=palette.rgba(STRUCTURE_COLOUR, 0.25)))
    return [marker], shapes


def mist_layer(design: Design, geom: SectionGeometry, step: StepRecord) -> Layer:
    """Always one (possibly empty) trace so frame trace indices stay stable.

    Two shapes when discharging: the spray zone from floor to the nozzles, and a
    steam band from the nozzles up toward the crown once evaporation is doing
    something worth showing. `chi_downstream` -- the fraction of convective heat
    the engine attributes to evaporation, in the plume and along the zone the
    band is drawn over -- is the only honest signal for "how much of this is
    turning to steam", so it drives the band's presence and depth, not a
    decorative animation. Shapes carry no frame-count invariant (a frame replaces
    the whole shapes list), so adding one here does not touch trace indexing.
    """
    half = design.active_length_m / 2.0
    top = design.nozzles.mounting.height_above_carriageway_m
    if step.water_lpm <= 0:
        return [go.Scatter(x=[], y=[], mode="markers", name="mist", showlegend=False)], []
    chi = step.mist.chi_downstream
    alpha = min(max(0.18 + 0.40 * chi, 0.18), 0.55)
    hover = go.Scatter(x=[0.0], y=[top / 2], mode="markers", name="mist", showlegend=False,
                       marker={"size": 40, "opacity": 0.0}, hoverinfo="text",
                       text=[f"{step.water_lpm:.0f} L/min · cooling {chi:.0%} · "
                             f"radiant transmission {step.mist.tau_mist:.0%}"])
    shapes = [_rect(-half, half, 0.0, top, line={"color": MIST_COLOUR, "width": 1},
                    fillcolor=palette.rgba(MIST_COLOUR, alpha))]
    band_top = geom.crown_height_m - STEAM_CEILING_MARGIN_M
    if chi > STEAM_MIN_CHI_COOL and band_top > top:
        steam_alpha = STEAM_BAND_MIN_ALPHA + (STEAM_BAND_MAX_ALPHA - STEAM_BAND_MIN_ALPHA) * min(chi / 0.6, 1.0)
        shapes.append(_rect(-half, half, top, band_top,
                            line={"width": 0}, fillcolor=palette.rgba(palette.STEAM, steam_alpha)))
    return [hover], shapes


# Keyed by the quantity string FDS writes into the .smv header: a particle field
# carries its PART_ID, so the deck's MPUV of the FINE class arrives as "FINE MPUV".
CFD_SCALES = {"TEMPERATURE": "Inferno", "SOOT DENSITY": "Greys", "FINE MPUV": "Blues"}
# A difference of two fields is signed, so it gets a diverging scale centred on zero.
DIFFERENCE_SCALE = "RdBu_r"
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


def _is_near_black(colour: str) -> bool:
    c = colour.lstrip("#")
    return len(c) == 6 and sum(int(c[i:i + 2], 16) for i in (0, 2, 4)) < _NEAR_BLACK_SUM


def cfd_scale(quantity: str) -> list[list]:
    """The named scale with any near-black stop nudged just off black.

    Streamlit substitutes near-black for an accent colour when it renders a Plotly
    figure in a dark theme. Inferno starts at #000004, so the coldest cells came out
    bright purple and an ambient tunnel read as the hottest thing on screen. Starting
    a shade above black keeps the ramp intact and leaves nothing for it to rewrite.
    """
    if quantity.startswith(DIFFERENCE_PREFIX):
        return pcolors.get_colorscale(DIFFERENCE_SCALE)
    stops = pcolors.get_colorscale(CFD_SCALES.get(quantity, "Viridis"))
    return [[p, _OFF_BLACK if _is_near_black(c) else c] for p, c in stops]


def _cfd_range(slice_: Slice) -> tuple[float, float]:
    """A difference field is centred on zero so its diverging scale reads as a
    sign: cooler-than-free-burn one colour, hotter the other, unchanged white."""
    lo, hi = float(slice_.frames.min()), float(slice_.frames.max())
    if slice_.quantity.startswith(DIFFERENCE_PREFIX):
        span = max(abs(lo), abs(hi))
        return -span, span
    return lo, hi


def cfd_layer(slice_: Slice, frame_index: int) -> Layer:
    zmin, zmax = _cfd_range(slice_)
    heat = go.Heatmap(
        x=slice_.x_m, y=slice_.z_m, z=slice_.frames[frame_index], name=slice_.quantity,
        colorscale=cfd_scale(slice_.quantity),
        zmin=zmin, zmax=zmax,
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


def play_menu(x: float = 0.0, y: float = 1.30) -> dict:
    # Laid out horizontally and above the slider: stacked vertically they overlap it.
    return {"type": "buttons", "direction": "right", "showactive": False,
            "x": x, "y": y, "xanchor": "left", "yanchor": "top", "pad": {"b": 4},
            "buttons": [
                {"label": "▶ Play", "method": "animate",
                 "args": [None, {"frame": {"duration": FRAME_MS, "redraw": True},
                                 "fromcurrent": True, "transition": {"duration": 0}}]},
                {"label": "❚❚ Pause", "method": "animate",
                 "args": [[None], {"frame": {"duration": 0, "redraw": False},
                                   "mode": "immediate"}]}]}


def time_slider(names: list[str], active: int, y: float = 1.16) -> dict:
    return {"active": active, "x": 0.0, "len": 1.0, "y": y, "pad": {"t": 0, "b": 0},
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

    # A negative index counts from the end, so -1 opens on the newest frame.
    # A CFD replay opened at t = 0 shows an empty picture: the difference field
    # is exactly zero everywhere before anything has happened, and the water-mass
    # field has no droplets in it until the system activates. Both are the very
    # things the field selector exists to show.
    k0 = len(steps) + initial_frame if initial_frame < 0 else initial_frame
    k0 = min(max(k0, 0), len(steps) - 1)
    traces0, shapes0 = instant(k0)
    names = [mmss(t) for t in times]
    frames = []
    for k in range(len(steps)):
        traces_k, shapes_k = instant(k)
        frames.append(go.Frame(data=traces_k, traces=list(range(len(traces_k))), name=names[k],
                               layout=go.Layout(shapes=shapes_k)))
    fig = go.Figure(data=traces0, frames=frames)
    fig.update_layout(
        # 60 px clears the y-axis title and its tick labels; at 10 they overlap.
        shapes=shapes0, height=560, margin={"l": 60, "r": 10, "t": 110, "b": 10},
        xaxis={"title": "distance from mock-up centre (m)", "range": list(window_m), "zeroline": False},
        yaxis={"title": "height (m)", "range": [-0.3, geom.crown_height_m + 1.0]},
        legend={"orientation": "h", "y": -0.2}, updatemenus=[play_menu()],
        sliders=[time_slider(names, k0)])
    return fig

"""The Design view: pick a starting preset per block, override the nine
parameters an engineer actually varies, and produce a `Design`.

Presets supply everything else -- this mirrors `solit2/schema/presets.py`'s
own stated philosophy ("a design JSON names a preset per block and
overrides individual fields; the preset supplies everything else"), so a
form that starts from a preset and overrides a handful of fields is not a
shortcut, it is how this schema is meant to be driven.
"""
from __future__ import annotations

import streamlit as st

from app import state
from solit2.engines.reduced.geometry import section_geometry
from solit2.engines.reduced.hydraulics import size_system
from solit2.schema.design import Design
from solit2.schema.presets import list_presets


def _render_summary(raw: dict) -> None:
    """What the inputs above add up to, before anything is built."""
    st.subheader("This system")
    try:
        design = Design.from_dict(raw)
    except Exception as exc:  # noqa: BLE001 -- shown inline, so the user can fix the input
        st.caption(f"Not a valid design yet: {exc}")
        return
    hyd = size_system(design, section_geometry(design))
    per_head_lpm = design.nozzles.k_factor_lpm_bar05 * design.nozzles.pressure_bar ** 0.5
    cols = st.columns(6)
    cols[0].metric("Active heads", f"{hyd.active_heads}")
    cols[1].metric("Per head", f"{per_head_lpm:.1f} L/min")
    cols[2].metric("Zone flow", f"{hyd.flow_lpm:.0f} L/min")
    cols[3].metric("Pump power", f"{hyd.power_kw:.0f} kW")
    cols[4].metric("Tank", f"{hyd.tank_m3:.1f} m³")
    cols[5].metric("Density", f"{hyd.density_mm_min:.2f} mm/min")


def render() -> None:
    st.header("Design")
    st.caption("Pick a starting preset for each block, then set the parameters an engineer "
               "actually varies. Everything else comes from the presets.")
    tunnel_preset, fire_preset, nozzle_preset, hydraulics_preset = _render_preset_pickers()
    k_factor, pressure_bar, rows, pitch_m = _render_nozzle_hydraulics_inputs()
    section_length_m, sections_simultaneous = _render_zoning_inputs()
    velocity_lo, velocity_hi = _render_ventilation_inputs()
    raw = _assemble(tunnel_preset, fire_preset, nozzle_preset, hydraulics_preset,
                    k_factor, pressure_bar, int(rows), pitch_m,
                    section_length_m, int(sections_simultaneous), velocity_lo, velocity_hi)
    _render_summary(raw)
    if st.button("Build & continue →", key="build_design", type="primary"):
        try:
            design = Design.from_dict(raw)
        except Exception as exc:  # noqa: BLE001 -- surfaced to the user, not swallowed
            st.error(f"Could not build a valid design: {exc}")
            return
        state.set_design(design)
        state.set_step(2)
        st.rerun()


def _default_index(options: list[str], name: str) -> int:
    """The index of `name` in `options`, or 0 if it isn't there.

    Falls back rather than raising: the four hardcoded default preset names
    include some that live only in examples/presets/, which
    solit2/schema/presets.py documents as optional -- "the tool must run
    without them." A missing example preset should degrade to the first
    available option, not crash the app's landing page.
    """
    return options.index(name) if name in options else 0


def _render_preset_pickers() -> tuple[str, str, str, str]:
    """The four per-block preset selectors: tunnel, fire, nozzle, hydraulics.

    Each defaults to a verified-compatible combination (`examples/designs/
    road-tunnel-twin-bore-single-mode.json`) rather than position 0 of the
    alphabetically sorted preset list, which can pair an incompatible tunnel
    and nozzle (e.g. a nozzle mounted above the crown) with zero user
    interaction.
    """
    col1, col2, col3 = st.columns(3)
    with col1:
        tunnel_options = list_presets("tunnel")
        tunnel_preset = st.selectbox(
            "Tunnel preset", tunnel_options, index=_default_index(tunnel_options, "twin_bore_11m"),
            key="d_tunnel")
    with col2:
        fire_options = list_presets("fire")
        fire_preset = st.selectbox(
            "Fire preset", fire_options, index=_default_index(fire_options, "hgv_150mw"),
            key="d_fire")
    with col3:
        nozzle_options = list_presets("nozzle")
        nozzle_preset = st.selectbox(
            "Nozzle preset", nozzle_options,
            index=_default_index(nozzle_options, "single_mode_fine_example"), key="d_nozzle")
    hydraulics_options = list_presets("hydraulics")
    hydraulics_preset = st.selectbox(
        "Hydraulics preset", hydraulics_options, index=_default_index(hydraulics_options, "example"),
        key="d_hydraulics")
    return tunnel_preset, fire_preset, nozzle_preset, hydraulics_preset


def _render_nozzle_hydraulics_inputs() -> tuple[float, float, int, float]:
    """K-factor, working pressure, nozzle row count, and pitch."""
    st.subheader("Nozzle & hydraulics")
    c1, c2, c3 = st.columns(3)
    with c1:
        k_factor = st.number_input(
            "K-factor (L/min·bar⁰·⁵)", min_value=0.6, max_value=20.0, value=4.1, step=0.1,
            key="d_k")
    with c2:
        pressure_bar = st.number_input(
            "Working pressure (bar)", min_value=34.5, max_value=140.0, value=50.0, step=0.5,
            key="d_pressure")
    with c3:
        rows = st.number_input("Nozzle rows", min_value=1, max_value=3, value=2, step=1,
                               key="d_rows")
    pitch_m = st.number_input(
        "Nozzle spacing / pitch (m)", min_value=0.1, max_value=10.0, value=2.4, step=0.1,
        key="d_pitch")
    return k_factor, pressure_bar, rows, pitch_m


def _render_zoning_inputs() -> tuple[float, int]:
    """Section length and how many sections activate simultaneously."""
    st.subheader("Zoning")
    z1, z2 = st.columns(2)
    with z1:
        section_length_m = st.number_input(
            "Section length (m)", min_value=8.0, max_value=100.0, value=30.0, step=1.0,
            key="d_section_len")
    with z2:
        sections_simultaneous = st.number_input(
            "Sections activated simultaneously", min_value=1, max_value=6, value=3, step=1,
            key="d_sections")
    return section_length_m, sections_simultaneous


def _render_ventilation_inputs() -> tuple[float, float]:
    """Low and high longitudinal ventilation velocities."""
    st.subheader("Ventilation")
    v1, v2 = st.columns(2)
    with v1:
        velocity_lo = st.number_input(
            "Ventilation velocity, low (m/s)", min_value=0.0, max_value=8.0, value=3.88, step=0.01,
            key="d_v_lo")
    with v2:
        velocity_hi = st.number_input(
            "Ventilation velocity, high (m/s)", min_value=0.0, max_value=8.0, value=5.08, step=0.01,
            key="d_v_hi")
    return velocity_lo, velocity_hi


def _assemble(tunnel_preset: str, fire_preset: str, nozzle_preset: str,
             hydraulics_preset: str, k_factor: float, pressure_bar: float,
             rows: int, pitch_m: float, section_length_m: float,
             sections_simultaneous: int, velocity_lo: float, velocity_hi: float) -> dict:
    """Every override lands inside its own block, on top of the chosen preset."""
    offsets = {1: [0.0], 2: [-2.5, 2.5], 3: [-2.8, 0.0, 2.8]}[rows]
    return {
        "meta": {"name": "streamlit-design", "notes": "Built from the Design view."},
        "tunnel": {"preset": tunnel_preset},
        "fire": {"preset": fire_preset},
        "nozzles": {
            "preset": nozzle_preset,
            "k_factor_lpm_bar05": k_factor,
            "pressure_bar": pressure_bar,
            "mounting": {"rows": rows, "row_lateral_offsets_m": offsets, "pitch_m": pitch_m},
        },
        "zones": {
            "section_length_m": section_length_m,
            "sections_simultaneous": sections_simultaneous,
            "manual_activation_s": 60.0,
            "activation_delay_s": 0.0,
            "pump_ramp_s": 30.0,
            "duration_min": 60.0,
        },
        "ventilation": {
            "mode": "longitudinal",
            "velocity_range_ms": [velocity_lo, velocity_hi],
        },
        "detection": {"type": "linear_heat", "threshold_c": 60.0, "sensor_spacing_m": 25.0},
        "hydraulics": {"preset": hydraulics_preset},
    }

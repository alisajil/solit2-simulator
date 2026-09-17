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
from solit2.schema.design import Design
from solit2.schema.presets import list_presets


def render() -> None:
    st.header("Design")
    st.caption(
        "Pick a starting preset for each block, then override the parameters "
        "below. Every other field comes from the presets you choose."
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        tunnel_preset = st.selectbox("Tunnel preset", list_presets("tunnel"))
    with col2:
        fire_preset = st.selectbox("Fire preset", list_presets("fire"))
    with col3:
        nozzle_preset = st.selectbox("Nozzle preset", list_presets("nozzle"))
    hydraulics_preset = st.selectbox("Hydraulics preset", list_presets("hydraulics"))

    st.subheader("Nozzle & hydraulics")
    c1, c2, c3 = st.columns(3)
    with c1:
        k_factor = st.number_input(
            "K-factor (L/min·bar⁰·⁵)", min_value=0.6, max_value=20.0, value=4.1, step=0.1)
    with c2:
        pressure_bar = st.number_input(
            "Working pressure (bar)", min_value=34.5, max_value=140.0, value=50.0, step=0.5)
    with c3:
        rows = st.number_input("Nozzle rows", min_value=1, max_value=3, value=2, step=1)
    pitch_m = st.number_input(
        "Nozzle spacing / pitch (m)", min_value=0.1, max_value=10.0, value=2.4, step=0.1)

    st.subheader("Zoning")
    z1, z2 = st.columns(2)
    with z1:
        section_length_m = st.number_input(
            "Section length (m)", min_value=8.0, max_value=100.0, value=30.0, step=1.0)
    with z2:
        sections_simultaneous = st.number_input(
            "Sections activated simultaneously", min_value=1, max_value=6, value=3, step=1)

    st.subheader("Ventilation")
    v1, v2 = st.columns(2)
    with v1:
        velocity_lo = st.number_input(
            "Ventilation velocity, low (m/s)", min_value=0.0, max_value=8.0, value=3.88, step=0.01)
    with v2:
        velocity_hi = st.number_input(
            "Ventilation velocity, high (m/s)", min_value=0.0, max_value=8.0, value=5.08, step=0.01)

    if st.button("Build design", type="primary"):
        raw = _assemble(tunnel_preset, fire_preset, nozzle_preset, hydraulics_preset,
                        k_factor, pressure_bar, int(rows), pitch_m,
                        section_length_m, int(sections_simultaneous),
                        velocity_lo, velocity_hi)
        try:
            design = Design.from_dict(raw)
        except Exception as exc:  # noqa: BLE001 -- surfaced to the user, not swallowed
            st.error(f"Could not build a valid design: {exc}")
            return
        state.set_design(design)
        st.success(f"Design built: {design.meta.name}")

    current = state.get_design()
    if current is not None:
        st.subheader("Current design")
        st.json(current.model_dump(mode="json"), expanded=False)
        st.download_button(
            "Download design JSON",
            data=current.model_dump_json(indent=2),
            file_name=f"{current.meta.name}.json",
            mime="application/json",
        )


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

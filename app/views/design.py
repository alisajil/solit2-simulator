"""The Design view: pick a starting preset per block, override the nine
parameters an engineer actually varies, and produce a `Design`.

Presets supply everything else -- this mirrors `solit2/schema/presets.py`'s
own stated philosophy ("a design JSON names a preset per block and
overrides individual fields; the preset supplies everything else"), so a
form that starts from a preset and overrides a handful of fields is not a
shortcut, it is how this schema is meant to be driven.
"""
from __future__ import annotations

import json
from pathlib import Path

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
    ahj = _render_ahj_inputs()
    raw = _assemble(tunnel_preset, fire_preset, nozzle_preset, hydraulics_preset,
                    k_factor, pressure_bar, int(rows), pitch_m,
                    section_length_m, int(sections_simultaneous), velocity_lo, velocity_hi, ahj)
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


AHJ_COLUMNS = 4

AHJ_FIELDS = (
    ("tvs_design_fire_mw", "ahj_tvs", "Ventilation design fire (MW)", 0.0, 500.0, 1.0),
    ("max_air_temp_c", "ahj_air_temp", "Max air temperature (°C)", 0.0, 2000.0, 1.0),
    ("max_heat_flux_kwm2", "ahj_flux", "Max heat flux (kW/m²)", 0.0, 200.0, 0.1),
    ("min_visibility_m", "ahj_visibility", "Min visibility (m)", 0.0, 500.0, 1.0),
    ("max_fed", "ahj_fed", "Max fractional effective dose", 0.0, 1.0, 0.01),
    ("max_co_ppm", "ahj_co", "Max carbon monoxide (ppm)", 0.0, 10000.0, 10.0),
    ("max_structure_exposure_length_m", "ahj_struct_len",
     "Max structure exposed above threshold (m)", 0.0, 2000.0, 1.0),
    ("max_structure_exposure_duration_s", "ahj_struct_dur",
     "Max structure exposure duration (s)", 0.0, 10000.0, 10.0),
)


DESIGNS_DIR = Path("designs")
NO_SOURCE = "— none —"
_APPLIED_SOURCE = "_ahj_applied_source"


def _design_files() -> list[str]:
    """Design files the user keeps in their own project space.

    `designs/` is the user's, and neither independence scan touches it by design —
    so it is where real project limits belong, with their provenance beside them.
    """
    if not DESIGNS_DIR.is_dir():
        return []
    return sorted(p.name for p in DESIGNS_DIR.glob("*.json"))


def _limits_from(name: str) -> tuple[dict, str]:
    """The limits a design file declares, and whatever it says about where they came from."""
    try:
        raw = json.loads((DESIGNS_DIR / name).read_text())
    except (OSError, ValueError) as exc:
        st.warning(f"{name} could not be read: {exc}")
        return {}, ""
    block = raw.get("ahj") or {}
    limits = {field: float(block[field]) for field, *_ in AHJ_FIELDS
              if block.get(field) is not None}
    return limits, str(block.get("note") or "")


def _prefill_from_file() -> dict:
    """Load the limits a design file declares, without inventing the ones it leaves out."""
    names = _design_files()
    if not names:
        return {}
    chosen = st.selectbox("Prefill from a design file", [NO_SOURCE, *names], key="ahj_source",
                          help="Reads the file's own `ahj` block. A limit the file leaves "
                               "null stays empty here — it is not invented.")
    if chosen == NO_SOURCE:
        st.session_state[_APPLIED_SOURCE] = None
        return {}
    limits, note = _limits_from(chosen)
    # Re-seed the fields when the source changes; otherwise the widgets keep the old file's
    # values, since Streamlit only honours `value=` on a key's first render.
    if st.session_state.get(_APPLIED_SOURCE) != chosen:
        for _field, key, *_rest in AHJ_FIELDS:
            st.session_state.pop(key, None)
        st.session_state[_APPLIED_SOURCE] = chosen
    st.caption(f"{len(limits)} of {len(AHJ_FIELDS)} limits come from **{chosen}**; the rest are "
               f"blank because that file declares none. Edit any of them for this run.")
    if note:
        st.caption(f"That file records: {note}")
    return limits


def _render_ahj_inputs() -> dict:
    """The acceptance limits, which belong to the authority and to nobody else.

    Annex 7 section 7.1 gives the categories but not the numbers: "the detailed
    acceptance criteria shall be defined by authorities having jurisdiction based on
    the risk analysis of every individual tunnel". So every field starts empty and an
    empty field stays unset — this tool never supplies a limit nobody set, and a
    criterion with no limit is reported as unjudged rather than as a pass.
    """
    st.subheader("Acceptance limits")
    st.caption("From the project's own authority — the tender, the fire strategy or the "
               "AHJ's risk analysis. Leave a field empty and that criterion is reported "
               "as not judged; it is never treated as passed.")
    prefill = _prefill_from_file()
    values: dict[str, float] = {}
    columns = st.columns(AHJ_COLUMNS)
    for i, (field, key, caption, low, high, step) in enumerate(AHJ_FIELDS):
        entered = columns[i % AHJ_COLUMNS].number_input(
            caption, min_value=low, max_value=high, value=prefill.get(field), step=step,
            key=key, placeholder="not set")
        if entered is not None:
            values[field] = float(entered)
    unset = len(AHJ_FIELDS) - len(values)
    if unset:
        st.caption(f"{unset} of {len(AHJ_FIELDS)} limits still unset.")
    return values


def _assemble(tunnel_preset: str, fire_preset: str, nozzle_preset: str,
             hydraulics_preset: str, k_factor: float, pressure_bar: float,
             rows: int, pitch_m: float, section_length_m: float,
             sections_simultaneous: int, velocity_lo: float, velocity_hi: float,
             ahj: dict) -> dict:
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
        "ahj": ahj,
    }

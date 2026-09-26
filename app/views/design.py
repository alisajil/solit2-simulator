"""The Design view: pick a starting preset per block, override the nine
parameters an engineer actually varies, and produce a `Design`.

Presets supply everything else -- this mirrors `solit2/schema/presets.py`'s
own stated philosophy ("a design JSON names a preset per block and
overrides individual fields; the preset supplies everything else"), so a
form that starts from a preset and overrides a handful of fields is not a
shortcut, it is how this schema is meant to be driven.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import streamlit as st

from app import state
from app.components import overview
from app.components.design_files import design_files
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
    geom = section_geometry(design)
    hyd = size_system(design, geom)
    per_head_lpm = design.nozzles.k_factor_lpm_bar05 * design.nozzles.pressure_bar ** 0.5
    cols = st.columns(6)
    cols[0].metric("Active heads", f"{hyd.active_heads}")
    cols[1].metric("Per head", f"{per_head_lpm:.1f} L/min")
    cols[2].metric("Zone flow", f"{hyd.flow_lpm:.0f} L/min")
    cols[3].metric("Pump power", f"{hyd.power_kw:.0f} kW")
    cols[4].metric("Tank", f"{hyd.tank_m3:.1f} m³")
    cols[5].metric("Density", f"{hyd.density_mm_min:.2f} mm/min")
    st.plotly_chart(overview.figure(design, geom), key="design_overview", theme=None)


def render() -> None:
    st.header("Design")
    st.caption("Pick a starting preset for each block, then set the parameters an engineer "
               "actually varies. Everything else comes from the presets.")
    raw_source = _render_source_picker()
    tunnel_preset, fire_preset, nozzle_preset, hydraulics_preset = _render_preset_pickers(raw_source)
    k_factor, pressure_bar, rows, pitch_m = _render_nozzle_hydraulics_inputs(raw_source)
    section_length_m, sections_simultaneous = _render_zoning_inputs(raw_source)
    velocity_lo, velocity_hi = _render_ventilation_inputs(raw_source)
    ahj = _render_ahj_inputs(raw_source)
    raw = _assemble(tunnel_preset, fire_preset, nozzle_preset, hydraulics_preset,
                    k_factor, pressure_bar, int(rows), pitch_m,
                    section_length_m, int(sections_simultaneous), velocity_lo, velocity_hi,
                    ahj, raw_source)
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


def _render_preset_pickers(raw: dict) -> tuple[str, str, str, str]:
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
            "Tunnel preset", tunnel_options, index=_default_index(tunnel_options, _dig(raw, "tunnel", "preset") or "twin_bore_11m"),
            key="d_tunnel")
    with col2:
        fire_options = list_presets("fire")
        fire_preset = st.selectbox(
            "Fire preset", fire_options, index=_default_index(fire_options, _dig(raw, "fire", "preset") or "hgv_150mw"),
            key="d_fire")
    with col3:
        nozzle_options = list_presets("nozzle")
        nozzle_preset = st.selectbox(
            "Nozzle preset", nozzle_options,
            index=_default_index(nozzle_options, _dig(raw, "nozzle", "preset") or "single_mode_fine_example"), key="d_nozzle")
    hydraulics_options = list_presets("hydraulics")
    hydraulics_preset = st.selectbox(
        "Hydraulics preset", hydraulics_options, index=_default_index(hydraulics_options, _dig(raw, "hydraulics", "preset") or "example"),
        key="d_hydraulics")
    return tunnel_preset, fire_preset, nozzle_preset, hydraulics_preset


def _render_nozzle_hydraulics_inputs(raw: dict) -> tuple[float, float, int, float]:
    """K-factor, working pressure, nozzle row count, and pitch."""
    st.subheader("Nozzle & hydraulics")
    c1, c2, c3 = st.columns(3)
    with c1:
        k_factor = st.number_input(
            "K-factor (L/min·bar⁰·⁵)", min_value=0.6, max_value=20.0, step=0.1,
            value=_seed(raw, ("nozzles", "k_factor_lpm_bar05"), 4.1, 0.6, 20.0),
            key="d_k")
    with c2:
        pressure_bar = st.number_input(
            "Working pressure (bar)", min_value=34.5, max_value=140.0, step=0.5,
            value=_seed(raw, ("nozzles", "pressure_bar"), 50.0, 34.5, 140.0),
            key="d_pressure")
    with c3:
        rows = st.number_input("Nozzle rows", min_value=1, max_value=3, step=1, key="d_rows",
                               value=_seed(raw, ("nozzles", "mounting", "rows"), 2, 1, 3))
    pitch_m = st.number_input(
        "Nozzle spacing / pitch (m)", min_value=0.1, max_value=10.0, step=0.1,
        value=_seed(raw, ("nozzles", "mounting", "pitch_m"), 2.4, 0.1, 10.0),
        key="d_pitch")
    return k_factor, pressure_bar, rows, pitch_m


def _render_zoning_inputs(raw: dict) -> tuple[float, int]:
    """Section length and how many sections activate simultaneously."""
    st.subheader("Zoning")
    z1, z2 = st.columns(2)
    with z1:
        section_length_m = st.number_input(
            "Section length (m)", min_value=8.0, max_value=100.0, step=1.0,
            value=_seed(raw, ("zones", "section_length_m"), 30.0, 8.0, 100.0),
            key="d_section_len")
    with z2:
        sections_simultaneous = st.number_input(
            "Sections activated simultaneously", min_value=1, max_value=6, step=1,
            value=_seed(raw, ("zones", "sections_simultaneous"), 3, 1, 6),
            key="d_sections")
    return section_length_m, sections_simultaneous


def _render_ventilation_inputs(raw: dict) -> tuple[float, float]:
    """Low and high longitudinal ventilation velocities."""
    st.subheader("Ventilation")
    declared = _dig(raw, "ventilation", "velocity_range_ms") or ()
    lo, hi = (list(declared) + [3.88, 5.08])[:2] if len(declared) >= 2 else (3.88, 5.08)
    v1, v2 = st.columns(2)
    with v1:
        velocity_lo = st.number_input(
            "Ventilation velocity, low (m/s)", min_value=0.0, max_value=8.0, step=0.01,
            value=min(max(float(lo), 0.0), 8.0), key="d_v_lo")
    with v2:
        velocity_hi = st.number_input(
            "Ventilation velocity, high (m/s)", min_value=0.0, max_value=8.0, step=0.01,
            value=min(max(float(hi), 0.0), 8.0), key="d_v_hi")
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
_APPLIED_SOURCE = "_applied_source"

# widget key -> where the value lives in a design file, this form's own default, and
# the range it allows. `None` bounds mark a preset name rather than a number.
SEEDED_FIELDS = (
    ("d_tunnel", ("tunnel", "preset"), "twin_bore_11m", None, None),
    ("d_fire", ("fire", "preset"), "hgv_150mw", None, None),
    ("d_nozzle", ("nozzles", "preset"), "single_mode_fine_example", None, None),
    ("d_hydraulics", ("hydraulics", "preset"), "example", None, None),
    ("d_k", ("nozzles", "k_factor_lpm_bar05"), 4.1, 0.6, 20.0),
    ("d_pressure", ("nozzles", "pressure_bar"), 50.0, 34.5, 140.0),
    ("d_rows", ("nozzles", "mounting", "rows"), 2, 1, 3),
    ("d_pitch", ("nozzles", "mounting", "pitch_m"), 2.4, 0.1, 10.0),
    ("d_section_len", ("zones", "section_length_m"), 30.0, 8.0, 100.0),
    ("d_sections", ("zones", "sections_simultaneous"), 3, 1, 6),
    ("d_v_lo", ("ventilation", "velocity_range_ms", 0), 3.88, 0.0, 8.0),
    ("d_v_hi", ("ventilation", "velocity_range_ms", 1), 5.08, 0.0, 8.0),
)

def _design_files() -> list[str]:
    """Design files the user keeps in their own project space.

    `designs/` is the user's, and neither independence scan touches it by design —
    so it is where real project values belong, with their provenance beside them.
    """
    return [p.name for p in design_files((DESIGNS_DIR,))]


def _dig(raw: dict, *path):
    """The value at `path`, or None if any step of it is missing."""
    node = raw
    for step in path:
        if isinstance(step, int):
            if not isinstance(node, (list, tuple)) or len(node) <= step:
                return None
            node = node[step]
        elif isinstance(node, dict) and node.get(step) is not None:
            node = node[step]
        else:
            return None
    return None if node is None else node


def _seed(raw: dict, path: tuple[str, ...], fallback, low, high):
    """A file's value for one field, clamped into the widget's range.

    Clamped rather than rejected: a design file is the user's own record and may
    predate a bound this form imposes, and silently refusing to load it would be
    harder to understand than showing the nearest value the form can hold.
    """
    found = _dig(raw, *path)
    if found is None:
        return fallback
    return min(max(type(fallback)(found), low), high)


def _read_design(name: str) -> dict:
    try:
        return json.loads((DESIGNS_DIR / name).read_text())
    except (OSError, ValueError) as exc:
        st.warning(f"{name} could not be read: {exc}")
        return {}


def _apply_to_widgets(raw: dict) -> None:
    """Write the file's values into the widgets' own state.

    Assigning rather than clearing the keys. Deleting a widget's key does NOT reset it
    once it has rendered in a live browser — observed directly: with a file declaring
    40 bar selected, a pressure field that had already drawn its 50 bar default kept
    showing 50, so the form disagreed with the file it said it was showing. (AppTest
    does not reproduce this, which is why no unit test catches it.)
    """
    for key, path, default, low, high in SEEDED_FIELDS:
        found = _dig(raw, *path)
        # A field this file is silent on returns to the form's default rather than
        # keeping the last file's value: the caption says every field starts here.
        if found is None:
            st.session_state[key] = default
        else:
            st.session_state[key] = (found if low is None
                                     else min(max(type(low)(found), low), high))
    declared = (raw.get("ahj") or {})
    for field, key, *_rest in AHJ_FIELDS:
        value = declared.get(field)
        # A limit this file does not declare is cleared, not carried over from the last.
        st.session_state[key] = float(value) if value is not None else None


def _render_source_picker() -> dict:
    """Start the whole form from a design file the user already keeps."""
    names = _design_files()
    if not names:
        return {}
    chosen = st.selectbox("Start from a design file", [NO_SOURCE, *names], key="design_source",
                          help="Seeds every field below from that file. Edit anything "
                               "afterwards; nothing is written back to the file.")
    if chosen == NO_SOURCE:
        st.session_state[_APPLIED_SOURCE] = None
        return {}
    raw = _read_design(chosen)
    # Re-seed on a change of source: Streamlit honours `value=`/`index=` only on a
    # key's first render, so without this the widgets keep the previous file's values.
    if st.session_state.get(_APPLIED_SOURCE) != chosen:
        _apply_to_widgets(raw)
        st.session_state[_APPLIED_SOURCE] = chosen
    st.caption(f"Every field below starts from **{chosen}**. Edit anything for this run.")
    return raw


def _limits_from(raw: dict) -> tuple[dict, str]:
    """The limits a design file declares, and whatever it says about where they came from."""
    block = raw.get("ahj") or {}
    limits = {field: float(block[field]) for field, *_ in AHJ_FIELDS
              if block.get(field) is not None}
    return limits, str(block.get("note") or "")


def _render_ahj_inputs(raw: dict) -> dict:
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
    prefill, note = _limits_from(raw)
    values: dict[str, float] = {}
    columns = st.columns(AHJ_COLUMNS)
    for i, (field, key, caption, low, high, step) in enumerate(AHJ_FIELDS):
        entered = columns[i % AHJ_COLUMNS].number_input(
            caption, min_value=low, max_value=high, value=prefill.get(field), step=step,
            key=key, placeholder="not set")
        if entered is not None:
            values[field] = float(entered)
    if note:
        st.caption(f"The source file records: {note}")
    unset = len(AHJ_FIELDS) - len(values)
    if unset:
        st.caption(f"{unset} of {len(AHJ_FIELDS)} limits still unset.")
    return values


def design_identity(raw_source: dict) -> dict:
    """What to call the design this view is about to build.

    A design seeded from a file keeps that file's NAME. It used to be called
    "streamlit-design" whatever it was seeded from, and the name is not
    cosmetic: it is half of what identifies a result. It heads every report,
    names every archive folder, and sits in `Result.meta.design_name` beside
    the sha -- and because the sha is taken over the whole design, the name
    changed that too. The same design assessed from the app and from the CLI
    landed in different run directories and produced results that could not be
    told to be the same design.

    Edits made after seeding are expected and do not change the name: the file
    is where this came from, and a result carries the sha to say whether it is
    still identical.
    """
    name = raw_source.get("meta", {}).get("name") if raw_source else None
    if not name:
        return {"name": "streamlit-design", "notes": "Built from the Design view."}
    notes = (raw_source.get("meta", {}) or {}).get("notes", "")
    return {"name": name,
            "notes": (f"{notes}\n\n" if notes else "")
                     + "Seeded from this design in the Design view; any field may "
                       "have been edited afterwards. The result's design sha says "
                       "whether it is still identical to the file."}


DEFAULT_ROW_OFFSETS_M = {1: [0.0], 2: [-2.5, 2.5], 3: [-2.8, 0.0, 2.8]}


def _deep_merge(base: dict, over: dict) -> dict:
    """`over` laid on `base`, nested dicts merged rather than replaced."""
    out = copy.deepcopy(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _overlay(scratch: dict, raw_source: dict, k_factor: float, pressure_bar: float,
             rows: int, pitch_m: float, section_length_m: float,
             sections_simultaneous: int, velocity_lo: float, velocity_hi: float,
             ahj: dict) -> dict:
    """Three layers, in order: the form's own defaults, then the source FILE, then
    the twelve fields the form actually edits.

    The file sits in the middle rather than being composed away, so everything
    the form cannot show -- drop size, cone angle, launch velocity, mounting
    height, detection, activation delay, discharge duration -- survives. The
    defaults stay underneath so a partial file still yields a complete design.

    Row offsets are the one field that cannot simply be kept: a file listing two
    offsets cannot describe three rows. They survive while the row COUNT is
    unchanged, and fall back to the spaced default when the user changes it.
    """
    raw = _deep_merge(scratch, raw_source)
    # An OVERRIDE the file did not ask for must not arrive from the defaults.
    # `zones.manual_activation_s` pins the activation to an absolute clock time
    # and overrides the detection timetable entirely -- the schema keeps it None
    # for that reason, and it exists for validation anchors transcribed from
    # tests the operator started by hand. The form's own defaults set it to 60 s,
    # so merging naively gave a file that specifies a detection delay BOTH a
    # detector and a manual start.
    if "zones" in raw_source and "manual_activation_s" not in raw_source["zones"]:
        raw["zones"].pop("manual_activation_s", None)
    raw["meta"] = design_identity(raw_source)
    nozzles = raw.setdefault("nozzles", {})
    nozzles["k_factor_lpm_bar05"] = k_factor
    nozzles["pressure_bar"] = pressure_bar
    kept = (raw_source.get("nozzles", {}).get("mounting", {}) or {}).get("row_lateral_offsets_m")
    mount = nozzles.setdefault("mounting", {})
    mount["rows"] = rows
    mount["pitch_m"] = pitch_m
    mount["row_lateral_offsets_m"] = (list(kept) if kept and len(kept) == rows
                                      else DEFAULT_ROW_OFFSETS_M[rows])
    zones = raw.setdefault("zones", {})
    zones["section_length_m"] = section_length_m
    zones["sections_simultaneous"] = sections_simultaneous
    raw.setdefault("ventilation", {})["velocity_range_ms"] = [velocity_lo, velocity_hi]
    raw["ahj"] = ahj
    return raw


def _assemble(tunnel_preset: str, fire_preset: str, nozzle_preset: str,
             hydraulics_preset: str, k_factor: float, pressure_bar: float,
             rows: int, pitch_m: float, section_length_m: float,
             sections_simultaneous: int, velocity_lo: float, velocity_hi: float,
             ahj: dict, raw_source: dict | None = None) -> dict:
    """Every override lands inside its own block, on top of the chosen preset.

    With a source file, the FILE is the base and the form's twelve fields are
    edits on top of it. Composing from the presets instead silently replaced
    everything the form cannot show -- drop size, cone angle, launch velocity,
    row offsets, detection, activation delay, discharge duration -- while the
    caption still said every field started from that file. A design file
    carrying a real nozzle's measured spray came back as the placeholder
    preset's, and the user had no way to see it.
    """
    offsets = DEFAULT_ROW_OFFSETS_M[rows]
    scratch = {
        "meta": design_identity(raw_source or {}),
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
    if not raw_source:
        return scratch
    return _overlay(scratch, raw_source, k_factor, pressure_bar, rows, pitch_m,
                    section_length_m, sections_simultaneous,
                    velocity_lo, velocity_hi, ahj)

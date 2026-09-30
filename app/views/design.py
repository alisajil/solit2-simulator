"""The Design view: pick a starting preset for the tunnel, fire and hydraulics,
enter the nozzle, override the parameters an engineer actually varies, and
produce a `Design`.

Presets supply the tunnel, fire and hydraulics -- this mirrors
`solit2/schema/presets.py`'s own stated philosophy ("a design JSON names a
preset per block and overrides individual fields; the preset supplies
everything else"). The NOZZLE is different: it is the system under test, and
every value of it is the tester's own. No preset or form default fills any of
it in, and the design cannot be built until all of it has been entered.
"""
from __future__ import annotations

import copy
import json
from pathlib import Path

import streamlit as st

from app import plot_theme, state
from app.components import overview
from app.components import save_design
from app.components.design_files import design_files
from solit2.engines.reduced.geometry import section_geometry
from solit2.engines.reduced.hydraulics import size_system
from solit2.schema.design import TESTER_INPUT, Design
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
    fig = overview.figure(design, geom)
    fig.update_layout(template=plot_theme.current())
    st.plotly_chart(fig, key="design_overview", theme=None)


def render() -> None:
    st.header("Design")
    st.caption("Pick a starting preset for the tunnel, fire and hydraulics, then enter "
               "the nozzle. The nozzle is yours to enter; nothing about it is assumed.")
    raw_source = _render_source_picker()
    tunnel_preset, fire_preset, hydraulics_preset = _render_preset_pickers(raw_source)
    nozzles, missing = _render_nozzle_inputs(raw_source)
    section_length_m, sections_simultaneous, pump_ramp_s = _render_zoning_inputs(raw_source)
    if pump_ramp_s is None:
        missing = [*missing, PUMP_RAMP_LABEL]
    velocity_lo, velocity_hi = _render_ventilation_inputs(raw_source)
    ahj = _render_ahj_inputs(raw_source)
    raw = _assemble(tunnel_preset, fire_preset, hydraulics_preset, nozzles,
                    section_length_m, int(sections_simultaneous), velocity_lo, velocity_hi,
                    ahj, raw_source, pump_ramp_s=pump_ramp_s,
                    keep_meta=save_design.seeded() is not None)
    _render_summary(raw)
    if missing:
        st.warning("Nozzle data still needed: " + ", ".join(missing))
    save_design.render(raw, missing)
    if st.button("Build & continue →", key="build_design", type="primary",
                 disabled=bool(missing)):
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


def _render_preset_pickers(raw: dict) -> tuple[str, str, str]:
    """The per-block preset selectors: tunnel, fire, hydraulics. Never the nozzle.

    Each defaults to a verified-compatible combination (`examples/designs/
    road-tunnel-twin-bore-single-mode.json`) rather than position 0 of the
    alphabetically sorted preset list, which can pair an incompatible tunnel
    and nozzle (e.g. a nozzle mounted above the crown) with zero user
    interaction.
    """
    col1, col2 = st.columns(2)
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
    hydraulics_options = list_presets("hydraulics")
    hydraulics_preset = st.selectbox(
        "Hydraulics preset", hydraulics_options, index=_default_index(hydraulics_options, _dig(raw, "hydraulics", "preset") or "example"),
        key="d_hydraulics")
    return tunnel_preset, fire_preset, hydraulics_preset


NOZZLE_FIELDS = (
    ("d_k", ("nozzles", "k_factor_lpm_bar05"), "K-factor (L/min·bar⁰·⁵)", 0.6, 20.0, 0.1),
    ("d_pressure", ("nozzles", "pressure_bar"), "Working pressure (bar)", 34.5, 140.0, 0.5),
    ("d_smd", ("nozzles", "modes", 0, "smd_um"), "Sauter mean D32 (µm)", 1.0, 3000.0, 1.0),
    ("d_dv50", ("nozzles", "modes", 0, "dv50_um"), "Dv50 (µm)", 1.0, 3000.0, 1.0),
    ("d_dv90", ("nozzles", "modes", 0, "dv90_um"), "Dv90 (µm)", 1.0, 5000.0, 1.0),
    ("d_cone", ("nozzles", "modes", 0, "cone_half_angle_deg"), "Spray cone half-angle (°)",
     1.0, 89.0, 1.0),
    ("d_launch", ("nozzles", "modes", 0, "launch_velocity_ms"), "Discharge velocity (m/s)",
     0.1, 200.0, 0.5),
    ("d_mount_h", ("nozzles", "mounting", "height_above_carriageway_m"),
     "Head height above road (m)", 0.1, 20.0, 0.05),
    ("d_rows", ("nozzles", "mounting", "rows"), "Nozzle rows", 1, 3, 1),
    ("d_pitch", ("nozzles", "mounting", "pitch_m"), "Nozzle spacing / pitch (m)", 0.1, 10.0, 0.1),
    ("d_tilt", ("nozzles", "mounting", "tilt_deg"), "Head tilt (°)", -45.0, 45.0, 1.0),
)
NOZZLE_COLUMNS = 3
OFFSETS_KEY = "d_offsets"
OFFSETS_LABEL = "Row lateral offsets from centre line (m, comma-separated)"
OFFSETS_PATH = ("nozzles", "mounting", "row_lateral_offsets_m")
# The system's own time from activation to full pressure: it sets when the spray
# arrives in every run, the Annex 7 test included, so it is entered, never assumed.
PUMP_RAMP_KEY = "d_pump_ramp"
PUMP_RAMP_PATH = ("zones", "pump_ramp_s")
PUMP_RAMP_LABEL = "Pump ramp to full pressure (s)"
PUMP_RAMP_BOUNDS_S = (0.0, 3600.0)


def nozzle_block(values: dict) -> tuple[dict | None, list[str]]:
    """The tester's nozzle as a preset-free design block, or the fields still missing."""
    missing = [label for key, _path, label, *_ in NOZZLE_FIELDS if values.get(key) is None]
    offsets_text = (values.get(OFFSETS_KEY) or "").strip()
    if not offsets_text:
        missing.append(OFFSETS_LABEL)
    if missing:
        return None, missing
    try:
        offsets = [float(x) for x in offsets_text.split(",")]
    except ValueError:
        return None, [f"{OFFSETS_LABEL}: {offsets_text!r} is not a list of numbers"]
    v = values
    return {
        "preset": TESTER_INPUT,
        "k_factor_lpm_bar05": v["d_k"], "pressure_bar": v["d_pressure"],
        "modes": [{"id": "fine", "fraction": 1.0, "smd_um": v["d_smd"], "dv50_um": v["d_dv50"],
                   "dv90_um": v["d_dv90"], "cone_half_angle_deg": v["d_cone"],
                   "launch_velocity_ms": v["d_launch"]}],
        "mounting": {"type": "ceiling_rows", "rows": int(v["d_rows"]),
                     "row_lateral_offsets_m": offsets,
                     "height_above_carriageway_m": v["d_mount_h"], "pitch_m": v["d_pitch"],
                     "tilt_deg": v["d_tilt"]},
    }, []


def _nozzle_seed(raw: dict, path: tuple, low, high):
    """A file's value for one nozzle field, clamped into range, or None: no default."""
    found = _dig(raw, *path)
    return None if found is None else min(max(type(low)(found), low), high)


def _offsets_seed(raw: dict) -> str:
    found = _dig(raw, *OFFSETS_PATH)
    return "" if found is None else ", ".join(f"{float(x):g}" for x in found)


def _render_nozzle_inputs(raw: dict) -> tuple[dict | None, list[str]]:
    """Every nozzle value the engine uses, typed by the tester. No defaults."""
    st.subheader("Nozzle (tester input)")
    st.caption("Enter the nozzle's measured data. Nothing here is filled in for you, and "
               "the design cannot be built until every field is set.")
    file_modes = _dig(raw, "nozzles", "modes") or []
    if len(file_modes) > 1:
        st.error(f"This file's nozzle has {len(file_modes)} spray modes; this form enters a "
                 f"single-mode head. Edit the file to change it, or run it from the CLI.")
        return None, ["a single-mode nozzle"]
    values = {}
    columns = st.columns(NOZZLE_COLUMNS)
    for i, (key, path, label, low, high, step) in enumerate(NOZZLE_FIELDS):
        values[key] = columns[i % NOZZLE_COLUMNS].number_input(
            label, min_value=low, max_value=high, step=step, key=key,
            value=_nozzle_seed(raw, path, low, high), placeholder="not set")
    values[OFFSETS_KEY] = st.text_input(OFFSETS_LABEL, key=OFFSETS_KEY, value=_offsets_seed(raw),
                                        placeholder="e.g. -2.75, 2.75")
    return nozzle_block(values)


def _render_zoning_inputs(raw: dict) -> tuple[float, int, float | None]:
    """Section length, how many sections activate simultaneously, and the pump ramp.

    The pump ramp has no default: None until the tester enters it or a file gives it.
    """
    st.subheader("Zoning")
    z1, z2, z3 = st.columns(3)
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
    with z3:
        pump_ramp_s = st.number_input(
            PUMP_RAMP_LABEL, min_value=PUMP_RAMP_BOUNDS_S[0], max_value=PUMP_RAMP_BOUNDS_S[1],
            step=1.0, value=_nozzle_seed(raw, PUMP_RAMP_PATH, *PUMP_RAMP_BOUNDS_S),
            key=PUMP_RAMP_KEY, placeholder="not set")
    return section_length_m, sections_simultaneous, pump_ramp_s


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
    ("d_hydraulics", ("hydraulics", "preset"), "example", None, None),
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
    # The nozzle has no form default to return to: a value this file is silent on
    # is cleared, so a previous file's head cannot survive into this one.
    for key, path, _label, low, high, _step in NOZZLE_FIELDS:
        st.session_state[key] = _nozzle_seed(raw, path, low, high)
    st.session_state[OFFSETS_KEY] = _offsets_seed(raw)
    st.session_state[PUMP_RAMP_KEY] = _nozzle_seed(raw, PUMP_RAMP_PATH, *PUMP_RAMP_BOUNDS_S)
    declared = (raw.get("ahj") or {})
    for field, key, *_rest in AHJ_FIELDS:
        value = declared.get(field)
        # A limit this file does not declare is cleared, not carried over from the last.
        st.session_state[key] = float(value) if value is not None else None
    # The save panel's name follows the source, like every other field.
    st.session_state[save_design.NAME_KEY] = (raw.get("meta") or {}).get("name", "")


def _render_source_picker() -> dict:
    """Start the whole form from a saved design or a design file the user keeps."""
    saved = save_design.saved_options()
    names = _design_files()
    pending = save_design.pop_pending()
    just_saved = None if pending is None else next(
        (text for text, row in saved.items() if row.id == pending[0]), None)
    if just_saved is not None:
        # A save just made this version: point the picker at it before the widgets draw.
        # The form already holds exactly its values, so it is marked applied, not re-seeded.
        design_id, version = pending
        st.session_state["design_source"] = just_saved
        st.session_state[save_design.version_key(design_id)] = version
        st.session_state[_APPLIED_SOURCE] = f"saved:{design_id}:v{version}"
    if not saved and not names:
        save_design.set_seeded(None, None)
        return {}
    chosen = st.selectbox("Start from a saved design or file", [NO_SOURCE, *saved, *names],
                          key="design_source",
                          help="Seeds every field below from it. Edit anything afterwards; "
                               "nothing is written back unless you save.")
    if chosen == NO_SOURCE:
        st.session_state[_APPLIED_SOURCE] = None
        save_design.set_seeded(None, None)
        return {}
    if chosen in saved:
        loaded = save_design.render_version_picker(saved[chosen])
        if loaded is None:
            save_design.set_seeded(None, None)
            return {}
        raw, applied = loaded.payload, f"saved:{loaded.design_id}:v{loaded.version}"
        shown = f"#{loaded.design_id} v{loaded.version} ({loaded.name})"
        save_design.set_seeded(saved[chosen], loaded.version)
    else:
        raw, applied, shown = _read_design(chosen), chosen, chosen
        save_design.set_seeded(None, None)
    # Re-seed on a change of source: Streamlit honours `value=`/`index=` only on a
    # key's first render, so without this the widgets keep the previous source's values.
    if st.session_state.get(_APPLIED_SOURCE) != applied:
        _apply_to_widgets(raw)
        st.session_state[_APPLIED_SOURCE] = applied
    st.caption(f"Every field below starts from **{shown}**. Edit anything for this run.")
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
               "PMC / Authority's Engineer's risk analysis. Leave a field empty and that criterion is reported "
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


def _deep_merge(base: dict, over: dict) -> dict:
    """`over` laid on `base`, nested dicts merged rather than replaced."""
    out = copy.deepcopy(base)
    for key, value in over.items():
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = _deep_merge(out[key], value)
        else:
            out[key] = copy.deepcopy(value)
    return out


def _overlay(scratch: dict, raw_source: dict, nozzles: dict | None,
             section_length_m: float, sections_simultaneous: int,
             velocity_lo: float, velocity_hi: float, ahj: dict,
             keep_meta: bool = False) -> dict:
    """Three layers, in order: the form's own defaults, then the source FILE, then
    the fields the form actually edits.

    The file sits in the middle rather than being composed away, so everything
    the form cannot show -- detection, activation delay, discharge duration --
    survives. The defaults stay underneath so a partial file still yields a
    complete design.

    The nozzle is not layered at all. The file SEEDED the form's nozzle fields,
    the tester has seen and completed them, and what the form holds is the
    nozzle, whole: merging the file's block (or a preset it names) underneath
    would bring back values the tester never saw.

    `keep_meta` is set when `raw_source` is a saved design: `design_identity`
    appends a "Seeded from" note on every call, which would change a saved
    design's SHA on every load and make an unedited re-save never read as
    unchanged. A saved design's meta is instead kept exactly as it was saved.
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
    raw["meta"] = dict(raw_source["meta"]) if keep_meta else design_identity(raw_source)
    raw["nozzles"] = scratch["nozzles"]
    zones = raw.setdefault("zones", {})
    zones["section_length_m"] = section_length_m
    zones["sections_simultaneous"] = sections_simultaneous
    raw.setdefault("ventilation", {})["velocity_range_ms"] = [velocity_lo, velocity_hi]
    raw["ahj"] = ahj
    return raw


def _assemble(tunnel_preset: str, fire_preset: str, hydraulics_preset: str,
              nozzles: dict | None, section_length_m: float,
              sections_simultaneous: int, velocity_lo: float, velocity_hi: float,
              ahj: dict, raw_source: dict | None = None, *,
              pump_ramp_s: float | None = None, keep_meta: bool = False) -> dict:
    """Every override lands inside its own block, on top of the chosen preset.

    With a source file, the FILE is the base and the form's fields are edits on
    top of it; the nozzle is the form's alone (see `_overlay`). `nozzles` is
    None while the tester has not finished entering it, and the design then
    stays unbuildable rather than borrowing a value from anywhere; `pump_ramp_s`
    likewise, which is the form's own and overrides the file's. Composing from the presets instead silently replaced
    everything the form cannot show -- drop size, cone angle, launch velocity,
    row offsets, detection, activation delay, discharge duration -- while the
    caption still said every field started from that file. A design file
    carrying a real nozzle's measured spray came back as the placeholder
    preset's, and the user had no way to see it.

    `keep_meta` carries a saved design's own `meta` through unchanged (see `_overlay`).
    """
    scratch = {
        "meta": (dict(raw_source["meta"]) if keep_meta and raw_source
                 else design_identity(raw_source or {})),
        "tunnel": {"preset": tunnel_preset},
        "fire": {"preset": fire_preset},
        "nozzles": nozzles if nozzles is not None else {"preset": TESTER_INPUT},
        "zones": {
            "section_length_m": section_length_m,
            "sections_simultaneous": sections_simultaneous,
            "manual_activation_s": 60.0,
            "activation_delay_s": 0.0,
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
    raw = scratch if not raw_source else _overlay(
        scratch, raw_source, nozzles, section_length_m, sections_simultaneous,
        velocity_lo, velocity_hi, ahj, keep_meta=keep_meta)
    if pump_ramp_s is None:
        raw["zones"].pop("pump_ramp_s", None)
    else:
        raw["zones"]["pump_ramp_s"] = pump_ramp_s
    return raw

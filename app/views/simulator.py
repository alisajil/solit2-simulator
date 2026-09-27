"""The landing screen: the SOLIT2 Annex 7 test of the tester's own system, live.

Move a knob of the system under test and watch its Annex 7 test replay, every
reading moving together. Tier 1 runs a whole test in about a second, so the
answer is on screen as soon as a slider is released.

The sliders edit the SHARED current design (`state.get_design()`), the one the
wizard's later steps read: the design is dumped, the changed fields are set, and
it is rebuilt through `Design.from_dict`, so everything the sliders do not show
survives unchanged. What runs is that system's Annex 7 test
(`solit2.reports.twin`) -- the gallery, the mock-up, both Annex 7 velocities,
manual activation -- with the conditions Annex 7 leaves to the AHJ entered by
the tester, exactly as on the Fire test step. Nothing is loaded for the tester:
until they pick one of their own design files or build one, there is no system
to test and the screen says so.
"""
from __future__ import annotations

import html
from dataclasses import dataclass
from pathlib import Path

import streamlit as st

from app import auth, plot_theme, state
from app.components import cfd_live, live_figure, readings, run_states, twin_canvas
from app.components.design_files import design_files
from app.views.fire_test import ensure_trace, render_annex7_inputs
from app.views.result import ensure_twin_result
from solit2.engines.reduced.geometry import nozzle_positions, section_geometry
from solit2.reports import twin
from solit2.schema.design import Design

# The tester's own design files only, as on the Design step. The shipped examples
# carry illustrative nozzle values, and the landing screen must not run one as if
# it were the system under test.
PRESET_ROOTS = (Path("designs"),)
_APPLIED_PRESET = "_sim_applied_preset"
_SEEDED_FROM = "_sim_seeded_from"
CAPTION = (
    "Every reading is the Tier 1 engine's own output for this design: a prediction, not a "
    "measurement. Gauges show the worst of the Annex 7 Table 5 stations that carry each "
    "instrument; a red band is the authority's limit and appears only where one is set. The "
    "heat-release criterion judges only the peak after full pressure, but its gauge's band "
    "marks the limit at every instant, including the free burn before activation. Across the "
    "tunnel the picture is enlarged for legibility. The smoke plane's height and the spray "
    "volume are schematic; the smoke's colour is the engine's temperature at the stations, "
    "interpolated between them.")


@dataclass(frozen=True)
class Slider:
    key: str
    label: str
    path: tuple[str, ...]
    low: float
    high: float
    step: float


SLIDERS: tuple[Slider, ...] = (
    Slider("sim_pressure", "Nozzle pressure (bar)", ("nozzles", "pressure_bar"), 34.5, 140.0, 0.5),
    Slider("sim_k", "K-factor (L/min·bar⁰·⁵)", ("nozzles", "k_factor_lpm_bar05"), 0.6, 20.0, 0.1),
    Slider("sim_mount", "Mounting height (m)",
           ("nozzles", "mounting", "height_above_carriageway_m"), 1.0, 12.0, 0.1),
    Slider("sim_heads", "Heads per zone", ("zones", "heads_per_zone"), 1, 200, 1),
    Slider("sim_section", "Section length (m)", ("zones", "section_length_m"), 8.0, 100.0, 1.0),
    Slider("sim_sections", "Sections simultaneous", ("zones", "sections_simultaneous"), 1, 6, 1),
)


def preset_files() -> list[Path]:
    """Design files in the user's own space and in the shipped examples."""
    return design_files(PRESET_ROOTS)


def _get(raw: dict, path: tuple) -> object:
    node = raw
    for step in path:
        node = node[step]
    return node


def _set(raw: dict, path: tuple, value: object) -> None:
    node = raw
    for step in path[:-1]:
        node = node[step]
    node[path[-1]] = value


def edited(design: Design, changes: dict[tuple, object]) -> Design:
    """`design` with each path set to its value, everything else untouched, checked
    that its nozzle rows fit the section at the mounting height."""
    raw = design.model_dump(by_alias=True, mode="json")
    for path, value in changes.items():
        _set(raw, path, value)
    candidate = Design.from_dict(raw)
    nozzle_positions(candidate, section_geometry(candidate), fire_x_m=0.0)
    return candidate


def _current(design: Design, raw: dict, slider: Slider) -> float:
    if slider.path == ("zones", "heads_per_zone"):
        return design.heads_per_zone      # computed from the pitch when the file pins none
    return _get(raw, slider.path)


def _bounds(slider: Slider, value: float, design: Design) -> tuple[float, float]:
    """The slider's range, widened to hold the design's own value -- a range that
    clipped it would edit the design the moment it loaded."""
    high = slider.high
    if slider.key == "sim_mount":
        high = section_geometry(design).crown_height_m
    return min(slider.low, value), max(high, value)


def _seed(design: Design) -> None:
    """Write the design's values into the sliders' own state before they render."""
    raw = design.model_dump(by_alias=True, mode="json")
    for slider in SLIDERS:
        st.session_state[slider.key] = _current(design, raw, slider)
    st.session_state[_SEEDED_FROM] = design


def _needs_seed(design: Design) -> bool:
    """True when the sliders must be rewritten from `design` before they render.

    Streamlit deletes a keyed widget's state at the end of any run that does not
    render that widget -- which is exactly what happens to every slider here while
    another view is showing. `_SEEDED_FROM` is a plain key (not a widget's), so it
    survives that deletion and still equals the unchanged design on return, which
    would skip reseeding: every slider would then silently reinitialise at its
    own minimum, corrupting the shared design underneath it.
    """
    if st.session_state.get(_SEEDED_FROM) != design:
        return True
    return any(slider.key not in st.session_state for slider in SLIDERS)


def _presets() -> None:
    files = preset_files()
    if not files:
        st.caption("No design files in designs/ yet.")
        return
    labels = [p.stem for p in files]
    chosen = st.pills("Design file", labels, key="sim_preset", label_visibility="collapsed")
    if chosen is None:
        st.session_state[_APPLIED_PRESET] = None
    elif st.session_state.get(_APPLIED_PRESET) != chosen:
        path = files[labels.index(chosen)]
        try:
            design = Design.load(path)
        except (OSError, ValueError) as exc:   # pydantic's ValidationError is a ValueError
            # Load first, mark applied only on success (M-4): marking it before the
            # load left a schema-invalid file's traceback on screen AND the pill
            # marked applied against the design that failed to load, so a later
            # rerun would not even retry it.
            st.error(f"Could not load {path}: {exc}. The screen keeps the current design.")
            return
        st.session_state[_APPLIED_PRESET] = chosen
        state.set_design(design)
        st.rerun()


def annex7_conditions(test: Design, inputs: twin.Annex7Inputs) -> str:
    """The Annex 7 test being run, each value an Annex 7 clause or the tester's own."""
    velocities = " and ".join(f"{v:g}" for v in twin.ANNEX7_VELOCITIES_MS)
    return (f"Class {inputs.fire_class} mock-up · manual activation {inputs.activation_s:g} s "
            f"after ignition · run {test.zones.duration_min:g} min · {velocities} m/s · "
            f"gallery {inputs.ambient_c:g} °C, {inputs.ambient_rh_pct:g} % RH · fire growth "
            f"α {inputs.growth_alpha_kw_s2:g} kW/s² after {inputs.incubation_s:g} s · your "
            f"system's pump ramp {test.zones.pump_ramp_s:g} s")


def _sidebar(design: Design | None) -> dict[tuple, object]:
    """The knobs; returns the fields the sliders now set differently from the design."""
    changes: dict[tuple, object] = {}
    with st.sidebar:
        st.markdown('<div class="sim-label">Your designs</div>', unsafe_allow_html=True)
        _presets()
        if design is None:
            return changes
        st.markdown('<div class="sim-label">Parameters</div>', unsafe_allow_html=True)
        st.caption("Drag a slider — the result updates when you let go.")
        raw = design.model_dump(by_alias=True, mode="json")
        for slider in SLIDERS:
            value_now = _current(design, raw, slider)
            low, high = _bounds(slider, value_now, design)
            chosen = st.slider(slider.label, min_value=low, max_value=high,
                               step=slider.step, key=slider.key)
            if chosen != value_now:
                changes[slider.path] = chosen
        # No velocity knob: Annex 7 5.2.7 / 5.3.6 test both 1.5 and 3.0 m/s.
        if st.button("Open the wizard →", key="sim_open_wizard", width="stretch"):
            state.set_view("wizard")
            state.set_step(2)
            st.rerun()
    return changes


def _header(design: Design, result) -> None:
    tiles = "".join(
        f'<div class="tile"><div class="tile-label">{html.escape(t.label)}</div>'
        f'<div class="tile-value">{html.escape(t.value)}</div>'
        f'<div class="tile-note">{html.escape(t.note)}</div></div>'
        for t in readings.tiles(result))
    st.markdown(
        f'<div class="sim-head">◉ SOLIT² VIRTUAL FIRE TEST · '
        f'{html.escape(str(result.meta["engine_version"]))} · Tier 1 · '
        f'{html.escape(design.meta.name)} '
        f'<span class="chip neutral">Class {html.escape(design.fire.fire_class)}</span></div>'
        f'<div class="tiles">{tiles}</div>'
        f'<div class="diag"><span class="pill"><span class="dot"></span>TIER 1 · PREDICTION'
        f'</span> {html.escape(readings.diagnostics(result))}</div>',
        unsafe_allow_html=True)
    st.caption(str(result.meta.get("calibration_note", "")))


@st.fragment(run_every=cfd_live.REFRESH_S)
def _cfd_panel(design: Design) -> None:
    if not auth.guard_fragment():
        return
    st.markdown('<div class="sim-label">CFD · LIVE</div>', unsafe_allow_html=True)
    found = cfd_live.panel(design)
    if found is None:
        st.caption("CFD not run for this design.")
        if st.button("Set up a CFD run →", key="sim_open_cfd", width="stretch"):
            state.set_view("wizard")
            state.set_step(4)
            st.rerun()
        return
    chip = run_states.chip_class(found.state)
    st.markdown(f'<span class="chip {chip}">{html.escape(found.state)}</span>',
                unsafe_allow_html=True)
    st.progress(min(max(found.progress, 0.0), 1.0))
    if found.detail:
        st.caption(found.detail)
    for label, value, help_text in found.metrics:
        st.metric(label, value, help=help_text)


def _no_system() -> None:
    st.markdown('<div class="sim-head">◉ SOLIT² VIRTUAL FIRE TEST</div>',
                unsafe_allow_html=True)
    st.info("No system to test yet. This screen runs the SOLIT² Annex 7 test of YOUR "
            "nozzle system, and nothing is loaded or assumed for you: pick one of your "
            "design files in the sidebar, or enter the system on the Design step.")
    if st.button("Enter the system on the Design step →", key="sim_open_design"):
        state.set_view("wizard")
        state.set_step(1)
        st.rerun()


def render() -> None:
    design = state.get_design()
    if design is not None and _needs_seed(design):
        _seed(design)
    changes = _sidebar(design)
    if design is None:
        _no_system()
        return
    if changes:
        try:
            candidate = edited(design, changes)
        except ValueError as exc:   # pydantic's ValidationError is a ValueError
            st.error(f"Those settings do not make a valid design: {exc}. "
                     "The screen shows the last valid design.")
        else:
            state.set_design(candidate)
            st.rerun()
    with st.expander("Annex 7 test conditions", expanded=state.get_annex7_inputs() is None):
        inputs = render_annex7_inputs(heading=False)
    if inputs is None:
        return
    pair = ensure_twin_result(design)
    if pair is None:
        return
    test, result = pair
    trace = ensure_trace(test, result)
    _header(test, result)
    with st.sidebar:
        st.markdown('<div class="sim-label">Annex 7 test (read-only)</div>',
                    unsafe_allow_html=True)
        st.caption(annex7_conditions(test, inputs))
    main, side = st.columns([5, 1])
    with main:
        fig = live_figure.figure(test, result, trace,
                                 window_m=twin_canvas.core_window_m(test),
                                 template=plot_theme.current())
        st.plotly_chart(fig, key="sim_figure", theme=None, config={"scrollZoom": False})
        notes = readings.judged_elsewhere(result)
        if notes:
            # I-1: the figure always replays `result.worst_case`; a gauge whose own
            # criterion was decided on a different case can look comfortably clear
            # here while that other case is what actually failed a gate.
            items = "".join(f"<li>{html.escape(note)}</li>" for note in notes)
            st.markdown(f'<div class="sim-label">Judged elsewhere</div>'
                        f'<ul class="judged-elsewhere">{items}</ul>', unsafe_allow_html=True)
        st.caption(CAPTION)
    with side:
        _cfd_panel(design)

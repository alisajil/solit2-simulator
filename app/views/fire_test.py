"""Step 3: the SOLIT2 Annex 7 fire test of the tester's nozzle, as a digital twin.

The test is the Annex 7 one — the SOLIT2 gallery, the Annex 7 mock-up, the
Annex 7 velocities and activation rules — run with the nozzle system the tester
entered, and watched with the Annex 7 instrumentation reading live. The
conditions Annex 7 leaves to the AHJ or the test day are asked for here and
never assumed (`solit2.reports.twin.Annex7Inputs`)."""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from app import plot_theme, state
from app.components import cross_section, hmi, timeline, twin_canvas
from app.views.result import ensure_twin_result
from solit2.engines.reduced.criteria import INSTRUMENTS, STATIONS
from solit2.engines.reduced.geometry import SectionGeometry, section_geometry
from solit2.engines.reduced.hydraulics import size_system
from solit2.engines.reduced.sim import run_once
from solit2.engines.reduced.state import RunTrace, StepRecord
from solit2.reports import twin
from solit2.schema.design import Design
from solit2.schema.result import Result

CHART_HEIGHT = 300
# One cached `RunTrace` is 4-7 MB, and the simulator makes one per slider release
# -- a distinct design every time a slider settles -- shared by every session on
# the remote server. Unbounded, that grows without limit; 16 is enough recent
# designs to hold without paying for every one a session has ever touched (I-2).
TRACE_CACHE_MAX_ENTRIES = 16


@st.cache_data(show_spinner="Replaying the worst case…", max_entries=TRACE_CACHE_MAX_ENTRIES)
def _trace(design: Design, section: str, velocity_ms: float) -> RunTrace:
    return run_once(design, section, velocity_ms)


def ensure_trace(design: Design, result: Result) -> RunTrace:
    """The step-by-step trace of the result's worst case (the envelope keeps only summaries).

    `design` must be the one `result` was run on: the Simulator passes its Annex 7
    test, the CFD step the project design.
    """
    return _trace(design, result.worst_case["section"], result.worst_case["velocity_ms"])


# (label, widget key, Annex7Inputs field, min, max, step): what Annex 7 leaves to the
# AHJ or the test day.
ANNEX7_FIELDS = (
    ("Activation after ignition (s) — PMC / Authority's Engineer trigger; A ≥ 60 s, B ≤ 120 s", "a7_activation",
     "activation_s", 0.0, 3600.0, 1.0),
    ("Test-day ambient temperature (°C)", "a7_ambient", "ambient_c", -30.0, 60.0, 0.5),
    ("Test-day relative humidity (%)", "a7_rh", "ambient_rh_pct", 0.0, 100.0, 1.0),
    ("Mock-up fire growth α (kW/s²) — PMC / Authority's Engineer design fire", "a7_alpha", "growth_alpha_kw_s2",
     0.001, 1.0, 0.001),
    ("Incubation, ignition to growth (s) — PMC / Authority's Engineer design fire", "a7_incubation", "incubation_s",
     0.0, 1800.0, 1.0),
)
ANNEX7_CLASS_KEY = "a7_class"
ANNEX7_COLUMNS = 3
FIRE_CLASSES = {"A": "Class A — 150 MW HGV mock-up, covered", "B": "Class B — diesel pools"}


def _seed_annex7_widgets() -> None:
    """Refill the fields from the inputs already entered, on this view or the other.

    The Simulator and this step share the fields' keys, and Streamlit deletes a
    widget's state on every run that does not render it, so without this the
    inputs typed on one view would come back blank on the other. Only what the
    tester entered is written back; nothing is filled in otherwise.
    """
    entered = state.get_annex7_inputs()
    if entered is None:
        return
    st.session_state.setdefault(ANNEX7_CLASS_KEY, entered.fire_class)
    for _label, key, field, *_bounds in ANNEX7_FIELDS:
        st.session_state.setdefault(key, getattr(entered, field))


def render_annex7_inputs(heading: bool = True) -> twin.Annex7Inputs | None:
    """The Annex 7 test conditions, as the tester enters them. None until all are set."""
    _seed_annex7_widgets()
    if heading:
        st.subheader("Annex 7 test conditions")
    fire_class = st.radio("Fire", tuple(FIRE_CLASSES), format_func=FIRE_CLASSES.get,
                          horizontal=True, key=ANNEX7_CLASS_KEY)
    values = {}
    columns = st.columns(ANNEX7_COLUMNS)
    for i, (label, key, field, low, high, step) in enumerate(ANNEX7_FIELDS):
        values[field] = columns[i % ANNEX7_COLUMNS].number_input(
            label, min_value=low, max_value=high, step=step, value=None, key=key,
            placeholder="not set", format="%.4g")
    if any(v is None for v in values.values()):
        st.info("Enter the Annex 7 test inputs above. SOLIT2 leaves the activation time, "
                "the test-day ambient and the design-fire growth to the PMC / Authority's Engineer, so this "
                "page does not choose them.")
        return None
    inputs = twin.Annex7Inputs(fire_class, **values)
    state.set_annex7_inputs(inputs)
    return inputs


def _kit_caption(name: str) -> str:
    kit = INSTRUMENTS[name]
    extras = [label for flag, label in ((kit.heat_flux, "heat-flux gauge"),
                                        (kit.visibility, "visibility meter"),
                                        (kit.carbon_monoxide > 0, "CO analyser"),
                                        (kit.ultrasonic > 0, "air-velocity probe")) if flag]
    return (f"{name} at {STATIONS[name]:+.0f} m from the mock-up centre — "
            f"{kit.thermocouples} thermocouples" + "".join(f", {e}" for e in extras))


def _station_chart(design: Design, geom: SectionGeometry, trace: RunTrace,
                   step: StepRecord, cmax_c: float) -> None:
    names = sorted(STATIONS, key=STATIONS.get)
    first_downstream = next(i for i, n in enumerate(names) if STATIONS[n] > 0)
    name = st.selectbox("Station", names, index=first_downstream, key="station")
    heights = trace.steps[0].stations[name].heights_m
    fig = go.Figure()
    for i, z in enumerate(heights):
        fig.add_trace(go.Scatter(x=[s.t_s for s in trace.steps],
                                 y=[s.stations[name].temps_c[i] for s in trace.steps],
                                 mode="lines", name=f"{z:.1f} m"))
    fig.update_layout(height=CHART_HEIGHT, xaxis_title="test clock (s)",
                      yaxis_title="gas temperature (°C)", legend_title="height",
                      # 60 px clears the y-axis title and its tick labels.
                      margin={"l": 60, "r": 10, "t": 10, "b": 10})
    st.plotly_chart(fig, key="station_chart")
    st.caption(_kit_caption(name))

    fig = cross_section.figure(design, geom, step, name, cmax_c)
    fig.update_layout(template=plot_theme.current())
    st.plotly_chart(fig, key="cross_section", theme=None)
    st.caption("Thermocouples sit where Annex 7 Figure 16 puts them — two on each side wall "
               "bracketing the load, one at the ceiling, two on the load — at the same "
               "positions the CFD deck measures at. Their COLOURS are a vertical profile: "
               "this engine resolves temperature against height and carries no lateral "
               "position, so two sensors at one height read alike whichever wall they are "
               "on. The positions are the standard's; the temperatures are Tier 1's.")


def render() -> None:
    st.header("Fire test — SOLIT² Annex 7, digital twin")
    st.caption("The SOLIT² Annex 7 test of your nozzle, in the SOLIT² gallery. A Tier 1 "
               "reduced-order prediction replayed to scale — not a measurement and not a "
               "record of a test that was run.")
    design = state.get_design()
    if design is None:
        st.info("Build a design first.")
        return
    if render_annex7_inputs() is None:
        return
    pair = ensure_twin_result(design)
    if pair is None:
        return
    test, result = pair
    worst = result.worst_case["velocity_ms"]
    velocity = st.radio("Annex 7 ventilation (m/s)", twin.ANNEX7_VELOCITIES_MS, horizontal=True,
                        index=twin.ANNEX7_VELOCITIES_MS.index(worst), key="annex7_v",
                        help="Annex 7 5.2.7 / 5.3.6 test both. The one selected first is "
                             "the worse of the two for this system.")
    trace = _trace(test, "test", velocity)
    geom = section_geometry(test)

    steps = twin_canvas.sample_steps(trace, twin_canvas.TWIN_FRAME_STRIDE_S)
    labels = [twin_canvas.mmss(s.t_s) for s in steps]
    chosen = st.select_slider("Test clock", options=labels, value=labels[len(labels) // 3],
                              key="twin_clock")
    k = labels.index(chosen)
    hmi.render(steps[k], trace, test, size_system(test, geom))

    zoom = st.toggle("Zoom to the fire zone", key="twin_zoom")
    window = twin_canvas.core_window_m(test) if zoom else twin_canvas.WINDOW_M
    fig = twin_canvas.figure(test, trace, initial_frame=k, window_m=window,
                             target_ignited=bool(result.criteria["target_ignited"].value
                                                 if "target_ignited" in result.criteria else False))
    fig.update_layout(template=plot_theme.current())
    st.plotly_chart(fig, key="twin_canvas", theme=None)
    st.caption("▶ Play runs the twin on its own clock inside the picture; the Test clock "
               "slider above sets the instant the readouts describe.")

    timeline.render(trace.events, result.criteria, trace.steps[-1].t_s)
    st.subheader("Station readings")
    _station_chart(test, geom, trace, steps[k], twin_canvas.temp_max_c(trace))

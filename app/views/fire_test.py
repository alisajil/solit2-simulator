"""Step 3: the fire test as a digital twin — watch the Tier 1 worst case play out
in a to-scale tunnel with the Annex 7 instrumentation reading live."""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from app import state
from app.components import cross_section, hmi, timeline, twin_canvas
from app.views.result import ensure_result
from solit2.engines.reduced.criteria import INSTRUMENTS, STATIONS
from solit2.engines.reduced.geometry import SectionGeometry, section_geometry
from solit2.engines.reduced.hydraulics import size_system
from solit2.engines.reduced.sim import run_once
from solit2.engines.reduced.state import RunTrace, StepRecord
from solit2.schema.design import Design
from solit2.schema.result import Result

CHART_HEIGHT = 300


@st.cache_data(show_spinner="Replaying the worst case…")
def _trace(design: Design, section: str, velocity_ms: float) -> RunTrace:
    return run_once(design, section, velocity_ms)


def ensure_trace(design: Design, result: Result) -> RunTrace:
    """The step-by-step trace of the result's worst case (the envelope keeps only summaries)."""
    return _trace(design, result.worst_case["section"], result.worst_case["velocity_ms"])


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

    st.plotly_chart(cross_section.figure(design, geom, step, name, cmax_c),
                    key="cross_section", theme=None)
    st.caption("Thermocouples sit where Annex 7 Figure 16 puts them — two on each side wall "
               "bracketing the load, one at the ceiling, two on the load — at the same "
               "positions the CFD deck measures at. Their COLOURS are a vertical profile: "
               "this engine resolves temperature against height and carries no lateral "
               "position, so two sensors at one height read alike whichever wall they are "
               "on. The positions are the standard's; the temperatures are Tier 1's.")


def render() -> None:
    st.header("Fire test — digital twin")
    st.caption("A Tier 1 reduced-order prediction replayed to scale — not a measurement "
               "and not a record of a test that was run.")
    design = state.get_design()
    if design is None:
        st.info("Build a design first.")
        return
    result = ensure_result(design)
    trace = ensure_trace(design, result)
    geom = section_geometry(design)

    steps = twin_canvas.sample_steps(trace, twin_canvas.TWIN_FRAME_STRIDE_S)
    labels = [twin_canvas.mmss(s.t_s) for s in steps]
    chosen = st.select_slider("Test clock", options=labels, value=labels[len(labels) // 3],
                              key="twin_clock")
    k = labels.index(chosen)
    hmi.render(steps[k], trace, design, size_system(design, geom))

    zoom = st.toggle("Zoom to the fire zone", key="twin_zoom")
    window = twin_canvas.core_window_m(design) if zoom else twin_canvas.WINDOW_M
    fig = twin_canvas.figure(design, trace, initial_frame=k, window_m=window,
                             target_ignited=bool(result.criteria["target_ignited"].value))
    st.plotly_chart(fig, key="twin_canvas", theme=None)
    st.caption("▶ Play runs the twin on its own clock inside the picture; the Test clock "
               "slider above sets the instant the readouts describe.")

    timeline.render(trace.events, result.criteria, trace.steps[-1].t_s)
    st.subheader("Station readings")
    _station_chart(design, geom, trace, steps[k], twin_canvas.temp_max_c(trace))

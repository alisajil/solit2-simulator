"""The Tunnel view: a longitudinal thermal-field section with a time slider."""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from app import state
from solit2.engines.reduced.criteria import STATIONS
from solit2.engines.reduced.sim import run_once
from solit2.engines.reduced.state import RunTrace
from solit2.schema.design import Design

X_WINDOW_M = (-140.0, 230.0)  # matches the window already proven readable in the artifact


@st.cache_data
def _run_trace(design: Design, section: str, velocity_ms: float) -> RunTrace:
    return run_once(design, section, velocity_ms)


def render() -> None:
    st.header("Tunnel")
    design = state.get_design()
    result = state.get_result()
    if design is None or result is None:
        st.warning("Build a design and run it on the Run page first.")
        return

    trace = _run_trace(design, result.worst_case["section"], result.worst_case["velocity_ms"])
    steps = trace.steps

    idx = st.slider("Time (s)", min_value=0, max_value=len(steps) - 1, value=len(steps) // 2,
                    key="tunnel_time_idx")
    step = steps[idx]
    st.caption(f"t = {step.t_s:.0f} s -- HRR {step.hrr_mw:.1f} MW "
              f"(free burn {step.hrr_free_mw:.1f} MW) -- ceiling {step.ceiling_temp_c:.0f} C")

    fig = go.Figure()
    xs, ys = [], []
    ceiling_xs, ceiling_ys = [], []
    for name, x_m in sorted(STATIONS.items(), key=lambda kv: kv[1]):
        if not (X_WINDOW_M[0] <= x_m <= X_WINDOW_M[1]):
            continue
        # sim._sample_stations always populates every STATIONS key -- no skip path.
        sample = step.stations[name]
        xs.append(x_m)
        ys.append(sample.temp_c)
        if sample.heights_m:
            # Top rung of the per-station thermocouple ladder: a real, always-
            # available near-ceiling reading, distinct from breathing height.
            ceiling_xs.append(x_m)
            ceiling_ys.append(sample.temps_c[-1])
    fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines+markers", name="gas temp (breathing height)"))
    fig.add_trace(go.Scatter(x=ceiling_xs, y=ceiling_ys, mode="lines+markers",
                             name="near-ceiling (top thermocouple)"))

    if step.backlayer_m > 1.0:
        fig.add_vrect(x0=-step.backlayer_m, x1=0.0, fillcolor="grey", opacity=0.2,
                     annotation_text=f"backlayering {step.backlayer_m:.0f} m", line_width=0)
    if step.water_lpm > 0:
        half = design.zones.section_length_m * design.zones.sections_simultaneous / 2.0
        fig.add_vrect(x0=-half, x1=half, fillcolor="lightblue", opacity=0.15,
                     annotation_text=f"{step.water_lpm:.0f} L/min", line_width=0)

    fig.update_layout(xaxis_title="distance from fire (m)", yaxis_title="gas temperature (C)",
                      height=420, margin=dict(l=10, r=10, t=30, b=10))
    st.plotly_chart(fig)

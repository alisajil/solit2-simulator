"""Where the test's events fall on the clock, and which criteria failed."""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from app.components.twin_canvas import MIST_COLOUR, STRUCTURE_COLOUR, mmss
from solit2.reports import labels
from solit2.schema.result import Criterion

EVENT_LABELS = (("t_detect_s", "Detection"), ("t_activate_s", "Activation"),
                ("t_full_pressure_s", "Full pressure"), ("t_peak_hrr_s", "Peak HRR"),
                ("pools_extinguished_at_s", "Pools out"))


def event_marks(events: dict) -> list[tuple[float, str]]:
    marks = [(float(events[key]), label) for key, label in EVENT_LABELS
             if events.get(key) is not None]
    cleared = (events.get("backlayering") or {}).get("cleared_at_s")
    if cleared is not None:
        marks.append((float(cleared), "Backlayer cleared"))
    return sorted(marks)


def figure(events: dict, t_end_s: float) -> go.Figure:
    marks = event_marks(events)
    fig = go.Figure()
    fig.add_shape(type="line", x0=0, x1=t_end_s, y0=0, y1=0, line={"color": STRUCTURE_COLOUR, "width": 2})
    fig.add_trace(go.Scatter(x=[t for t, _ in marks], y=[0] * len(marks), mode="markers+text",
                             text=[f"{label}<br>{mmss(t)}" for t, label in marks],
                             textposition="top center",
                             marker={"size": 10, "color": MIST_COLOUR}, hoverinfo="skip"))
    fig.update_layout(height=130, margin={"l": 10, "r": 10, "t": 10, "b": 10}, showlegend=False,
                      xaxis={"range": [0, t_end_s], "title": "test clock (s)"},
                      yaxis={"visible": False, "range": [-1, 1]})
    return fig


def render(events: dict, criteria: dict[str, Criterion], t_end_s: float) -> None:
    st.plotly_chart(figure(events, t_end_s), key="timeline")
    failed = [name for name, c in criteria.items() if c.status == "fail"]
    unset = [name for name, c in criteria.items() if c.status == "unset"]
    if failed:
        chips = "".join(f'<span class="chip fail">{labels.label(n)}</span>' for n in failed)
        st.markdown(f"Failed criteria: {chips}", unsafe_allow_html=True)
    # Without this, a run judged against almost nothing looks like a clean sheet.
    if unset:
        chips = "".join(f'<span class="chip unset">{labels.label(n)}</span>' for n in unset)
        st.markdown(f"Not judged — no AHJ limit set: {chips}", unsafe_allow_html=True)

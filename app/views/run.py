"""The Run view: execute the engine on the current design, show what it found."""
from __future__ import annotations

import streamlit as st

from app import state
from app.components.charts import criteria_table, timeseries_chart
from solit2.engines.reduced import envelope


def render() -> None:
    st.header("Run")
    design = state.get_design()
    if design is None:
        st.warning("Build a design on the Design page first.")
        return

    st.caption(f"Design: **{design.meta.name}**")
    if st.button("Run simulation", type="primary"):
        with st.spinner("Running the reduced-order engine..."):
            result = envelope.run(design)
        state.set_result(result)

    result = state.get_result()
    if result is None:
        return

    st.subheader("Peaks")
    cols = st.columns(4)
    peak_items = list(result.peaks.items())[:4]
    for col, (name, value) in zip(cols, peak_items):
        col.metric(name, f"{value:.1f}")

    st.subheader("Acceptance criteria")
    st.dataframe(criteria_table(result.criteria), use_container_width=True)

    if result.constraints:
        st.subheader("Site constraints (not SOLIT2 acceptance criteria)")
        st.dataframe(criteria_table(result.constraints), use_container_width=True)

    st.subheader("Timeseries")
    available = [k for k in result.timeseries if k != "t_s"]
    chosen = st.multiselect("Series", available, default=available[: min(3, len(available))])
    if chosen:
        st.plotly_chart(timeseries_chart(result.timeseries, chosen), use_container_width=True)

    if result.warnings:
        st.subheader("Warnings")
        for w in result.warnings:
            st.warning(w)

    with st.expander("Full result JSON"):
        st.json(result.model_dump(mode="json"), expanded=False)

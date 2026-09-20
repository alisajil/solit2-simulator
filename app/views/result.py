"""Step 2: the Tier 1 verdict on the current design, and how it ranks.

The engine runs the moment this step is opened — a Tier 1 run takes seconds,
so there is nothing to click. Every run is recorded to the history file, as
`solit2 run` does by default.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app import state
from app.components.charts import criteria_table, timeseries_chart
from solit2 import history
from solit2.engines.reduced import envelope
from solit2.schema.design import Design
from solit2.schema.result import Result

PEAK_TILES = 4
SERIES_DEFAULT = 3
LEADERBOARD_TOP = 20


def ensure_result(design: Design) -> Result:
    """The Tier 1 result for `design`, computing and recording it on first use."""
    result = state.get_result()
    if result is None:
        try:
            with st.spinner("Running the reduced-order engine…"):
                result = envelope.run(design)
        except (ArithmeticError, RuntimeError, ValueError, KeyError) as exc:
            # The stepper header is already drawn, so the user can go back and fix the design.
            st.error(f"The engine could not finish this design: {exc}")
            st.stop()
        state.set_result(result)
        history.append(result, history.DEFAULT_PATH)
    return result


def _verdict(result: Result) -> None:
    failed, unset = result.score["gates_failed"], result.score["criteria_unset"]
    label, cls = ("FAIL", "fail") if failed else ("PASS", "pass")
    note = (f"{len(unset)} criteria not judged — no AHJ limit set" if unset
            else "every criterion judged")
    st.markdown(
        f'<div class="verdict {cls}"><span class="verdict-label">{label}</span>'
        f'<span class="verdict-score">score {result.score["total"]:.2f} / 10</span>'
        f'<span class="verdict-note">{note}</span></div>', unsafe_allow_html=True)


def _chips(result: Result) -> None:
    chips = "".join(f'<span class="chip {c.status}">{name}</span>'
                    for name, c in result.criteria.items() if c.hard)
    st.markdown(chips, unsafe_allow_html=True)


def _leaderboard(result: Result) -> None:
    with st.expander("Compare with earlier designs"):
        passing = st.checkbox("Passing designs only", key="lb_passing")
        rows = history.leaderboard(history.DEFAULT_PATH, top=LEADERBOARD_TOP, passing_only=passing)
        if not rows:
            st.info("No earlier runs recorded yet.")
            return
        table = pd.DataFrame(rows)
        table.insert(0, "this", table["design_sha"].eq(result.meta["design_sha"])
                     .map({True: "◀", False: ""}))
        st.dataframe(table, key="leaderboard", hide_index=True)


def render() -> None:
    st.header("Result — Tier 1")
    design = state.get_design()
    if design is None:
        st.info("Build a design first.")
        return
    result = ensure_result(design)
    st.caption(f"Design **{design.meta.name}** · worst case: {result.worst_case['section']} "
               f"section at {result.worst_case['velocity_ms']:.2f} m/s")
    _verdict(result)
    _chips(result)

    st.subheader("Peaks")
    for col, (name, value) in zip(st.columns(PEAK_TILES), list(result.peaks.items())[:PEAK_TILES]):
        col.metric(name, f"{value:.1f}")
    st.subheader("Acceptance criteria")
    st.dataframe(criteria_table(result.criteria), key="criteria", hide_index=True)
    if result.constraints:
        st.subheader("Site constraints (not SOLIT2 acceptance criteria)")
        st.dataframe(criteria_table(result.constraints), key="constraints", hide_index=True)

    st.subheader("Timeseries")
    available = [k for k in result.timeseries if k != "t_s"]
    chosen = st.multiselect("Series", available, default=available[:SERIES_DEFAULT], key="series")
    if chosen:
        st.plotly_chart(timeseries_chart(result.timeseries, chosen), key="timeseries")
    for warning in result.warnings:
        st.warning(warning)
    _leaderboard(result)

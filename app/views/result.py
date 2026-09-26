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
from solit2.reports import labels
from solit2.schema.design import Design
from solit2.schema.result import Result

PEAK_TILES = 4
SERIES_DEFAULT = 3
LEADERBOARD_TOP = 20
_RECORDED_SHA_KEY = "_result_recorded_sha"   # the design whose result this session already appended to the history


def ensure_result(design: Design, record: bool = True) -> Result:
    """The Tier 1 result for `design`, computing it on first use and recording once per design per session.

    `record=False` (the simulator's own slider exploration) never appends to
    `runs/history.jsonl` -- the simulator makes one run per slider release, and
    recording every one of them would flood the leaderboard with slider-drag
    noise. The wizard's Result step keeps `record=True` (the default): a design
    reaching that step is the one the engineer is actually considering (I-3).

    When `record=True`, the result is recorded to history once per design SHA
    per session, whether it was just computed or served from the cache.
    """
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

    # Record once per design SHA per session when record=True, whether the result
    # was just computed or served from the cache.
    if record and st.session_state.get(_RECORDED_SHA_KEY) != result.meta["design_sha"]:
        history.append(result, history.DEFAULT_PATH)
        st.session_state[_RECORDED_SHA_KEY] = result.meta["design_sha"]

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
    _calibration(result)


def _calibration(result: Result) -> None:
    """What the number rests on. INDEPENDENCE rule 3: a result states this itself.

    Without it a green PASS reads as a measurement, when it is an extrapolation from an
    engine fitted against reference cases that used a different nozzle.
    """
    note = result.meta.get("calibration_note")
    if note:
        st.caption(f"Tier 1 — reduced-order prediction, not a measurement. {note}")


def _chips(result: Result) -> None:
    chips = "".join(f'<span class="chip {c.status}">{labels.label(name)}</span>'
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
    for col, (name, peak) in zip(st.columns(PEAK_TILES), list(result.peaks.items())[:PEAK_TILES]):
        col.metric(labels.label(name), labels.with_unit(name, peak))
    st.subheader("Acceptance criteria")
    st.dataframe(criteria_table(result.criteria), key="criteria", hide_index=True)
    if result.constraints:
        st.subheader("Site constraints (not SOLIT2 acceptance criteria)")
        st.dataframe(criteria_table(result.constraints), key="constraints", hide_index=True)

    st.subheader("Timeseries")
    available = [k for k in result.timeseries if k != "t_s"]
    chosen = st.multiselect("Series", available, default=available[:SERIES_DEFAULT],
                            key="series", format_func=labels.heading)
    if chosen:
        st.plotly_chart(timeseries_chart(result.timeseries, chosen), key="timeseries")
    for warning in result.warnings:
        st.warning(warning)
    _leaderboard(result)

"""The Leaderboard view: save the current run to history, browse past runs."""
from __future__ import annotations

import streamlit as st

from app import state
from solit2 import history


def render() -> None:
    st.header("Leaderboard")

    result = state.get_result()
    if result is not None:
        if st.button("Save this run to history"):
            history.append(result)
            st.success("Saved.")

    passing_only = st.checkbox("Passing designs only", value=False)
    rows = history.leaderboard(top=20, passing_only=passing_only)
    if not rows:
        st.info("No runs saved yet. Run a simulation, then save it here.")
        return
    st.dataframe(rows)

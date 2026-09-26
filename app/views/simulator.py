"""The landing screen. This task gives it its heading and the way into the wizard;
the sidebar, tiles, live figure and CFD panel arrive in Task 5."""
from __future__ import annotations

import streamlit as st

from app import state


def render() -> None:
    st.markdown('<div class="sim-head">SOLIT² VIRTUAL FIRE TEST · Tier 1 · PREDICTION</div>',
                unsafe_allow_html=True)
    if st.button("Open the wizard →", key="sim_open_wizard"):
        state.set_view("wizard")
        st.rerun()

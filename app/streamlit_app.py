"""Entry point. Run with: uv run streamlit run app/streamlit_app.py"""
from __future__ import annotations

import streamlit as st

from app import state, theme
from app.components import stepper
from app.views import cfd, compliance, design, fire_test, reports, result

st.set_page_config(page_title="SOLIT2 Simulator", layout="wide",
                   initial_sidebar_state="collapsed")
theme.inject()

VIEWS = {1: design.render, 2: result.render, 3: fire_test.render,
         4: cfd.render, 5: compliance.render, 6: reports.render}

stepper.render_header()
step = state.get_step()
if step > state.STEP_MIN and state.get_design() is None:
    st.info("Build a design first — every later step is computed from it.")
    if st.button("Go to Design", key="goto_design", type="primary"):
        state.set_step(state.STEP_MIN)
        st.rerun()
else:
    VIEWS[step]()
stepper.render_footer()

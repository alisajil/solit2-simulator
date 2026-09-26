"""Entry point. Run with: uv run streamlit run app/streamlit_app.py"""
from __future__ import annotations

from functools import partial

import streamlit as st

from app import state, theme
from app.components import nav, stepper
from app.views import admin, cfd, compliance, design, fire_test, login, reports, result, runs, simulator

st.set_page_config(page_title="SOLIT2 Simulator", layout="wide",
                   initial_sidebar_state="expanded")
theme.inject()
# The login gate. It returns only for an approved, signed-in account; for anyone else it
# shows the login screens and stops the run, so nothing below this line runs.
user = login.gate()

STEP_VIEWS = {1: design.render, 2: result.render, 3: fire_test.render,
              4: cfd.render, 5: compliance.render, 6: reports.render}


def _wizard() -> None:
    stepper.render_header()
    step = state.get_step()
    if step > state.STEP_MIN and state.get_design() is None:
        st.info("Build a design first — every later step is computed from it.")
        if st.button("Go to Design", key="goto_design", type="primary"):
            state.set_step(state.STEP_MIN)
            st.rerun()
    else:
        STEP_VIEWS[step]()
    stepper.render_footer()


SCREENS = {"simulator": simulator.render, "wizard": _wizard, "runs": runs.render,
           "admin": partial(admin.render, user)}

nav.render(user)
view = state.current_view(user.role)
if view is None:
    login.render_workspace_pending()
else:
    SCREENS[view]()

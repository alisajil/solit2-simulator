"""Entry point. Run with: uv run streamlit run app/streamlit_app.py"""
from __future__ import annotations

import streamlit as st

from app.views import design as design_view
from app.views import leaderboard as leaderboard_view
from app.views import reports as reports_view
from app.views import run as run_view
from app.views import tunnel as tunnel_view
from app.views import verify as verify_view

st.set_page_config(page_title="SOLIT2 Simulator", layout="wide")

PAGES = {
    "Design": design_view.render,
    "Run": run_view.render,
    "Tunnel": tunnel_view.render,
    "Leaderboard": leaderboard_view.render,
    "Verify": verify_view.render,
    "Reports": reports_view.render,
}

page = st.sidebar.radio("Page", list(PAGES))
st.sidebar.caption("SOLIT2 Annex 7 simulator -- reduced-order engine, calibrated against Annex 2.")
PAGES[page]()

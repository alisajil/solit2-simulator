"""The top-level nav: one button per screen, the current one highlighted."""
from __future__ import annotations

import streamlit as st

from app import state

LABELS = {"simulator": "Simulator", "wizard": "Wizard", "runs": "CFD runs"}
# Three narrow buttons on the left, the rest of the row left empty.
NAV_COLUMNS = (1, 1, 1, 5)


def render() -> None:
    current = state.get_view()
    for col, (view, label) in zip(st.columns(NAV_COLUMNS), LABELS.items()):
        kind = "primary" if view == current else "secondary"
        if col.button(label, key=f"nav_{view}", type=kind, width="stretch"):
            state.set_view(view)
            st.rerun()

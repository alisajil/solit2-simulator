"""The top-level nav: one button per screen the account may open, the current one
highlighted, and on the right who is signed in with a Log out button."""
from __future__ import annotations

import streamlit as st

from app import auth, state
from app.accounts.store import User

LABELS = {"simulator": "Simulator", "wizard": "Wizard", "runs": "CFD runs"}
# One narrow column per screen, a spacer, then the account's email and Log out.
VIEW_COLUMN, SPACER_COLUMN, EMAIL_COLUMN, LOGOUT_COLUMN = 1, 3, 2, 1


def render(user: User) -> None:
    views = state.views_for(user.role)
    current = state.current_view(user.role)
    widths = [VIEW_COLUMN] * len(views) + [SPACER_COLUMN, EMAIL_COLUMN, LOGOUT_COLUMN]
    *view_columns, _, email_column, logout_column = st.columns(widths,
                                                               vertical_alignment="center")
    for column, view in zip(view_columns, views):
        kind = "primary" if view == current else "secondary"
        if column.button(LABELS[view], key=f"nav_{view}", type=kind, width="stretch"):
            state.set_view(view)
            st.rerun()
    email_column.caption(f"Signed in as {user.email}")
    if logout_column.button("Log out", key="nav_logout", width="stretch"):
        auth.sign_out(auth.LOGGED_OUT_NOTICE)
        st.rerun()

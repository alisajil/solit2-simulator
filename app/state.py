"""Typed accessors for the two pieces of state every view shares.

Streamlit's `st.session_state` is an untyped dict that persists across
reruns of the script within one browser session. Every view reads and
writes through these functions rather than touching the dict directly, so
the keys in use — design, result, twin_result, tier2_result, step and view
— are named in exactly one place.
"""
from __future__ import annotations

import streamlit as st

from solit2.schema.design import Design
from solit2.schema.result import Result

_DESIGN_KEY = "design"
_RESULT_KEY = "result"
_TWIN_KEY = "twin_result"
_TIER2_KEY = "tier2_result"
_STEP_KEY = "step"
STEP_MIN, STEP_MAX = 1, 6
_DERIVED_KEYS = (_RESULT_KEY, _TWIN_KEY, _TIER2_KEY)

_VIEW_KEY = "view"
# The app's three top-level screens: the live simulator is the landing screen,
# the wizard carries the formal record, the runs manager watches the FDS fleet.
VIEWS = ("simulator", "wizard", "runs")
DEFAULT_VIEW = "simulator"


def get_view() -> str:
    view = st.session_state.get(_VIEW_KEY, DEFAULT_VIEW)
    return view if view in VIEWS else DEFAULT_VIEW


def set_view(view: str) -> None:
    if view not in VIEWS:
        raise ValueError(f"unknown view {view!r}; expected one of {', '.join(VIEWS)}")
    st.session_state[_VIEW_KEY] = view


def get_step() -> int:
    return int(st.session_state.get(_STEP_KEY, STEP_MIN))


def set_step(step: int) -> None:
    st.session_state[_STEP_KEY] = min(max(int(step), STEP_MIN), STEP_MAX)


def get_design() -> Design | None:
    return st.session_state.get(_DESIGN_KEY)


def set_design(design: Design) -> None:
    st.session_state[_DESIGN_KEY] = design
    # A new design invalidates everything computed from the old one.
    for key in _DERIVED_KEYS:
        st.session_state.pop(key, None)


def get_result() -> Result | None:
    return st.session_state.get(_RESULT_KEY)


def set_result(result: Result) -> None:
    st.session_state[_RESULT_KEY] = result


def get_twin_result() -> Result | None:
    return st.session_state.get(_TWIN_KEY)


def set_twin_result(result: Result) -> None:
    st.session_state[_TWIN_KEY] = result


def get_tier2_result() -> Result | None:
    return st.session_state.get(_TIER2_KEY)


def set_tier2_result(result: Result | None) -> None:
    """`None` clears it — a relaunched run invalidates the previous run's result."""
    if result is None:
        st.session_state.pop(_TIER2_KEY, None)
        return
    st.session_state[_TIER2_KEY] = result

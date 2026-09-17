"""Typed accessors for the two pieces of state every view shares.

Streamlit's `st.session_state` is an untyped dict that persists across
reruns of the script within one browser session. Every view reads and
writes through these functions rather than touching the dict directly, so
the two keys in use -- "design" and "result" -- are named in exactly one
place.
"""
from __future__ import annotations

import streamlit as st

from solit2.schema.design import Design
from solit2.schema.result import Result

_DESIGN_KEY = "design"
_RESULT_KEY = "result"


def get_design() -> Design | None:
    return st.session_state.get(_DESIGN_KEY)


def set_design(design: Design) -> None:
    st.session_state[_DESIGN_KEY] = design
    # A new design invalidates whatever the last run computed.
    st.session_state.pop(_RESULT_KEY, None)


def get_result() -> Result | None:
    return st.session_state.get(_RESULT_KEY)


def set_result(result: Result) -> None:
    st.session_state[_RESULT_KEY] = result

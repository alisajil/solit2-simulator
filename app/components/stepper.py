"""The wizard's navigation: five step pills on top, Back / Next underneath.

Reachability is deliberately simple: step 1 is always open and every other
step opens once a design exists, because each of them auto-computes what it
needs from the design (spec §3.3). The stepper never runs the engine itself.
"""
from __future__ import annotations

import streamlit as st

from app import state

STEPS = ("Design", "Result", "Fire test", "CFD verify", "Reports")


def reachable(step: int) -> bool:
    return step == state.STEP_MIN or state.get_design() is not None


def _go(step: int) -> None:
    state.set_step(step)
    st.rerun()


def render_header() -> None:
    current = state.get_step()
    for i, (col, label) in enumerate(zip(st.columns(len(STEPS)), STEPS), start=state.STEP_MIN):
        done = i < current and reachable(i)
        text = f"{'✓' if done else i}  {label}"
        kind = "primary" if i == current else "secondary"
        if col.button(text, key=f"step_{i}", type=kind, disabled=not reachable(i),
                      width="stretch"):
            _go(i)


def render_footer() -> None:
    current = state.get_step()
    st.divider()
    back, _, nxt = st.columns([1, 4, 1])
    if current > state.STEP_MIN and back.button("← Back", key="nav_back", width="stretch"):
        _go(current - 1)
    if current < state.STEP_MAX and nxt.button(
            "Next →", key="nav_next", type="primary", width="stretch",
            disabled=not reachable(current + 1)):
        _go(current + 1)

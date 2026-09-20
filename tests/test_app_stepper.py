"""Stepper navigation on a minimal script; the real app is exercised in test_app_wizard."""
from streamlit.testing.v1 import AppTest

from app import state

SCRIPT = """
import streamlit as st
from app import state
from app.components import stepper
from solit2.schema.design import Design
if st.session_state.get("_seed") and state.get_design() is None:
    state.set_design(Design.load("examples/designs/road-tunnel-twin-bore.json"))
stepper.render_header()
st.write(f"step={state.get_step()}")
stepper.render_footer()
"""


def _keys(at):
    return {b.key for b in at.button}


def test_without_a_design_only_step_one_is_enabled_and_there_is_no_back_button():
    at = AppTest.from_string(SCRIPT)
    at.run()
    assert not at.exception
    assert not at.button(key="step_1").disabled
    for i in range(2, 6):
        assert at.button(key=f"step_{i}").disabled, i
    assert "nav_back" not in _keys(at)
    assert at.button(key="nav_next").disabled


def test_with_a_design_next_back_and_jump_move_the_step():
    at = AppTest.from_string(SCRIPT)
    at.session_state["_seed"] = True
    at.run()
    assert all(not at.button(key=f"step_{i}").disabled for i in range(1, 6))
    at.button(key="nav_next").click().run()
    assert at.session_state["step"] == 2
    at.button(key="nav_back").click().run()
    assert at.session_state["step"] == 1
    at.button(key="step_5").click().run()
    assert at.session_state["step"] == 5
    assert "nav_next" not in _keys(at)


def test_set_design_invalidates_every_downstream_result(monkeypatch):
    fake = {"result": "r", "twin_result": "t", "tier2_result": "f"}
    monkeypatch.setattr(state.st, "session_state", fake)
    state.set_design("design")
    assert fake == {"design": "design"}


def test_set_step_clamps_to_the_wizard_range(monkeypatch):
    fake = {}
    monkeypatch.setattr(state.st, "session_state", fake)
    state.set_step(0)
    assert fake["step"] == state.STEP_MIN
    state.set_step(99)
    assert fake["step"] == state.STEP_MAX

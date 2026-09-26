"""The app's three top-level screens and the nav between them."""
from streamlit.testing.v1 import AppTest

from app.views import cfd
from solit2 import history
from tests.conftest import sign_in

APP = "../app/streamlit_app.py"


def _app(monkeypatch, tmp_path) -> AppTest:
    monkeypatch.setattr(history, "DEFAULT_PATH", tmp_path / "h.jsonl")
    monkeypatch.setattr(cfd, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setenv("SOLIT2_RUN_ROOTS", str(tmp_path / "runs"))
    monkeypatch.setenv("SOLIT2_CFD_STATE_DIR", str(tmp_path / "state"))
    at = AppTest.from_file(APP, default_timeout=180)
    sign_in(at)
    at.run()
    return at


def _keys(at: AppTest) -> set[str]:
    return {b.key for b in at.button}


def test_the_app_opens_on_the_simulator(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    assert not at.exception
    assert {"nav_simulator", "nav_wizard", "nav_runs"} <= _keys(at)
    assert "step_1" not in _keys(at)


def test_the_nav_opens_the_wizard_and_comes_back(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    at.button(key="nav_wizard").click().run()
    assert not at.exception
    assert "step_1" in _keys(at)
    at.button(key="nav_simulator").click().run()
    # C-1: the round trip itself must not crash (Streamlit drops the velocity
    # slider's keyed state on the run that doesn't render it) and must land back
    # on the simulator, not silently stay on the wizard's own view.
    assert not at.exception
    assert at.session_state["view"] == "simulator"
    assert "step_1" not in _keys(at)


def test_the_nav_opens_the_runs_manager(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    at.button(key="nav_runs").click().run()
    assert not at.exception
    assert at.session_state["view"] == "runs"


def test_set_view_refuses_an_unknown_view():
    at = AppTest.from_string("from app import state\nstate.set_view('nowhere')\n")
    at.run()
    assert at.exception
    assert "unknown view" in at.exception[0].value


def test_a_role_lands_only_on_a_screen_it_may_open():
    script = ("import streamlit as st\nfrom app import state\n"
              "st.write(' '.join(f'{r}={state.current_view(r)}' "
              "for r in ('admin', 'team', 'customer', None)))\n")
    at = AppTest.from_string(script)
    at.session_state["view"] = "wizard"
    at.run()
    assert at.markdown[0].value == "admin=wizard team=wizard customer=None None=None"

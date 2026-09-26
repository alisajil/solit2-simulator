"""The real app, headless: six steps, automatic hand-off, no file movement."""
from streamlit.testing.v1 import AppTest

from app.views import cfd
from solit2 import history
from tests.conftest import sign_in

APP = "../app/streamlit_app.py"


def _app(monkeypatch, tmp_path) -> AppTest:
    monkeypatch.setattr(history, "DEFAULT_PATH", tmp_path / "h.jsonl")
    monkeypatch.setattr(cfd, "RUNS_DIR", tmp_path / "runs")
    at = AppTest.from_file(APP, default_timeout=180)
    sign_in(at)
    at.session_state["view"] = "wizard"
    at.run()
    return at


def test_the_wizard_opens_on_the_design_step_with_later_steps_locked(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    assert not at.exception
    assert at.session_state.get("step", 1) == 1
    assert not at.button(key="step_1").disabled
    assert all(at.button(key=f"step_{i}").disabled for i in range(2, 7))
    assert not at.sidebar.radio


def test_build_and_continue_runs_tier_one_without_another_click(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    at.button(key="build_design").click().run()
    assert at.session_state["step"] == 2
    assert at.session_state["result"] is not None
    assert any('class="verdict' in m.value for m in at.markdown)
    assert (tmp_path / "h.jsonl").exists()


def test_every_step_renders_and_none_asks_for_a_file(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    at.button(key="build_design").click().run()
    for i in range(2, 7):
        at.button(key=f"step_{i}").click().run()
        assert not at.exception, i
        assert at.session_state["step"] == i
        assert not at.get("file_uploader"), i
    # The form's example heads sit at 5.75 m, above the 5.2 m SOLIT2 gallery, and
    # SOLIT2 publishes no reference height to substitute: the twin is refused, said
    # so on screen, and the rest of the step still renders.
    assert "twin_result" not in at.session_state
    assert any("enter the height the heads will be tested at" in e.value for e in at.error)
    assert at.get("download_button")            # exports live on the last step only


def test_back_and_next_walk_the_wizard(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    at.button(key="build_design").click().run()
    at.button(key="nav_next").click().run()
    assert at.session_state["step"] == 3
    at.button(key="nav_back").click().run()
    at.button(key="nav_back").click().run()
    assert at.session_state["step"] == 1


def test_a_later_step_without_a_design_offers_the_way_back(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    at.session_state["step"] = 3
    at.run()
    assert not at.exception
    at.button(key="goto_design").click().run()
    assert at.session_state["step"] == 1

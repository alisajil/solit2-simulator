"""The landing screen, headless: live readings of the engine's own output."""
from streamlit.testing.v1 import AppTest

from app.views import cfd, simulator
from solit2 import history
from solit2.engines.fds import deck
from solit2.schema.design import Design

APP = "../app/streamlit_app.py"


def _app(monkeypatch, tmp_path) -> AppTest:
    monkeypatch.setattr(history, "DEFAULT_PATH", tmp_path / "h.jsonl")
    monkeypatch.setattr(cfd, "RUNS_DIR", tmp_path / "runs")
    at = AppTest.from_file(APP, default_timeout=180)
    at.run()
    return at


def _text(at: AppTest) -> str:
    return " ".join(m.value for m in at.markdown)


def test_the_landing_screen_is_the_live_simulator(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    assert not at.exception
    assert "VIRTUAL FIRE TEST" in _text(at)
    assert "TIER 1 · PREDICTION" in _text(at)
    assert at.session_state["design"] is not None


def test_the_tiles_show_the_results_own_peaks(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    result = at.session_state["result"]
    assert f"{result.peaks['hrr_mw']:.1f} MW" in _text(at)
    assert f"free burn {result.peaks['hrr_free_burn_mw']:.1f} MW" in _text(at)


def test_the_calibration_note_is_on_screen(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    note = at.session_state["result"].meta["calibration_note"]
    assert any(note in c.value for c in at.caption)


def test_moving_a_slider_rebuilds_the_design_and_reruns_the_engine(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    before = at.session_state["result"].meta["design_sha"]
    at.sidebar.slider(key="sim_pressure").set_value(60.0).run()
    assert not at.exception
    assert at.session_state["design"].nozzles.pressure_bar == 60.0
    assert at.session_state["result"].meta["design_sha"] != before


def test_settings_that_make_no_valid_design_are_reported_and_the_last_design_kept(
        monkeypatch, tmp_path):
    def refuse(design, changes):
        raise ValueError("synthetic refusal")
    at = _app(monkeypatch, tmp_path)
    before = at.session_state["design"]
    monkeypatch.setattr(simulator, "edited", refuse)
    at.sidebar.slider(key="sim_pressure").set_value(61.0).run()
    assert any("synthetic refusal" in e.value for e in at.error)
    assert at.session_state["design"] == before


def test_a_preset_loads_that_design_file(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    at.session_state["sim_preset"] = "solit2-test-protocol-class-b"
    at.run()
    expected = Design.load("examples/designs/solit2-test-protocol-class-b.json")
    assert at.session_state["design"] == expected


def test_open_the_wizard_lands_on_the_result_step_with_the_same_design(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    sha = at.session_state["result"].meta["design_sha"]
    at.sidebar.button(key="sim_open_wizard").click().run()
    assert at.session_state["view"] == "wizard"
    assert at.session_state["step"] == 2
    assert at.session_state["result"].meta["design_sha"] == sha


def test_the_cfd_panel_says_when_no_run_exists(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    assert any("CFD not run for this design" in c.value for c in at.caption)


def test_the_cfd_panel_reads_a_run_of_this_design(monkeypatch, tmp_path):
    chid = deck.chid(Design.load(simulator.DEFAULT_PRESET))
    run_dir = tmp_path / "runs" / chid
    run_dir.mkdir(parents=True)
    (run_dir / "deck.fds").write_text(f"&HEAD CHID='{chid}' /\n&TIME T_END=1200.0 /\n")
    (run_dir / f"{chid}.out").write_text("Time Step 10\n Total Time:  120.0 s\n")
    at = _app(monkeypatch, tmp_path)
    assert not at.exception
    assert any(m.label == "Simulated" for m in at.metric)

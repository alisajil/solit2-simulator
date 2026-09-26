"""The landing screen, headless: live readings of the engine's own output."""
import pytest
from streamlit.testing.v1 import AppTest

from app.components import readings
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


def test_judged_elsewhere_is_shown_under_the_figure(monkeypatch, tmp_path):
    """I-1: the default landing design already disagrees -- heat flux peaks at the
    3.0 m/s end of the protocol's envelope while the figure replays the worst
    case, 1.5 m/s (thinnest hard margin), so the gauge alone would look clear."""
    at = _app(monkeypatch, tmp_path)
    text = _text(at)
    assert "Judged elsewhere" in text
    assert "Heat flux was judged on the test section at 3.00 m/s" in text
    assert "worst case (test section at 1.50 m/s)" in text


def test_judged_elsewhere_is_absent_when_the_envelope_has_only_one_case(monkeypatch, tmp_path):
    raw = Design.load(simulator.DEFAULT_PRESET).model_dump(by_alias=True, mode="json")
    raw["ventilation"]["velocity_ms"] = 1.5
    monkeypatch.setattr(history, "DEFAULT_PATH", tmp_path / "h.jsonl")
    monkeypatch.setattr(cfd, "RUNS_DIR", tmp_path / "runs")
    at = AppTest.from_file(APP, default_timeout=180)
    at.session_state["design"] = Design.from_dict(raw)
    at.run()
    assert not at.exception
    assert "Judged elsewhere" not in _text(at)


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


def test_a_velocity_range_wider_than_the_sliders_default_does_not_crash(monkeypatch, tmp_path):
    """`ventilation.velocity_range_ms` carries no schema bound of its own (unlike the
    scalar `velocity_ms`), so a design declaring a range outside the slider's default
    (0.0, 8.0) span must still render -- the slider widens to hold it, not the other
    way round."""
    monkeypatch.setattr(history, "DEFAULT_PATH", tmp_path / "h.jsonl")
    monkeypatch.setattr(cfd, "RUNS_DIR", tmp_path / "runs")
    raw = Design.load(simulator.DEFAULT_PRESET).model_dump(by_alias=True, mode="json")
    raw["ventilation"]["velocity_range_ms"] = [9.0, 10.5]
    wide = Design.from_dict(raw)
    at = AppTest.from_file(APP, default_timeout=180)
    at.session_state["design"] = wide
    at.run()
    assert not at.exception
    assert at.session_state["design"] == wide
    assert at.sidebar.slider(key="sim_velocity").value == (9.0, 10.5)


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


def _slider_values(at: AppTest) -> dict:
    return {s.key: s.value for s in at.sidebar.slider}


def _expected_slider_values(design: Design) -> dict:
    raw = design.model_dump(by_alias=True, mode="json")
    values = {s.key: simulator._current(design, raw, s) for s in simulator.SLIDERS}
    lo, hi = simulator._get(raw, simulator.VELOCITY_PATH)
    values[simulator.VELOCITY_KEY] = (float(lo), float(hi))
    return values


@pytest.mark.parametrize("away", ["nav_wizard", "nav_runs"])
def test_returning_to_the_simulator_does_not_crash_or_corrupt_the_design(
        monkeypatch, tmp_path, away):
    """C-1: Streamlit deletes a keyed widget's state at the end of any run that does
    not render it, so the velocity slider has no state by the time the simulator
    renders again -- and, unfixed, `_seed` is skipped because `_SEEDED_FROM` (a plain
    key) survives and still equals the unchanged design. Reproduced for every way
    back: the top-level nav, the sidebar's own "Open the wizard" button, and the
    runs manager."""
    monkeypatch.delenv("SOLIT2_RUN_ROOTS", raising=False)
    at = _app(monkeypatch, tmp_path)
    design = at.session_state["design"]
    at.button(key=away).click().run()
    assert not at.exception
    at.button(key="nav_simulator").click().run()
    assert not at.exception, [str(e.value) for e in at.exception]
    assert at.session_state["design"] == design
    assert _slider_values(at) == _expected_slider_values(design)


def test_returning_via_the_sidebars_open_the_wizard_button_does_not_crash(
        monkeypatch, tmp_path):
    """The third way back (see C-1 above): the sidebar's own button, not the header nav."""
    at = _app(monkeypatch, tmp_path)
    design = at.session_state["design"]
    at.sidebar.button(key="sim_open_wizard").click().run()
    assert not at.exception
    at.button(key="nav_simulator").click().run()
    assert not at.exception, [str(e.value) for e in at.exception]
    assert at.session_state["design"] == design
    assert _slider_values(at) == _expected_slider_values(design)


def test_a_preset_that_fails_to_load_reports_the_file_and_reason_and_keeps_the_design(
        monkeypatch, tmp_path):
    """M-4: `_presets()` used to mark the pill applied BEFORE the unguarded
    `Design.load`, so a schema-invalid file left a traceback and the pill marked
    on the OLD design. It must load first, and only mark the preset applied on
    success."""
    bad = tmp_path / "bad.json"
    bad.write_text("{}")   # valid JSON, not a valid Design: fails schema validation
    monkeypatch.setattr(simulator, "preset_files", lambda: [bad])
    at = _app(monkeypatch, tmp_path)
    before = at.session_state["design"]
    at.session_state["sim_preset"] = "bad"
    at.run()
    assert not at.exception
    assert any(str(bad) in e.value for e in at.error)
    assert at.session_state["design"] == before
    assert at.session_state.get(simulator._APPLIED_PRESET) != "bad"
    # A later rerun with nothing changed must not get stuck retrying silently --
    # the pill stays selectable and the same error is reported again.
    at.run()
    assert any(str(bad) in e.value for e in at.error)


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

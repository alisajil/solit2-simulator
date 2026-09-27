"""The landing screen, headless: the Annex 7 test of the tester's system, live."""
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app.components import readings
from app.views import cfd, simulator
from solit2 import history
from solit2.engines.fds import deck
from solit2.reports import twin
from solit2.schema.design import Design
from tests.conftest import PROTOCOL_DESIGN, sign_in

APP = "../app/streamlit_app.py"
# TEST VALUES, NOT DATA: the conditions Annex 7 leaves to the AHJ or the test day.
INPUTS = twin.Annex7Inputs("A", activation_s=150.0, ambient_c=20.0, ambient_rh_pct=60.0,
                           growth_alpha_kw_s2=0.1876, incubation_s=243.0)


def _bare(monkeypatch, tmp_path) -> AppTest:
    monkeypatch.setattr(history, "DEFAULT_PATH", tmp_path / "h.jsonl")
    monkeypatch.setattr(cfd, "RUNS_DIR", tmp_path / "runs")
    at = AppTest.from_file(APP, default_timeout=180)
    sign_in(at)
    return at


def _app(monkeypatch, tmp_path, inputs: twin.Annex7Inputs | None = INPUTS) -> AppTest:
    """The landing screen with a system to test and, by default, its Annex 7 inputs."""
    at = _bare(monkeypatch, tmp_path)
    at.session_state["design"] = Design.load(PROTOCOL_DESIGN)
    if inputs is not None:
        at.session_state["annex7_inputs"] = inputs
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


def test_with_no_system_nothing_is_loaded_and_the_tester_is_asked_for_one(monkeypatch, tmp_path):
    """The landing used to load an example protocol with the template head and run
    it as if it were the system under test."""
    at = _bare(monkeypatch, tmp_path)
    at.run()
    assert not at.exception
    assert at.session_state["design"] is None if "design" in at.session_state else True
    assert "twin_result" not in at.session_state and "result" not in at.session_state
    assert any("No system to test yet" in i.value for i in at.info)
    at.button(key="sim_open_design").click().run()
    assert at.session_state["view"] == "wizard" and at.session_state["step"] == 1


def test_only_the_testers_own_design_files_are_offered():
    assert simulator.PRESET_ROOTS == (Path("designs"),)
    assert not any("examples" in str(p) for p in simulator.preset_files())


def test_it_runs_the_annex7_test_of_the_system_not_the_design_as_it_stands(
        monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    result = at.session_state["twin_result"]
    assert result.meta["design_name"].endswith("-annex7-class-a")
    assert "result" not in at.session_state, "the site run is the wizard's, not this screen's"
    assert not [s for s in at.sidebar.slider if s.key == "sim_velocity"], \
        "Annex 7 fixes both velocities; there is no knob for them"


def test_the_annex7_conditions_are_shown_and_no_assumed_protocol(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    shown = " ".join(c.value for c in at.sidebar.caption)
    assert "manual activation 150 s after ignition" in shown
    assert "1.5 and 3 m/s" in shown and "gallery 20 °C, 60 % RH" in shown
    assert "activation delay" not in shown and "detector" not in shown


def test_without_annex7_inputs_nothing_is_run_and_they_are_asked_for(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path, inputs=None)
    assert not at.exception
    assert "twin_result" not in at.session_state
    assert at.number_input(key="a7_activation").value is None
    assert any("Enter the Annex 7 test inputs" in i.value for i in at.info)


def test_inputs_entered_on_either_view_come_back_on_the_other(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    assert at.number_input(key="a7_activation").value == 150.0
    assert at.radio(key="a7_class").value == "A"


def test_the_fire_class_chip_is_neutral_not_unset(monkeypatch, tmp_path):
    """M-9: amber ("unset") means "not judged" in this app; the fire class is
    descriptive, not a criterion, so it must not borrow that meaning."""
    at = _app(monkeypatch, tmp_path)
    assert 'chip neutral">Class' in _text(at)
    assert 'chip unset">Class' not in _text(at)


def test_the_tiles_show_the_results_own_peaks(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    result = at.session_state["twin_result"]
    assert f"{result.peaks['hrr_mw']:.1f} MW" in _text(at)
    assert f"free burn {result.peaks['hrr_free_burn_mw']:.1f} MW" in _text(at)


def test_judged_elsewhere_is_shown_under_the_figure(monkeypatch, tmp_path):
    """I-1: the protocol design's Annex 7 twin already disagrees -- heat flux peaks
    at one velocity while the figure replays the worst case at the other, so the
    gauge alone would look clear."""
    at = _app(monkeypatch, tmp_path)
    text = _text(at)
    assert "Judged elsewhere" in text


def test_the_calibration_note_is_on_screen(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    note = at.session_state["twin_result"].meta["calibration_note"]
    assert any(note in c.value for c in at.caption)


def test_moving_a_slider_rebuilds_the_design_and_reruns_the_engine(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    before = at.session_state["twin_result"].meta["design_sha"]
    before_tiles = readings.tiles(at.session_state["twin_result"])
    at.sidebar.slider(key="sim_pressure").set_value(60.0).run()
    assert not at.exception
    assert at.session_state["design"].nozzles.pressure_bar == 60.0
    assert at.session_state["twin_result"].meta["design_sha"] != before
    # M-10: a slider that changes the design must change what the tiles show, not
    # just what is stored in session state.
    assert readings.tiles(at.session_state["twin_result"]) != before_tiles


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


def test_the_simulator_never_records_to_history(monkeypatch, tmp_path):
    """I-3: the simulator makes one Tier 1 run per slider release, and would flood
    `runs/history.jsonl` (and its leaderboard) if it recorded every one of them --
    only the wizard's own Result step records a considered design."""
    history_path = tmp_path / "h.jsonl"
    at = _app(monkeypatch, tmp_path)
    assert not at.exception
    assert not history_path.exists()
    at.sidebar.slider(key="sim_pressure").set_value(61.0).run()
    assert not at.exception
    assert not history_path.exists()


def test_a_preset_loads_that_design_file(monkeypatch, tmp_path):
    path = Path("examples/designs/solit2-test-protocol-class-b.json")
    monkeypatch.setattr(simulator, "preset_files", lambda: [path])
    at = _app(monkeypatch, tmp_path)
    at.session_state["sim_preset"] = path.stem
    at.run()
    assert at.session_state["design"] == Design.load(path)


def _slider_values(at: AppTest) -> dict:
    return {s.key: s.value for s in at.sidebar.slider}


def _expected_slider_values(design: Design) -> dict:
    raw = design.model_dump(by_alias=True, mode="json")
    return {s.key: simulator._current(design, raw, s) for s in simulator.SLIDERS}


@pytest.mark.parametrize("away", ["nav_wizard", "nav_runs"])
def test_returning_to_the_simulator_does_not_crash_or_corrupt_the_design(
        monkeypatch, tmp_path, away):
    """C-1: Streamlit deletes a keyed widget's state at the end of any run that does
    not render it, so no slider has state by the time the simulator renders
    again -- and, unfixed, `_seed` is skipped because `_SEEDED_FROM` (a plain
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
    design = at.session_state["design"]
    at.sidebar.button(key="sim_open_wizard").click().run()
    assert at.session_state["view"] == "wizard"
    assert at.session_state["step"] == 2
    assert at.session_state["design"] == design
    assert at.session_state["result"].meta["design_name"] == design.meta.name


def test_the_cfd_panel_says_when_no_run_exists(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    assert any("CFD not run for this design" in c.value for c in at.caption)


def test_set_up_a_cfd_run_opens_the_wizards_cfd_step(monkeypatch, tmp_path):
    """M-7: the panel's own button, reachable only when no run exists yet."""
    at = _app(monkeypatch, tmp_path)
    assert at.button(key="sim_open_cfd")
    at.button(key="sim_open_cfd").click().run()
    assert not at.exception
    assert at.session_state["view"] == "wizard"
    assert at.session_state["step"] == 4


def test_the_cfd_panel_reads_a_run_of_this_design(monkeypatch, tmp_path):
    """M-7: the fixture really yields state `running` at progress 0.1 -- the old
    test only asserted a `Simulated` metric label exists, which is always true
    (its own value is "--" here); assert the chip and the progress it actually
    reads instead."""
    chid = deck.chid(Design.load(PROTOCOL_DESIGN))
    run_dir = tmp_path / "runs" / chid
    run_dir.mkdir(parents=True)
    (run_dir / "deck.fds").write_text(f"&HEAD CHID='{chid}' /\n&TIME T_END=1200.0 /\n")
    (run_dir / f"{chid}.out").write_text("Time Step 10\n Total Time:  120.0 s\n")
    at = _app(monkeypatch, tmp_path)
    assert not at.exception
    assert any(m.label == "Simulated" for m in at.metric)
    assert '<span class="chip unset">running</span>' in _text(at)
    progress = at.get("progress")
    assert progress and progress[0].proto.value == 10   # 0.1 of T_END, on a 0-100 scale


def test_opening_the_wizard_from_the_simulator_records_that_design_once(monkeypatch, tmp_path):
    """The wizard's Result step must record the design exactly once, even though
    the simulator cached it with record=False. This test verifies that opening
    the wizard from the simulator via the sidebar button records the design."""
    import json
    history_path = tmp_path / "h.jsonl"
    at = _app(monkeypatch, tmp_path)
    assert not at.exception
    # History file should not exist yet (simulator never records)
    assert not history_path.exists()
    # Click "Open the wizard" button
    at.sidebar.button(key="sim_open_wizard").click().run()
    assert not at.exception
    design_sha = at.session_state["result"].meta["design_sha"]
    # Now history file should exist with exactly one line
    assert history_path.exists()
    lines = history_path.read_text().splitlines()
    assert len(lines) == 1, f"Expected 1 history line, got {len(lines)}"
    # The recorded design_sha should match
    row = json.loads(lines[0])
    assert row["design_sha"] == design_sha


def test_revisiting_the_result_step_does_not_record_twice(monkeypatch, tmp_path):
    """After opening the wizard from the simulator and recording the design,
    a second run of the Result step should not record it again."""
    import json
    history_path = tmp_path / "h.jsonl"
    at = _app(monkeypatch, tmp_path)
    # Open wizard and record
    at.sidebar.button(key="sim_open_wizard").click().run()
    assert not at.exception
    design_sha = at.session_state["result"].meta["design_sha"]
    assert len(history_path.read_text().splitlines()) == 1
    # Trigger another run of the Result step (still on result step)
    at.run()
    assert not at.exception
    # History should still have exactly one line for this design
    lines = history_path.read_text().splitlines()
    assert len(lines) == 1, f"Expected 1 history line after re-run, got {len(lines)}"
    row = json.loads(lines[0])
    assert row["design_sha"] == design_sha

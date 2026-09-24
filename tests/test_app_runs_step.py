"""No FDS is assumed and no real run is launched: fleet/runner/scheduler are
stubbed at the module boundary, the way test_app_cfd_step.py stubs runner
for the CFD step.
"""
from streamlit.testing.v1 import AppTest

from app.views import runs
from solit2.engines.fds import fleet
from solit2.engines.fds import runner as runner_mod

APP = "../app/streamlit_app.py"


def _app(monkeypatch, tmp_path, roots=None) -> AppTest:
    monkeypatch.setenv("SOLIT2_CFD_STATE_DIR", str(tmp_path / "state"))
    if roots is None:
        monkeypatch.delenv("SOLIT2_RUN_ROOTS", raising=False)
    else:
        monkeypatch.setenv("SOLIT2_RUN_ROOTS", ":".join(str(r) for r in roots))
    at = AppTest.from_file(APP, default_timeout=180)
    at.session_state["manager_view"] = True
    at.run()
    return at


def _write_deck(run_dir, chid="c1", title="A synthetic run"):
    run_dir.mkdir(parents=True, exist_ok=True)
    (run_dir / "deck.fds").write_text(
        f"&HEAD CHID='{chid}', TITLE='{title}' /\n"
        "&MESH IJK=40,20,15, XB=-2.0,22.0,-6.0,6.0,0.0,9.0 /\n"
        "&TIME T_END=1000.0 /\n&TAIL /\n")
    return run_dir


# --- reaching the manager page ------------------------------------------------

def test_the_header_button_switches_to_the_manager_and_back(monkeypatch, tmp_path):
    monkeypatch.delenv("SOLIT2_RUN_ROOTS", raising=False)
    at = AppTest.from_file(APP, default_timeout=180)
    at.run()
    assert not at.exception
    assert at.button(key="manager_toggle").label == "CFD runs"

    at.button(key="manager_toggle").click().run()
    assert not at.exception
    assert any("CFD runs" in h.value for h in at.header)
    assert at.button(key="manager_toggle").label == "← Back to design"

    at.button(key="manager_toggle").click().run()
    assert not at.exception
    # "step" is never written to session_state until the user actually
    # navigates (see app/state.py's get_step default) -- a fresh load that
    # only toggles the manager on and off never should have written it either.
    assert at.session_state.get("step", 1) == 1, "toggling back must land on the same wizard step"


def test_switching_to_the_manager_keeps_the_current_wizard_step(monkeypatch, tmp_path):
    monkeypatch.delenv("SOLIT2_RUN_ROOTS", raising=False)
    at = AppTest.from_file(APP, default_timeout=180)
    at.run()
    at.button(key="build_design").click().run()          # -> step 2
    assert at.session_state["step"] == 2
    at.button(key="manager_toggle").click().run()
    at.button(key="manager_toggle").click().run()
    assert at.session_state["step"] == 2


# --- empty states ---------------------------------------------------------------

def test_with_no_run_roots_the_page_asks_for_one(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path, roots=None)
    assert not at.exception
    assert any("SOLIT2_RUN_ROOTS" in m.value for m in at.info)


def test_with_roots_and_no_runs_the_page_still_shows_the_core_count(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path, roots=(tmp_path / "runs",))
    assert not at.exception
    assert any("cores busy" in c.value for c in at.caption)
    assert any("No run directories" in c.value for c in at.caption)


# --- a synthetic run: counts, row, and the pause/stop confirmation gate --------

def test_a_running_run_is_counted_and_shows_its_row(monkeypatch, tmp_path):
    _write_deck(tmp_path / "runs" / "dx_0.60")
    monkeypatch.setattr(runner_mod, "status",
                        lambda d: {"state": "running", "progress": 0.4, "detail": ""})
    monkeypatch.setattr(runner_mod, "live", lambda d, t_end_s=None: {
        "time_step": 1, "simulated_s": 400.0, "t_end_s": 1000.0, "step_size_s": 0.1,
        "elapsed_s": 60.0, "rate_s_per_s": 2.0, "eta_s": 300.0, "hrr_mw": 10.0,
        "detect_s": None, "activate_s": None})

    at = _app(monkeypatch, tmp_path, roots=(tmp_path / "runs",))
    assert not at.exception
    assert any("1 running" in m.value for m in at.markdown)
    assert any("A synthetic run" in m.value for m in at.markdown)


def test_stop_opens_a_confirmation_instead_of_stopping_directly(monkeypatch, tmp_path):
    run_dir = _write_deck(tmp_path / "runs" / "dx_0.60")
    monkeypatch.setattr(runner_mod, "status",
                        lambda d: {"state": "running", "progress": 0.4, "detail": ""})
    monkeypatch.setattr(runner_mod, "live", lambda d, t_end_s=None: {
        "time_step": 1, "simulated_s": 400.0, "t_end_s": 1000.0, "step_size_s": 0.1,
        "elapsed_s": 60.0, "rate_s_per_s": 2.0, "eta_s": 300.0, "hrr_mw": 10.0,
        "detect_s": None, "activate_s": None})
    calls = []
    monkeypatch.setattr(fleet, "stop", lambda run, state_dir: calls.append(run) or True)

    at = _app(monkeypatch, tmp_path, roots=(tmp_path / "runs",))
    stop_key = f"stop_{runs._key(run_dir)}"
    assert at.button(key=stop_key)
    at.button(key=stop_key).click().run()

    assert not at.exception
    assert calls == [], "clicking Stop must open a confirmation dialog, never stop directly"


def test_pause_opens_a_confirmation_instead_of_pausing_directly(monkeypatch, tmp_path):
    run_dir = _write_deck(tmp_path / "runs" / "dx_0.60")
    monkeypatch.setattr(runner_mod, "status",
                        lambda d: {"state": "running", "progress": 0.4, "detail": ""})
    monkeypatch.setattr(runner_mod, "live", lambda d, t_end_s=None: {
        "time_step": 1, "simulated_s": 400.0, "t_end_s": 1000.0, "step_size_s": 0.1,
        "elapsed_s": 60.0, "rate_s_per_s": 2.0, "eta_s": 300.0, "hrr_mw": 10.0,
        "detect_s": None, "activate_s": None})
    calls = []
    monkeypatch.setattr(fleet, "pause", lambda run, state_dir: calls.append(run))

    at = _app(monkeypatch, tmp_path, roots=(tmp_path / "runs",))
    pause_key = f"pause_{runs._key(run_dir)}"
    at.button(key=pause_key).click().run()

    assert not at.exception
    assert calls == [], "clicking Pause must open a confirmation dialog, never pause directly"


def test_a_failed_run_shows_its_last_issue_line(monkeypatch, tmp_path):
    run_dir = _write_deck(tmp_path / "runs" / "dx_0.60")
    (run_dir / "run.out").write_text("Total Time: 10.0 s\nERROR: negative HRR\n")
    monkeypatch.setattr(runner_mod, "status",
                        lambda d: {"state": "failed", "progress": 0.1, "detail": "boom"})
    monkeypatch.setattr(runner_mod, "live", lambda d, t_end_s=None: {
        "time_step": None, "simulated_s": None, "t_end_s": None, "step_size_s": None,
        "elapsed_s": None, "rate_s_per_s": None, "eta_s": None, "hrr_mw": None,
        "detect_s": None, "activate_s": None})

    at = _app(monkeypatch, tmp_path, roots=(tmp_path / "runs",))
    assert not at.exception
    assert any("ERROR: negative HRR" in m.value for m in list(at.markdown) + list(at.caption))

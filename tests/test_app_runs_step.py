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
    at.session_state["view"] = "runs"
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

def test_the_nav_switches_to_the_manager_and_back_to_the_wizard(monkeypatch, tmp_path):
    monkeypatch.delenv("SOLIT2_RUN_ROOTS", raising=False)
    at = AppTest.from_file(APP, default_timeout=180)
    at.run()
    assert not at.exception
    assert at.button(key="nav_runs")

    at.button(key="nav_runs").click().run()
    assert not at.exception
    assert any("CFD runs" in h.value for h in at.header)
    assert at.session_state["view"] == "runs"

    at.button(key="nav_wizard").click().run()
    assert not at.exception
    # "step" is never written to session_state until the user actually
    # navigates (see app/state.py's get_step default) -- a fresh load that
    # only toggles the manager on and off never should have written it either.
    assert at.session_state.get("step", 1) == 1, "toggling back must land on the same wizard step"


def test_switching_to_the_manager_keeps_the_current_wizard_step(monkeypatch, tmp_path):
    monkeypatch.delenv("SOLIT2_RUN_ROOTS", raising=False)
    at = AppTest.from_file(APP, default_timeout=180)
    at.session_state["view"] = "wizard"
    at.run()
    at.button(key="build_design").click().run()          # -> step 2
    assert at.session_state["step"] == 2
    at.button(key="nav_runs").click().run()
    at.button(key="nav_wizard").click().run()
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
    assert at.session_state[runs._PENDING_KEY] == {"kind": "stop", "run": str(run_dir)}
    # The dialog's own buttons must actually be reachable -- I5's own
    # verified fix: they live outside the fragment (_open_pending_dialog is
    # called from render(), not from inside _live_panel), so they survive
    # exactly the rerun this .click().run() above already triggered.
    assert at.button(key="dlg_stop_yes")
    assert at.button(key="dlg_stop_no")

    at.button(key="dlg_stop_yes").click().run()

    assert not at.exception
    assert calls == [run_dir], "confirming inside the dialog must call fleet.stop exactly once"
    assert runs._PENDING_KEY not in at.session_state, "confirming must clear the pending action"


def test_stop_confirmation_cancel_clears_the_pending_action_without_stopping(monkeypatch,
                                                                             tmp_path):
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
    at.button(key=f"stop_{runs._key(run_dir)}").click().run()
    at.button(key="dlg_stop_no").click().run()

    assert not at.exception
    assert calls == [], "Cancel must never call fleet.stop"
    assert runs._PENDING_KEY not in at.session_state


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
    assert at.button(key="dlg_pause_yes")

    at.button(key="dlg_pause_yes").click().run()

    assert not at.exception
    assert calls == [run_dir], "confirming inside the dialog must call fleet.pause exactly once"


def test_confirmation_dialog_survives_a_fragment_tick(monkeypatch, tmp_path):
    """I5, the actual browser bug reproduced: a dialog opened INSIDE the
    fragment loses its buttons on the fragment's own next tick. Simulating a
    tick here is calling render() again (as the 10s auto-refresh would) with
    the pending action still in session_state, before ever clicking a dialog
    button -- the dialog must still be there and still work afterwards."""
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
    at.button(key=f"stop_{runs._key(run_dir)}").click().run()
    at.run()          # a second, unrelated rerun -- the fragment's own tick

    assert not at.exception
    assert at.button(key="dlg_stop_yes"), "the dialog must still be open and its buttons live"

    at.button(key="dlg_stop_yes").click().run()
    assert calls == [run_dir]


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

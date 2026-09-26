"""No real FDS process is ever launched: `runner.pause`/`stop`/`status`/`live`
are monkeypatched at the module boundary, exactly as `test_fds_scheduler.py`
does for the scheduler itself.
"""
import json
from pathlib import Path

import pytest

from solit2.engines.fds import fleet
from solit2.engines.fds import runner as runner_mod
from solit2.engines.fds import scheduler as scheduler_mod
from solit2.schema.design import Design

BASELINE = "designs/og-dbr-rev0.json"


def _write_deck(run_dir, *, chid="x1", title="A run", dx_m=None, extra_mesh=""):
    run_dir.mkdir(parents=True, exist_ok=True)
    mesh = extra_mesh or "&MESH IJK=40,20,15, XB=-2.0,22.0,-6.0,6.0,0.0,9.0 /\n"
    (run_dir / "deck.fds").write_text(
        f"&HEAD CHID='{chid}', TITLE='{title}' /\n"
        f"{mesh}"
        "&TIME T_END=1000.0 /\n"
        "&SURF ID='FIRE1', HRRPUA=100., E_COEFFICIENT=0.4, COLOR='RED' /\n"
        "&TAIL /\n")
    return run_dir


# --- discover() ----------------------------------------------------------------

def test_discover_finds_every_run_dir_holding_its_own_deck(tmp_path):
    a = _write_deck(tmp_path / "study" / "chid1" / "dx_0.60")
    b = _write_deck(tmp_path / "sweep" / "c4" / "e_0.400_dx_0.60")
    (tmp_path / "not_a_run").mkdir()
    found = fleet.discover((tmp_path,))
    assert set(found) == {a, b}


def test_discover_ignores_a_root_that_does_not_exist(tmp_path):
    assert fleet.discover((tmp_path / "nope",)) == []


def test_resolve_roots_splits_on_colon(monkeypatch, tmp_path):
    monkeypatch.setenv(fleet.RUN_ROOTS_ENV, f"{tmp_path}/a:{tmp_path}/b")
    assert fleet.resolve_roots() == (tmp_path / "a", tmp_path / "b")


def test_resolve_roots_is_empty_when_unset(monkeypatch):
    monkeypatch.delenv(fleet.RUN_ROOTS_ENV, raising=False)
    assert fleet.resolve_roots() == ()


# --- per-field extraction --------------------------------------------------------

def test_dx_m_reads_the_directory_name_first(tmp_path):
    run_dir = _write_deck(tmp_path / "dx_0.60")
    text = (run_dir / "deck.fds").read_text()
    assert fleet._dx_m(run_dir, text) == pytest.approx(0.60)


def test_dx_m_falls_back_to_the_first_mesh_line(tmp_path):
    run_dir = _write_deck(tmp_path / "renamed_dir")   # no dx_ in the name
    text = (run_dir / "deck.fds").read_text()
    assert fleet._dx_m(run_dir, text) == pytest.approx(0.6)


def test_title_reads_the_head_line():
    text = "&HEAD CHID='x', TITLE='My design' /\n"
    assert fleet._title(text) == "My design"


def test_title_is_none_with_no_deck_text():
    assert fleet._title(None) is None


def test_last_issue_returns_the_last_error_or_warning_line(tmp_path, monkeypatch):
    run_dir = _write_deck(tmp_path / "dx_0.60")
    (run_dir / "run.out").write_text(
        "Time Step 1\nWARNING: cell aspect ratio\nTime Step 2\nERROR: negative HRR\n")
    assert fleet._last_issue(run_dir) == "ERROR: negative HRR"


def test_last_issue_is_none_with_no_log(tmp_path):
    run_dir = tmp_path / "dx_0.60"
    run_dir.mkdir()
    assert fleet._last_issue(run_dir) is None


# --- list_runs() / summarise() ---------------------------------------------------

@pytest.fixture
def two_runs(tmp_path, monkeypatch):
    running = _write_deck(tmp_path / "runs" / "a" / "dx_0.60", chid="c1", title="Running one")
    queued = _write_deck(tmp_path / "runs" / "b" / "dx_0.60", chid="c2", title="Queued one")
    state_dir = tmp_path / "state"
    scheduler_mod.save_state(state_dir, {"0-9": str(running), "10-19": None})
    scheduler_mod.save_queue(state_dir, [str(queued)])

    def fake_status(run_dir):
        return ({"state": "running", "progress": 0.3, "detail": ""} if run_dir == running
               else {"state": "failed", "progress": 0.0, "detail": "no log"})

    def fake_live(run_dir, t_end_s=None):
        return {"time_step": 10, "simulated_s": 300.0, "t_end_s": 1000.0, "step_size_s": 0.1,
               "elapsed_s": 60.0, "rate_s_per_s": 5.0, "eta_s": 140.0, "hrr_mw": 10.0,
               "detect_s": None, "activate_s": None}

    monkeypatch.setattr(runner_mod, "status", fake_status)
    monkeypatch.setattr(runner_mod, "live", fake_live)
    return running, queued, state_dir


def test_list_runs_reports_core_block_and_queue_position(two_runs, tmp_path):
    running, queued, state_dir = two_runs
    infos = fleet.list_runs(roots=(tmp_path / "runs",), state_dir=state_dir,
                            blocks=("0-9", "10-19"))
    by_path = {i.path: i for i in infos}
    assert by_path[running].core_block == "0-9"
    assert by_path[running].queue_position is None
    assert by_path[queued].core_block is None
    assert by_path[queued].queue_position == 0


def test_list_runs_reads_title_dx_and_e_coefficient(two_runs, tmp_path):
    running, queued, state_dir = two_runs
    infos = fleet.list_runs(roots=(tmp_path / "runs",), state_dir=state_dir,
                            blocks=("0-9", "10-19"))
    by_path = {i.path: i for i in infos}
    assert by_path[running].title == "Running one"
    assert by_path[running].chid == "c1"
    assert by_path[running].dx_m == pytest.approx(0.60)
    assert by_path[running].e_coefficient == pytest.approx(0.4)


def test_list_runs_never_invents_a_rate_when_live_has_none(tmp_path, monkeypatch):
    _write_deck(tmp_path / "dx_0.60")
    monkeypatch.setattr(runner_mod, "status", lambda d: {"state": "running", "progress": 0.1,
                                                          "detail": ""})
    monkeypatch.setattr(runner_mod, "live", lambda d, t_end_s=None: {
        "time_step": None, "simulated_s": None, "t_end_s": None, "step_size_s": None,
        "elapsed_s": None, "rate_s_per_s": None, "eta_s": None, "hrr_mw": None,
        "detect_s": None, "activate_s": None})
    info = fleet.list_runs(roots=(tmp_path,), state_dir=tmp_path / "state",
                           blocks=("0-9",))[0]
    assert info.rate_s_per_s is None
    assert info.eta_s is None
    assert info.eta_ist is None


def test_list_runs_hides_the_rate_and_eta_of_a_paused_run(tmp_path, monkeypatch):
    """I4: a rate or an ETA is a claim about something advancing right now --
    showing the last one a paused/failed/done run happened to have read as a
    forecast of a future that is not going to happen."""
    _write_deck(tmp_path / "dx_0.60")
    monkeypatch.setattr(runner_mod, "status", lambda d: {"state": "paused", "progress": 0.3,
                                                          "detail": ""})
    monkeypatch.setattr(runner_mod, "live", lambda d, t_end_s=None: {
        "time_step": 10, "simulated_s": 300.0, "t_end_s": 1000.0, "step_size_s": 0.1,
        "elapsed_s": 60.0, "rate_s_per_s": 5.0, "eta_s": 140.0, "hrr_mw": 10.0,
        "detect_s": None, "activate_s": None})
    info = fleet.list_runs(roots=(tmp_path,), state_dir=tmp_path / "state",
                           blocks=("0-9",))[0]
    assert info.rate_s_per_s is None
    assert info.eta_s is None
    assert info.eta_ist is None
    # simulated_s / t_end_s are NOT hidden -- "how far did it get" is a fact
    # about the past, not a forecast, and stays true after the run stops.
    assert info.simulated_s == 300.0


def test_list_runs_reports_pending_for_an_unlaunched_deck(tmp_path):
    _write_deck(tmp_path / "dx_0.60")   # deck.fds only -- no run.out, never launched
    info = fleet.list_runs(roots=(tmp_path,), state_dir=tmp_path / "state",
                           blocks=("0-9",))[0]
    assert info.state == "pending"


def test_block_width_reads_a_lo_hi_range():
    assert fleet._block_width("0-9") == 10
    assert fleet._block_width("10-19") == 10
    assert fleet._block_width("20-29") == 10


def test_summarise_counts_cores_as_block_widths_not_block_counts(tmp_path):
    state_dir = tmp_path / "state"
    scheduler_mod.save_state(state_dir, {"0-9": "runs/a", "10-19": None, "20-39": None})
    summary = fleet.summarise([], state_dir=state_dir, blocks=("0-9", "10-19", "20-39"))
    assert summary.cores_total == 10 + 10 + 20
    assert summary.cores_busy == 10


def test_summarise_counts_an_unmanaged_running_deck_by_its_mesh_count(tmp_path, monkeypatch):
    """A run the web app launched unpinned (app/views/cfd.py) occupies real
    cores that no scheduler block accounts for -- it must still count."""
    _write_deck(tmp_path / "runs" / "unpinned",
               extra_mesh="&MESH IJK=1,1,1, XB=0,1,0,1,0,1 /\n"
                         "&MESH IJK=1,1,1, XB=1,2,0,1,0,1 /\n"
                         "&MESH IJK=1,1,1, XB=2,3,0,1,0,1 /\n")
    state_dir = tmp_path / "state"
    monkeypatch.setattr(runner_mod, "status", lambda d: {"state": "running", "progress": 0.1,
                                                          "detail": ""})
    monkeypatch.setattr(runner_mod, "live", lambda d, t_end_s=None: {
        "time_step": 1, "simulated_s": 1.0, "t_end_s": 10.0, "step_size_s": 0.1,
        "elapsed_s": 1.0, "rate_s_per_s": 1.0, "eta_s": 9.0, "hrr_mw": 1.0,
        "detect_s": None, "activate_s": None})
    infos = fleet.list_runs(roots=(tmp_path / "runs",), state_dir=state_dir, blocks=("0-9",))
    summary = fleet.summarise(infos, state_dir=state_dir, blocks=("0-9",))
    assert summary.cores_busy == 3, "three &MESH lines -- one rank each"


def test_summarise_counts_by_state_and_reports_cores(two_runs, tmp_path):
    running, queued, state_dir = two_runs
    infos = fleet.list_runs(roots=(tmp_path / "runs",), state_dir=state_dir,
                            blocks=("0-9", "10-19"))
    summary = fleet.summarise(infos, state_dir=state_dir, blocks=("0-9", "10-19"))
    assert summary.running == 1
    assert summary.failed_or_stopped == 1
    assert summary.cores_busy == 10, "block width (0-9 = 10 cores), not a block count"
    assert summary.cores_total == 20, "0-9 and 10-19 together, 10 cores each"
    assert summary.scheduler_running is False


def test_summarise_reports_a_live_scheduler(two_runs, tmp_path):
    import os
    running, queued, state_dir = two_runs
    (state_dir / scheduler_mod.PID_NAME).write_text(str(os.getpid()))
    summary = fleet.summarise([], state_dir=state_dir, blocks=("0-9", "10-19"))
    assert summary.scheduler_running is True


def test_to_json_stringifies_the_path(two_runs, tmp_path):
    running, queued, state_dir = two_runs
    infos = fleet.list_runs(roots=(tmp_path / "runs",), state_dir=state_dir,
                            blocks=("0-9", "10-19"))
    rows = fleet.to_json(infos)
    assert all(isinstance(r["path"], str) for r in rows)


def test_render_status_lists_every_run_and_the_core_summary(two_runs, tmp_path):
    running, queued, state_dir = two_runs
    infos = fleet.list_runs(roots=(tmp_path / "runs",), state_dir=state_dir,
                            blocks=("0-9", "10-19"))
    summary = fleet.summarise(infos, state_dir=state_dir, blocks=("0-9", "10-19"))
    text = fleet.render_status(infos, summary)
    assert "10 of 20 cores busy" in text
    assert str(running) in text and str(queued) in text


def test_render_status_with_no_runs_says_so():
    summary = fleet.FleetSummary(0, 0, 0, 0, 0, 3, False)
    assert "no run directories" in fleet.render_status([], summary)


# --- actions: pause / stop -------------------------------------------------------

def test_pause_calls_runner_and_logs_ok(tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(runner_mod, "pause", lambda d: calls.append(d) or (d / "x.stop"))
    fleet.pause(tmp_path / "run", tmp_path / "state")
    assert calls == [tmp_path / "run"]
    row = json.loads((tmp_path / "state" / fleet.ACTIONS_LOG_NAME).read_text().splitlines()[0])
    assert row["action"] == "pause" and row["outcome"] == "ok"
    assert row["timestamp"].endswith("+05:30"), "the audit trail must be IST-stamped, not naive"


def test_pause_logs_the_failure_and_reraises(tmp_path, monkeypatch):
    def boom(d):
        raise FileNotFoundError("no deck.fds")
    monkeypatch.setattr(runner_mod, "pause", boom)
    with pytest.raises(FileNotFoundError):
        fleet.pause(tmp_path / "run", tmp_path / "state")
    row = json.loads((tmp_path / "state" / fleet.ACTIONS_LOG_NAME).read_text().splitlines()[0])
    assert row["action"] == "pause" and row["outcome"].startswith("failed:")


def test_stop_calls_runner_and_logs_ok(tmp_path, monkeypatch):
    monkeypatch.setattr(runner_mod, "stop", lambda d: True)
    killed = fleet.stop(tmp_path / "run", tmp_path / "state")
    assert killed is True
    row = json.loads((tmp_path / "state" / fleet.ACTIONS_LOG_NAME).read_text().splitlines()[0])
    assert row["action"] == "stop" and "ok" in row["outcome"]


# --- queue actions: enqueue / dequeue / move --------------------------------------

def test_enqueue_appends_by_default(tmp_path):
    tmp_path = tmp_path.resolve()      # I8: enqueue() resolves; compare against the same form
    a, b = _write_deck(tmp_path / "run" / "a"), _write_deck(tmp_path / "run" / "b")
    fleet.enqueue(a, tmp_path / "state")
    fleet.enqueue(b, tmp_path / "state")
    assert scheduler_mod.load_queue(tmp_path / "state") == [str(a), str(b)]


def test_enqueue_clears_an_existing_failure_count(tmp_path):
    """I6: a human choosing to re-enqueue this run is a deliberate "try it
    again" -- the strikes from before must not carry over and put it one
    poll from being skipped in place, or already there."""
    run_dir = _write_deck(tmp_path / "run")
    scheduler_mod._record_failure(run_dir)
    scheduler_mod._record_failure(run_dir)
    fleet.enqueue(run_dir, tmp_path / "state")
    assert scheduler_mod._failure_count(run_dir) == 0


def test_enqueue_never_duplicates_an_entry(tmp_path):
    tmp_path = tmp_path.resolve()
    run = _write_deck(tmp_path / "run" / "a")
    fleet.enqueue(run, tmp_path / "state")
    fleet.enqueue(run, tmp_path / "state")
    assert scheduler_mod.load_queue(tmp_path / "state") == [str(run)]


def test_enqueue_at_a_position_inserts_there(tmp_path):
    tmp_path = tmp_path.resolve()
    state_dir = tmp_path / "state"
    a, b, c = (_write_deck(tmp_path / n) for n in "abc")
    fleet.enqueue(a, state_dir)
    fleet.enqueue(b, state_dir)
    fleet.enqueue(c, state_dir, position=1)
    assert scheduler_mod.load_queue(state_dir) == [str(a), str(c), str(b)]


def test_enqueue_resolves_a_relative_path_and_requires_a_deck(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    run_dir = _write_deck(tmp_path / "runs" / "x")
    fleet.enqueue(Path("runs") / "x", tmp_path / "state")
    assert scheduler_mod.load_queue(tmp_path / "state") == [str(run_dir.resolve())]


def test_enqueue_refuses_a_directory_with_no_deck(tmp_path):
    with pytest.raises(FileNotFoundError, match="deck.fds"):
        fleet.enqueue(tmp_path / "empty", tmp_path / "state")


def test_dequeue_removes_an_entry(tmp_path):
    state_dir = tmp_path / "state"
    a = _write_deck(tmp_path / "a")
    fleet.enqueue(a, state_dir)
    fleet.dequeue(a, state_dir)
    assert scheduler_mod.load_queue(state_dir) == []


def test_dequeue_refuses_an_entry_not_in_the_queue(tmp_path):
    with pytest.raises(ValueError, match="not in the queue"):
        fleet.dequeue(tmp_path / "a", tmp_path / "state")


def test_move_reorders_and_clamps_the_position(tmp_path):
    tmp_path = tmp_path.resolve()
    state_dir = tmp_path / "state"
    a, b, c = (_write_deck(tmp_path / n) for n in "abc")
    for run in (a, b, c):
        fleet.enqueue(run, state_dir)
    fleet.move(c, state_dir, 0)
    assert scheduler_mod.load_queue(state_dir) == [str(c), str(a), str(b)]
    fleet.move(c, state_dir, 999)
    assert scheduler_mod.load_queue(state_dir)[-1] == str(c)


def test_move_refuses_an_entry_not_in_the_queue(tmp_path):
    with pytest.raises(ValueError, match="not in the queue"):
        fleet.move(tmp_path / "a", tmp_path / "state", 0)


def test_every_queue_action_writes_an_audit_line(tmp_path):
    state_dir = tmp_path / "state"
    a = _write_deck(tmp_path / "a")
    fleet.enqueue(a, state_dir)
    fleet.move(a, state_dir, 0)
    fleet.dequeue(a, state_dir)
    rows = [json.loads(ln) for ln in (state_dir / fleet.ACTIONS_LOG_NAME).read_text().splitlines()]
    assert [r["action"] for r in rows] == ["enqueue", "move", "dequeue"]
    assert all(r["outcome"] == "ok" or r["outcome"].startswith("ok") for r in rows)


# --- resume() ---------------------------------------------------------------------

def test_resume_refuses_without_restart_files(tmp_path, monkeypatch):
    monkeypatch.setattr(runner_mod, "has_restart_files", lambda d: False)
    with pytest.raises(FileNotFoundError, match="no restart files"):
        fleet.resume(tmp_path / "run", tmp_path / "state")


def test_resume_refuses_without_design_json(tmp_path, monkeypatch):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    monkeypatch.setattr(runner_mod, "has_restart_files", lambda d: True)
    with pytest.raises(FileNotFoundError, match=scheduler_mod.DESIGN_NAME):
        fleet.resume(run_dir, tmp_path / "state")


def test_resume_enqueues_when_restart_files_and_design_are_present(tmp_path, monkeypatch):
    tmp_path = tmp_path.resolve()
    run_dir = _write_deck(tmp_path / "run")
    (run_dir / scheduler_mod.DESIGN_NAME).write_text(
        Design.load(BASELINE).model_dump_json(by_alias=True))
    monkeypatch.setattr(runner_mod, "has_restart_files", lambda d: True)
    fleet.resume(run_dir, tmp_path / "state")
    assert scheduler_mod.load_queue(tmp_path / "state") == [str(run_dir)]
    rows = [json.loads(ln)
            for ln in (tmp_path / "state" / fleet.ACTIONS_LOG_NAME).read_text().splitlines()]
    assert rows[-1]["action"] == "resume" and rows[-1]["outcome"] == "enqueued"


def test_resume_refuses_a_directory_that_already_has_a_live_process(tmp_path, monkeypatch):
    """C2: even with restart files and design.json both present, resuming a
    directory that is ALREADY running would launch a second FDS on top of
    the first."""
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / scheduler_mod.DESIGN_NAME).write_text(
        Design.load(BASELINE).model_dump_json(by_alias=True))
    monkeypatch.setattr(runner_mod, "has_restart_files", lambda d: True)
    monkeypatch.setattr(runner_mod, "_launcher_alive", lambda d: True)
    with pytest.raises(ValueError, match="already has a live process"):
        fleet.resume(run_dir, tmp_path / "state")
    assert scheduler_mod.load_queue(tmp_path / "state") == []
    rows = [json.loads(ln)
            for ln in (tmp_path / "state" / fleet.ACTIONS_LOG_NAME).read_text().splitlines()]
    assert rows[-1]["outcome"] == "failed: already running"


def test_enqueue_refuses_a_directory_that_already_has_a_live_process(tmp_path, monkeypatch):
    run_dir = _write_deck(tmp_path / "run")
    monkeypatch.setattr(runner_mod, "_launcher_alive", lambda d: True)
    with pytest.raises(ValueError, match="already has a live process"):
        fleet.enqueue(run_dir, tmp_path / "state")
    assert scheduler_mod.load_queue(tmp_path / "state") == []


# --- adopt_design() ----------------------------------------------------------------

def test_adopt_design_writes_design_json(tmp_path):
    run_dir = _write_deck(tmp_path / "dx_0.60")
    design = Design.load(BASELINE)
    path = fleet.adopt_design(run_dir, design)
    assert path == run_dir / scheduler_mod.DESIGN_NAME
    assert Design.load(path) == design


def test_adopt_design_refuses_a_directory_with_no_deck(tmp_path):
    with pytest.raises(FileNotFoundError, match="deck.fds"):
        fleet.adopt_design(tmp_path / "empty", Design.load(BASELINE))

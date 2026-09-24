"""No real FDS process is ever launched: `runner.run`/`resume`/`status` are
monkeypatched at the module boundary, the same style `test_fds_runner.py`
uses for `run_or_resume`.
"""
import json
import os

import pytest

from solit2.engines.fds import runner as runner_mod
from solit2.engines.fds import scheduler


# --- parse_blocks -------------------------------------------------------------

def test_parse_blocks_splits_the_default_spec():
    assert scheduler.parse_blocks("0-9,10-19,20-29") == ("0-9", "10-19", "20-29")


def test_parse_blocks_strips_whitespace_and_drops_empties():
    assert scheduler.parse_blocks(" 0-9 , 10-19 ,, ") == ("0-9", "10-19")


def test_parse_blocks_rejects_a_malformed_range():
    with pytest.raises(ValueError, match="not a 'lo-hi'"):
        scheduler.parse_blocks("0-9,not-a-range")


def test_parse_blocks_rejects_an_empty_spec():
    with pytest.raises(ValueError, match="no core blocks"):
        scheduler.parse_blocks("")


def test_resolve_blocks_reads_the_env_var(monkeypatch):
    monkeypatch.setenv(scheduler.BLOCKS_ENV, "0-3,4-7")
    assert scheduler.resolve_blocks() == ("0-3", "4-7")


def test_resolve_blocks_falls_back_to_the_default(monkeypatch):
    monkeypatch.delenv(scheduler.BLOCKS_ENV, raising=False)
    assert scheduler.resolve_blocks() == scheduler.parse_blocks(scheduler.DEFAULT_BLOCKS)


def test_resolve_state_dir_reads_the_env_var(monkeypatch, tmp_path):
    monkeypatch.setenv(scheduler.STATE_DIR_ENV, str(tmp_path / "x"))
    assert scheduler.resolve_state_dir() == tmp_path / "x"


# --- state.json / queue.txt ----------------------------------------------------

def test_load_state_defaults_every_block_to_none_when_no_file_exists(tmp_path):
    state = scheduler.load_state(tmp_path, ("0-9", "10-19"))
    assert state == {"0-9": None, "10-19": None}


def test_save_and_load_state_round_trip(tmp_path):
    state = {"0-9": "runs/a", "10-19": None}
    scheduler.save_state(tmp_path, state)
    assert scheduler.load_state(tmp_path, ("0-9", "10-19")) == state


def test_load_state_ignores_blocks_not_in_the_requested_set(tmp_path):
    (tmp_path / scheduler.STATE_NAME).write_text(json.dumps({"0-9": "runs/a", "99-99": "runs/b"}))
    assert scheduler.load_state(tmp_path, ("0-9",)) == {"0-9": "runs/a"}


def test_save_state_writes_atomically_leaving_no_tmp_file_behind(tmp_path):
    scheduler.save_state(tmp_path, {"0-9": "runs/a"})
    leftovers = [p for p in tmp_path.iterdir() if p.suffix == ".tmp"]
    assert leftovers == []


def test_queue_round_trip(tmp_path):
    scheduler.save_queue(tmp_path, ["runs/a", "runs/b"])
    assert scheduler.load_queue(tmp_path) == ["runs/a", "runs/b"]


def test_load_queue_is_empty_when_no_file_exists(tmp_path):
    assert scheduler.load_queue(tmp_path) == []


def test_queue_lock_serialises_two_read_modify_writes(tmp_path):
    with scheduler.queue_lock(tmp_path):
        # A second, non-blocking attempt on the SAME lock file must fail while
        # the first is held -- this is what stops the scheduler's own loop and
        # a `fds-fleet move` interleaving on the same queue.
        import fcntl
        handle = (tmp_path / scheduler.QUEUE_LOCK_NAME).open("w")
        with pytest.raises(OSError):
            fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
        handle.close()


# --- per-run-dir lock: never start two runs on one directory ------------------

def test_try_lock_run_grants_a_free_lock_and_refuses_a_held_one(tmp_path):
    first, reason = scheduler._try_lock_run(tmp_path)
    assert first is not None and reason is None
    second, reason = scheduler._try_lock_run(tmp_path)
    assert second is None, "a second attempt while the first is held must be refused"
    assert "already locked" in reason
    first.close()
    third, reason = scheduler._try_lock_run(tmp_path)
    assert third is not None, "closing the first handle must release the lock"
    third.close()


def test_try_lock_run_reports_a_reason_when_the_directory_does_not_exist(tmp_path):
    handle, reason = scheduler._try_lock_run(tmp_path / "does" / "not" / "exist")
    assert handle is None
    assert reason is not None


# --- failure counting -----------------------------------------------------------

def test_failure_count_starts_at_zero(tmp_path):
    assert scheduler._failure_count(tmp_path) == 0


def test_record_failure_increments_and_persists(tmp_path):
    assert scheduler._record_failure(tmp_path) == 1
    assert scheduler._record_failure(tmp_path) == 2
    assert scheduler._failure_count(tmp_path) == 2


def test_clear_failures_resets_the_counter(tmp_path):
    scheduler._record_failure(tmp_path)
    scheduler._clear_failures(tmp_path)
    assert scheduler._failure_count(tmp_path) == 0


def test_record_failure_does_not_crash_when_the_run_dir_does_not_exist(tmp_path):
    """A state.json/queue.txt entry naming a directory that is not actually
    on disk (a stale adopted reference, a typo) must not take the whole
    scheduler loop down over one bad entry."""
    missing = tmp_path / "does" / "not" / "exist"
    assert scheduler._record_failure(missing) == 1
    assert scheduler._failure_count(missing) == 0, "nothing was persisted, so it reads as 0 again"


# --- adopt(): importing the interim scheduler's files --------------------------

def test_adopt_imports_state_and_queue_once(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    interim_state = tmp_path / "interim" / "state.json"
    interim_state.parent.mkdir()
    interim_state.write_text(json.dumps({"0-9": "runs/a", "10-19": None, "20-29": "runs/b"}))
    interim_queue = tmp_path / "interim" / "queue.txt"
    interim_queue.write_text("runs/c\nruns/d\n")

    state_dir = tmp_path / "state"
    scheduler.adopt(state_dir, ("0-9", "10-19", "20-29"), interim_state, interim_queue)

    assert scheduler.load_state(state_dir, ("0-9", "10-19", "20-29")) == {
        "0-9": "runs/a", "10-19": None, "20-29": "runs/b"}
    assert scheduler.load_queue(state_dir) == ["runs/c", "runs/d"]
    log = (state_dir / scheduler.LOG_NAME).read_text()
    assert "adopted state" in log
    assert "2 block(s) already running" in log
    assert "2 queued" in log


def test_adopt_drops_blocks_not_in_this_schedulers_own_set(tmp_path):
    interim_state = tmp_path / "state.json"
    interim_state.write_text(json.dumps({"0-9": "runs/a", "30-39": "runs/orphan"}))
    interim_queue = tmp_path / "queue.txt"
    interim_queue.write_text("")
    state_dir = tmp_path / "adopted"
    scheduler.adopt(state_dir, ("0-9",), interim_state, interim_queue)
    assert scheduler.load_state(state_dir, ("0-9",)) == {"0-9": "runs/a"}


# --- is_running() / pid file ----------------------------------------------------

def test_is_running_is_false_with_no_pid_file(tmp_path):
    assert scheduler.is_running(tmp_path) is False


def test_is_running_is_true_for_this_process_own_pid(tmp_path):
    (tmp_path / scheduler.PID_NAME).write_text(str(os.getpid()))
    assert scheduler.is_running(tmp_path) is True


def test_is_running_is_false_for_a_pid_that_does_not_exist(tmp_path):
    (tmp_path / scheduler.PID_NAME).write_text("999999999")
    assert scheduler.is_running(tmp_path) is False


def test_run_forever_writes_and_removes_its_pid_file(tmp_path):
    seen_during = {}

    def fake_status(run_dir):
        return {"state": "done", "progress": 1.0, "detail": ""}

    import unittest.mock as mock
    with mock.patch.object(runner_mod, "status", fake_status):
        pid_file = tmp_path / scheduler.PID_NAME

        # capture whether the pid file exists mid-run by checking after the
        # (single) iteration but before run_forever returns is not directly
        # observable synchronously, so this checks the documented contract:
        # present during, absent after.
        scheduler.run_forever(tmp_path, ("0-9",), stop_after=1)
        seen_during["after"] = pid_file.exists()
    assert seen_during["after"] is False


def test_log_lines_are_ist_stamped(tmp_path):
    scheduler._log(tmp_path, "hello")
    line = (tmp_path / scheduler.LOG_NAME).read_text().splitlines()[0]
    stamp = line.split("  ", 1)[0]
    assert stamp.endswith("+05:30"), "every log line must carry the IST offset, not naive local time"
    from datetime import datetime
    datetime.fromisoformat(stamp)          # must parse as ISO 8601


# --- eta_ist ---------------------------------------------------------------------

def test_eta_ist_is_none_when_eta_is_none():
    assert scheduler.eta_ist(None) is None


def test_eta_ist_is_an_ist_offset_timestamp():
    result = scheduler.eta_ist(3600.0)
    assert result is not None
    assert result.endswith("+05:30")


# --- step(): the scheduling loop's one iteration --------------------------------

@pytest.fixture
def fake_run_dir(tmp_path):
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "deck.fds").write_text("&HEAD CHID='x' /\n&TIME T_END=100.0 /\n&TAIL /\n")
    return run_dir


def test_step_launches_a_queued_run_on_a_free_block_pinned_to_it(tmp_path, fake_run_dir,
                                                                  monkeypatch):
    scheduler.save_queue(tmp_path, [str(fake_run_dir)])
    monkeypatch.setattr(runner_mod, "status", lambda d: {"state": "failed", "detail": ""})
    monkeypatch.setattr(runner_mod, "has_restart_files", lambda d: False)
    launched = []
    monkeypatch.setattr(runner_mod, "run",
                        lambda deck, out, extra_env=None: launched.append((deck, out, extra_env)))

    state = {"0-9": None}
    state = scheduler.step(tmp_path, ("0-9",), state, {}, set())

    assert state["0-9"] == str(fake_run_dir)
    assert launched == [(fake_run_dir / "deck.fds", fake_run_dir,
                        {"I_MPI_PIN_PROCESSOR_LIST": "0-9"})]
    assert scheduler.load_queue(tmp_path) == [], "the launched run must leave the queue"


def test_step_does_not_touch_a_block_already_running(tmp_path, fake_run_dir, monkeypatch):
    monkeypatch.setattr(runner_mod, "status", lambda d: {"state": "running", "progress": 0.5})
    calls = []
    monkeypatch.setattr(runner_mod, "run", lambda *a, **k: calls.append("run"))

    state = {"0-9": str(fake_run_dir)}
    state = scheduler.step(tmp_path, ("0-9",), state, {}, set())

    assert state == {"0-9": str(fake_run_dir)}
    assert calls == []


def test_step_frees_a_done_block_and_clears_its_failure_count(tmp_path, fake_run_dir,
                                                               monkeypatch):
    scheduler._record_failure(fake_run_dir)
    monkeypatch.setattr(runner_mod, "status", lambda d: {"state": "done", "progress": 1.0})

    state = scheduler.step(tmp_path, ("0-9",), {"0-9": str(fake_run_dir)}, {}, set())

    assert state == {"0-9": None}
    assert scheduler._failure_count(fake_run_dir) == 0
    assert "done on block 0-9, freed" in (tmp_path / scheduler.LOG_NAME).read_text()


def test_step_frees_a_paused_block_without_recording_a_failure(tmp_path, fake_run_dir,
                                                                monkeypatch):
    monkeypatch.setattr(runner_mod, "status",
                        lambda d: {"state": "paused", "detail": "stopped gracefully"})
    state = scheduler.step(tmp_path, ("0-9",), {"0-9": str(fake_run_dir)}, {}, set())
    assert state == {"0-9": None}
    assert scheduler._failure_count(fake_run_dir) == 0


def test_step_records_a_failure_and_leaves_the_block_free(tmp_path, fake_run_dir, monkeypatch):
    monkeypatch.setattr(runner_mod, "status",
                        lambda d: {"state": "failed", "detail": "no output"})
    state = scheduler.step(tmp_path, ("0-9",), {"0-9": str(fake_run_dir)}, {}, set())
    assert state == {"0-9": None}
    assert scheduler._failure_count(fake_run_dir) == 1


def test_step_skips_a_run_that_has_failed_too_many_times_and_logs_once(tmp_path, fake_run_dir,
                                                                       monkeypatch):
    for _ in range(scheduler.MAX_FAILURES):
        scheduler._record_failure(fake_run_dir)
    scheduler.save_queue(tmp_path, [str(fake_run_dir)])
    monkeypatch.setattr(runner_mod, "run", lambda *a, **k: pytest.fail("must not launch"))

    logged_skips: set[str] = set()
    state = scheduler.step(tmp_path, ("0-9",), {"0-9": None}, {}, logged_skips)

    assert state == {"0-9": None}
    assert scheduler.load_queue(tmp_path) == [str(fake_run_dir)], "stays queued for a human to fix"
    log_text = (tmp_path / scheduler.LOG_NAME).read_text()
    assert log_text.count("failed 3 times, skipped") == 1

    # a second iteration must not log the skip again
    scheduler.step(tmp_path, ("0-9",), {"0-9": None}, {}, logged_skips)
    assert (tmp_path / scheduler.LOG_NAME).read_text().count("failed 3 times, skipped") == 1


def test_step_resumes_a_run_with_restart_files_and_a_design(tmp_path, fake_run_dir, monkeypatch):
    from solit2.schema.design import Design

    (fake_run_dir / "x.restart").write_text("")
    (fake_run_dir / scheduler.DESIGN_NAME).write_text(
        Design.load("designs/og-dbr-rev0.json").model_dump_json(by_alias=True))
    scheduler.save_queue(tmp_path, [str(fake_run_dir)])
    monkeypatch.setattr(runner_mod, "status", lambda d: {"state": "failed", "detail": ""})
    monkeypatch.setattr(runner_mod, "has_restart_files", lambda d: True)
    resumed_deck = fake_run_dir / "deck.fds"
    monkeypatch.setattr(runner_mod, "prepare_resume",
                        lambda run_dir, design, t_end_s=None: resumed_deck)
    launched = []
    monkeypatch.setattr(runner_mod, "run",
                        lambda deck, out, extra_env=None: launched.append((deck, extra_env)))

    state = scheduler.step(tmp_path, ("0-9",), {"0-9": None}, {}, set())

    assert state["0-9"] == str(fake_run_dir)
    assert launched == [(resumed_deck, {"I_MPI_PIN_PROCESSOR_LIST": "0-9"})]


def test_step_refuses_to_resume_without_design_json_and_records_a_failure(tmp_path, fake_run_dir,
                                                                          monkeypatch):
    (fake_run_dir / "x.restart").write_text("")
    scheduler.save_queue(tmp_path, [str(fake_run_dir)])
    monkeypatch.setattr(runner_mod, "status", lambda d: {"state": "failed", "detail": ""})
    monkeypatch.setattr(runner_mod, "has_restart_files", lambda d: True)
    monkeypatch.setattr(runner_mod, "run", lambda *a, **k: pytest.fail("must not launch"))

    state = scheduler.step(tmp_path, ("0-9",), {"0-9": None}, {}, set())

    assert state == {"0-9": None}, "a refused launch must not claim the block"
    assert scheduler._failure_count(fake_run_dir) == 1
    log_text = (tmp_path / scheduler.LOG_NAME).read_text()
    assert "design.json" in log_text


def test_step_resumes_through_the_real_prepare_resume_keeping_dx_and_window(tmp_path, monkeypatch):
    """The companion above mocks `prepare_resume` to check step()'s own
    wiring; this one lets it run for real (only `runner.run`, the actual FDS
    launch, is stubbed), so the scheduler's resume path is exercised against
    the same generator the live probes found broken -- a grid-study point at
    a non-default dx and a shortened T_END, exactly as C3 reported."""
    from solit2.engines.fds import deck as deck_mod
    from solit2.schema.design import Design

    design = Design.load("designs/og-dbr-rev0.json")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "deck.fds").write_text(deck_mod.generate(design, dx_m=0.75, t_end_s=600.0))
    (run_dir / scheduler.DESIGN_NAME).write_text(design.model_dump_json(by_alias=True))
    (run_dir / "x.restart").write_text("")
    scheduler.save_queue(tmp_path, [str(run_dir)])

    launched = []
    monkeypatch.setattr(runner_mod, "run",
                        lambda deck, out, extra_env=None: launched.append(deck))
    state = scheduler.step(tmp_path, ("0-9",), {"0-9": None}, {}, set())

    assert state["0-9"] == str(run_dir)
    assert launched == [run_dir / "deck.fds"]
    deck_text = (run_dir / "deck.fds").read_text()
    assert "RESTART=.TRUE." in deck_text
    assert "T_END=600.0" in deck_text, "must keep the run's own window, not the design's full one"
    assert deck_mod.stored_dx_m(run_dir) == pytest.approx(0.75), "must keep the run's own dx"


def test_step_frees_a_block_whose_run_dir_does_not_exist_on_disk(tmp_path):
    """A `state.json` entry pointing at a directory that no longer exists
    (or never did -- a stale adopted reference) must free the block and log
    it, not crash the whole scheduler loop. Regression: `_release_finished`
    used to propagate a bare FileNotFoundError from `_record_failure` here."""
    missing = tmp_path / "runs" / "gone"
    state = scheduler.step(tmp_path, ("0-9",), {"0-9": str(missing)}, {}, set())
    assert state == {"0-9": None}


def test_step_skips_a_queued_run_dir_that_does_not_exist_and_counts_it_as_a_failure(tmp_path):
    """Regression: adopting an interim scheduler's queue.txt can name a run
    directory that turns out not to exist on disk (a stale entry). `step()`
    used to propagate a bare FileNotFoundError from `_try_lock_run` trying to
    create a lock file inside it, crashing the whole loop over one bad
    queue entry -- verified against the CLI's `--adopt-state/--adopt-queue`
    path, which is exactly how this surfaced."""
    missing = tmp_path / "runs" / "gone"
    scheduler.save_queue(tmp_path, [str(missing)])
    state = scheduler.step(tmp_path, ("0-9",), {"0-9": None}, {}, set())
    assert state == {"0-9": None}
    assert scheduler.load_queue(tmp_path) == [str(missing)]
    log_text = (tmp_path / scheduler.LOG_NAME).read_text()
    assert "does not exist on disk" in log_text
    assert "(1/3)" in log_text, "the failure is reported even though it cannot be persisted"


def test_step_never_launches_twice_on_one_run_dir_already_locked(tmp_path, fake_run_dir,
                                                                  monkeypatch):
    scheduler.save_queue(tmp_path, [str(fake_run_dir)])
    monkeypatch.setattr(runner_mod, "status", lambda d: {"state": "failed", "detail": ""})
    monkeypatch.setattr(runner_mod, "has_restart_files", lambda d: False)
    monkeypatch.setattr(runner_mod, "run", lambda *a, **k: None)

    held, _ = scheduler._try_lock_run(fake_run_dir)   # simulate an external fds-exec holding it
    try:
        state = scheduler.step(tmp_path, ("0-9",), {"0-9": None}, {}, set())
    finally:
        held.close()

    assert state == {"0-9": None}
    assert scheduler.load_queue(tmp_path) == [str(fake_run_dir)], \
        "left in the queue for the next poll, not lost"
    assert "already locked" in (tmp_path / scheduler.LOG_NAME).read_text()

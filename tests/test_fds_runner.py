import shutil
import time

import pytest

from solit2.engines.fds import runner


@pytest.fixture
def ready(monkeypatch, tmp_path):
    """An environment where every pre-flight check passes."""
    monkeypatch.delenv(runner.REMOTE_ENV, raising=False)
    monkeypatch.delenv(runner.BIN_ENV, raising=False)
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/local/bin/{name}")
    monkeypatch.setattr(shutil, "disk_usage",
                        lambda p: shutil._ntuple_diskusage(0, 0, runner.MIN_FREE_BYTES * 2))
    return tmp_path


def test_preflight_passes_when_everything_is_present(ready):
    assert runner.preflight() == []


def test_preflight_reports_a_missing_fds_binary(ready, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None if name == "fds" else "/usr/bin/x")
    problems = runner.preflight()
    assert any("fds" in p for p in problems)


def test_an_explicit_binary_path_satisfies_the_binary_check(ready, monkeypatch, tmp_path):
    monkeypatch.setattr(shutil, "which", lambda name: None if name == "fds" else "/usr/bin/x")
    binary = tmp_path / "fds"
    binary.write_text("#!/bin/sh\n")
    monkeypatch.setenv(runner.BIN_ENV, str(binary))
    assert runner.preflight() == []


def test_preflight_reports_missing_mpiexec(ready, monkeypatch):
    monkeypatch.setattr(shutil, "which",
                        lambda name: None if name == "mpiexec" else "/usr/local/bin/fds")
    assert any("mpiexec" in p for p in runner.preflight())


def test_preflight_reports_insufficient_disk(ready, monkeypatch):
    monkeypatch.setattr(shutil, "disk_usage",
                        lambda p: shutil._ntuple_diskusage(0, 0, 1024))
    assert any("disk" in p.lower() for p in runner.preflight())


def test_a_remote_host_is_reported_as_not_implemented(ready, monkeypatch):
    monkeypatch.setenv(runner.REMOTE_ENV, "someone@hpc.example")
    problems = runner.preflight()
    assert len(problems) == 1
    assert "remote" in problems[0].lower()


def test_status_reports_failed_when_there_is_no_log(tmp_path):
    assert runner.status(tmp_path)["state"] == "failed"


def test_status_reports_progress_from_the_fds_log(tmp_path):
    (tmp_path / "run.out").write_text(
        "Time Step       100   March 15, 2026  10:00:00\n"
        "Total Time:        250.000 s\n")
    (tmp_path / "deck.fds").write_text("&TIME T_END=1000.0 /\n")
    state = runner.status(tmp_path)
    assert state["state"] == "running"
    assert state["progress"] == pytest.approx(0.25)


def test_status_reports_done_when_fds_says_it_completed(tmp_path):
    (tmp_path / "run.out").write_text("Total Time:      1000.000 s\nSTOP: FDS completed successfully\n")
    (tmp_path / "deck.fds").write_text("&TIME T_END=1000.0 /\n")
    state = runner.status(tmp_path)
    assert state["state"] == "done"
    assert state["progress"] == 1.0


def test_a_just_launched_run_is_running_not_failed(tmp_path):
    # `run()` opens the log before FDS has written a thing. Calling that
    # "failed" made `run --engine fds` impossible to complete: the CLI polls
    # while the state is "running", which was never true at launch.
    (tmp_path / "run.out").write_text("")
    (tmp_path / "deck.fds").write_text("&TIME T_END=1000.0 /\n")
    state = runner.status(tmp_path)
    assert state["state"] == "running"
    assert state["progress"] == 0.0


def test_a_banner_only_log_is_running_not_failed(tmp_path):
    (tmp_path / "run.out").write_text(
        " Fire Dynamics Simulator\n\n Revision : FDS6.9.1-0-g889da6a-release\n")
    (tmp_path / "deck.fds").write_text("&TIME T_END=1000.0 /\n")
    assert runner.status(tmp_path)["state"] == "running"


def test_an_error_in_the_log_is_reported_as_failed(tmp_path):
    (tmp_path / "run.out").write_text(
        "ERROR: Mesh 2 is not aligned with Mesh 1\nSTOP: FDS was improperly set up\n")
    (tmp_path / "deck.fds").write_text("&TIME T_END=1000.0 /\n")
    assert runner.status(tmp_path)["state"] == "failed"


def test_progress_prefers_the_out_file_fds_writes_over_captured_stdout(tmp_path):
    # `run()` captures the process's stdout into run.out; the "Total Time:"
    # line is one FDS writes to <CHID>.out, so that file is the truth.
    (tmp_path / "run.out").write_text("Total Time:        250.000 s\n")
    (tmp_path / "abc123.out").write_text("Total Time:        750.000 s\n")
    (tmp_path / "deck.fds").write_text("&TIME T_END=1000.0 /\n")
    assert runner.status(tmp_path)["progress"] == pytest.approx(0.75)


def test_the_captured_stdout_is_used_when_fds_wrote_no_out_file(tmp_path):
    (tmp_path / "run.out").write_text("Total Time:        250.000 s\n")
    (tmp_path / "deck.fds").write_text("&TIME T_END=1000.0 /\n")
    assert runner.status(tmp_path)["progress"] == pytest.approx(0.25)


def test_a_run_without_a_deck_cannot_report_progress_and_is_failed(tmp_path):
    (tmp_path / "run.out").write_text("Total Time:        250.000 s\n")
    assert runner.status(tmp_path)["state"] == "failed"


def test_the_fds_version_is_read_from_the_log_and_is_none_when_absent(tmp_path):
    assert runner.fds_version(tmp_path) is None
    (tmp_path / "run.out").write_text("Total Time: 1.0 s\n")
    assert runner.fds_version(tmp_path) is None
    (tmp_path / "abc123.out").write_text(
        " Revision         : FDS6.9.1-0-g889da6a-release\n")
    assert runner.fds_version(tmp_path) == "6.9.1"


def test_run_launches_one_mpi_rank_per_mesh(ready, monkeypatch, tmp_path):
    # A bare `fds` runs every mesh in one process -- valid, but measured at
    # 2.1x slower than one rank per mesh on a three-mesh deck. The launch must
    # be `mpiexec -np N fds deck.fds` with N read off the deck itself.
    captured = {}

    class FakePopen:
        pid = 1234

        def __init__(self, argv, **kwargs):
            captured["argv"] = argv

    monkeypatch.setattr(runner.subprocess, "Popen", FakePopen)
    deck = tmp_path / "deck.fds"
    deck.write_text("&MESH IJK=1,1,1, XB=0,1,0,1,0,1 /\n" * 4 + "&TAIL /\n")
    runner.run(deck, tmp_path)
    argv = captured["argv"]
    assert argv[0].endswith("mpiexec")
    assert argv[1:3] == ["-np", "4"]
    assert argv[3].endswith("fds") and argv[4] == "deck.fds"


def test_mesh_count_reads_the_deck(tmp_path):
    deck = tmp_path / "d.fds"
    deck.write_text("&HEAD /\n&MESH a /\n&MESH b /\n&MESH c /\n&TAIL /\n")
    assert runner.mesh_count(deck) == 3


def test_smokeview_binary_prefers_the_env_var_then_path(monkeypatch, tmp_path):
    fake = tmp_path / "smokeview"
    fake.write_text("")
    monkeypatch.setenv(runner.SMV_ENV, str(fake))
    assert runner.smokeview_binary() == str(fake)
    monkeypatch.delenv(runner.SMV_ENV)
    monkeypatch.setattr(runner.shutil, "which",
                        lambda name: "/usr/bin/smv" if name == "smokeview" else None)
    assert runner.smokeview_binary() == "/usr/bin/smv"


def test_open_smokeview_launches_on_the_run_dirs_smv(monkeypatch, tmp_path):
    (tmp_path / "abc.smv").write_text("")
    monkeypatch.setattr(runner, "smokeview_binary", lambda: "/usr/bin/smv")
    calls = []
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **kw: calls.append((a, kw)))
    runner.open_smokeview(tmp_path)
    (args,), kw = calls[0]
    assert args == ["/usr/bin/smv", "abc.smv"] and kw["cwd"] == tmp_path


def test_open_smokeview_names_what_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "smokeview_binary", lambda: None)
    with pytest.raises(FileNotFoundError, match="smokeview"):
        runner.open_smokeview(tmp_path)
    monkeypatch.setattr(runner, "smokeview_binary", lambda: "/usr/bin/smv")
    with pytest.raises(FileNotFoundError, match=r"\.smv"):
        runner.open_smokeview(tmp_path)


def _unfinished(tmp_path, total_time_s: float = 250.0):
    """A run dir that looks like FDS got part way and stopped writing."""
    (tmp_path / "run.out").write_text(
        f"Time Step       100   March 15, 2026  10:00:00\n"
        f"Total Time:        {total_time_s:.3f} s\n")
    (tmp_path / "deck.fds").write_text("&TIME T_END=1000.0 /\n")
    return tmp_path


def test_a_killed_run_is_not_reported_as_still_running(tmp_path):
    # A killed run leaves its log behind looking exactly like a live one. The
    # pid `run()` recorded is the evidence that it is gone.
    _unfinished(tmp_path)
    (tmp_path / runner.PID_NAME).write_text("999999")     # no such process
    state = runner.status(tmp_path)
    assert state["state"] == "failed"
    assert "gone" in state["detail"] and "250 s of 1000 s" in state["detail"]
    assert state["progress"] == pytest.approx(0.25), "how far it got is still reported"


def test_a_live_pid_keeps_the_run_running(tmp_path):
    import os
    _unfinished(tmp_path)
    (tmp_path / runner.PID_NAME).write_text(str(os.getpid()))
    assert runner.status(tmp_path)["state"] == "running"


def test_a_wedged_run_is_caught_by_its_silence_even_with_live_processes(tmp_path):
    # The case this exists for: a deadlocked MPI run keeps every process ALIVE.
    # One real run sat at 935.8 s of 3600 s for seven hours with nine ranks
    # spinning at 100% CPU while the app reported "running -- 26%".
    import os
    _unfinished(tmp_path)
    (tmp_path / runner.PID_NAME).write_text(str(os.getpid()))   # alive, and still wedged
    old = time.time() - (runner.STALL_AFTER_S + 600.0)
    for f in tmp_path.glob("*"):
        os.utime(f, (old, old))
    state = runner.status(tmp_path)
    assert state["state"] == "failed"
    assert "not advancing" in state["detail"] and "minutes" in state["detail"]


def test_a_run_writing_output_now_is_running_however_long_it_has_been_going(tmp_path):
    _unfinished(tmp_path)
    assert runner.silent_for_s(tmp_path) < runner.STALL_AFTER_S
    assert runner.status(tmp_path)["state"] == "running"


def test_silence_is_measured_from_the_newest_file_not_just_the_log(tmp_path):
    # FDS dumps its CSVs on their own schedule, so a log that has gone quiet
    # while the CSVs keep growing is a slow run, not a dead one.
    import os
    _unfinished(tmp_path)
    old = time.time() - (runner.STALL_AFTER_S + 600.0)
    for f in tmp_path.glob("*"):
        os.utime(f, (old, old))
    (tmp_path / "x_devc.csv").write_text("s\nTime\n0.0\n")      # written just now
    assert runner.silent_for_s(tmp_path) < 60.0
    assert runner.status(tmp_path)["state"] == "running"


def test_run_records_the_pid_it_launched(ready, monkeypatch, tmp_path):
    launched = {}

    class _Fake:
        pid = 4242

    def fake_popen(cmd, **kw):
        launched["cmd"] = cmd
        return _Fake()

    monkeypatch.setattr(runner.subprocess, "Popen", fake_popen)
    deck = tmp_path / "deck.fds"
    deck.write_text("&MESH IJK=1,1,1, XB=0,1,0,1,0,1 /\n&TIME T_END=10.0 /\n")
    runner.run(deck, tmp_path)
    assert (tmp_path / runner.PID_NAME).read_text() == "4242"

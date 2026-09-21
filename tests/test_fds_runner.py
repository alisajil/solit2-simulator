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


def test_a_build_from_source_reports_its_revision_rather_than_nothing(tmp_path):
    """A locally built FDS stamps no release number. The build on this machine
    banners "Revision : -master" with a date and nothing else, which made every
    Tier 2 result say its engine version was unverified. The revision and its
    date identify the code that ran, in a shape no one can mistake for a release."""
    (tmp_path / "abc.out").write_text(
        " Fire Dynamics Simulator\n"
        " Revision         : -master\n"
        " Revision Date    : Thu Sep 17 12:46:53 2026 -0400\n"
        " Compiler         : GCC version 16.2.0\n")
    assert runner.fds_version(tmp_path) == "master@2026-09-17"


def test_a_numbered_release_still_wins_over_the_revision(tmp_path):
    (tmp_path / "abc.out").write_text(
        " Revision         : FDS6.9.1-0-g889da6a-release\n"
        " Revision Date    : Thu Sep 17 12:46:53 2026 -0400\n")
    assert runner.fds_version(tmp_path) == "6.9.1"


def test_a_revision_without_a_readable_date_is_still_reported(tmp_path):
    (tmp_path / "abc.out").write_text(" Revision         : -master\n")
    assert runner.fds_version(tmp_path) == "master"
    (tmp_path / "abc.out").write_text(
        " Revision         : -master\n Revision Date    : sometime last week\n")
    assert runner.fds_version(tmp_path) == "master"


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


def test_the_liveness_check_never_signals_the_process_it_asks_about():
    """`os.kill(pid, 0)` is the POSIX idiom and is correct there. On Windows
    `os.kill` routes any signal other than CTRL_C_EVENT/CTRL_BREAK_EVENT
    straight to TerminateProcess, so the liveness CHECK would kill the FDS run
    it was asked about. This pins that the Windows path never reaches os.kill.
    """
    import os
    called = []
    real_name = os.name

    def exploding_kill(pid, sig):
        called.append((pid, sig))
        raise AssertionError("os.kill must never be reached on Windows")

    try:
        os.name = "nt"
        try:
            runner._pid_alive(os.getpid())
        except (AttributeError, ImportError, OSError, FileNotFoundError):
            pass          # no Windows DLLs here; what matters is os.kill was not used
    finally:
        os.name = real_name
    assert called == []


def test_the_liveness_check_answers_correctly_on_this_platform():
    import os
    assert runner._pid_alive(os.getpid()) is True
    # a pid that cannot exist: max_pid is far below this on every platform
    assert runner._pid_alive(4294967294) is False, "and a pid too large must not raise"
    assert runner._pid_alive(999999) is False


def test_a_run_is_launched_detached_so_it_outlives_the_app():
    """Hours-long runs are polled, not held open. POSIX gets a new session;
    Windows ignores that argument and needs creation flags instead, or the run
    dies with the console that started it."""
    import os
    if os.name == "nt":
        assert runner._DETACHED == {"creationflags": 0x00000008 | 0x00000200}
    else:
        assert runner._DETACHED == {"start_new_session": True}


def _steps_csv(tmp_path, rows):
    """FDS's own `<CHID>_steps.csv`: units row, header row, then one row a step."""
    lines = [",,s,s,s", "Time Step,Wall Time,Step Size,Simulation Time,CPU Time"]
    for step, wall, size, simulated in rows:
        lines.append(f"{step},{wall},{size},{simulated},0.0")
    (tmp_path / "abc_steps.csv").write_text("\n".join(lines) + "\n")


def test_live_progress_measures_the_rate_from_fds_own_wall_clock(tmp_path):
    base = "2026-09-21T03:00:{:02d}.000+05:30"
    # 10 s of wall clock buys 1 s of simulation: a tenth of real time
    _steps_csv(tmp_path, [(i, base.format(i * 10), 0.05, i * 1.0) for i in range(6)])
    (tmp_path / "deck.fds").write_text("&TIME T_END=100.0 /\n")
    live = runner.live(tmp_path)
    assert live["time_step"] == 5
    assert live["simulated_s"] == pytest.approx(5.0)
    assert live["elapsed_s"] == pytest.approx(50.0)
    assert live["rate_s_per_s"] == pytest.approx(0.1)
    assert live["eta_s"] == pytest.approx((100.0 - 5.0) / 0.1)


def test_the_rate_is_the_current_one_not_the_average_since_launch(tmp_path):
    """This matters: one real run spent a night throttled to a thirtieth of its
    speed, and an average over that would have predicted days of work left for
    a run that finished within the hour."""
    from datetime import datetime, timedelta
    start = datetime.fromisoformat("2026-09-21T03:00:00.000+05:30")

    def at(seconds):
        return (start + timedelta(seconds=seconds)).isoformat()

    # 40 steps at a tenth of a simulated second per minute, then 90 at one a
    # second. 90 exceeds RATE_WINDOW_STEPS, so the window is entirely fast.
    slow = [(i, at(i * 60), 0.05, i * 0.1) for i in range(40)]
    t0, sim0 = 40 * 60, slow[-1][3]
    fast = [(40 + i, at(t0 + i), 0.05, sim0 + i * 1.0) for i in range(1, 91)]
    assert len(fast) > runner.RATE_WINDOW_STEPS
    _steps_csv(tmp_path, slow + fast)
    (tmp_path / "deck.fds").write_text("&TIME T_END=1000.0 /\n")
    live = runner.live(tmp_path)
    assert live["rate_s_per_s"] == pytest.approx(1.0, rel=0.05), "the recent rate, not 0.1"


def test_live_progress_reads_heat_release_and_the_control_log(tmp_path):
    _steps_csv(tmp_path, [(1, "2026-09-21T03:00:00.000+05:30", 0.05, 1.0)])
    (tmp_path / "abc_hrr.csv").write_text(
        "s,kW\nTime,HRR\n0.0,0.0\n1.0,4200.0\n")
    (tmp_path / "abc_ctrl.csv").write_text(
        "s,status,status\nTime,DETECT,ACT\n0.0,-1,-1\n9.0,1,-1\n20.0,1,1\n")
    live = runner.live(tmp_path, t_end_s=100.0)
    assert live["hrr_mw"] == pytest.approx(4.2)
    assert live["detect_s"] == pytest.approx(9.0)
    assert live["activate_s"] == pytest.approx(20.0)


def test_live_progress_reports_unknown_rather_than_guessing(tmp_path):
    """A run that has written nothing yet has no rate and no estimate, and must
    not invent either."""
    live = runner.live(tmp_path, t_end_s=100.0)
    assert live["simulated_s"] is None and live["rate_s_per_s"] is None
    assert live["eta_s"] is None and live["hrr_mw"] is None
    # one step is a position but not yet a rate
    _steps_csv(tmp_path, [(1, "2026-09-21T03:00:00.000+05:30", 0.05, 1.0)])
    one = runner.live(tmp_path, t_end_s=100.0)
    assert one["simulated_s"] == pytest.approx(1.0)
    assert one["rate_s_per_s"] is None and one["eta_s"] is None


def test_a_half_written_step_row_is_skipped_not_fatal(tmp_path):
    """The file is appended to while it is read."""
    _steps_csv(tmp_path, [(1, "2026-09-21T03:00:00.000+05:30", 0.05, 1.0)])
    with (tmp_path / "abc_steps.csv").open("a") as fh:
        fh.write("2,2026-09-21T03:00:10.0")
    live = runner.live(tmp_path, t_end_s=100.0)
    assert live["time_step"] == 1


def _csv(tmp_path, name, header, rows):
    lines = ["s," + ",".join("x" for _ in header[1:]), ",".join(header)]
    lines += [",".join(str(v) for v in r) for r in rows]
    (tmp_path / name).write_text("\n".join(lines) + "\n")


def test_series_reads_named_columns_against_the_clock(tmp_path):
    _csv(tmp_path, "abc_hrr.csv", ["Time", "HRR", "Q_PART"],
         [(0.0, 0.0, 0.0), (1.0, 100.0, -5.0), (2.0, 250.0, -9.0)])
    out = runner.series(tmp_path, "_hrr.csv", ("HRR", "Q_PART"))
    assert out["t_s"] == [0.0, 1.0, 2.0]
    assert out["HRR"] == [0.0, 100.0, 250.0]
    assert out["Q_PART"] == [0.0, -5.0, -9.0]


def test_series_omits_a_column_the_run_does_not_carry(tmp_path):
    """A device the run never wrote must be absent, not charted as zero."""
    _csv(tmp_path, "abc_devc.csv", ["Time", "TARGET_FLUX"], [(0.0, 1.0), (1.0, 2.0)])
    out = runner.series(tmp_path, "_devc.csv", ("TARGET_FLUX", "NOT_PRESENT"))
    assert set(out) == {"t_s", "TARGET_FLUX"}
    assert runner.series(tmp_path, "_devc.csv", ("NOT_PRESENT",)) == {}


def test_series_is_empty_until_there_is_a_complete_row(tmp_path):
    assert runner.series(tmp_path, "_hrr.csv", ("HRR",)) == {}
    (tmp_path / "abc_hrr.csv").write_text("s,kW\nTime,HRR\n")
    assert runner.series(tmp_path, "_hrr.csv", ("HRR",)) == {}


def test_series_drops_a_half_written_last_row_but_keeps_the_newest_whole_one(tmp_path):
    """The file is appended to while it is read."""
    _csv(tmp_path, "abc_hrr.csv", ["Time", "HRR"], [(0.0, 0.0), (1.0, 100.0)])
    with (tmp_path / "abc_hrr.csv").open("a") as fh:
        fh.write("2.0,")
    out = runner.series(tmp_path, "_hrr.csv", ("HRR",))
    assert out["t_s"] == [0.0, 1.0] and out["HRR"] == [0.0, 100.0]


def test_series_subsamples_a_long_run_but_never_drops_the_newest_sample(tmp_path):
    rows = [(float(i), float(i) * 2) for i in range(5000)]
    _csv(tmp_path, "abc_hrr.csv", ["Time", "HRR"], rows)
    out = runner.series(tmp_path, "_hrr.csv", ("HRR",), max_points=100)
    assert len(out["t_s"]) <= 102
    assert out["t_s"][0] == 0.0
    assert out["t_s"][-1] == 4999.0, "the latest sample is what a live chart is for"
    assert out["HRR"][-1] == 9998.0

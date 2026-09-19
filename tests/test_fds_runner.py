import shutil

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

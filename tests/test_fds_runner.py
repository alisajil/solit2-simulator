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

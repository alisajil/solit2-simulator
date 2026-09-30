# tests/test_cfd_runs.py
from pathlib import Path

import pytest

from solit2.compliance.spec import load_spec
from solit2.engines.fds import deck, reader, runner
from solit2.reports import cfd_runs

SPEC = "examples/compliance/solit2-example.spec.json"


@pytest.fixture(scope="module")
def design():
    return load_spec(SPEC).tests["A"]


def _run_dir(tmp_path: Path, design, t_end: float = 600.0) -> Path:
    run_dir = tmp_path / deck.chid(design)
    run_dir.mkdir()
    (run_dir / "deck.fds").write_text(f"&TIME T_END={t_end} /\n")
    return run_dir


def test_a_design_with_no_run_directory_is_not_run(tmp_path, design):
    assert cfd_runs.lookup(design, tmp_path) == cfd_runs.NOT_RUN


def test_a_running_run_reports_simulated_time_against_t_end(tmp_path, design, monkeypatch):
    _run_dir(tmp_path, design)
    monkeypatch.setattr(runner, "status",
                        lambda d: {"state": "running", "progress": 0.5, "detail": ""})
    got = cfd_runs.lookup(design, tmp_path)
    assert got.state == "running"
    assert got.detail == "running, 300 of 600 s"
    assert got.result is None


def test_a_failed_run_carries_the_runners_own_reason(tmp_path, design, monkeypatch):
    _run_dir(tmp_path, design)
    monkeypatch.setattr(runner, "status", lambda d: {
        "state": "failed", "progress": 0.2, "detail": "FDS reported an error in run.out"})
    got = cfd_runs.lookup(design, tmp_path)
    assert (got.state, got.detail) == ("failed", "FDS reported an error in run.out")
    assert got.result is None


def test_a_finished_run_is_read_with_the_fds_reader(tmp_path, design, monkeypatch):
    run_dir = _run_dir(tmp_path, design)
    sentinel = object()
    seen = {}

    def fake_read(path, d, *, free_burn_dir=None):
        seen["args"] = (path, free_burn_dir)
        return sentinel

    monkeypatch.setattr(runner, "status",
                        lambda d: {"state": "done", "progress": 1.0, "detail": ""})
    monkeypatch.setattr(reader, "read", fake_read)
    got = cfd_runs.lookup(design, tmp_path)
    assert got.state == "done" and got.result is sentinel
    assert seen["args"] == (run_dir, None)   # no free-burn run exists, so none is passed


def test_a_finished_run_the_reader_refuses_is_reported_not_raised(tmp_path, design, monkeypatch):
    _run_dir(tmp_path, design)
    monkeypatch.setattr(runner, "status",
                        lambda d: {"state": "done", "progress": 1.0, "detail": ""})

    def refuse(path, d, *, free_burn_dir=None):
        raise ValueError("the FDS run's heat detectors never tripped")

    monkeypatch.setattr(reader, "read", refuse)
    got = cfd_runs.lookup(design, tmp_path)
    assert got.state == "unreadable"
    assert "never tripped" in got.detail

"""No FDS is assumed: the runner is stubbed at the module boundary."""
from pathlib import Path

from solit2 import history
from solit2.engines.fds import reader as fds_reader
from solit2.engines.fds import runner as fds_runner
from solit2.engines.reduced import envelope
from solit2.engines.reduced.envelope import _design_sha
from solit2.schema.design import Design

EXAMPLE = "examples/designs/road-tunnel-twin-bore.json"


def _isolate(monkeypatch, tmp_path, problems):
    from app.views import cfd
    monkeypatch.setattr(history, "DEFAULT_PATH", tmp_path / "h.jsonl")
    monkeypatch.setattr(cfd, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(fds_runner, "preflight", lambda: problems)
    monkeypatch.setattr(fds_runner, "smokeview_binary", lambda: None)
    return tmp_path / "runs" / _design_sha(Design.load(EXAMPLE))


def _fake_run(run_dir: Path, log: str, t_end: float = 1200.0) -> None:
    run_dir.mkdir(parents=True)
    (run_dir / "deck.fds").write_text(f"&HEAD CHID='x' /\n&TIME T_END={t_end} /\n")
    (run_dir / "x.out").write_text(log)


def test_without_fds_the_step_says_so_and_offers_no_start(run_view, monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path, ["the fds binary is not on PATH"])
    at = run_view("cfd")
    assert not at.exception
    assert any("fds binary" in m.value for m in at.markdown)
    assert all(b.key != "fds_start" for b in at.button)
    assert not at.get("file_uploader")


def test_with_fds_ready_the_start_button_names_the_default_window(run_view, monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path, [])
    at = run_view("cfd")
    assert at.radio(key="fds_minutes").value == "20 min"
    assert at.button(key="fds_start").label == "Start FDS run (20 min)"


def test_start_writes_the_shortened_deck_and_launches(run_view, monkeypatch, tmp_path):
    run_dir = _isolate(monkeypatch, tmp_path, [])
    launched = []
    monkeypatch.setattr(fds_runner, "run", lambda deck, out: launched.append((deck, out)) or out.name)
    at = run_view("cfd")
    at.radio(key="fds_minutes").set_value("5 min").run()
    at.button(key="fds_start").click().run()
    assert launched and launched[0][1] == run_dir
    assert "T_END=300.0" in (run_dir / "deck.fds").read_text()


def test_a_running_run_shows_progress_and_hides_start(run_view, monkeypatch, tmp_path):
    run_dir = _isolate(monkeypatch, tmp_path, [])
    _fake_run(run_dir, "Time Step 10\n Total Time:  120.0 s\n")
    at = run_view("cfd")
    assert not at.exception
    assert at.get("progress") and all(b.key != "fds_start" for b in at.button)
    assert any("Preliminary" in c.value or "not written" in c.value
               for c in list(at.info) + list(at.caption))


def test_a_finished_run_reads_tier_two_and_correlates(run_view, monkeypatch, tmp_path):
    run_dir = _isolate(monkeypatch, tmp_path, [])
    _fake_run(run_dir, "Total Time: 1200.0 s\nSTOP: FDS completed successfully\n")
    tier1 = envelope.run(Design.load(EXAMPLE))
    monkeypatch.setattr(fds_reader, "read", lambda d, design: tier1)
    at = run_view("cfd")
    assert not at.exception
    assert at.session_state["tier2_result"] is not None
    assert any(m.value.startswith("# Correlation") for m in at.markdown)
    assert at.button(key="open_smv").disabled
    assert at.button(key="fds_start").label.startswith("Re-run FDS")


def test_stamp_changes_when_a_slice_file_changes(tmp_path):
    from app.views import cfd
    (tmp_path / "a_1_1.sf").write_bytes(b"1")
    before = cfd.stamp(tmp_path)
    (tmp_path / "a_1_1.sf").write_bytes(b"12")
    assert cfd.stamp(tmp_path) != before


def test_a_failed_run_never_captions_its_field_as_complete(run_view, monkeypatch, tmp_path):
    """A run that died mid-simulation must not describe its partial field as finished.

    The canvas caption keys off the run's actual state, not merely "is it still
    running", so `failed` gets its own wording rather than falling through to the
    completed-run sentence.
    """
    import numpy as np

    from app.views import cfd
    from solit2.engines.fds.slices import Slice

    run_dir = _isolate(monkeypatch, tmp_path, [])
    _fake_run(run_dir, "Total Time: 300.0 s\n ERROR: Numerical instability\n")
    partial = Slice("TEMPERATURE", "C", np.linspace(-10.0, 10.0, 4), np.linspace(0.0, 6.0, 3),
                    np.array([0.0, 150.0, 300.0]), np.zeros((3, 3, 4)))
    monkeypatch.setattr(cfd, "_load_slice", lambda *a, **kw: partial)
    at = run_view("cfd")

    assert not at.exception
    captions = [c.value for c in at.caption]
    assert any("did not finish" in c for c in captions), captions
    assert not any(c.startswith("Preliminary") for c in captions), captions
    assert not any("frames to t =" in c for c in captions), captions

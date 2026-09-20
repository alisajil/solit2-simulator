from solit2 import history
from solit2.reports import twin


def test_reports_step_builds_and_runs_the_twin_and_offers_exports(run_view, monkeypatch, tmp_path):
    monkeypatch.setattr(history, "DEFAULT_PATH", tmp_path / "h.jsonl")
    at = run_view("reports", timeout=180)
    assert not at.exception
    assert at.session_state["twin_result"] is not None
    bodies = [m.value for m in at.markdown]
    assert any(b.startswith("# Test Plan") for b in bodies)
    assert any(b.startswith("# Correlation") for b in bodies)
    assert any("gallery" in i.value for i in at.info)
    assert any("Run the CFD step" in c.value for c in at.caption)
    assert len(at.get("download_button")) >= 5 and not at.get("file_uploader")


def test_a_twin_that_cannot_be_built_is_reported_and_the_rest_still_renders(run_view, monkeypatch, tmp_path):
    monkeypatch.setattr(history, "DEFAULT_PATH", tmp_path / "h.jsonl")
    def boom(design):
        raise ValueError("nozzle mounting cannot be reproduced in the 5.20 m test gallery")
    monkeypatch.setattr(twin, "test_facility_twin", boom)
    at = run_view("reports", timeout=180)
    assert not at.exception
    assert any("test gallery" in e.value for e in at.error)
    assert any(m.value.startswith("# Test Plan") for m in at.markdown)

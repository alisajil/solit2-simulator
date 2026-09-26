from solit2 import history
from solit2.reports import twin

# Test values for the conditions Annex 7 leaves to the AHJ or the test day.
INPUTS = twin.Annex7Inputs("A", 150.0, 20.0, 60.0, 0.1876, 243.0)


def test_reports_step_builds_and_runs_the_twin_and_offers_exports(run_view, monkeypatch, tmp_path):
    monkeypatch.setattr(history, "DEFAULT_PATH", tmp_path / "h.jsonl")
    # Heads at 5.0 m fit the 5.2 m SOLIT2 gallery; the site example's 5.75 m would
    # be refused, since SOLIT2 publishes no reference height to substitute.
    at = run_view("reports", timeout=180, design_path="examples/designs/solit2-test-protocol.json")
    assert not at.exception
    assert any("Annex 7 test inputs" in i.value for i in at.info), "no inputs yet: asks for them"
    at.session_state["annex7_inputs"] = INPUTS
    at.run()
    assert not at.exception
    assert at.session_state["twin_result"] is not None
    bodies = [m.value for m in at.markdown]
    assert any(b.startswith("# Fire test protocol") for b in bodies)
    assert any(b.startswith("# Correlation") for b in bodies)
    assert any("gallery" in i.value for i in at.info)
    assert any("Run the CFD step" in c.value for c in at.caption)
    assert len(at.get("download_button")) >= 5 and not at.get("file_uploader")


def test_a_twin_that_cannot_be_built_is_reported_and_the_rest_still_renders(run_view, monkeypatch, tmp_path):
    monkeypatch.setattr(history, "DEFAULT_PATH", tmp_path / "h.jsonl")
    def boom(design, inputs):
        raise ValueError("nozzle mounting cannot be reproduced in the 5.20 m test gallery")
    monkeypatch.setattr(twin, "test_facility_twin", boom)
    at = run_view("reports", timeout=180)
    at.session_state["annex7_inputs"] = INPUTS
    at.run()
    assert not at.exception
    assert any("test gallery" in e.value for e in at.error)
    assert any(m.value.startswith("# Fire test protocol") for m in at.markdown)

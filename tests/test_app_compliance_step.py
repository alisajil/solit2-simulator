from pathlib import Path

from streamlit.testing.v1 import AppTest

from app.views import compliance
from tests.conftest import sign_in

APP = "../app/streamlit_app.py"
FIXTURE_DIR = Path("tests/fixtures/compliance")


def test_spec_files_are_found_by_their_version_field():
    assert FIXTURE_DIR / "minimal.spec.json" in compliance.find_specs(FIXTURE_DIR)
    assert FIXTURE_DIR / "project.rules.json" not in compliance.find_specs(FIXTURE_DIR)


def test_the_step_shows_the_headline_and_the_blockers(monkeypatch):
    monkeypatch.setattr(compliance, "SPEC_ROOTS", (FIXTURE_DIR,))
    at = AppTest.from_file(APP, default_timeout=180)
    sign_in(at)
    at.session_state["step"] = 5
    at.session_state["view"] = "wizard"
    at.session_state["design"] = object()  # the gate only checks that a design exists
    at.run()
    text = " ".join(m.value for m in at.markdown)
    assert "applicable clauses comply" in text
    assert any("Blockers" in s.value for s in at.subheader)

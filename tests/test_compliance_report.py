import subprocess

from solit2.compliance import check
from solit2.reports import compliance

SPEC = "tests/fixtures/compliance/minimal.spec.json"


def test_the_report_leads_with_the_headline_and_lists_every_blocker():
    report = check.run(SPEC)
    text = compliance.render(report)
    assert text.startswith(f"# SOLIT² compliance — {report.spec_name}")
    assert report.headline.text in text
    for f in report.blockers:
        assert f.rule_id in text
    assert "requirement (paraphrased)" in text
    assert report.provenance["calibration"] in text


def test_the_lab_checklist_names_each_missing_fact_once():
    report = check.run(SPEC)
    checklist = compliance.lab_checklist(report)
    facts = {f.fact for f in report.blockers if f.fact}
    for fact in facts:
        assert checklist.count(f"`{fact}`") >= 1
    assert "pallet_moisture_pct" not in checklist  # supplied in the fixture


def test_the_cli_writes_the_report(tmp_path):
    out = tmp_path / "c.md"
    done = subprocess.run(["uv", "run", "solit2", "report", "compliance", SPEC, "--out", str(out)],
                          capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert out.read_text().startswith("# SOLIT² compliance")

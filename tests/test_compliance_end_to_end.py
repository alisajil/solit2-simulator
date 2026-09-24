from solit2.compliance import check
from solit2.compliance.verdict import Verdict


def _by_id(report):
    return {f.rule_id: f for f in report.findings}


def test_the_example_spec_checks_cleanly_and_is_not_full():
    report = check.run("examples/compliance/solit2-example.spec.json")
    assert report.headline.applicable > 50
    assert not report.headline.full
    assert _by_id(report)["annex7.6_5.hrr_method"].verdict is Verdict.COMPLIES


def test_the_project_spec_shows_the_findings_the_audit_predicted():
    found = _by_id(check.run("designs/og-test-spec.json"))
    # The SOLIT2 test tunnel preset is 39.0 m2 against Annex 7's 40 m2.
    assert found["annex7.3_6.free_area"].verdict is Verdict.FAILS
    # A 1.5-3.0 m/s test cannot qualify a 3.88-5.08 m/s tunnel.
    assert found["annex3.3_3.ventilation"].verdict is Verdict.FAILS
    assert found["project.r2.8.test_velocity_high"].verdict is Verdict.FAILS
    # 1.5 m installed standoff against 1.0 m in a 5.2 m test tunnel.
    assert found["main.3_6_2.standoff"].verdict is Verdict.FAILS
    # Nothing has been evidenced, so no laboratory clause may pass.
    assert all(f.verdict is Verdict.NEEDS_EVIDENCE for f in found.values() if f.kind == "lab")

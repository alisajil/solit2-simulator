import json
import re
from pathlib import Path

import pytest

from solit2.compliance import check
from solit2.compliance.project_rules import ProjectRule, load_project_rules
from solit2.compliance.rules import REGISTRY
from solit2.compliance.verdict import Verdict
from solit2.reports import guidance

SPEC = "tests/fixtures/compliance/minimal.spec.json"
# guidance.py constants that are not requirements a test can meet, and why.
NOT_REQUIREMENTS = {
    "MAIN_TYPICAL_LONGITUDINAL_MS": "the main document says 'normally used', not required",
    "RISK_ANALYSIS_EXAMPLE": "a worked example on a model tunnel, not a limit",
    "RISK_RANKING_NOISE_PCT": "the example's own reading of its result",
}


def test_every_guidance_requirement_is_read_by_some_rule():
    constants = {n for n in dir(guidance) if re.fullmatch(r"[A-Z][A-Z0-9_]+", n)}
    used = {c for rule in REGISTRY for c in rule.constants}
    assert constants - used - set(NOT_REQUIREMENTS) == set()
    assert used <= constants


def test_rule_ids_are_unique_across_the_registry():
    ids = [r.id for r in REGISTRY]
    assert len(ids) == len(set(ids))


def test_the_checker_runs_every_rule_once():
    report = check.run(SPEC)
    assert len(report.findings) == len(REGISTRY)
    assert report.provenance["design_sha.A"]
    assert report.provenance["calibration"]
    assert all(f.verdict in (Verdict.FAILS, Verdict.NEEDS_EVIDENCE) for f in report.blockers)
    assert not report.headline.full


def test_project_rules_load_and_gate_on_their_fact():
    rules = load_project_rules("tests/fixtures/compliance/project.rules.json")
    assert [r.id for r in rules] == ["project.hrr", "project.report"]
    assert all(r.kind == "project" for r in rules)


def test_a_project_rule_naming_an_unknown_quantity_is_refused():
    with pytest.raises(ValueError, match="quantity"):
        ProjectRule.model_validate({"id": "x", "source": "s", "requirement": "r",
                                    "quantity": "installation.made_up", "comparator": "<=",
                                    "limit": 1.0})


def test_a_deviation_on_a_clause_solit2_does_not_let_the_authority_waive_is_refused(tmp_path):
    raw = json.loads(open(SPEC).read())
    # Absolute paths: a spec's relative paths resolve against the spec file's folder.
    raw["test_designs"] = {"A": str(Path("examples/designs/solit2-test-protocol.json").resolve())}
    raw["installation_design"] = str(Path("examples/designs/road-tunnel-twin-bore.json").resolve())
    raw["deviations"] = {"main.3_6_2.height": {"accepted_by": "a", "document": "d",
                                               "locator": "l", "reason": "r"}}
    path = tmp_path / "s.spec.json"
    path.write_text(json.dumps(raw))
    with pytest.raises(ValueError, match="not waivable"):
        check.run(path)

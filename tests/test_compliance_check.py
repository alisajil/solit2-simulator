import hashlib
import json
import re
import shutil
from pathlib import Path

import pytest

from solit2.compliance import check
from solit2.compliance.project_rules import ProjectRule, load_project_rules
from solit2.compliance.rules import REGISTRY
from solit2.compliance.verdict import Verdict
from solit2.reports import guidance
from solit2.schema import presets

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


@pytest.mark.parametrize("rule, message", [
    ({"quantity": "installation.power_kw", "comparator": "<="}, "together"),
    ({}, "a quantity to compare or a fact to require"),
    ({"requires_fact": "not_a_fact"}, "use one of"),
])
def test_a_malformed_project_rule_is_refused(rule, message):
    with pytest.raises(ValueError, match=message):
        ProjectRule.model_validate({"id": "x", "source": "s", "requirement": "r", **rule})


@pytest.mark.parametrize("empty_value", ["   ", {}])
def test_a_fact_only_project_rule_treats_whitespace_and_empty_containers_as_empty(empty_value):
    """Residual item 3: a whitespace-only string and an empty dict/list/tuple must read
    as "supplied but empty" (Needs evidence), not as a truthy pass -- a fact carrying no
    actual content has not been supplied any more than an empty string has."""
    from dataclasses import replace

    from solit2.compliance import project_rules
    from solit2.compliance.context import Context
    from solit2.compliance.spec import Evidence, Fact, Facts
    from solit2.engines.reduced import envelope
    from solit2.schema.design import Design

    ev = Evidence(document="d", locator="l")
    design = Design.load("examples/designs/road-tunnel-twin-bore.json")
    result = envelope.run(design)
    base_ctx = Context(tests={}, test_results={}, installation=design, installation_result=result,
                       facts=Facts(), protocol_text={})

    # `correlation_cfd_report` (str) covers the whitespace case; `velocity_measured_at_m`
    # (dict) covers the empty-container case -- both are real Facts fields.
    fact_name = "velocity_measured_at_m" if isinstance(empty_value, dict) else "correlation_cfd_report"
    rule = ProjectRule(id="x", source="s", requirement="r", requires_fact=fact_name)
    ctx = replace(base_ctx, facts=Facts(**{fact_name: Fact(value=empty_value, evidence=ev)}))

    outcome = project_rules._check(rule)(ctx)
    assert outcome.verdict is Verdict.NEEDS_EVIDENCE
    assert "empty" in outcome.found


def test_a_reloaded_calibration_change_is_picked_up_and_the_provenance_hash_matches_it(
        monkeypatch, tmp_path):
    """Residual item 1: `load_calibration` is process-cached, so a calibration edited
    on disk must not be picked up until something calls `reload_calibration()` -- and
    once it is, the report's provenance hash must describe exactly that content, not a
    fresh-off-disk read that could disagree with what the Tier 1 runs above actually
    used."""
    real_dir = presets.PRESET_DIR
    tmp_presets = tmp_path / "presets"
    shutil.copytree(real_dir, tmp_presets)
    cal_path = tmp_presets / "calibration.json"
    original = json.loads(cal_path.read_text())

    monkeypatch.setattr(presets, "PRESET_DIR", tmp_presets)
    presets.reload_calibration()
    try:
        before = check.run(SPEC)

        mutated = json.loads(json.dumps(original))
        mutated["mist"]["flank_reach_factor"]["value"] *= 1.5
        cal_path.write_text(json.dumps(mutated))

        # Without a reload, the process-cached calibration is still in effect, and the
        # report must say so honestly -- the hash must not change on its own.
        stale = check.run(SPEC)
        assert stale.provenance["calibration"] == before.provenance["calibration"]

        presets.reload_calibration()
        after = check.run(SPEC)
        assert after.provenance["calibration"] != before.provenance["calibration"]
        expected = hashlib.sha256(
            json.dumps(presets.load_calibration(), sort_keys=True).encode()
        ).hexdigest()[:check.CALIBRATION_HASH_CHARS]
        assert after.provenance["calibration"] == expected
    finally:
        monkeypatch.setattr(presets, "PRESET_DIR", real_dir)
        presets.reload_calibration()


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

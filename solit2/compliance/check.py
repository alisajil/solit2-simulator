"""Run every clause against a spec and say how far from compliant the test is."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from solit2.compliance.context import Context
from solit2.compliance.project_rules import load_project_rules
from solit2.compliance.rules import REGISTRY
from solit2.compliance.rules.base import Rule, evaluate
from solit2.compliance.spec import load_spec
from solit2.compliance.verdict import Finding, Headline, Verdict, headline
from solit2.engines.reduced import envelope
from solit2.reports import test_plan
from solit2.schema.presets import CALIBRATION_HASH_CHARS, calibration_hash


@dataclass(frozen=True)
class ComplianceReport:
    spec_name: str
    spec_path: Path
    findings: tuple[Finding, ...]
    headline: Headline
    provenance: dict[str, str]

    @property
    def blockers(self) -> tuple[Finding, ...]:
        return tuple(f for f in self.findings
                     if f.verdict in (Verdict.FAILS, Verdict.NEEDS_EVIDENCE))


def _check_deviations(rules: tuple[Rule, ...], deviation_ids) -> None:
    by_id = {r.id: r for r in rules}
    for rule_id in deviation_ids:
        if rule_id not in by_id:
            raise ValueError(f"deviation names unknown rule {rule_id!r}")
        if not by_id[rule_id].waivable:
            raise ValueError(f"deviation on {rule_id!r} ({by_id[rule_id].clause}) is refused: "
                             "that clause is not waivable -- SOLIT2 gives the authority no "
                             "allowance to accept a shortfall on it")


def run(spec_path: str | Path) -> ComplianceReport:
    loaded = load_spec(spec_path)
    rules = REGISTRY + (load_project_rules(loaded.project_rules_path)
                        if loaded.project_rules_path else ())
    _check_deviations(rules, loaded.spec.deviations)
    results = {cls: envelope.run(d) for cls, d in loaded.tests.items()}
    installation_result = envelope.run(loaded.installation)
    ctx = Context(tests=loaded.tests, test_results=results, installation=loaded.installation,
                  installation_result=installation_result, facts=loaded.spec.facts,
                  protocol_text={cls: test_plan.render(d, results[cls])
                                 for cls, d in loaded.tests.items()})
    findings = tuple(evaluate(r, ctx, loaded.spec.deviations) for r in rules)
    provenance = {f"design_sha.{cls}": res.meta["design_sha"] for cls, res in results.items()}
    provenance["design_sha.installation"] = installation_result.meta["design_sha"]
    provenance["calibration"] = calibration_hash()
    return ComplianceReport(loaded.spec.name, loaded.path, findings, headline(findings), provenance)

"""A rule is one clause: where it comes from, what it asks, and how to judge it."""
from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Literal

from solit2.compliance.context import Context
from solit2.compliance.spec import Deviation
from solit2.compliance.verdict import Finding, Verdict


@dataclass(frozen=True)
class Outcome:
    verdict: Verdict
    found: str
    required: str
    basis: str
    evidence: str = ""
    fact: str = ""


@dataclass(frozen=True)
class Rule:
    id: str
    group: str
    clause: str
    requirement: str
    kind: Literal["design", "lab", "transfer", "project"]
    check: Callable[[Context], Outcome]
    # SOLIT2 lets the authority accept a shortfall on this clause (Annex 7 §3.6
    # does for the test tunnel; the main document states no such allowance).
    waivable: bool = False
    # Names of the guidance.py constants this rule reads, so a test can prove
    # every requirement in guidance.py is checked by something.
    constants: tuple[str, ...] = ()


def judge(ok: bool, found: str, required: str, basis: str, evidence: str = "") -> Outcome:
    return Outcome(Verdict.COMPLIES if ok else Verdict.FAILS, found, required, basis, evidence)


def needs(fact: str, required: str, why: str = "not supplied") -> Outcome:
    return Outcome(Verdict.NEEDS_EVIDENCE, why, required, "spec fact", fact=fact)


def not_applicable(why: str) -> Outcome:
    return Outcome(Verdict.NOT_APPLICABLE, why, "—", "—")


def evaluate(rule: Rule, ctx: Context, deviations: Mapping[str, Deviation]) -> Finding:
    try:
        out = rule.check(ctx)
    except Exception as exc:  # a crashing rule must stop the check, never pass quietly
        raise RuntimeError(f"rule {rule.id} ({rule.clause}) could not be evaluated: {exc}") from exc
    verdict, note = out.verdict, ""
    dev = deviations.get(rule.id)
    if dev is not None and verdict is Verdict.FAILS:
        verdict, note = Verdict.DEVIATION_ACCEPTED, dev.cite()
    return Finding(rule_id=rule.id, group=rule.group, clause=rule.clause,
                   requirement=rule.requirement, kind=rule.kind, verdict=verdict,
                   found=out.found, required=out.required, basis=out.basis,
                   evidence=out.evidence, fact=out.fact, deviation=note)

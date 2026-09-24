"""What the compliance checker concludes about one clause, and about all of them.

Five verdicts, because "not met" and "not known" are different findings and a
checker that merged them could report a test as compliant nobody had evidenced.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum


class Verdict(str, Enum):
    COMPLIES = "complies"
    FAILS = "fails"
    # Not met, but an authority's acceptance is on record -- only for clauses
    # SOLIT2 lets the authority accept (see Rule.waivable).
    DEVIATION_ACCEPTED = "deviation_accepted"
    # The fact that decides the clause has not been supplied. Never a pass.
    NEEDS_EVIDENCE = "needs_evidence"
    NOT_APPLICABLE = "not_applicable"


@dataclass(frozen=True)
class Finding:
    rule_id: str
    group: str
    clause: str
    requirement: str
    kind: str
    verdict: Verdict
    found: str
    required: str
    basis: str
    evidence: str = ""
    # For a Needs-evidence finding: the spec fact that would decide it.
    fact: str = ""
    # For an accepted deviation: who accepted it, where, and why.
    deviation: str = ""


@dataclass(frozen=True)
class Headline:
    applicable: int
    complying: int
    by_deviation: int
    fails: int
    needs_evidence: int

    @property
    def full(self) -> bool:
        """100 % only with nothing failing and nothing unevidenced."""
        return self.applicable > 0 and self.fails == 0 and self.needs_evidence == 0

    @property
    def text(self) -> str:
        out = f"{self.complying} of {self.applicable} applicable clauses comply"
        if self.by_deviation:
            out += f" ({self.by_deviation} by accepted deviation)"
        if self.full:
            out += " — 100 %"
        return out


def headline(findings: Iterable[Finding]) -> Headline:
    verdicts = [f.verdict for f in findings]
    by_deviation = verdicts.count(Verdict.DEVIATION_ACCEPTED)
    return Headline(
        applicable=sum(v is not Verdict.NOT_APPLICABLE for v in verdicts),
        complying=verdicts.count(Verdict.COMPLIES) + by_deviation,
        by_deviation=by_deviation,
        fails=verdicts.count(Verdict.FAILS),
        needs_evidence=verdicts.count(Verdict.NEEDS_EVIDENCE),
    )

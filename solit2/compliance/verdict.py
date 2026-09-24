"""What the compliance checker concludes about one clause, and about all of them.

Five verdicts, because "not met" and "not known" are different findings and a
checker that merged them could report a test as compliant nobody had evidenced.
"""
from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from enum import Enum
from typing import Literal

# How trustworthy the value behind a finding is: a laboratory measurement, a
# design value the test programme has committed to, or a Tier 1 prediction
# that stands only until the test measures it. Independent of `Rule.kind`,
# which says which registry a rule lives in, not how firm its number is.
BasisKind = Literal["evidenced", "planned", "predicted"]


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
    # The kind of value `basis` describes -- see `BasisKind`. Needs-evidence
    # and Not-applicable findings still carry the kind the clause WOULD be
    # judged on, so the headline's breakdown never has to guess.
    basis_kind: BasisKind
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
    # Complying findings (COMPLIES or DEVIATION_ACCEPTED), split by basis kind.
    # These three always sum to `complying` -- the whole point of I6 is that a
    # single "% comply" figure must not blur a lab measurement into a Tier 1
    # prediction of the same clause.
    evidenced: int = 0
    planned: int = 0
    predicted: int = 0

    @property
    def full(self) -> bool:
        """100 % only with nothing failing and nothing unevidenced."""
        return self.applicable > 0 and self.fails == 0 and self.needs_evidence == 0

    @property
    def text(self) -> str:
        out = f"{self.complying} of {self.applicable} applicable clauses comply"
        notes = []
        if self.by_deviation:
            notes.append(f"{self.by_deviation} by accepted deviation")
        for count, label in ((self.evidenced, "evidenced"),
                             (self.planned, "from the planned design"),
                             (self.predicted, "predicted")):
            if count:
                notes.append(f"{count} {label}")
        if notes:
            out += " (" + ", ".join(notes) + ")"
        if self.full:
            out += " — 100 %"
        return out


def headline(findings: Iterable[Finding]) -> Headline:
    findings = list(findings)
    verdicts = [f.verdict for f in findings]
    by_deviation = verdicts.count(Verdict.DEVIATION_ACCEPTED)
    complying = [f for f in findings if f.verdict in (Verdict.COMPLIES, Verdict.DEVIATION_ACCEPTED)]
    return Headline(
        applicable=sum(v is not Verdict.NOT_APPLICABLE for v in verdicts),
        complying=len(complying),
        by_deviation=by_deviation,
        fails=verdicts.count(Verdict.FAILS),
        needs_evidence=verdicts.count(Verdict.NEEDS_EVIDENCE),
        evidenced=sum(f.basis_kind == "evidenced" for f in complying),
        planned=sum(f.basis_kind == "planned" for f in complying),
        predicted=sum(f.basis_kind == "predicted" for f in complying),
    )

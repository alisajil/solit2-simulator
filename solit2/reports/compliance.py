"""The compliance matrix as a document for the main contractor and the authority."""
from __future__ import annotations

from solit2.compliance.check import ComplianceReport
from solit2.compliance.verdict import Finding, Verdict

MARK = {Verdict.COMPLIES: "✅ complies", Verdict.FAILS: "❌ fails",
        Verdict.DEVIATION_ACCEPTED: "🟦 deviation accepted",
        Verdict.NEEDS_EVIDENCE: "🟧 needs evidence", Verdict.NOT_APPLICABLE: "— n/a"}


def _cell(text: str) -> str:
    return text.replace("|", "\\|").replace("\n", " ")


def _row(f: Finding) -> str:
    note = f.deviation or f.evidence
    return (f"| {f.rule_id} | {_cell(f.clause)} | {_cell(f.requirement)} | {_cell(f.found)} | "
            f"{_cell(f.required)} | {MARK[f.verdict]} | {_cell(f.basis)} | {_cell(note)} |")


HEADER = ("| rule | clause | requirement (paraphrased) | found | required | verdict | basis | "
          "evidence / deviation |\n|---|---|---|---|---|---|---|---|")


def by_group(findings: list[Finding]) -> list[tuple[str, list[Finding]]]:
    """Findings bucketed by group, groups in first-seen order, findings in registry order.
    `itertools.groupby` would split a group whose rules come from two rule modules."""
    buckets: dict[str, list[Finding]] = {}
    for f in findings:
        buckets.setdefault(f.group, []).append(f)
    return list(buckets.items())


def render(report: ComplianceReport) -> str:
    h = report.headline
    lines = [f"# SOLIT² compliance — {report.spec_name}", "",
             f"**{h.text}.** Fails: {h.fails}. Needs evidence: {h.needs_evidence}.", "",
             "Needs evidence is never counted as compliant. Values marked *predicted* are "
             "Tier 1 predictions until the test measures them.", "",
             "Provenance: " + ", ".join(f"{k} `{v}`" for k, v in sorted(report.provenance.items())),
             "", "## Blockers", ""]
    lines += ([HEADER] + [_row(f) for f in report.blockers]) if report.blockers else ["None."]
    lines += ["", "## Clause matrix"]
    for group, items in by_group(report.findings):
        lines += ["", f"### {group}", "", HEADER] + [_row(f) for f in items]
    lines += ["", "## What the laboratory and the authority must supply", "", lab_checklist(report)]
    return "\n".join(lines) + "\n"


def lab_checklist(report: ComplianceReport) -> str:
    wanted: dict[str, list[str]] = {}
    for f in report.findings:
        if f.verdict is Verdict.NEEDS_EVIDENCE and f.fact:
            wanted.setdefault(f.fact, []).append(f"{f.clause} ({f.rule_id})")
    if not wanted:
        return "Nothing outstanding."
    return "\n".join(f"- [ ] `{fact}` — for {', '.join(clauses)}"
                     for fact, clauses in sorted(wanted.items()))

from solit2.compliance.verdict import Finding, Verdict, headline


def _f(verdict: Verdict, rule_id: str = "r") -> Finding:
    return Finding(rule_id=rule_id, group="g", clause="§1", requirement="req", kind="design",
                   verdict=verdict, found="x", required="y", basis="b")


def test_not_applicable_is_excluded_from_the_count():
    h = headline([_f(Verdict.COMPLIES), _f(Verdict.NOT_APPLICABLE)])
    assert (h.applicable, h.complying) == (1, 1)
    assert h.full and h.text == "1 of 1 applicable clauses comply — 100 %"


def test_needs_evidence_never_rounds_up_to_full():
    h = headline([_f(Verdict.COMPLIES), _f(Verdict.NEEDS_EVIDENCE)])
    assert not h.full
    assert h.text == "1 of 2 applicable clauses comply"


def test_a_fail_blocks_full_and_an_accepted_deviation_counts_but_is_named():
    h = headline([_f(Verdict.COMPLIES), _f(Verdict.DEVIATION_ACCEPTED), _f(Verdict.FAILS)])
    assert (h.complying, h.by_deviation, h.fails) == (2, 1, 1)
    assert not h.full
    assert h.text == "2 of 3 applicable clauses comply (1 by accepted deviation)"


def test_nothing_applicable_is_not_full():
    assert not headline([_f(Verdict.NOT_APPLICABLE)]).full

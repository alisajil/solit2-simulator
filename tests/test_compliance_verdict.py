from solit2.compliance.verdict import Finding, Verdict, headline


def _f(verdict: Verdict, rule_id: str = "r", basis_kind: str = "planned") -> Finding:
    return Finding(rule_id=rule_id, group="g", clause="§1", requirement="req", kind="design",
                   verdict=verdict, found="x", required="y", basis="b", basis_kind=basis_kind)


def test_not_applicable_is_excluded_from_the_count():
    h = headline([_f(Verdict.COMPLIES), _f(Verdict.NOT_APPLICABLE)])
    assert (h.applicable, h.complying) == (1, 1)
    assert h.full
    assert h.text == "1 of 1 applicable clauses comply (1 from the planned design) — 100 %"


def test_needs_evidence_never_rounds_up_to_full():
    h = headline([_f(Verdict.COMPLIES), _f(Verdict.NEEDS_EVIDENCE)])
    assert not h.full
    assert h.text == "1 of 2 applicable clauses comply (1 from the planned design)"


def test_a_fail_blocks_full_and_an_accepted_deviation_counts_but_is_named():
    h = headline([_f(Verdict.COMPLIES), _f(Verdict.DEVIATION_ACCEPTED), _f(Verdict.FAILS)])
    assert (h.complying, h.by_deviation, h.fails) == (2, 1, 1)
    assert not h.full
    assert h.text == "2 of 3 applicable clauses comply (1 by accepted deviation, 2 from the planned design)"


def test_nothing_applicable_is_not_full():
    assert not headline([_f(Verdict.NOT_APPLICABLE)]).full


def test_headline_breaks_down_complying_findings_by_basis_kind():
    """I6: a single "% comply" figure must not blur a lab measurement into a
    Tier 1 prediction of the same clause -- the breakdown is unconditional
    whenever anything complies, not only when the mix is complicated."""
    h = headline([_f(Verdict.COMPLIES, "r1", "evidenced"),
                  _f(Verdict.COMPLIES, "r2", "planned"),
                  _f(Verdict.COMPLIES, "r3", "planned"),
                  _f(Verdict.COMPLIES, "r4", "predicted")])
    assert (h.evidenced, h.planned, h.predicted) == (1, 2, 1)
    assert h.evidenced + h.planned + h.predicted == h.complying
    assert h.text == ("4 of 4 applicable clauses comply "
                       "(1 evidenced, 2 from the planned design, 1 predicted) — 100 %")


def test_needs_evidence_and_fails_do_not_count_toward_the_kind_breakdown():
    h = headline([_f(Verdict.NEEDS_EVIDENCE, "r1", "evidenced"),
                  _f(Verdict.FAILS, "r2", "predicted")])
    assert (h.evidenced, h.planned, h.predicted) == (0, 0, 0)
    assert h.text == "0 of 2 applicable clauses comply"

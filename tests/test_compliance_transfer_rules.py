from dataclasses import replace

import pytest

from solit2.compliance.context import Context
from solit2.compliance.rules.base import evaluate
from solit2.compliance.rules.transfer_rules import RULES
from solit2.compliance.spec import Facts
from solit2.compliance.verdict import Verdict
from solit2.engines.reduced import envelope
from solit2.schema.design import Design

BY_ID = {r.id: r for r in RULES}


def _ctx(test: Design, installation: Design) -> Context:
    return Context(tests={"A": test}, test_results={"A": envelope.run(test)},
                   installation=installation, installation_result=envelope.run(installation),
                   facts=Facts(), protocol_text={})


@pytest.fixture(scope="module")
def same() -> Context:
    a = Design.load("examples/designs/solit2-test-protocol.json")
    return _ctx(a, a)


def _v(rule_id: str, ctx: Context) -> Verdict:
    return evaluate(BY_ID[rule_id], ctx, {}).verdict


def test_an_installation_identical_to_its_test_transfers(same):
    for rule_id in BY_ID:
        assert _v(rule_id, same) is Verdict.COMPLIES, rule_id


def test_a_faster_installation_velocity_than_tested_fails(same):
    inst = same.installation
    fast = inst.model_copy(update={"ventilation": inst.ventilation.model_copy(
        update={"velocity_range_ms": (3.88, 5.08)})})
    ctx = replace(same, installation=fast, installation_result=envelope.run(fast))
    assert _v("annex3.3_3.ventilation", ctx) is Verdict.FAILS
    assert _v("annex7.3_4.no_extrapolation", ctx) is Verdict.FAILS


def test_standoff_may_exceed_the_tested_one_by_twenty_percent_and_no_more(same):
    inst = same.installation
    top = inst.fire.footprint.top_height_m
    tested = inst.nozzles.mounting.height_above_carriageway_m - top

    def at(standoff: float) -> Context:
        mount = inst.nozzles.mounting.model_copy(update={"height_above_carriageway_m": top + standoff})
        moved = inst.model_copy(update={"nozzles": inst.nozzles.model_copy(update={"mounting": mount})})
        return replace(same, installation=moved)

    assert _v("main.3_6_2.standoff", at(tested * 1.2)) is Verdict.COMPLIES
    assert _v("main.3_6_2.standoff", at(tested * 1.21)) is Verdict.FAILS
    assert _v("main.3_6_2.standoff", at(tested * 0.9)) is Verdict.FAILS


def test_no_test_of_the_installations_fire_class_needs_evidence():
    b = Design.load("examples/designs/solit2-test-protocol-class-b.json")
    a = Design.load("examples/designs/solit2-test-protocol.json")
    ctx = Context(tests={"B": b}, test_results={"B": envelope.run(b)}, installation=a,
                  installation_result=envelope.run(a), facts=Facts(), protocol_text={})
    assert _v("annex3.3_3.k_factor", ctx) is Verdict.NEEDS_EVIDENCE


def test_the_transfer_rules_cover_every_test_derived_parameter():
    from solit2.reports import guidance as g
    named = {r.requirement.split("(Annex 3 §3.3: ")[1].rstrip(")") for r in RULES
             if "(Annex 3 §3.3: " in r.requirement}
    assert named == set(g.TEST_DERIVED_PARAMETERS)


def test_an_unknown_test_derived_parameter_is_refused_with_the_valid_names():
    from solit2.compliance.rules import transfer_rules as tr
    with pytest.raises(ValueError, match="use one of"):
        tr._t("x", "Annex 3 §3.3", "req", "Not a parameter", tr._spacing, "req")

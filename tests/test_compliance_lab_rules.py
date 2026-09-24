from dataclasses import replace

import pytest

from solit2.compliance.context import Context
from solit2.compliance.rules.base import evaluate
from solit2.compliance.rules.lab_rules import RULES
from solit2.compliance.spec import Evidence, Fact, Facts, PlannedTest
from solit2.compliance.verdict import Verdict
from solit2.engines.reduced import envelope
from solit2.reports import guidance as g
from solit2.schema.design import Design

EV = Evidence(document="lab report", locator="§2")
BY_ID = {r.id: r for r in RULES}


@pytest.fixture(scope="module")
def ctx() -> Context:
    a = Design.load("examples/designs/solit2-test-protocol.json")
    res = envelope.run(a)
    return Context(tests={"A": a}, test_results={"A": res}, installation=a,
                   installation_result=res, facts=Facts(), protocol_text={})


def _facts(ctx: Context, **facts) -> Context:
    return replace(ctx, facts=Facts(**{k: Fact(value=v, evidence=EV) for k, v in facts.items()}))


def _v(rule_id: str, ctx: Context) -> Verdict:
    return evaluate(BY_ID[rule_id], ctx, {}).verdict


def test_a_lab_clause_with_no_fact_needs_evidence_and_names_the_fact(ctx):
    finding = evaluate(BY_ID["annex7.5_2_4.moisture"], ctx, {})
    assert finding.verdict is Verdict.NEEDS_EVIDENCE
    assert finding.fact == "pallet_moisture_pct"


def test_moisture_boundary(ctx):
    assert _v("annex7.5_2_4.moisture", _facts(ctx, pallet_moisture_pct=18.0)) is Verdict.COMPLIES
    assert _v("annex7.5_2_4.moisture", _facts(ctx, pallet_moisture_pct=18.1)) is Verdict.FAILS


def test_a_complying_fact_carries_its_evidence(ctx):
    finding = evaluate(BY_ID["annex7.5_2_4.moisture"], _facts(ctx, pallet_moisture_pct=14.0), {})
    assert finding.evidence == "lab report, §2"


def test_one_rule_per_instrument_type_and_per_schedule_item():
    assert sum(r.constants == ("INSTRUMENT_SPEC",) for r in RULES) == len(g.INSTRUMENT_SPEC)
    assert (sum(r.constants == ("MAIN_MEASUREMENT_SCHEDULE",) for r in RULES)
            == len(g.MAIN_MEASUREMENT_SCHEDULE))


def test_the_four_required_table_4_tests_must_each_be_planned(ctx):
    planned = [PlannedTest(fire_class="A", covered=True, velocity_ms=1.5),
               PlannedTest(fire_class="A", covered=True, velocity_ms=3.0),
               PlannedTest(fire_class="B", covered=False, velocity_ms=1.5)]
    with_three = _facts(ctx, planned_tests=planned)
    assert _v("annex7.5_4.test_1", with_three) is Verdict.COMPLIES
    assert _v("annex7.5_4.test_4", with_three) is Verdict.FAILS


def test_activation_option_b_cannot_be_judged(ctx):
    assert _v("annex7.5_2_8.option", _facts(ctx, activation_option="A")) is Verdict.COMPLIES
    assert _v("annex7.5_2_8.option", _facts(ctx, activation_option="B")) is Verdict.NEEDS_EVIDENCE


def test_spray_deviation_must_cover_every_listed_velocity(ctx):
    assert _v("main.3_6_2.spray_deviation",
              _facts(ctx, spray_deviation_tested_ms=[1.0, 3.0])) is Verdict.FAILS
    assert _v("main.3_6_2.spray_deviation",
              _facts(ctx, spray_deviation_tested_ms=[1.0, 3.0, 5.0])) is Verdict.COMPLIES

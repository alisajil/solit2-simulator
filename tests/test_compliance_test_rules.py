from dataclasses import replace

import pytest

from solit2.compliance.context import Context
from solit2.compliance.rules.base import evaluate
from solit2.compliance.rules.test_rules import RULES
from solit2.compliance.spec import Deviation, Facts
from solit2.compliance.verdict import Verdict
from solit2.engines.reduced import envelope
from solit2.schema.design import Design

A = "examples/designs/solit2-test-protocol.json"
B = "examples/designs/solit2-test-protocol-class-b.json"
INSTALL = "examples/designs/road-tunnel-twin-bore.json"
BY_ID = {r.id: r for r in RULES}


@pytest.fixture(scope="module")
def ctx() -> Context:
    tests = {"A": Design.load(A), "B": Design.load(B)}
    inst = Design.load(INSTALL)
    return Context(tests=tests, test_results={k: envelope.run(d) for k, d in tests.items()},
                   installation=inst, installation_result=envelope.run(inst),
                   facts=Facts(), protocol_text={})


def _with_tunnel(ctx: Context, **tunnel) -> Context:
    a = ctx.tests["A"]
    moved = a.model_copy(update={"tunnel": a.tunnel.model_copy(update=tunnel)})
    return replace(ctx, tests={**ctx.tests, "A": moved})


def _verdict(rule_id: str, ctx: Context, deviations=None) -> Verdict:
    return evaluate(BY_ID[rule_id], ctx, deviations or {}).verdict


def test_rule_ids_are_unique_and_every_rule_cites_a_clause():
    assert len(BY_ID) == len(RULES)
    assert all(r.clause.startswith(("Annex 7", "Main", "Annex 3")) for r in RULES)


def test_the_test_tunnel_area_boundary_is_the_annex_7_figure(ctx):
    assert _verdict("annex7.3_6.free_area", _with_tunnel(ctx, area_m2=40.0)) is Verdict.COMPLIES
    assert _verdict("annex7.3_6.free_area", _with_tunnel(ctx, area_m2=39.9)) is Verdict.FAILS


def test_the_stricter_main_document_height_governs(ctx):
    at_4_8 = _with_tunnel(ctx, height_m=4.8)
    assert _verdict("annex7.3_6.height", at_4_8) is Verdict.COMPLIES
    assert _verdict("main.3_6_2.height", at_4_8) is Verdict.FAILS


def test_an_accepted_deviation_applies_only_where_solit2_allows_it(ctx):
    small = _with_tunnel(ctx, area_m2=39.0)
    dev = {"annex7.3_6.free_area": Deviation(accepted_by="authority", document="letter",
                                             locator="§1", reason="reason")}
    finding = evaluate(BY_ID["annex7.3_6.free_area"], small, dev)
    assert finding.verdict is Verdict.DEVIATION_ACCEPTED
    assert "accepted by authority" in finding.deviation
    assert not BY_ID["main.3_6_2.height"].waivable


def test_class_b_rules_need_evidence_when_no_class_b_design_is_given(ctx):
    only_a = replace(ctx, tests={"A": ctx.tests["A"]},
                     test_results={"A": ctx.test_results["A"]})
    assert _verdict("annex7.5_3_1.hrr", only_a) is Verdict.NEEDS_EVIDENCE
    assert _verdict("annex7.5_3_1.hrr", ctx) is Verdict.COMPLIES


def test_the_example_class_a_mock_up_meets_its_geometry_clauses(ctx):
    for rule_id in ("annex7.5_2_1.potential", "annex7.5_2_2.pallets", "annex7.5_2_2.energy",
                    "annex7.5_2_2.height", "annex7.5_2_2.fuel_height", "annex7.5_2_2.width",
                    "annex7.5_2_2.length", "annex7.5_2_3.wall_clearance", "annex7.5_2_6.target",
                    "annex7.5_4.covered", "annex7.5_2_8.area"):
        assert _verdict(rule_id, ctx) is Verdict.COMPLIES, rule_id


def test_discharge_shorter_than_thirty_minutes_after_activation_fails(ctx):
    a = ctx.tests["A"]
    short = a.model_copy(update={"zones": a.zones.model_copy(update={"duration_min": 20.0})})
    shorter = replace(ctx, tests={**ctx.tests, "A": short},
                      test_results={**ctx.test_results, "A": envelope.run(short)})
    assert _verdict("annex7.5_2_8.discharge", shorter) is Verdict.FAILS

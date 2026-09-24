import json
from dataclasses import replace
from pathlib import Path

import pytest

from solit2.compliance.context import Context, time_to_full_operation_s
from solit2.compliance.rules.base import evaluate
from solit2.compliance.rules.transfer_rules import RULES
from solit2.compliance.spec import Evidence, Fact, Facts
from solit2.compliance.verdict import Verdict
from solit2.engines.reduced import envelope
from solit2.schema.design import Design

BY_ID = {r.id: r for r in RULES}
EV = Evidence(document="LHDS and pump data", locator="§1")


def _ctx(test: Design, installation: Design) -> Context:
    return Context(tests={"A": test}, test_results={"A": envelope.run(test)},
                   installation=installation, installation_result=envelope.run(installation),
                   facts=Facts(), protocol_text={})


@pytest.fixture(scope="module")
def same() -> Context:
    """Test and installation are the SAME design -- exactly the "placeholder
    timings copied into both designs" case I2 describes. `annex7.3_2.response`
    now needs an evidenced `installation_response_s` fact rather than the
    installation's own Tier 1 prediction, so this fixture supplies one equal
    to the test's Tier 1 time -- the installation genuinely IS the test here,
    so a fact that says so is not fabricated evidence, just the fixture's
    stand-in for "the site is evidenced to match its own test"."""
    a = Design.load("examples/designs/solit2-test-protocol.json")
    ctx = _ctx(a, a)
    response_s = time_to_full_operation_s(ctx.test_results["A"])
    facts = Facts(installation_response_s=Fact(value=response_s, evidence=EV))
    return replace(ctx, facts=facts)


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
        tr._t("x", "Annex 3 §3.3", "req", "Not a parameter", tr._spacing, "req", "planned")


def test_no_extrapolation_takes_the_weakest_basis_kind_among_its_sub_checks(same):
    """Residual item 2: fire_at_activation is "predicted" and every other sub-check
    here is "planned" -- the aggregate must be the WEAKEST of the two (predicted),
    computed from what the sub-checks actually returned, not a hard-coded "planned"
    that stops being true the moment a predicted sub-check joins the set."""
    finding = evaluate(BY_ID["annex7.3_4.no_extrapolation"], same, {})
    assert finding.verdict is Verdict.COMPLIES
    assert finding.basis_kind == "predicted"


def test_no_extrapolation_is_needs_evidence_not_fails_on_an_undeclared_test_velocity(same):
    """Residual item 4: a sub-check with no evidence (here, ventilation on a test
    design that never declared its tested velocity range) is unknown, not a breach --
    it must read as Needs evidence, naming that sub-check's fact, never as Fails."""
    raw = json.loads(Path("examples/designs/road-tunnel-twin-bore.json").read_text())
    del raw["ventilation"]["velocity_range_ms"]
    # The installation already declares 3.88-5.08 m/s, the schema's own default, so
    # this "test" design -- built without declaring the field at all -- ends up
    # simulated at the SAME actual velocity. Every other sub-check therefore still
    # compares two physically identical designs and complies; only `_ventilation`'s
    # check of `model_fields_set` (not of the resolved value) can tell the two apart.
    installation = Design.load("examples/designs/road-tunnel-twin-bore.json")
    undeclared_test = Design.from_dict(raw)
    ctx = Context(tests={"A": undeclared_test}, test_results={"A": envelope.run(undeclared_test)},
                  installation=installation, installation_result=envelope.run(installation),
                  facts=Facts(), protocol_text={})
    finding = evaluate(BY_ID["annex7.3_4.no_extrapolation"], ctx, {})
    assert finding.verdict is Verdict.NEEDS_EVIDENCE
    assert finding.fact == "planned_tests"

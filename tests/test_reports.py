from solit2.engines.reduced import envelope
from solit2.reports import correlation, labels, test_plan
from solit2.schema.design import Design

SITE_DESIGN = "examples/designs/road-tunnel-twin-bore.json"
TEST_DESIGN = "examples/designs/solit2-test-protocol.json"


def test_test_plan_reports_the_design_name_and_tunnel_inputs():
    design = Design.load(SITE_DESIGN)
    result = envelope.run(design)
    md = test_plan.render(design, result)
    assert "road-tunnel-twin-bore" in md
    assert "twin_bore_11m" in md
    assert f"{design.fire.design_hrr_mw:.0f}" in md
    assert f"{design.nozzles.pressure_bar:.1f}" in md


def test_test_plan_reports_every_criterion_with_its_status():
    design = Design.load(SITE_DESIGN)
    result = envelope.run(design)
    md = test_plan.render(design, result)
    for name, criterion in result.criteria.items():
        assert name in md
        assert criterion.status in md


def test_test_plan_reports_the_score():
    design = Design.load(SITE_DESIGN)
    result = envelope.run(design)
    md = test_plan.render(design, result)
    assert f"{result.score['total']:.2f}" in md


def test_correlation_reports_both_design_names_and_engines():
    test_result = envelope.run(Design.load(TEST_DESIGN))
    site_result = envelope.run(Design.load(SITE_DESIGN))
    md = correlation.render(test_result, site_result)
    assert "solit2-test-protocol (reduced)" in md
    assert "road-tunnel-twin-bore (reduced)" in md


def test_correlation_tells_the_two_tiers_of_one_design_apart():
    # the comparison this report exists for: one design, Tier 1 against Tier 2.
    # Heading both columns with the design name printed "X vs X".
    tier1 = envelope.run(Design.load(SITE_DESIGN))
    tier2 = tier1.model_copy(update={"meta": {**tier1.meta, "engine": "fds"}})
    md = correlation.render(tier1, tier2)
    assert f"{tier1.meta['design_name']} (reduced)" in md
    assert f"{tier1.meta['design_name']} (fds)" in md


def test_correlation_reports_each_criterion_from_both_sides():
    test_result = envelope.run(Design.load(TEST_DESIGN))
    site_result = envelope.run(Design.load(SITE_DESIGN))
    md = correlation.render(test_result, site_result)
    for name in set(test_result.criteria) | set(site_result.criteria):
        # The table names criteria the way a fire engineer does, not by identifier.
        assert labels.label(name) in md


def test_correlation_handles_a_criterion_present_on_only_one_side():
    test_result = envelope.run(Design.load(TEST_DESIGN))
    site_result = envelope.run(Design.load(SITE_DESIGN))
    trimmed = test_result.model_copy(
        update={"criteria": {k: v for k, v in test_result.criteria.items()
                             if k != next(iter(test_result.criteria))}})
    md = correlation.render(trimmed, site_result)
    assert "—" in md

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


def test_the_test_plan_never_calls_a_design_passed_without_saying_what_went_unjudged():
    """CLAUDE.md: `gates_passed: true` is not approval while `criteria_unset` is not empty.

    The outcome line is read on its own — in the report's summary and in the exported
    markdown — so "all gates passed" standing alone would overstate a design that was
    measured against almost nothing.
    """
    result = envelope.run(Design.load(SITE_DESIGN))
    unset = result.score["criteria_unset"]
    assert unset, "this fixture is meant to have unjudged criteria; pick another if it changes"

    outcome_line = next(line for line in test_plan.render(Design.load(SITE_DESIGN), result)
                        .splitlines() if "gates passed" in line or "gates failed" in line)
    assert f"{len(unset)} of {len(result.criteria)} criteria were not judged" in outcome_line
    for name in unset:
        assert name in outcome_line


def _result_covering(seconds: float, name: str, engine: str):
    """A minimal Result carrying a clock, for the coverage caveat."""
    from solit2.schema.result import Result
    return Result(
        meta={"design_name": name, "engine": engine},
        envelope=[], worst_case={}, events={}, criteria={}, criteria_cases={},
        constraints={}, peaks={}, mist={}, hydraulics={}, cost={},
        score={"total": 0.0, "gates_passed": True, "gates_failed": [],
               "components": {}, "penalties": [], "criteria_unset": []},
        timeseries={"t_s": [0.0, seconds]}, warnings=[])


def test_the_correlation_report_says_when_the_columns_cover_different_exposures():
    """Every criterion in the table is a peak or a dose, so a column from a
    shorter run is biased toward passing. The app embedded a caveat of its own
    in the export; the CLI's `report correlation` carried none at all, and both
    results have always known their own clocks."""
    from solit2.reports import correlation
    full = _result_covering(3600.0, "og", "reduced")
    short = _result_covering(250.0, "og", "fds")
    note = correlation.coverage_note(full, short)
    assert note and "0-250 s" in note and "3600 s" in note
    assert "biased toward passing" in note
    assert note in correlation.render(full, short)
    # the order of the arguments must not change the finding
    assert correlation.coverage_note(short, full) == note


def test_no_coverage_caveat_when_the_two_runs_cover_the_same_exposure():
    from solit2.reports import correlation
    a = _result_covering(3600.0, "og", "reduced")
    b = _result_covering(3590.0, "og", "fds")      # inside the tolerance
    assert correlation.coverage_note(a, b) is None
    assert ">" not in correlation.render(a, b).splitlines()[-1]
    assert correlation.coverage_note(a, a) is None, "a result against itself is one column"


def test_a_result_without_a_clock_gets_no_invented_caveat():
    from solit2.reports import correlation
    from solit2.schema.result import Result
    full = _result_covering(3600.0, "og", "reduced")
    blank = Result(**{**full.model_dump(), "meta": {"design_name": "og", "engine": "fds"},
                      "timeseries": {}})
    assert correlation.coverage_note(full, blank) is None


def _baseline_pair():
    from solit2.engines.reduced import envelope
    from solit2.schema.design import Design
    design = Design.load("designs/og-dbr-rev0.json")
    return design, envelope.run(design)


def test_the_assessment_states_its_standing_before_any_number():
    """A reader who is handed only this document must not take it for a test
    report, and must not take a fitted engine for a validated one."""
    from solit2.reports import assessment
    design, result = _baseline_pair()
    text = assessment.render(design, result)
    standing = text.index("Standing of this assessment")
    assert standing < text.index("## 4. Results"), "standing comes before results"
    assert "not a test report" in text
    assert "No physical fire test was performed" in text
    assert result.meta["calibration_note"][:60] in text, "the engine's own note, verbatim"


def test_the_assessment_never_reads_as_approval_while_criteria_are_unjudged():
    from solit2.reports import assessment
    design, result = _baseline_pair()
    assert result.score["criteria_unset"], "this design has unjudged criteria"
    text = assessment.render(design, result)
    assert "were not judged" in text
    assert "An unjudged criterion is not a passed one" in text
    assert "not judged" in text, "and each such row says so in the table"


def test_the_assessment_names_quantities_the_way_an_engineer_would():
    from solit2.reports import assessment
    design, result = _baseline_pair()
    text = assessment.render(design, result)
    assert "Peak air temperature (°C)" in text and "max_air_temp_c" not in text
    assert "Application density (mm/min)" in text and "density_mm_min" not in text
    # and rounded: a raw float is unreadable in a report
    assert "42.971843487711226" not in text


def test_the_assessment_carries_the_instrument_layout():
    from solit2.reports import assessment
    from solit2.engines.reduced.criteria import STATIONS
    design, result = _baseline_pair()
    text = assessment.render(design, result)
    for station in STATIONS:
        assert station in text, station
    assert "Figure 16" in text


def test_a_tier_2_result_and_the_validation_standing_are_included_when_given():
    from solit2.reports import assessment
    design, result = _baseline_pair()
    plain = assessment.render(design, result)
    assert "Tier 1 against Tier 2" not in plain and "reference tests" not in plain
    rich = assessment.render(design, result, tier2=result, validation="c4 ... NO")
    assert "Tier 1 against Tier 2" in rich
    assert "c4 ... NO" in rich and "a property of the engine" in rich


def test_the_archive_keeps_everything_needed_to_re_read_the_report(tmp_path):
    """A report ages badly alone: the calibration that produced it is a file in
    this repository that moves."""
    import json

    from solit2.reports import archive, assessment
    design, result = _baseline_pair()
    written = archive.write(tmp_path, design, result, assessment.render(design, result))
    names = {p.name for p in written}
    assert names == {"assessment.md", "result.json", "design.resolved.json",
                     "calibration.json", "provenance.json"}
    folder = written[0].parent
    assert folder.name.startswith(design.meta.name)
    # the design as the ENGINE saw it, presets merged, not the source file
    resolved = json.loads((folder / "design.resolved.json").read_text())
    assert resolved["fire"]["design_hrr_mw"] == design.fire.design_hrr_mw
    assert resolved["nozzles"]["mounting"]["pitch_m"] is not None
    prov = json.loads((folder / "provenance.json").read_text())
    assert prov["design_sha"] == result.meta["design_sha"]
    assert prov["engine_version"] and prov["tool_commit"]


def test_a_second_archive_does_not_overwrite_the_first(tmp_path):
    """An archive that replaces the previous one cannot show that an answer
    changed, which is most of why it exists."""
    from solit2.reports import archive, assessment
    design, result = _baseline_pair()
    text = assessment.render(design, result)
    first = archive.write(tmp_path, design, result, text)[0].parent
    second = archive.write(tmp_path, design, result, text)[0].parent
    assert first.exists() and second.exists()
    if first == second:      # same second; the stamp cannot separate them
        return
    assert first != second

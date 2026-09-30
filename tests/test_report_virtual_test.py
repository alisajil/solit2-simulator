# tests/test_report_virtual_test.py
import functools
import html as stdlib_html

from solit2.compliance import check as compliance_check
from solit2.compliance.spec import load_spec
from solit2.engines.reduced import envelope, sim
from solit2.reports import cfd_runs, labels
from solit2.reports import virtual_test

SPEC = "examples/compliance/solit2-example.spec.json"


@functools.lru_cache(maxsize=1)
def _loaded_and_results():
    loaded = load_spec(SPEC)
    results = {cls: envelope.run(d) for cls, d in loaded.tests.items()}
    return loaded, results


@functools.lru_cache(maxsize=1)
def _inputs():
    loaded, results = _loaded_and_results()
    traces = {cls: sim.run_once(loaded.tests[cls], r.worst_case["section"],
                                r.worst_case["velocity_ms"])
              for cls, r in results.items()}
    return loaded, results, traces


@functools.lru_cache(maxsize=1)
def _compliance():
    return compliance_check.run(SPEC)


COMMIT = "0123abc (working tree modified)"


def _render(**overrides):
    """(loaded, results, html). Later tasks add their required keywords here."""
    loaded, results, traces = _inputs()
    kwargs = {"traces": traces, "cfd": {cls: cfd_runs.NOT_RUN for cls in loaded.tests},
              "compliance": _compliance(), "commit": COMMIT, **overrides}
    return loaded, results, virtual_test.render(loaded, results, **kwargs)


def test_every_page_carries_the_prediction_band():
    loaded, results, out = _render()
    # One band per section plus one in the header; at minimum one per rendered section.
    assert out.count(virtual_test.html.BAND_TEXT) >= 2


def test_the_document_names_both_test_designs():
    loaded, results, out = _render()
    assert loaded.tests["A"].meta.name in out
    assert loaded.tests["B"].meta.name in out


def test_the_document_makes_no_network_reference():
    loaded, results, out = _render()
    # Not a substring test: once Task 6 embeds Plotly, the bundle's own JS strings
    # contain https:// text that is never fetched. external_references() skips
    # script bodies and catches every tag or CSS rule that would fetch something.
    assert virtual_test.html.external_references(out) == []


def test_facility_section_states_each_designs_own_geometry():
    loaded, results, out = _render()
    from solit2.engines.reduced.geometry import section_geometry
    for design in loaded.tests.values():
        geom = section_geometry(design)
        assert f"{geom.road_width_m:.2f}" in out


def test_water_mist_system_states_pressure_and_active_head_count():
    loaded, results, out = _render()
    for design in loaded.tests.values():
        assert f"{design.nozzles.pressure_bar:.1f}" in out
        assert str(design.active_heads) in out


def test_fire_load_states_the_design_hrr_and_covered_flag():
    loaded, results, out = _render()
    for design in loaded.tests.values():
        assert f"{design.fire.design_hrr_mw:.0f}" in out


def test_instruments_section_names_every_modelled_station():
    from solit2.engines.reduced.criteria import STATIONS
    loaded, results, out = _render()
    for station in STATIONS:
        assert station in out


def test_procedure_section_shows_limit_not_set_for_an_unset_criterion():
    loaded, results, out = _render()
    # examples/compliance/solit2-example.spec.json's designs carry an empty
    # `ahj` block (see examples/designs/solit2-test-protocol*.json), so every
    # criterion beyond target_ignited is unset.
    assert "limit not set" in out


def test_the_results_summary_states_each_tests_engine_peaks():
    loaded, results, out = _render()
    assert "<h2>8. Results</h2>" in out
    for result in results.values():
        assert labels.with_unit("hrr_mw", result.peaks["hrr_mw"]) in out
        assert labels.with_unit("hrr_free_burn_mw", result.peaks["hrr_free_burn_mw"]) in out
        assert labels.with_unit("ceiling_temp_c", result.peaks["ceiling_temp_c"]) in out


def test_criteria_counts_split_met_not_met_and_not_set():
    from solit2.schema.result import Criterion
    result = _loaded_and_results()[1]["A"].model_copy(update={"criteria": {
        "max_air_temp_c": Criterion.build(300.0, 250.0, "<=", True),      # fail
        "max_heat_flux_kwm2": Criterion.build(2.0, 5.0, "<=", True),       # pass
        "min_visibility_m": Criterion.build(10.0, None, ">=", True),       # unset
        "target_ignited": Criterion.build(False, None, "is_false", True),  # pass
    }})
    assert virtual_test._criteria_counts(result) == (2, 1, 1)


def test_the_hrr_chart_plots_the_engines_own_series_and_four_growth_curves():
    _, results = _loaded_and_results()
    fig = virtual_test._hrr_figure(results)
    by_name = {trace.name: trace for trace in fig.data}
    for cls, result in results.items():
        assert tuple(by_name[f"Test {cls} — suppressed"].y) == tuple(result.timeseries["hrr_mw"])
        assert tuple(by_name[f"Test {cls} — free burn"].y) == tuple(
            result.timeseries["hrr_free_burn_mw"])
    growth = [name for name in by_name if name.startswith("t² ")]
    assert len(growth) == 4
    for name in ("slow", "medium", "fast", "ultra-fast"):
        assert any(g.startswith(f"t² {name} ") for g in growth)


def test_the_growth_curves_are_cited_as_reference_shapes_not_engine_output():
    loaded, results, out = _render()
    assert "NFPA 72" in out and "SFPE" in out
    assert "not engine output" in out


def test_the_ceiling_chart_has_one_engine_line_per_test():
    _, results = _loaded_and_results()
    fig = virtual_test._ceiling_figure(results)
    assert len(fig.data) == len(results)
    for trace, (cls, result) in zip(fig.data, sorted(results.items())):
        assert trace.name == f"Test {cls}"
        assert tuple(trace.y) == tuple(result.timeseries["ceiling_temp_c"])


def test_the_plotly_bundle_is_embedded_exactly_once_however_many_charts_there_are():
    loaded, results, out = _render()
    assert out.count(virtual_test.html.BUNDLE_MARK) == 1
    assert out.count("Plotly.newPlot") >= 2


def test_each_test_gets_a_results_page_with_its_timeline_and_all_six_charts():
    loaded, results, out = _render()
    for cls in loaded.tests:
        assert f"Test {cls}:" in out
    for label in ("Ignition", "Detection", "Activation", "Full pressure",
                  "Peak heat release", "Backlayering", "End of test"):
        assert out.count(f"<td>{label}</td>") == len(loaded.tests)
    for title, _keys in virtual_test.CHART_SPECS:
        assert out.count(title) >= len(loaded.tests)
    assert len(virtual_test.CHART_SPECS) == 6


def test_the_3d_tunnel_is_drawn_at_the_traces_peak_heat_release():
    loaded, results, traces = _inputs()
    fig = virtual_test._tunnel_at_peak(loaded.tests["A"], traces["A"])
    peak = max(traces["A"].steps, key=lambda s: s.hrr_mw)
    assert f"t = {peak.t_s:.0f} s" in fig.layout.title.text
    assert len(fig.data) >= 10   # 4 static + 6 dynamic traces


def test_the_trace_is_the_worst_case_the_result_reports():
    _, results, traces = _inputs()
    for cls, result in results.items():
        assert max(s.hrr_mw for s in traces[cls].steps) == result.peaks["hrr_mw"]


def test_the_timeline_marks_an_unreached_event_as_not_reached():
    events = {"t_detect_s": 40.0, "t_activate_s": None, "t_full_pressure_s": None,
              "t_peak_hrr_s": 120.0,
              "backlayering": {"occurred": False, "max_length_m": 0.0, "cleared_at_s": None}}
    rows = dict((r[0], r[1]) for r in virtual_test._timeline_rows(events, 600.0))
    assert rows["Detection"].startswith("40 s")
    assert rows["Activation"] == "not reached"
    assert rows["Backlayering"] == "did not occur"
    assert rows["End of test"].startswith("600 s")


def test_the_checklist_marks_met_not_met_and_limit_not_set():
    from solit2.schema.result import Criterion
    criteria = {
        "max_air_temp_c": Criterion.build(300.0, 250.0, "<=", True),      # not met
        "max_heat_flux_kwm2": Criterion.build(2.0, 5.0, "<=", True),       # met
        "min_visibility_m": Criterion.build(10.0, None, ">=", True),       # unset
        "target_ignited": Criterion.build(False, None, "is_false", True),  # met
    }
    out = virtual_test._criteria_checklist(criteria)
    assert out.count("✓ met") == 2
    assert out.count("✗ not met") == 1
    assert out.count("limit not set") == 1
    # The predicted value is still shown beside a limit that was never set.
    assert labels.with_unit("min_visibility_m", 10.0) in out


def test_a_design_name_with_markup_is_escaped_in_the_results_page():
    loaded, results, traces = _inputs()
    design = loaded.tests["A"]
    hostile = design.model_copy(
        update={"meta": design.meta.model_copy(update={"name": "<script>x</script>"})})
    out = virtual_test._test_results("A", hostile, results["A"], traces["A"],
                                     virtual_test._Figures())
    assert "<script>x</script>" not in out
    assert "&lt;script&gt;x&lt;/script&gt;" in out


def _finished_run(result, scale=0.8):
    """A stand-in for a finished FDS run: an FDS Result carries these four series."""
    ts = result.timeseries
    return cfd_runs.CfdRun("done", "", result.model_copy(update={
        "timeseries": {"t_s": ts["t_s"],
                       "hrr_mw": [v * scale for v in ts["hrr_mw"]],
                       "hrr_free_mw": [v * scale for v in ts["hrr_free_burn_mw"]],
                       "ceiling_temp_c": [v * scale for v in ts["ceiling_temp_c"]]},
        "peaks": {**result.peaks, "hrr_mw": result.peaks["hrr_mw"] * scale,
                  "ceiling_temp_c": result.peaks["ceiling_temp_c"] * scale},
        "warnings": ["cfd: window ends before the HRR turnover"]}))


def test_without_a_run_the_cfd_section_says_so_for_every_test():
    loaded, _, out = _render()
    assert "<h2>9. CFD comparison</h2>" in out
    assert out.count("CFD not yet run") == len(loaded.tests)


def test_a_running_run_is_reported_with_its_progress():
    running = cfd_runs.CfdRun("running", "running, 300 of 600 s")
    _, _, out = _render(cfd={"A": running, "B": cfd_runs.NOT_RUN})
    assert "running, 300 of 600 s" in out
    assert out.count("CFD not yet run") == 1


def test_a_finished_run_is_overlaid_on_that_tests_charts():
    _, results, _ = _inputs()
    run = _finished_run(results["A"])
    figures = virtual_test._cfd_figures("A", results["A"], run.result)
    assert len(figures) == 2   # HRR and ceiling temperature: the series an FDS Result carries
    for fig in figures:
        names = [t.name for t in fig.data]
        assert names == ["Tier 1 (reduced)", "CFD (FDS)"]
    assert tuple(figures[0].data[1].y) == tuple(run.result.timeseries["hrr_mw"])
    _, _, out = _render(cfd={"A": run, "B": cfd_runs.NOT_RUN})
    assert "CFD (FDS)" in out
    assert "cfd: window ends before the HRR turnover" in out   # the run's own warnings travel


def test_the_cfd_peaks_table_reports_the_difference_without_judging_it():
    _, results, _ = _inputs()
    run = _finished_run(results["A"], scale=0.8)
    table = virtual_test._cfd_peaks_table(results["A"], run.result)
    tier1 = results["A"].peaks["hrr_mw"]
    assert f"{tier1 * 0.8 - tier1:+.1f} MW" in table
    assert "pass" not in table.lower() and "fail" not in table.lower()


def _finding(verdict, clause="§7.2.1", requirement="No fire spread to the target"):
    from solit2.compliance.verdict import Finding
    return Finding(rule_id="r1", group="g", clause=clause, requirement=requirement,
                   kind="predicted", verdict=verdict, found="target ignited",
                   required="not ignited", basis="Tier 1", basis_kind="predicted")


def _report(findings):
    from pathlib import Path
    from solit2.compliance.check import ComplianceReport
    from solit2.compliance.verdict import headline
    return ComplianceReport("Spec <x>", Path("s.json"), tuple(findings),
                            headline(findings), {"calibration": "abc"})


def test_the_compliance_summary_lists_blocking_clauses_and_escapes_the_spec_name():
    from solit2.compliance.verdict import Verdict
    report = _report([_finding(Verdict.FAILS), _finding(Verdict.COMPLIES, clause="§9.9")])
    out = virtual_test._compliance_summary(report)
    assert "§7.2.1" in out and "§9.9" not in out   # only the blocker is tabled
    assert "Spec &lt;x&gt;" in out and "Spec <x>" not in out


def test_the_compliance_summary_says_so_when_nothing_blocks():
    from solit2.compliance.verdict import Verdict
    out = virtual_test._compliance_summary(_report([_finding(Verdict.COMPLIES)]))
    assert "No clause fails or lacks evidence" in out


def test_the_full_document_carries_the_checkers_headline():
    _, _, out = _render()
    report = _compliance()
    assert "<h2>10. Compliance summary</h2>" in out
    assert f"{report.headline.applicable} clauses apply" in out


def test_the_conclusion_names_every_criterion_no_authority_has_set():
    loaded, results, out = _render()
    unset = virtual_test._unset_criteria(results)
    assert unset, "the example spec's designs carry an empty ahj block"
    conclusion = out.split("<h2>11. Conclusion</h2>")[1].split("<h2>12.")[0]
    for label in unset:
        assert label in conclusion
    assert "no authority has set a limit for" in conclusion


def test_the_conclusion_never_reads_as_an_approval():
    _, _, out = _render()
    conclusion = out.split("<h2>11. Conclusion</h2>")[1].split("<h2>12.")[0].lower()
    for word in ("approved", "certified", "accepted", "passes the test"):
        assert word not in conclusion


def test_limitations_carry_the_calibration_note_and_full_provenance():
    loaded, results, out = _render()
    tail = out.split("<h2>12. Limitations and provenance</h2>")[1]
    report = _compliance()
    for result in results.values():
        assert result.meta["design_sha"] in tail
        assert result.meta["engine_version"] in tail
        # The note is HTML-escaped in the page, so compare against the unescaped section.
        assert result.meta["calibration_note"][:60] in stdlib_html.unescape(tail)
    assert report.provenance["calibration"] in tail
    assert COMMIT in tail

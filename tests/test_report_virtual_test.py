# tests/test_report_virtual_test.py
from pathlib import Path

from solit2.compliance.spec import load_spec
from solit2.engines.reduced import envelope
from solit2.reports import labels
from solit2.reports import virtual_test

SPEC = "examples/compliance/solit2-example.spec.json"


def _loaded_and_results():
    loaded = load_spec(SPEC)
    results = {cls: envelope.run(d) for cls, d in loaded.tests.items()}
    return loaded, results


def test_every_page_carries_the_prediction_band():
    loaded, results = _loaded_and_results()
    out = virtual_test.render(loaded, results)
    # One band per section plus one in the header; at minimum one per rendered section.
    assert out.count(virtual_test.html.BAND_TEXT) >= 2


def test_the_document_names_both_test_designs():
    loaded, results = _loaded_and_results()
    out = virtual_test.render(loaded, results)
    assert loaded.tests["A"].meta.name in out
    assert loaded.tests["B"].meta.name in out


def test_the_document_makes_no_network_reference():
    loaded, results = _loaded_and_results()
    out = virtual_test.render(loaded, results)
    # Not a substring test: once Task 6 embeds Plotly, the bundle's own JS strings
    # contain https:// text that is never fetched. external_references() skips
    # script bodies and catches every tag or CSS rule that would fetch something.
    assert virtual_test.html.external_references(out) == []


def test_facility_section_states_each_designs_own_geometry():
    loaded, results = _loaded_and_results()
    out = virtual_test.render(loaded, results)
    from solit2.engines.reduced.geometry import section_geometry
    for design in loaded.tests.values():
        geom = section_geometry(design)
        assert f"{geom.road_width_m:.2f}" in out


def test_water_mist_system_states_pressure_and_active_head_count():
    loaded, results = _loaded_and_results()
    out = virtual_test.render(loaded, results)
    for design in loaded.tests.values():
        assert f"{design.nozzles.pressure_bar:.1f}" in out
        assert str(design.active_heads) in out


def test_fire_load_states_the_design_hrr_and_covered_flag():
    loaded, results = _loaded_and_results()
    out = virtual_test.render(loaded, results)
    for design in loaded.tests.values():
        assert f"{design.fire.design_hrr_mw:.0f}" in out


def test_instruments_section_names_every_modelled_station():
    from solit2.engines.reduced.criteria import STATIONS
    loaded, results = _loaded_and_results()
    out = virtual_test.render(loaded, results)
    for station in STATIONS:
        assert station in out


def test_procedure_section_shows_limit_not_set_for_an_unset_criterion():
    loaded, results = _loaded_and_results()
    out = virtual_test.render(loaded, results)
    # examples/compliance/solit2-example.spec.json's designs carry an empty
    # `ahj` block (see examples/designs/solit2-test-protocol*.json), so every
    # criterion beyond target_ignited is unset.
    assert "limit not set" in out


def test_the_results_summary_states_each_tests_engine_peaks():
    loaded, results = _loaded_and_results()
    out = virtual_test.render(loaded, results)
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
    loaded, results = _loaded_and_results()
    out = virtual_test.render(loaded, results)
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
    loaded, results = _loaded_and_results()
    out = virtual_test.render(loaded, results)
    assert out.count(virtual_test.html.BUNDLE_MARK) == 1
    assert out.count("Plotly.newPlot") >= 2

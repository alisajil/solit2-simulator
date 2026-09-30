# tests/test_report_virtual_test.py
from pathlib import Path

from solit2.compliance.spec import load_spec
from solit2.engines.reduced import envelope
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

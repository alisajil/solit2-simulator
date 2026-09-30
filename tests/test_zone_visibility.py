"""An unjudged visibility reading inside the spray zone.

Annex 7 places no opacimeter there, so it is reported and never judged: it is not in
`Result.criteria`, and no limit can be set against it.
"""
import functools

import pytest

from solit2.engines.reduced import envelope, sim, tenability
from solit2.engines.reduced.criteria import STATIONS
from solit2.reports import labels, virtual_test
from solit2.schema.design import Design

BASELINE = "examples/designs/road-tunnel-twin-bore.json"
LONG_SECTION_M = 100.0     # a 100 m section puts D45 inside the spray zone
KEY = "zone_min_visibility_m"


@functools.lru_cache(maxsize=4)
def _run(section_length_m=None):
    design = Design.load(BASELINE)
    if section_length_m is not None:
        design = design.model_copy(update={"zones": design.zones.model_copy(
            update={"section_length_m": section_length_m})})
    result = envelope.run(design)
    trace = sim.run_once(design, result.worst_case["section"], result.worst_case["velocity_ms"])
    return design, result, trace


def test_every_step_carries_a_zone_visibility_within_the_reporting_cap():
    _, _, trace = _run()
    values = [s.zone_visibility_m for s in trace.steps]
    assert all(v is not None and 0.0 < v <= tenability.MAX_REPORTED_VISIBILITY_M for v in values)


def test_droplets_alone_bound_the_zone_visibility_while_the_spray_runs():
    _, _, trace = _run()
    active = [s for s in trace.steps if s.mist.kappa_visible_per_m > 0.0]
    assert active
    for s in active:
        assert s.zone_visibility_m <= tenability.JIN_LIGHT_EMITTING / s.mist.kappa_visible_per_m + 1e-9


def test_the_probe_reads_what_an_instrument_in_the_zone_would_read():
    """With a zone long enough to contain D45, the probe and D45 see the same soot and the
    same droplets, so they must agree wherever D45 reads."""
    _, _, trace = _run(LONG_SECTION_M)
    design, _, _ = _run(LONG_SECTION_M)
    assert abs(STATIONS["D45"]) <= design.active_length_m / 2.0
    compared = 0
    for s in trace.steps:
        station = s.stations["D45"].visibility_m
        if station is not None:
            assert s.zone_visibility_m == pytest.approx(station, rel=1e-9)
            compared += 1
    assert compared > 0


def test_the_result_reports_the_minimum_and_the_series_but_never_judges_it():
    _, result, trace = _run()
    series = [s.zone_visibility_m for s in trace.steps]
    assert result.peaks[KEY] == pytest.approx(min(series))
    assert len(result.timeseries["zone_visibility_m"]) == len(result.timeseries["t_s"])
    assert KEY not in result.criteria and "zone_visibility_m" not in result.criteria
    assert KEY not in result.constraints


def test_the_reading_has_a_plain_name_and_unit():
    assert labels.label(KEY) == "Minimum visibility inside the spray zone"
    assert labels.unit(KEY) == "m"


def test_the_virtual_test_results_page_shows_it_as_not_judged():
    _, result, _ = _run()
    text = virtual_test._zone_visibility_note(result)
    assert "not judged" in text
    assert labels.with_unit(KEY, result.peaks[KEY]) in text
    assert "de-stratification" in text and "optimistic" in text
    assert "Annex 7" in text

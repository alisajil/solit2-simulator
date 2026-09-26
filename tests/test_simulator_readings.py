"""The simulator's readings are the engine's own, read the way the criteria read them."""
import pytest

from app.components import readings
from solit2.engines.reduced import envelope
from solit2.engines.reduced.criteria import (
    HEAT_FLUX_STATIONS, THERMOCOUPLE_STATIONS, VISIBILITY_STATIONS,
)
from solit2.engines.reduced.sim import run_once
from solit2.schema.design import Design
from solit2.schema.presets import calibration_hash

PROTOCOL = "examples/designs/solit2-test-protocol.json"


@pytest.fixture(scope="module")
def run():
    design = Design.load(PROTOCOL)
    result = envelope.run(design)
    trace = run_once(design, result.worst_case["section"], result.worst_case["velocity_ms"])
    return design, result, trace


def _gauge(key: str) -> readings.Gauge:
    return next(g for g in readings.GAUGES if g.key == key)


def _with_limit(design: Design, field: str, value: float) -> Design:
    raw = design.model_dump(by_alias=True, mode="json")
    raw["ahj"][field] = value      # a synthetic limit, set by this test only
    return Design.from_dict(raw)


def test_air_temperature_is_the_worst_breathing_height_reading_at_that_instant(run):
    step = run[2].steps[len(run[2].steps) // 2]
    assert readings.reading(step, "air_temp_c") == max(
        step.stations[n].temp_c for n in THERMOCOUPLE_STATIONS)


def test_flux_and_visibility_read_only_the_stations_that_carry_the_instrument(run):
    step = run[2].steps[len(run[2].steps) // 2]
    assert readings.reading(step, "heat_flux_kwm2") == max(
        step.stations[n].flux_kwm2 for n in HEAT_FLUX_STATIONS)
    assert readings.reading(step, "visibility_m") == min(
        step.stations[n].visibility_m for n in VISIBILITY_STATIONS)


def test_the_plain_gauges_are_the_steps_own_fields(run):
    step = run[2].steps[-1]
    assert readings.reading(step, "hrr_mw") == step.hrr_mw
    assert readings.reading(step, "air_velocity_ms") == step.u_eff_ms
    assert readings.reading(step, "water_lpm") == step.water_lpm


def test_an_unknown_gauge_is_refused_with_the_valid_names(run):
    with pytest.raises(ValueError, match="unknown gauge 'co_ppm'.*hrr_mw"):
        readings.reading(run[2].steps[0], "co_ppm")


def test_a_gauges_limit_is_exactly_what_the_design_declares(run):
    design, result, _ = run
    assert readings.limit(result, _gauge("air_temp_c")) == design.ahj.max_air_temp_c
    assert readings.limit(result, _gauge("hrr_mw")) == design.ahj.tvs_design_fire_mw


def test_a_set_limit_is_the_criterions_own(run):
    result = envelope.run(_with_limit(run[0], "max_air_temp_c", 60.0))
    assert readings.limit(result, _gauge("air_temp_c")) == 60.0


def test_velocity_and_water_never_carry_a_limit(run):
    for key in ("air_velocity_ms", "water_lpm"):
        assert _gauge(key).criterion is None
        assert readings.limit(run[1], _gauge(key)) is None


def test_the_axis_covers_the_peak_and_the_limit(run):
    trace = run[2]
    peak = max(s.hrr_mw for s in trace.steps)
    assert readings.axis_max(trace, _gauge("hrr_mw"), None) >= peak
    assert readings.axis_max(trace, _gauge("hrr_mw"), 10 * peak) >= 10 * peak


def test_the_score_tile_says_how_many_criteria_are_set(run):
    result = run[1]
    n_set, total = readings.criteria_set(result)
    assert total == len(result.criteria)
    assert n_set == total - len(result.score["criteria_unset"])
    score = next(t for t in readings.tiles(result) if t.label == "Score")
    assert score.value == f"{result.score['total']:.1f}"
    assert (score.note == f"{n_set} of {total} criteria set"
            or score.note.startswith("gates failed"))


def test_the_tiles_carry_the_results_own_peaks(run):
    result = run[1]
    hrr = next(t for t in readings.tiles(result) if t.label == "Peak heat release")
    assert hrr.value == f"{result.peaks['hrr_mw']:.1f} MW"
    assert hrr.note == f"free burn {result.peaks['hrr_free_burn_mw']:.1f} MW"


def test_the_diagnostics_line_names_the_worst_case_and_the_calibration(run):
    line = readings.diagnostics(run[1])
    assert "playback: worst case" in line
    assert f"calibration {calibration_hash()}" in line

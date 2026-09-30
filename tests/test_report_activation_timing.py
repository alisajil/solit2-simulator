import functools

import pytest

from solit2.engines.reduced import envelope
from solit2.reports import activation_timing
from solit2.schema.design import Design

BASELINE = "examples/designs/road-tunnel-twin-bore.json"
LATE_S = 420.0


@functools.lru_cache(maxsize=1)
def _world():
    design = Design.load(BASELINE)
    designs = activation_timing.strategies(design, LATE_S)
    results = {name: envelope.run(d) for name, d in designs.items()}
    return design, designs, results


def test_strategies_change_only_the_manual_activation_and_leave_the_input_alone():
    design = Design.load(BASELINE)
    before = design.model_dump()
    designs = activation_timing.strategies(design, LATE_S)
    assert design.model_dump() == before
    assert designs["as_designed"] == design
    assert designs["late"].zones.manual_activation_s == LATE_S
    expected = design.model_dump()
    expected["zones"]["manual_activation_s"] = LATE_S
    assert designs["late"].model_dump() == expected


def test_a_late_time_beyond_the_run_length_is_refused_with_the_limit_named():
    design = Design.load(BASELINE)
    limit_s = design.zones.duration_min * 60.0
    with pytest.raises(ValueError, match=f"{limit_s:.0f}"):
        activation_timing.strategies(design, limit_s + 1.0)


@pytest.mark.parametrize("bad", [0.0, -5.0])
def test_a_non_positive_late_time_is_refused(bad):
    with pytest.raises(ValueError):
        activation_timing.strategies(Design.load(BASELINE), bad)


def test_the_late_run_activates_at_the_supplied_time():
    _, designs, results = _world()
    events = results["late"].events
    assert events["t_activate_s"] == LATE_S
    assert events["t_full_pressure_s"] == LATE_S + designs["late"].zones.pump_ramp_s


def test_the_report_says_the_late_time_was_supplied_and_not_chosen():
    _, designs, results = _world()
    out = activation_timing.render(LATE_S, designs, results)
    assert (f"Late activation time: {LATE_S:.0f} s, supplied by the user. "
            "The tool does not choose it.") in out
    assert results["as_designed"].meta["design_sha"] in out


def test_the_as_designed_timetable_is_labelled_by_how_it_was_set():
    _, designs, results = _world()
    out = activation_timing.render(LATE_S, designs, results)
    delay = designs["as_designed"].zones.activation_delay_s
    assert f"detection + {delay:.0f} s delay" in out
    zones = designs["as_designed"].zones.model_copy(update={"manual_activation_s": 90.0})
    pinned = designs["as_designed"].model_copy(update={"zones": zones})
    out = activation_timing.render(LATE_S, {"as_designed": pinned, "late": designs["late"]},
                                   results)
    assert "pinned at 90 s" in out


def test_the_comparison_table_reads_both_columns_from_the_results():
    _, designs, results = _world()
    out = activation_timing.render(LATE_S, designs, results)
    a, b = results["as_designed"], results["late"]
    for key in ("hrr_mw", "ceiling_temp_c", "lining_temp_c"):
        assert activation_timing.labels.value(key, a.peaks[key]) in out
        assert activation_timing.labels.value(key, b.peaks[key]) in out
    diff = b.peaks["hrr_mw"] - a.peaks["hrr_mw"]
    assert f"{diff:+.1f}" in out


def test_the_water_volume_is_the_integral_of_the_water_flow():
    _, _, results = _world()
    ts = results["late"].timeseries
    t, q = ts["t_s"], ts["water_lpm"]
    expected_m3 = sum((t[i + 1] - t[i]) * (q[i] + q[i + 1]) / 2.0
                      for i in range(len(t) - 1)) / 60.0 / 1000.0
    assert activation_timing.water_volume_m3(results["late"]) == pytest.approx(expected_m3)
    # Started later, less water is discharged.
    assert (activation_timing.water_volume_m3(results["late"])
            < activation_timing.water_volume_m3(results["as_designed"]))


def test_a_criterion_that_changes_status_is_named_as_a_fact():
    _, designs, results = _world()
    changed = [k for k, c in results["as_designed"].criteria.items()
               if c.status != results["late"].criteria[k].status]
    out = activation_timing.render(LATE_S, designs, results)
    if changed:
        facts = out.split("## What changes")[1]
        for key in changed:
            assert activation_timing.labels.label(key) in facts
    else:
        assert "No criterion changes status." in out


def test_a_status_change_reads_met_then_not_met_from_synthetic_criteria():
    from solit2.schema.result import Criterion
    _, designs, results = _world()
    met = Criterion.build(2.0, 5.0, "<=", True)
    unmet = Criterion.build(9.0, 5.0, "<=", True)
    a = results["as_designed"].model_copy(update={"criteria": {"max_heat_flux_kwm2": met}})
    b = results["late"].model_copy(update={"criteria": {"max_heat_flux_kwm2": unmet}})
    out = activation_timing.render(LATE_S, designs, {"as_designed": a, "late": b})
    assert "met as designed, not met when started late" in out


def test_an_unset_limit_reads_limit_not_set_and_is_not_a_status_change():
    from solit2.schema.result import Criterion
    _, designs, results = _world()
    unset = Criterion.build(10.0, None, ">=", True)
    a = results["as_designed"].model_copy(update={"criteria": {"min_visibility_m": unset}})
    b = results["late"].model_copy(update={"criteria": {"min_visibility_m": unset}})
    out = activation_timing.render(LATE_S, designs, {"as_designed": a, "late": b})
    assert "limit not set" in out
    assert "No criterion changes status." in out


def test_the_report_states_consequences_and_never_a_preference():
    _, designs, results = _world()
    out = activation_timing.render(LATE_S, designs, results)
    body = out.split("## Warnings")[0].lower()
    for word in ("better", "worse", "recommend", "optimal", "preferred"):
        assert word not in body


def test_a_late_time_not_after_the_as_designed_activation_is_flagged():
    _, designs, results = _world()
    t_activate = results["as_designed"].events["t_activate_s"]
    flagged = activation_timing.render(t_activate - 1.0, designs, results)
    assert "not later than the as-designed activation" in flagged
    assert "not later than the as-designed activation" not in activation_timing.render(
        LATE_S, designs, results)


def test_the_report_is_a_prediction_and_says_so():
    _, designs, results = _world()
    assert "Prediction, not a measurement" in activation_timing.render(
        LATE_S, designs, results)


def test_the_report_explains_why_the_two_tables_can_disagree_on_a_peak():
    _, designs, results = _world()
    out = activation_timing.render(LATE_S, designs, results)
    assert "reported worst case" in out
    assert "different case than the table above" in out


def test_the_comparison_shows_the_in_zone_visibility_of_both_runs():
    _, designs, results = _world()
    out = activation_timing.render(LATE_S, designs, results)
    a, b = results["as_designed"], results["late"]
    key = "zone_min_visibility_m"
    assert "Minimum visibility inside the spray zone" in out
    assert activation_timing.labels.value(key, a.peaks[key]) in out
    assert activation_timing.labels.value(key, b.peaks[key]) in out
    assert f"{b.peaks[key] - a.peaks[key]:+.1f}" in out


def test_the_in_zone_reading_is_stated_as_not_judged_and_stays_out_of_the_criteria():
    _, designs, results = _world()
    out = activation_timing.render(LATE_S, designs, results)
    comparison = out.split("## Comparison")[1].split("## Criteria")[0]
    criteria = out.split("## Criteria")[1].split("## What changes")[0]
    assert "not an Annex 7 measurement position and is not judged" in comparison
    assert "optimistic" in comparison
    assert "inside the spray zone" not in criteria

import pytest
from solit2.schema.design import Design
from solit2.engines.reduced import sim, envelope

BASELINE = "examples/designs/road-tunnel-twin-bore.json"


def test_run_once_produces_a_full_hour_of_one_second_steps():
    trace = sim.run_once(Design.load(BASELINE), section="bored", velocity_ms=5.08)
    assert len(trace.steps) == 3600
    assert trace.steps[-1].t_s == pytest.approx(3600.0)
    assert trace.section == "bored"


def test_detection_then_delay_then_full_pressure():
    trace = sim.run_once(Design.load(BASELINE), "bored", 5.08)
    e = trace.events
    assert 30.0 < e["t_detect_s"] < 300.0
    assert e["t_activate_s"] == pytest.approx(e["t_detect_s"] + 60.0)
    assert e["t_full_pressure_s"] == pytest.approx(e["t_activate_s"] + 30.0)


def test_water_flows_only_after_activation():
    trace = sim.run_once(Design.load(BASELINE), "bored", 5.08)
    before = [s for s in trace.steps if s.t_s < trace.events["t_activate_s"]]
    after = [s for s in trace.steps if s.t_s > trace.events["t_full_pressure_s"]]
    assert all(s.water_lpm == 0.0 for s in before)
    assert all(s.water_lpm > 0.0 for s in after)


def test_suppression_holds_the_fire_below_the_free_burn():
    trace = sim.run_once(Design.load(BASELINE), "bored", 5.08)
    assert max(s.hrr_mw for s in trace.steps) < max(s.hrr_free_mw for s in trace.steps)


def test_every_station_is_sampled_at_every_step():
    from solit2.engines.reduced.criteria import STATIONS
    trace = sim.run_once(Design.load(BASELINE), "bored", 5.08)
    assert set(trace.steps[0].stations) == set(STATIONS)
    assert all(set(s.stations) == set(STATIONS) for s in trace.steps[::600])


def test_fed_accumulates_monotonically():
    trace = sim.run_once(Design.load(BASELINE), "bored", 5.08)
    fed = [s.stations["D35"].fed_tox for s in trace.steps]
    assert all(b >= a for a, b in zip(fed, fed[1:]))


def test_envelope_runs_the_velocity_range_and_keeps_the_worst_case():
    result = envelope.run(Design.load(BASELINE))
    assert len(result.envelope) >= 2
    assert result.worst_case["velocity_ms"] in (3.88, 5.08)
    assert set(result.criteria) >= {"target_ignited", "max_air_temp_c", "max_fed"}
    assert result.meta["engine"] == "reduced"
    assert len(result.timeseries["t_s"]) == len(result.timeseries["hrr_mw"])


def test_envelope_completes_in_a_few_seconds():
    import time
    start = time.perf_counter()
    envelope.run(Design.load(BASELINE))
    assert time.perf_counter() - start < 20.0


def test_thin_critical_velocity_margin_is_warned_about():
    """`_critical_velocity_warnings` is the mechanism Annex 7 relies on to flag
    a design running close to backlayering. Built from a synthetic trace
    rather than the baseline design's calibrated margin: whether the baseline
    actually runs within `CRITICAL_VELOCITY_WARNING_MARGIN` of critical
    velocity depends on the ventilation/thermal calibration, so asserting on
    it directly would make this test track a calibration snapshot instead of
    the warning logic.
    """
    from solit2.engines.reduced.state import MistEffect, RunTrace, StepRecord

    def _step(u_eff_ms, u_critical_ms):
        return StepRecord(
            t_s=0.0, hrr_mw=50.0, hrr_free_mw=50.0, ceiling_temp_c=400.0,
            lining_temp_c=690.0, pipe_temp_c=120.0, target_flux_kwm2=0.0,
            u_eff_ms=u_eff_ms, u_critical_ms=u_critical_ms, backlayer_m=0.0,
            water_lpm=0.0, pools_remaining=0, mist=MistEffect.none(), stations={})

    margin = envelope.CRITICAL_VELOCITY_WARNING_MARGIN
    u_critical_ms = 10.0
    thin = RunTrace((_step(u_critical_ms * (1.0 + margin / 2), u_critical_ms),),
                    {}, "bored", 3.0)
    comfortable = RunTrace((_step(u_critical_ms * (1.0 + margin * 3), u_critical_ms),),
                           {}, "bored", 4.5)

    thin_warnings = envelope._critical_velocity_warnings(thin)
    assert any("critical velocity" in w for w in thin_warnings)
    assert envelope._critical_velocity_warnings(comfortable) == []


def test_a_scenario_that_never_trips_the_detector_raises():
    d = Design.load(BASELINE)
    blind = d.model_copy(update={"detection": d.detection.model_copy(
        update={"threshold_c": 5000.0})})
    with pytest.raises(RuntimeError) as excinfo:
        sim.run_once(blind, "bored", 5.08)
    message = str(excinfo.value)
    assert "5000.0" in message, "the raise must name the threshold it never reached"
    assert "60.0" in message, "the raise must name the duration it had to reach it in"


def test_every_criterion_names_the_case_it_came_from():
    result = envelope.run(Design.load(BASELINE))
    assert set(result.criteria_cases) == set(result.criteria)
    ran = {(c["section"], c["velocity_ms"]) for c in result.envelope}
    assert all((c["section"], c["velocity_ms"]) in ran
               for c in result.criteria_cases.values())


def test_a_criterion_is_attributed_to_the_case_that_actually_produced_it():
    design = Design.load(BASELINE)
    result = envelope.run(design)
    owner = result.criteria_cases["hrr_below_tvs_design_mw"]
    trace = sim.run_once(design, owner["section"], owner["velocity_ms"])
    peak = max(s.hrr_mw for s in trace.after(trace.events["t_full_pressure_s"]))
    assert result.criteria["hrr_below_tvs_design_mw"].value == pytest.approx(peak)


def test_pinning_a_single_velocity_runs_one_case():
    d = Design.load(BASELINE)
    pinned = d.model_copy(update={"ventilation": d.ventilation.model_copy(
        update={"velocity_ms": 4.5})})
    result = envelope.run(pinned)
    assert len(result.envelope) == 1
    assert result.worst_case["velocity_ms"] == pytest.approx(4.5)


def test_each_step_carries_the_two_annex_7_running_quantities():
    trace = sim.run_once(Design.load(BASELINE), "bored", 5.08)
    assert all(s.target_exposure_s >= 0.0 for s in trace.steps)
    assert all(s.structure_exposure_length_m >= 0.0 for s in trace.steps)
    # the clock only ever advances by one step or resets to zero
    for before, after in zip(trace.steps, trace.steps[1:]):
        assert after.target_exposure_s in (0.0, pytest.approx(before.target_exposure_s + 1.0))


def test_every_station_sample_carries_carbon_monoxide():
    """Annex 7 7.2.2 calls CO out by name, so it has to reach the stations."""
    trace = sim.run_once(Design.load(BASELINE), "bored", 5.08)
    late = trace.steps[-1]
    assert all(s.co_ppm >= 0.0 for s in late.stations.values())
    assert max(s.co_ppm for s in late.stations.values()) > 0.0


def test_the_result_reports_the_unset_criteria_and_the_target_context():
    result = envelope.run(Design.load(BASELINE))
    assert "criteria_unset" in result.score
    assert set(result.score["criteria_unset"]) <= set(result.criteria)
    assert all(result.criteria[cid].status == "unset"
               for cid in result.score["criteria_unset"])
    assert "target_peak_flux_kwm2" in result.peaks
    assert "target_max_exposure_s" in result.peaks

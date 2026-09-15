import pytest
from solit2.schema.design import Design
from solit2.engines.reduced import sim, envelope

BASELINE = "designs/og-dbr-rev0.json"


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
    assert set(result.criteria) >= {"hrr_control_mw", "u35_temp_c", "fed_d35"}
    assert result.meta["engine"] == "reduced"
    assert len(result.timeseries["t_s"]) == len(result.timeseries["hrr_mw"])


def test_envelope_completes_in_a_few_seconds():
    import time
    start = time.perf_counter()
    envelope.run(Design.load(BASELINE))
    assert time.perf_counter() - start < 20.0


def test_thin_critical_velocity_margin_is_warned_about():
    result = envelope.run(Design.load(BASELINE))
    assert any("critical velocity" in w for w in result.warnings)


def test_pinning_a_single_velocity_runs_one_case():
    d = Design.load(BASELINE)
    pinned = d.model_copy(update={"ventilation": d.ventilation.model_copy(
        update={"velocity_ms": 4.5})})
    result = envelope.run(pinned)
    assert len(result.envelope) == 1
    assert result.worst_case["velocity_ms"] == pytest.approx(4.5)

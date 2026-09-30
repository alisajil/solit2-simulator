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
    fed = [s.stations["D45"].fed_tox for s in trace.steps]
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


def test_every_carbon_monoxide_station_carries_carbon_monoxide():
    """Annex 7 7.2.2 calls CO out by name, so it has to reach the stations that
    measure it -- Table 5's U45 and D45, and not the twelve that do not."""
    from solit2.engines.reduced.criteria import CO_STATIONS

    trace = sim.run_once(Design.load(BASELINE), "bored", 5.08)
    late = trace.steps[-1]
    measured = [late.stations[name].co_ppm for name in CO_STATIONS]
    assert all(value >= 0.0 for value in measured)
    assert max(measured) > 0.0
    assert all(sample.co_ppm is None for name, sample in late.stations.items()
               if name not in CO_STATIONS)


def test_the_result_reports_the_unset_criteria_and_the_target_context():
    result = envelope.run(Design.load(BASELINE))
    assert "criteria_unset" in result.score
    assert set(result.score["criteria_unset"]) <= set(result.criteria)
    assert all(result.criteria[cid].status == "unset"
               for cid in result.score["criteria_unset"])
    assert "target_peak_flux_kwm2" in result.peaks
    assert "target_max_exposure_s" in result.peaks


# --- Annex 7 sections 5.2.6 / 6.3: where the fire target actually sits -------

class _FluxRecorder:
    """A `ThermalField` stand-in that records the x it was asked to radiate to.

    What matters is the target position that REACHES `sim`, so it is captured at
    the call rather than read back off a constant that may be unused.
    """

    def __init__(self, flame_tip_x_m: float, flux_kwm2: float = 1.0):
        self.flame_tip_x_m = flame_tip_x_m
        self._flux_kwm2 = flux_kwm2
        self.asked_x_m: list[float] = []

    def radiant_flux_kwm2(self, x_m: float, height_m: float, tau_mist: float) -> float:
        self.asked_x_m.append(x_m)
        return self._flux_kwm2


def _asked_target_x_m(design: Design) -> float:
    from solit2.engines.reduced.state import MistEffect
    scene = sim._build_scene(design, "bored", 5.08)
    recorder = _FluxRecorder(flame_tip_x_m=0.0)
    sim._target_flux_kwm2(scene, recorder, MistEffect.none())
    assert len(recorder.asked_x_m) == 1, "the target flux is read at exactly one place"
    return recorder.asked_x_m[0]


def _with_mock_up_length(design: Design, length_m: float) -> Design:
    footprint = design.fire.footprint.model_copy(update={"length_m": length_m})
    return design.model_copy(update={"fire": design.fire.model_copy(
        update={"footprint": footprint})})


def test_the_target_x_is_half_the_mock_up_plus_the_standoff():
    """Annex 7 section 5.2.6 puts the target "5m downstream behind the mock-up",
    and section 6.3 puts the x origin "longitudinally in the middle of the
    mock-up". The target's x in that frame is therefore half the mock-up length
    plus the standoff, not the standoff on its own."""
    design = Design.load(BASELINE)
    expected = design.fire.footprint.length_m / 2.0 + design.fire.target_distance_m
    assert _asked_target_x_m(design) == pytest.approx(expected)


def test_a_longer_mock_up_carries_the_target_downstream_with_it():
    """The position is derived from the mock-up, not hardcoded: a 16 m mock-up
    puts its ends at U8/D8 and its target at D13."""
    design = _with_mock_up_length(Design.load(BASELINE), 16.0)
    assert _asked_target_x_m(design) == pytest.approx(8.0 + design.fire.target_distance_m)


def test_the_annex7_mock_up_puts_the_target_at_d10_not_d5():
    """Regression guard on the frame bug. Annex 7 section 6.3: "the ends of the
    HGV Class A mock-up are located in U5 and D5. Correspondingly the fire target
    is located at D10." `target_distance_m` is 5.0 m, but that is the standoff
    BEHIND the mock-up, not a position in the thermal field's x-frame; using it
    as one declared flame contact 5 m too early."""
    from solit2.engines.reduced.criteria import STATIONS
    design = Design.load(BASELINE)
    assert design.fire.footprint.length_m == 10.0
    assert design.fire.target_distance_m == 5.0
    assert _asked_target_x_m(design) == pytest.approx(10.0)
    assert _asked_target_x_m(design) == pytest.approx(STATIONS["Target"])


def test_flame_contact_is_judged_against_the_target_x_not_the_standoff():
    """A 7 m tip is past the 5 m standoff but well short of the D10 target, so it
    is not flame contact and the flux stays the radiant one."""
    from solit2.engines.reduced.criteria import FLAME_CONTACT_FLUX_KWM2
    from solit2.engines.reduced.state import MistEffect
    scene = sim._build_scene(Design.load(BASELINE), "bored", 5.08)
    short = _FluxRecorder(flame_tip_x_m=7.0, flux_kwm2=1.0)
    assert sim._target_flux_kwm2(scene, short, MistEffect.none()) == pytest.approx(1.0)
    reaching = _FluxRecorder(flame_tip_x_m=10.0, flux_kwm2=1.0)
    assert sim._target_flux_kwm2(
        scene, reaching, MistEffect.none()) == pytest.approx(FLAME_CONTACT_FLUX_KWM2)


def test_a_tip_short_of_the_target_leaves_the_flux_below_the_contact_clamp(monkeypatch):
    """Annex 7 section 7.2.1 end to end: with a deflected-flame coefficient small
    enough that the tip stops short of D10, a real thermal field hands `sim` a
    radiant flux STRICTLY below the flame-contact clamp -- so the criterion has
    something left to discriminate with."""
    import copy
    from solit2.engines.reduced import fire as fire_mod
    from solit2.engines.reduced import thermal
    from solit2.engines.reduced.criteria import FLAME_CONTACT_FLUX_KWM2
    from solit2.engines.reduced.state import FireState, MistEffect
    from solit2.engines.reduced.ventilation import evaluate

    design = Design.load(BASELINE)
    scene = sim._build_scene(design, "bored", 5.08)
    cal = copy.deepcopy(thermal.load_calibration())
    cal["thermal"]["flame_length_coefficient"]["value"] = 0.5
    monkeypatch.setattr(thermal, "load_calibration", lambda: cal)

    state = FireState(t_s=600.0, hrr_mw=30.0, hrr_free_mw=30.0,
                      energy_released_mj=10_000.0, suppression=0.5,
                      pools_remaining=0, wet_time_s=180.0)
    vent = evaluate(scene.geom, 5.08, fire_mod.convective_kw(scene.model, 30.0))
    field = thermal.field(scene.geom, scene.model, state, vent, MistEffect.none(),
                          fire_top_m=scene.fire_top_m, fire_base_m=scene.fire_base_m,
                          fire_length_m=design.fire.footprint.length_m,
                          fire_width_m=design.fire.footprint.width_m, ambient_c=20.0)

    assert field.flame_tip_x_m < design.fire.target_x_m
    assert sim._target_flux_kwm2(scene, field, MistEffect.none()) < FLAME_CONTACT_FLUX_KWM2


def test_a_declared_head_count_that_contradicts_the_layout_is_warned_about():
    """`zones.heads_per_zone`, when set, silently overrides rows x pitch. The
    baseline declares 25, which is exactly what its two rows derive, so the
    design is self-consistent and nothing should be said. Change the row count
    alone and the declared figure wins: flow, pump power and tank size go on
    costing two rows while the spray pattern is drawn with three. Nothing in
    the result revealed that until this warning."""
    design = Design.load(BASELINE)
    mount = design.nozzles.mounting
    implied = round(design.zones.section_length_m / (mount.pitch_m / mount.rows))
    agreeing = design.model_copy(deep=True)
    object.__setattr__(agreeing.zones, "heads_per_zone", implied)
    assert envelope._head_count_warnings(agreeing) == [], \
        "a design that agrees with its own geometry; saying otherwise is noise"

    three_rows = agreeing.model_copy(deep=True)
    object.__setattr__(three_rows.nozzles.mounting, "rows", 3)
    object.__setattr__(three_rows.nozzles.mounting, "row_lateral_offsets_m",
                       (mount.row_lateral_offsets_m[0], 0.0, mount.row_lateral_offsets_m[-1]))
    warned = envelope._head_count_warnings(three_rows)
    assert len(warned) == 1
    assert str(three_rows.zones.heads_per_zone) in warned[0], "say what was declared"
    assert "3 row" in warned[0], "say what the layout implies"


def test_no_head_count_warning_when_the_design_lets_the_layout_decide():
    """A design that does not pin the count cannot contradict itself."""
    design = Design.load(BASELINE)
    free = design.model_copy(deep=True)
    object.__setattr__(free.zones, "heads_per_zone", None)
    assert envelope._head_count_warnings(free) == []


def test_timeseries_includes_the_free_burn_hrr():
    result = envelope.run(Design.load(BASELINE))
    assert "hrr_free_burn_mw" in result.timeseries
    assert len(result.timeseries["hrr_free_burn_mw"]) == len(result.timeseries["t_s"])
    # Free-burn HRR is never below the suppressed HRR it is measured alongside.
    assert all(free >= actual for free, actual in
               zip(result.timeseries["hrr_free_burn_mw"], result.timeseries["hrr_mw"]))

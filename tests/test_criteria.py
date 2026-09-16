import pytest
from solit2.schema.result import Criterion
from solit2.schema.design import AHJ, Design
from solit2.engines.reduced import criteria as criteria_mod
from solit2.engines.reduced import sim as sim_mod
from solit2.engines.reduced.state import MistEffect, RunTrace, StationSample, StepRecord

BASELINE = "examples/designs/road-tunnel-twin-bore.json"

# Every criterion whose limit SOLIT2 Annex 7 7.1 defers to the authority
# having jurisdiction, and which therefore reads "unset" until one is set.
AHJ_DEPENDENT = {
    "hrr_below_tvs_design_mw", "max_air_temp_c", "max_heat_flux_kwm2",
    "min_visibility_m", "max_fed", "max_co_ppm",
    "structure_exposure_length_m", "structure_exposure_duration_s",
}


# Minimal stand-ins, in the style of tests/test_score.py. `evaluate` reads
# nothing off the hydraulics or the cost any more: the two entries that did
# (`power_kw`, `density_mm_min`) were a project's feeder capacity and a vendor's
# design margin, and are now user-declared `constraints` judged separately.
class _Hyd:
    flow_lpm = 2174.3
    power_kw = 375.0
    density_mm_min = 2.4


class _Cost:
    index = 1.0


def _station(name, temp_c=25.0, flux_kwm2=0.2, visibility_m=200.0, fed_tox=0.0,
             co_ppm=0.0):
    """A sample shaped like that station's own Annex 7 Table 5 instrument list.

    The values offered are kept whole where Table 5 puts a sensor and dropped
    where it does not, so a fixture cannot accidentally hand a criterion a
    reading from a location the standard does not instrument.
    """
    kit = criteria_mod.INSTRUMENTS[name]
    return StationSample(
        temp_c=temp_c,
        flux_kwm2=flux_kwm2 if kit.heat_flux else None,
        visibility_m=visibility_m if kit.visibility else None,
        fed_tox=fed_tox if kit.toxic_gas else None,
        fed_heat=0.0 if kit.thermal_dose else None,
        co_ppm=co_ppm if kit.carbon_monoxide else None,
    )


def _step(t_s, hrr_mw, target_flux_kwm2, stations, target_exposure_s=0.0,
          structure_exposure_length_m=0.0):
    full = {name: _station(name) for name in criteria_mod.STATIONS}
    full.update(stations)
    return StepRecord(
        t_s=t_s, hrr_mw=hrr_mw, hrr_free_mw=hrr_mw, ceiling_temp_c=400.0,
        lining_temp_c=690.0, pipe_temp_c=120.0, target_flux_kwm2=target_flux_kwm2,
        u_eff_ms=4.2, u_critical_ms=3.72, backlayer_m=0.0, water_lpm=2174.3,
        pools_remaining=0, mist=MistEffect.none(), stations=full,
        target_exposure_s=target_exposure_s,
        structure_exposure_length_m=structure_exposure_length_m,
    )


def _trace(steps=None):
    """A pre-activation peak the criteria must exclude, then the settled state.

    `hrr_below_tvs_design_mw` is measured only after full pressure (Annex 7 7.4:
    the system's response delay must be accounted for), so the 150 MW first step
    must not reach it. The settled step is deliberately worse DOWNSTREAM than
    upstream at every life-safety quantity, because Annex 7 7.2.2 asks for both.

    Each worst value is placed at a station Annex 7 Table 5 actually instruments
    for that quantity: the flux pair at U15/D15 (section 6.4.2), the visibility
    pair at U45/D100 (6.4.5), the gas pair at U45/D45 (6.4.3).
    """
    return RunTrace(
        steps=steps or (
            _step(0.0, hrr_mw=150.0, target_flux_kwm2=9.0, stations={}),
            _step(120.0, hrr_mw=46.0, target_flux_kwm2=9.8, stations={
                "U45": _station("U45", temp_c=31.0, visibility_m=60.0,
                                fed_tox=0.02, co_ppm=10.0),
                "U15": _station("U15", flux_kwm2=2.0),
                "D15": _station("D15", temp_c=52.0, flux_kwm2=4.0),
                "D100": _station("D100", visibility_m=12.0),
                "D45": _station("D45", temp_c=58.0, fed_tox=0.05, co_ppm=120.0),
            }, structure_exposure_length_m=7.0),
        ),
        events={"t_full_pressure_s": 90.0},
        section="bored",
        velocity_ms=5.08,
    )


def _evaluate(design, trace=None):
    return criteria_mod.evaluate(trace or _trace(), _Hyd(), _Cost(), design)


def _with_ahj(**fields):
    return Design.load(BASELINE).model_copy(update={"ahj": AHJ(**fields)})


def _flux_trace(flux_series):
    """Fold sim's exposure accumulator over a flux series, as a real run would.

    This is the whole point of tests 3 and 4: the accumulator, not the criterion,
    is what turns a sustained-exposure rule into something a peak cannot fake.
    """
    steps, exposure, t = [], 0.0, 0.0
    for flux in flux_series:
        exposure = sim_mod.target_exposure_s(exposure, flux, sim_mod.DT_S)
        steps.append(_step(t, hrr_mw=20.0, target_flux_kwm2=flux, stations={},
                           target_exposure_s=exposure))
        t += sim_mod.DT_S
    return RunTrace(tuple(steps), {"t_full_pressure_s": 0.0}, "bored", 5.08)


# --- the criterion primitive ------------------------------------------------

def test_upper_bound_margin():
    c = Criterion.build(value=46.0, limit=50.0, op="<=", hard=True)
    assert c.passed
    assert c.status == "pass"
    assert c.margin == pytest.approx(0.08)


def test_upper_bound_failure_has_negative_margin():
    c = Criterion.build(value=77.0, limit=50.0, op="<=", hard=True)
    assert not c.passed
    assert c.status == "fail"
    assert c.margin < 0


def test_lower_bound_margin():
    c = Criterion.build(value=60.0, limit=10.0, op=">=", hard=True)
    assert c.passed
    assert c.margin == pytest.approx(1.0)


def test_band_criterion():
    inside = Criterion.build(value=50.0, limit=(45.0, 60.0), op="in", hard=True)
    outside = Criterion.build(value=80.0, limit=(45.0, 60.0), op="in", hard=True)
    assert inside.passed and not outside.passed
    assert inside.margin > 0 and outside.margin < 0


def test_an_unset_limit_reports_its_value_and_never_rejects_the_design():
    c = Criterion.build(value=812.0, limit=None, op="<=", hard=True)
    assert c.status == "unset"
    assert c.passed, "an unset limit must not reject a design; `status` is the signal"
    assert c.margin == 0.0
    assert c.value == pytest.approx(812.0), "the computed value is still reported"


def test_is_false_is_a_binary_rule_that_needs_no_limit():
    clean = Criterion.build(value=False, limit=None, op="is_false", hard=True)
    ignited = Criterion.build(value=True, limit=None, op="is_false", hard=True)
    assert clean.passed and clean.status == "pass"
    assert not ignited.passed and ignited.status == "fail"
    assert ignited.margin < 0 < clean.margin


def test_build_rejects_an_unknown_comparison_operator():
    with pytest.raises(ValueError) as exc:
        Criterion.build(value=50.0, limit=60.0, op="<", hard=True)
    message = str(exc.value)
    assert "'<'" in message                              # names the offending operator
    assert all(op in message for op in ("'<='", "'>='", "'in'", "'is_false'"))


# --- the table ---------------------------------------------------------------

def test_every_spec_criterion_is_defined_once():
    ids = [c.id for c in criteria_mod.DEFAULT_CRITERIA]
    assert len(ids) == len(set(ids))
    assert set(ids) == {
        "target_ignited", "hrr_below_tvs_design_mw",
        "max_air_temp_c", "max_heat_flux_kwm2", "min_visibility_m", "max_fed", "max_co_ppm",
        "structure_exposure_length_m", "structure_exposure_duration_s",
    }


def test_the_vendor_criteria_are_gone():
    """These came from one manufacturer's test report, not from SOLIT2 Annex 7."""
    ids = {c.id for c in criteria_mod.DEFAULT_CRITERIA}
    assert ids.isdisjoint({
        "hrr_control_mw", "target_hf_kwm2", "u35_temp_c", "hf_u15_kwm2", "hf_u35_kwm2",
        "visibility_u35_m", "fed_d35", "ff_u5_hf_kwm2", "ff_d20_temp_c",
        "remote_nozzle_bar", "pools_extinguished_s",
    })


def test_the_project_and_vendor_limits_are_gone_from_the_criteria():
    """`power_kw` was one tunnel's feeder capacity and `density_mm_min` one
    vendor's power-headroom figure. Neither is an Annex 7 acceptance criterion;
    both are now declared by the user in `constraints` and reported apart."""
    ids = {c.id for c in criteria_mod.DEFAULT_CRITERIA}
    assert ids.isdisjoint({"power_kw", "density_mm_min"})


def test_stations_cover_every_criterion_location():
    """The full Annex 7 Table 5 set is asserted, both directions, in
    tests/test_annex7_conformance.py; what matters here is only that the
    life-safety criteria have an upstream and a downstream station to compare."""
    assert criteria_mod.STATIONS["U45"] == -45.0
    assert criteria_mod.STATIONS["D100"] == 100.0
    assert min(criteria_mod.STATIONS.values()) < 0.0 < max(criteria_mod.STATIONS.values())


# --- test 1: an AHJ that has set nothing ------------------------------------

def test_an_empty_ahj_leaves_every_deferred_criterion_unset():
    out = _evaluate(Design.load(BASELINE))
    assert AHJ_DEPENDENT <= set(out)
    for cid in AHJ_DEPENDENT:
        assert out[cid].status == "unset", f"{cid} should defer to the AHJ"
        assert out[cid].limit is None
        assert out[cid].passed, f"{cid} must not reject a design nobody has set a limit for"


def test_unset_criteria_never_reach_gates_failed():
    from solit2.engines.reduced import score as score_mod
    out = _evaluate(Design.load(BASELINE))
    scored = score_mod.compute(out, _Hyd(), _Cost(), _trace(), peak_lining_c=690.0)
    assert AHJ_DEPENDENT.isdisjoint(scored.gates_failed)


# --- test 2: the ventilation design fire size, Annex 7 7.3.1 ----------------

def test_a_tvs_design_fire_below_the_modelled_peak_fails_the_gate():
    from solit2.engines.reduced import score as score_mod
    out = _evaluate(_with_ahj(tvs_design_fire_mw=30.0))
    c = out["hrr_below_tvs_design_mw"]
    assert c.status == "fail" and not c.passed
    assert c.value == pytest.approx(46.0), "measured after full pressure, per 7.4"
    assert c.limit == pytest.approx(30.0)
    scored = score_mod.compute(out, _Hyd(), _Cost(), _trace(), peak_lining_c=690.0)
    assert "hrr_below_tvs_design_mw" in scored.gates_failed


def test_a_tvs_design_fire_above_the_modelled_peak_passes_the_gate():
    out = _evaluate(_with_ahj(tvs_design_fire_mw=70.0))
    c = out["hrr_below_tvs_design_mw"]
    assert c.status == "pass" and c.passed
    assert c.margin > 0


# --- test 3: target ignition is absolute, Annex 7 7.2.1 ---------------------

def test_target_ignited_is_hard_whatever_the_ahj_has_set():
    out = _evaluate(Design.load(BASELINE))
    assert out["target_ignited"].hard, "7.2.1 is mandated absolutely, not deferred"
    assert out["target_ignited"].status != "unset"
    assert out["target_ignited"].limit is None


def test_a_target_kept_below_the_ignition_flux_does_not_ignite():
    below = criteria_mod.WOOD_PILOTED_IGNITION_KWM2 - 2.0
    out = _evaluate(Design.load(BASELINE), _flux_trace([below] * 600))
    assert out["target_ignited"].value is False
    assert out["target_ignited"].passed


def test_sustained_exposure_above_the_ignition_flux_ignites_and_fails():
    from solit2.engines.reduced import score as score_mod
    above = criteria_mod.WOOD_PILOTED_IGNITION_KWM2 + 5.0
    held = int(criteria_mod.IGNITION_EXPOSURE_S) + 10
    trace = _flux_trace([above] * held)
    out = _evaluate(Design.load(BASELINE), trace)
    assert out["target_ignited"].value is True
    assert not out["target_ignited"].passed
    scored = score_mod.compute(out, _Hyd(), _Cost(), trace, peak_lining_c=690.0)
    assert "target_ignited" in scored.gates_failed
    assert not scored.gates_passed


def test_flame_contact_ignites_the_target_immediately():
    """7.2.1 also fails on flame spread, which needs no sustained-exposure clock."""
    trace = _flux_trace([criteria_mod.FLAME_CONTACT_FLUX_KWM2 + 1.0] * 5)
    assert _evaluate(Design.load(BASELINE), trace)["target_ignited"].value is True


# --- test 4: a duration rule is not a peak rule -----------------------------

def test_a_flux_that_chatters_across_the_threshold_is_not_ignition():
    above = criteria_mod.WOOD_PILOTED_IGNITION_KWM2 + 8.0
    below = criteria_mod.WOOD_PILOTED_IGNITION_KWM2 - 8.0
    longest_burst = int(criteria_mod.IGNITION_EXPOSURE_S) - 15
    series = ([above] * 30 + [below] * 5) * 3 + [above] * longest_burst + [below] * 5
    trace = _flux_trace(series)

    assert max(s.target_flux_kwm2 for s in trace.steps) > criteria_mod.WOOD_PILOTED_IGNITION_KWM2
    assert max(s.target_exposure_s for s in trace.steps) < criteria_mod.IGNITION_EXPOSURE_S
    assert _evaluate(Design.load(BASELINE), trace)["target_ignited"].value is False


def test_the_exposure_clock_resets_the_moment_the_flux_drops_back():
    hot = criteria_mod.WOOD_PILOTED_IGNITION_KWM2 + 1.0
    cold = criteria_mod.WOOD_PILOTED_IGNITION_KWM2 - 1.0
    assert sim_mod.target_exposure_s(40.0, hot, 1.0) == pytest.approx(41.0)
    assert sim_mod.target_exposure_s(40.0, cold, 1.0) == 0.0


# --- test 6: life safety spans upstream AND downstream, Annex 7 7.2.2 -------

def test_life_safety_criteria_take_the_worst_of_upstream_and_downstream():
    out = _evaluate(Design.load(BASELINE))
    # Every one of these worst values sits at a DOWNSTREAM station in `_trace`;
    # the old upstream-only criteria would have reported the U45 figure instead.
    assert out["max_air_temp_c"].value == pytest.approx(58.0)     # D45, not U45's 31.0
    assert out["max_heat_flux_kwm2"].value == pytest.approx(4.0)  # D15, not U15's 2.0
    assert out["min_visibility_m"].value == pytest.approx(12.0)   # D100, not U45's 60.0
    assert out["max_fed"].value == pytest.approx(0.05)            # D45, not U45's 0.02
    assert out["max_co_ppm"].value == pytest.approx(120.0)        # D45, not U45's 10.0


def test_life_safety_criteria_compare_against_the_ahj_limits():
    out = _evaluate(_with_ahj(max_air_temp_c=60.0, max_heat_flux_kwm2=2.5,
                              min_visibility_m=10.0, max_fed=0.3, max_co_ppm=100.0))
    assert out["max_air_temp_c"].passed        # 58 <= 60
    assert not out["max_heat_flux_kwm2"].passed  # 4.0 > 2.5
    assert out["min_visibility_m"].passed      # 12 >= 10
    assert out["max_fed"].passed               # 0.05 <= 0.3
    assert not out["max_co_ppm"].passed        # 120 > 100


# --- structure exposure, Annex 7 7.2.4 --------------------------------------

def test_structure_exposure_reports_length_and_duration_not_a_peak_temperature():
    out = _evaluate(_with_ahj(max_structure_exposure_length_m=10.0,
                              max_structure_exposure_duration_s=300.0))
    assert out["structure_exposure_length_m"].value == pytest.approx(7.0)
    # one of the two steps in `_trace` carries a non-zero length
    assert out["structure_exposure_duration_s"].value > 0.0
    assert out["structure_exposure_length_m"].passed


# The engineering constraints that used to live here are now user-declared and
# evaluated by solit2.engines.reduced.constraints; see tests/test_independence.py.

# --- design-level overrides still work --------------------------------------

def test_evaluate_applies_a_design_limit_override():
    design = _with_ahj(tvs_design_fire_mw=70.0)
    tightened = design.model_copy(
        update={"criteria": {"hrr_below_tvs_design_mw": {"limit": 40.0}}})
    out = _evaluate(tightened)
    assert out["hrr_below_tvs_design_mw"].limit == 40.0
    assert not out["hrr_below_tvs_design_mw"].passed   # 46 MW exceeds the tightened limit
    assert out["hrr_below_tvs_design_mw"].hard         # a limit override leaves hardness alone
    assert _evaluate(design)["hrr_below_tvs_design_mw"].passed


def test_a_design_override_can_set_a_limit_the_ahj_block_left_unset():
    design = Design.load(BASELINE).model_copy(
        update={"criteria": {"max_air_temp_c": {"limit": 60.0}}})
    out = _evaluate(design)
    assert out["max_air_temp_c"].status == "pass"
    assert out["max_air_temp_c"].limit == pytest.approx(60.0)


def test_evaluate_can_soften_a_hard_gate():
    design = _with_ahj(max_fed=0.3)
    softened = design.model_copy(update={"criteria": {"max_fed": {"hard": False}}})
    assert _evaluate(design)["max_fed"].hard is True
    assert _evaluate(softened)["max_fed"].hard is False


def test_evaluate_coerces_a_band_limit_supplied_as_a_json_list():
    # A design file spells a band as `"limit": [40.0, 55.0]`, and json.load hands
    # back a list; the band comparison needs the pair as a tuple.
    design = Design.load(BASELINE).model_copy(
        update={"criteria": {"max_air_temp_c": {"limit": [40.0, 70.0], "op": "in"}}})
    out = _evaluate(design)
    assert isinstance(out["max_air_temp_c"].limit, tuple)
    assert out["max_air_temp_c"].limit == (40.0, 70.0)
    assert out["max_air_temp_c"].passed    # 58 C sits inside the overridden band

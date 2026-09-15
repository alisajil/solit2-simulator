import pytest
from solit2.schema.result import Criterion
from solit2.engines.reduced import score as score_mod


class _Hyd:
    flow_lpm = 2174.3
    power_kw = 375.0
    density_mm_min = 2.4


class _Cost:
    index = 1.0


class _Trace:
    events = {}
    steps = ()


# An AHJ that has set every limit, so the classic "does a good design score well"
# tests still have real margins to average. `_unset_criteria` is the opposite case.
def _criteria(**overrides):
    base = {
        "target_ignited": Criterion.build(False, None, "is_false", True),
        "hrr_below_tvs_design_mw": Criterion.build(46.0, 50.0, "<=", True),
        "max_air_temp_c": Criterion.build(31.0, 60.0, "<=", True),
        "max_heat_flux_kwm2": Criterion.build(1.1, 5.0, "<=", True),
        "min_visibility_m": Criterion.build(60.0, 10.0, ">=", True),
        "max_fed": Criterion.build(0.05, 0.3, "<=", True),
        "max_co_ppm": Criterion.build(40.0, 500.0, "<=", True),
        "structure_exposure_length_m": Criterion.build(7.0, 20.0, "<=", True),
        "structure_exposure_duration_s": Criterion.build(120.0, 600.0, "<=", True),
        "power_kw": Criterion.build(375.0, 650.0, "<=", True),
        "density_mm_min": Criterion.build(2.4, 3.8, "<=", False),
    }
    base.update(overrides)
    return base


# Every limit SOLIT2 Annex 7 7.1 defers to the AHJ, with no AHJ having spoken.
AHJ_DEFERRED = ("hrr_below_tvs_design_mw", "max_air_temp_c", "max_heat_flux_kwm2",
                "min_visibility_m", "max_fed", "max_co_ppm",
                "structure_exposure_length_m", "structure_exposure_duration_s")


def _unset_criteria():
    ops = {"min_visibility_m": ">="}
    out = {cid: Criterion.build(1.0, None, ops.get(cid, "<="), True) for cid in AHJ_DEFERRED}
    out["target_ignited"] = Criterion.build(False, None, "is_false", True)
    out["power_kw"] = Criterion.build(375.0, 650.0, "<=", True)
    out["density_mm_min"] = Criterion.build(2.4, 3.8, "<=", False)
    return out


def test_passing_design_scores_between_zero_and_ten():
    s = score_mod.compute(_criteria(), _Hyd(), _Cost(), _Trace(), peak_lining_c=690.0)
    assert s.gates_passed
    assert 0.0 < s.total <= 10.0
    assert set(s.components) == {"water", "margin", "cost", "structural"}


def test_a_failed_hard_gate_zeroes_the_score_and_is_named():
    s = score_mod.compute(
        _criteria(hrr_below_tvs_design_mw=Criterion.build(77.0, 50.0, "<=", True)),
        _Hyd(), _Cost(), _Trace(), peak_lining_c=690.0)
    assert not s.gates_passed
    assert s.total == 0.0
    assert s.gates_failed == ["hrr_below_tvs_design_mw"]
    assert s.components["water"] > 0  # still reported, so the optimiser can steer


def test_a_failed_soft_criterion_does_not_zero_the_score():
    s = score_mod.compute(
        _criteria(density_mm_min=Criterion.build(4.5, 3.8, "<=", False)),
        _Hyd(), _Cost(), _Trace(), peak_lining_c=690.0)
    assert s.gates_passed
    assert s.total > 0.0


def test_less_water_scores_higher():
    lean = type("H", (), {"flow_lpm": 1500.0, "power_kw": 300.0, "density_mm_min": 1.8})()
    base = score_mod.compute(_criteria(), _Hyd(), _Cost(), _Trace(), peak_lining_c=690.0)
    better = score_mod.compute(_criteria(), lean, _Cost(), _Trace(), peak_lining_c=690.0)
    assert better.total > base.total


def test_hotter_lining_scores_lower():
    cool = score_mod.compute(_criteria(), _Hyd(), _Cost(), _Trace(), peak_lining_c=400.0)
    hot = score_mod.compute(_criteria(), _Hyd(), _Cost(), _Trace(), peak_lining_c=1200.0)
    assert cool.total > hot.total


def test_penalty_for_exceeding_the_density_headroom():
    # score.compute() reads the penalty threshold from `hyd.density_mm_min`
    # directly (see score.py), not from the criteria dict, so the mock hyd
    # must carry the exceeding value too -- mirrors the `lean` mock below.
    dense = type("H", (), {"flow_lpm": 2174.3, "power_kw": 375.0, "density_mm_min": 4.5})()
    s = score_mod.compute(
        _criteria(density_mm_min=Criterion.build(4.5, 3.8, "<=", False)),
        dense, _Cost(), _Trace(), peak_lining_c=690.0)
    assert any("density" in p for p in s.penalties)


def test_weights_sum_to_one():
    assert sum(score_mod.WEIGHTS.values()) == pytest.approx(1.0)


# --- test 7: a design nobody has set limits for is unassessed, not passing ---

def test_criteria_unset_lists_exactly_the_deferred_ids():
    s = score_mod.compute(_unset_criteria(), _Hyd(), _Cost(), _Trace(), peak_lining_c=690.0)
    assert set(s.criteria_unset) == set(AHJ_DEFERRED)


def test_a_fully_unset_design_reports_gates_passed_beside_a_non_empty_unset_list():
    s = score_mod.compute(_unset_criteria(), _Hyd(), _Cost(), _Trace(), peak_lining_c=690.0)
    assert s.gates_passed, "nothing failed, because nothing was asked of it"
    assert s.gates_failed == []
    assert s.criteria_unset, "...and the output must say so rather than imply approval"


def test_a_design_with_every_limit_set_has_nothing_unset():
    s = score_mod.compute(_criteria(), _Hyd(), _Cost(), _Trace(), peak_lining_c=690.0)
    assert s.criteria_unset == []


def test_unset_criteria_do_not_dilute_the_margin_component():
    """An unset limit has no margin; averaging its 0.0 in would understate the design."""
    assessed = score_mod.compute(_criteria(), _Hyd(), _Cost(), _Trace(), peak_lining_c=690.0)
    unassessed = score_mod.compute(_unset_criteria(), _Hyd(), _Cost(), _Trace(),
                                   peak_lining_c=690.0)
    assert unassessed.components["margin"] > 0.0
    assert assessed.components["margin"] > 0.0

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


def _criteria(**overrides):
    base = {
        "hrr_control_mw": Criterion.build(46.0, 50.0, "<=", True),
        "power_kw": Criterion.build(375.0, 650.0, "<=", True),
        "target_hf_kwm2": Criterion.build(9.8, 12.5, "<=", True),
        "remote_nozzle_bar": Criterion.build(50.0, (45.0, 60.0), "in", True),
        "u35_temp_c": Criterion.build(31.0, 60.0, "<=", True),
        "hf_u15_kwm2": Criterion.build(1.1, 5.0, "<=", True),
        "hf_u35_kwm2": Criterion.build(0.3, 2.5, "<=", True),
        "visibility_u35_m": Criterion.build(60.0, 10.0, ">=", True),
        "fed_d35": Criterion.build(0.05, 0.3, "<=", True),
        "density_mm_min": Criterion.build(2.4, 3.8, "<=", False),
    }
    base.update(overrides)
    return base


def test_passing_design_scores_between_zero_and_ten():
    s = score_mod.compute(_criteria(), _Hyd(), _Cost(), _Trace(), peak_lining_c=690.0)
    assert s.gates_passed
    assert 0.0 < s.total <= 10.0
    assert set(s.components) == {"water", "margin", "cost", "structural"}


def test_a_failed_hard_gate_zeroes_the_score_and_is_named():
    s = score_mod.compute(
        _criteria(hrr_control_mw=Criterion.build(77.0, 50.0, "<=", True)),
        _Hyd(), _Cost(), _Trace(), peak_lining_c=690.0)
    assert not s.gates_passed
    assert s.total == 0.0
    assert s.gates_failed == ["hrr_control_mw"]
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

import pytest
from solit2.schema.result import Criterion


def test_upper_bound_margin():
    c = Criterion.build(value=46.0, limit=50.0, op="<=", hard=True)
    assert c.passed
    assert c.margin == pytest.approx(0.08)


def test_upper_bound_failure_has_negative_margin():
    c = Criterion.build(value=77.0, limit=50.0, op="<=", hard=True)
    assert not c.passed
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


def test_every_spec_criterion_is_defined_once():
    from solit2.engines.reduced.criteria import DEFAULT_CRITERIA
    ids = [c.id for c in DEFAULT_CRITERIA]
    assert len(ids) == len(set(ids))
    assert set(ids) == {
        "hrr_control_mw", "power_kw", "target_hf_kwm2", "remote_nozzle_bar",
        "u35_temp_c", "hf_u15_kwm2", "hf_u35_kwm2", "visibility_u35_m", "fed_d35",
        "ff_u5_hf_kwm2", "ff_d20_temp_c", "density_mm_min", "pools_extinguished_s",
    }


def test_hard_gates_are_the_tender_and_solit2_set():
    from solit2.engines.reduced.criteria import DEFAULT_CRITERIA
    hard = {c.id for c in DEFAULT_CRITERIA if c.hard}
    assert hard == {
        "hrr_control_mw", "power_kw", "target_hf_kwm2", "remote_nozzle_bar",
        "u35_temp_c", "hf_u15_kwm2", "hf_u35_kwm2", "visibility_u35_m", "fed_d35",
    }


def test_stations_cover_every_criterion_location():
    from solit2.engines.reduced.criteria import STATIONS
    assert STATIONS["U35"] == -35.0
    assert STATIONS["D100"] == 100.0
    assert set(STATIONS) == {"U35", "U15", "U5", "D5", "D15", "D20", "D35", "D100"}

import pytest
from solit2.schema.result import Criterion
from solit2.schema.design import Design
from solit2.engines.reduced import criteria as criteria_mod
from solit2.engines.reduced.state import MistEffect, RunTrace, StationSample, StepRecord

BASELINE = "designs/og-dbr-rev0.json"


# Minimal stand-ins, in the style of tests/test_score.py: `evaluate` only reads
# `power_kw` and `density_mm_min` off the hydraulics, and nothing off the cost.
class _Hyd:
    power_kw = 375.0
    density_mm_min = 2.4


class _Cost:
    index = 1.0


def _station(temp_c=25.0, flux_kwm2=0.2, visibility_m=200.0, fed_tox=0.0):
    return StationSample(temp_c=temp_c, flux_kwm2=flux_kwm2,
                         visibility_m=visibility_m, fed_tox=fed_tox, fed_heat=0.0)


def _step(t_s, hrr_mw, target_flux_kwm2, stations):
    full = {name: _station() for name in criteria_mod.STATIONS}
    full.update(stations)
    return StepRecord(
        t_s=t_s, hrr_mw=hrr_mw, hrr_free_mw=hrr_mw, ceiling_temp_c=400.0,
        lining_temp_c=690.0, pipe_temp_c=120.0, target_flux_kwm2=target_flux_kwm2,
        u_eff_ms=4.2, u_critical_ms=3.72, backlayer_m=0.0, water_lpm=2174.3,
        pools_remaining=0, mist=MistEffect.none(), stations=full,
    )


def _trace():
    """A pre-activation peak the criteria must exclude, then the settled state.

    `hrr_control_mw` and `target_hf_kwm2` are measured only after full pressure,
    so the 150 MW / 40 kW-m2 first step must not reach them.
    """
    return RunTrace(
        steps=(
            _step(0.0, hrr_mw=150.0, target_flux_kwm2=40.0, stations={}),
            _step(120.0, hrr_mw=46.0, target_flux_kwm2=9.8, stations={
                "U35": _station(temp_c=31.0, flux_kwm2=0.3, visibility_m=60.0, fed_tox=0.02),
                "U15": _station(flux_kwm2=1.1),
                "U5": _station(flux_kwm2=2.0),
                "D20": _station(temp_c=55.0),
                "D35": _station(temp_c=58.0, fed_tox=0.05),
            }),
        ),
        events={"t_full_pressure_s": 90.0},
        section="bored",
        velocity_ms=5.08,
    )


def _evaluate(design):
    return criteria_mod.evaluate(_trace(), _Hyd(), _Cost(), design)


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


def test_build_rejects_an_unknown_comparison_operator():
    with pytest.raises(ValueError) as exc:
        Criterion.build(value=50.0, limit=60.0, op="<", hard=True)
    message = str(exc.value)
    assert "'<'" in message                              # names the offending operator
    assert "'<='" in message and "'>='" in message and "'in'" in message


def test_evaluate_measures_every_criterion_against_the_baseline_design():
    out = _evaluate(Design.load(BASELINE))
    assert set(out) == {spec.id for spec in criteria_mod.DEFAULT_CRITERIA}
    # Both post-activation extractors ignore the 150 MW / 40 kW-m2 first step.
    assert out["hrr_control_mw"].value == pytest.approx(46.0)
    assert out["target_hf_kwm2"].value == pytest.approx(9.8)
    assert out["u35_temp_c"].value == pytest.approx(31.0)      # peak over all steps
    assert out["visibility_u35_m"].value == pytest.approx(60.0)  # minimum over all steps
    assert out["fed_d35"].value == pytest.approx(0.05)          # final step only
    assert out["power_kw"].value == pytest.approx(375.0)        # read off the hydraulics
    assert out["remote_nozzle_bar"].value == pytest.approx(50.0)  # read off the design
    assert all(c.passed for c in out.values())


def test_evaluate_applies_a_design_limit_override():
    design = Design.load(BASELINE)
    tightened = design.model_copy(update={"criteria": {"hrr_control_mw": {"limit": 40.0}}})
    out = _evaluate(tightened)
    assert out["hrr_control_mw"].limit == 40.0
    assert not out["hrr_control_mw"].passed       # 46 MW now exceeds the tightened limit
    assert out["hrr_control_mw"].hard             # a limit override leaves hardness alone
    assert _evaluate(design)["hrr_control_mw"].passed   # unoverridden, it still passes


def test_evaluate_can_soften_a_hard_gate():
    design = Design.load(BASELINE)
    softened = design.model_copy(update={"criteria": {"fed_d35": {"hard": False}}})
    assert _evaluate(design)["fed_d35"].hard is True
    assert _evaluate(softened)["fed_d35"].hard is False


def test_evaluate_coerces_a_band_limit_supplied_as_a_json_list():
    # A design file spells a band as `"limit": [40.0, 55.0]`, and json.load hands
    # back a list; the band comparison needs the pair as a tuple.
    design = Design.load(BASELINE)
    banded = design.model_copy(
        update={"criteria": {"remote_nozzle_bar": {"limit": [40.0, 55.0]}}})
    out = _evaluate(banded)
    assert isinstance(out["remote_nozzle_bar"].limit, tuple)
    assert out["remote_nozzle_bar"].limit == (40.0, 55.0)
    assert out["remote_nozzle_bar"].passed    # 50 bar sits inside the overridden band

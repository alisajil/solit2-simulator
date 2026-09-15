import json
import pytest
from pydantic import ValidationError
from solit2.schema.design import Design

BASELINE = "designs/og-dbr-rev0.json"


def test_baseline_design_loads_with_dbr_values():
    d = Design.load(BASELINE)
    assert d.nozzles.k_factor_lpm_bar05 == pytest.approx(4.1)
    assert d.nozzles.pressure_bar == pytest.approx(50.0)
    assert d.nozzles.flow_per_head_lpm == pytest.approx(28.99, abs=0.05)
    assert d.zones.section_length_m == pytest.approx(30.0)
    assert d.zones.sections_simultaneous == 3


def test_heads_per_zone_derived_from_staggered_rows():
    # two rows at 2.4 m pitch, staggered -> one head every 1.2 m -> 25 over 30 m
    d = Design.load(BASELINE)
    assert d.heads_per_zone == 25
    assert d.active_length_m == pytest.approx(90.0)


def test_mode_flows_split_by_mass_fraction():
    d = Design.load(BASELINE)
    assert d.nozzles.mode_flow_lpm("fine") == pytest.approx(17.39, abs=0.05)
    assert d.nozzles.mode_flow_lpm("coarse") == pytest.approx(11.60, abs=0.05)


def test_fine_smd_interpolated_from_pressure_table():
    d = Design.load(BASELINE)
    assert d.nozzles.smd_um("fine") == pytest.approx(102.0, abs=1.0)
    assert d.nozzles.smd_um("coarse") == pytest.approx(450.0)


def test_pressure_below_nfpa750_floor_is_rejected(tmp_path):
    raw = json.loads(open(BASELINE).read())
    raw["nozzles"]["pressure_bar"] = 30.0
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(raw))
    with pytest.raises(ValidationError) as e:
        Design.load(p)
    assert "pressure_bar" in str(e.value)
    assert "34.5" in str(e.value)


def test_mode_fractions_must_sum_to_one(tmp_path):
    raw = json.loads(open(BASELINE).read())
    raw["nozzles"]["modes"] = [{"id": "fine", "fraction": 0.7},
                               {"id": "coarse", "fraction": 0.7}]
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(raw))
    with pytest.raises(ValidationError) as e:
        Design.load(p)
    assert "fraction" in str(e.value)


def test_velocity_envelope_defaults_to_tender_range():
    d = Design.load(BASELINE)
    assert d.ventilation.velocity_ms is None
    assert d.ventilation.velocity_range_ms == (3.88, 5.08)

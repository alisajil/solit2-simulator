import json
import pytest
from pydantic import ValidationError
from solit2.schema.design import Design, Nozzles

BASELINE = "designs/og-dbr-rev0.json"

# Real mistelix_msx_t100 droplet-size-vs-pressure performance data (matches
# solit2/presets/nozzle_mistelix_msx_t100.json), reused to build ad hoc
# Nozzles fixtures at pressures the baseline design and its JSON presets
# don't happen to use.
_MISTELIX_SMD_TABLE = {"34.5": 118.0, "45": 107.0, "50": 102.0, "60": 95.0}


def _nozzles(pressure_bar: float, smd_table: dict[str, float]) -> Nozzles:
    """Build a standalone, valid Nozzles model at a given pressure/table.

    Mode geometry and mounting are copied from the mistelix_msx_t100 preset;
    only `pressure_bar` and `smd_table` vary, so tests can isolate
    `smd_um`'s interpolation/clamping behaviour at pressures the checked-in
    JSON presets don't cover.
    """
    return Nozzles(
        preset="test-fixture",
        k_factor_lpm_bar05=4.1,
        pressure_bar=pressure_bar,
        smd_table=smd_table,
        modes=[
            {"id": "fine", "fraction": 0.60, "cone_half_angle_deg": 45.0, "launch_velocity_ms": 15.0},
            {"id": "coarse", "fraction": 0.40, "smd_um": 450.0, "cone_half_angle_deg": 8.0, "launch_velocity_ms": 100.0},
        ],
        mounting={
            "rows": 2,
            "row_lateral_offsets_m": [-2.5, 2.5],
            "height_above_carriageway_m": 5.75,
            "pitch_m": 2.4,
        },
    )


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


def test_smd_um_interpolates_between_table_keys() -> None:
    # Expected values worked out by hand from the log-log linear
    # interpolation rule smd_um's docstring names (Y = Y0 + f*(Y1-Y0) in
    # ln-space, f = (ln(p)-ln(x0))/(ln(x1)-ln(x0)), result = exp(Y)), applied
    # to the real mistelix_msx_t100 table
    # {34.5: 118.0, 45: 107.0, 50: 102.0, 60: 95.0} -- not read off whatever
    # smd_um happens to return:
    #   p=40 bar, between (34.5, 118.0) and (45, 107.0)  -> 111.74 um
    #   p=48 bar, between (45, 107.0) and (50, 102.0)    -> 103.91 um
    #   p=55 bar, between (50, 102.0) and (60, 95.0)     -> 98.28 um
    assert _nozzles(40.0, _MISTELIX_SMD_TABLE).smd_um("fine") == pytest.approx(111.74, abs=1.0)
    assert _nozzles(48.0, _MISTELIX_SMD_TABLE).smd_um("fine") == pytest.approx(103.91, abs=1.0)
    assert _nozzles(55.0, _MISTELIX_SMD_TABLE).smd_um("fine") == pytest.approx(98.28, abs=1.0)


def test_smd_um_clamps_outside_table_domain() -> None:
    # Above the table's highest key (60 bar): clamps to the 60-bar value.
    # pressure_bar=140 is the schema's own upper legal bound, well above 60.
    assert _nozzles(140.0, _MISTELIX_SMD_TABLE).smd_um("fine") == pytest.approx(95.0)

    # Below the table's lowest key: the real mistelix table's lowest key
    # (34.5) coincides exactly with the NFPA750 pressure floor, so a legal
    # Nozzles.pressure_bar can never actually fall below it -- the low-clamp
    # branch is unreachable through that specific preset. A synthetic table
    # (not real nozzle performance data -- for this clamp check only) whose
    # lowest key sits above the legal floor makes pressure_bar=34.5 genuinely
    # below the table's domain.
    synthetic_table = {"40": 130.0, "60": 90.0}
    assert _nozzles(34.5, synthetic_table).smd_um("fine") == pytest.approx(130.0)


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
    # Every required Mode field must be present so the ONLY invalid condition
    # is the fraction sum (0.7 + 0.7 = 1.4, not 1.00 +/- 0.01). Without
    # cone_half_angle_deg/launch_velocity_ms, pydantic raises "Field required"
    # errors before Nozzles._fractions_sum_to_one ever runs, and its error
    # text merely echoes the input dict back (which happens to contain the
    # word "fraction" as a key) -- that would not exercise the sum rule.
    raw["nozzles"]["modes"] = [
        {"id": "fine", "fraction": 0.7, "cone_half_angle_deg": 45.0, "launch_velocity_ms": 15.0},
        {"id": "coarse", "fraction": 0.7, "cone_half_angle_deg": 8.0, "launch_velocity_ms": 100.0},
    ]
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(raw))
    with pytest.raises(ValidationError) as e:
        Design.load(p)
    msg = str(e.value)
    assert "sum to" in msg
    assert "1.400" in msg


def test_velocity_envelope_defaults_to_tender_range():
    d = Design.load(BASELINE)
    assert d.ventilation.velocity_ms is None
    assert d.ventilation.velocity_range_ms == (3.88, 5.08)

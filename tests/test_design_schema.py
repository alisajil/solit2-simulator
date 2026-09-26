import math
import json
from pathlib import Path

import pytest
from pydantic import ValidationError
from solit2.schema.design import AHJ, Design, MissingNozzleData, Nozzles

BASELINE = "examples/designs/road-tunnel-twin-bore.json"

# The example bimodal head's droplet-size-vs-pressure table (matches
# examples/presets/nozzle_bimodal_example.json), reused to build ad hoc
# Nozzles fixtures at pressures the example design and its JSON presets
# don't happen to use.
_EXAMPLE_SMD_TABLE = {"34.5": 118.0, "45": 107.0, "50": 102.0, "60": 95.0}


def _nozzles(pressure_bar: float, smd_table: dict[str, float]) -> Nozzles:
    """Build a standalone, valid Nozzles model at a given pressure/table.

    Mode geometry and mounting are copied from the bimodal example preset;
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


def test_the_example_design_loads_with_its_stated_values():
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
    # to the example bimodal table
    # {34.5: 118.0, 45: 107.0, 50: 102.0, 60: 95.0} -- not read off whatever
    # smd_um happens to return:
    #   p=40 bar, between (34.5, 118.0) and (45, 107.0)  -> 111.74 um
    #   p=48 bar, between (45, 107.0) and (50, 102.0)    -> 103.91 um
    #   p=55 bar, between (50, 102.0) and (60, 95.0)     -> 98.28 um
    assert _nozzles(40.0, _EXAMPLE_SMD_TABLE).smd_um("fine") == pytest.approx(111.74, abs=1.0)
    assert _nozzles(48.0, _EXAMPLE_SMD_TABLE).smd_um("fine") == pytest.approx(103.91, abs=1.0)
    assert _nozzles(55.0, _EXAMPLE_SMD_TABLE).smd_um("fine") == pytest.approx(98.28, abs=1.0)


def test_smd_um_clamps_outside_table_domain() -> None:
    # Above the table's highest key (60 bar): clamps to the 60-bar value.
    # pressure_bar=140 is the schema's own upper legal bound, well above 60.
    assert _nozzles(140.0, _EXAMPLE_SMD_TABLE).smd_um("fine") == pytest.approx(95.0)

    # Below the table's lowest key: the example table's lowest key
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


def test_fire_base_height_must_be_below_the_fuel_top(tmp_path):
    """Task 18: the fuel cannot start above its own top, and the schema must
    say so by naming both values, not merely reject with some generic error."""
    raw = json.loads(open(BASELINE).read())
    raw["fire"] = {"preset": "hgv_150mw", "footprint": {"base_height_m": 5.0}}
    p = tmp_path / "bad_base_height.json"
    p.write_text(json.dumps(raw))
    with pytest.raises(ValidationError) as e:
        Design.load(p)
    msg = str(e.value)
    assert "5.0" in msg  # base_height_m, the offending value
    assert "4.0" in msg  # top_height_m (hgv_150mw's preset value), for comparison


def test_the_example_design_declares_its_own_velocity_envelope():
    d = Design.load(BASELINE)
    assert d.ventilation.velocity_ms is None
    assert d.ventilation.velocity_range_ms == (3.88, 5.08)


def test_the_ahj_block_defaults_to_nothing_set():
    """SOLIT2 Annex 7 7.1 defers every absolute value to the authority having
    jurisdiction, so the tool must start with none of them assumed."""
    d = Design.load(BASELINE)
    deferred = ("tvs_design_fire_mw", "max_air_temp_c", "max_heat_flux_kwm2",
                "min_visibility_m", "max_fed", "max_co_ppm",
                "max_structure_exposure_length_m", "max_structure_exposure_duration_s")
    assert all(getattr(d.ahj, name) is None for name in deferred)


def test_the_structure_reporting_threshold_is_annex_7s_own_example_figure():
    # 7.2.4 uses 500 C in its own wording; it is a reporting threshold, not a
    # limit, so unlike every other AHJ field it has a value out of the box.
    assert Design.load(BASELINE).ahj.structure_temp_threshold_c == 500.0


def test_a_design_can_set_ahj_limits(tmp_path):
    raw = json.loads(open(BASELINE).read())
    raw["ahj"] = {"note": "Annex 7 7.1 limits set by the road authority",
                  "tvs_design_fire_mw": 50.0, "max_air_temp_c": 60.0}
    p = tmp_path / "with_ahj.json"
    p.write_text(json.dumps(raw))
    d = Design.load(p)
    assert d.ahj.tvs_design_fire_mw == 50.0
    assert d.ahj.max_air_temp_c == 60.0
    assert d.ahj.max_fed is None
    assert "road authority" in d.ahj.note


def test_the_ahj_block_is_frozen_and_rejects_unknown_fields():
    with pytest.raises(ValidationError):
        AHJ(max_air_temp_c=60.0, max_smoke_temp_c=99.0)


def test_the_solit2_test_tunnel_preset_loads(tmp_path):
    """Annex 7 5.2.7 mandates BOTH 1.5 and 3.0 m/s. Test conditions are not
    site conditions, which Annex 7 3.3 governs transferring between."""
    raw = json.loads(open(BASELINE).read())
    raw["tunnel"] = {"preset": "solit2_test"}
    raw["ventilation"] = {"mode": "longitudinal", "velocity_range_ms": [1.5, 3.0]}
    p = tmp_path / "test_conditions.json"
    p.write_text(json.dumps(raw))
    d = Design.load(p)
    assert d.tunnel.section == "test"
    assert d.ventilation.velocity_range_ms == (1.5, 3.0)
    assert "5.2.7" in d.tunnel.note


def test_from_dict_merges_presets_exactly_like_load(tmp_path):
    """from_dict and load must produce an identical Design from identical
    input, since load becomes a thin wrapper over from_dict."""
    raw = json.loads(Path("examples/designs/road-tunnel-twin-bore-single-mode.json").read_text())
    from_dict_design = Design.from_dict(raw)
    from_load_design = Design.load("examples/designs/road-tunnel-twin-bore-single-mode.json")
    assert from_dict_design == from_load_design


def test_from_dict_rejects_an_unknown_preset_kind_the_same_way_load_does():
    raw = {"meta": {"name": "x"}, "tunnel": {"preset": "does_not_exist"},
           "fire": {"preset": "hgv_150mw"}, "nozzles": {"preset": "template"},
           "zones": {"section_length_m": 30.0, "sections_simultaneous": 1,
                     "manual_activation_s": 60.0, "activation_delay_s": 0.0,
                     "pump_ramp_s": 30.0, "duration_min": 30.0},
           "ventilation": {"mode": "longitudinal", "velocity_ms": 2.0},
           "detection": {"type": "linear_heat", "threshold_c": 60.0, "sensor_spacing_m": 25.0},
           "hydraulics": {"preset": "template"}}
    with pytest.raises(FileNotFoundError):
        Design.from_dict(raw)


def _spectrum_nozzles(**mode_extra):
    mode = {"id": "fine", "fraction": 1.0, "smd_um": 90.0,
            "cone_half_angle_deg": 50.0, "launch_velocity_ms": 25.0, **mode_extra}
    return Nozzles.model_validate({
        "preset": "tester_input", "k_factor_lpm_bar05": 2.8, "pressure_bar": 100.0,
        "modes": [mode],
        "mounting": {"rows": 2, "row_lateral_offsets_m": [-2.2, 2.2],
                     "height_above_carriageway_m": 4.9, "pitch_m": 4.0}})


def test_spread_is_solved_from_the_testers_dv50_and_dv90():
    n = _spectrum_nozzles(dv50_um=100.0, dv90_um=161.6398).spread_n("fine")
    assert n == pytest.approx(2.5, abs=1e-4)
    assert n == pytest.approx(math.log(math.log(10) / math.log(2)) / math.log(1.616398), rel=1e-6)


def test_a_mode_without_a_measured_spectrum_refuses_rather_than_assuming_one():
    with pytest.raises(MissingNozzleData, match="Dv50 and Dv90"):
        _spectrum_nozzles().spread_n("fine")


def test_dv90_must_be_coarser_than_dv50():
    with pytest.raises(MissingNozzleData, match="coarser"):
        _spectrum_nozzles(dv50_um=150.0, dv90_um=120.0).spread_n("fine")


def test_a_spectrum_too_wide_for_a_finite_sauter_mean_is_refused():
    # Dv90/Dv50 = 4 gives n = ln(ln10/ln2)/ln 4 = 0.87, and n <= 1 has no finite D32.
    with pytest.raises(MissingNozzleData, match="too wide"):
        _spectrum_nozzles(dv50_um=100.0, dv90_um=400.0).spread_n("fine")

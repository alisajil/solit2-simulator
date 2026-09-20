import shutil
from pathlib import Path

import pytest

from solit2.engines.fds import reader
from solit2.schema.design import Design

BASELINE = "designs/og-dbr-rev0.json"
FIXTURES = Path("tests/fixtures/fds")


@pytest.fixture
def run_dir(tmp_path):
    """A finished run directory, named the way `deck.generate` names its CHID."""
    from solit2.engines.reduced.envelope import _design_sha
    chid = _design_sha(Design.load(BASELINE))
    shutil.copy(FIXTURES / "sample_devc.csv", tmp_path / f"{chid}_devc.csv")
    shutil.copy(FIXTURES / "sample_hrr.csv", tmp_path / f"{chid}_hrr.csv")
    shutil.copy(FIXTURES / "sample_ctrl.csv", tmp_path / f"{chid}_ctrl.csv")
    return tmp_path


def _free_burn_dir(tmp_path, t_end: float = 2.0, scale: float = 1.5):
    """A finished free-burn run: the same clock, a larger HRR."""
    from solit2.engines.fds import deck as deck_mod
    free = tmp_path / "free"
    free.mkdir()
    lines = (FIXTURES / "sample_hrr.csv").read_text().splitlines()
    rows = [ln for ln in lines[2:] if float(ln.split(",")[0]) <= t_end]
    scaled = [",".join([r.split(",")[0]] + [f"{float(v) * scale:.3f}" for v in r.split(",")[1:]])
              for r in rows]
    chid = deck_mod.chid(Design.load(BASELINE), suppression=False)
    (free / f"{chid}_hrr.csv").write_text("\n".join(lines[:2] + scaled) + "\n")
    return free


def test_the_reader_fills_the_same_result_contract_tier_1_does(run_dir):
    result = reader.read(run_dir, Design.load(BASELINE))
    assert result.meta["engine"] == "fds"
    assert result.meta["design_name"] == "og-dbr-rev0"
    assert set(result.criteria) >= {"target_ignited", "max_air_temp_c"}
    assert "hrr_mw" in result.peaks
    assert "total" in result.score


def test_the_hrr_peak_comes_from_the_hrr_csv_in_megawatts(run_dir):
    result = reader.read(run_dir, Design.load(BASELINE))
    assert result.peaks["hrr_mw"] == pytest.approx(22.0)


def test_a_missing_device_column_is_fatal(run_dir):
    from solit2.engines.reduced.envelope import _design_sha
    chid = _design_sha(Design.load(BASELINE))
    devc = run_dir / f"{chid}_devc.csv"
    lines = devc.read_text().splitlines()
    # drop the target gauge column entirely
    header = lines[1].split(",")
    drop = header.index("TARGET_FLUX")
    devc.write_text("\n".join(
        ",".join(p for i, p in enumerate(ln.split(",")) if i != drop) for ln in lines))
    with pytest.raises(KeyError, match="TARGET_FLUX"):
        reader.read(run_dir, Design.load(BASELINE))


def test_mist_is_reported_empty_rather_than_zero(run_dir):
    # every MistEffect field is a reduced-order construct; FDS computes none of
    # them, and a zero would read as a measurement
    result = reader.read(run_dir, Design.load(BASELINE))
    assert result.mist == {}


def test_the_result_round_trips_through_json(run_dir):
    from solit2.schema.result import Result
    result = reader.read(run_dir, Design.load(BASELINE))
    assert Result.model_validate_json(result.model_dump_json()) == result


def test_the_lining_temperature_comes_from_the_ceiling_device_above_the_fire(run_dir):
    from solit2.engines.fds import deck as deck_mod
    from solit2.engines.reduced.envelope import _design_sha
    chid = _design_sha(Design.load(BASELINE))
    devc = run_dir / f"{chid}_devc.csv"
    lines = devc.read_text().splitlines()
    column = lines[1].split(",").index(deck_mod.fire_ceiling_device_id())
    marked = []
    for row in lines[2:]:
        cells = row.split(",")
        cells[column] = "911.0"
        marked.append(",".join(cells))
    devc.write_text("\n".join(lines[:2] + marked))
    result = reader.read(run_dir, Design.load(BASELINE))
    assert result.peaks["lining_temp_c"] == pytest.approx(911.0)


def test_the_result_names_the_gap_between_the_stepped_and_the_smooth_section(run_dir):
    # a stair-stepped circle cannot match a smooth one; the requirement is that
    # the difference is visible in the result, not that it is zero
    from solit2.engines.fds import deck as deck_mod
    from solit2.engines.reduced.geometry import section_geometry
    design = Design.load(BASELINE)
    geom = section_geometry(design)
    stepped_m2 = deck_mod.stepped_free_area_m2(geom)
    assert stepped_m2 != pytest.approx(geom.free_area_m2), "nothing to report otherwise"
    named = [w for w in reader.read(run_dir, design).warnings if "free area" in w]
    assert len(named) == 1
    assert f"{stepped_m2:.1f} m2" in named[0]
    assert f"{geom.free_area_m2:.1f} m2" in named[0]
    assert "%" in named[0]


def test_the_result_says_which_penalties_a_tier_2_run_cannot_receive(run_dir):
    # u_critical_ms = 0.0 makes score.py's backlayering deduction and the
    # envelope's critical-velocity warning unreachable, and the leaderboard
    # ranks Tier 1 and Tier 2 in one list. An unreachable penalty that nothing
    # names reads as a clean run.
    design = Design.load(BASELINE)
    result = reader.read(run_dir, design)
    assert any("critical-velocity penalty cannot apply" in w for w in result.warnings)
    velocity = design.ventilation.velocity_ms or max(design.ventilation.velocity_range_ms)
    single = [w for w in result.warnings if "single ventilation velocity" in w]
    assert len(single) == 1
    assert f"{velocity:.2f} m/s" in single[0]
    assert result.criteria_cases == {}


def test_the_engine_version_is_unverified_when_the_log_does_not_name_one(run_dir):
    # "fds-6.11.1" used to be hardcoded: a provenance claim nothing measured
    result = reader.read(run_dir, Design.load(BASELINE))
    assert result.meta["engine_version"] == reader.ENGINE_VERSION_UNKNOWN
    assert any("unverified" in w for w in result.warnings)


def test_the_engine_version_comes_from_the_fds_log_when_it_names_one(run_dir):
    (run_dir / "run.out").write_text(
        " Fire Dynamics Simulator\n Revision : FDS6.9.1-0-g889da6a-release\n")
    result = reader.read(run_dir, Design.load(BASELINE))
    assert result.meta["engine_version"] == "fds-6.9.1"
    assert not any("unverified" in w for w in result.warnings)


def test_activation_comes_from_fds_own_control_log_not_the_design_timetable(run_dir):
    # The design says "60 s after detection"; the reader used to write
    # activation_delay_s measured from t=0, as if the fire tripped the detector
    # at ignition. FDS records when its controls changed state.
    result = reader.read(run_dir, Design.load(BASELINE))
    assert result.events["t_detect_s"] == pytest.approx(1.0)
    assert result.events["t_activate_s"] == pytest.approx(2.0)
    design = Design.load(BASELINE)
    assert result.events["t_full_pressure_s"] == pytest.approx(2.0 + design.zones.pump_ramp_s)
    assert "t_activation_s" not in result.events, "Tier 1's key names, so the timeline and HMI light up"


def test_water_arrives_at_the_recorded_activation_and_ramps_with_the_pumps():
    # Tier 1's `_flow_fraction`, on FDS's recorded activation instant: nothing
    # before the valves open, full flow only after the pumps' ramp.
    ramp = 30.0
    assert reader._flow_fraction(1.0, 2.0, ramp) == 0.0
    assert reader._flow_fraction(2.0, 2.0, ramp) == 0.0
    assert reader._flow_fraction(17.0, 2.0, ramp) == pytest.approx(0.5)
    assert reader._flow_fraction(32.0, 2.0, ramp) == 1.0
    assert reader._flow_fraction(100.0, None, ramp) == 0.0, "no activation, no water"
    assert reader._flow_fraction(2.0, 2.0, 0.0) == 1.0, "no ramp: full flow at once"


def test_a_run_whose_detectors_never_tripped_is_refused_as_a_mist_result(run_dir):
    from solit2.engines.reduced.envelope import _design_sha
    chid = _design_sha(Design.load(BASELINE))
    ctrl = run_dir / f"{chid}_ctrl.csv"
    ctrl.write_text("s,status,status\nTime,DETECT,ACT\n0.0,-1,-1\n1.0,-1,-1\n2.0,-1,-1\n")
    with pytest.raises(ValueError, match="never tripped"):
        reader.read(run_dir, Design.load(BASELINE))


def test_a_missing_control_log_is_fatal(run_dir):
    from solit2.engines.reduced.envelope import _design_sha
    chid = _design_sha(Design.load(BASELINE))
    (run_dir / f"{chid}_ctrl.csv").unlink()
    with pytest.raises(FileNotFoundError):
        reader.read(run_dir, Design.load(BASELINE))


def test_without_a_free_burn_run_the_free_hrr_mirrors_and_says_so(run_dir):
    result = reader.read(run_dir, Design.load(BASELINE))
    assert result.timeseries["hrr_free_mw"] == result.timeseries["hrr_mw"]
    assert any("mirrors hrr_mw" in w for w in result.warnings)


def test_a_free_burn_run_supplies_the_free_hrr_and_the_mirror_warning_goes(run_dir, tmp_path):
    free = _free_burn_dir(tmp_path)
    result = reader.read(run_dir, Design.load(BASELINE), free_burn_dir=free)
    assert result.peaks["hrr_free_burn_mw"] == pytest.approx(1.5 * result.peaks["hrr_mw"])
    assert all(f == pytest.approx(1.5 * m) for f, m in
               zip(result.timeseries["hrr_free_mw"], result.timeseries["hrr_mw"]))
    assert not any("mirrors hrr_mw" in w for w in result.warnings)
    assert any("free-burn FDS run" in w for w in result.warnings)


def test_a_free_burn_run_shorter_than_the_mist_run_is_refused(run_dir, tmp_path):
    free = _free_burn_dir(tmp_path, t_end=0.5)
    with pytest.raises(ValueError, match="not comparable"):
        reader.read(run_dir, Design.load(BASELINE), free_burn_dir=free)


def test_the_result_names_every_stand_in_the_deck_makes(run_dir):
    result = reader.read(run_dir, Design.load(BASELINE))
    text = " ".join(result.warnings)
    for phrase in ("E_COEFFICIENT", "snapped to the", "target flux gauge sits", "burner segments",
                   "ceiling thermocouple line runs over the fuel load"):
        assert phrase in text, phrase


def test_the_hrr_column_is_found_by_name_not_by_position(run_dir):
    # FDS's _hrr.csv carries a different column count with and without
    # particles, so a fixed index is a guess that happens to hold.
    from solit2.engines.reduced.envelope import _design_sha
    chid = _design_sha(Design.load(BASELINE))
    path = run_dir / f"{chid}_hrr.csv"
    lines = path.read_text().splitlines()
    shifted = [",".join([p.split(",")[0], "0.0"] + p.split(",")[1:]) for p in lines[2:]]
    path.write_text("\n".join([lines[0] + ",kW", "Time,DUMMY," + lines[1].split(",", 1)[1]]
                               + shifted))
    result = reader.read(run_dir, Design.load(BASELINE))
    assert result.peaks["hrr_mw"] == pytest.approx(22.0)

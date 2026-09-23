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


def _set_ceiling(run_dir, values: dict[str, float], others_c: float = 40.0):
    """Every ceiling device at `others_c`, then the named ones overridden.

    The fixture puts the whole ceiling line on one series, so a test that moves
    a single device proves nothing about which one the reader picked.
    """
    from solit2.engines.fds import deck as deck_mod
    from solit2.engines.reduced.envelope import _design_sha
    chid = _design_sha(Design.load(BASELINE))
    devc = run_dir / f"{chid}_devc.csv"
    lines = devc.read_text().splitlines()
    header = [c.strip() for c in lines[1].split(",")]
    wanted = {name: others_c for name in header
              if name.startswith(deck_mod.CEILING_TC_PREFIX)}
    wanted.update(values)
    columns = {header.index(name): v for name, v in wanted.items()}
    rows = []
    for row in lines[2:]:
        cells = row.split(",")
        for index, value in columns.items():
            cells[index] = f"{value}"
        rows.append(",".join(cells))
    devc.write_text("\n".join(lines[:2] + rows))


def test_the_lining_temperature_is_the_hottest_ceiling_not_the_point_above_the_fire(run_dir):
    """Tier 1 holds `ceiling_temp_c` and `lining_temp_c` as ONE variable, a
    correlation evaluated at x=0 whose decay peaks there. FDS is not obliged to
    agree about where the hottest lining is, and does not: at 5.08 m/s the plume
    leans downstream, and a real run read 78.1 C above the fire against 132.6 C
    five metres past it. Reading the cooler one into the structural score, which
    measures how far the peak lining sits below 1350 C, overstates the margin.
    """
    from solit2.engines.fds import deck as deck_mod
    above_fire = deck_mod.fire_ceiling_device_id()
    downstream = f"{deck_mod.CEILING_TC_PREFIX}13"
    assert deck_mod.CEILING_TC_PREFIX in downstream and downstream != above_fire
    _set_ceiling(run_dir, {above_fire: 78.1, downstream: 132.6})
    result = reader.read(run_dir, Design.load(BASELINE))
    assert result.peaks["lining_temp_c"] == pytest.approx(132.6)
    assert result.peaks["ceiling_temp_c"] == pytest.approx(132.6), "Tier 1's identity holds"


def test_the_result_says_where_the_hottest_lining_actually_sat(run_dir):
    from solit2.engines.fds import deck as deck_mod
    _set_ceiling(run_dir, {deck_mod.fire_ceiling_device_id(): 78.1,
                           f"{deck_mod.CEILING_TC_PREFIX}13": 132.6})
    named = [w for w in reader.read(run_dir, Design.load(BASELINE).model_copy())
             .warnings if "hottest lining" in w]
    assert named and "+5 m" in named[0] and "133 C" in named[0] and "78 C" in named[0]


def test_no_such_warning_when_the_peak_really_is_above_the_fire(run_dir):
    from solit2.engines.fds import deck as deck_mod
    _set_ceiling(run_dir, {deck_mod.fire_ceiling_device_id(): 900.0})
    result = reader.read(run_dir, Design.load(BASELINE))
    assert result.peaks["lining_temp_c"] == pytest.approx(900.0)
    assert not any("hottest lining" in w for w in result.warnings)


def test_ceiling_device_positions_are_the_ones_the_deck_laid_out(run_dir):
    from solit2.engines.fds import deck as deck_mod
    text = deck_mod.generate(Design.load(BASELINE))
    for index in (0, 12, 13, 20):
        device = f"{deck_mod.CEILING_TC_PREFIX}{index}"
        line = next(ln for ln in text.splitlines() if f"ID='{device}'" in ln)
        assert reader.ceiling_device_x_m(device) == pytest.approx(
            float(line.split("XYZ=")[1].split(",")[0]))



def test_the_result_reports_the_emitted_free_area_against_tier_1s(run_dir):
    """The figure must be a measurement of the emitted geometry, not a claim
    about it. They agree now; the requirement is that the result still says so
    from the numbers, and would say the opposite if a change reopened a gap."""
    from solit2.engines.fds import deck as deck_mod
    from solit2.engines.reduced.geometry import section_geometry
    design = Design.load(BASELINE)
    geom = section_geometry(design)
    stepped_m2 = deck_mod.stepped_free_area_m2(geom)
    assert stepped_m2 == pytest.approx(geom.free_area_m2, rel=1e-3)
    named = [w for w in reader.read(run_dir, design).warnings if "free area" in w]
    assert len(named) == 1
    assert f"{stepped_m2:.1f} m2" in named[0] and f"{geom.free_area_m2:.1f} m2" in named[0]
    assert "same cross-section" in named[0]


def test_a_reopened_geometry_gap_is_reported_as_one(run_dir, monkeypatch):
    from solit2.engines.fds import deck as deck_mod
    from solit2.engines.reduced.geometry import section_geometry
    design = Design.load(BASELINE)
    true_m2 = section_geometry(design).free_area_m2
    monkeypatch.setattr(deck_mod, "stepped_free_area_m2", lambda geom, dx_m=0.6: true_m2 * 0.92)
    named = [w for w in reader.read(run_dir, design).warnings if "free area" in w]
    assert len(named) == 1
    assert "-8.0%" in named[0] and "not modelling the same cross-section" in named[0]



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


def test_a_result_says_when_its_run_came_from_a_different_deck(run_dir):
    from solit2.engines.fds import deck as deck_mod
    design = Design.load(BASELINE)
    # no deck at all: the reader cannot check, and says so
    assert any("kept no deck.fds" in w for w in reader.read(run_dir, design).warnings)

    (run_dir / "deck.fds").write_text(deck_mod.generate(design))
    current = reader.read(run_dir, design).warnings
    assert not any("deck" in w and "NOT" in w for w in current)
    assert not any("kept no deck.fds" in w for w in current)

    (run_dir / "deck.fds").write_text(
        deck_mod.generate(design).replace("E_COEFFICIENT=0.4", "E_COEFFICIENT=0.9"))
    assert any("NOT the deck this design generates now" in w
               for w in reader.read(run_dir, design).warnings)


def test_a_source_build_is_named_as_one_rather_than_passed_off_as_a_release(run_dir):
    (run_dir / "x.out").write_text(
        " Revision         : -master\n"
        " Revision Date    : Thu Sep 17 12:46:53 2026 -0400\n")
    result = reader.read(run_dir, Design.load(BASELINE))
    assert result.meta["engine_version"] == "fds-master@2026-09-17"
    assert any("build from source" in w and "not a numbered FDS release" in w
               for w in result.warnings)
    assert not any("unverified" in w for w in result.warnings)


def test_a_numbered_release_carries_no_source_build_caveat(run_dir):
    (run_dir / "x.out").write_text(" Revision         : FDS6.9.1-0-g889da6a-release\n")
    result = reader.read(run_dir, Design.load(BASELINE))
    assert result.meta["engine_version"] == "fds-6.9.1"
    assert not any("build from source" in w for w in result.warnings)
    assert not any("unverified" in w for w in result.warnings)


def test_no_banner_at_all_is_still_reported_as_unverified(run_dir):
    result = reader.read(run_dir, Design.load(BASELINE))
    assert result.meta["engine_version"] == reader.ENGINE_VERSION_UNKNOWN
    assert any("neither a release nor a source revision" in w for w in result.warnings)


def test_a_run_that_stops_before_full_pressure_says_its_suppression_means_nothing_yet(run_dir):
    """Measured on a real 250 s pair: the mist ran 22 s at up to 72 % of flow,
    the suppressed and free-burn HRR agreed to 0.3 %, and the ceiling above the
    fire differed by 119 C. FDS's E_COEFFICIENT lowers a prescribed burner only
    as water lands and stays on the fuel, while droplets cool the gas at once,
    so a run cut off here reads as "the mist did nothing" when it has barely
    started."""
    design = Design.load(BASELINE)
    result = reader.read(run_dir, design)
    # the fixture activates at 2.0 s and runs to 2.0 s, so full pressure is ahead
    named = [w for w in result.warnings if "before the pumps reach full pressure" in w]
    assert named, result.warnings
    assert "must not be read as the suppression this system achieves" in named[0]


def _extend_run(run_dir, hrr_kw_extra: list[float]):
    """Append more samples to the fixture's devc/hrr CSVs, one per value in
    `hrr_kw_extra`, each a whole second after the last. The devc rows repeat
    the last real row's values -- only the clock and the HRR move -- because
    these tests are about the HRR peak-passed rule, not about what every
    other device reads."""
    from solit2.engines.reduced.envelope import _design_sha
    chid = _design_sha(Design.load(BASELINE))
    hrr_path = run_dir / f"{chid}_hrr.csv"
    hrr_lines = hrr_path.read_text().splitlines()
    last_t = float(hrr_lines[-1].split(",")[0])
    n_extra_cols = len(hrr_lines[-1].split(",")) - 2
    new_hrr_rows = [f"{last_t + i + 1:.1f},{kw * 1000.0:.1f}," + ",".join(["0.0"] * n_extra_cols)
                    for i, kw in enumerate(hrr_kw_extra)]
    hrr_path.write_text("\n".join(hrr_lines + new_hrr_rows) + "\n")

    devc_path = run_dir / f"{chid}_devc.csv"
    devc_lines = devc_path.read_text().splitlines()
    last_row = devc_lines[-1].split(",")
    new_devc_rows = [",".join([f"{last_t + i + 1:.1f}"] + last_row[1:])
                     for i in range(len(hrr_kw_extra))]
    devc_path.write_text("\n".join(devc_lines + new_devc_rows) + "\n")


def test_hrr_peak_passed_true_after_a_ten_percent_fall():
    assert reader.hrr_peak_passed([0.0, 10.0, 20.0, 20.0, 18.0]) is True


def test_hrr_peak_passed_true_at_exactly_the_ten_percent_threshold():
    assert reader.hrr_peak_passed([0.0, 20.0, 18.0]) is True


def test_hrr_peak_passed_false_when_still_at_its_max_at_the_end():
    assert reader.hrr_peak_passed([0.0, 10.0, 20.0]) is False


def test_hrr_peak_passed_false_under_a_ten_percent_fall():
    # 20 -> 18.5 is a 7.5% fall, short of PEAK_PASSED_DROP_FRACTION
    assert reader.hrr_peak_passed([0.0, 10.0, 20.0, 18.5]) is False


def test_hrr_peak_passed_false_for_a_curve_that_never_rises():
    # 0 <= 0 * 0.9 would be trivially true; a fire that never got going has no
    # peak to have passed
    assert reader.hrr_peak_passed([0.0, 0.0, 0.0]) is False


def test_the_result_reports_the_peak_passed_when_the_run_reaches_it(run_dir):
    _extend_run(run_dir, [20.0, 18.0])  # rises from the fixture's own 22 MW... falls back
    result = reader.read(run_dir, Design.load(BASELINE))
    assert result.peaks["hrr_mw"] == pytest.approx(22.0)
    assert result.peaks["hrr_peak_passed"] is True
    assert not any("never fell back" in w for w in result.warnings)


def test_the_result_warns_when_the_window_stops_before_the_peak(run_dir):
    # the raw 3-sample fixture ends AT its own maximum, 22 MW at the last sample
    result = reader.read(run_dir, Design.load(BASELINE))
    assert result.peaks["hrr_peak_passed"] is False
    named = [w for w in result.warnings if "never fell back" in w]
    assert named
    assert "LOWER BOUND" in named[0] and "10%" in named[0]


def test_the_e_coefficient_warning_names_the_runs_own_deck_not_the_module_default(run_dir):
    from solit2.engines.fds import deck as deck_mod
    design = Design.load(BASELINE)
    (run_dir / "deck.fds").write_text(
        deck_mod.generate(design, e_coefficient=0.25))
    result = reader.read(run_dir, design)
    named = [w for w in result.warnings if "E_COEFFICIENT" in w]
    assert named
    assert "0.25" in named[0] and "0.4" not in named[0]


def test_the_e_coefficient_warning_falls_back_to_the_module_default_with_no_deck(run_dir):
    # no deck.fds in this run_dir: nothing on disk to read the actual E from,
    # so the module's own default is the best available answer
    from solit2.engines.fds import deck as deck_mod
    result = reader.read(run_dir, Design.load(BASELINE))
    named = [w for w in result.warnings if "E_COEFFICIENT" in w]
    assert named
    assert f"{deck_mod.E_COEFFICIENT}" in named[0]


def test_a_run_that_passes_full_pressure_carries_no_such_caveat(run_dir):
    import shutil

    from solit2.engines.reduced.envelope import _design_sha
    design = Design.load(BASELINE)
    # No pump ramp, so ACT at 2.0 s IS full pressure and the last sample reaches it.
    instant = design.model_copy(
        update={"zones": design.zones.model_copy(update={"pump_ramp_s": 0.0})})
    old_chid, new_chid = _design_sha(design), _design_sha(instant)
    assert old_chid != new_chid, "the sha covers the design, so the run dir must be renamed"
    for suffix in ("_devc.csv", "_hrr.csv", "_ctrl.csv"):
        shutil.copy(run_dir / f"{old_chid}{suffix}", run_dir / f"{new_chid}{suffix}")
    result = reader.read(run_dir, instant)
    assert result.events["t_full_pressure_s"] == pytest.approx(2.0)
    assert not any("before the pumps reach full pressure" in w for w in result.warnings)

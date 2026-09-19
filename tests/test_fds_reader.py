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
    return tmp_path


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

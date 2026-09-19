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

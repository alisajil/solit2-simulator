"""Slice parsing on synthetic files with known values, and on one real FDS file."""
import struct
from pathlib import Path

import numpy as np
import pytest

from solit2.engines.fds import slices

FIXTURE = Path("tests/fixtures/fds/sample_1_1.sf")


def _rec(payload: bytes) -> bytes:
    return struct.pack("<i", len(payload)) + payload + struct.pack("<i", len(payload))


def _write_sf(path: Path, header, bounds, times, frames) -> None:
    """frames: list of arrays shaped (nk, nj, ni), written in FDS's Fortran order."""
    out = b"".join(_rec(h.ljust(30).encode()) for h in header)
    out += _rec(struct.pack("<6i", *bounds))
    for t, f in zip(times, frames):
        out += _rec(struct.pack("<f", t)) + _rec(np.asarray(f, dtype="<f4").tobytes())
    path.write_bytes(out)


def _write_smv(path: Path, chid: str) -> None:
    """Two meshes side by side on x: nodes 0,1,2 and 2,3,4; y nodes -1,0,1; z nodes 0,1,2."""
    def mesh(n, xs):
        lines = [f"GRID   MESH_{n:07d}", "   2   2   2   0   0   0   0   0   0", "",
                 "TRNX", "    0"] + [f"    {i}   {x:.5f}" for i, x in enumerate(xs)] + [
                 "TRNY", "    0", "    0  -1.00000", "    1   0.00000", "    2   1.00000",
                 "TRNZ", "    0", "    0   0.00000", "    1   1.00000", "    2   2.00000", ""]
        return lines
    slcf = []
    for n in (1, 2):
        slcf += [f"SLCF     {n} # STRUCTURED &     0     2     1     1     0     2 !      1      0      2",
                 f" {chid}_{n}_1.sf", " TEMPERATURE", " temp", " C"]
    path.write_text("\n".join(mesh(1, [0.0, 1.0, 2.0]) + mesh(2, [2.0, 3.0, 4.0]) + slcf) + "\n")


def _frame(xs, scale=1.0):
    # value = 10*k + x, so every stitched cell is checkable
    # nj axis has 1 element to match the fixture's j1==j2==1 bounds (a single-plane slice)
    return np.array([[[10 * k + x for x in xs] for _ in range(1)] for k in range(3)]) * scale


@pytest.fixture
def run_dir(tmp_path):
    _write_smv(tmp_path / "case.smv", "case")
    bounds = (0, 2, 1, 1, 0, 2)
    _write_sf(tmp_path / "case_1_1.sf", ("TEMPERATURE", "temp", "C"), bounds,
              [0.0, 5.0], [_frame([0, 1, 2]), _frame([0, 1, 2], 2.0)])
    _write_sf(tmp_path / "case_2_1.sf", ("TEMPERATURE", "temp", "C"), bounds,
              [0.0, 5.0, 10.0], [_frame([2, 3, 4]), _frame([2, 3, 4], 2.0), _frame([2, 3, 4], 3.0)])
    return tmp_path


def test_read_sf_parses_the_real_fixture():
    header, bounds, times, frames = slices.read_sf(FIXTURE)
    assert header == ("TEMPERATURE", "temp", "C")
    assert bounds == (0, 200, 4, 4, 0, 5)
    # actual FDS output time is 18.0265s (adaptive time-stepping); not exactly 18.0
    assert len(times) == 6 and times[-1] == pytest.approx(18.0265, rel=1e-4)
    assert frames.shape == (6, 6, 1, 201)


def test_read_sf_stops_at_a_truncated_record(tmp_path):
    src = FIXTURE.read_bytes()
    cut = tmp_path / "cut.sf"
    cut.write_bytes(src[:-100])
    _, _, times, frames = slices.read_sf(cut)
    assert len(times) == 5 and frames.shape[0] == 5


def test_read_smv_lists_slices_and_grids(run_dir):
    metas, grids = slices.read_smv(run_dir / "case.smv")
    assert [m.mesh for m in metas] == [1, 2]
    assert metas[0].quantity == "TEMPERATURE" and metas[0].unit == "C"
    assert (metas[0].i1, metas[0].i2, metas[0].j1, metas[0].j2) == (0, 2, 1, 1)
    assert grids[2].x_m == (2.0, 3.0, 4.0) and grids[1].z_m == (0.0, 1.0, 2.0)


def test_load_centreline_stitches_meshes_in_x_and_trims_to_the_common_time(run_dir):
    sl = slices.load_centreline(run_dir, "TEMPERATURE")
    assert sl is not None and sl.unit == "C"
    assert list(sl.x_m) == [0.0, 1.0, 2.0, 3.0, 4.0]       # shared node at x=2 kept once
    assert list(sl.z_m) == [0.0, 1.0, 2.0]
    assert list(sl.t_s) == [0.0, 5.0]                     # mesh 1 has two frames; mesh 2 three
    assert sl.frames.shape == (2, 3, 5)
    assert sl.frames[0, 2, :].tolist() == [20.0, 21.0, 22.0, 23.0, 24.0]
    assert sl.frames[1, 0, 4] == pytest.approx(8.0)       # frame 2 is scaled by 2: (0*10+4)*2


def test_load_centreline_is_none_when_nothing_matches(run_dir, tmp_path):
    assert slices.load_centreline(run_dir, "SOOT DENSITY") is None
    assert slices.load_centreline(tmp_path / "empty", "TEMPERATURE") is None

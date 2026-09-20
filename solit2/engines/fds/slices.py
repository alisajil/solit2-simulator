"""Read FDS slice output (`.sf`) and the mesh geometry Smokeview lists (`.smv`).

FDS writes one slice file per (mesh, `&SLCF` line) as Fortran sequential
unformatted records: a 4-byte little-endian record length, the payload, the
same 4 bytes again. Three 30-character header records (quantity, short name,
unit), one record of six int32 node bounds (i1 i2 j1 j2 k1 k2), then for every
output time a one-float32 record (time) and one record of
(i2-i1+1)(j2-j1+1)(k2-k1+1) float32 in Fortran order (i fastest). FDS appends
while it runs, so the final record may be incomplete: readers stop there and
return the complete frames.

The `.smv` file is text. Per mesh: `GRID <name>` then `ibar jbar kbar ...`,
then `TRNX`/`TRNY`/`TRNZ` blocks (a count of extra lines to skip, then
`index coordinate` for every node). Each `&SLCF` appears as
`SLCF <mesh> # STRUCTURED & i1 i2 j1 j2 k1 k2 ! ...` followed by four indented
lines: file name, quantity, short name, unit.
"""
from __future__ import annotations

import struct
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np

_HEADER_RECORDS = 3
_MARKER = struct.Struct("<i")
_BOUNDS = struct.Struct("<6i")
_TIME = struct.Struct("<f")
_AXES = "xyz"


@dataclass(frozen=True)
class SliceMeta:
    mesh: int
    path: Path
    quantity: str
    short: str
    unit: str
    i1: int
    i2: int
    j1: int
    j2: int
    k1: int
    k2: int


@dataclass(frozen=True)
class MeshGrid:
    mesh: int
    x_m: tuple[float, ...]
    y_m: tuple[float, ...]
    z_m: tuple[float, ...]


@dataclass(frozen=True)
class Slice:
    quantity: str
    unit: str
    x_m: np.ndarray
    z_m: np.ndarray
    t_s: np.ndarray
    frames: np.ndarray  # [t, z, x]


def _records(data: bytes) -> Iterator[bytes]:
    """Yield complete Fortran records; stop at the first truncated one."""
    pos, n = 0, len(data)
    while pos + _MARKER.size <= n:
        (length,) = _MARKER.unpack_from(data, pos)
        end = pos + _MARKER.size + length + _MARKER.size
        if length < 0 or end > n:
            return
        yield data[pos + _MARKER.size:pos + _MARKER.size + length]
        pos = end


def read_sf(path: Path) -> tuple[tuple[str, str, str], tuple[int, ...], np.ndarray, np.ndarray]:
    recs = _records(Path(path).read_bytes())
    try:
        header = tuple(next(recs).decode("ascii", "replace").strip() for _ in range(_HEADER_RECORDS))
        bounds = _BOUNDS.unpack(next(recs))
    except (StopIteration, struct.error) as exc:
        raise ValueError(f"{path}: slice header is incomplete") from exc
    ni, nj, nk = (bounds[1] - bounds[0] + 1, bounds[3] - bounds[2] + 1, bounds[5] - bounds[4] + 1)
    times: list[float] = []
    frames: list[np.ndarray] = []
    for rec in recs:
        payload = next(recs, None)
        if len(rec) != _TIME.size or payload is None or len(payload) != 4 * ni * nj * nk:
            break
        times.append(_TIME.unpack(rec)[0])
        frames.append(np.frombuffer(payload, dtype="<f4").reshape(nk, nj, ni))
    stacked = np.stack(frames) if frames else np.empty((0, nk, nj, ni), dtype=np.float32)
    return header, bounds, np.asarray(times, dtype=np.float32), stacked


def _read_trn(lines: list[str], start: int, count: int) -> tuple[tuple[float, ...], int]:
    """A TRN* block: skip-count line, that many lines, then `count` node lines."""
    skip = int(lines[start + 1])
    first = start + 2 + skip
    coords = tuple(float(lines[k].split()[1]) for k in range(first, first + count))
    return coords, first + count


def read_smv(path: Path) -> tuple[list[SliceMeta], dict[int, MeshGrid]]:
    lines = Path(path).read_text().splitlines()
    metas: list[SliceMeta] = []
    dims: dict[int, tuple[int, int, int]] = {}
    axes: dict[int, dict[str, tuple[float, ...]]] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("GRID"):
            mesh = len(dims) + 1  # meshes are listed in order
            ibar, jbar, kbar = (int(v) for v in lines[i + 1].split()[:3])
            dims[mesh] = (ibar, jbar, kbar)
            i += 2
        elif line.startswith(("TRNX", "TRNY", "TRNZ")):
            mesh, axis = len(dims), line[3].lower()
            coords, i = _read_trn(lines, i, dims[mesh][_AXES.index(axis)] + 1)
            axes.setdefault(mesh, {})[axis] = coords
        elif line.startswith("SLCF"):
            head = line.split()
            b = [int(v) for v in head[head.index("&") + 1:head.index("&") + 7]]
            metas.append(SliceMeta(int(head[1]), Path(path).parent / lines[i + 1].strip(),
                                   lines[i + 2].strip(), lines[i + 3].strip(),
                                   lines[i + 4].strip(), *b))
            i += 5
        else:
            i += 1
    grids = {m: MeshGrid(m, a["x"], a["y"], a["z"]) for m, a in axes.items()}
    return metas, grids


def _part(meta: SliceMeta, grid: MeshGrid):
    header, _, t, frames = read_sf(meta.path)
    if len(t) == 0:
        return None
    x = np.asarray(grid.x_m[meta.i1:meta.i2 + 1])
    z = np.asarray(grid.z_m[meta.k1:meta.k2 + 1])
    return x, z, t, frames[:, :, 0, :], header[2]


def load_centreline(run_dir: Path, quantity: str) -> Slice | None:
    """Every constant-y slice of `quantity`, stitched along x at the common frame count."""
    smv = next(iter(sorted(Path(run_dir).glob("*.smv"))), None) if Path(run_dir).exists() else None
    if smv is None:
        return None
    metas, grids = read_smv(smv)
    wanted = [m for m in metas if m.quantity == quantity and m.j1 == m.j2 and m.path.exists()]
    parts = [p for p in (_part(m, grids[m.mesh]) for m in wanted) if p is not None]
    if not parts:
        return None
    parts.sort(key=lambda p: float(p[0][0]))
    n = min(len(p[2]) for p in parts)
    z = parts[0][1]
    xs, blocks = [parts[0][0]], [parts[0][3][:n]]
    for x, z_i, _, frames, _ in parts[1:]:
        if len(z_i) != len(z):
            raise ValueError("meshes on the centreline do not share a z grid")
        drop = 1 if np.isclose(x[0], xs[-1][-1]) else 0   # shared boundary node
        xs.append(x[drop:])
        blocks.append(frames[:n, :, drop:])
    return Slice(quantity, parts[0][4], np.concatenate(xs), z, parts[0][2][:n],
                 np.concatenate(blocks, axis=2))


DIFFERENCE_PREFIX = "Δ "


def difference(minuend: Slice, subtrahend: Slice, label: str) -> Slice:
    """`minuend - subtrahend`, frame by frame, on the minuend's clock.

    Each minuend frame is paired with the subtrahend frame nearest in time, and
    only frames the subtrahend actually reaches are kept: holding its last
    frame flat past its end would manufacture a difference nothing computed.
    The two runs must share a grid -- they do when they come from the same
    design's mist and free-burn decks, and nothing else is a valid pair.
    """
    if (minuend.x_m.shape != subtrahend.x_m.shape or minuend.z_m.shape != subtrahend.z_m.shape
            or not np.allclose(minuend.x_m, subtrahend.x_m)
            or not np.allclose(minuend.z_m, subtrahend.z_m)):
        raise ValueError("the two slices are on different grids and cannot be differenced")
    if minuend.quantity != subtrahend.quantity:
        raise ValueError(f"{minuend.quantity!r} minus {subtrahend.quantity!r} is not a difference")
    if len(subtrahend.t_s) == 0:
        raise ValueError("the subtrahend has no complete frame yet")
    keep = minuend.t_s <= subtrahend.t_s[-1] + 1e-6
    if not keep.any():
        raise ValueError("the subtrahend has not reached the minuend's first frame")
    t_s = minuend.t_s[keep]
    nearest = np.abs(subtrahend.t_s[None, :] - t_s[:, None]).argmin(axis=1)
    return Slice(f"{DIFFERENCE_PREFIX}{minuend.quantity} ({label})", minuend.unit,
                 minuend.x_m, minuend.z_m, t_s, minuend.frames[keep] - subtrahend.frames[nearest])

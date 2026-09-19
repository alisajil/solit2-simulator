"""Regenerate sample_devc.csv from the committed golden deck.

Run: uv run python tests/fixtures/fds/make_fixture.py
The values are deliberately simple -- ambient, then rising -- because this
fixture exists to prove parsing and assembly, not to be a realistic fire.
"""
import re
from pathlib import Path

HERE = Path(__file__).parent
AMBIENT_C = 33.0

UNITS = {"_TC": "C", "_HF": "kW/m2", "_VIS": "m", "_CO": "ppm",
         "_FED": "1", "_U": "m/s", "CEIL": "C", "TARGET_FLUX": "kW/m2"}
# (t=0, t=1, t=2) per quantity: ambient, then a developing fire
SERIES = {"C": (AMBIENT_C, 120.0, 260.0), "kW/m2": (0.0, 3.5, 9.0),
          "m": (30.0, 18.0, 7.0), "ppm": (0.0, 40.0, 150.0),
          "1": (0.0, 0.01, 0.04), "m/s": (4.5, 4.4, 4.2)}


def unit_of(device: str) -> str:
    for marker, unit in UNITS.items():
        if marker in device:
            return unit
    raise ValueError(f"no unit rule for device {device!r}")


def main() -> None:
    deck_text = (HERE / "og-dbr-rev0.fds").read_text()
    ids = [d for d in re.findall(r"&DEVC ID='([^']+)'", deck_text)
           if not d.startswith(("NOZ", "LHD"))]
    units = [unit_of(d) for d in ids]
    rows = [[SERIES[u][step] for u in units] for step in range(3)]
    lines = ["s," + ",".join(units), "Time," + ",".join(ids)]
    lines += [f"{float(step)}," + ",".join(f"{v:.3f}" for v in row)
              for step, row in enumerate(rows)]
    (HERE / "sample_devc.csv").write_text("\n".join(lines) + "\n")
    print(f"wrote {len(ids)} device columns")


if __name__ == "__main__":
    main()

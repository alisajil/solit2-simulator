"""Regenerate the golden decks and the sample FDS output that the reader tests parse.

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


def write_goldens() -> None:
    from solit2.engines.fds import deck
    from solit2.schema.design import Design
    for name, path in (("og-dbr-rev0", "designs/og-dbr-rev0.json"),
                       ("solit2-test-protocol", "examples/designs/solit2-test-protocol.json")):
        (HERE / f"{name}.fds").write_text(deck.generate(Design.load(path)))


def write_ctrl() -> None:
    """FDS's `<CHID>_ctrl.csv`: control status -1 until it fires, 1 after.

    Detection at the second sample and activation at the third, so the reader
    tests can see water arrive at a time FDS recorded rather than one the
    design's timetable assumed.
    """
    lines = ["s,status,status", "Time,DETECT,ACT", "0.0,-1,-1", "1.0,1,-1", "2.0,1,1"]
    (HERE / "sample_ctrl.csv").write_text("\n".join(lines) + "\n")


def main() -> None:
    write_goldens()
    write_ctrl()
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

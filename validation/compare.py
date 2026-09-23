"""Compare the engine against published full-scale fire tests.

Each anchor holds a design, the values measured in that test, and the tolerance
each value must be matched to. `check` produces a readable report; `residuals`
produces the normalised errors the calibration fit minimises.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from solit2.engines.reduced import envelope
from solit2.engines.reduced.criteria import (FLAME_CONTACT_FLUX_KWM2, IGNITION_EXPOSURE_S,
                                             STATIONS)
from solit2.schema.design import Design

ANCHOR_DIR = Path(__file__).resolve().parent / "anchors"


@dataclass(frozen=True)
class Anchor:
    id: str
    weight: float
    source: str
    design: Design
    measured: dict
    tolerances: dict


@dataclass(frozen=True)
class AnchorReport:
    anchor_id: str
    rows: list[tuple[str, float | bool, float | bool, str, bool]]

    @property
    def passed(self) -> bool:
        return all(row[4] for row in self.rows)


def _load_design(path: Path, raw_design: dict) -> Design:
    """Build a `Design` from an anchor's inline design dict.

    `Design.load` only reads from a path (it needs one to resolve presets
    relative to nothing in particular, but its signature is path-in), so the
    design block is written to a sibling file, loaded, then removed. The
    write/unlink is wrapped in try/finally so a bad anchor design (one that
    fails validation) can never leave a stray `*.design.json` file behind --
    such a file would itself match the `c*.json` glob `load_anchors` scans on
    its next call and be misread as an anchor record.
    """
    design_path = path.with_suffix(".design.json")
    design_path.write_text(json.dumps(raw_design))
    try:
        return Design.load(design_path)
    finally:
        design_path.unlink(missing_ok=True)


def load_anchors(ids: tuple[str, ...] | None = None) -> tuple[Anchor, ...]:
    out = []
    for path in sorted(ANCHOR_DIR.glob("c*.json")):
        raw = json.loads(path.read_text())
        if ids and raw["id"] not in ids:
            continue
        out.append(Anchor(raw["id"], raw["weight"], raw["source"],
                          _load_design(path, raw["design"]), raw["measured"], raw["tolerances"]))
    if not out:
        raise FileNotFoundError(f"no anchors matched {ids} in {ANCHOR_DIR}")
    return tuple(out)


def within(measured, modelled, tolerance: dict) -> bool:
    kind = tolerance["kind"]
    if kind == "exact":
        return bool(measured) == bool(modelled)
    if kind == "absolute":
        return abs(modelled - measured) <= tolerance["value"]
    if kind == "relative":
        return abs(modelled - measured) <= abs(measured) * tolerance["value"]
    if kind == "factor":
        if measured <= 0 or modelled <= 0:
            return abs(modelled - measured) < 1e-9
        return 1.0 / tolerance["value"] <= modelled / measured <= tolerance["value"]
    raise ValueError(f"unknown tolerance kind {kind!r}")


def _target_ignited(result) -> bool:
    """SOLIT2 Annex 7 section 7.2.1's outcome, rebuilt from the run's own peaks.

    `criteria._target_ignited` asks the same question of the same two thresholds,
    but it is a CRITERION, and the rule below is that no anchor may depend on one
    existing: an authority can replace the criteria list, and an anchor that read
    it would then compare against nothing. `target_peak_flux_kwm2` and
    `target_max_exposure_s` are maxima over the whole trace, and
    `any(flux_i >= F or exposure_i >= E)` is exactly `max(flux) >= F or
    max(exposure) >= E`, so this is the same predicate on data the run always
    records.
    """
    peaks = result.peaks
    return bool(peaks["target_peak_flux_kwm2"] >= FLAME_CONTACT_FLUX_KWM2
                or peaks["target_max_exposure_s"] >= IGNITION_EXPOSURE_S)


# Where the anchor tests looked for backlayering. Annex 2 judges it from one
# instrument in all three: "Temperatures in various heights at U15. No
# backlayering of smoke is observed" (Figures 11 and 20) and "A strong
# backlayering before the activation of the FFFS can be observed" (Figure 29).
BACKLAYERING_STATION = "U15"


def _backlayering_at_u15(result) -> bool:
    """Did smoke reach the U15 thermocouple tree, which is what the tests reported.

    The engine's own `events.backlayering.occurred` flags ANY upstream layer, a
    metre of it included. The tests could not see a metre: they saw the U15
    ladder or nothing. Comparing the two answered a question no test asked, and
    on c4 scored a 3 m layer that never left the mock-up as a miss. The engine
    already decides the ladder the same way -- `sim._sample_stations` holds a
    station at ambient unless `abs(x) <= backlayer_m` -- so this is that
    condition on the run's longest layer, not a new threshold.
    """
    reach = abs(STATIONS[BACKLAYERING_STATION])
    return bool(result.events["backlayering"]["max_length_m"] >= reach)


# How each comparable quantity is pulled out of a result. Every entry reads the
# trace or the peaks, never a criterion: the acceptance criteria are what an
# authority sets, not what a fire test measured, so an anchor must not depend on
# one existing (see solit2/engines/reduced/criteria.py).
EXTRACTORS = {
    "flow_lpm": lambda r: r.hydraulics["flow_lpm"],
    "peak_hrr_mw": lambda r: r.peaks["hrr_mw"],
    "peak_ceiling_temp_c": lambda r: r.peaks["ceiling_temp_c"],
    "u15_temp_c": lambda r: max(r.timeseries["u15_temp_c"]),
    "d15_temp_c": lambda r: max(r.timeseries["d15_temp_c"]),
    "d100_temp_c": lambda r: max(r.timeseries["d100_temp_c"]),
    "hf_d15_kwm2": lambda r: max(r.timeseries["hf_d15_kwm2"]),
    "backlayering": _backlayering_at_u15,
    "pools_extinguished": lambda r: r.events["pools_extinguished_at_s"] is not None,
    "target_ignited": _target_ignited,
}



def _modelled(result, quantity: str):
    """Pull one comparable quantity out of a result."""
    if quantity not in EXTRACTORS:
        raise KeyError(
            f"anchor quantity {quantity!r} has no extractor; known quantities are "
            f"{sorted(EXTRACTORS)}"
        )
    return EXTRACTORS[quantity](result)


def check(anchor: Anchor, engine: str = "reduced") -> AnchorReport:
    if engine != "reduced":
        raise ValueError(f"engine {engine!r} is not available in this plan; use 'reduced'")
    result = envelope.run(anchor.design)
    rows = []
    for quantity, measured in anchor.measured.items():
        tolerance = anchor.tolerances[quantity]
        modelled = _modelled(result, quantity)
        label = (tolerance["kind"] if tolerance["kind"] == "exact"
                 else f"{tolerance['kind']} {tolerance['value']}")
        rows.append((quantity, modelled, measured, label, within(measured, modelled, tolerance)))
    return AnchorReport(anchor.id, rows)


def residuals(anchors: tuple[Anchor, ...]) -> list[float]:
    """Weighted, normalised errors for the calibration fit."""
    out: list[float] = []
    for anchor in anchors:
        result = envelope.run(anchor.design)
        for quantity, measured in anchor.measured.items():
            modelled = _modelled(result, quantity)
            if isinstance(measured, bool):
                out.append(anchor.weight * (0.0 if bool(modelled) == measured else 1.0))
            else:
                scale = abs(measured) if abs(measured) > 1e-6 else 1.0
                out.append(anchor.weight * (modelled - measured) / scale)
    if not all(math.isfinite(r) for r in out):
        raise ValueError("a residual is not finite; the engine returned NaN or infinity")
    return out

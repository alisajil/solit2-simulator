"""Relative installed-cost index for a candidate design.

Quantities cover `tunnel.length_m` in each of the design's `tunnel.tubes`
bores. The index is normalised against a fixed reference installation so that
reference scores 1.00; only ratios between designs are meaningful, and the
absolute number carries no currency and no endorsement.

NOTE ON SCOPE: every quantity below is derived from the design being
evaluated, so it describes the tunnel the user actually described. The one
fixed element left is BASELINE_TOTAL, the constant the totals are divided by.
It sets the scale of the ratio and nothing else, so a cost index is comparable
between designs and is still NOT a statement about any real installation.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from solit2.engines.reduced.hydraulics import HydraulicsResult
from solit2.schema.design import Design

_WEIGHTS = json.loads((Path(__file__).resolve().parents[2] / "presets" / "cost_weights.json").read_text())
# The reference installation: its cost in the units above, and the total tube
# length that cost covered. The index is a cost PER METRE OF PROTECTED TUBE
# against this reference's cost per metre, which is what makes it scale-free.
#
# Indexing against BASELINE_TOTAL alone stopped working once quantities became
# the design's own: the reference is 8.5 km of tube, so a 600 m test gallery
# scored 0.095 and every design in it clipped the score's cost dimension to the
# same 1.0, leaving that 0.20 weight inert. Per metre, a dense design in a short
# tunnel and a sparse one in a long tunnel are compared on the thing that
# actually differs between them. Neither number decides any quantity of the
# design being evaluated. See the cost tests.
BASELINE_TOTAL = 128_535.82945588144
BASELINE_LENGTH_M = 8_500.0
BASELINE_PER_M = BASELINE_TOTAL / BASELINE_LENGTH_M


@dataclass(frozen=True)
class CostResult:
    zones: int
    heads: int
    section_valves: int
    ring_main_m: float
    zone_header_m: float
    row_pipe_m: float
    pumps: int
    tank_m3: float
    total: float
    index: float


def cost_index(design: Design, hyd: HydraulicsResult) -> CostResult:
    zone_len = design.zones.section_length_m
    tubes = design.tunnel.tubes
    # A tunnel shorter than half a zone still needs one zone per tube: round()
    # alone returns 0 there, and a design with no zones has no heads and no cost.
    zones = tubes * max(1, round(design.tunnel.length_m / zone_len))
    heads = zones * design.heads_per_zone
    rows = design.nozzles.mounting.rows
    total_length = design.tunnel.length_m * tubes

    ring_main_m = 2.0 * total_length          # one main each side of every tube
    zone_header_m = zones * zone_len / rows   # header feeds the gridded rows
    row_pipe_m = rows * total_length
    pumps = hyd.pumps_duty + hyd.pumps_standby

    total = (
        heads * _WEIGHTS["head"]
        + zones * _WEIGHTS["section_valve"]
        + ring_main_m * _WEIGHTS["ring_main_per_m"]
        + zone_header_m * _WEIGHTS["zone_header_per_m"]
        + row_pipe_m * _WEIGHTS["row_pipe_per_m"]
        + pumps * _WEIGHTS["pump_unit"]
        + hyd.tank_m3 * _WEIGHTS["tank_per_m3"]
    )
    index = (total / total_length) / BASELINE_PER_M
    return CostResult(zones, heads, zones, ring_main_m, zone_header_m, row_pipe_m,
                      pumps, hyd.tank_m3, total, index)

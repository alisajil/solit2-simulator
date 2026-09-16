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
# Cost of the reference installation in the units above: the denominator that
# turns a total into an index. Any design, in any tunnel, is indexed against
# this one number -- it sets the scale of the ratio and decides no quantity of
# the design being evaluated. See the cost tests.
BASELINE_TOTAL = 128_535.82945588144


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
    zones = tubes * round(design.tunnel.length_m / zone_len)
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
    return CostResult(zones, heads, zones, ring_main_m, zone_header_m, row_pipe_m,
                      pumps, hyd.tank_m3, total, total / BASELINE_TOTAL)

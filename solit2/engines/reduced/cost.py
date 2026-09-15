"""Relative installed-cost index for a candidate design.

Quantities cover both tubes. The index is normalised against a fixed reference
installation so that reference scores 1.00; only ratios between designs are
meaningful, and the absolute number carries no currency and no endorsement.

NOTE ON SCOPE: the reference installation's tube lengths and total below are
fixed constants inherited from the worked example this tool was first built
around. They are a normalisation baseline, not an assessment input, but they
are not derived from the design being evaluated either, so a cost index is
comparable between designs and is NOT a statement about any real installation.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from solit2.engines.reduced.hydraulics import HydraulicsResult
from solit2.schema.design import Design

_WEIGHTS = json.loads((Path(__file__).resolve().parents[2] / "presets" / "cost_weights.json").read_text())
# The reference installation's two tubes. A fixed normalisation baseline, not
# the geometry of the design under evaluation.
TUBE_LENGTHS_M = (4240.0, 4260.0)
# Cost of the reference installation in the units above; see the cost tests.
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
    zones = sum(round(length / zone_len) for length in TUBE_LENGTHS_M)
    heads = zones * design.heads_per_zone
    rows = design.nozzles.mounting.rows
    total_length = sum(TUBE_LENGTHS_M)

    ring_main_m = 2.0 * total_length          # one main each side of both tubes
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

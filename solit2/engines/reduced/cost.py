"""Relative installed-cost index for a candidate design.

Quantities cover both tubes. The index is normalised so the DBR Rev 0 baseline
scores 1.00; only ratios between designs are meaningful.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from solit2.engines.reduced.hydraulics import HydraulicsResult
from solit2.schema.design import Design

_WEIGHTS = json.loads((Path(__file__).resolve().parents[2] / "presets" / "cost_weights.json").read_text())
# Both tubes: LHS 4240 m and RHS 4260 m (HPWM-TECHNICAL SPEC_R2 section 3).
TUBE_LENGTHS_M = (4240.0, 4260.0)
# Cost of the DBR Rev 0 design in the units above; see test_baseline_index_is_one.
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

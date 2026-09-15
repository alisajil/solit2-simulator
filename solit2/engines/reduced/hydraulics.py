"""Flow, pipe friction, pump duty, power and tank volume.

Sizing follows the tender: the main is sized for the three simultaneous zones
plus 10 %, and the pump head is rated 10 % above the required discharge.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from solit2.engines.reduced.geometry import SectionGeometry
from solit2.schema.design import Design

WATER_DENSITY_KGM3 = 1000.0
WATER_VISCOSITY_PAS = 1.0e-3
BAR_PER_PA = 1.0e-5
# Wall thickness allowance from DN to bore for schedule-10S stainless pipe.
_DN_TO_BORE_M = {150.0: 0.1541, 65.0: 0.0687, 50.0: 0.0525, 40.0: 0.0409, 32.0: 0.0351}


def _bore_m(dn_mm: float) -> float:
    if dn_mm not in _DN_TO_BORE_M:
        raise KeyError(f"no bore for DN{dn_mm:g}; known sizes are {sorted(_DN_TO_BORE_M)}")
    return _DN_TO_BORE_M[dn_mm]


def _friction_factor(reynolds: float, relative_roughness: float) -> float:
    """Swamee-Jain explicit approximation to Colebrook-White."""
    if reynolds < 2300:
        return 64.0 / max(reynolds, 1.0)
    return 0.25 / math.log10(relative_roughness / 3.7 + 5.74 / reynolds**0.9) ** 2


def darcy_weisbach_bar(flow_m3s: float, diameter_m: float, length_m: float,
                       roughness_mm: float) -> float:
    if flow_m3s <= 0 or diameter_m <= 0 or length_m < 0:
        raise ValueError(f"non-physical input: flow={flow_m3s}, D={diameter_m}, L={length_m}")
    area = math.pi * diameter_m**2 / 4.0
    velocity = flow_m3s / area
    reynolds = WATER_DENSITY_KGM3 * velocity * diameter_m / WATER_VISCOSITY_PAS
    f = _friction_factor(reynolds, roughness_mm / 1000.0 / diameter_m)
    return f * (length_m / diameter_m) * WATER_DENSITY_KGM3 * velocity**2 / 2.0 * BAR_PER_PA


@dataclass(frozen=True)
class HydraulicsResult:
    active_heads: int
    flow_lpm: float
    flow_design_lpm: float
    ring_loss_bar: float
    zone_loss_bar: float
    required_pump_bar: float
    rated_pump_bar: float
    power_kw: float
    tank_m3: float
    pumps_duty: int
    pumps_standby: int
    density_mm_min: float
    density_l_m3_min: float


def size_system(design: Design, geom: SectionGeometry) -> HydraulicsResult:
    h = design.hydraulics
    flow_lpm = design.flow_lpm
    flow_design_lpm = flow_lpm * h.safety_factor
    flow_m3s = flow_design_lpm / 60_000.0

    # Looped cross-tube ring: flow reaches the far zone from two directions, so the
    # worst-path loss is a fraction of the equivalent single radial main.
    # ponytail: constant loop_factor - replace with a network solve if the DN200
    # option or the broken-ring case is studied.
    ring_loss = h.loop_factor * darcy_weisbach_bar(
        flow_m3s, _bore_m(h.main_dn_mm), design.tunnel.length_m, h.roughness_mm)

    # Zone header carries one zone; the gridded rows carry half each.
    zone_flow_m3s = flow_m3s / design.zones.sections_simultaneous
    zone_loss = (
        darcy_weisbach_bar(zone_flow_m3s, _bore_m(h.zone_header_dn_mm),
                           design.zones.section_length_m, h.roughness_mm)
        + darcy_weisbach_bar(zone_flow_m3s / 2.0, _bore_m(h.row_pipe_dn_mm),
                             design.zones.section_length_m, h.roughness_mm)
    )

    required = (design.nozzles.pressure_bar + ring_loss + zone_loss
                + h.static_head_bar + h.fittings_loss_bar)
    rated = required * h.safety_factor

    hydraulic_kw = flow_m3s * required / BAR_PER_PA / 1000.0
    power_kw = hydraulic_kw / h.pump_efficiency / h.motor_efficiency

    duty = math.ceil(flow_design_lpm * 60.0 / 1000.0 / h.pump_unit_m3h)
    tank_m3 = flow_design_lpm * design.zones.duration_min / 1000.0

    wetted_area = design.active_length_m * geom.road_width_m
    wetted_volume = design.active_length_m * geom.free_area_m2

    return HydraulicsResult(
        active_heads=design.active_heads,
        flow_lpm=flow_lpm,
        flow_design_lpm=flow_design_lpm,
        ring_loss_bar=ring_loss,
        zone_loss_bar=zone_loss,
        required_pump_bar=required,
        rated_pump_bar=rated,
        power_kw=power_kw,
        tank_m3=tank_m3,
        pumps_duty=duty,
        pumps_standby=1,
        density_mm_min=flow_lpm / wetted_area,
        density_l_m3_min=flow_lpm / wetted_volume,
    )

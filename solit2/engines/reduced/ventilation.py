"""Longitudinal ventilation: critical velocity, backlayering and fire throttling.

Correlations are Li, Lei & Ingason (2010) for the critical velocity and the
backlayering length. The height used is the tunnel crown height; using the
area-equivalent height instead lowers the critical velocity by about 5 %
(recorded in calibration.json under ventilation.critical_velocity_height).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from solit2.engines.reduced.geometry import SectionGeometry
from solit2.schema.presets import load_calibration

GRAVITY_MS2 = 9.81
AIR_DENSITY_KGM3 = 1.2
AIR_CP_KJKGK = 1.0
AMBIENT_T_K = 293.0
# Li, Lei & Ingason (2010): the dimensionless critical velocity saturates above Q* = 0.15.
Q_STAR_TRANSITION = 0.15
U_STAR_SATURATED = 0.43
U_STAR_COEFFICIENT = 0.81
BACKLAYER_COEFFICIENT = 18.5
MIN_EFFECTIVE_VELOCITY_MS = 0.1


def dimensionless_hrr(q_conv_kw: float, height_m: float) -> float:
    if height_m <= 0:
        raise ValueError(f"tunnel height must be positive, got {height_m}")
    denominator = (AIR_DENSITY_KGM3 * AIR_CP_KJKGK * AMBIENT_T_K
                   * math.sqrt(GRAVITY_MS2) * height_m**2.5)
    return q_conv_kw / denominator


def _u_star_critical(q_star: float) -> float:
    if q_star <= Q_STAR_TRANSITION:
        return U_STAR_COEFFICIENT * q_star ** (1.0 / 3.0)
    return U_STAR_SATURATED


def critical_velocity_ms(q_conv_kw: float, height_m: float) -> float:
    q_star = dimensionless_hrr(q_conv_kw, height_m)
    return _u_star_critical(q_star) * math.sqrt(GRAVITY_MS2 * height_m)


def backlayering_length_m(q_conv_kw: float, height_m: float, velocity_ms: float) -> float:
    if velocity_ms <= 0:
        raise ValueError(f"velocity must be positive, got {velocity_ms}")
    q_star = dimensionless_hrr(q_conv_kw, height_m)
    u_star = velocity_ms / math.sqrt(GRAVITY_MS2 * height_m)
    u_star_c = _u_star_critical(q_star)
    if u_star >= u_star_c:
        return 0.0
    return BACKLAYER_COEFFICIENT * height_m * math.log(u_star_c / u_star)


def throttled_velocity_ms(fan_velocity_ms: float, q_conv_kw: float, area_m2: float) -> float:
    """Buoyancy opposes the fans; the effective velocity at the fire falls."""
    if area_m2 <= 0:
        raise ValueError(f"free area must be positive, got {area_m2}")
    if fan_velocity_ms <= 0:
        return 0.0
    k = load_calibration()["ventilation"]["throttling_coefficient"]["value"]
    thermal = q_conv_kw / (AIR_DENSITY_KGM3 * AIR_CP_KJKGK * AMBIENT_T_K * area_m2 * fan_velocity_ms)
    return max(fan_velocity_ms * (1.0 - k * thermal), MIN_EFFECTIVE_VELOCITY_MS)


@dataclass(frozen=True)
class VentilationState:
    u_fan_ms: float
    u_eff_ms: float
    u_critical_ms: float
    backlayer_m: float


def evaluate(geom: SectionGeometry, fan_velocity_ms: float, q_conv_kw: float) -> VentilationState:
    u_eff = throttled_velocity_ms(fan_velocity_ms, q_conv_kw, geom.free_area_m2)
    h = geom.crown_height_m
    u_c = critical_velocity_ms(q_conv_kw, h) if q_conv_kw > 0 else 0.0
    backlayer = backlayering_length_m(q_conv_kw, h, u_eff) if q_conv_kw > 0 else 0.0
    return VentilationState(fan_velocity_ms, u_eff, u_c, backlayer)

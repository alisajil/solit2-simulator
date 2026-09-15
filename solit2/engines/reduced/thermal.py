"""Gas temperature and radiant heat flux along the tunnel.

Maximum ceiling excess temperature is Li & Ingason (2012), which splits into a
plume-controlled region I and a ventilation-controlled region II; the
longitudinal decay is the two-exponential form from Ingason, Li & Lonnermark
(2015). Breathing-height values come from the ceiling value through a Newman
stratification factor. Radiation to a gauge is a point source at the flame
centroid, attenuated by the mist and by the smoke.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from solit2.engines.reduced.fire import FireModel, convective_kw, radiative_fraction
from solit2.engines.reduced.geometry import SectionGeometry
from solit2.engines.reduced.state import FireState, MistEffect
from solit2.engines.reduced.ventilation import VentilationState
from solit2.schema.presets import load_calibration

GRAVITY_MS2 = 9.81
AIR_DENSITY_KGM3 = 1.2
AIR_CP_KJKGK = 1.0
AMBIENT_T_K = 293.0
# Li & Ingason (2012)
REGION_TRANSITION_V = 0.19
REGION_I_COEFFICIENT = 17.5
# Ingason, Li & Lonnermark (2015) two-term longitudinal decay
DECAY_A1, DECAY_B1 = 0.57, 0.13
DECAY_A2, DECAY_B2 = 0.43, 0.021
# Alpert ceiling jet
ALPERT_PLUME_COEFFICIENT = 16.9
ALPERT_JET_COEFFICIENT = 5.38
ALPERT_PLUME_RADIUS_RATIO = 0.18
# Newman stratification regimes
FROUDE_STRATIFIED = 0.9
FROUDE_MIXED = 10.0
STRATIFIED_FACTOR = 0.1
BREATHING_HEIGHT_M = 1.8
# Smoke extinction for the radiant path (mist attenuation is supplied separately)
SMOKE_EXTINCTION_PER_M = 0.004
# Resolution at which the ceiling is walked to measure how much of it is hot,
# for SOLIT2 Annex 7 section 7.2.4. One metre resolves a "small area" finely
# enough to judge it without costing a closed-form inversion of the two-term decay.
STRUCTURE_SCAN_STEP_M = 1.0


def equivalent_radius_m(length_m: float, width_m: float) -> float:
    if length_m <= 0 or width_m <= 0:
        raise ValueError(f"fire footprint must be positive, got {length_m} x {width_m}")
    return math.sqrt(length_m * width_m / math.pi)


def _plume_velocity_scale_ms(q_conv_kw: float, b_fo_m: float) -> float:
    denominator = b_fo_m * AIR_DENSITY_KGM3 * AIR_CP_KJKGK * AMBIENT_T_K
    return (GRAVITY_MS2 * q_conv_kw / denominator) ** (1.0 / 3.0)


def max_ceiling_excess_k(hrr_kw: float, q_conv_kw: float, u_ms: float,
                         b_fo_m: float, h_ef_m: float) -> float:
    if h_ef_m <= 0:
        raise ValueError(
            f"effective height {h_ef_m} m is not positive: the fuel reaches the ceiling"
        )
    if hrr_kw <= 0:
        return 0.0
    cap = load_calibration()["thermal"]["ceiling_temp_cap_k"]["value"]
    w_star = _plume_velocity_scale_ms(q_conv_kw, b_fo_m)
    v_prime = u_ms / w_star if w_star > 0 else math.inf
    if v_prime <= REGION_TRANSITION_V:
        excess = REGION_I_COEFFICIENT * hrr_kw ** (2.0 / 3.0) / h_ef_m ** (5.0 / 3.0)
    else:
        excess = hrr_kw / (u_ms * b_fo_m ** (1.0 / 3.0) * h_ef_m ** (5.0 / 3.0))
    return min(excess, cap)


def longitudinal_decay(x_m: float, height_m: float) -> float:
    """Fraction of the maximum ceiling excess remaining `x_m` downstream."""
    ratio = abs(x_m) / height_m
    return DECAY_A1 * math.exp(-DECAY_B1 * ratio) + DECAY_A2 * math.exp(-DECAY_B2 * ratio)


def stratification_factor(u_ms: float, height_m: float, ceiling_excess_k: float) -> float:
    """Newman regimes: how much of the ceiling excess reaches breathing height."""
    if ceiling_excess_k <= 0:
        return 0.0
    froude = u_ms**2 / (GRAVITY_MS2 * height_m * ceiling_excess_k / AMBIENT_T_K)
    if froude < FROUDE_STRATIFIED:
        return STRATIFIED_FACTOR
    if froude >= FROUDE_MIXED:
        return 1.0
    span = (froude - FROUDE_STRATIFIED) / (FROUDE_MIXED - FROUDE_STRATIFIED)
    return STRATIFIED_FACTOR + span * (1.0 - STRATIFIED_FACTOR)


def alpert_ceiling_excess_k(hrr_kw: float, radius_m: float, height_m: float) -> float:
    if hrr_kw <= 0:
        return 0.0
    if radius_m / height_m <= ALPERT_PLUME_RADIUS_RATIO:
        return ALPERT_PLUME_COEFFICIENT * hrr_kw ** (2.0 / 3.0) / height_m ** (5.0 / 3.0)
    return ALPERT_JET_COEFFICIENT * (hrr_kw / radius_m) ** (2.0 / 3.0) / height_m


def heskestad_flame_length_m(hrr_kw: float, diameter_m: float) -> float:
    return max(0.235 * hrr_kw**0.4 - 1.02 * diameter_m, 0.0)


def point_source_flux_kwm2(hrr_kw: float, radiative_fraction_: float,
                           distance_m: float, transmissivity: float) -> float:
    if distance_m <= 0:
        raise ValueError(f"distance to the gauge must be positive, got {distance_m}")
    return radiative_fraction_ * hrr_kw * transmissivity / (4.0 * math.pi * distance_m**2)


@dataclass(frozen=True)
class ThermalField:
    ceiling_excess_k: float
    strat_factor: float
    ambient_c: float
    height_m: float
    hrr_kw: float
    radiative_fraction: float
    flame_centroid_z_m: float
    flame_tip_x_m: float

    def ceiling_temp_c(self, x_m: float) -> float:
        return self.ambient_c + self.ceiling_excess_k * longitudinal_decay(x_m, self.height_m)

    def gas_temp_c(self, x_m: float, height_m: float) -> float:
        """Breathing-height gas temperature; the ceiling value scaled by stratification."""
        excess = self.ceiling_excess_k * longitudinal_decay(x_m, self.height_m)
        # strat_factor is defined AT breathing height (Newman), so anchor the blend there
        # rather than at the floor: exactly strat_factor at BREATHING_HEIGHT_M, rising
        # linearly to 1.0 at the crown, flat at strat_factor below breathing height. A
        # floor-anchored blend dilutes strat_factor with a height-ratio term and hands back
        # far more heat at breathing height than the stratification factor says should arrive.
        fraction = self.strat_factor + (1.0 - self.strat_factor) * max(
            0.0, (height_m - BREATHING_HEIGHT_M) / (self.height_m - BREATHING_HEIGHT_M)
        )
        return self.ambient_c + excess * min(fraction, 1.0)

    def radiant_flux_kwm2(self, x_m: float, height_m: float, tau_mist: float) -> float:
        dx = abs(x_m)
        dz = self.flame_centroid_z_m - height_m
        distance = max(math.hypot(dx, dz), 0.5)
        tau_smoke = math.exp(-SMOKE_EXTINCTION_PER_M * dx)
        return point_source_flux_kwm2(self.hrr_kw, self.radiative_fraction,
                                      distance, tau_mist * tau_smoke)


def exposure_length_m(thermal_field: ThermalField, threshold_c: float,
                      x_min_m: float, x_max_m: float,
                      step_m: float = STRUCTURE_SCAN_STEP_M) -> float:
    """Length of tunnel whose ceiling temperature exceeds `threshold_c`.

    SOLIT2 Annex 7 section 7.2.4 sets "the minimum criterion [...] that high
    temperature exposure areas will be limited to a small area", so what matters
    is how much tunnel got hot, not how hot the hottest point got. The ceiling
    is walked between the outermost station positions at `step_m` resolution.
    """
    if step_m <= 0:
        raise ValueError(f"the ceiling scan step must be positive, got {step_m}")
    # The longitudinal decay falls monotonically with distance from the fire, so
    # if the fire's own station is below the threshold nothing downstream of it
    # can be above it. This short-circuit skips the scan for every cool step.
    if thermal_field.ceiling_temp_c(0.0) <= threshold_c:
        return 0.0
    samples = int((x_max_m - x_min_m) / step_m) + 1
    hot = sum(1 for i in range(samples)
              if thermal_field.ceiling_temp_c(x_min_m + i * step_m) > threshold_c)
    return hot * step_m


def field(geom: SectionGeometry, fire_model: FireModel, fire_state: FireState,
          vent_state: VentilationState, mist: MistEffect, fire_top_m: float,
          fire_length_m: float, fire_width_m: float, ambient_c: float) -> ThermalField:
    hrr_kw = fire_state.hrr_mw * 1000.0
    q_conv = convective_kw(fire_model, fire_state.hrr_mw)
    b_fo = equivalent_radius_m(fire_length_m, fire_width_m)
    h_ef = geom.crown_height_m - fire_top_m
    excess = max_ceiling_excess_k(hrr_kw, q_conv, vent_state.u_eff_ms, b_fo, h_ef)
    # evaporating mist removes part of the convective heat before it reaches the ceiling
    excess *= 1.0 - mist.chi_cool
    strat = stratification_factor(vent_state.u_eff_ms, geom.crown_height_m, excess)
    diameter = 2.0 * b_fo
    flame = heskestad_flame_length_m(hrr_kw, diameter)
    centroid = fire_top_m + 0.5 * min(flame, h_ef)
    c_f = load_calibration()["thermal"]["flame_length_coefficient"]["value"]
    tip = c_f * max(flame - h_ef, 0.0)  # flame that cannot rise is deflected downstream
    return ThermalField(ceiling_excess_k=excess, strat_factor=strat, ambient_c=ambient_c,
                        height_m=geom.crown_height_m, hrr_kw=hrr_kw,
                        radiative_fraction=radiative_fraction(fire_model),
                        flame_centroid_z_m=centroid, flame_tip_x_m=tip)

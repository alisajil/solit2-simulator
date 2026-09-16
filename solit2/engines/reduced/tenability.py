"""Tenability: what the smoke does to a person at breathing height.

Species come from published yields and the fire's mass loss rate, diluted by the
ventilation flow and reduced by stratification. The fractional effective dose
follows ISO 13571 (toxic and thermal), and visibility follows Jin's relation for
light-emitting signs.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from solit2.engines.reduced.fire import FireModel, mass_loss_rate_kgs

# Yields, g per g of fuel burnt: well-ventilated wood and diesel.
YIELDS = {
    "A": {"co": 0.005, "co2": 1.30, "soot": 0.015},
    "B": {"co": 0.010, "co2": 3.00, "soot": 0.060},
}
AIR_DENSITY_KGM3 = 1.2
AMBIENT_O2_PCT = 20.9
# Water of combustion, expressed per unit of CO2 rather than per unit of fuel so
# that it inherits the same combustion completeness as the measured CO2 yields
# above instead of being a second, independent number. The ratio is the fuel's
# own formula: cellulose C6H10O5 burns to 6 CO2 + 5 H2O, diesel taken as C12H23
# burns to 12 CO2 + 11.5 H2O.
WATER_PER_CO2_MASS = {
    "A": (5 * 18.02) / (6 * 44.01),
    "B": (11.5 * 18.02) / (12 * 44.01),
}
# Oxygen consumed per unit of heat released (Huggett), and the energy per kg of O2.
HUGGETT_KJ_PER_KG_O2 = 13_100.0
MOLAR_MASS_AIR = 28.97
MOLAR_MASS_CO = 28.01
MOLAR_MASS_CO2 = 44.01
# ISO 13571 fractional effective dose: every coefficient, exponent and threshold
# below is taken from that standard (asphyxiant CO dose with the CO2
# hyperventilation factor; thermal dose as convected heat plus radiant heat).
FED_CO_COEFFICIENT = 2.764e-5
FED_CO_EXPONENT = 1.036
FED_CO2_HYPERVENTILATION_DIVISOR = 5.0
FED_HEAT_CONVECTIVE_COEFFICIENT = 5.0e7
FED_HEAT_CONVECTIVE_EXPONENT = -3.4
FED_HEAT_CONVECTIVE_THRESHOLD_C = 30.0
FED_HEAT_RADIANT_COEFFICIENT = 6.9
FED_HEAT_RADIANT_EXPONENT = -1.56
FED_HEAT_FLUX_THRESHOLD_KWM2 = 2.5
# Jin: light-emitting signs.
JIN_LIGHT_EMITTING = 8.0
SOOT_EXTINCTION_M2_PER_G = 8.7
MAX_REPORTED_VISIBILITY_M = 1000.0
# Psychrometry for the Annex 7 Table 5 relative-humidity probe at U45 and D45.
# Saturation vapour pressure over water is the Magnus form with the Alduchov &
# Eskridge (1996) coefficients, within 0.4 % over 0-100 C. Above 100 C it is an
# extrapolation, which costs nothing here: any humidity it returns there is far
# below saturation anyway.
ATMOSPHERIC_PRESSURE_PA = 101_325.0
MAGNUS_A_PA = 610.94
MAGNUS_B = 17.625
MAGNUS_C_C = 243.04
MOLAR_MASS_WATER = 18.02
# kg of water vapour per kg of dry air at equal partial pressures.
WATER_AIR_MOLAR_RATIO = MOLAR_MASS_WATER / MOLAR_MASS_AIR
MAX_REPORTED_HUMIDITY_PCT = 100.0


@dataclass(frozen=True)
class Species:
    co_ppm: float
    co2_pct: float
    soot_gm3: float
    o2_pct: float
    # kg of water vapour of combustion per kg of air, the quantity relative
    # humidity is built from. A ratio rather than a concentration because it is
    # unchanged by the thermal expansion this one-dimensional model does not
    # resolve, where a per-volume figure would not be.
    h2o_ratio: float = 0.0


def species_at(fire_model: FireModel, hrr_mw: float, air_volumetric_m3s: float,
               strat_factor: float) -> Species:
    """Concentrations at breathing height in the flow passing a downstream station."""
    if air_volumetric_m3s <= 0:
        raise ValueError(f"ventilation flow must be positive, got {air_volumetric_m3s} m3/s")
    if hrr_mw <= 0:
        return Species(0.0, 0.0, 0.0, AMBIENT_O2_PCT)

    yields = YIELDS[fire_model.fire_class]
    mdot_fuel = mass_loss_rate_kgs(fire_model, hrr_mw)
    mass_flow_air = air_volumetric_m3s * AIR_DENSITY_KGM3

    co_mass_fraction = strat_factor * yields["co"] * mdot_fuel / mass_flow_air
    co2_mass_fraction = strat_factor * yields["co2"] * mdot_fuel / mass_flow_air
    soot_gm3 = strat_factor * yields["soot"] * mdot_fuel * 1000.0 / air_volumetric_m3s

    co_ppm = co_mass_fraction * (MOLAR_MASS_AIR / MOLAR_MASS_CO) * 1e6
    co2_pct = co2_mass_fraction * (MOLAR_MASS_AIR / MOLAR_MASS_CO2) * 100.0

    o2_consumed_kgs = hrr_mw * 1000.0 / HUGGETT_KJ_PER_KG_O2
    o2_depletion_pct = strat_factor * o2_consumed_kgs / mass_flow_air * 100.0
    return Species(co_ppm, co2_pct, soot_gm3,
                   max(AMBIENT_O2_PCT - o2_depletion_pct, 0.0),
                   h2o_ratio=co2_mass_fraction * WATER_PER_CO2_MASS[fire_model.fire_class])


def fed_tox_increment(species: Species, dt_s: float) -> float:
    """ISO 13571 asphyxiant dose, with the CO2 hyperventilation multiplier."""
    if species.co_ppm <= 0:
        return 0.0
    hyperventilation = math.exp(species.co2_pct / FED_CO2_HYPERVENTILATION_DIVISOR)
    return (species.co_ppm**FED_CO_EXPONENT * FED_CO_COEFFICIENT
            * hyperventilation * dt_s / 60.0)


def fed_heat_increment(temp_c: float, flux_kwm2: float, dt_s: float) -> float:
    """ISO 13571 thermal dose: convected heat plus radiant heat."""
    minutes = dt_s / 60.0
    dose = 0.0
    if temp_c > FED_HEAT_CONVECTIVE_THRESHOLD_C:
        dose += minutes / (FED_HEAT_CONVECTIVE_COEFFICIENT
                           * temp_c**FED_HEAT_CONVECTIVE_EXPONENT)
    if flux_kwm2 >= FED_HEAT_FLUX_THRESHOLD_KWM2:
        dose += minutes / (FED_HEAT_RADIANT_COEFFICIENT
                           * flux_kwm2**FED_HEAT_RADIANT_EXPONENT)
    return dose


def saturation_vapour_pressure_pa(temp_c: float) -> float:
    """Magnus form, over water."""
    return MAGNUS_A_PA * math.exp(MAGNUS_B * temp_c / (MAGNUS_C_C + temp_c))


def humidity_ratio(vapour_pressure_pa: float) -> float:
    """kg of water vapour per kg of dry air at a given partial pressure."""
    return (WATER_AIR_MOLAR_RATIO * vapour_pressure_pa
            / (ATMOSPHERIC_PRESSURE_PA - vapour_pressure_pa))


def relative_humidity_pct(gas_temp_c: float, ambient_temp_c: float,
                          ambient_rh_pct: float, added_water_ratio: float) -> float:
    """RH at a station: the tunnel's own air plus the water the fire and the
    mist put into it, read against saturation at the station's gas temperature.

    Definitional, not correlated: relative humidity IS the vapour pressure over
    the saturation pressure. The only fitted piece is the Magnus saturation
    curve. `added_water_ratio` is kg of water vapour added per kg of air, which
    is why the ambient state is converted to a ratio before the two are summed.

    Capped at saturation, because water past that point leaves the vapour phase
    as fog rather than being reported as a humidity above 100 %.
    """
    ambient_vapour_pa = (ambient_rh_pct / 100.0
                         * saturation_vapour_pressure_pa(ambient_temp_c))
    ratio = humidity_ratio(ambient_vapour_pa) + max(added_water_ratio, 0.0)
    vapour_pa = ATMOSPHERIC_PRESSURE_PA * ratio / (WATER_AIR_MOLAR_RATIO + ratio)
    saturated_pa = saturation_vapour_pressure_pa(gas_temp_c)
    return min(100.0 * vapour_pa / saturated_pa, MAX_REPORTED_HUMIDITY_PCT)


def visibility_m(soot_gm3: float, kappa_mist_per_m: float) -> float:
    extinction = SOOT_EXTINCTION_M2_PER_G * soot_gm3 + kappa_mist_per_m
    if extinction <= 0:
        return MAX_REPORTED_VISIBILITY_M
    return min(JIN_LIGHT_EMITTING / extinction, MAX_REPORTED_VISIBILITY_M)

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
# Oxygen consumed per unit of heat released (Huggett), and the energy per kg of O2.
HUGGETT_KJ_PER_KG_O2 = 13_100.0
MOLAR_MASS_AIR = 28.97
MOLAR_MASS_CO = 28.01
MOLAR_MASS_CO2 = 44.01
# ISO 13571
FED_CO_COEFFICIENT = 2.764e-5
FED_CO_EXPONENT = 1.036
FED_HEAT_FLUX_THRESHOLD_KWM2 = 2.5
# Jin: light-emitting signs.
JIN_LIGHT_EMITTING = 8.0
SOOT_EXTINCTION_M2_PER_G = 8.7
MAX_REPORTED_VISIBILITY_M = 1000.0


@dataclass(frozen=True)
class Species:
    co_ppm: float
    co2_pct: float
    soot_gm3: float
    o2_pct: float


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
    return Species(co_ppm, co2_pct, soot_gm3, max(AMBIENT_O2_PCT - o2_depletion_pct, 0.0))


def fed_tox_increment(species: Species, dt_s: float) -> float:
    """ISO 13571 asphyxiant dose, with the CO2 hyperventilation multiplier."""
    if species.co_ppm <= 0:
        return 0.0
    hyperventilation = math.exp(species.co2_pct / 5.0)
    return (species.co_ppm**FED_CO_EXPONENT * FED_CO_COEFFICIENT
            * hyperventilation * dt_s / 60.0)


def fed_heat_increment(temp_c: float, flux_kwm2: float, dt_s: float) -> float:
    """ISO 13571 thermal dose: convected heat plus radiant heat."""
    minutes = dt_s / 60.0
    dose = 0.0
    if temp_c > 30.0:
        dose += minutes / (5.0e7 * temp_c**-3.4)
    if flux_kwm2 >= FED_HEAT_FLUX_THRESHOLD_KWM2:
        dose += minutes / (1.33 * flux_kwm2**-1.33)
    return dose


def visibility_m(soot_gm3: float, kappa_mist_per_m: float) -> float:
    extinction = SOOT_EXTINCTION_M2_PER_G * soot_gm3 + kappa_mist_per_m
    if extinction <= 0:
        return MAX_REPORTED_VISIBILITY_M
    return min(JIN_LIGHT_EMITTING / extinction, MAX_REPORTED_VISIBILITY_M)

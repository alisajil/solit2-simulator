"""Heat release rate for Class A (solid, pallet/HGV) and Class B (diesel pool) fires.

Class A follows a t-squared growth to the design fire, burns at that level until
most of the fuel energy is gone, then decays linearly. The mist reduces the
burning rate through a first-order response.

Class B follows Babrauskas' pool-fire law per pool, with a ventilation factor for
the tunnel wind. The mist first reduces the burning rate, then extinguishes the
pools one at a time once the water flux on the fuel is high enough for long
enough, which is the behaviour reported in SOLIT2 Annex 2.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from solit2.engines.reduced.state import FireState, MistEffect
from solit2.schema.design import Design
from solit2.schema.presets import load_calibration

WOOD_HEAT_OF_COMBUSTION_MJKG = 17.5
DIESEL_HEAT_OF_COMBUSTION_MJKG = 44.8
COMBUSTION_EFFICIENCY = 0.80
RADIATIVE_FRACTION_CLASS_A = 0.35
RADIATIVE_FRACTION_CLASS_B = 0.30
# Babrauskas diesel: infinite-diameter mass burning rate and extinction coefficient.
DIESEL_MDOT_INF_KGM2S = 0.035
DIESEL_KBETA_PER_M = 1.7


def _cal(section: str, key: str):
    return load_calibration()[section][key]["value"]


@dataclass(frozen=True)
class FireModel:
    fire_class: str
    alpha_kw_s2: float
    incubation_s: float
    design_hrr_kw: float
    total_energy_mj: float
    decay_energy_fraction: float
    tau_suppression_s: float
    pool_count: int
    pool_area_m2: float
    pool_hrr_each_kw: float
    pool_ramp_s: float
    pool_reduction: float
    pool_extinction_flux_mm_min: float
    pool_extinction_time_s: float


def build_model(design: Design) -> FireModel:
    f = design.fire
    tau = _cal("fire", "suppression_response_s")
    if f.covered:
        tau *= _cal("fire", "cover_shielding_factor")

    if f.fire_class == "A":
        if f.pallets is None:
            raise ValueError("a Class A fire needs a pallet count to bound its energy")
        energy = f.pallets * f.energy_mj_per_pallet
        return FireModel(
            fire_class="A", alpha_kw_s2=f.alpha, incubation_s=f.incubation_s,
            design_hrr_kw=f.design_hrr_mw * 1000.0, total_energy_mj=energy,
            decay_energy_fraction=_cal("fire", "decay_energy_fraction"),
            tau_suppression_s=tau,
            pool_count=0, pool_area_m2=0.0, pool_hrr_each_kw=0.0, pool_ramp_s=0.0,
            pool_reduction=0.0, pool_extinction_flux_mm_min=0.0, pool_extinction_time_s=0.0,
        )

    if f.pools is None:
        raise ValueError("a Class B fire needs a `pools` block")
    area = f.pools.length_m * f.pools.width_m
    d_eff = math.sqrt(4.0 * area / math.pi)
    mdot = DIESEL_MDOT_INF_KGM2S * (1.0 - math.exp(-DIESEL_KBETA_PER_M * d_eff))
    each_kw = (_cal("fire", "pool_ventilation_factor") * mdot * area
               * DIESEL_HEAT_OF_COMBUSTION_MJKG * 1000.0)
    return FireModel(
        fire_class="B", alpha_kw_s2=f.alpha, incubation_s=f.incubation_s,
        design_hrr_kw=f.design_hrr_mw * 1000.0, total_energy_mj=math.inf,
        decay_energy_fraction=1.0, tau_suppression_s=tau,
        pool_count=f.pools.count, pool_area_m2=area, pool_hrr_each_kw=each_kw,
        pool_ramp_s=_cal("fire", "pool_ramp_s"),
        pool_reduction=_cal("fire", "pool_burning_rate_reduction"),
        pool_extinction_flux_mm_min=_cal("fire", "pool_extinction_flux_mm_min"),
        pool_extinction_time_s=_cal("fire", "pool_extinction_time_s"),
    )


def initial_state(model: FireModel) -> FireState:
    return FireState(t_s=0.0, hrr_mw=0.0, hrr_free_mw=0.0, energy_released_mj=0.0,
                     suppression=1.0, pools_remaining=model.pool_count, wet_time_s=0.0)


def _free_burn_class_a_kw(model: FireModel, state: FireState, t_s: float) -> float:
    grown = model.alpha_kw_s2 * max(t_s - model.incubation_s, 0.0) ** 2
    plateau = min(grown, model.design_hrr_kw)
    burnt = model.decay_energy_fraction * model.total_energy_mj
    if state.energy_released_mj <= burnt:
        return plateau
    remaining = model.total_energy_mj - state.energy_released_mj
    decay_span = (1.0 - model.decay_energy_fraction) * model.total_energy_mj
    return plateau * max(remaining / decay_span, 0.0)


def _free_burn_class_b_kw(model: FireModel, state: FireState, t_s: float) -> float:
    ramp = min(t_s / model.pool_ramp_s, 1.0) if model.pool_ramp_s > 0 else 1.0
    return state.pools_remaining * model.pool_hrr_each_kw * ramp


def step(model: FireModel, state: FireState, dt_s: float, mist: MistEffect) -> FireState:
    if dt_s <= 0:
        raise ValueError(f"dt_s must be positive, got {dt_s}")
    t = state.t_s + dt_s

    if model.fire_class == "A":
        free_kw = _free_burn_class_a_kw(model, state, t)
        # first-order approach to the suppressed level while the mist is on the fuel
        target = 1.0 - mist.eta
        tau = model.tau_suppression_s
        decayed = state.suppression + (target - state.suppression) * (1.0 - math.exp(-dt_s / tau))
        suppression = decayed if mist.eta > 0 else 1.0
        hrr_kw = free_kw * suppression
        pools, wet = state.pools_remaining, state.wet_time_s
    else:
        free_kw = _free_burn_class_b_kw(model, state, t)
        wetting = mist.w_fuel_mm_min * mist.f_cov >= model.pool_extinction_flux_mm_min
        wet = state.wet_time_s + dt_s if wetting else 0.0
        pools = state.pools_remaining
        if wet >= model.pool_extinction_time_s and pools > 0:
            pools -= 1
            wet = 0.0
        suppression = 1.0 - model.pool_reduction if mist.w_fuel_mm_min > 0 else 1.0
        hrr_kw = free_kw * suppression

    if hrr_kw < 0:
        raise ValueError(f"negative heat release {hrr_kw} kW at t={t} s")
    energy = state.energy_released_mj + hrr_kw * dt_s / 1000.0
    return FireState(t_s=t, hrr_mw=hrr_kw / 1000.0, hrr_free_mw=free_kw / 1000.0,
                     energy_released_mj=energy, suppression=suppression,
                     pools_remaining=pools, wet_time_s=wet)


def radiative_fraction(model: FireModel) -> float:
    return RADIATIVE_FRACTION_CLASS_A if model.fire_class == "A" else RADIATIVE_FRACTION_CLASS_B


def convective_kw(model: FireModel, hrr_mw: float) -> float:
    return hrr_mw * 1000.0 * (1.0 - radiative_fraction(model))


def mass_loss_rate_kgs(model: FireModel, hrr_mw: float) -> float:
    heat = (WOOD_HEAT_OF_COMBUSTION_MJKG if model.fire_class == "A"
            else DIESEL_HEAT_OF_COMBUSTION_MJKG)
    return hrr_mw / (COMBUSTION_EFFICIENCY * heat)

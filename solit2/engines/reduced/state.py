"""State objects shared between the engine modules.

Keeping these here avoids an import cycle: `fire` needs the mist's effect and
`mist` needs the fire's size, so neither may import the other.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MistEffect:
    """What the mist is doing to the fire at one instant."""
    eta: float            # suppression efficiency applied to the Class A burning rate, 0..1
    # effective application on the fuel: top-face water plus flank-band water at
    # its reduced efficiency, over the top-face area
    w_fuel_mm_min: float
    f_cov: float          # fraction of the fuel's interception envelope any spray reaches
    chi_cool: float       # fraction of the convective heat release removed by evaporation
    tau_mist: float       # radiant transmissivity through the mist curtain, 0..1

    @classmethod
    def none(cls) -> "MistEffect":
        return cls(eta=0.0, w_fuel_mm_min=0.0, f_cov=0.0, chi_cool=0.0, tau_mist=1.0)


@dataclass(frozen=True)
class FireState:
    t_s: float
    hrr_mw: float
    hrr_free_mw: float
    energy_released_mj: float
    suppression: float
    pools_remaining: int
    wet_time_s: float


@dataclass(frozen=True)
class StationSample:
    temp_c: float
    flux_kwm2: float
    visibility_m: float
    fed_tox: float      # cumulative to this instant
    fed_heat: float     # cumulative to this instant
    # SOLIT2 Annex 7 section 7.2.2 names CO and CO2 as life-safety quantities in
    # their own right, so the concentration is carried per station rather than
    # only reaching the run through the FED dose it contributes to.
    co_ppm: float = 0.0


@dataclass(frozen=True)
class StepRecord:
    t_s: float
    hrr_mw: float
    hrr_free_mw: float
    ceiling_temp_c: float
    lining_temp_c: float
    pipe_temp_c: float
    target_flux_kwm2: float
    u_eff_ms: float
    u_critical_ms: float
    backlayer_m: float
    water_lpm: float
    pools_remaining: int
    mist: MistEffect
    stations: dict[str, StationSample]
    # How long the target has been continuously above the piloted-ignition flux.
    # Annex 7 section 7.2.1 is a sustained-exposure rule, so this resets to zero
    # the moment the flux drops back below the threshold.
    target_exposure_s: float = 0.0
    # Annex 7 section 7.2.4 asks for the hot AREA, not the hottest point: the
    # length of tunnel whose ceiling exceeds the AHJ reporting threshold.
    structure_exposure_length_m: float = 0.0


@dataclass(frozen=True)
class RunTrace:
    steps: tuple[StepRecord, ...]
    events: dict
    section: str
    velocity_ms: float

    def after(self, t_s: float) -> tuple[StepRecord, ...]:
        return tuple(s for s in self.steps if s.t_s >= t_s)

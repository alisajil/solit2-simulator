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
    w_fuel_mm_min: float  # water flux actually landing on the fuel and its 1 m halo
    f_cov: float          # fraction of that halo reached by at least one spray footprint
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

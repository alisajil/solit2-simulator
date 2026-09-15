"""Single-droplet flight from a nozzle to the fuel plane.

This is what separates the two spray modes: a fine droplet loses its launch
momentum within centimetres and is then carried by the tunnel airflow, while a
coarse droplet keeps enough momentum to cross the plume. The model tracks one
representative droplet per mode in the vertical plane, with Schiller-Naumann
drag and d-squared-law evaporation driven by the local gas temperature rise.

`launch_angle_deg` is measured from vertical: 0 degrees is straight down. Tilting
off vertical therefore both cuts the downward velocity component and adds a
downstream one, so it lengthens the drift rather than shortening it.

ponytail: one representative droplet per mode, two-dimensional - replace with a
size distribution if the FDS tier shows the tail of the spectrum matters.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from solit2.schema.presets import load_calibration

GRAVITY_MS2 = 9.81
AIR_DENSITY_KGM3 = 1.2
AIR_VISCOSITY_PAS = 1.8e-5
WATER_DENSITY_KGM3 = 1000.0
STOKES_REYNOLDS_LIMIT = 1000.0
NEWTON_DRAG_COEFFICIENT = 0.44
FULLY_EVAPORATED_UM = 10.0


def drag_coefficient(reynolds: float) -> float:
    """Schiller-Naumann below Re 1000, constant Newton drag above."""
    if reynolds <= 0:
        return 0.0
    if reynolds >= STOKES_REYNOLDS_LIMIT:
        return NEWTON_DRAG_COEFFICIENT
    return 24.0 / reynolds * (1.0 + 0.15 * reynolds**0.687)


def terminal_velocity_ms(diameter_um: float) -> float:
    """Fixed-point solve of the balance between weight and drag."""
    d = diameter_um * 1e-6
    v = 1.0
    for _ in range(60):
        reynolds = AIR_DENSITY_KGM3 * v * d / AIR_VISCOSITY_PAS
        c_d = max(drag_coefficient(reynolds), 1e-6)
        v_new = math.sqrt(4.0 * d * GRAVITY_MS2 * WATER_DENSITY_KGM3
                          / (3.0 * c_d * AIR_DENSITY_KGM3))
        if abs(v_new - v) < 1e-6:
            return v_new
        v = 0.5 * (v + v_new)
    return v


@dataclass(frozen=True)
class Trajectory:
    drift_m: float
    flight_s: float
    surviving_fraction: float
    final_diameter_um: float
    reached_target: bool


def integrate(diameter_um: float, launch_velocity_ms: float, launch_angle_deg: float,
              drop_height_m: float, air_velocity_ms: float, gas_excess_k: float,
              dt_s: float = 0.001, max_time_s: float = 60.0) -> Trajectory:
    """Fly one droplet from the nozzle down to a plane `drop_height_m` below it."""
    if diameter_um <= 0 or drop_height_m <= 0:
        raise ValueError(f"non-physical droplet input: d={diameter_um} um, h={drop_height_m} m")

    cal = load_calibration()["mist"]
    k_ref = cal["evaporation_k_ref_m2s"]["value"]
    delta_ref = cal["evaporation_reference_delta_t_k"]["value"]
    k_evap = k_ref * max(gas_excess_k, 0.0) / delta_ref

    d = diameter_um * 1e-6
    angle = math.radians(launch_angle_deg)
    vx = launch_velocity_ms * math.sin(angle)
    vz = -launch_velocity_ms * math.cos(angle)   # negative is downward
    x = 0.0
    z = 0.0
    t = 0.0

    while t < max_time_s:
        surviving_fraction = (d * 1e6 / diameter_um) ** 3
        if -z >= drop_height_m:
            return Trajectory(x, t, surviving_fraction, d * 1e6, True)
        if d * 1e6 <= FULLY_EVAPORATED_UM:
            return Trajectory(x, t, surviving_fraction, d * 1e6, False)

        rel_x = vx - air_velocity_ms
        rel = math.hypot(rel_x, vz)
        reynolds = AIR_DENSITY_KGM3 * rel * d / AIR_VISCOSITY_PAS
        c_d = drag_coefficient(reynolds)
        prefactor = 3.0 * AIR_DENSITY_KGM3 * c_d * rel / (4.0 * WATER_DENSITY_KGM3 * d)
        ax = -prefactor * rel_x
        az = -prefactor * vz - GRAVITY_MS2

        vx += ax * dt_s
        vz += az * dt_s
        x += vx * dt_s
        z += vz * dt_s
        t += dt_s

        if k_evap > 0:
            d_squared = max(d**2 - k_evap * dt_s, 0.0)
            d = math.sqrt(d_squared)

    raise RuntimeError(
        f"droplet of {diameter_um} um did not reach the plane {drop_height_m} m below "
        f"the nozzle within {max_time_s} s; check the launch conditions"
    )

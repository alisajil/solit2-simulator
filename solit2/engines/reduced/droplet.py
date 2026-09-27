"""Single-droplet flight from a nozzle to the fuel plane.

This is what separates the two spray modes: a fine droplet loses its launch
momentum within centimetres and is then carried by the tunnel airflow, while a
coarse droplet keeps enough momentum to cross the plume. The model tracks one
representative droplet per mode in the vertical plane, with Schiller-Naumann
drag and d-squared-law evaporation driven by the local gas temperature rise.

`launch_angle_deg` is measured from vertical: 0 degrees is straight down. Tilting
off vertical therefore both cuts the downward velocity component and adds a
downstream one, so it lengthens the drift rather than shortening it.

`integrate` flies ONE diameter, and a mode's `smd_um` is a Sauter MEAN, so a
mode is not one diameter. `size_distribution` expands it into the population it
stands for; the caller flies each bin through the same `integrate` and sums the
result over the bins' volume shares. That is the whole of the population model:
the trajectory, drag and evaporation physics below are untouched by it.

ponytail: two-dimensional flight, one representative droplet per SIZE BIN -
promote to a three-dimensional trajectory if the FDS tier shows the lateral
spread matters.
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
LPM_PER_M3S = 60_000.0

# How many equal-volume size bins one mode's spectrum is discretised into.
# A FIXED MODELLING CONSTANT, chosen by convergence and NOT FITTED. Swept 1 to
# 48 on the c4 reference case (task-25 report): every anchor output is converged
# by 8 bins -- c4 peak HRR moves 29.75 -> 29.70 MW between 8 and 48, c5 0.01 MW,
# c6 and every temperature not at all -- while the raw delivery at the hot end
# is still creeping about 1.5% per doubling at 48, because Rosin-Rammler has an
# unbounded tail and the coarsest bin's representative diameter grows slowly
# with the bin count. Twelve is past the knee on both measures and costs 1.19 s
# on a cold `compare.residuals()` call against 0.53 s for a single drop -- 2.2x,
# where 24 bins is 1.89 s and 3.6x. Every bin multiplies the trajectory work, and
# a fit runs that call hundreds of times, always cold: writing calibration clears
# the geometry cache.
SIZE_DISTRIBUTION_BINS = 12

# Where down the fall the spray's water loading is sampled: the midpoint.
# ponytail: one sample point for the whole flight. The cone widens and the
# droplet slows as it descends, so the true shield varies along the path;
# integrating the loading step by step inside `integrate` is the upgrade path if
# a single midpoint sample proves too coarse.
SHIELDING_SAMPLE_FRACTION = 0.5


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


def spray_shielding_factor(mode_flow_lpm: float, cone_half_angle_deg: float,
                           launch_velocity_ms: float, diameter_um: float,
                           drop_height_m: float) -> float:
    """How much of the ambient gas temperature rise one droplet actually feels.

    A droplet does not fall alone. It falls inside a cloud of other droplets
    from the same spray, and that cloud locally cools the gas -- heat goes into
    evaporating the droplets around it, not only the one being tracked -- and
    locally humidifies it, cutting the vapour-concentration gradient that drives
    further evaporation. A dense spray core is partly self-shielding, and the
    single-droplet-in-fully-hot-gas treatment has no way to represent that.

    The physical quantity behind the correction is the local water mass loading:
    the mass of water packed into each cubic metre of spray volume as it
    descends, from the mode's mass flow spread over the cone's cross-section at
    the sample point and carried through it at a representative transit speed.
    A wide cone or a slow droplet spreads the same flow over more volume and
    gives a lower loading; a tight, fast jet concentrates it.

    The shield factor saturates between `shielding_floor` and 1. It is exactly
    1 at zero loading -- a lone droplet sees the full local gas temperature rise,
    which is the model's previous behaviour recovered as a limiting case -- and
    tends to the floor as loading grows, because the spray also entrains hot
    ambient gas and full insulation from it is not physical.
    """
    if mode_flow_lpm < 0:
        raise ValueError(f"a mode cannot flow backwards: {mode_flow_lpm} lpm")
    if cone_half_angle_deg <= 0 or drop_height_m <= 0 or diameter_um <= 0:
        raise ValueError(
            f"non-physical spray input: cone half-angle={cone_half_angle_deg} deg, "
            f"drop height={drop_height_m} m, diameter={diameter_um} um; the spray "
            f"has to occupy a volume for its water loading to be defined"
        )

    cal = load_calibration()["mist"]
    reference_loading = cal["shielding_reference_loading_kgm3"]["value"]
    floor = cal["shielding_floor"]["value"]

    sample_distance_m = SHIELDING_SAMPLE_FRACTION * drop_height_m
    cone_area_m2 = math.pi * (sample_distance_m
                              * math.tan(math.radians(cone_half_angle_deg))) ** 2
    transit_velocity_ms = (launch_velocity_ms + terminal_velocity_ms(diameter_um)) / 2.0
    mdot_kgs = mode_flow_lpm * WATER_DENSITY_KGM3 / LPM_PER_M3S
    loading_kgm3 = mdot_kgs / (cone_area_m2 * transit_velocity_ms)

    return floor + (1.0 - floor) / (1.0 + loading_kgm3 / reference_loading)


class StillAirborne(RuntimeError):
    """The droplet had not reached the plane when the flight clock ran out.

    A `RuntimeError` subclass, so anything that caught the plain `RuntimeError`
    `integrate` used to raise still catches this; the flight itself is unchanged.
    It is named because a caller flying a whole SIZE SPECTRUM meets it as an
    ordinary outcome rather than as a mis-specified design: the fine tail of a
    real spray genuinely does not reach the fuel, it is carried away, and the
    caller has to be able to tell that apart from any other runtime failure.
    """


@dataclass(frozen=True)
class SizeBin:
    """One slice of a mode's droplet spectrum, and its share of the WATER VOLUME.

    Volume, not droplet count. Everything downstream of the spray is a volume
    flow -- litres per minute onto the fuel, millimetres per minute of
    application -- so these weights have to be volume shares for the sum over
    bins to be the mode's flow. Number shares would be the same spectrum read
    the other way round and would put nearly all the weight on the fines, which
    carry cubically less water each; see `size_distribution`.
    """
    diameter_um: float
    volume_fraction: float


def size_distribution(smd_um: float, spread_n: float,
                      bin_count: int | None = None) -> tuple[SizeBin, ...]:
    """A mode's Sauter mean diameter expanded into the spectrum it stands for.

    Rosin-Rammler, the standard form for pressure-atomised sprays: the volume
    fraction of the spray held in droplets coarser than `d` is
    `exp(-(d / X) ** n)`, with `n` the spread exponent (`spread_n`, from the
    mode's measured Dv50/Dv90 via `Nozzles.spread_n`; lower is wider) and `X` a characteristic diameter. Its
    spread parameter is a quantity nozzle datasheets actually quote, which is
    why it is the right form here rather than a log-normal.

    The spectrum is cut into `bin_count` slices of EQUAL VOLUME and each is
    represented by the diameter at its own mid-quantile. Equal volume is what
    makes the weighting impossible to get backwards -- every weight is
    `1 / bin_count` by construction -- and it puts the bins where the water is
    rather than where the droplets are.

    `X` is then set so that the discrete set's own Sauter mean,
    `1 / sum(v_i / d_i)` (volume over surface, which is what a Sauter mean is),
    equals `smd_um` exactly, at any bin count. Two things follow. At
    `bin_count == 1` this returns the single representative drop unchanged, so
    the population model is a strict generalisation of the one it replaces. And
    the spray's total surface area per unit volume is preserved, so the
    radiation extinction computed from the mode's SMD in `mist` stays exactly
    right without knowing the spectrum exists.
    """
    if smd_um <= 0:
        raise ValueError(f"a spray's Sauter mean diameter must be positive, got {smd_um} um")
    # Read at call time, not bound as a default, so the convergence sweep that
    # chose it can be re-run against the shipped code by setting one name.
    bin_count = SIZE_DISTRIBUTION_BINS if bin_count is None else bin_count
    if bin_count < 1:
        raise ValueError(f"a spectrum needs at least one size bin, got {bin_count}")

    spread = spread_n
    if spread <= 1.0:
        raise ValueError(
            f"spread_n={spread} is not a spray: the Rosin-Rammler Sauter mean is "
            f"X / gamma(1 - 1/n), and gamma(1 - 1/n) diverges at n = 1 and is negative "
            f"below it, so such a spectrum has unbounded surface area per unit volume"
        )

    volume_fraction = 1.0 / bin_count
    # Inverse Rosin-Rammler at the mid-quantile of each equal-volume slice, in
    # units of the characteristic diameter X, which is still to be determined.
    shape = tuple((-math.log(1.0 - (i + 0.5) / bin_count)) ** (1.0 / spread)
                  for i in range(bin_count))
    scale_um = smd_um * sum(volume_fraction / u for u in shape)
    return tuple(SizeBin(u * scale_um, volume_fraction) for u in shape)


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

    raise StillAirborne(
        f"droplet of {diameter_um} um did not reach the plane {drop_height_m} m below "
        f"the nozzle within {max_time_s} s; check the launch conditions"
    )

"""What the spray actually delivers to the fire.

Every head discharges each mode as a cone. The cone's footprint on the plane of
the fuel top is shifted downstream by the droplet's drift, which is why a fine
mode released far upstream can still arrive over the fire while a coarse mode
lands almost under its own nozzle. Water flux on the fuel and its one-metre halo
drives suppression; evaporated water cools the gas; suspended water attenuates
radiation.

Ruling R4 splits the work in two. The expensive half - the trajectory
integration and the sweep of every head's footprint across the halo grid -
depends only on the spray geometry and the flight condition, never on how much
water is flowing. It is computed once per distinct condition and cached. The
cheap half - scaling that footprint overlap by the actual flow - runs on every
call. `evaluate` is called once per simulated second for an hour, several times
over, so the split is what makes the run tractable at all.

`mounting.tilt_deg` and `droplet.integrate`'s `launch_angle_deg` are both
measured from vertical, 0 being straight down, so the tilt passes straight
through with no conversion.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from solit2.engines.reduced.droplet import integrate
from solit2.engines.reduced.geometry import NozzlePosition, SectionGeometry
from solit2.engines.reduced.state import MistEffect
from solit2.schema.design import Design
from solit2.schema.presets import load_calibration

WATER_DENSITY_KGM3 = 1000.0
WATER_CP_KJKGK = 4.18
WATER_LATENT_HEAT_KJKG = 2257.0
WATER_INLET_TEMP_C = 30.0
WATER_BOILING_C = 100.0
LPM_PER_M3S = 60_000.0
METRES_PER_UM = 1e-6
GRID_CELL_M = 0.2
HALO_MARGIN_M = 1.0
# Geometric-optics extinction: kappa = 1.5 * volume fraction / droplet diameter.
EXTINCTION_PREFACTOR = 1.5
# A target beside the fire sees the curtain over half the active length.
CURTAIN_PATH_FRACTION = 0.5
# Floors that keep the residence time finite for a pencil jet or still air.
MIN_RESIDENCE_RADIUS_M = 0.1
MIN_RESIDENCE_VELOCITY_MS = 0.1

# Ruling R4: flight conditions are quantised so that a 3600-step run performs a
# few dozen distinct geometry computations instead of 3600. Narrowing either
# width smooths the suppression response at the cost of more cache entries.
VELOCITY_BUCKET_MS = 0.25
GAS_EXCESS_BUCKET_K = 25.0


@dataclass(frozen=True)
class Halo:
    x0_m: float
    x1_m: float
    y0_m: float
    y1_m: float

    @property
    def area_m2(self) -> float:
        return (self.x1_m - self.x0_m) * (self.y1_m - self.y0_m)


@dataclass(frozen=True)
class ModeDelivery:
    mode_id: str
    drift_m: float
    surviving_fraction: float
    footprint_radius_m: float
    flow_to_halo_lpm: float


@dataclass(frozen=True, eq=False)
class _ModeGeometry:
    """The flow-independent half of a mode's delivery.

    `unit_overlap_per_lpm` is the halo overlap summed over every head for one
    litre per minute per head; `coverage_mask` is the union of those footprints
    over the halo grid. Both scale linearly with flow, so neither needs
    recomputing when only the pump ramp moves. The mask is read-only because it
    is shared by every caller that hits the same cache entry.
    """
    mode_id: str
    drift_m: float
    surviving_fraction: float
    footprint_radius_m: float
    unit_overlap_per_lpm: float
    coverage_mask: np.ndarray


# ponytail: unbounded dict keyed on the full spray geometry. One run adds a few
# dozen entries of roughly 2 kB each; swap for an LRU if a fitting loop over
# thousands of designs makes the footprint matter.
_GEOMETRY_CACHE: dict[tuple, tuple[_ModeGeometry, ...]] = {}


def halo_around(fire_x_m: float, fire_y_m: float, fire_length_m: float,
                fire_width_m: float, margin_m: float = HALO_MARGIN_M) -> Halo:
    return Halo(
        x0_m=fire_x_m - fire_length_m / 2.0 - margin_m,
        x1_m=fire_x_m + fire_length_m / 2.0 + margin_m,
        y0_m=fire_y_m - fire_width_m / 2.0 - margin_m,
        y1_m=fire_y_m + fire_width_m / 2.0 + margin_m,
    )


def _grid(halo: Halo) -> tuple[np.ndarray, np.ndarray]:
    nx = max(int(round((halo.x1_m - halo.x0_m) / GRID_CELL_M)), 1)
    ny = max(int(round((halo.y1_m - halo.y0_m) / GRID_CELL_M)), 1)
    xs = np.linspace(halo.x0_m + GRID_CELL_M / 2, halo.x1_m - GRID_CELL_M / 2, nx)
    ys = np.linspace(halo.y0_m + GRID_CELL_M / 2, halo.y1_m - GRID_CELL_M / 2, ny)
    return np.meshgrid(xs, ys, indexing="ij")


def _drop_height_m(design: Design, fire_top_m: float) -> float:
    mounted_at = design.nozzles.mounting.height_above_carriageway_m
    drop = mounted_at - fire_top_m
    if drop <= 0:
        raise ValueError(
            f"nozzles at {mounted_at} m are not above the fuel top at {fire_top_m} m"
        )
    return drop


def _bucket(value: float, width: float) -> float:
    """Snap to the centre of a quantisation bucket (ruling R4)."""
    return round(value / width) * width


def _sweep(positions: tuple[NozzlePosition, ...], gx: np.ndarray, gy: np.ndarray,
           drift_m: float, radius_m: float) -> tuple[float, np.ndarray]:
    """Halo overlap per litre-per-minute-per-head, and the union of the footprints."""
    footprint_area = math.pi * radius_m**2
    covered = np.zeros(gx.shape, dtype=bool)
    unit_overlap = 0.0
    for p in positions:
        cx = p.x_m + drift_m
        inside = ((gx - cx) ** 2 + (gy - p.y_m) ** 2) <= radius_m**2
        hit = float(inside.sum()) * GRID_CELL_M**2
        if hit > 0:
            unit_overlap += min(hit / footprint_area, 1.0)
            covered |= inside
    covered.flags.writeable = False
    return unit_overlap, covered


def _compute_geometry(design: Design, positions: tuple[NozzlePosition, ...], halo: Halo,
                      drop_height_m: float, u_eff_ms: float,
                      gas_excess_k: float) -> tuple[_ModeGeometry, ...]:
    """The expensive half: one trajectory and one footprint sweep per mode."""
    tilt_deg = design.nozzles.mounting.tilt_deg
    gx, gy = _grid(halo)
    out = []
    for mode in design.nozzles.modes:
        traj = integrate(
            diameter_um=design.nozzles.smd_um(mode.id),
            launch_velocity_ms=mode.launch_velocity_ms,
            launch_angle_deg=tilt_deg,
            drop_height_m=drop_height_m,
            air_velocity_ms=u_eff_ms,
            gas_excess_k=gas_excess_k,
        )
        radius = drop_height_m * math.tan(math.radians(mode.cone_half_angle_deg))
        unit_overlap, mask = _sweep(positions, gx, gy, traj.drift_m, radius)
        out.append(_ModeGeometry(mode.id, traj.drift_m, traj.surviving_fraction,
                                 radius, unit_overlap, mask))
    return tuple(out)


def _geometry_key(design: Design, positions: tuple[NozzlePosition, ...], halo: Halo,
                  drop_height_m: float, u_bucket_ms: float, gas_bucket_k: float) -> tuple:
    """Everything the cached geometry depends on.

    Ruling R4: the key carries the design's own spray geometry as well as the
    flight condition, so two designs evaluated in the same process - the
    envelope runs several, a calibration fit runs many - cannot read each
    other's entries.
    """
    nozzles = design.nozzles
    modes = tuple((m.id, nozzles.smd_um(m.id), m.cone_half_angle_deg, m.launch_velocity_ms)
                  for m in nozzles.modes)
    return (modes, nozzles.mounting.tilt_deg, drop_height_m,
            u_bucket_ms, gas_bucket_k, positions, halo)


def _geometry(design: Design, positions: tuple[NozzlePosition, ...], halo: Halo,
              fire_top_m: float, u_eff_ms: float,
              gas_excess_k: float) -> tuple[_ModeGeometry, ...]:
    """Cached spray geometry for one quantised flight condition."""
    drop_height_m = _drop_height_m(design, fire_top_m)
    u_bucket_ms = _bucket(u_eff_ms, VELOCITY_BUCKET_MS)
    gas_bucket_k = _bucket(gas_excess_k, GAS_EXCESS_BUCKET_K)
    key = _geometry_key(design, positions, halo, drop_height_m, u_bucket_ms, gas_bucket_k)
    cached = _GEOMETRY_CACHE.get(key)
    if cached is None:
        # The bucket centres, not the raw values, so the entry is self-consistent.
        cached = _compute_geometry(design, positions, halo, drop_height_m,
                                   u_bucket_ms, gas_bucket_k)
        _GEOMETRY_CACHE[key] = cached
    return cached


def _deliveries(design: Design, geometries: tuple[_ModeGeometry, ...],
                flow_fraction: float) -> tuple[ModeDelivery, ...]:
    """The cheap half: scale the cached unit overlap by the water actually flowing."""
    return tuple(
        ModeDelivery(
            mode_id=g.mode_id,
            drift_m=g.drift_m,
            surviving_fraction=g.surviving_fraction,
            footprint_radius_m=g.footprint_radius_m,
            flow_to_halo_lpm=(g.unit_overlap_per_lpm
                              * design.nozzles.mode_flow_lpm(g.mode_id)
                              * flow_fraction * g.surviving_fraction),
        )
        for g in geometries
    )


def mode_deliveries(design: Design, positions: tuple[NozzlePosition, ...], halo: Halo,
                    fire_top_m: float, u_eff_ms: float, gas_excess_k: float,
                    flow_fraction: float) -> tuple[ModeDelivery, ...]:
    """Per mode: how far the spray drifts, how much survives, how much lands on the halo."""
    geometries = _geometry(design, positions, halo, fire_top_m, u_eff_ms, gas_excess_k)
    return _deliveries(design, geometries, flow_fraction)


def _coverage(geometries: tuple[_ModeGeometry, ...],
              deliveries: tuple[ModeDelivery, ...]) -> float:
    """Fraction of the halo under at least one footprint that is actually delivering."""
    masks = [g.coverage_mask for g, d in zip(geometries, deliveries)
             if d.flow_to_halo_lpm > 0]
    if not masks:
        return 0.0
    covered = masks[0]
    for mask in masks[1:]:
        covered = covered | mask
    return float(covered.mean())


def _cooling_fraction(design: Design, geometries: tuple[_ModeGeometry, ...], head_count: int,
                      flow_fraction: float, q_conv_kw: float, cap: float) -> float:
    """Only the water that evaporates in flight removes heat from the gas."""
    if q_conv_kw <= 0:
        return 0.0
    sensible = WATER_CP_KJKGK * (WATER_BOILING_C - WATER_INLET_TEMP_C) + WATER_LATENT_HEAT_KJKG
    total = 0.0
    for g in geometries:
        evaporated = 1.0 - g.surviving_fraction
        mdot = (design.nozzles.mode_flow_lpm(g.mode_id) * head_count * flow_fraction
                / LPM_PER_M3S * WATER_DENSITY_KGM3)
        total += evaporated * mdot * sensible / q_conv_kw
    return min(total, cap)


def _curtain_transmissivity(design: Design, geom: SectionGeometry,
                            geometries: tuple[_ModeGeometry, ...], head_count: int,
                            flow_fraction: float, u_eff_ms: float) -> float:
    """Beer-Lambert through the water suspended in the active zone."""
    active_volume = design.active_length_m * geom.free_area_m2
    kappa = 0.0
    for g in geometries:
        flow_m3s = (design.nozzles.mode_flow_lpm(g.mode_id) * head_count
                    * flow_fraction / LPM_PER_M3S)
        residence_s = (max(g.footprint_radius_m, MIN_RESIDENCE_RADIUS_M)
                       / max(u_eff_ms, MIN_RESIDENCE_VELOCITY_MS))
        volume_fraction = flow_m3s * residence_s / active_volume
        kappa += (EXTINCTION_PREFACTOR * volume_fraction
                  / (design.nozzles.smd_um(g.mode_id) * METRES_PER_UM))
    return math.exp(-kappa * design.active_length_m * CURTAIN_PATH_FRACTION)


def evaluate(design: Design, geom: SectionGeometry, positions: tuple[NozzlePosition, ...],
             halo: Halo, fire_top_m: float, u_eff_ms: float, gas_excess_k: float,
             q_conv_kw: float, flow_fraction: float) -> MistEffect:
    if flow_fraction <= 0:
        return MistEffect.none()

    cal = load_calibration()["mist"]
    geometries = _geometry(design, positions, halo, fire_top_m, u_eff_ms, gas_excess_k)
    deliveries = _deliveries(design, geometries, flow_fraction)

    w_fuel = sum(d.flow_to_halo_lpm for d in deliveries) / halo.area_m2
    f_cov = _coverage(geometries, deliveries)
    eta = cal["eta_max"]["value"] * (
        1.0 - math.exp(-w_fuel * f_cov / cal["w_ref_mm_min"]["value"]))

    head_count = len(positions)
    chi_cool = _cooling_fraction(design, geometries, head_count, flow_fraction,
                                 q_conv_kw, cal["chi_cool_max"]["value"])
    tau_mist = _curtain_transmissivity(design, geom, geometries, head_count,
                                       flow_fraction, u_eff_ms)

    return MistEffect(eta=eta, w_fuel_mm_min=w_fuel, f_cov=f_cov,
                      chi_cool=chi_cool, tau_mist=tau_mist)

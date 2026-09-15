"""What the spray actually delivers to the fire.

Every head discharges each mode as a cone. The cone's footprint on the plane of
the fuel top is shifted downstream by the droplet's drift, which is why a fine
mode released far upstream can still arrive over the fire while a coarse mode
lands almost under its own nozzle. Water flux on the fuel drives suppression;
evaporated water cools the gas; suspended water attenuates radiation.

The fuel is a stack, not a plate, so it is given two interception surfaces. The
`top` face takes water that soaks in and runs down through the load, and is
credited in full. Around it, a flank band as wide as `FLANK_REACH_FACTOR` times
the fuel's height catches spray that strikes the stack's sides and ends on the
way down; it is credited at `FLANK_EFFICIENCY`, because water running down a
vertical face wets less fuel per litre than water landing on top and some of it
rebounds away. Counting only the top plane treats a four-metre stack as a flat
plate, and at a short throw -- nozzles less than a metre above the load -- it
reports almost nothing arriving.

`w_fuel_mm_min` is normalised to the TOP-FACE area, so it keeps its meaning:
millimetres per minute of effective application on the fuel. It can exceed the
zone-average application density, which is correct -- a stack standing in a
spray field intercepts more than its plan area's share.

Ruling R4 splits the work in two. The expensive half - the trajectory
integration and the sweep of every head's footprint across the envelope grid -
depends only on the spray geometry and the flight condition, never on how much
water is flowing. It is computed once per distinct condition and cached. The
cheap half - scaling that footprint overlap by the actual flow - runs on every
call. `evaluate` is called once per simulated second for an hour, several times
over, so the split is what makes the run tractable at all.

`mounting.tilt_deg` and `droplet.integrate`'s `launch_angle_deg` are both
measured from vertical, 0 being straight down, so the tilt passes straight
through with no conversion.

Each mode's droplets are not treated as falling alone. `_compute_geometry` asks
`droplet.spray_shielding_factor` how dense that mode's spray core is and scales
the gas temperature rise handed to `integrate` by the answer, because a droplet
inside a dense cloud of others feels a locally cooled, locally humidified
environment rather than the full plume. Everything the shield depends on is
fixed by the design, and the gas temperature it scales is already bucketed, so
it composes with the R4 cache without adding a dimension to the key.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from solit2.engines.reduced.droplet import integrate, spray_shielding_factor
from solit2.engines.reduced.geometry import NozzlePosition, SectionGeometry
from solit2.engines.reduced.state import MistEffect
from solit2.schema.design import Design
from solit2.schema.presets import load_calibration, register_cache_invalidation_hook

WATER_DENSITY_KGM3 = 1000.0
WATER_CP_KJKGK = 4.18
WATER_LATENT_HEAT_KJKG = 2257.0
WATER_INLET_TEMP_C = 30.0
WATER_BOILING_C = 100.0
LPM_PER_M3S = 60_000.0
METRES_PER_UM = 1e-6
GRID_CELL_M = 0.2
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
class Rect:
    """An axis-aligned patch of the carriageway plan."""
    x0_m: float
    x1_m: float
    y0_m: float
    y1_m: float

    @property
    def area_m2(self) -> float:
        return (self.x1_m - self.x0_m) * (self.y1_m - self.y0_m)


@dataclass(frozen=True)
class FuelEnvelope:
    """The surfaces a stack of fuel presents to descending spray.

    `top` is the fuel footprint itself, at the load's top height. `outer` is
    that footprint grown by the flank reach on every side; the band between the
    two is what the stack's sides sweep out of the falling spray.
    """
    top: Rect
    outer: Rect

    @property
    def flank_area_m2(self) -> float:
        return self.outer.area_m2 - self.top.area_m2


@dataclass(frozen=True)
class ModeDelivery:
    mode_id: str
    drift_m: float
    surviving_fraction: float
    footprint_radius_m: float
    flow_to_top_lpm: float
    flow_to_flank_lpm: float

    @property
    def flow_to_fuel_lpm(self) -> float:
        """Everything the fuel intercepts, before the flank is discounted."""
        return self.flow_to_top_lpm + self.flow_to_flank_lpm


@dataclass(frozen=True, eq=False)
class _ModeGeometry:
    """The flow-independent half of a mode's delivery.

    `unit_top_per_lpm` and `unit_flank_per_lpm` are the shares of each head's
    cone landing on the two surfaces, summed over every head, for one litre per
    minute per head; `coverage_mask` is the union of those footprints over the
    envelope grid. All three scale linearly with flow, so none needs recomputing
    when only the pump ramp moves. The mask is read-only because it is shared by
    every caller that hits the same cache entry.
    """
    mode_id: str
    drift_m: float
    surviving_fraction: float
    footprint_radius_m: float
    unit_top_per_lpm: float
    unit_flank_per_lpm: float
    coverage_mask: np.ndarray


# ponytail: unbounded dict keyed on the full spray geometry. One run adds a few
# dozen entries of roughly 2 kB each; swap for an LRU if a fitting loop over
# thousands of designs makes the footprint matter.
_GEOMETRY_CACHE: dict[tuple, tuple[_ModeGeometry, ...]] = {}

# `_compute_geometry` calls `spray_shielding_factor`, which reads its own
# calibration constants internally -- values `_geometry_key` cannot see because
# they never pass through its arguments. A fit that changes them would
# otherwise go on being served trajectories computed under whatever value
# happened to populate a cache entry first. Registering unconditionally, at
# import time, means that discipline does not depend on `_geometry_key` (or
# whoever edits it next) knowing every constant every callee reads.
register_cache_invalidation_hook(_GEOMETRY_CACHE.clear)


def flank_reach_m(fire_top_height_m: float) -> float:
    """How wide a band of falling spray a stack of this height sweeps up."""
    factor = load_calibration()["mist"]["flank_reach_factor"]["value"]
    return factor * fire_top_height_m


def fuel_envelope(fire_x_m: float, fire_y_m: float, fire_length_m: float,
                  fire_width_m: float, reach_m: float) -> FuelEnvelope:
    """The fuel's top face and the flank band around it."""
    if reach_m < 0:
        raise ValueError(f"flank reach must not be negative, got {reach_m} m")
    top = Rect(
        x0_m=fire_x_m - fire_length_m / 2.0,
        x1_m=fire_x_m + fire_length_m / 2.0,
        y0_m=fire_y_m - fire_width_m / 2.0,
        y1_m=fire_y_m + fire_width_m / 2.0,
    )
    outer = Rect(top.x0_m - reach_m, top.x1_m + reach_m,
                 top.y0_m - reach_m, top.y1_m + reach_m)
    return FuelEnvelope(top=top, outer=outer)


def _grid(rect: Rect) -> tuple[np.ndarray, np.ndarray]:
    nx = max(int(round((rect.x1_m - rect.x0_m) / GRID_CELL_M)), 1)
    ny = max(int(round((rect.y1_m - rect.y0_m) / GRID_CELL_M)), 1)
    xs = np.linspace(rect.x0_m + GRID_CELL_M / 2, rect.x1_m - GRID_CELL_M / 2, nx)
    ys = np.linspace(rect.y0_m + GRID_CELL_M / 2, rect.y1_m - GRID_CELL_M / 2, ny)
    return np.meshgrid(xs, ys, indexing="ij")


def _top_face_mask(top: Rect, gx: np.ndarray, gy: np.ndarray) -> np.ndarray:
    """Which cells of the envelope grid are the fuel's own top face."""
    return ((gx >= top.x0_m) & (gx <= top.x1_m)
            & (gy >= top.y0_m) & (gy <= top.y1_m))


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
           top_mask: np.ndarray, drift_m: float,
           radius_m: float) -> tuple[float, float, np.ndarray]:
    """Per litre-per-minute-per-head: the share of every head's cone landing on
    the top face and on the flank band, and the union of the footprints."""
    footprint_area = math.pi * radius_m**2
    cell_area = GRID_CELL_M**2
    covered = np.zeros(gx.shape, dtype=bool)
    unit_top = 0.0
    unit_flank = 0.0
    for p in positions:
        cx = p.x_m + drift_m
        inside = ((gx - cx) ** 2 + (gy - p.y_m) ** 2) <= radius_m**2
        on_top = float((inside & top_mask).sum()) * cell_area / footprint_area
        on_flank = float(inside.sum()) * cell_area / footprint_area - on_top
        if on_top + on_flank <= 0.0:
            continue
        on_top, on_flank = _capped(on_top, on_flank)
        unit_top += on_top
        unit_flank += on_flank
        covered |= inside
    covered.flags.writeable = False
    return unit_top, unit_flank, covered


def _capped(on_top: float, on_flank: float) -> tuple[float, float]:
    """A head cannot deliver more than the water it is given.

    The two surfaces are disjoint, so their shares can only sum above one
    through grid discretisation; scaling both keeps the split between them.
    """
    total = on_top + on_flank
    if total <= 1.0:
        return on_top, on_flank
    return on_top / total, on_flank / total


def _compute_geometry(design: Design, positions: tuple[NozzlePosition, ...],
                      envelope: FuelEnvelope, drop_height_m: float, u_eff_ms: float,
                      gas_excess_k: float) -> tuple[_ModeGeometry, ...]:
    """The expensive half: one trajectory and one footprint sweep per mode."""
    tilt_deg = design.nozzles.mounting.tilt_deg
    gx, gy = _grid(envelope.outer)
    top_mask = _top_face_mask(envelope.top, gx, gy)
    out = []
    for mode in design.nozzles.modes:
        # A droplet falls inside a cloud of others from the same spray, which
        # locally cools and humidifies its gas, so it feels only part of the
        # plume's temperature rise. This changes what thermal environment the
        # droplet experiences, not its ballistics: `integrate` is unchanged and
        # only its `gas_excess_k` argument is scaled. The coupling that follows
        # is real -- less evaporation keeps the droplet larger, which changes its
        # drag and so its drift -- and is not fought.
        # ponytail: shielding computed at full rated flow, not scaled by the ramp
        # fraction -- the differential effect during the ~30 s ramp is
        # second-order against exposure over the full run; revisit if a design
        # with an unusually long ramp is ever evaluated. Ruling R4 also requires
        # it: a shield that depended on `flow_fraction` would put the pump ramp
        # into the geometry cache key and the whole run's tractability with it.
        shield = spray_shielding_factor(
            mode_flow_lpm=design.nozzles.mode_flow_lpm(mode.id),
            cone_half_angle_deg=mode.cone_half_angle_deg,
            launch_velocity_ms=mode.launch_velocity_ms,
            diameter_um=design.nozzles.smd_um(mode.id),
            drop_height_m=drop_height_m,
        )
        traj = integrate(
            diameter_um=design.nozzles.smd_um(mode.id),
            launch_velocity_ms=mode.launch_velocity_ms,
            launch_angle_deg=tilt_deg,
            drop_height_m=drop_height_m,
            air_velocity_ms=u_eff_ms,
            gas_excess_k=gas_excess_k * shield,
        )
        radius = drop_height_m * math.tan(math.radians(mode.cone_half_angle_deg))
        unit_top, unit_flank, mask = _sweep(positions, gx, gy, top_mask,
                                            traj.drift_m, radius)
        out.append(_ModeGeometry(mode.id, traj.drift_m, traj.surviving_fraction,
                                 radius, unit_top, unit_flank, mask))
    return tuple(out)


def _geometry_key(design: Design, positions: tuple[NozzlePosition, ...],
                  envelope: FuelEnvelope, drop_height_m: float, u_bucket_ms: float,
                  gas_bucket_k: float) -> tuple:
    """Everything the cached geometry depends on.

    Ruling R4: the key carries the design's own spray geometry as well as the
    flight condition, so two designs evaluated in the same process - the
    envelope runs several, a calibration fit runs many - cannot read each
    other's entries. The fuel envelope is part of the key too, so moving
    `flank_reach_factor` between fits cannot serve a stale sweep.

    `mode_flow_lpm` is part of the key for the same reason: `_compute_geometry`
    feeds it to `spray_shielding_factor`, so two designs that differ only in
    K-factor or pressure -- same droplet size, cone angle, launch velocity,
    mounting and fire geometry -- would otherwise collide on one entry and read
    back a shield factor computed for the wrong flow rate.
    """
    nozzles = design.nozzles
    modes = tuple((m.id, nozzles.smd_um(m.id), m.cone_half_angle_deg, m.launch_velocity_ms,
                  nozzles.mode_flow_lpm(m.id))
                  for m in nozzles.modes)
    return (modes, nozzles.mounting.tilt_deg, drop_height_m,
            u_bucket_ms, gas_bucket_k, positions, envelope)


def _geometry(design: Design, positions: tuple[NozzlePosition, ...],
              envelope: FuelEnvelope, fire_top_m: float, u_eff_ms: float,
              gas_excess_k: float) -> tuple[_ModeGeometry, ...]:
    """Cached spray geometry for one quantised flight condition."""
    drop_height_m = _drop_height_m(design, fire_top_m)
    u_bucket_ms = _bucket(u_eff_ms, VELOCITY_BUCKET_MS)
    gas_bucket_k = _bucket(gas_excess_k, GAS_EXCESS_BUCKET_K)
    key = _geometry_key(design, positions, envelope, drop_height_m,
                        u_bucket_ms, gas_bucket_k)
    cached = _GEOMETRY_CACHE.get(key)
    if cached is None:
        # The bucket centres, not the raw values, so the entry is self-consistent.
        cached = _compute_geometry(design, positions, envelope, drop_height_m,
                                   u_bucket_ms, gas_bucket_k)
        _GEOMETRY_CACHE[key] = cached
    return cached


def _deliveries(design: Design, geometries: tuple[_ModeGeometry, ...],
                flow_fraction: float) -> tuple[ModeDelivery, ...]:
    """The cheap half: scale the cached unit overlap by the water actually flowing."""
    out = []
    for g in geometries:
        flowing = (design.nozzles.mode_flow_lpm(g.mode_id)
                   * flow_fraction * g.surviving_fraction)
        out.append(ModeDelivery(
            mode_id=g.mode_id,
            drift_m=g.drift_m,
            surviving_fraction=g.surviving_fraction,
            footprint_radius_m=g.footprint_radius_m,
            flow_to_top_lpm=g.unit_top_per_lpm * flowing,
            flow_to_flank_lpm=g.unit_flank_per_lpm * flowing,
        ))
    return tuple(out)


def mode_deliveries(design: Design, positions: tuple[NozzlePosition, ...],
                    envelope: FuelEnvelope, fire_top_m: float, u_eff_ms: float,
                    gas_excess_k: float,
                    flow_fraction: float) -> tuple[ModeDelivery, ...]:
    """Per mode: how far the spray drifts, how much survives, how much lands on
    the fuel's top face and how much on its flanks."""
    geometries = _geometry(design, positions, envelope, fire_top_m, u_eff_ms, gas_excess_k)
    return _deliveries(design, geometries, flow_fraction)


def _coverage(geometries: tuple[_ModeGeometry, ...],
              deliveries: tuple[ModeDelivery, ...]) -> float:
    """Fraction of the fuel's whole interception envelope - top face and flank
    band together - under at least one footprint that is actually delivering."""
    masks = [g.coverage_mask for g, d in zip(geometries, deliveries)
             if d.flow_to_fuel_lpm > 0]
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


def _effective_flux_mm_min(deliveries: tuple[ModeDelivery, ...], envelope: FuelEnvelope,
                           flank_efficiency: float) -> float:
    """Millimetres per minute of effective application, over the top-face area."""
    q_top = sum(d.flow_to_top_lpm for d in deliveries)
    q_flank = sum(d.flow_to_flank_lpm for d in deliveries)
    return (q_top + flank_efficiency * q_flank) / envelope.top.area_m2


def evaluate(design: Design, geom: SectionGeometry, positions: tuple[NozzlePosition, ...],
             envelope: FuelEnvelope, fire_top_m: float, u_eff_ms: float, gas_excess_k: float,
             q_conv_kw: float, flow_fraction: float) -> MistEffect:
    if flow_fraction <= 0:
        return MistEffect.none()

    cal = load_calibration()["mist"]
    geometries = _geometry(design, positions, envelope, fire_top_m, u_eff_ms, gas_excess_k)
    deliveries = _deliveries(design, geometries, flow_fraction)

    w_fuel = _effective_flux_mm_min(deliveries, envelope,
                                    cal["flank_efficiency"]["value"])
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

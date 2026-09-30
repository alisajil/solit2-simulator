"""State objects shared between the engine modules.

Keeping these here avoids an import cycle: `fire` needs the mist's effect and
`mist` needs the fire's size, so neither may import the other.
"""
from __future__ import annotations

from bisect import bisect_right
from dataclasses import dataclass, field


def _ratio_along(xs: tuple[float, ...], ratios: tuple[float, ...], x_m: float) -> float:
    """Piecewise-linear lookup of a cumulative ratio; flat beyond both ends."""
    i = bisect_right(xs, x_m)
    if i == 0:
        return 0.0
    if i == len(xs):
        return ratios[-1]
    x0, x1 = xs[i - 1], xs[i]
    return ratios[i - 1] + (ratios[i] - ratios[i - 1]) * (x_m - x0) / (x1 - x0)


@dataclass(frozen=True)
class CoolingProfile:
    """Where along the tunnel the spray takes heat from gas that has left the fire.

    Gas flows away from the fire: downstream with the ventilation, upstream in
    the backlayer. Beyond the plume it meets the heads it passes, one after
    another, and each takes its share of what is left. `remaining(x)` is the
    share of the heat the gas left the plume with that it still carries at `x`
    -- 1 over the plume, falling past every head it has passed.

    The ratios are the cumulative evaporation potential met beyond each edge of
    the plume, scaled by the share of the heat the plume let through, so that
    the plume's own first-order closure carries on along the path:
    share = 1 / (1 + ratio). Far downstream the gas has then given up exactly
    what one closure over every head it passed would take.
    Downstream breakpoints ascend in x; upstream ones are stored as distances
    beyond the upstream edge, mirrored so that they ascend too.
    """
    downstream_edge_m: float = 0.0
    upstream_edge_m: float = 0.0
    downstream_x_m: tuple[float, ...] = ()
    downstream_ratio: tuple[float, ...] = ()
    upstream_x_m: tuple[float, ...] = ()      # -x, ascending
    upstream_ratio: tuple[float, ...] = ()

    def remaining(self, x_m: float) -> float:
        if x_m > self.downstream_edge_m and self.downstream_x_m:
            return 1.0 / (1.0 + _ratio_along(self.downstream_x_m, self.downstream_ratio, x_m))
        if x_m < self.upstream_edge_m and self.upstream_x_m:
            return 1.0 / (1.0 + _ratio_along(self.upstream_x_m, self.upstream_ratio, -x_m))
        return 1.0

    @property
    def downstream_end(self) -> float:
        """Share still carried by the gas once it has passed every head downstream."""
        return 1.0 / (1.0 + self.downstream_ratio[-1]) if self.downstream_ratio else 1.0

    @property
    def upstream_end(self) -> float:
        """Share still carried by the backlayer once it has passed every head upstream."""
        return 1.0 / (1.0 + self.upstream_ratio[-1]) if self.upstream_ratio else 1.0


@dataclass(frozen=True)
class MistEffect:
    """What the mist is doing to the fire at one instant."""
    eta: float            # suppression efficiency applied to the Class A burning rate, 0..1
    # effective application on the fuel: top-face water plus flank-band water at
    # its reduced efficiency, over the top-face area
    w_fuel_mm_min: float
    f_cov: float          # fraction of the fuel's interception envelope any spray reaches
    # fraction of the convective heat release the spray removes IN THE PLUME, from
    # the water falling through it; what it takes further along is `cooling`
    chi_cool: float
    tau_mist: float       # radiant transmissivity through the mist curtain, 0..1
    cooling: CoolingProfile = field(default_factory=CoolingProfile)
    # Extinction of visible light by the suspended droplets, per metre, inside the
    # active zone: geometric optics with Q_ext = 2, from the same water loading that
    # sets `tau_mist`. Zero when the system is not discharging.
    kappa_visible_per_m: float = 0.0

    @property
    def chi_downstream(self) -> float:
        """Fraction of the convective heat the spray has taken from the gas by the
        time it has passed every head downstream: the plume's share and the
        tunnel's together."""
        return 1.0 - (1.0 - self.chi_cool) * self.cooling.downstream_end

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
    """What the instruments at one Annex 7 Table 5 location read this step.

    EVERY OPTIONAL FIELD IS `None` WHERE TABLE 5 PUTS NO SENSOR, never zero.
    Zero is a reading; absence is not, and a zero would be silently averaged or
    compared as though a gauge had produced it. `criteria.INSTRUMENTS` is the
    single statement of which is which, and the worst-station searches in
    `criteria` read that map rather than testing these fields for `None`.
    """
    # Breathing height (criteria.BREATHING_HEIGHT_M), the height the section
    # 7.2.2 tenability criteria are evaluated at, and by construction the entry
    # of `temps_c` at that height.
    temp_c: float
    flux_kwm2: float | None
    visibility_m: float | None
    fed_tox: float | None       # cumulative to this instant
    fed_heat: float | None      # cumulative to this instant
    # SOLIT2 Annex 7 section 7.2.2 names CO and CO2 as life-safety quantities in
    # their own right, so the concentration is carried per station rather than
    # only reaching the run through the FED dose it contributes to.
    co_ppm: float | None = None
    co2_pct: float | None = None
    o2_pct: float | None = None
    relative_humidity_pct: float | None = None
    air_velocity_ms: float | None = None
    # Table 5 instruments 2 to 7 thermocouples per cross-section, not one. The
    # two tuples are the same length and in the same order, floor upwards;
    # `heights_m` is built once per run by `criteria.thermocouple_heights_m`.
    temps_c: tuple[float, ...] = ()
    heights_m: tuple[float, ...] = ()


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
    # Newman stratification factor of the smoke layer this step (1.0 = well mixed).
    # The spray does not change it; a step from a CFD run resolves the layer itself
    # and leaves this at 1.0.
    strat_factor: float = 1.0
    # Visibility at the downstream edge of the spray zone, at the opacimeter height. Not
    # an Annex 7 station (the standard puts none inside the zone), so it is reported and
    # never judged. None for a step from a CFD run, which has no such probe.
    zone_visibility_m: float | None = None


@dataclass(frozen=True)
class RunTrace:
    steps: tuple[StepRecord, ...]
    events: dict
    section: str
    velocity_ms: float

    def after(self, t_s: float) -> tuple[StepRecord, ...]:
        return tuple(s for s in self.steps if s.t_s >= t_s)

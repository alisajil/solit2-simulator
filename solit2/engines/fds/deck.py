"""Design -> FDS namelist text.

Deterministic by construction: the same `Design` always produces byte-identical
output, which is what makes golden-file testing possible. Geometry, the fire's
position and the station positions are taken from the Tier 1 modules rather
than recomputed, so both engines describe the same tunnel, burn the same fire
in the same place and measure the same points -- without that,
`solit2 report correlation` would be comparing two different experiments.

Everything the deck places is emitted ALREADY SNAPPED to the mesh (`_snap`,
`fuel_box`, `target_box`). FDS snaps obstruction bounds to the nearest cell
face on its own (User Guide, "Specified versus actual areas"), and a burner
whose HRRPUA was sized on the design footprint then releases HRRPUA x the
SNAPPED area -- not the design HRR. Doing the snapping here makes the emitted
area known, so HRRPUA can be normalised to it and the reader can report the
geometry FDS actually ran.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from functools import lru_cache

from solit2.engines.reduced import fire as fire_mod
from solit2.engines.reduced.envelope import _design_sha
from solit2.engines.reduced.fire import (DIESEL_HEAT_OF_COMBUSTION_MJKG,
                                         RADIATIVE_FRACTION_CLASS_A,
                                         RADIATIVE_FRACTION_CLASS_B,
                                         WOOD_HEAT_OF_COMBUSTION_MJKG)
from solit2.engines.reduced.geometry import SectionGeometry, fire_lateral_m, section_geometry
from solit2.engines.reduced.state import MistEffect
from solit2.engines.reduced.tenability import YIELDS
from solit2.schema.design import Design

# The fire sits at the origin of the measurement x-frame, the same frame
# `criteria.STATIONS` is written in.
FIRE_X_M = 0.0
# Wide enough to contain EVERY Annex 7 Table 5 station the criteria read --
# U340 to D215 -- because a station the deck does not measure is a KeyError
# inside `criteria._worst_station_value`, not a smaller result.
WINDOW_M = (-360.0, 240.0)
# The near-fire region the ceiling thermocouple line and the detection line
# cover. It no longer decides the mesh -- see DX_M.
CORE_M = (-60.0, 120.0)
# ONE cell size for the whole window, split into MESH_COUNT equal meshes along
# x for MPI. Nested meshes -- a fine core inside a coarse far field -- were
# built first and failed against a real FDS 6.11.1 run: the pressure solver
# pinned at its iteration cap every step without converging at the interfaces
# (velocity error 1-2 m/s in cold flow, ~9 m/s once the fire lit) and the run
# went numerically unstable at ignition, at a 3:1 ratio and again at 2:1. The
# User Guide lists "a change in grid resolution of more than a factor of 2 at
# a mesh interface" as a cause of instability; uniform meshes carrying the
# same fire converged in a few iterations. 0.6 m keeps D*/dx = 11.8 at 150 MW,
# inside the 10-16 band, at 221k cells; 0.5 m is one --dx away at 403k.
DX_M = 0.6
MESH_COUNT = 10              # one MPI rank per mesh; sized for an 11-core machine
# Lagrangian droplets inserted per head per second. FDS defaults to 5000, which
# on a 54-head deck inserts 270,000 droplets a second: a 66k-cell test case
# accumulated over a million of them, took ~4 GB, and decelerated toward a
# four-hour run it never finished -- at full scale that is not merely slow but
# close to infeasible.
#
# 1000 is chosen from a convergence study on an isolated 33k-cell case (fire
# from t=0, water from t=10 s, 60 s simulated), comparing 250 / 500 / 1000:
#
#   mean suppressed HRR   126,535 / 126,591 / 126,685 kW   (0.12% spread)
#   water evaporated       14.96 /  14.78 /  14.65 kg/s    (2.1%)
#   energy to droplets    -36,813 / -36,300 / -35,985 kW   (2.3%)
#   D15 heat flux            7.44 /   7.47 /   7.76 kW/m2  (4.3%)
#
# Three points over a 4x range agree to ~2% on everything and 0.12% on the
# suppression HRR the tier exists to compute, so the spray sampling is
# converged well below FDS's default. 250 would do, but the study also measured
# the cost -- 382 s / 414 s / 450 s -- so 4x the sampling costs 18%, not the
# steep climb assumed before measuring. 1000 therefore sits mid-range rather
# than at its edge, leaving margin for designs with fewer heads or coarser
# cells where 250 could sample too thinly, at a price worth paying.
PARTICLES_PER_SECOND = 1000
# FDS's Rosin-Rammler/lognormal spread parameter; its own default.
GAMMA_D = 2.4
CEILING_TC_SPACING_M = 5.0
CEILING_TC_PREFIX = "CEIL"
TARGET_GAUGE_ID = "TARGET_FLUX"
# Below the LOCAL ceiling -- see `ceiling_z_at`. The stair-stepped bore's crown
# is a full-width solid layer, so "crown minus an offset" is inside the wall.
CEILING_OFFSET_M = 0.15
DEVC_DT_S = 1.0
# FDS's VOLUME FRACTION is mol/mol. `max_co_ppm` is an Annex 7 life-safety
# criterion in ppm, so FDS is asked to emit ppm rather than the reader guessing
# at the unit -- without this the gate compares ~2e-4 against a limit of 500 and
# structurally cannot fail.
CO_PPM_CONVERSION = "1E6"
# O2 and CO2 are reported the way a test data sheet reports them, per cent by
# volume, rather than as FDS's mol/mol.
PERCENT_CONVERSION = "1E2"
# FDS requires a THICKNESS wherever a SURF names a MATL; without it the wall
# has a material and no heat capacity to apply it to.
WALL_THICKNESS_M = 0.30      # concrete lining
# FDS's extinguishing coefficient: the prescribed burner's HRRPUA is scaled by
# exp(-E * integral of water mass per unit area landing on it). It is the ONE
# parameter that decides how much the mist suppresses a prescribed fire, it is
# empirical, and 0.4 is a generic value not fitted to this nozzle or this fuel.
# The reader names it in every Tier 2 result for that reason.
E_COEFFICIENT = 0.4
# How finely the free-burn HRR curve is sampled into the fire ramps: every
# RAMP_GROWTH_SAMPLE_S while the fire grows, every RAMP_DECAY_SAMPLE_S after
# it has reached its plateau. The growth knees are added exactly on top.
RAMP_GROWTH_SAMPLE_S = 10.0
RAMP_DECAY_SAMPLE_S = 30.0
PUMP_RAMP_ID = "PUMP"
FREE_BURN_SUFFIX = "_free"
# FDS rejects any SURF using HRRPUA without a REAC line (ERROR 314): the fuel
# chemistry is what lets it balance the reaction and compute species transport,
# not merely a heat source. Formulas are generic surrogates -- cellulose for
# wood (Class A), heptane for diesel (Class B, close on heat of combustion:
# ~44.6 MJ/kg pure heptane against the 44.8 MJ/kg Tier 1 already assumes for
# diesel) -- common choices in published tunnel-fire FDS work, verified only to
# the extent that FDS accepts and runs them, not against a cited source.
# Heat of combustion and species yields are NOT surrogate guesses: they are the
# exact constants Tier 1's own fire.py/tenability.py use, so both tiers burn
# the same fuel.
_REAC_FORMULA = {"A": {"C": 3.4, "H": 6.2, "O": 2.5}, "B": {"C": 7.0, "H": 16.0}}
_REAC_HEAT_OF_COMBUSTION_MJKG = {"A": WOOD_HEAT_OF_COMBUSTION_MJKG,
                                 "B": DIESEL_HEAT_OF_COMBUSTION_MJKG}
# How much of the fire's energy leaves as radiation rather than convection. It
# decides every heat-flux reading and, through them, whether the target
# ignites. The deck used to leave it to FDS's own default, which happens to
# equal Tier 1's Class A figure and does NOT equal its Class B one -- so on a
# diesel pool the two tiers radiated differently and the agreement on wood was
# a coincidence. Taken from Tier 1's constants, like the heat of combustion and
# the species yields already are.
_REAC_RADIATIVE_FRACTION = {"A": RADIATIVE_FRACTION_CLASS_A,
                            "B": RADIATIVE_FRACTION_CLASS_B}


def chid(design: Design, suppression: bool = True) -> str:
    """FDS's CHID, which names every output file. The free-burn deck of the same
    design is a different run and must not overwrite the mist run's files."""
    sha = _design_sha(design)
    return sha if suppression else sha + FREE_BURN_SUFFIX


def _head(design: Design, suppression: bool) -> list[str]:
    title = design.meta.name if suppression else f"{design.meta.name} (free burn)"
    return [f"&HEAD CHID='{chid(design, suppression)}', TITLE='{title}' /", ""]


def _time(design: Design, t_end_s: float | None = None) -> list[str]:
    """`t_end_s` shortens the SIMULATION without touching the DESIGN.

    `zones.duration_min` is how long the system discharges, and it sizes the
    water tank (`hydraulics.size_system`) and the cost index. Editing it to cut
    a CFD run short would shrink the tank -- on a 2175 lpm system, 60 min to
    20 min takes it from 92.4 m3 to 30.8 m3 -- and break Annex 7 5.2.8's
    30-minute minimum discharge. The simulated window is a property of the
    run, not of the system, so it is a separate knob.
    """
    return [f"&TIME T_END={(t_end_s if t_end_s is not None else design.zones.duration_min * 60.0):.1f} /",
            f"&MISC TMPA={design.tunnel.ambient_temp_c:.1f} /",
            # One global pressure matrix across all meshes instead of FDS's
            # default block-wise FFT per mesh. A 600 m tunnel split into
            # MESH_COUNT pieces is one duct, and the default solver has to
            # iterate pressure across every interface to act like it: measured
            # on a 10-mesh proxy of this exact topology it hit its iteration
            # cap on half the steps and still left 0.4-0.7 m/s of velocity
            # error at the interfaces. UGLMAT converged in 1-8 iterations with
            # interface error at machine precision (~1e-15) and 24% less wall
            # time. Defaults to UGLMAT HYPRE, which needs no Intel MKL and so
            # also works in a native Apple-silicon build.
            "&PRES SOLVER='UGLMAT' /", ""]


def _mesh_extent(geom: SectionGeometry, dx_m: float) -> tuple[int, int]:
    """(j, k): whole cells across the WIDEST part of the section and up to the
    crown, rounded UP.

    The mesh is padded out to whole cells rather than clipped to the section,
    and `_tunnel` fills the padding with wall, so the solid boundary always
    lands exactly on a cell face.

    Across, this is the section's maximum width and not the carriageway's. A
    bored tunnel's deck is a chord below the centre, so the bore goes on
    widening above it: 11.00 m at centre height against a 10.15 m carriageway
    on the reference section. A mesh sized to the road clipped 0.8 m off the
    tunnel through its whole lower half, which was most of a 7.6 % free-area
    deficit against Tier 1.
    """
    return (math.ceil(geom.max_width_m / dx_m), math.ceil(geom.crown_height_m / dx_m))


def _y_origin(geom: SectionGeometry, dx_m: float) -> float:
    j, _ = _mesh_extent(geom, dx_m)
    return -j * dx_m / 2.0


def _snap(value: float, origin: float, dx_m: float) -> float:
    """The cell face nearest `value` on a grid of `dx_m` starting at `origin`.

    A value exactly between two faces rounds UP, so the same design always
    snaps the same way here -- FDS's own tie-break is not documented.
    """
    return origin + math.floor((value - origin) / dx_m + 0.5) * dx_m


@dataclass(frozen=True)
class Box:
    """An axis-aligned solid whose every bound lies on a cell face."""
    x0: float
    x1: float
    y0: float
    y1: float
    z0: float
    z1: float

    @property
    def top_area_m2(self) -> float:
        return (self.x1 - self.x0) * (self.y1 - self.y0)

    @property
    def y_centre_m(self) -> float:
        return (self.y0 + self.y1) / 2.0

    def xb(self) -> str:
        return (f"{self.x0:.2f},{self.x1:.2f},{self.y0:.2f},{self.y1:.2f},"
                f"{self.z0:.2f},{self.z1:.2f}")


def _snapped_box(x0: float, x1: float, y_centre: float, width_m: float, z0: float, z1: float,
                 geom: SectionGeometry, dx_m: float) -> Box:
    y_origin = _y_origin(geom, dx_m)
    bx0, bx1 = _snap(x0, WINDOW_M[0], dx_m), _snap(x1, WINDOW_M[0], dx_m)
    by0 = _snap(y_centre - width_m / 2.0, y_origin, dx_m)
    by1 = _snap(y_centre + width_m / 2.0, y_origin, dx_m)
    bz0, bz1 = _snap(z0, 0.0, dx_m), _snap(z1, 0.0, dx_m)
    # A dimension thinner than a cell would snap to nothing at all and FDS
    # would drop the obstruction; keep at least one cell of it.
    return Box(bx0, max(bx1, bx0 + dx_m), by0, max(by1, by0 + dx_m), bz0, max(bz1, bz0 + dx_m))


def fuel_box(design: Design, geom: SectionGeometry, dx_m: float = DX_M) -> Box:
    """The mock-up as the deck emits it: the design footprint at Tier 1's own
    lateral position (`fire_lateral_m`), snapped to the mesh."""
    fp = design.fire.footprint
    return _snapped_box(FIRE_X_M - fp.length_m / 2.0, FIRE_X_M + fp.length_m / 2.0,
                        fire_lateral_m(design, geom), fp.width_m,
                        fp.base_height_m, fp.top_height_m, geom, dx_m)


def target_box(design: Design, geom: SectionGeometry, dx_m: float = DX_M) -> Box:
    """The fire target, `target_distance_m` behind the mock-up's downstream end.

    Annex 7 5.2.6 gives the target the mock-up's width, height and
    combustibility and never states its along-tunnel length, so -- as the twin
    draws it -- the one figure the standard does state, the width, is used for
    the length too. It is a solid the flow has to go round, not a point.
    """
    fp = design.fire.footprint
    x0 = design.fire.target_x_m
    return _snapped_box(x0, x0 + fp.width_m, fire_lateral_m(design, geom), fp.width_m,
                        fp.base_height_m, fp.top_height_m, geom, dx_m)


def _meshes(geom: SectionGeometry, dx_m: float) -> list[str]:
    """MESH_COUNT equal meshes along x, all at one cell size -- see DX_M.

    Every mesh shares one y extent and one z extent, each a whole number of
    cells, so the interfaces are trivially aligned in all three directions and
    the stair-stepped bore is the same solid in every mesh.
    """
    x0, x1 = WINDOW_M
    nx = (x1 - x0) / dx_m
    if abs(nx - round(nx)) > 1e-9 or round(nx) % MESH_COUNT:
        raise ValueError(
            f"dx={dx_m} m does not tile the {x1 - x0:.0f} m window into "
            f"{MESH_COUNT} equal whole-cell meshes; 0.5 and 0.6 do")
    nx_each = round(nx) // MESH_COUNT
    span = (x1 - x0) / MESH_COUNT
    j, k = _mesh_extent(geom, dx_m)
    half_width, z_top = j * dx_m / 2.0, k * dx_m
    return [
        f"&MESH IJK={nx_each},{j},{k}, "
        f"XB={x0 + i * span:.1f},{x0 + (i + 1) * span:.1f},"
        f"{-half_width:.2f},{half_width:.2f},0.0,{z_top:.2f} /"
        for i in range(MESH_COUNT)
    ] + [""]


def _tunnel(geom: SectionGeometry, dx_m: float) -> list[str]:
    """Solid boundary. A box gets walls; a bore gets a stair-stepped ring."""
    x0, x1 = WINDOW_M
    # Fill from the section's real edge out to the mesh's padded edge, so the
    # wall lands on a cell face: the mesh is whole cells, the tunnel is not.
    j, k = _mesh_extent(geom, dx_m)
    half_width, z_top = j * dx_m / 2.0, k * dx_m
    real_half = geom.road_width_m / 2.0
    lines = [f"&SURF ID='WALL', DEFAULT=.TRUE., MATL_ID='CONCRETE', "
             f"THICKNESS={WALL_THICKNESS_M:.2f} /",
             "&MATL ID='CONCRETE', DENSITY=2280., CONDUCTIVITY=1.8, "
             "SPECIFIC_HEAT=1.04 /", ""]
    if geom.shape == "box":
        lines += [
            f"&OBST XB={x0:.1f},{x1:.1f},{-half_width:.2f},{-real_half:.2f},"
            f"0.0,{z_top:.2f}, SURF_ID='WALL' /",
            f"&OBST XB={x0:.1f},{x1:.1f},{real_half:.2f},{half_width:.2f},"
            f"0.0,{z_top:.2f}, SURF_ID='WALL' /",
            f"&OBST XB={x0:.1f},{x1:.1f},{-half_width:.2f},{half_width:.2f},"
            f"{geom.crown_height_m:.2f},{z_top:.2f}, SURF_ID='WALL' /",
        ]
        return lines + [""]
    # circle: one OBST pair per dx layer, each as wide as the bore is at that height
    for z_lo, z_hi, clear in _bore_layers(geom, dx_m):
        if clear >= half_width:
            continue
        lines += [
            f"&OBST XB={x0:.1f},{x1:.1f},{-half_width:.2f},{-clear:.2f},"
            f"{z_lo:.2f},{z_hi:.2f}, SURF_ID='WALL' /",
            f"&OBST XB={x0:.1f},{x1:.1f},{clear:.2f},{half_width:.2f},"
            f"{z_lo:.2f},{z_hi:.2f}, SURF_ID='WALL' /",
        ]
    return lines + [""]


def _bore_layers(geom: SectionGeometry, dx_m: float) -> list[tuple[float, float, float]]:
    """(z_lo, z_hi, clear half-width) for every dx layer of the stair-stepped bore."""
    # ceil, not int: the mesh is padded to whole cells above the crown, and the
    # top layer must be sealed (width_at(crown) is 0, so it is a full-width wall)
    steps = max(math.ceil(geom.crown_height_m / dx_m), 1)
    out = []
    for i in range(steps):
        z_lo = i * dx_m
        # The width that preserves this band's true open area, not the width at
        # one of its edges: taking the top edge made every step narrower than
        # the bore it stands for, by 2.85 m in the layer where the crown turns
        # over. See `SectionGeometry.mean_width_over`.
        z_top = (i + 1) * dx_m
        out.append((z_lo, z_top, geom.band_width_m(z_lo, z_top) / 2.0))
    return out


def ceiling_z_at(geom: SectionGeometry, y_m: float, dx_m: float = DX_M) -> float:
    """Height of a ceiling device at lateral position `y_m`: CEILING_OFFSET_M below
    the ceiling AS THE DECK EMITS IT, so the device sits in gas.

    For the stair-stepped bore the topmost layer is a full-width solid (the
    clear width at the crown is zero), so `crown_height_m - offset` lies INSIDE
    the wall. A thermocouple placed there read ambient for the whole of a real
    147 MW run while a station 5 m away read 1094 C -- the linear-heat
    detectors sat on the same line, never tripped, and the "mist" run was in
    fact a free burn. The ceiling that exists at `y_m` is the top of the
    highest layer still open there.
    """
    if geom.shape == "box":
        return geom.crown_height_m - CEILING_OFFSET_M
    open_tops = [z_hi for _, z_hi, clear in _bore_layers(geom, dx_m) if clear > abs(y_m)]
    if not open_tops:
        raise ValueError(f"y={y_m} m is outside the bore at every height")
    # Never above the real crown: the topmost slab runs past it, because the
    # mesh is whole cells and the crown is not.
    return min(max(open_tops), geom.crown_height_m) - CEILING_OFFSET_M


def gas_z_m(geom: SectionGeometry, y_m: float, z_m: float, dx_m: float = DX_M) -> float:
    """`z_m`, moved down into gas if the stair-stepped bore has walled it off.

    Tier 1 lays its thermocouple ladder out from the section's TRUE crown, but
    the deck emits a stair-stepped bore whose topmost layer is solid across the
    full width. On an 11 m bore the ladder's top rung lands at 7.25 m and the
    highest open layer at the centreline tops at 7.20 m, so five of the Annex 7
    stations had their uppermost thermocouple inside the lining: in a real run
    every one of them read exactly ambient for the whole 250 s while the rung
    below reached 80 C. A device the deck promises and then buries is worse
    than one it never placed, because it reports a number.
    """
    if geom.shape == "box":
        return min(z_m, max(geom.crown_height_m - CEILING_OFFSET_M, 0.0))
    open_tops = [z_hi for _, z_hi, clear in _bore_layers(geom, dx_m) if clear > abs(y_m)]
    if not open_tops:
        raise ValueError(f"y={y_m} m is outside the bore at every height")
    return min(z_m, min(max(open_tops), geom.crown_height_m) - CEILING_OFFSET_M)


def stepped_free_area_m2(geom: SectionGeometry, dx_m: float = DX_M) -> float:
    """Free area of the section AS THE DECK EMITS IT, not as Tier 1 defines it.

    These now agree. They did not: a mesh sized to the carriageway clipped the
    bore where it is widest, and every stair-step took its width at the top of
    its layer, together losing 7.6 % of the section. The mesh is sized to the
    section's widest point and each slab carries its band's true area, so the
    two engines model the same tunnel rather than one being asked to explain a
    deficit.

    Kept, and still reported, because it is a measurement of the emitted
    geometry rather than an assertion about it: if a future change to the mesh
    or the stepping reopens a gap, the result says so instead of the agreement
    being assumed.
    """
    if geom.shape == "box":
        return geom.road_width_m * geom.crown_height_m
    j, _ = _mesh_extent(geom, dx_m)
    half_width = j * dx_m / 2.0
    return sum(min(2.0 * clear, 2.0 * half_width) * (z_hi - z_lo)
               for z_lo, z_hi, clear in _bore_layers(geom, dx_m))


def _portals(design: Design) -> list[str]:
    """Longitudinal ventilation: forced inflow upstream, open downstream.

    FDS reads a NEGATIVE normal velocity on XMIN as flow INTO the domain.
    """
    u = design.ventilation.velocity_ms
    if u is None:
        u = max(design.ventilation.velocity_range_ms)
    return [f"&SURF ID='SUPPLY', VEL=-{u:.2f}, TMP_FRONT={design.tunnel.ambient_temp_c:.1f} /",
            "&VENT MB='XMIN', SURF_ID='SUPPLY' /",
            "&VENT MB='XMAX', SURF_ID='OPEN' /", ""]


def free_burn_curve(design: Design, horizon_s: float, dt_s: float = 1.0) -> list[tuple[float, float]]:
    """(t, fraction of the design HRR) for the UNSUPPRESSED fire, burnout included.

    Stepped with Tier 1's own fire model and no mist, so the deck's ramp IS
    Tier 1's `hrr_free_mw` curve: the t-squared growth, the plateau, and the
    decay once the pallets' energy is spent. The previous ramp held the design
    HRR to the end of the run -- 540 GJ over an hour from a 140 GJ fuel load.
    """
    model = fire_mod.build_model(design)
    state = fire_mod.initial_state(model)
    points = [(0.0, 0.0)]
    while state.t_s < horizon_s - 1e-9:
        state = fire_mod.step(model, state, dt_s, MistEffect.none())
        points.append((state.t_s, state.hrr_free_mw * 1000.0 / model.design_hrr_kw))
    return points


def _interp(points: list[tuple[float, float]], t: float) -> float:
    """Linear interpolation on a curve sampled at a fixed step from t=0."""
    if t <= points[0][0]:
        return points[0][1]
    if t >= points[-1][0]:
        return points[-1][1]
    step = points[1][0] - points[0][0]
    i = min(int(t / step), len(points) - 2)
    (t0, f0), (t1, f1) = points[i], points[i + 1]
    return f0 + (f1 - f0) * (t - t0) / (t1 - t0) if t1 > t0 else f0


def _crossing_times(points: list[tuple[float, float]], level: float, until_s: float) -> list[float]:
    """Every time the curve crosses `level` upward before `until_s`."""
    out = []
    for (t0, f0), (t1, f1) in zip(points, points[1:]):
        if t1 > until_s:
            break
        if f0 < level <= f1:
            out.append(t0 + (t1 - t0) * (level - f0) / (f1 - f0))
    return out


def segment_ramps(curve: list[tuple[float, float]], n_segments: int) -> list[list[tuple[float, float]]]:
    """Split one HRR curve into `n_segments` burner ramps that SUM to it exactly.

    The Annex 7 mock-up is lit at its upstream end and the fire spreads down
    the load; a single burner ramping everywhere at once puts flame over the
    downstream end -- 5 m from the target -- from the first second. Segment k
    (k = 0 upstream) carries clamp(N*F(t) - k, 0, 1) while the fire grows, so
    the segments light one after another from upstream to downstream and
    sum(F_k)/N == F(t) at every instant. Once the whole curve reaches its
    plateau every segment follows F(t) together, so burnout is uniform.

    This is a proxy for spread, not a pyrolysis model: how fast the front moves
    is dictated by the design growth curve, not predicted from the fuel.
    """
    if n_segments < 1:
        raise ValueError("a fire needs at least one segment")
    horizon = curve[-1][0]
    plateau_t = next((t for t, f in curve if f >= 1.0 - 1e-6), horizon)
    grid = {0.0, horizon}
    t = 0.0
    while t < plateau_t:
        grid.add(min(t, plateau_t))
        t += RAMP_GROWTH_SAMPLE_S
    grid.add(plateau_t)
    t = plateau_t
    while t < horizon:
        grid.add(t)
        t += RAMP_DECAY_SAMPLE_S
    ramps = []
    for k in range(n_segments):
        knees = (_crossing_times(curve, k / n_segments, plateau_t)
                 + _crossing_times(curve, (k + 1) / n_segments, plateau_t))
        # Whole seconds: FDS resamples every RAMP onto 5000 points (0.72 s apart
        # over an hour), so finer spacing is discarded and warned about.
        times = sorted({float(round(x)) for x in list(grid) + knees})

        def f_k(t_s: float) -> float:
            f = _interp(curve, t_s)
            if t_s <= plateau_t:
                return min(max(n_segments * f - k, 0.0), 1.0)
            return f

        sampled = [(x, round(f_k(x), 4)) for x in times]
        # Drop the interior of every constant run: a hundred F=0 points before
        # ignition say nothing a first and last point do not.
        kept = [sampled[0]]
        for prev, cur, nxt in zip(sampled, sampled[1:], sampled[2:]):
            if not (prev[1] == cur[1] == nxt[1]):
                kept.append(cur)
        if len(sampled) > 1:
            kept.append(sampled[-1])
        ramps.append(kept)
    return ramps


def _fire(design: Design, geom: SectionGeometry, dx_m: float, horizon_s: float) -> list[str]:
    """The unsuppressed fire as a sequence of burner segments; suppression is FDS's job.

    Tier 1 bakes suppression into its HRR curve because it has no droplets.
    Here the deck declares the FREE-BURN curve segment by segment and lets
    `E_COEFFICIENT` fall out of the water that actually lands on each.
    """
    f = design.fire
    box = fuel_box(design, geom, dx_m)
    n = round((box.x1 - box.x0) / dx_m) if f.fire_class == "A" else 1
    seg_len = (box.x1 - box.x0) / n
    # Normalised to the SNAPPED top face, so HRRPUA x emitted area == the design HRR.
    hrrpua = f.design_hrr_mw * 1000.0 / box.top_area_m2
    fuel = "WOOD" if f.fire_class == "A" else "DIESEL"
    formula_str = ", ".join(f"{el}={v}" for el, v in _REAC_FORMULA[f.fire_class].items())
    yields = YIELDS[f.fire_class]
    lines = [
        f"&REAC ID='{fuel}', FUEL='{fuel}', {formula_str}, "
        f"HEAT_OF_COMBUSTION={_REAC_HEAT_OF_COMBUSTION_MJKG[f.fire_class] * 1000.0:.1f}, "
        f"RADIATIVE_FRACTION={_REAC_RADIATIVE_FRACTION[f.fire_class]:.2f}, "
        f"SOOT_YIELD={yields['soot']:.3f}, CO_YIELD={yields['co']:.3f} /",
    ]
    for k in range(n):
        lines += [
            f"&SURF ID='FIRE{k}', HRRPUA={hrrpua:.1f}, RAMP_Q='FIRE_RAMP{k}', "
            f"E_COEFFICIENT={E_COEFFICIENT}, COLOR='RED' /",
            f"&OBST XB={box.x0 + k * seg_len:.2f},{box.x0 + (k + 1) * seg_len:.2f},"
            f"{box.y0:.2f},{box.y1:.2f},{box.z0:.2f},{box.z1:.2f}, "
            f"SURF_IDS='FIRE{k}','INERT','INERT' /",
        ]
    for k, ramp in enumerate(segment_ramps(free_burn_curve(design, horizon_s), n)):
        lines += [f"&RAMP ID='FIRE_RAMP{k}', T={t:.1f}, F={fr:.4f} /" for t, fr in ramp]
    return lines + [""]


def _target(design: Design, geom: SectionGeometry, dx_m: float) -> list[str]:
    """A solid target with the flux gauge ON its face toward the fire.

    Tier 1's `_target_ignited` judges the flux at the target's face, at half the
    fuel top height (`sim`: `fire_top_m / 2`). A gauge in free gas at a point
    the flow passes straight through is not that measurement; a solid the flow
    must go round, carrying a water-cooled gauge on its upstream face, is.
    FDS's boundary 'GAUGE HEAT FLUX' needs exactly such a solid to sit on
    (ERROR 427 without one), and IOR points from the face into the gas.
    """
    box = target_box(design, geom, dx_m)
    z = design.fire.footprint.top_height_m / 2.0
    z = min(max(z, box.z0 + dx_m / 2.0), box.z1 - dx_m / 2.0)
    ior = -1 if box.x0 > FIRE_X_M else 1
    face_x = box.x0 if ior < 0 else box.x1
    return [
        f"&OBST XB={box.xb()}, SURF_ID='INERT' /",
        f"&DEVC ID='{TARGET_GAUGE_ID}', XYZ={face_x:.2f},{box.y_centre_m:.2f},{z:.2f}, "
        f"QUANTITY='GAUGE HEAT FLUX', IOR={ior} /", "",
    ]


@lru_cache(maxsize=None)
def _dv50_over_d32(gamma_d: float) -> float:
    """Volume-median over Sauter-mean diameter for FDS's default drop distribution.

    FDS's `DIAMETER` is the volume median D_v,0.5 (User Guide, "Droplet size
    distribution"); the design records the Sauter mean D_32, the size that
    governs evaporation. FDS's cumulative volume fraction is lognormal below
    the median and Rosin-Rammler above it with sigma = 1.15/gamma, and
    D_32 = 1 / E_v[1/D], so the ratio depends on gamma alone. At the default
    2.4 it is 1.14: handing D_32 to FDS as DIAMETER runs a spray 12% finer than
    the one specified.
    """
    sigma = 1.15 / gamma_d

    def cdf(d: float) -> float:
        if d <= 1.0:
            return 0.5 * (1.0 + math.erf(math.log(d) / (math.sqrt(2.0) * sigma)))
        return 1.0 - math.exp(-0.693 * d ** gamma_d)

    n, lo, hi = 20000, 0.02, 6.0
    inverse_mean, prev = 0.0, cdf(lo)
    for i in range(1, n + 1):
        d = lo + (hi - lo) * i / n
        cur = cdf(d)
        inverse_mean += (cur - prev) / (d - (hi - lo) / (2 * n))
        prev = cur
    return round(inverse_mean, 4)     # D32 = 1/inverse_mean at Dv50 = 1


def volume_median_um(smd_um: float, gamma_d: float = GAMMA_D) -> float:
    return smd_um * _dv50_over_d32(gamma_d)


def _nozzles(design: Design, geom: SectionGeometry) -> list[str]:
    """One PART, one PROP, and one DEVC per head -- single-mode only."""
    from solit2.engines.reduced.geometry import nozzle_positions

    mode = design.nozzles.modes[0]
    smd_um = mode.smd_um or next(iter(design.nozzles.smd_table.values()))
    ramp_s = design.zones.pump_ramp_s
    flow_ramp = f"FLOW_RAMP='{PUMP_RAMP_ID}', " if ramp_s > 0 else ""
    lines = [
        "&SPEC ID='WATER VAPOR' /",
        f"&PART ID='FINE', SPEC_ID='WATER VAPOR', DIAMETER={volume_median_um(smd_um):.1f}, "
        f"GAMMA_D={GAMMA_D}, SAMPLING_FACTOR=10 /",
        f"&PROP ID='NOZ_FINE', PART_ID='FINE', "
        f"FLOW_RATE={design.nozzles.flow_per_head_lpm:.2f}, {flow_ramp}"
        f"SPRAY_ANGLE=0.0,{mode.cone_half_angle_deg:.1f}, "
        f"PARTICLE_VELOCITY={mode.launch_velocity_ms:.1f}, "
        f"PARTICLES_PER_SECOND={PARTICLES_PER_SECOND} /",
    ]
    if ramp_s > 0:
        # The pumps take `pump_ramp_s` to reach full pressure after the valves
        # open (Tier 1 `_flow_fraction`); FLOW_RAMP's clock starts at activation.
        lines += [f"&RAMP ID='{PUMP_RAMP_ID}', T=0.0, F=0.0 /",
                  f"&RAMP ID='{PUMP_RAMP_ID}', T={ramp_s:.1f}, F=1.0 /"]
    tilt = math.radians(design.nozzles.mounting.tilt_deg)
    for i, pos in enumerate(nozzle_positions(design, geom, FIRE_X_M)):
        lines.append(
            # QUANTITY='CONTROL' + CTRL_ID is FDS's form for a head opened by an
            # external control (see its own Verification/Sprinklers_and_Sprays/
            # activate_sprinklers.fds). The earlier QUANTITY='TIME', SETPOINT=0.0
            # self-triggered every head at t=0 regardless of CTRL_ID: a real run
            # had 22,781 droplets in one mesh by t=0.5 s, with detection and the
            # activation delay never applied, which makes suppression look
            # instant. LATCH keeps a zone open once it has opened.
            f"&DEVC ID='NOZ{i}', XYZ={pos.x_m:.2f},{pos.y_m:.2f},{pos.z_m:.2f}, "
            f"PROP_ID='NOZ_FINE', QUANTITY='CONTROL', LATCH=.TRUE., "
            f"ORIENTATION=0.0,{math.sin(tilt):.3f},{-math.cos(tilt):.3f}, "
            f"CTRL_ID='ACT' /"
        )
    return lines + [""]


def detector_x_m(design: Design) -> list[float]:
    """Where the linear-heat sensors sit along the core, from its upstream end at
    the design's own spacing -- shared with the twin so the picture shows the
    sensors the deck actually measures with."""
    x0, x1 = CORE_M
    n = int((x1 - x0) / design.detection.sensor_spacing_m)
    return [x0 + i * design.detection.sensor_spacing_m for i in range(n)]


def _detection(design: Design, geom: SectionGeometry, dx_m: float) -> list[str]:
    """Linear heat detection along the ceiling crown, then the activation delay.

    Over the core only: detection that matters is detection near the fire, and
    a sensor 300 m up the approach tunnel would never be the one that trips.
    The cable runs at the tunnel's centre, as an installed cable does, which
    with an eccentric fire is the later-tripping (conservative) position.
    """
    z = ceiling_z_at(geom, 0.0, dx_m)
    lines = []
    xs = detector_x_m(design)
    n = len(xs)
    for i, x in enumerate(xs):
        lines.append(
            f"&DEVC ID='LHD{i}', XYZ={x:.2f},0.0,{z:.2f}, "
            f"QUANTITY='THERMOCOUPLE', SETPOINT={design.detection.threshold_c:.1f} /"
        )
    lines += [
        f"&CTRL ID='DETECT', FUNCTION_TYPE='ANY', "
        f"INPUT_ID={','.join(repr(f'LHD{i}') for i in range(n))} /",
        f"&CTRL ID='ACT', FUNCTION_TYPE='TIME_DELAY', INPUT_ID='DETECT', "
        f"DELAY={design.zones.activation_delay_s:.1f} /",
    ]
    return lines + [""]


def fire_ceiling_device_id() -> str:
    """The ceiling thermocouple directly above the fire.

    `_stations` lays the ceiling line out from CORE_M[0] in CEILING_TC_SPACING_M
    steps, so the device over the fire is that offset divided by the spacing.
    The MIDDLE of the line is not it: the line is not centred on the fire, and
    on the current window the midpoint sits 30 m downstream of it.
    """
    return f"{CEILING_TC_PREFIX}{int((FIRE_X_M - CORE_M[0]) / CEILING_TC_SPACING_M)}"


def _gauge_orientation(x_m: float) -> str:
    """Unit vector from a gauge toward the fire, on the x-axis.

    The Table 5 station gauges stand in free gas where a person would, so they
    are the gas-phase GAUGE HEAT FLUX GAS with an ORIENTATION -- the sensing
    face's outward normal -- rather than a boundary quantity needing a solid.
    """
    return "1.0,0.0,0.0" if FIRE_X_M > x_m else "-1.0,0.0,0.0"


# Table 5 counts its gas and velocity instruments per cross-section; the
# criteria only ever read one value from each, so the deck used to emit one.
# A real test records the whole profile, and a Tier 2 result that cannot be set
# beside a test data sheet column for column is harder to check than it needs
# to be. These carry their own IDs and nothing reads them: they exist to be
# compared against measurements.
_SPECIES_PROFILE = (("O2", "OXYGEN"), ("CO2", "CARBON DIOXIDE"), ("COP", "CARBON MONOXIDE"))
# A cross-section carrying at least this many thermocouples gets a second tree
# in the plane of the fuel load -- see `_table_5_profiles`.
LOAD_SIDE_TREE_MIN_TC = 5


def _table_5_profiles(name: str, kit, x_m: float, geom: SectionGeometry,
                      dx_m: float, load_y_m: float) -> list[str]:
    """Every instrument Table 5 counts at this station, at its own count.

    Annex 7 gives counts, never heights -- the same silence as for the
    thermocouples -- so these reuse `thermocouple_heights_m`, the ladder this
    engine already documents as its own engineering choice, at each
    instrument's own count. One rule for every instrument beats a second
    invented one.
    """
    from solit2.engines.reduced.criteria import BREATHING_HEIGHT_M, thermocouple_heights_m
    lines = []
    if kit.oxygen or kit.carbon_dioxide or kit.carbon_monoxide:
        counts = {"O2": kit.oxygen, "CO2": kit.carbon_dioxide, "COP": kit.carbon_monoxide}
        for tag, species in _SPECIES_PROFILE:
            count = counts[tag]
            unit, factor = (("ppm", CO_PPM_CONVERSION) if tag == "COP"
                            else ("%", PERCENT_CONVERSION))
            for rung, z in enumerate(thermocouple_heights_m(count, geom.crown_height_m)
                                     if count else ()):
                lines.append(
                    f"&DEVC ID='{name}_{tag}_{rung}', XYZ={x_m:.2f},0.0,"
                    f"{gas_z_m(geom, 0.0, z, dx_m):.2f}, QUANTITY='VOLUME FRACTION', "
                    f"SPEC_ID='{species}', CONVERSION_FACTOR={factor}, UNITS='{unit}' /")
    for rung, z in enumerate(thermocouple_heights_m(kit.bidirectional, geom.crown_height_m)
                             if kit.bidirectional else ()):
        lines.append(f"&DEVC ID='{name}_UBI_{rung}', XYZ={x_m:.2f},0.0,"
                     f"{gas_z_m(geom, 0.0, z, dx_m):.2f}, QUANTITY='U-VELOCITY' /")
    if kit.relative_humidity:
        lines.append(f"&DEVC ID='{name}_RH', XYZ={x_m:.2f},0.0,{BREATHING_HEIGHT_M:.2f}, "
                     f"QUANTITY='RELATIVE HUMIDITY' /")
    if kit.reference_thermocouple:
        # Table 5 lists it on its own line, beside the humidity probe: an RH
        # reading means nothing without the temperature it was taken at.
        lines.append(f"&DEVC ID='{name}_TCREF', XYZ={x_m:.2f},0.0,{BREATHING_HEIGHT_M:.2f}, "
                     f"QUANTITY='THERMOCOUPLE' /")
    if kit.thermocouples >= LOAD_SIDE_TREE_MIN_TC and abs(load_y_m) > dx_m:
        # A second tree in the plane of the fuel load. Annex 7 gives counts and
        # cross-sections and never a lateral position, and Tier 1 resolves none
        # at all -- it models a vertical profile, not a lateral one -- so the
        # criteria stay on the centreline, which is the only place the two
        # tiers can be compared. That left the result silent about a real and
        # large gradient: measured on a 6.8 MW run, the ceiling over the load
        # read 133 C against 78 C on the centreline at the same station.
        # These rungs record it. Nothing reads them and no criterion moves.
        for rung, z in enumerate(thermocouple_heights_m(kit.thermocouples,
                                                        geom.crown_height_m)):
            lines.append(
                f"&DEVC ID='{name}_TCL{rung}', XYZ={x_m:.2f},{load_y_m:.2f},"
                f"{gas_z_m(geom, load_y_m, z, dx_m):.2f}, QUANTITY='THERMOCOUPLE' /")
    return lines


def _stations(design: Design, geom: SectionGeometry, dx_m: float) -> list[str]:
    """Annex 7 Table 5, device by device, plus the ceiling line a simulation needs."""
    from solit2.engines.reduced.criteria import (BREATHING_HEIGHT_M, HEAT_FLUX_HEIGHT_M,
                                                 INSTRUMENTS, STATIONS,
                                                 VISIBILITY_HEIGHT_M,
                                                 thermocouple_heights_m)
    lines = []
    load_y_m = fuel_box(design, geom, dx_m).y_centre_m
    for name, x_m in sorted(STATIONS.items(), key=lambda kv: kv[1]):
        if not (WINDOW_M[0] <= x_m <= WINDOW_M[1]):
            continue
        kit = INSTRUMENTS[name]
        heights = thermocouple_heights_m(kit.thermocouples, geom.crown_height_m)
        for rung, z in enumerate(heights):
            lines.append(f"&DEVC ID='{name}_TC{rung}', "
                        f"XYZ={x_m:.2f},0.0,{gas_z_m(geom, 0.0, z, dx_m):.2f}, "
                        f"QUANTITY='THERMOCOUPLE' /")
        if kit.heat_flux:
            lines.append(
                f"&DEVC ID='{name}_HF', XYZ={x_m:.2f},0.0,{HEAT_FLUX_HEIGHT_M:.2f}, "
                f"QUANTITY='GAUGE HEAT FLUX GAS', ORIENTATION={_gauge_orientation(x_m)} /")
        if kit.visibility:
            lines.append(
                f"&DEVC ID='{name}_VIS', XYZ={x_m:.2f},0.0,{VISIBILITY_HEIGHT_M:.2f}, "
                f"QUANTITY='VISIBILITY' /")
        if kit.toxic_gas:
            lines += [
                f"&DEVC ID='{name}_CO', XYZ={x_m:.2f},0.0,{BREATHING_HEIGHT_M:.2f}, "
                f"QUANTITY='VOLUME FRACTION', SPEC_ID='CARBON MONOXIDE', "
                f"CONVERSION_FACTOR={CO_PPM_CONVERSION}, UNITS='ppm' /",
                f"&DEVC ID='{name}_FED', XYZ={x_m:.2f},0.0,{BREATHING_HEIGHT_M:.2f}, "
                f"QUANTITY='FED' /",
            ]
        if kit.air_velocity:
            lines.append(
                f"&DEVC ID='{name}_U', XYZ={x_m:.2f},0.0,{BREATHING_HEIGHT_M:.2f}, "
                f"QUANTITY='U-VELOCITY' /")
        lines += _table_5_profiles(name, kit, x_m, geom, dx_m, load_y_m)
    # Ceiling line over the core for the lining temperature and the exposed
    # length: OVER THE FUEL LOAD, at the ceiling that exists there, not at the
    # crown centre 2-3 m to the side of an eccentric plume.
    x0, x1 = CORE_M
    y = fuel_box(design, geom, dx_m).y_centre_m
    z = ceiling_z_at(geom, y, dx_m)
    for i in range(int((x1 - x0) / CEILING_TC_SPACING_M)):
        x = x0 + i * CEILING_TC_SPACING_M
        lines.append(f"&DEVC ID='{CEILING_TC_PREFIX}{i}', XYZ={x:.2f},{y:.2f},{z:.2f}, "
                    f"QUANTITY='THERMOCOUPLE' /")
    return lines + [""]


def _output(design: Design, geom: SectionGeometry, dx_m: float, suppression: bool) -> list[str]:
    # Constant-y slices THROUGH THE FIRE feed the twin canvas: gas temperature
    # and axial velocity, soot density for the smoke layer, and -- when there is
    # a mist system in the deck -- the water mass per unit volume of the FINE
    # particle class for the mist layer.
    y = fuel_box(design, geom, dx_m).y_centre_m
    lines = [f"&DUMP DT_DEVC={DEVC_DT_S:.1f}, DT_HRR={DEVC_DT_S:.1f} /",
             f"&SLCF PBY={y:.2f}, QUANTITY='TEMPERATURE' /",
             f"&SLCF PBY={y:.2f}, QUANTITY='U-VELOCITY' /",
             # FDS 6.11 has no 'SOOT DENSITY' quantity (ERROR 1042 in a real run):
             # a species' mass per unit volume is 'DENSITY' with its SPEC_ID.
             f"&SLCF PBY={y:.2f}, QUANTITY='DENSITY', SPEC_ID='SOOT' /"]
    if suppression:
        lines.append(f"&SLCF PBY={y:.2f}, QUANTITY='MPUV', PART_ID='FINE' /")
    return lines + [""]


def _without_run_window(text: str) -> str:
    """The deck minus the one line a shortened run is allowed to differ on."""
    return "\n".join(ln for ln in text.splitlines() if not ln.startswith("&TIME "))


def matches_design(run_dir: Path, design: Design) -> bool | None:
    """Whether a run's own deck is still the deck this design generates.

    None when the run kept no deck to compare. The design's sha names the run
    directory, so a run made BEFORE a change to this module keeps its name and
    reads as current while describing a different experiment -- which is how a
    result gets attributed to geometry it never simulated. `T_END` is excluded
    because a deliberately shortened window is not a different deck.
    """
    deck_path = Path(run_dir) / "deck.fds"
    if not deck_path.exists():
        return None
    try:
        stored = deck_path.read_text()
    except OSError:
        return None
    # Which variant this run is, from its own CHID rather than from a substring
    # that a design's title could also carry.
    head = stored.split("\n", 1)[0]
    suppression = f"CHID='{chid(design, suppression=False)}'" not in head
    return (_without_run_window(stored)
            == _without_run_window(generate(design, suppression=suppression)))


def generate(design: Design, dx_m: float = DX_M,
             t_end_s: float | None = None, *, suppression: bool = True) -> str:
    """The deck. `suppression=False` is the SAME fire in the SAME tunnel with no
    mist system at all -- the free-burn reference the mist run is judged against."""
    geom = section_geometry(design)
    duration_s = design.zones.duration_min * 60.0
    horizon_s = max(duration_s, t_end_s or 0.0)
    blocks = (_head(design, suppression) + _time(design, t_end_s) + _meshes(geom, dx_m)
              + _tunnel(geom, dx_m) + _portals(design) + _fire(design, geom, dx_m, horizon_s)
              + _target(design, geom, dx_m)
              + (_nozzles(design, geom) if suppression else [])
              + _detection(design, geom, dx_m)
              + _stations(design, geom, dx_m) + _output(design, geom, dx_m, suppression)
              + ["&TAIL /"])
    return "\n".join(blocks)

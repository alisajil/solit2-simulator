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
import re
from dataclasses import dataclass
from pathlib import Path
from functools import lru_cache

from solit2.engines.reduced import fire as fire_mod
from solit2.engines.reduced.envelope import design_sha
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
# Cells are DX_M across and up everywhere. Along x they are DX_M inside
# FIRE_X_M +- FINE_HALF_LENGTH_M and COARSE_FACTOR x DX_M beyond it.
#
# A fine core in a coarse far field was built once before and failed against
# a real FDS 6.11.1 run: the pressure solver pinned at its iteration cap every
# step without converging at the interfaces (velocity error 1-2 m/s in cold
# flow, ~9 m/s once the fire lit) and the run went unstable at ignition, at
# 3:1 and again at 2:1. That was under FDS's default block-wise FFT solver,
# which reconciles interfaces by iteration. The deck now asks for UGLMAT (see
# `_time`), which the 6.11.1 User Guide Sec. 21.1 lists as the solver that
# "allows stretching and refinement" with the normal velocity at mesh
# boundaries exact (Table 21.1). Measured on this deck: one pressure iteration
# per step in both layouts, and over 20 s of cold flow no station more than
# 5 % from the uniform mesh.
#
# Why bother: wall time per step follows the LARGEST mesh, not the cell total,
# because every rank waits for the slowest at each step. Ten uniform 60 m
# meshes carried 24,700 cells each; this split's largest carries 17,784, and
# the same 20 s deck went from 119 s to 90 s on the same ten ranks.
#
# Refinement is along x only. Across and up the cells stay DX_M, so a
# head-height reading at the far stations still sits in a 0.6 m cell
# vertically, and an integer ratio in every direction keeps the coarse
# lattice a subset of the fine one, which is what a conforming interface
# needs. The factor is 2 because the User Guide names a change of more than a
# factor of 2 at an interface as a cause of instability. 0.5 m keeps
# D*/dx = 14.2 at 150 MW in the fine region, inside the 10-16 band.
#
# Why 0.5 and not 0.6: the Annex 7 positions are metres on a 0.5 grid. At 0.6 m
# the mock-up snapped to 9.6 m long (ends at +-4.8, not U5/D5) and the target
# face to 10.2 m, a 5.4 m gap against the standard's 5.0. At 0.5 m the mock-up
# ends, the target face and the mock-up's height all land exactly; the one
# thing that does not is the 2.4 m width, which snaps to 2.0 m (HRRPUA is
# normalised to the snapped face, so the total HRR is unchanged). 0.25 m would
# fit the width too, at about 14x the cells of 0.6 m.
DX_M = 0.5
FINE_HALF_LENGTH_M = 108.0   # every station within +-100 m stays in fine cells
COARSE_FACTOR = 2
# Meshes per region -- upstream coarse, fine, downstream coarse -- one MPI
# rank each. (3, 5, 2) puts 17,290 / 17,784 / 13,585 cells on a rank at 0.6 m
# (about 1.7x that at 0.5 m)
# and keeps the fire mid-mesh: the old uniform split had an interface at x=0,
# through the fuel bed.
# Meshes within a region differ by at most one cell along x when the region's
# cell count does not divide, so any dx that tiles the three regions in whole
# cells is accepted: 0.25, 0.5, 0.6, 0.75, 1.0 and 1.2 m all do.
MESH_SPLIT = (3, 5, 2)
MESH_COUNT = sum(MESH_SPLIT)  # one MPI rank per mesh; sized for an 11-core machine
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
# How often FDS writes restart files, in simulated seconds. Its own default is
# effectively never, which means a run stopped by anything other than a
# graceful stop has to start again from zero. Each set overwrites the last, so
# the cost is bounded disk rather than growing disk, and on a run where a
# simulated second takes tens of wall seconds this is a checkpoint every
# several minutes.
DT_RESTART_S = 60.0
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
    sha = design_sha(design)
    return sha if suppression else sha + FREE_BURN_SUFFIX


def _head(design: Design, suppression: bool) -> list[str]:
    title = design.meta.name if suppression else f"{design.meta.name} (free burn)"
    return [f"&HEAD CHID='{chid(design, suppression)}', TITLE='{title}' /", ""]


def _time(design: Design, t_end_s: float | None = None, restart: bool = False) -> list[str]:
    """`t_end_s` shortens the SIMULATION without touching the DESIGN.

    `restart` adds FDS's own `RESTART=.TRUE.`, which picks the run up from the
    restart files it last wrote rather than starting again from zero.

    `zones.duration_min` is how long the system discharges, and it sizes the
    water tank (`hydraulics.size_system`) and the cost index. Editing it to cut
    a CFD run short would shrink the tank -- on a 2175 lpm system, 60 min to
    20 min takes it from 92.4 m3 to 30.8 m3 -- and break Annex 7 5.2.8's
    30-minute minimum discharge. The simulated window is a property of the
    run, not of the system, so it is a separate knob.
    """
    restart_flag = ", RESTART=.TRUE." if restart else ""
    return [f"&TIME T_END={(t_end_s if t_end_s is not None else design.zones.duration_min * 60.0):.1f} /",
            f"&MISC TMPA={design.tunnel.ambient_temp_c:.1f}{restart_flag} /",
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


def _load_y_bounds(design: Design, geom: SectionGeometry, dx_m: float) -> tuple[float, float]:
    """(y0, y1) of the mock-up and the target, snapped to the mesh.

    The near face goes to the nearest node, which keeps the wall clearance as
    close to the design's as the mesh allows: 1.3 m becomes 1.5 m at 0.5 m cells.
    Annex 7 5.2.3's text says "less than 1,5 m" and Fig 13 says "max 1.5m"; 1.5 m
    is the limit itself, so the report should say the load sits AT it. The width
    is rounded UP to whole cells: 5.2.2 gives 2.4 m as a minimum, and 2.0 m
    would be below it.
    """
    origin = _y_origin(geom, dx_m)
    yc, width = fire_lateral_m(design, geom), design.fire.footprint.width_m
    y0 = origin + math.floor((yc - width / 2.0 - origin) / dx_m + 0.5) * dx_m
    return y0, y0 + max(math.ceil(width / dx_m - 1e-9), 1) * dx_m


def fuel_box(design: Design, geom: SectionGeometry, dx_m: float = DX_M) -> Box:
    """The mock-up as the deck emits it: the design footprint near Tier 1's own
    lateral position (`fire_lateral_m`), snapped to the mesh."""
    fp = design.fire.footprint
    base = _snapped_box(FIRE_X_M - fp.length_m / 2.0, FIRE_X_M + fp.length_m / 2.0,
                        fire_lateral_m(design, geom), fp.width_m,
                        fp.base_height_m, fp.top_height_m, geom, dx_m)
    y0, y1 = _load_y_bounds(design, geom, dx_m)
    return Box(base.x0, base.x1, y0, y1, base.z0, base.z1)


def cover_box(design: Design, geom: SectionGeometry, dx_m: float = DX_M) -> Box | None:
    """The tarpaulin as a zero-thickness inert plate, one cell ABOVE the fuel top.

    Zero thickness because that is what FDS offers for a thin sheet, and because
    a one-cell slab does not fit: in the SOLIT2 test tunnel there is 1.0 m between
    the fuel top and the ceiling, and the heads hang in it.

    ponytail: a flat plate, no side skirts, and it never burns or melts. The real
    PVC drapes the sides and gives way in a hot fire; this only stops water
    falling straight onto the fuel, which is the effect Annex 7 5.2.2 cares
    about. Skirts / burn-through if a comparison shows the sides matter.

    The gap is not optional: FDS drops a burner face that borders another
    solid, so a cover laid ON the fuel top would put the fire out.
    """
    if not design.fire.covered:
        return None
    fuel = fuel_box(design, geom, dx_m)
    z = fuel.z1 + dx_m
    ceiling = min(ceiling_z_at(geom, y, dx_m) for y in (fuel.y0, fuel.y1))
    if z >= ceiling:
        raise ValueError(
            f"the tarpaulin cover does not fit: it would sit at {z:.2f} m but the "
            f"ceiling over the mock-up is at {ceiling:.2f} m")
    # One cell of margin all round: the real tarpaulin (10.5 x 7.5 m over a
    # 10.0 x 2.4 m load) overhangs and drapes the sides, and a quarter-metre
    # overhang is below the mesh, where it would snap unpredictably.
    return Box(fuel.x0 - dx_m, fuel.x1 + dx_m, fuel.y0 - dx_m, fuel.y1 + dx_m, z, z)


def has_target(design: Design) -> bool:
    """Annex 7 5.2.6 sites a fire target for Class A fires only."""
    return design.fire.has_target


def target_box(design: Design, geom: SectionGeometry, dx_m: float = DX_M) -> Box:
    """The fire target, `target_distance_m` behind the mock-up's downstream end.

    Annex 7 5.2.6 gives the target the mock-up's width, height and
    combustibility and never states its along-tunnel length, so -- as the twin
    draws it -- the one figure the standard does state, the width, is used for
    the length too. It is a solid the flow has to go round, not a point.
    """
    fp = design.fire.footprint
    x0 = design.fire.target_x_m
    base = _snapped_box(x0, x0 + fp.width_m, fire_lateral_m(design, geom), fp.width_m,
                        fp.base_height_m, fp.top_height_m, geom, dx_m)
    y0, y1 = _load_y_bounds(design, geom, dx_m)
    return Box(base.x0, base.x1, y0, y1, base.z0, base.z1)


def _x_regions(dx_m: float) -> list[tuple[float, float, float, int]]:
    """(x0, x1, dx, mesh count) for the upstream coarse, fine and downstream
    coarse regions, each checked to be a whole number of its cells long.

    A cell size that does not tile is refused with the reason. The window and
    the fine band are fixed, so this is a property of dx alone.
    """
    x0, x1 = WINDOW_M
    fine_lo, fine_hi = FIRE_X_M - FINE_HALF_LENGTH_M, FIRE_X_M + FINE_HALF_LENGTH_M
    coarse = COARSE_FACTOR * dx_m
    regions = [(x0, fine_lo, coarse, MESH_SPLIT[0]),
               (fine_lo, fine_hi, dx_m, MESH_SPLIT[1]),
               (fine_hi, x1, coarse, MESH_SPLIT[2])]
    for r0, r1, dx, _ in regions:
        n = (r1 - r0) / dx
        if abs(n - round(n)) > 1e-9:
            raise ValueError(
                f"dx={dx_m} m does not tile the {r0:.0f}..{r1:.0f} m region in whole "
                f"cells of {dx:g} m; 0.25, 0.5, 0.6, 0.75, 1.0 and 1.2 do")
    return regions


def _mesh_cells(n_cells: int, count: int) -> list[int]:
    """`n_cells` shared over `count` meshes, the first `n_cells % count` of them
    one cell longer. A one-cell difference is a rounding error in load; a
    divisibility rule would have refused half the useful cell sizes."""
    base, extra = divmod(n_cells, count)
    return [base + (1 if i < extra else 0) for i in range(count)]


def _meshes(geom: SectionGeometry, dx_m: float) -> list[str]:
    """One &MESH per rank: fine around the fire, coarser along x beyond -- see
    FINE_HALF_LENGTH_M.

    Every mesh shares one y extent and one z extent, each a whole number of
    DX_M cells, so the interfaces are aligned across and up and the
    stair-stepped bore is the same solid in every mesh. Along x the coarse
    edges fall on the fine lattice because COARSE_FACTOR is an integer.
    """
    j, k = _mesh_extent(geom, dx_m)
    half_width, z_top = j * dx_m / 2.0, k * dx_m
    lines = []
    for r0, r1, dx, count in _x_regions(dx_m):
        mx0 = r0
        for nx in _mesh_cells(round((r1 - r0) / dx), count):
            lines.append(f"&MESH IJK={nx},{j},{k}, "
                         f"XB={mx0:.1f},{mx0 + nx * dx:.1f},"
                         f"{-half_width:.2f},{half_width:.2f},0.0,{z_top:.2f} /")
            mx0 += nx * dx
    return lines + [""]


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


def clear_of_solids_z_m(z_m: float, x_m: float, y_m: float, solids: tuple[Box, ...],
                        ceiling_z_m: float, dx_m: float = DX_M) -> float | None:
    """`z_m` lifted just above any solid it lands in; None if it cannot clear one.

    A Class B pool sits on the floor and spans the centreline, so the lowest
    rung of an Annex 7 ladder lands inside the burning fuel. The ladder's COUNT
    is contractual -- the reader reads rungs 0..n-1 by name -- so a buried rung
    is moved rather than dropped, and only reported missing if there is no room
    above the solid at all.
    """
    for _ in range(len(solids) + 1):
        inside = next((b for b in solids
                       if b.x0 <= x_m <= b.x1 and b.y0 <= y_m <= b.y1 and b.z0 <= z_m <= b.z1),
                      None)
        if inside is None:
            return z_m if z_m <= ceiling_z_m else None
        z_m = inside.z1 + dx_m / 2.0
    return None


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


def _fire(design: Design, geom: SectionGeometry, dx_m: float, horizon_s: float,
          e_coefficient: float) -> list[str]:
    """The unsuppressed fire as a sequence of burner segments; suppression is FDS's job.

    Tier 1 bakes suppression into its HRR curve because it has no droplets.
    Here the deck declares the FREE-BURN curve segment by segment and lets
    `e_coefficient` fall out of the water that actually lands on each.
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
            f"E_COEFFICIENT={e_coefficient}, COLOR='RED' /",
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
    if not has_target(design):
        return []
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


def _cover(design: Design, geom: SectionGeometry, dx_m: float) -> list[str]:
    roof = cover_box(design, geom, dx_m)
    return [] if roof is None else [f"&OBST XB={roof.xb()}, SURF_ID='INERT' /", ""]


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
    lines.append(f"&CTRL ID='DETECT', FUNCTION_TYPE='ANY', "
                 f"INPUT_ID={','.join(repr(f'LHD{i}') for i in range(n))} /")
    manual = design.zones.manual_activation_s
    if manual is None:
        lines.append(f"&CTRL ID='ACT', FUNCTION_TYPE='TIME_DELAY', INPUT_ID='DETECT', "
                     f"DELAY={design.zones.activation_delay_s:.1f} /")
    else:
        # Started by hand at a clock time, as Tier 1 does (sim._detect): the
        # detector still trips and is still logged, but it does not open the
        # heads. A TIME device needs a point in the gas; the first detector's is one.
        lines += [
            f"&DEVC ID='MANUAL', QUANTITY='TIME', XYZ={xs[0]:.2f},0.0,{z:.2f}, "
            f"SETPOINT={manual:.1f} /",
            "&CTRL ID='ACT', FUNCTION_TYPE='ANY', INPUT_ID='MANUAL' /",
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
# A cross-section carrying at least this many thermocouples is laid out the way
# Annex 7 Figure 16 lays one out -- see `_figure_16_positions`.
LOAD_SIDE_TREE_MIN_TC = 5
# Annex 7 section 6.4.10 names a measurement "<type>-<location>-<position>",
# e.g. TC-D40-01: thermocouple, at D40, cross-section position 1. These are
# that scheme's type codes, for the devices laid out to Figure 16.
ANNEX7_TYPE_CODES = {"thermocouple": "TC", "heat_flux": "HF", "gas": "GA",
                     "visibility": "VI", "anemometer": "AN"}


def _inside_any(x_m: float, y_m: float, z_m: float, boxes: tuple[Box, ...]) -> bool:
    """Is this point inside one of the deck's own solid blocks?"""
    return any(b.x0 <= x_m <= b.x1 and b.y0 <= y_m <= b.y1 and b.z0 <= z_m <= b.z1
               for b in boxes)


def annex7_id(type_key: str, station: str, position: int) -> str:
    """Annex 7 section 6.4.10's own identifier, e.g. `TC-D05-01`."""
    return f"{ANNEX7_TYPE_CODES[type_key]}-{station}-{position:02d}"


def _figure_16_positions(station: str, kit, x_m: float, geom: SectionGeometry,
                         dx_m: float, fuel: Box, solids: tuple[Box, ...]) -> list[str]:  # noqa: D401
    """The cross-section laid out as Annex 7 Figure 16 draws it.

    Figure 16 numbers seven thermocouples round a cross-section, and it is not
    the vertical rake on the centreline that this engine's own ladder builds:

        01, 02   left side wall, at the fuel's base and top heights
        03       ceiling, on the centreline
        04, 05   right side wall, at the fuel's top and base heights
        06       beside the load at its platform level
        07       just above the load's top

    A five-thermocouple section gets 01 to 05, the walls and the ceiling.

    HEIGHTS ARE READ OFF THE FIGURE'S STRUCTURE, NOT OFF DIMENSIONS. Figure 16
    is schematic and carries no numbers. What it does show unambiguously is
    what each sensor is keyed TO -- the wall pairs bracket the load between its
    platform and its top, one sensor sits at the ceiling, and two sit on the
    load itself -- so every height here comes from the fuel geometry the design
    already states rather than from a measurement off the drawing.

    Positions 06 and 07 attach to the load, so at a station whose plane misses
    the mock-up they have nothing to attach to and fall back to the centreline
    at the same two heights. Nothing is placed inside the load: 06 stands off
    its outboard face and 07 above its top, and every position is then checked
    against the solids like any other device.

    These are additional to the centreline ladder, which stays because it is
    the only thing Tier 1 can be compared against -- that engine resolves a
    vertical profile and no lateral one at all.
    """
    return [f"&DEVC ID='{annex7_id('thermocouple', station, position)}', "
            f"XYZ={x_m:.2f},{y:.2f},{z:.2f}, QUANTITY='THERMOCOUPLE' /"
            for position, y, z in figure_16_positions(kit, x_m, geom, dx_m, fuel, solids)]


def figure_16_positions(kit, x_m: float, geom: SectionGeometry, dx_m: float,
                        fuel: Box, solids: tuple[Box, ...]) -> list[tuple[int, float, float]]:
    """(position number, y, z) for the cross-section, as data.

    The single source of the Figure 16 layout: the deck turns these into DEVC
    lines and the cross-section view draws them, so the picture cannot drift
    away from what is measured. See `_figure_16_positions` for what the figure
    shows and for which heights are read off it.
    """
    if kit.thermocouples < LOAD_SIDE_TREE_MIN_TC:
        return []
    ceiling = ceiling_z_at(geom, 0.0, dx_m)
    wall_y = geom.width_at(fuel.z0) / 2.0 - dx_m
    in_plane = fuel.x0 <= x_m <= fuel.x1
    outboard = fuel.y1 + dx_m / 2.0 if in_plane else 0.0
    layout = [(1, -wall_y, fuel.z0), (2, -wall_y, fuel.z1), (3, 0.0, ceiling),
              (4, wall_y, fuel.z1), (5, wall_y, fuel.z0)]
    if kit.thermocouples >= 7:
        layout += [(6, outboard, fuel.z0), (7, fuel.y_centre_m if in_plane else 0.0,
                                            fuel.z1 + dx_m / 2.0)]
    out = []
    for position, y, z in layout[:kit.thermocouples]:
        placed = clear_of_solids_z_m(min(z, ceiling), x_m, y, solids, ceiling, dx_m)
        if placed is not None:
            out.append((position, y, placed))
    return out


def _table_5_profiles(name: str, kit, x_m: float, geom: SectionGeometry,
                      dx_m: float, load_y_m: float, solids: tuple[Box, ...]) -> list[str]:
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
    return lines


def _target_thermocouples(name: str, count: int, target: Box, dx_m: float) -> list[str]:
    """Table 5's thermocouples AT the target: in the gas cell against its upstream
    face, on its centreline, spread over its height. They used to sit on the
    tunnel centreline like every other station, which is beside a target that
    stands off to one side and reads the gas next to it, not the target."""
    x = target.x0 - dx_m / 2.0
    height = target.z1 - target.z0
    return [f"&DEVC ID='{name}_TC{i}', XYZ={x:.2f},{target.y_centre_m:.2f},"
            f"{target.z0 + (i + 0.5) / count * height:.2f}, QUANTITY='THERMOCOUPLE' /"
            for i in range(count)]


def _stations(design: Design, geom: SectionGeometry, dx_m: float) -> list[str]:
    """Annex 7 Table 5, device by device, plus the ceiling line a simulation needs."""
    from solit2.engines.reduced.criteria import (BREATHING_HEIGHT_M, HEAT_FLUX_HEIGHT_M,
                                                 INSTRUMENTS, STATIONS,
                                                 VISIBILITY_HEIGHT_M,
                                                 thermocouple_heights_m)
    lines = []
    fuel, target = fuel_box(design, geom, dx_m), target_box(design, geom, dx_m)
    roof = cover_box(design, geom, dx_m)
    solids = ((fuel, target) if has_target(design) else (fuel,)) \
        + (() if roof is None else (roof,))
    load_y_m = fuel.y_centre_m
    for name, x_m in sorted(STATIONS.items(), key=lambda kv: kv[1]):
        if not (WINDOW_M[0] <= x_m <= WINDOW_M[1]):
            continue
        kit = INSTRUMENTS[name]
        if name == "Target" and has_target(design):
            lines += _target_thermocouples(name, kit.thermocouples, target, dx_m)
            continue
        heights = thermocouple_heights_m(kit.thermocouples, geom.crown_height_m)
        for rung, z in enumerate(heights):
            placed = clear_of_solids_z_m(gas_z_m(geom, 0.0, z, dx_m), x_m, 0.0, solids,
                                         ceiling_z_at(geom, 0.0, dx_m), dx_m)
            if placed is None:
                raise ValueError(
                    f"{name}_TC{rung} at z={z:.2f} m cannot be placed clear of the fuel "
                    f"at x={x_m} m: the solid reaches the ceiling there")
            lines.append(f"&DEVC ID='{name}_TC{rung}', "
                        f"XYZ={x_m:.2f},0.0,{placed:.2f}, QUANTITY='THERMOCOUPLE' /")
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
        lines += _table_5_profiles(name, kit, x_m, geom, dx_m, load_y_m, solids)
        lines += _figure_16_positions(name, kit, x_m, geom, dx_m, fuel, solids)
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
    lines = [f"&DUMP DT_DEVC={DEVC_DT_S:.1f}, DT_HRR={DEVC_DT_S:.1f}, "
             f"DT_RESTART={DT_RESTART_S:.1f} /",
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


_E_COEFFICIENT_RE = re.compile(r"E_COEFFICIENT=([-+]?[0-9]*\.?[0-9]+(?:[eE][-+]?[0-9]+)?)")


def stored_e_coefficient(run_dir: Path) -> float | None:
    """The E_COEFFICIENT this run's own deck.fds actually carries, or None when
    there is no deck.fds to read it from (or it names none at all).

    A result must never describe what a run used by naming this module's
    CURRENT default instead: a run made with E=0.25 must not be reported as
    E=0.4 just because that happens to be what this build of the deck emits
    today. Every `&SURF ID='FIRE...'` line in a deck this module wrote carries
    the same value, so the first match is the run's own E.
    """
    deck_path = Path(run_dir) / "deck.fds"
    if not deck_path.exists():
        return None
    match = _E_COEFFICIENT_RE.search(deck_path.read_text())
    return float(match.group(1)) if match else None


# The first &MESH line's own IJK/XB: y spans j cells of one dx each, on every
# mesh in a deck this module writes (only x is split fine/coarse -- see
# _meshes), so the first mesh's y extent divided by its y cell count is the
# whole deck's dx, regardless of which x-region that first mesh happens to be.
_MESH_RE = re.compile(r"&MESH IJK=\d+,(\d+),\d+, XB=[^,]+,[^,]+,([^,]+),([^,]+),")


def stored_dx_m(run_dir: Path) -> float | None:
    """The cell size this run's own deck.fds actually carries, or None when
    there is no deck.fds to read it from (or it names no &MESH line at all).

    Exactly the same reasoning as `stored_e_coefficient`: a resume must rebuild
    the deck at the dx it was ORIGINALLY run at, never at this module's
    current default -- a grid-study point checkpointed at dx=0.75 resumed at
    the default 0.6 is a different mesh, and `_refuse_on_mesh_change` in
    runner.py would (correctly) refuse it as one, even though the run dir's
    OWN dx never changed.

    Rounded to 2 decimal places: `_meshes` writes the y/z extent at 2dp
    (`XB={-half_width:.2f},{half_width:.2f}`), and `half_width = j * dx_m /
    2.0` is not always exactly representable at that precision (dx=0.75,
    j=15 writes half_width as 5.62, not 5.625) -- dividing back out without
    rounding recovers 0.74933... instead of 0.75, and `generate()` then
    refuses to tile the window at that dx at all. Every dx this module
    documents as valid (0.25, 0.5, 0.6, 0.75, 1.0, 1.2) has at most 2
    decimals, so rounding to 2dp always recovers the intended value.
    """
    deck_path = Path(run_dir) / "deck.fds"
    if not deck_path.exists():
        return None
    match = _MESH_RE.search(deck_path.read_text())
    if not match:
        return None
    j, y0, y1 = int(match.group(1)), float(match.group(2)), float(match.group(3))
    return round((y1 - y0) / j, 2) if j else None


def matches_design(run_dir: Path, design: Design) -> bool | None:
    """Whether a run's own deck is still the deck this design generates.

    None when the run kept no deck to compare. The design's sha names the run
    directory, so a run made BEFORE a change to this module keeps its name and
    reads as current while describing a different experiment -- which is how a
    result gets attributed to geometry it never simulated. `T_END` is excluded
    because a deliberately shortened window is not a different deck.

    Compared against THIS MODULE'S CURRENT default `e_coefficient`, exactly
    like every other generator default (`dx_m`, for one) that this function
    does not accept as an argument: a design carries no E of its own, so "the
    deck this design generates now" means the deck at today's default E. A run
    deliberately made at a different E -- an `fds-calibrate-e` sweep point --
    is therefore correctly reported as not matching: it IS a different deck,
    for a different run, exactly as it should be.
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
             t_end_s: float | None = None, *, suppression: bool = True,
             restart: bool = False, e_coefficient: float = E_COEFFICIENT) -> str:
    """The deck. `suppression=False` is the SAME fire in the SAME tunnel with no
    mist system at all -- the free-burn reference the mist run is judged against.

    `restart=True` resumes from the restart files an earlier run of THIS deck
    left behind, instead of starting over. Everything else must match what that
    run was given, which is why it is a flag on the same generator rather than
    a separate one.

    `e_coefficient` overrides the module default for a calibration sweep
    (`solit2 fds-calibrate-e`); the deck text carries whatever value is passed,
    so a run's own deck.fds is always the record of the E it actually used --
    see `stored_e_coefficient`.
    """
    geom = section_geometry(design)
    duration_s = design.zones.duration_min * 60.0
    horizon_s = max(duration_s, t_end_s or 0.0)
    blocks = (_head(design, suppression) + _time(design, t_end_s, restart) + _meshes(geom, dx_m)
              + _tunnel(geom, dx_m) + _portals(design)
              + _fire(design, geom, dx_m, horizon_s, e_coefficient)
              + _cover(design, geom, dx_m) + _target(design, geom, dx_m)
              + (_nozzles(design, geom) if suppression else [])
              + _detection(design, geom, dx_m)
              + _stations(design, geom, dx_m) + _output(design, geom, dx_m, suppression)
              + ["&TAIL /"])
    return "\n".join(blocks)

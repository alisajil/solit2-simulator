"""Design -> FDS namelist text.

Deterministic by construction: the same `Design` always produces byte-identical
output, which is what makes golden-file testing possible. Geometry and station
positions are taken from the Tier 1 modules rather than recomputed, so both
engines describe the same tunnel and measure the same points -- without that,
`solit2 report correlation` would be comparing two different experiments.
"""
from __future__ import annotations

from solit2.engines.reduced.envelope import _design_sha
from solit2.engines.reduced.geometry import SectionGeometry, section_geometry
from solit2.schema.design import Design

# The fire sits at the origin of the measurement x-frame, the same frame
# `criteria.STATIONS` is written in.
FIRE_X_M = 0.0
# Wide enough to contain EVERY Annex 7 Table 5 station the criteria read --
# U340 to D215 -- because a station the deck does not measure is a KeyError
# inside `criteria._worst_station_value`, not a smaller result.
WINDOW_M = (-360.0, 240.0)
# Where the fire is and where resolution has to be paid for.
CORE_M = (-60.0, 120.0)
FINE_DX_M = 0.5              # D*/dx = 14.2 at 150 MW, inside the 10-16 band
COARSE_RATIO = 3             # far-field dx = FINE_DX_M * COARSE_RATIO


def _head(design: Design) -> list[str]:
    return [f"&HEAD CHID='{_design_sha(design)}', TITLE='{design.meta.name}' /", ""]


def _time(design: Design) -> list[str]:
    return [f"&TIME T_END={design.zones.duration_min * 60.0:.1f} /",
            f"&MISC TMPA={design.tunnel.ambient_temp_c:.1f} /", ""]


def _meshes(geom: SectionGeometry, fine_dx_m: float) -> list[str]:
    """Three meshes: coarse approach, fine core, coarse exit.

    The far meshes exist so U340, U100 and D215 are measured at all; they carry
    near-uniform flow, so they are resolved at COARSE_RATIO x the core's dx.
    Each span is an exact multiple of its own dx, which is what keeps the mesh
    interfaces aligned -- a misaligned interface is the classic multi-mesh bug.
    """
    coarse_dx_m = fine_dx_m * COARSE_RATIO
    half_width = geom.road_width_m / 2.0
    z_top = geom.crown_height_m
    zones = ((WINDOW_M[0], CORE_M[0], coarse_dx_m),
             (CORE_M[0], CORE_M[1], fine_dx_m),
             (CORE_M[1], WINDOW_M[1], coarse_dx_m))
    lines = []
    for x0, x1, dx in zones:
        ijk = (round((x1 - x0) / dx), round(geom.road_width_m / dx), round(z_top / dx))
        lines.append(
            f"&MESH IJK={ijk[0]},{ijk[1]},{ijk[2]}, "
            f"XB={x0:.1f},{x1:.1f},{-half_width:.2f},{half_width:.2f},0.0,{z_top:.2f} /"
        )
    return lines + [""]


def _tunnel(geom: SectionGeometry, dx_m: float) -> list[str]:
    """Solid boundary. A box gets walls; a bore gets a stair-stepped ring."""
    x0, x1 = WINDOW_M
    half_width = geom.road_width_m / 2.0
    lines = ["&SURF ID='WALL', DEFAULT=.TRUE., MATL_ID='CONCRETE' /",
             "&MATL ID='CONCRETE', DENSITY=2280., CONDUCTIVITY=1.8, "
             "SPECIFIC_HEAT=1.04 /", ""]
    if geom.shape == "box":
        lines += [
            f"&OBST XB={x0:.1f},{x1:.1f},{-half_width - dx_m:.2f},{-half_width:.2f},"
            f"0.0,{geom.crown_height_m:.2f}, SURF_ID='WALL' /",
            f"&OBST XB={x0:.1f},{x1:.1f},{half_width:.2f},{half_width + dx_m:.2f},"
            f"0.0,{geom.crown_height_m:.2f}, SURF_ID='WALL' /",
            f"&OBST XB={x0:.1f},{x1:.1f},{-half_width:.2f},{half_width:.2f},"
            f"{geom.crown_height_m:.2f},{geom.crown_height_m + dx_m:.2f}, SURF_ID='WALL' /",
        ]
        return lines + [""]
    # circle: one OBST pair per dx layer, each as wide as the bore is at that height
    steps = max(int(geom.crown_height_m / dx_m), 1)
    for i in range(steps):
        z_lo = i * dx_m
        z_hi = z_lo + dx_m
        clear = geom.width_at(min(z_hi, geom.crown_height_m)) / 2.0
        if clear >= half_width:
            continue
        lines += [
            f"&OBST XB={x0:.1f},{x1:.1f},{-half_width:.2f},{-clear:.2f},"
            f"{z_lo:.2f},{z_hi:.2f}, SURF_ID='WALL' /",
            f"&OBST XB={x0:.1f},{x1:.1f},{clear:.2f},{half_width:.2f},"
            f"{z_lo:.2f},{z_hi:.2f}, SURF_ID='WALL' /",
        ]
    return lines + [""]


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


def generate(design: Design, fine_dx_m: float = FINE_DX_M) -> str:
    geom = section_geometry(design)
    blocks = (_head(design) + _time(design) + _meshes(geom, fine_dx_m)
              + _tunnel(geom, fine_dx_m) + _portals(design) + ["&TAIL /"])
    return "\n".join(blocks)

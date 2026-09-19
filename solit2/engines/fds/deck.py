"""Design -> FDS namelist text.

Deterministic by construction: the same `Design` always produces byte-identical
output, which is what makes golden-file testing possible. Geometry and station
positions are taken from the Tier 1 modules rather than recomputed, so both
engines describe the same tunnel and measure the same points -- without that,
`solit2 report correlation` would be comparing two different experiments.
"""
from __future__ import annotations

import math

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
CEILING_TC_SPACING_M = 5.0
CEILING_TC_PREFIX = "CEIL"
TARGET_GAUGE_ID = "TARGET_FLUX"
CEILING_OFFSET_M = 0.15      # below the crown, matching Tier 1's ceiling definition
DEVC_DT_S = 1.0
# FDS's VOLUME FRACTION is mol/mol. `max_co_ppm` is an Annex 7 life-safety
# criterion in ppm, so FDS is asked to emit ppm rather than the reader guessing
# at the unit -- without this the gate compares ~2e-4 against a limit of 500 and
# structurally cannot fail.
CO_PPM_CONVERSION = "1E6"


def _head(design: Design) -> list[str]:
    return [f"&HEAD CHID='{_design_sha(design)}', TITLE='{design.meta.name}' /", ""]


def _time(design: Design) -> list[str]:
    return [f"&TIME T_END={design.zones.duration_min * 60.0:.1f} /",
            f"&MISC TMPA={design.tunnel.ambient_temp_c:.1f} /", ""]


def _cells_up_to_ratio(cells: int) -> int:
    """Round a cell count UP to a multiple of COARSE_RATIO, never below it."""
    cells = max(cells, COARSE_RATIO)
    return cells + (-cells) % COARSE_RATIO


def _meshes(geom: SectionGeometry, fine_dx_m: float) -> list[str]:
    """Three meshes: coarse approach, fine core, coarse exit.

    The far meshes exist so U340, U100 and D215 are measured at all; they carry
    near-uniform flow, so they are resolved at COARSE_RATIO x the core's dx.
    A misaligned interface is the classic multi-mesh bug, so alignment is
    enforced in all three directions, not just x:

    - x: each span is an exact multiple of its own dx, and the coarse dx is
      COARSE_RATIO x the fine one;
    - y and z: the three meshes share ONE y extent and ONE z extent, so the
      core's j and k are rounded UP to a multiple of COARSE_RATIO and the far
      meshes take exactly a COARSE_RATIO-th of them. Rounding up rather than
      taking round(width/dx) is what stops j=20 landing against j=7.
    """
    coarse_dx_m = fine_dx_m * COARSE_RATIO
    half_width = geom.road_width_m / 2.0
    z_top = geom.crown_height_m
    fine_j = _cells_up_to_ratio(round(geom.road_width_m / fine_dx_m))
    fine_k = _cells_up_to_ratio(round(z_top / fine_dx_m))
    coarse_jk = (fine_j // COARSE_RATIO, fine_k // COARSE_RATIO)
    zones = ((WINDOW_M[0], CORE_M[0], coarse_dx_m, coarse_jk),
             (CORE_M[0], CORE_M[1], fine_dx_m, (fine_j, fine_k)),
             (CORE_M[1], WINDOW_M[1], coarse_dx_m, coarse_jk))
    lines = []
    for x0, x1, dx, (j, k) in zones:
        lines.append(
            f"&MESH IJK={round((x1 - x0) / dx)},{j},{k}, "
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
    steps = max(int(geom.crown_height_m / dx_m), 1)
    return [(i * dx_m, (i + 1) * dx_m,
             geom.width_at(min((i + 1) * dx_m, geom.crown_height_m)) / 2.0)
            for i in range(steps)]


def stepped_free_area_m2(geom: SectionGeometry, dx_m: float = FINE_DX_M) -> float:
    """Free area of the section AS THE DECK EMITS IT, not as Tier 1 defines it.

    A stair-stepped circle cannot match a smooth one, so this will not equal
    `geom.free_area_m2` and no attempt is made to make it. It exists so the gap
    can be REPORTED: the whole point of Tier 2 is that it models the same
    tunnel Tier 1 does, and where the discretisation makes that untrue, the
    difference belongs in `Result.warnings` rather than in a source comment.
    """
    if geom.shape == "box":
        return geom.road_width_m * geom.crown_height_m
    half_width = geom.road_width_m / 2.0
    layers = _bore_layers(geom, dx_m)
    area = sum((geom.road_width_m if clear >= half_width else 2.0 * clear)
               * (z_hi - z_lo) for z_lo, z_hi, clear in layers)
    # above the topmost whole layer the deck writes no obstruction at all, so
    # that sliver stands open at the full road width
    return area + geom.road_width_m * (geom.crown_height_m - layers[-1][1])


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


def _fire(design: Design) -> list[str]:
    """Free-burn curve as the surface's own ramp; suppression is FDS's job.

    Tier 1 bakes suppression into its HRR curve because it has no droplets.
    Here the deck declares the UNSUPPRESSED fire and lets `E_COEFFICIENT` --
    the surface's extinguishing coefficient -- fall out of the water that
    actually lands on it.
    """
    f = design.fire
    fp = f.footprint
    area_m2 = fp.length_m * fp.width_m
    hrrpua = design.fire.design_hrr_mw * 1000.0 / area_m2
    half_l, half_w = fp.length_m / 2.0, fp.width_m / 2.0
    lines = [
        f"&SURF ID='FIRE', HRRPUA={hrrpua:.1f}, RAMP_Q='FIRE_RAMP', "
        f"E_COEFFICIENT=0.4, COLOR='RED' /",
        f"&OBST XB={FIRE_X_M - half_l:.2f},{FIRE_X_M + half_l:.2f},"
        f"{-half_w:.2f},{half_w:.2f},{fp.base_height_m:.2f},{fp.top_height_m:.2f}, "
        f"SURF_IDS='FIRE','INERT','INERT' /",
    ]
    # t-squared growth after the incubation period, sampled every 30 s
    alpha = f.alpha
    t_peak = math.sqrt(design.fire.design_hrr_mw * 1000.0 / alpha) + f.incubation_s
    t = 0.0
    while t <= t_peak:
        q = 0.0 if t < f.incubation_s else min(alpha * (t - f.incubation_s) ** 2, design.fire.design_hrr_mw * 1000.0)
        lines.append(f"&RAMP ID='FIRE_RAMP', T={t:.1f}, F={q / (design.fire.design_hrr_mw * 1000.0):.4f} /")
        t += 30.0
    lines.append(f"&RAMP ID='FIRE_RAMP', T={design.zones.duration_min * 60.0:.1f}, F=1.0000 /")
    return lines + [""]


def _nozzles(design: Design, geom: SectionGeometry) -> list[str]:
    """One PART, one PROP, and one DEVC per head -- single-mode only."""
    from solit2.engines.reduced.geometry import nozzle_positions

    mode = design.nozzles.modes[0]
    smd_um = mode.smd_um or next(iter(design.nozzles.smd_table.values()))
    lines = [
        "&SPEC ID='WATER VAPOR' /",
        f"&PART ID='FINE', SPEC_ID='WATER VAPOR', DIAMETER={smd_um:.1f}, "
        f"GAMMA_D=2.4, SAMPLING_FACTOR=10 /",
        f"&PROP ID='NOZ_FINE', PART_ID='FINE', "
        f"FLOW_RATE={design.nozzles.flow_per_head_lpm:.2f}, "
        f"SPRAY_ANGLE=0.0,{mode.cone_half_angle_deg:.1f}, "
        f"PARTICLE_VELOCITY={mode.launch_velocity_ms:.1f} /",
    ]
    tilt = math.radians(design.nozzles.mounting.tilt_deg)
    for i, pos in enumerate(nozzle_positions(design, geom, FIRE_X_M)):
        lines.append(
            f"&DEVC ID='NOZ{i}', XYZ={pos.x_m:.2f},{pos.y_m:.2f},{pos.z_m:.2f}, "
            f"PROP_ID='NOZ_FINE', QUANTITY='TIME', SETPOINT=0.0, "
            f"ORIENTATION=0.0,{math.sin(tilt):.3f},{-math.cos(tilt):.3f}, "
            f"CTRL_ID='ACT' /"
        )
    return lines + [""]


def _detection(design: Design) -> list[str]:
    """Linear heat detection along the ceiling, then the activation delay.

    Over the core only: detection that matters is detection near the fire, and
    a sensor 300 m up the approach tunnel would never be the one that trips.
    """
    x0, x1 = CORE_M
    lines = []
    n = int((x1 - x0) / design.detection.sensor_spacing_m)
    for i in range(n):
        x = x0 + i * design.detection.sensor_spacing_m
        lines.append(
            f"&DEVC ID='LHD{i}', XYZ={x:.2f},0.0,{_ceiling_z(design):.2f}, "
            f"QUANTITY='THERMOCOUPLE', SETPOINT={design.detection.threshold_c:.1f} /"
        )
    lines += [
        f"&CTRL ID='DETECT', FUNCTION_TYPE='ANY', "
        f"INPUT_ID={','.join(repr(f'LHD{i}') for i in range(n))} /",
        f"&CTRL ID='ACT', FUNCTION_TYPE='TIME_DELAY', INPUT_ID='DETECT', "
        f"DELAY={design.zones.activation_delay_s:.1f} /",
    ]
    return lines + [""]


def _ceiling_z(design: Design) -> float:
    return section_geometry(design).crown_height_m - CEILING_OFFSET_M


def fire_ceiling_device_id() -> str:
    """The ceiling thermocouple directly above the fire.

    `_stations` lays the ceiling line out from CORE_M[0] in CEILING_TC_SPACING_M
    steps, so the device over the fire is that offset divided by the spacing.
    The MIDDLE of the line is not it: the line is not centred on the fire, and
    on the current window the midpoint sits 30 m downstream of it.
    """
    return f"{CEILING_TC_PREFIX}{int((FIRE_X_M - CORE_M[0]) / CEILING_TC_SPACING_M)}"


def _stations(design: Design, geom: SectionGeometry) -> list[str]:
    """Annex 7 Table 5, device by device, plus the two a simulation needs."""
    from solit2.engines.reduced.criteria import (BREATHING_HEIGHT_M, HEAT_FLUX_HEIGHT_M,
                                                 INSTRUMENTS, STATIONS,
                                                 VISIBILITY_HEIGHT_M,
                                                 thermocouple_heights_m)
    lines = []
    for name, x_m in sorted(STATIONS.items(), key=lambda kv: kv[1]):
        if not (WINDOW_M[0] <= x_m <= WINDOW_M[1]):
            continue
        kit = INSTRUMENTS[name]
        heights = thermocouple_heights_m(kit.thermocouples, geom.crown_height_m)
        for rung, z in enumerate(heights):
            lines.append(f"&DEVC ID='{name}_TC{rung}', XYZ={x_m:.2f},0.0,{z:.2f}, "
                        f"QUANTITY='THERMOCOUPLE' /")
        if kit.heat_flux:
            lines.append(
                f"&DEVC ID='{name}_HF', XYZ={x_m:.2f},0.0,{HEAT_FLUX_HEIGHT_M:.2f}, "
                f"QUANTITY='GAUGE HEAT FLUX', IOR=-1 /")
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
    # the target gauge Table 5 has no reason to carry
    lines.append(
        f"&DEVC ID='{TARGET_GAUGE_ID}', XYZ={design.fire.target_x_m:.2f},0.0,"
        f"{BREATHING_HEIGHT_M:.2f}, QUANTITY='GAUGE HEAT FLUX', IOR=-1 /")
    # ceiling line over the core, for the exposed-length criterion
    x0, x1 = CORE_M
    z = _ceiling_z(design)
    for i in range(int((x1 - x0) / CEILING_TC_SPACING_M)):
        x = x0 + i * CEILING_TC_SPACING_M
        lines.append(f"&DEVC ID='{CEILING_TC_PREFIX}{i}', XYZ={x:.2f},0.0,{z:.2f}, "
                    f"QUANTITY='THERMOCOUPLE' /")
    return lines + [""]


def _output() -> list[str]:
    return [f"&DUMP DT_DEVC={DEVC_DT_S:.1f}, DT_HRR={DEVC_DT_S:.1f} /",
            "&SLCF PBY=0.0, QUANTITY='TEMPERATURE' /",
            "&SLCF PBY=0.0, QUANTITY='U-VELOCITY' /", ""]


def generate(design: Design, fine_dx_m: float = FINE_DX_M) -> str:
    geom = section_geometry(design)
    blocks = (_head(design) + _time(design) + _meshes(geom, fine_dx_m)
              + _tunnel(geom, fine_dx_m) + _portals(design) + _fire(design)
              + _nozzles(design, geom) + _detection(design)
              + _stations(design, geom) + _output() + ["&TAIL /"])
    return "\n".join(blocks)

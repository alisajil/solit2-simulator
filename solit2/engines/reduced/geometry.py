"""Tunnel section geometry and nozzle placement.

The bored tunnel is a circle with the carriageway as a chord below the centre,
so the road width, the free area and the width available at the nozzle mounting
height all follow from circular-segment algebra. The cut-and-cover and test
tunnels are rectangles.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from solit2.schema.design import Design


@dataclass(frozen=True)
class SectionGeometry:
    name: str
    road_width_m: float
    crown_height_m: float
    free_area_m2: float
    shape: str
    radius_m: float | None = None
    deck_below_centre_m: float | None = None

    @property
    def mean_height_m(self) -> float:
        """Area-equivalent height, used where a correlation wants a single height."""
        return self.free_area_m2 / self.road_width_m

    @property
    def hydraulic_diameter_m(self) -> float:
        perimeter = (math.pi * 2 * self.radius_m if self.shape == "circle"
                     else 2 * (self.road_width_m + self.crown_height_m))
        return 4 * self.free_area_m2 / perimeter

    def width_at(self, height_above_carriageway_m: float) -> float:
        """Clear width at a height above the carriageway; 0.0 above the crown."""
        if height_above_carriageway_m < 0:
            raise ValueError(f"height {height_above_carriageway_m} is below the carriageway")
        if height_above_carriageway_m > self.crown_height_m:
            return 0.0
        if self.shape == "box":
            return self.road_width_m
        y = height_above_carriageway_m - self.deck_below_centre_m
        return 2.0 * math.sqrt(max(self.radius_m**2 - y**2, 0.0))


@dataclass(frozen=True)
class NozzlePosition:
    x_m: float
    y_m: float
    z_m: float
    row: int
    tilt_deg: float


def section_geometry(design: Design) -> SectionGeometry:
    t = design.tunnel
    if t.shape == "box":
        if t.width_m is None or t.height_m is None:
            raise ValueError("a box section needs both width_m and height_m")
        area = t.area_m2 if t.area_m2 is not None else t.width_m * t.height_m
        return SectionGeometry(t.section, t.width_m, t.height_m, area, "box")

    if t.internal_diameter_m is None or t.deck_below_centre_m is None:
        raise ValueError("a circular section needs internal_diameter_m and deck_below_centre_m")
    r = t.internal_diameter_m / 2.0
    d = t.deck_below_centre_m
    if d >= r:
        raise ValueError(f"deck_below_centre_m={d} must be less than the radius {r}")
    half_chord = math.sqrt(r**2 - d**2)
    road_width = 2.0 * half_chord
    crown = r + d
    # circle area minus the segment cut off below the carriageway chord
    segment = r**2 * math.acos(d / r) - d * half_chord
    area = t.area_m2 if t.area_m2 is not None else math.pi * r**2 - segment
    return SectionGeometry(t.section, road_width, crown, area, "circle", r, d)


def nozzle_positions(design: Design, geom: SectionGeometry,
                     fire_x_m: float) -> tuple[NozzlePosition, ...]:
    """Heads over the active length, rows staggered by one longitudinal step.

    The active length is the fire's zone plus one zone each side, centred on the
    fire, so head `i` sits at `-L/2 + (i + 0.5) * step` relative to the fire.
    """
    mount = design.nozzles.mounting
    width_here = geom.width_at(mount.height_above_carriageway_m)
    for offset in mount.row_lateral_offsets_m:
        if abs(offset) > width_here / 2.0:
            raise ValueError(
                f"nozzle row at lateral offset {offset} m does not fit: the section is "
                f"{width_here:.2f} m wide at the mounting height "
                f"{mount.height_above_carriageway_m} m (limit +/-{width_here / 2:.2f} m)"
            )
    n = design.active_heads
    length = design.active_length_m
    step = length / n
    return tuple(
        NozzlePosition(
            x_m=fire_x_m - length / 2.0 + (i + 0.5) * step,
            y_m=mount.row_lateral_offsets_m[i % mount.rows],
            z_m=mount.height_above_carriageway_m,
            row=i % mount.rows,
            tilt_deg=mount.tilt_deg,
        )
        for i in range(n)
    )

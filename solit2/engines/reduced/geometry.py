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
        """4A/P, P being the wetted perimeter of the FREE-FLOW cross-section --
        every solid surface the air actually touches, not the shape's full
        outline.

        Box: floor, ceiling and both walls -- the full rectangle perimeter.

        Circle (bored tunnel): the carriageway deck sits on a chord below the
        centre and cuts the bore into two pieces. `free_area_m2` is only the
        piece ABOVE the deck (the segment below it is solid ground/services,
        not part of the flow), so the wetted perimeter is the ARC bounding that
        piece plus the DECK ITSELF -- not the full circle's circumference. The
        previous formula used the full circumference, which double-counts the
        arc below the deck (not wetted, and not walked past by the air) and
        omits the deck (which is wetted). On the bored-tunnel test fixture this
        understated D_h by about 8%.

        The two intersection points of the deck chord with the bore are at
        angular distance acos(d/r) from the bottom of the circle, so the MINOR
        arc (below the deck, excluded) subtends 2*acos(d/r) and the MAJOR arc
        (above the deck, the one that bounds the free area) subtends the
        remainder, 2*pi - 2*acos(d/r). At d=0 (deck through the centre) this
        correctly gives a semicircle's arc, pi*r.
        """
        if self.shape == "circle":
            r, d = self.radius_m, self.deck_below_centre_m
            major_arc = 2 * r * (math.pi - math.acos(d / r))
            perimeter = major_arc + self.road_width_m  # road_width_m IS the deck chord
        else:
            perimeter = 2 * (self.road_width_m + self.crown_height_m)
        return 4 * self.free_area_m2 / perimeter

    @property
    def max_width_m(self) -> float:
        """The widest the free cross-section ever gets, at any height.

        NOT the road width. A bored tunnel's carriageway is a chord BELOW the
        centre, so the bore keeps widening above it and reaches its full
        diameter at centre height -- 11.00 m against a 10.15 m carriageway on
        the reference section. Anything sized to the road width clips the
        widest part of the tunnel off.
        """
        if self.shape == "box":
            return self.road_width_m
        # the circle is widest at its centre, which sits above the carriageway
        return max(self.road_width_m, 2.0 * self.radius_m)

    def area_between(self, z_lo_m: float, z_hi_m: float, samples: int = 256) -> float:
        """True open area of the band z_lo..z_hi, by midpoint rule on `width_at`."""
        top = min(z_hi_m, self.crown_height_m)
        if top <= z_lo_m:
            return 0.0
        step = (top - z_lo_m) / samples
        return sum(self.width_at(z_lo_m + (k + 0.5) * step)
                   for k in range(samples)) * step

    def band_width_m(self, z_lo_m: float, z_hi_m: float) -> float:
        """The constant width that gives a z_lo..z_hi slab the band's TRUE area.

        A stair-step taking its width at one edge of a layer is wrong by the
        curvature across it, worst where the bore turns over near the crown --
        2.85 m of width in that layer on the reference section. Spreading the
        band's real area over the slab's full height instead makes every step
        carry exactly the area it stands for, including the last one, whose
        slab runs past the crown because the mesh is whole cells and the crown
        is not.
        """
        if z_hi_m <= z_lo_m:
            return 0.0
        return self.area_between(z_lo_m, z_hi_m) / (z_hi_m - z_lo_m)

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


def fire_lateral_m(design: Design, geom: SectionGeometry) -> float:
    """The fuel load's centreline across the tunnel, in the deck's y (0 = tunnel centre).

    Annex 7 section 5.2.3 sites the mock-up eccentric to the tunnel centreline,
    near one side wall, precisely because a centred load flatters the system.
    `lane_centre_offset_from_wall_m` is that offset measured from the near wall;
    the standard names no side, so ONE convention is fixed here for every
    consumer -- the Tier 1 mist envelope, the FDS deck and every drawing: the
    near wall is the -y wall (the left wall looking downstream). The tunnel is
    mirror-symmetric about y = 0, so the choice changes no physics, only which
    way the picture is drawn.
    """
    offset = design.fire.lane_centre_offset_from_wall_m
    half_load = design.fire.footprint.width_m / 2.0
    # The whole load, not just its centreline. `lane_centre_offset_from_wall_m`
    # is measured to the load's CENTRE, so an offset under half its width puts
    # its near face beyond the wall. Nothing downstream would say so: FDS snaps
    # the obstruction into the wall solid and burns a surface that is buried,
    # which reads as a quietly weak fire rather than as an error. Annex 7 5.2.3
    # asks for under 1.5 m of clearance at the near FACE, so an offset in that
    # range is exactly the plausible misreading this catches.
    if not half_load <= offset <= geom.road_width_m - half_load:
        raise ValueError(
            f"lane_centre_offset_from_wall_m={offset} m puts the "
            f"{design.fire.footprint.width_m} m wide fuel load outside the "
            f"{geom.road_width_m:.2f} m carriageway: the offset is measured to the load's "
            f"CENTRE, so it must be between {half_load:.2f} and "
            f"{geom.road_width_m - half_load:.2f} m. Annex 7 5.2.3's 'less than 1.5 m' is "
            f"the clearance at the load's near face, which is this offset minus "
            f"{half_load:.2f} m")
    return offset - geom.road_width_m / 2.0

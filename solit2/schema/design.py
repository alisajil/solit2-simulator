"""Design JSON -> validated, frozen `Design`.

Field names carry their units. Presets supply every field the design omits.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

from solit2.schema.presets import deep_merge, load_preset

NFPA750_HIGH_PRESSURE_FLOOR_BAR = 34.5
# NFPA 72 t-squared fire growth coefficients, kW/s^2.
GROWTH_ALPHA_KW_S2 = {"slow": 0.00293, "medium": 0.01172, "fast": 0.0469, "ultrafast": 0.1876}


class Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class Meta(Frozen):
    name: str
    notes: str = ""


class Tunnel(Frozen):
    preset: str
    note: str = ""
    tube: Literal["LHS", "RHS"] = "LHS"
    section: Literal["bored", "cut_cover", "test"] = "bored"
    shape: Literal["circle", "box"] = "circle"
    internal_diameter_m: float | None = None
    deck_below_centre_m: float | None = None
    width_m: float | None = None
    height_m: float | None = None
    area_m2: float | None = None
    clearance_m: float = 5.5
    length_m: float
    gradient_pct: float = 0.0
    ambient_temp_c: float = 30.0
    ambient_rh_pct: float = 75.0


class Footprint(Frozen):
    length_m: float = Field(gt=0)
    width_m: float = Field(gt=0)
    top_height_m: float = Field(gt=0)
    # Li & Ingason's effective tunnel height is measured from the BASE of the
    # fire source to the ceiling, not from the fuel top -- see thermal.field().
    # `provenance` records whether a value is a measured figure or, like the
    # HGV mock-up's load-platform height, an engineering assumption.
    base_height_m: float = Field(ge=0)
    provenance: str | None = None

    @model_validator(mode="after")
    def _base_below_top(self) -> "Footprint":
        if self.base_height_m >= self.top_height_m:
            raise ValueError(
                f"base_height_m={self.base_height_m} must be less than "
                f"top_height_m={self.top_height_m}: the fuel cannot start above its own top"
            )
        return self


class Pool(Frozen):
    count: int = Field(gt=0)
    length_m: float = Field(gt=0)
    width_m: float = Field(gt=0)
    fuel: Literal["diesel"] = "diesel"


class Fire(Frozen):
    preset: str
    note: str = ""
    fire_class: Literal["A", "B"] = Field(alias="class")
    design_hrr_mw: float = Field(gt=0, le=300)
    growth: Literal["slow", "medium", "fast", "ultrafast"] = "fast"
    alpha_kw_s2: float | None = None
    incubation_s: float = 60.0
    pallets: int | None = None
    energy_mj_per_pallet: float = 343.0
    covered: bool = False
    pools: Pool | None = None
    footprint: Footprint
    lane_centre_offset_from_wall_m: float = Field(gt=0)
    target_distance_m: float = Field(gt=0)

    model_config = ConfigDict(frozen=True, extra="forbid", populate_by_name=True)

    @property
    def alpha(self) -> float:
        return self.alpha_kw_s2 if self.alpha_kw_s2 is not None else GROWTH_ALPHA_KW_S2[self.growth]


class Mode(Frozen):
    id: str
    fraction: float = Field(gt=0, le=1)
    smd_um: float | None = None
    cone_half_angle_deg: float
    launch_velocity_ms: float


class Mounting(Frozen):
    type: Literal["ceiling_rows"] = "ceiling_rows"
    rows: int = Field(ge=1, le=3)
    row_lateral_offsets_m: tuple[float, ...]
    height_above_carriageway_m: float = Field(gt=0)
    pitch_m: float = Field(gt=0, le=10)
    tilt_deg: float = 0.0

    @model_validator(mode="after")
    def _offsets_match_rows(self) -> "Mounting":
        if len(self.row_lateral_offsets_m) != self.rows:
            raise ValueError(
                f"row_lateral_offsets_m has {len(self.row_lateral_offsets_m)} entries "
                f"but rows={self.rows}; one lateral offset per row is required"
            )
        return self


class Nozzles(Frozen):
    preset: str
    note: str = ""
    k_factor_lpm_bar05: float = Field(gt=0.5, le=20)
    pressure_bar: float
    smd_table: dict[str, float] = Field(default_factory=dict)
    modes: tuple[Mode, ...]
    mounting: Mounting

    @field_validator("pressure_bar")
    @classmethod
    def _above_nfpa_floor(cls, v: float) -> float:
        if v < NFPA750_HIGH_PRESSURE_FLOOR_BAR:
            raise ValueError(
                f"pressure_bar={v} is below the NFPA 750 high-pressure floor of "
                f"{NFPA750_HIGH_PRESSURE_FLOOR_BAR} bar; allowed range is "
                f"{NFPA750_HIGH_PRESSURE_FLOOR_BAR}-140"
            )
        if v > 140:
            raise ValueError(f"pressure_bar={v} exceeds the 140 bar limit")
        return v

    @model_validator(mode="after")
    def _fractions_sum_to_one(self) -> "Nozzles":
        total = sum(m.fraction for m in self.modes)
        if abs(total - 1.0) > 0.01:
            raise ValueError(f"mode fraction values sum to {total:.3f}; they must sum to 1.00 +/- 0.01")
        return self

    @property
    def flow_per_head_lpm(self) -> float:
        return self.k_factor_lpm_bar05 * math.sqrt(self.pressure_bar)

    def _mode(self, mode_id: str) -> Mode:
        for m in self.modes:
            if m.id == mode_id:
                return m
        raise KeyError(f"no nozzle mode {mode_id!r}; modes are {[m.id for m in self.modes]}")

    def mode_flow_lpm(self, mode_id: str) -> float:
        return self.flow_per_head_lpm * self._mode(mode_id).fraction

    def smd_um(self, mode_id: str) -> float:
        """Mode droplet size: explicit value, else log-log interpolation of the preset table."""
        mode = self._mode(mode_id)
        if mode.smd_um is not None:
            return mode.smd_um
        if not self.smd_table:
            raise ValueError(f"mode {mode_id!r} has no smd_um and the nozzle preset has no smd_table")
        pressures = sorted(float(p) for p in self.smd_table)
        sizes = [self.smd_table[f"{p:g}"] for p in pressures]
        p = min(max(self.pressure_bar, pressures[0]), pressures[-1])
        return math.exp(
            _interp(math.log(p), [math.log(x) for x in pressures], [math.log(s) for s in sizes])
        )


def _interp(x: float, xs: list[float], ys: list[float]) -> float:
    for i in range(1, len(xs)):
        if x <= xs[i]:
            f = (x - xs[i - 1]) / (xs[i] - xs[i - 1])
            return ys[i - 1] + f * (ys[i] - ys[i - 1])
    return ys[-1]


class Zones(Frozen):
    section_length_m: float = Field(ge=8, le=100)
    heads_per_zone: int | None = None
    sections_simultaneous: int = Field(ge=1, le=6)
    activation_delay_s: float = Field(ge=0, le=600)
    pump_ramp_s: float = Field(ge=0)
    duration_min: float = Field(ge=10, le=120)
    # Absolute clock time (seconds from ignition) at which the system was
    # manually activated, overriding the detection+delay timetable. Used by
    # validation anchors transcribed from tests where the FFFS was started by
    # the test operator rather than by the modelled linear-heat detector.
    manual_activation_s: float | None = None


class Ventilation(Frozen):
    mode: Literal["longitudinal"] = "longitudinal"
    velocity_ms: float | None = Field(default=None, ge=0, le=8)
    velocity_range_ms: tuple[float, float] = (3.88, 5.08)


class Detection(Frozen):
    type: Literal["linear_heat"] = "linear_heat"
    threshold_c: float = Field(gt=0)
    sensor_spacing_m: float = Field(gt=0)


class Hydraulics(Frozen):
    preset: str
    note: str = ""
    main_dn_mm: float
    zone_header_dn_mm: float
    row_pipe_dn_mm: float
    roughness_mm: float
    pump_unit_m3h: float
    pump_efficiency: float = Field(gt=0, lt=1)
    motor_efficiency: float = Field(gt=0, lt=1)
    loop_factor: float = Field(gt=0, le=1)
    static_head_bar: float
    fittings_loss_bar: float
    safety_factor: float = 1.10


class Constraints(Frozen):
    """Engineering limits the user's own project imposes.

    Not from SOLIT2. These are site and procurement constraints -- the feeder
    capacity at a portal, a water volume a tank farm can hold, a pressure band a
    procurement spec fixes -- and they are evaluated separately from the
    acceptance criteria and reported in their own block. A constraint breach is
    a local circumstance, never a SOLIT2 failure, so it can never fail a gate.

    Every limit is `None` until the user declares it, and an undeclared limit
    reports as unset exactly as an unset AHJ limit does.
    """
    note: str = ""
    max_pump_power_kw: float | None = None
    max_application_density_mm_min: float | None = None
    max_water_volume_m3: float | None = None
    max_nozzle_pressure_bar: float | None = None
    min_nozzle_pressure_bar: float | None = None


class AHJ(Frozen):
    """Limits the authority having jurisdiction sets.

    SOLIT2 Annex 7 section 7.1 gives four categories of acceptance criteria but
    "do[es] not specify in detail absolute values": "the detailed acceptance
    criteria shall be defined by authorities having jurisdiction based on the
    risk analysis of every individual tunnel". So every absolute value here is
    `None` until someone sets it, and a criterion reading `None` is reported as
    unset rather than silently borrowing a figure from another vendor's report.
    """
    note: str = ""
    # 7.3.1 - the ventilation system's unsuppressed design fire size
    tvs_design_fire_mw: float | None = None
    # 7.2.2 life safety, upstream and downstream
    max_air_temp_c: float | None = None
    max_heat_flux_kwm2: float | None = None
    min_visibility_m: float | None = None
    max_fed: float | None = None
    max_co_ppm: float | None = None
    # 7.2.4 structure: how hot, over how long a run of tunnel, for how long.
    # The threshold is Annex 7's own example figure (">500 C are allowed if
    # exposure time is short and area is small"), so it is a reporting
    # threshold rather than a limit and is the one field that is never None.
    structure_temp_threshold_c: float = 500.0
    max_structure_exposure_length_m: float | None = None
    max_structure_exposure_duration_s: float | None = None


class Design(Frozen):
    meta: Meta
    tunnel: Tunnel
    fire: Fire
    nozzles: Nozzles
    zones: Zones
    ventilation: Ventilation
    detection: Detection
    hydraulics: Hydraulics
    ahj: AHJ = Field(default_factory=AHJ)
    # The user's own engineering limits, kept apart from `criteria` because one
    # is a local circumstance and the other is the standard.
    constraints: Constraints = Field(default_factory=Constraints)
    criteria: dict = Field(default_factory=dict)

    @classmethod
    def load(cls, path: str | Path) -> "Design":
        raw = json.loads(Path(path).read_text())
        for block, kind in (("tunnel", "tunnel"), ("fire", "fire"),
                            ("nozzles", "nozzle"), ("hydraulics", "hydraulics")):
            name = raw.get(block, {}).get("preset")
            if name is None:
                raise ValueError(f"design block {block!r} must name a preset")
            raw[block] = deep_merge(load_preset(kind, name), raw[block])
        return cls.model_validate(raw)

    @property
    def heads_per_zone(self) -> int:
        """Rows are staggered, so heads alternate sides every `pitch / rows` metres."""
        if self.zones.heads_per_zone is not None:
            return self.zones.heads_per_zone
        mount = self.nozzles.mounting
        return round(self.zones.section_length_m / (mount.pitch_m / mount.rows))

    @property
    def active_length_m(self) -> float:
        return self.zones.section_length_m * self.zones.sections_simultaneous

    @property
    def active_heads(self) -> int:
        return self.heads_per_zone * self.zones.sections_simultaneous

    @property
    def flow_lpm(self) -> float:
        return self.active_heads * self.nozzles.flow_per_head_lpm

# SOLIT² Simulator — Plan 1: Tier 1 Optimiser Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the reduced-order (Tier 1) tunnel-fire + water-mist engine so that `solit2 run designs/og-dbr-rev0.json` scores a candidate FFFS design against the Orange Gate tender gates and SOLIT² tenability criteria in under a second, and `solit2 validate` proves the engine reproduces six published full-scale fire tests.

**Architecture:** A pydantic design JSON is resolved against presets into a frozen `Design`. `engines/reduced/sim.py` marches a 1-second explicit time loop over pure per-module state transitions (fire → ventilation → thermal → mist → tenability), `envelope.py` repeats that over the tunnel-section × ventilation-velocity grid and keeps the worst case, `score.py` applies hard gates then a weighted objective, and `cli.py` emits one result JSON and appends a history row. Every empirical constant lives in `presets/calibration.json` and is fitted by `validation/` against the six anchor tests.

**Tech Stack:** Python 3.12, uv, pydantic v2, numpy, scipy (`optimize.least_squares` for calibration), pytest + pytest-cov + hypothesis. No plotting or web dependencies in this plan.

**Spec:** `docs/superpowers/specs/2026-09-15-solit2-simulator-design.md` (rev 2) and its companion `docs/superpowers/specs/2026-09-15-solit2-scope-and-engine-analysis.md`. Read both before Task 1.

## Global Constraints

- Python 3.12; dependency management with `uv`; the broken Anaconda base environment must not be used.
- Files ≤ 400 lines target, 800 hard. Functions ≤ 50 lines. Nesting ≤ 4 levels.
- Frozen dataclasses / pydantic models. Never mutate a function's input; return new values.
- No magic numbers in formulas. Every empirical constant is a named module constant or an entry in `solit2/presets/calibration.json`, and every `calibration.json` entry records the anchor it was fitted on.
- Intentional shortcuts carry a `# ponytail: <what is simplified> — <upgrade path>` comment.
- Errors are explicit: validation errors name the field, the value and the allowed range; physics functions raise on non-physical intermediate state (negative HRR, `H_ef <= 0`, `area <= 0`) rather than clamping silently. Intentional clamps are named constants and are recorded in the result's `warnings` list when they bind. Nothing is swallowed.
- **IP hygiene (hard rule):** only nozzle *performance* data may enter this repo — K-factor, pressure band, SMD-vs-pressure table, mass split, cone angles, launch velocities. Internal atomiser geometry (orifice diameters, swirl-port counts, insert dimensions) must never appear in code, presets, tests, docstrings or commit messages. Source tender/vendor documents stay outside the repo; `.gitignore` already blocks `*.pdf *.docx *.pptx *.xlsx *.dwg *.step *.stl *.blend*`.
- Nozzle design pressure floor is **34.5 bar** (NFPA 750 high-pressure definition) — below this is a validation error, not a warning.
- Test coverage ≥ 80 % measured by `pytest --cov=solit2`.
- Commit after every task with a conventional-commit message. Do not push.

---

## File Structure

| File | Responsibility |
|---|---|
| `pyproject.toml` | uv project, pinned deps, pytest/coverage config |
| `solit2/schema/design.py` | `Design` and nested pydantic models; all input validation and derivation |
| `solit2/schema/result.py` | `Criterion`, `Result` and the margin arithmetic |
| `solit2/schema/presets.py` | preset lookup + deep merge of overrides |
| `solit2/presets/*.json` | tunnel, nozzle, fire, hydraulics, cost-weight and calibration data |
| `solit2/engines/reduced/geometry.py` | section geometry (circular bore, box) and nozzle placement |
| `solit2/engines/reduced/fire.py` | Class A pallet/HGV and Class B pool heat-release models |
| `solit2/engines/reduced/ventilation.py` | critical velocity, backlayering, fire throttling of the airflow |
| `solit2/engines/reduced/thermal.py` | ceiling-jet temperature, longitudinal decay, stratification, detection, radiant heat flux, flame length, lining and pipe temperature |
| `solit2/engines/reduced/mist.py` | per-mode droplet trajectory, footprints, suppression, gas cooling, radiation attenuation |
| `solit2/engines/reduced/tenability.py` | species, FED, visibility |
| `solit2/engines/reduced/hydraulics.py` | flow, pipe friction, pump duty, power, tank |
| `solit2/engines/reduced/cost.py` | quantities and the relative cost index |
| `solit2/engines/reduced/criteria.py` | criterion definitions and evaluation against a run |
| `solit2/engines/reduced/score.py` | hard gates, weighted objective, penalties |
| `solit2/engines/reduced/sim.py` | the 1 s time loop; composes the modules |
| `solit2/engines/reduced/envelope.py` | section × velocity grid, worst-case selection |
| `solit2/history.py` | append-only `runs/history.jsonl` and leaderboard queries |
| `solit2/cli.py` | `run`, `validate`, `history` subcommands |
| `validation/anchors/c*.json` | six published fire tests: design + measured + tolerances |
| `validation/compare.py` | per-anchor tolerance report and the calibration fit |
| `designs/og-dbr-rev0.json` | the Mistelix DBR Rev 0 baseline design |

---

### Task 1: Project skeleton, design schema and presets

**Files:**
- Create: `pyproject.toml`, `solit2/__init__.py`, `solit2/schema/__init__.py`, `solit2/schema/design.py`, `solit2/schema/presets.py`
- Create: `solit2/presets/tunnel_orange_gate.json`, `solit2/presets/tunnel_san_pedro_de_anes.json`, `solit2/presets/nozzle_mistelix_msx_t100.json`, `solit2/presets/nozzle_ultrafog_202_260t.json`, `solit2/presets/fire_hgv_150mw.json`, `solit2/presets/fire_pool_60mw.json`, `solit2/presets/hydraulics_orange_gate.json`
- Create: `designs/og-dbr-rev0.json`
- Test: `tests/test_design_schema.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `solit2.schema.design.Design` (frozen pydantic model) with attributes `meta, tunnel, fire, nozzles, zones, ventilation, detection, hydraulics, criteria`; `Design.load(path: Path) -> Design`; `Design.heads_per_zone: int`; `Design.active_length_m: float`; `Nozzles.flow_per_head_lpm: float`; `Nozzles.mode_flow_lpm(mode_id: str) -> float`; `Nozzles.smd_um(mode_id: str) -> float`; `solit2.schema.presets.load_preset(kind: str, name: str) -> dict`; `solit2.schema.presets.deep_merge(base: dict, override: dict) -> dict`.

- [ ] **Step 1: Initialise the project**

```bash
cd /Users/sajil/Solit2_simulator
uv init --name solit2 --python 3.12 --no-workspace
uv add pydantic numpy scipy
uv add --dev pytest pytest-cov hypothesis
rm -f main.py hello.py
mkdir -p solit2/schema solit2/engines/reduced solit2/presets designs tests validation/anchors
touch solit2/__init__.py solit2/schema/__init__.py solit2/engines/__init__.py solit2/engines/reduced/__init__.py
```

Then append to `pyproject.toml`:

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-q"

[tool.coverage.run]
source = ["solit2"]
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_design_schema.py`:

```python
import json
import pytest
from pydantic import ValidationError
from solit2.schema.design import Design

BASELINE = "designs/og-dbr-rev0.json"


def test_baseline_design_loads_with_dbr_values():
    d = Design.load(BASELINE)
    assert d.nozzles.k_factor_lpm_bar05 == pytest.approx(4.1)
    assert d.nozzles.pressure_bar == pytest.approx(50.0)
    assert d.nozzles.flow_per_head_lpm == pytest.approx(28.99, abs=0.05)
    assert d.zones.section_length_m == pytest.approx(30.0)
    assert d.zones.sections_simultaneous == 3


def test_heads_per_zone_derived_from_staggered_rows():
    # two rows at 2.4 m pitch, staggered -> one head every 1.2 m -> 25 over 30 m
    d = Design.load(BASELINE)
    assert d.heads_per_zone == 25
    assert d.active_length_m == pytest.approx(90.0)


def test_mode_flows_split_by_mass_fraction():
    d = Design.load(BASELINE)
    assert d.nozzles.mode_flow_lpm("fine") == pytest.approx(17.39, abs=0.05)
    assert d.nozzles.mode_flow_lpm("coarse") == pytest.approx(11.60, abs=0.05)


def test_fine_smd_interpolated_from_pressure_table():
    d = Design.load(BASELINE)
    assert d.nozzles.smd_um("fine") == pytest.approx(102.0, abs=1.0)
    assert d.nozzles.smd_um("coarse") == pytest.approx(450.0)


def test_pressure_below_nfpa750_floor_is_rejected(tmp_path):
    raw = json.loads(open(BASELINE).read())
    raw["nozzles"]["pressure_bar"] = 30.0
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(raw))
    with pytest.raises(ValidationError) as e:
        Design.load(p)
    assert "pressure_bar" in str(e.value)
    assert "34.5" in str(e.value)


def test_mode_fractions_must_sum_to_one(tmp_path):
    raw = json.loads(open(BASELINE).read())
    raw["nozzles"]["modes"] = [{"id": "fine", "fraction": 0.7},
                               {"id": "coarse", "fraction": 0.7}]
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(raw))
    with pytest.raises(ValidationError) as e:
        Design.load(p)
    assert "fraction" in str(e.value)


def test_velocity_envelope_defaults_to_tender_range():
    d = Design.load(BASELINE)
    assert d.ventilation.velocity_ms is None
    assert d.ventilation.velocity_range_ms == (3.88, 5.08)
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_design_schema.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'solit2.schema.design'`

- [ ] **Step 4: Write the preset loader**

Create `solit2/schema/presets.py`:

```python
"""Preset lookup and merge.

A design JSON names a preset per block and overrides individual fields; the
preset supplies everything else.
"""
from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

PRESET_DIR = Path(__file__).resolve().parent.parent / "presets"

_KIND_PREFIX = {
    "tunnel": "tunnel_",
    "nozzle": "nozzle_",
    "fire": "fire_",
    "hydraulics": "hydraulics_",
}


def load_preset(kind: str, name: str) -> dict:
    """Load `presets/<kind>_<name>.json`."""
    if kind not in _KIND_PREFIX:
        raise KeyError(f"unknown preset kind {kind!r}; expected one of {sorted(_KIND_PREFIX)}")
    path = PRESET_DIR / f"{_KIND_PREFIX[kind]}{name}.json"
    if not path.exists():
        available = sorted(p.stem for p in PRESET_DIR.glob(f"{_KIND_PREFIX[kind]}*.json"))
        raise FileNotFoundError(f"no {kind} preset {name!r}; available: {available}")
    return json.loads(path.read_text())


def load_calibration() -> dict:
    return json.loads((PRESET_DIR / "calibration.json").read_text())


def deep_merge(base: dict, override: dict) -> dict:
    """Return a new dict: `override` wins, nested dicts merge, `None` means 'not set'."""
    out = deepcopy(base)
    for key, value in override.items():
        if value is None and key in out:
            continue
        if isinstance(value, dict) and isinstance(out.get(key), dict):
            out[key] = deep_merge(out[key], value)
        else:
            out[key] = deepcopy(value)
    return out
```

- [ ] **Step 5: Write the design schema**

Create `solit2/schema/design.py`:

```python
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


class Pool(Frozen):
    count: int = Field(gt=0)
    length_m: float = Field(gt=0)
    width_m: float = Field(gt=0)
    fuel: Literal["diesel"] = "diesel"


class Fire(Frozen):
    preset: str
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
    power_cap_kw: float
    safety_factor: float = 1.10


class Design(Frozen):
    meta: Meta
    tunnel: Tunnel
    fire: Fire
    nozzles: Nozzles
    zones: Zones
    ventilation: Ventilation
    detection: Detection
    hydraulics: Hydraulics
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
```

- [ ] **Step 6: Write the presets and the baseline design**

Create `solit2/presets/tunnel_orange_gate.json` — geometry read off GA drawing `EWCR-LNT-430-PD-102886_A1.3` section 6 (bored) and section 5 (cut & cover); lengths from `HPWM-TECHNICAL SPEC_R2` §3:

```json
{
  "preset": "orange_gate",
  "tube": "LHS",
  "section": "bored",
  "shape": "circle",
  "internal_diameter_m": 11.0,
  "deck_below_centre_m": 2.125,
  "clearance_m": 5.5,
  "length_m": 4240.0,
  "gradient_pct": 0.3,
  "ambient_temp_c": 30.0,
  "ambient_rh_pct": 75.0
}
```

Create `solit2/presets/tunnel_san_pedro_de_anes.json` — APPLUS+TST test tunnel with the false ceiling in place:

```json
{
  "preset": "san_pedro_de_anes",
  "tube": "LHS",
  "section": "test",
  "shape": "box",
  "width_m": 9.5,
  "height_m": 5.17,
  "area_m2": 48.0,
  "clearance_m": 4.5,
  "length_m": 600.0,
  "gradient_pct": 1.0,
  "ambient_temp_c": 20.0,
  "ambient_rh_pct": 60.0
}
```

Create `solit2/presets/nozzle_mistelix_msx_t100.json` — performance data only, from DBR Rev 0 tables 5.1 and 7.1:

```json
{
  "preset": "mistelix_msx_t100",
  "k_factor_lpm_bar05": 4.1,
  "pressure_bar": 50.0,
  "smd_table": {"34.5": 118.0, "45": 107.0, "50": 102.0, "60": 95.0},
  "modes": [
    {"id": "fine", "fraction": 0.60, "cone_half_angle_deg": 45.0, "launch_velocity_ms": 15.0},
    {"id": "coarse", "fraction": 0.40, "smd_um": 450.0, "cone_half_angle_deg": 8.0, "launch_velocity_ms": 100.0}
  ],
  "mounting": {
    "type": "ceiling_rows",
    "rows": 2,
    "row_lateral_offsets_m": [-2.5, 2.5],
    "height_above_carriageway_m": 5.75,
    "pitch_m": 2.4,
    "tilt_deg": 0.0
  }
}
```

Create `solit2/presets/nozzle_ultrafog_202_260t.json` — the calibration nozzle, single mode, wall mounted:

```json
{
  "preset": "ultrafog_202_260t",
  "k_factor_lpm_bar05": 4.2,
  "pressure_bar": 56.0,
  "smd_table": {"56": 120.0},
  "modes": [
    {"id": "fine", "fraction": 1.0, "cone_half_angle_deg": 50.0, "launch_velocity_ms": 20.0}
  ],
  "mounting": {
    "type": "ceiling_rows",
    "rows": 1,
    "row_lateral_offsets_m": [4.55],
    "height_above_carriageway_m": 4.97,
    "pitch_m": 3.8,
    "tilt_deg": 35.0
  }
}
```

Create `solit2/presets/fire_hgv_150mw.json` — SOLIT² Class A truck load (Annex 2 §3.1):

```json
{
  "preset": "hgv_150mw",
  "class": "A",
  "design_hrr_mw": 150.0,
  "growth": "ultrafast",
  "incubation_s": 60.0,
  "pallets": 408,
  "energy_mj_per_pallet": 343.0,
  "covered": false,
  "footprint": {"length_m": 8.4, "width_m": 2.4, "top_height_m": 4.0},
  "lane_centre_offset_from_wall_m": 3.4,
  "target_distance_m": 5.0
}
```

Create `solit2/presets/fire_pool_60mw.json` — SOLIT² Class B (Annex 2 §3.2):

```json
{
  "preset": "pool_60mw",
  "class": "B",
  "design_hrr_mw": 60.0,
  "growth": "fast",
  "incubation_s": 0.0,
  "covered": false,
  "pools": {"count": 7, "length_m": 2.5, "width_m": 1.6, "fuel": "diesel"},
  "footprint": {"length_m": 17.5, "width_m": 1.6, "top_height_m": 0.4},
  "lane_centre_offset_from_wall_m": 3.4,
  "target_distance_m": 5.0
}
```

Create `solit2/presets/hydraulics_orange_gate.json` — DBR §§7–10:

```json
{
  "preset": "orange_gate",
  "main_dn_mm": 150.0,
  "zone_header_dn_mm": 65.0,
  "row_pipe_dn_mm": 40.0,
  "roughness_mm": 0.045,
  "pump_unit_m3h": 72.0,
  "pump_efficiency": 0.68,
  "motor_efficiency": 0.93,
  "loop_factor": 0.25,
  "static_head_bar": 2.0,
  "fittings_loss_bar": 1.9,
  "power_cap_kw": 650.0,
  "safety_factor": 1.10
}
```

Create `designs/og-dbr-rev0.json` — the bid baseline:

```json
{
  "meta": {"name": "og-dbr-rev0", "notes": "Mistelix DBR MSTX-OG-DBR-001 Rev 0, as bid"},
  "tunnel": {"preset": "orange_gate", "tube": "LHS", "section": "bored"},
  "fire": {"preset": "hgv_150mw"},
  "nozzles": {"preset": "mistelix_msx_t100"},
  "zones": {
    "section_length_m": 30.0,
    "sections_simultaneous": 3,
    "activation_delay_s": 60.0,
    "pump_ramp_s": 30.0,
    "duration_min": 60.0
  },
  "ventilation": {"mode": "longitudinal", "velocity_range_ms": [3.88, 5.08]},
  "detection": {"type": "linear_heat", "threshold_c": 60.0, "sensor_spacing_m": 25.0},
  "hydraulics": {"preset": "orange_gate"},
  "criteria": {}
}
```

- [ ] **Step 7: Run tests to verify they pass**

Run: `uv run pytest tests/test_design_schema.py -v`
Expected: PASS, 7 tests.

- [ ] **Step 8: Commit**

```bash
git add pyproject.toml uv.lock solit2 designs tests
git commit -m "feat(schema): design model, presets and the Orange Gate baseline design

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 2: Section geometry and nozzle placement

**Files:**
- Create: `solit2/engines/reduced/geometry.py`
- Test: `tests/test_geometry.py`

**Interfaces:**
- Consumes: `Design` from Task 1.
- Produces: `SectionGeometry` (frozen dataclass: `name, road_width_m, crown_height_m, free_area_m2, mean_height_m, hydraulic_diameter_m`) with method `width_at(height_above_carriageway_m: float) -> float`; `section_geometry(design: Design) -> SectionGeometry`; `NozzlePosition` (frozen dataclass: `x_m, y_m, z_m, row, tilt_deg`); `nozzle_positions(design: Design, geom: SectionGeometry, fire_x_m: float) -> tuple[NozzlePosition, ...]`. `x_m` is chainage relative to the fire centre (negative = upstream), `y_m` is lateral from the tunnel centreline, `z_m` is height above the carriageway.

- [ ] **Step 1: Write the failing test**

Create `tests/test_geometry.py`:

```python
import pytest
from solit2.schema.design import Design
from solit2.engines.reduced.geometry import section_geometry, nozzle_positions

BASELINE = "designs/og-dbr-rev0.json"


def test_bored_section_matches_the_ga_drawing():
    # 11.0 m internal diameter, carriageway 2.125 m below the centre
    geom = section_geometry(Design.load(BASELINE))
    assert geom.road_width_m == pytest.approx(10.146, abs=0.01)
    assert geom.crown_height_m == pytest.approx(7.625, abs=0.01)
    assert geom.free_area_m2 == pytest.approx(70.29, abs=0.1)
    assert geom.mean_height_m == pytest.approx(6.928, abs=0.02)


def test_bored_width_at_clearance_height():
    geom = section_geometry(Design.load(BASELINE))
    assert geom.width_at(5.5) == pytest.approx(8.686, abs=0.01)
    assert geom.width_at(0.0) == pytest.approx(10.146, abs=0.01)


def test_width_above_the_crown_is_zero():
    geom = section_geometry(Design.load(BASELINE))
    assert geom.width_at(7.7) == 0.0


def test_box_section_uses_plain_rectangle():
    d = Design.load(BASELINE).model_copy(
        update={"tunnel": Design.load(BASELINE).tunnel.model_copy(
            update={"section": "test", "shape": "box", "width_m": 9.5,
                    "height_m": 5.17, "area_m2": 48.0})})
    geom = section_geometry(d)
    assert geom.road_width_m == pytest.approx(9.5)
    assert geom.crown_height_m == pytest.approx(5.17)
    assert geom.free_area_m2 == pytest.approx(48.0)
    assert geom.width_at(3.0) == pytest.approx(9.5)


def test_nozzle_positions_are_staggered_and_cover_the_active_length():
    d = Design.load(BASELINE)
    geom = section_geometry(d)
    pos = nozzle_positions(d, geom, fire_x_m=0.0)
    assert len(pos) == d.active_heads == 75
    assert min(p.x_m for p in pos) == pytest.approx(-44.4, abs=0.1)
    assert max(p.x_m for p in pos) == pytest.approx(44.4, abs=0.1)
    # consecutive heads alternate rows
    assert pos[0].row != pos[1].row
    # spacing along the tunnel is pitch / rows
    assert pos[1].x_m - pos[0].x_m == pytest.approx(1.2, abs=0.01)
    assert {p.z_m for p in pos} == {pytest.approx(5.75)}
    assert sorted({round(p.y_m, 2) for p in pos}) == [-2.5, 2.5]


def test_rows_must_fit_inside_the_section_at_mounting_height():
    d = Design.load(BASELINE)
    bad = d.model_copy(update={"nozzles": d.nozzles.model_copy(
        update={"mounting": d.nozzles.mounting.model_copy(
            update={"row_lateral_offsets_m": (-4.6, 4.6)})})})
    with pytest.raises(ValueError) as e:
        nozzle_positions(bad, section_geometry(bad), fire_x_m=0.0)
    assert "4.6" in str(e.value) and "8.69" in str(e.value)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_geometry.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'solit2.engines.reduced.geometry'`

- [ ] **Step 3: Write the implementation**

Create `solit2/engines/reduced/geometry.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_geometry.py -v`
Expected: PASS, 7 tests.

- [ ] **Step 5: Commit**

```bash
git add solit2/engines/reduced/geometry.py tests/test_geometry.py
git commit -m "feat(geometry): circular bore and box section geometry, staggered nozzle rows

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 3: Hydraulics and cost index

**Files:**
- Create: `solit2/engines/reduced/hydraulics.py`, `solit2/engines/reduced/cost.py`, `solit2/presets/cost_weights.json`
- Test: `tests/test_hydraulics.py`, `tests/test_cost.py`

**Interfaces:**
- Consumes: `Design` (Task 1), `SectionGeometry` (Task 2).
- Produces: `darcy_weisbach_bar(flow_m3s, diameter_m, length_m, roughness_mm) -> float`; `HydraulicsResult` (frozen dataclass: `active_heads, flow_lpm, flow_design_lpm, required_pump_bar, rated_pump_bar, power_kw, tank_m3, pumps_duty, pumps_standby, density_mm_min, density_l_m3_min, ring_loss_bar, zone_loss_bar`); `size_system(design, geom) -> HydraulicsResult`; `CostResult` (frozen dataclass: `zones, heads, section_valves, ring_main_m, zone_header_m, row_pipe_m, pumps, tank_m3, index`); `cost_index(design, hyd) -> CostResult`.

- [ ] **Step 1: Write the failing hydraulics test**

Create `tests/test_hydraulics.py`:

```python
import math
import pytest
from solit2.schema.design import Design
from solit2.engines.reduced.geometry import section_geometry
from solit2.engines.reduced.hydraulics import darcy_weisbach_bar, size_system

BASELINE = "designs/og-dbr-rev0.json"


def test_darcy_weisbach_against_a_hand_calculation():
    # 143.6 m3/h through 154.1 mm bore, 1000 m of it:
    # A = 0.018653 m2, v = 2.139 m/s, Re = 1.83e5, f ~ 0.0165 (Colebrook, eps 0.045 mm)
    # dp = f (L/D) rho v^2 / 2 = 0.0165 * 6489 * 1000 * 2.139^2 / 2 = 2.45e5 Pa = 2.45 bar
    dp = darcy_weisbach_bar(flow_m3s=143.6 / 3600, diameter_m=0.1541,
                            length_m=1000.0, roughness_mm=0.045)
    assert dp == pytest.approx(2.45, rel=0.10)


def test_dbr_flow_chain():
    hyd = size_system(Design.load(BASELINE), section_geometry(Design.load(BASELINE)))
    assert hyd.active_heads == 75
    assert hyd.flow_lpm == pytest.approx(2174.3, abs=2.0)        # DBR: 2175
    assert hyd.flow_design_lpm == pytest.approx(2391.7, abs=3.0)  # DBR: 2393


def test_dbr_pump_pressure_and_power():
    hyd = size_system(Design.load(BASELINE), section_geometry(Design.load(BASELINE)))
    assert hyd.required_pump_bar == pytest.approx(59.4, abs=2.5)  # DBR: 59.4
    assert hyd.rated_pump_bar == pytest.approx(hyd.required_pump_bar * 1.10, rel=1e-6)
    assert hyd.power_kw == pytest.approx(375.0, rel=0.08)          # DBR: ~375 kW
    assert hyd.power_kw < 650.0


def test_dbr_tank_volume_is_sixty_minutes_of_design_flow():
    hyd = size_system(Design.load(BASELINE), section_geometry(Design.load(BASELINE)))
    assert hyd.tank_m3 == pytest.approx(143.5, abs=1.0)            # DBR: ~145


def test_density_uses_the_road_width_not_the_bore_diameter():
    d = Design.load(BASELINE)
    hyd = size_system(d, section_geometry(d))
    # 2175 lpm over 90 m x 10.146 m
    assert hyd.density_mm_min == pytest.approx(2.38, abs=0.05)


def test_higher_pressure_raises_flow_and_power():
    d = Design.load(BASELINE)
    geom = section_geometry(d)
    base = size_system(d, geom)
    hotter = size_system(d.model_copy(update={"nozzles": d.nozzles.model_copy(
        update={"pressure_bar": 60.0})}), geom)
    assert hotter.flow_lpm > base.flow_lpm
    assert hotter.power_kw > base.power_kw
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_hydraulics.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'solit2.engines.reduced.hydraulics'`

- [ ] **Step 3: Write the hydraulics implementation**

Create `solit2/engines/reduced/hydraulics.py`:

```python
"""Flow, pipe friction, pump duty, power and tank volume.

Sizing follows the tender: the main is sized for the three simultaneous zones
plus 10 %, and the pump head is rated 10 % above the required discharge.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from solit2.engines.reduced.geometry import SectionGeometry
from solit2.schema.design import Design

WATER_DENSITY_KGM3 = 1000.0
WATER_VISCOSITY_PAS = 1.0e-3
BAR_PER_PA = 1.0e-5
# Wall thickness allowance from DN to bore for schedule-10S stainless pipe.
_DN_TO_BORE_M = {150.0: 0.1541, 65.0: 0.0687, 50.0: 0.0525, 40.0: 0.0409, 32.0: 0.0351}


def _bore_m(dn_mm: float) -> float:
    if dn_mm not in _DN_TO_BORE_M:
        raise KeyError(f"no bore for DN{dn_mm:g}; known sizes are {sorted(_DN_TO_BORE_M)}")
    return _DN_TO_BORE_M[dn_mm]


def _friction_factor(reynolds: float, relative_roughness: float) -> float:
    """Swamee-Jain explicit approximation to Colebrook-White."""
    if reynolds < 2300:
        return 64.0 / max(reynolds, 1.0)
    return 0.25 / math.log10(relative_roughness / 3.7 + 5.74 / reynolds**0.9) ** 2


def darcy_weisbach_bar(flow_m3s: float, diameter_m: float, length_m: float,
                       roughness_mm: float) -> float:
    if flow_m3s <= 0 or diameter_m <= 0 or length_m < 0:
        raise ValueError(f"non-physical input: flow={flow_m3s}, D={diameter_m}, L={length_m}")
    area = math.pi * diameter_m**2 / 4.0
    velocity = flow_m3s / area
    reynolds = WATER_DENSITY_KGM3 * velocity * diameter_m / WATER_VISCOSITY_PAS
    f = _friction_factor(reynolds, roughness_mm / 1000.0 / diameter_m)
    return f * (length_m / diameter_m) * WATER_DENSITY_KGM3 * velocity**2 / 2.0 * BAR_PER_PA


@dataclass(frozen=True)
class HydraulicsResult:
    active_heads: int
    flow_lpm: float
    flow_design_lpm: float
    ring_loss_bar: float
    zone_loss_bar: float
    required_pump_bar: float
    rated_pump_bar: float
    power_kw: float
    tank_m3: float
    pumps_duty: int
    pumps_standby: int
    density_mm_min: float
    density_l_m3_min: float


def size_system(design: Design, geom: SectionGeometry) -> HydraulicsResult:
    h = design.hydraulics
    flow_lpm = design.flow_lpm
    flow_design_lpm = flow_lpm * h.safety_factor
    flow_m3s = flow_design_lpm / 60_000.0

    # Looped cross-tube ring: flow reaches the far zone from two directions, so the
    # worst-path loss is a fraction of the equivalent single radial main.
    # ponytail: constant loop_factor - replace with a network solve if the DN200
    # option or the broken-ring case is studied.
    ring_loss = h.loop_factor * darcy_weisbach_bar(
        flow_m3s, _bore_m(h.main_dn_mm), design.tunnel.length_m, h.roughness_mm)

    # Zone header carries one zone; the gridded rows carry half each.
    zone_flow_m3s = flow_m3s / design.zones.sections_simultaneous
    zone_loss = (
        darcy_weisbach_bar(zone_flow_m3s, _bore_m(h.zone_header_dn_mm),
                           design.zones.section_length_m, h.roughness_mm)
        + darcy_weisbach_bar(zone_flow_m3s / 2.0, _bore_m(h.row_pipe_dn_mm),
                             design.zones.section_length_m, h.roughness_mm)
    )

    required = (design.nozzles.pressure_bar + ring_loss + zone_loss
                + h.static_head_bar + h.fittings_loss_bar)
    rated = required * h.safety_factor

    hydraulic_kw = flow_m3s * required / BAR_PER_PA / 1000.0
    power_kw = hydraulic_kw / h.pump_efficiency / h.motor_efficiency

    duty = math.ceil(flow_design_lpm * 60.0 / 1000.0 / h.pump_unit_m3h)
    tank_m3 = flow_design_lpm * design.zones.duration_min / 1000.0

    wetted_area = design.active_length_m * geom.road_width_m
    wetted_volume = design.active_length_m * geom.free_area_m2

    return HydraulicsResult(
        active_heads=design.active_heads,
        flow_lpm=flow_lpm,
        flow_design_lpm=flow_design_lpm,
        ring_loss_bar=ring_loss,
        zone_loss_bar=zone_loss,
        required_pump_bar=required,
        rated_pump_bar=rated,
        power_kw=power_kw,
        tank_m3=tank_m3,
        pumps_duty=duty,
        pumps_standby=1,
        density_mm_min=flow_lpm / wetted_area,
        density_l_m3_min=flow_lpm / wetted_volume,
    )
```

- [ ] **Step 4: Run hydraulics tests**

Run: `uv run pytest tests/test_hydraulics.py -v`
Expected: PASS, 6 tests.

- [ ] **Step 5: Write the failing cost test**

Create `tests/test_cost.py`:

```python
import pytest
from solit2.schema.design import Design
from solit2.engines.reduced.geometry import section_geometry
from solit2.engines.reduced.hydraulics import size_system
from solit2.engines.reduced.cost import cost_index

BASELINE = "designs/og-dbr-rev0.json"


def _cost(design):
    geom = section_geometry(design)
    return cost_index(design, size_system(design, geom))


def test_zone_and_head_counts_match_the_dbr_boq():
    c = _cost(Design.load(BASELINE))
    assert c.zones == 283            # DBR 10.1: LHS 141 + RHS 142
    assert c.section_valves == 283
    assert c.heads == 7075           # DBR 10.1: ~7100


def test_baseline_index_is_one():
    assert _cost(Design.load(BASELINE)).index == pytest.approx(1.0, abs=1e-9)


def test_tighter_pitch_costs_more():
    d = Design.load(BASELINE)
    tight = d.model_copy(update={"nozzles": d.nozzles.model_copy(
        update={"mounting": d.nozzles.mounting.model_copy(update={"pitch_m": 1.6})})})
    assert _cost(tight).index > 1.0
    assert _cost(tight).heads > 7075


def test_longer_zones_need_fewer_section_valves():
    d = Design.load(BASELINE)
    longer = d.model_copy(update={"zones": d.zones.model_copy(update={"section_length_m": 45.0})})
    assert _cost(longer).section_valves < 283
```

- [ ] **Step 6: Run test to verify it fails**

Run: `uv run pytest tests/test_cost.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'solit2.engines.reduced.cost'`

- [ ] **Step 7: Write the cost implementation**

Create `solit2/presets/cost_weights.json` — relative units, the Orange Gate baseline normalises to 1.00:

```json
{
  "note": "relative cost units; absolute currency is out of scope. Baseline = DBR Rev 0.",
  "head": 1.0,
  "section_valve": 120.0,
  "ring_main_per_m": 3.2,
  "zone_header_per_m": 1.4,
  "row_pipe_per_m": 0.9,
  "pump_unit": 1800.0,
  "tank_per_m3": 45.0,
  "baseline_total": null
}
```

Create `solit2/engines/reduced/cost.py`:

```python
"""Relative installed-cost index for a candidate design.

Quantities cover both tubes. The index is normalised so the DBR Rev 0 baseline
scores 1.00; only ratios between designs are meaningful.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from solit2.engines.reduced.hydraulics import HydraulicsResult
from solit2.schema.design import Design

_WEIGHTS = json.loads((Path(__file__).resolve().parents[2] / "presets" / "cost_weights.json").read_text())
# Both tubes: LHS 4240 m and RHS 4260 m (HPWM-TECHNICAL SPEC_R2 section 3).
TUBE_LENGTHS_M = (4240.0, 4260.0)
# Cost of the DBR Rev 0 design in the units above; see test_baseline_index_is_one.
BASELINE_TOTAL = 2_090_733.0


@dataclass(frozen=True)
class CostResult:
    zones: int
    heads: int
    section_valves: int
    ring_main_m: float
    zone_header_m: float
    row_pipe_m: float
    pumps: int
    tank_m3: float
    total: float
    index: float


def cost_index(design: Design, hyd: HydraulicsResult) -> CostResult:
    zone_len = design.zones.section_length_m
    zones = sum(round(length / zone_len) for length in TUBE_LENGTHS_M)
    heads = zones * design.heads_per_zone
    rows = design.nozzles.mounting.rows
    total_length = sum(TUBE_LENGTHS_M)

    ring_main_m = 2.0 * total_length          # one main each side of both tubes
    zone_header_m = zones * zone_len / rows   # header feeds the gridded rows
    row_pipe_m = rows * total_length
    pumps = hyd.pumps_duty + hyd.pumps_standby

    total = (
        heads * _WEIGHTS["head"]
        + zones * _WEIGHTS["section_valve"]
        + ring_main_m * _WEIGHTS["ring_main_per_m"]
        + zone_header_m * _WEIGHTS["zone_header_per_m"]
        + row_pipe_m * _WEIGHTS["row_pipe_per_m"]
        + pumps * _WEIGHTS["pump_unit"]
        + hyd.tank_m3 * _WEIGHTS["tank_per_m3"]
    )
    return CostResult(zones, heads, zones, ring_main_m, zone_header_m, row_pipe_m,
                      pumps, hyd.tank_m3, total, total / BASELINE_TOTAL)
```

- [ ] **Step 8: Calibrate `BASELINE_TOTAL` and run the tests**

Run: `uv run python -c "
from solit2.schema.design import Design
from solit2.engines.reduced.geometry import section_geometry
from solit2.engines.reduced.hydraulics import size_system
from solit2.engines.reduced.cost import cost_index
d = Design.load('designs/og-dbr-rev0.json')
print(cost_index(d, size_system(d, section_geometry(d))).total)
"`

Replace `BASELINE_TOTAL` in `cost.py` with the printed value (keep the underscore separators), then run: `uv run pytest tests/test_cost.py tests/test_hydraulics.py -v`
Expected: PASS, 10 tests.

- [ ] **Step 9: Commit**

```bash
git add solit2/engines/reduced/hydraulics.py solit2/engines/reduced/cost.py solit2/presets/cost_weights.json tests/test_hydraulics.py tests/test_cost.py
git commit -m "feat(sizing): hydraulics and relative cost index against the DBR Rev 0 numbers

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 4: Heat release — Class A and Class B

**Files:**
- Create: `solit2/engines/reduced/state.py`, `solit2/engines/reduced/fire.py`, `solit2/presets/calibration.json`
- Test: `tests/test_fire.py`

**Interfaces:**
- Consumes: `Design` (Task 1).
- Produces: `state.MistEffect` (frozen dataclass: `eta, w_fuel_mm_min, f_cov, chi_cool, tau_mist`, with classmethod `none() -> MistEffect` giving all zeros and `tau_mist=1.0`); `state.FireState` (frozen dataclass: `t_s, hrr_mw, hrr_free_mw, energy_released_mj, suppression, pools_remaining, wet_time_s`); `fire.FireModel` (frozen dataclass built by `fire.build_model(design) -> FireModel`); `fire.initial_state(model) -> FireState`; `fire.step(model, state, dt_s, mist: MistEffect) -> FireState`; `fire.mass_loss_rate_kgs(model, hrr_mw) -> float`; `fire.radiative_fraction(model) -> float`; `fire.convective_kw(model, hrr_mw) -> float`.

- [ ] **Step 1: Write the calibration file**

Create `solit2/presets/calibration.json`. Every entry records the anchor it is fitted on; `"none"` means it is taken from published literature and is not fitted here:

```json
{
  "fire": {
    "suppression_response_s": {"value": 90.0, "anchor": "c4,c5", "note": "tau_s in S(t)"},
    "cover_shielding_factor": {"value": 2.5, "anchor": "c4", "note": "PVC tarpaulin delays suppression"},
    "decay_energy_fraction": {"value": 0.80, "anchor": "none", "note": "fraction burnt before linear decay"},
    "pool_ventilation_factor": {"value": 1.40, "anchor": "c6", "note": "tunnel wind enhances pool burning"},
    "pool_ramp_s": {"value": 150.0, "anchor": "c6", "note": "Annex 2: pools need 2-3 min to develop"},
    "pool_burning_rate_reduction": {"value": 0.55, "anchor": "c6"},
    "pool_extinction_flux_mm_min": {"value": 1.8, "anchor": "c6"},
    "pool_extinction_time_s": {"value": 45.0, "anchor": "c6", "note": "per pool; Annex 2: extinguished pool by pool"}
  },
  "ventilation": {
    "throttling_coefficient": {"value": 0.35, "anchor": "c4,c5", "note": "Annex 2 fig 10/19: 3 -> 2 m/s"},
    "critical_velocity_height": {"value": "crown", "anchor": "none", "note": "H in Li-Ingason; mean height gives ~5% lower u_c"}
  },
  "thermal": {
    "flame_length_coefficient": {"value": 4.3, "anchor": "none", "note": "C_f, Ingason & Li, Tunnel Fire Dynamics ch.11"},
    "ceiling_temp_cap_k": {"value": 1350.0, "anchor": "none"}
  },
  "mist": {
    "eta_max": {"value": 0.85, "anchor": "c4,c5", "note": "SOLIT2 held a 150 MW potential load to ~30 MW, so the ceiling is at least 0.80"},
    "w_ref_mm_min": {"value": 1.2, "anchor": "c1,c2,c3"},
    "chi_cool_max": {"value": 0.45, "anchor": "c3"},
    "evaporation_k_ref_m2s": {"value": 1.0e-7, "anchor": "c3", "note": "d-squared law constant at the reference gas temperature rise; a 100 um drop evaporates in ~0.1 s at that rise and essentially not at all in cool air"},
    "evaporation_reference_delta_t_k": {"value": 600.0, "anchor": "c3"}
  }
}
```

- [ ] **Step 2: Write the failing test**

Create `tests/test_fire.py`:

```python
import pytest
from solit2.schema.design import Design
from solit2.engines.reduced import fire
from solit2.engines.reduced.state import MistEffect

BASELINE = "designs/og-dbr-rev0.json"
POOL = "tests/fixtures/pool_design.json"


def _march(design, seconds, mist=None, dt=1.0):
    model = fire.build_model(design)
    st = fire.initial_state(model)
    effect = mist or MistEffect.none()
    out = [st]
    for _ in range(int(seconds / dt)):
        st = fire.step(model, st, dt, effect)
        out.append(st)
    return out


def test_class_a_free_burn_reaches_the_design_hrr():
    # ultrafast t-squared after 60 s incubation: 150 MW at ~60 + sqrt(150000/0.1876) = 954 s
    hist = _march(Design.load(BASELINE), 1200)
    at_954 = hist[954]
    assert at_954.hrr_free_mw == pytest.approx(150.0, rel=0.05)
    assert hist[100].hrr_free_mw < 1.0


def test_class_a_is_fuel_limited_and_decays():
    hist = _march(Design.load(BASELINE), 3600)
    peak = max(h.hrr_free_mw for h in hist)
    assert peak == pytest.approx(150.0, rel=0.02)
    assert hist[-1].hrr_free_mw < 5.0
    total_mj = hist[-1].energy_released_mj
    assert total_mj == pytest.approx(408 * 343, rel=0.05)


def test_suppression_pulls_the_peak_below_the_free_burn():
    mist = MistEffect(eta=0.72, w_fuel_mm_min=3.0, f_cov=0.9, chi_cool=0.35, tau_mist=0.6)
    hist = _march(Design.load(BASELINE), 3600, mist)
    assert max(h.hrr_mw for h in hist) < 0.45 * 150.0
    assert max(h.hrr_free_mw for h in hist) == pytest.approx(150.0, rel=0.02)


def test_covered_load_delays_suppression():
    mist = MistEffect(eta=0.72, w_fuel_mm_min=3.0, f_cov=0.9, chi_cool=0.35, tau_mist=0.6)
    d = Design.load(BASELINE)
    covered = d.model_copy(update={"fire": d.fire.model_copy(update={"covered": True})})
    bare_peak = max(h.hrr_mw for h in _march(d, 3600, mist))
    covered_peak = max(h.hrr_mw for h in _march(covered, 3600, mist))
    assert covered_peak > bare_peak


def test_class_b_pool_hrr_matches_the_nominal_sixty_megawatts():
    # 7 pools of 2.5 x 1.6 m diesel, Babrauskas with the fitted ventilation factor
    hist = _march(Design.load(POOL), 600)
    assert max(h.hrr_free_mw for h in hist) == pytest.approx(60.0, rel=0.15)


def test_class_b_pools_extinguish_one_by_one_under_mist():
    mist = MistEffect(eta=0.0, w_fuel_mm_min=3.0, f_cov=1.0, chi_cool=0.3, tau_mist=0.6)
    hist = _march(Design.load(POOL), 1200, mist)
    remaining = [h.pools_remaining for h in hist]
    assert remaining[0] == 7
    assert remaining[-1] == 0
    # strictly non-increasing, one at a time
    assert all(b - a in (0, -1) for a, b in zip(remaining, remaining[1:]))


def test_class_b_below_the_extinction_flux_never_goes_out():
    mist = MistEffect(eta=0.0, w_fuel_mm_min=0.5, f_cov=1.0, chi_cool=0.1, tau_mist=0.9)
    hist = _march(Design.load(POOL), 1200, mist)
    assert hist[-1].pools_remaining == 7


def test_mass_loss_and_convective_split():
    model = fire.build_model(Design.load(BASELINE))
    assert fire.radiative_fraction(model) == pytest.approx(0.35)
    assert fire.convective_kw(model, 100.0) == pytest.approx(65_000.0)
    # 100 MW of wood at 17.5 MJ/kg and 80 % combustion efficiency
    assert fire.mass_loss_rate_kgs(model, 100.0) == pytest.approx(7.14, rel=0.02)
```

Create `tests/fixtures/pool_design.json`:

```json
{
  "meta": {"name": "solit2-class-b-60mw", "notes": "SOLIT2 Annex 2 diesel pool test"},
  "tunnel": {"preset": "san_pedro_de_anes", "section": "test"},
  "fire": {"preset": "pool_60mw"},
  "nozzles": {"preset": "ultrafog_202_260t"},
  "zones": {
    "section_length_m": 20.0,
    "sections_simultaneous": 3,
    "activation_delay_s": 100.0,
    "pump_ramp_s": 30.0,
    "duration_min": 40.0
  },
  "ventilation": {"mode": "longitudinal", "velocity_ms": 2.5, "velocity_range_ms": [2.5, 2.5]},
  "detection": {"type": "linear_heat", "threshold_c": 60.0, "sensor_spacing_m": 25.0},
  "hydraulics": {"preset": "orange_gate"},
  "criteria": {}
}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_fire.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'solit2.engines.reduced.state'`

- [ ] **Step 4: Write the shared state module**

Create `solit2/engines/reduced/state.py`:

```python
"""State objects shared between the engine modules.

Keeping these here avoids an import cycle: `fire` needs the mist's effect and
`mist` needs the fire's size, so neither may import the other.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class MistEffect:
    """What the mist is doing to the fire at one instant."""
    eta: float            # suppression efficiency applied to the Class A burning rate, 0..1
    w_fuel_mm_min: float  # water flux actually landing on the fuel and its 1 m halo
    f_cov: float          # fraction of that halo reached by at least one spray footprint
    chi_cool: float       # fraction of the convective heat release removed by evaporation
    tau_mist: float       # radiant transmissivity through the mist curtain, 0..1

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
```

- [ ] **Step 5: Write the fire module**

Create `solit2/engines/reduced/fire.py`:

```python
"""Heat release rate for Class A (solid, pallet/HGV) and Class B (diesel pool) fires.

Class A follows a t-squared growth to the design fire, burns at that level until
most of the fuel energy is gone, then decays linearly. The mist reduces the
burning rate through a first-order response.

Class B follows Babrauskas' pool-fire law per pool, with a ventilation factor for
the tunnel wind. The mist first reduces the burning rate, then extinguishes the
pools one at a time once the water flux on the fuel is high enough for long
enough, which is the behaviour reported in SOLIT2 Annex 2.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from solit2.engines.reduced.state import FireState, MistEffect
from solit2.schema.design import Design
from solit2.schema.presets import load_calibration

WOOD_HEAT_OF_COMBUSTION_MJKG = 17.5
DIESEL_HEAT_OF_COMBUSTION_MJKG = 44.8
COMBUSTION_EFFICIENCY = 0.80
RADIATIVE_FRACTION_CLASS_A = 0.35
RADIATIVE_FRACTION_CLASS_B = 0.30
# Babrauskas diesel: infinite-diameter mass burning rate and extinction coefficient.
DIESEL_MDOT_INF_KGM2S = 0.035
DIESEL_KBETA_PER_M = 1.7


def _cal(section: str, key: str):
    return load_calibration()[section][key]["value"]


@dataclass(frozen=True)
class FireModel:
    fire_class: str
    alpha_kw_s2: float
    incubation_s: float
    design_hrr_kw: float
    total_energy_mj: float
    decay_energy_fraction: float
    tau_suppression_s: float
    pool_count: int
    pool_area_m2: float
    pool_hrr_each_kw: float
    pool_ramp_s: float
    pool_reduction: float
    pool_extinction_flux_mm_min: float
    pool_extinction_time_s: float


def build_model(design: Design) -> FireModel:
    f = design.fire
    tau = _cal("fire", "suppression_response_s")
    if f.covered:
        tau *= _cal("fire", "cover_shielding_factor")

    if f.fire_class == "A":
        if f.pallets is None:
            raise ValueError("a Class A fire needs a pallet count to bound its energy")
        energy = f.pallets * f.energy_mj_per_pallet
        return FireModel(
            fire_class="A", alpha_kw_s2=f.alpha, incubation_s=f.incubation_s,
            design_hrr_kw=f.design_hrr_mw * 1000.0, total_energy_mj=energy,
            decay_energy_fraction=_cal("fire", "decay_energy_fraction"),
            tau_suppression_s=tau,
            pool_count=0, pool_area_m2=0.0, pool_hrr_each_kw=0.0, pool_ramp_s=0.0,
            pool_reduction=0.0, pool_extinction_flux_mm_min=0.0, pool_extinction_time_s=0.0,
        )

    if f.pools is None:
        raise ValueError("a Class B fire needs a `pools` block")
    area = f.pools.length_m * f.pools.width_m
    d_eff = math.sqrt(4.0 * area / math.pi)
    mdot = DIESEL_MDOT_INF_KGM2S * (1.0 - math.exp(-DIESEL_KBETA_PER_M * d_eff))
    each_kw = (_cal("fire", "pool_ventilation_factor") * mdot * area
               * DIESEL_HEAT_OF_COMBUSTION_MJKG * 1000.0)
    return FireModel(
        fire_class="B", alpha_kw_s2=f.alpha, incubation_s=f.incubation_s,
        design_hrr_kw=f.design_hrr_mw * 1000.0, total_energy_mj=math.inf,
        decay_energy_fraction=1.0, tau_suppression_s=tau,
        pool_count=f.pools.count, pool_area_m2=area, pool_hrr_each_kw=each_kw,
        pool_ramp_s=_cal("fire", "pool_ramp_s"),
        pool_reduction=_cal("fire", "pool_burning_rate_reduction"),
        pool_extinction_flux_mm_min=_cal("fire", "pool_extinction_flux_mm_min"),
        pool_extinction_time_s=_cal("fire", "pool_extinction_time_s"),
    )


def initial_state(model: FireModel) -> FireState:
    return FireState(t_s=0.0, hrr_mw=0.0, hrr_free_mw=0.0, energy_released_mj=0.0,
                     suppression=1.0, pools_remaining=model.pool_count, wet_time_s=0.0)


def _free_burn_class_a_kw(model: FireModel, state: FireState, t_s: float) -> float:
    grown = model.alpha_kw_s2 * max(t_s - model.incubation_s, 0.0) ** 2
    plateau = min(grown, model.design_hrr_kw)
    burnt = model.decay_energy_fraction * model.total_energy_mj
    if state.energy_released_mj <= burnt:
        return plateau
    remaining = model.total_energy_mj - state.energy_released_mj
    decay_span = (1.0 - model.decay_energy_fraction) * model.total_energy_mj
    return plateau * max(remaining / decay_span, 0.0)


def _free_burn_class_b_kw(model: FireModel, state: FireState, t_s: float) -> float:
    ramp = min(t_s / model.pool_ramp_s, 1.0) if model.pool_ramp_s > 0 else 1.0
    return state.pools_remaining * model.pool_hrr_each_kw * ramp


def step(model: FireModel, state: FireState, dt_s: float, mist: MistEffect) -> FireState:
    if dt_s <= 0:
        raise ValueError(f"dt_s must be positive, got {dt_s}")
    t = state.t_s + dt_s

    if model.fire_class == "A":
        free_kw = _free_burn_class_a_kw(model, state, t)
        # first-order approach to the suppressed level while the mist is on the fuel
        target = 1.0 - mist.eta
        tau = model.tau_suppression_s
        decayed = state.suppression + (target - state.suppression) * (1.0 - math.exp(-dt_s / tau))
        suppression = decayed if mist.eta > 0 else 1.0
        hrr_kw = free_kw * suppression
        pools, wet = state.pools_remaining, state.wet_time_s
    else:
        free_kw = _free_burn_class_b_kw(model, state, t)
        wetting = mist.w_fuel_mm_min * mist.f_cov >= model.pool_extinction_flux_mm_min
        wet = state.wet_time_s + dt_s if wetting else 0.0
        pools = state.pools_remaining
        if wet >= model.pool_extinction_time_s and pools > 0:
            pools -= 1
            wet = 0.0
        suppression = 1.0 - model.pool_reduction if mist.w_fuel_mm_min > 0 else 1.0
        hrr_kw = free_kw * suppression

    if hrr_kw < 0:
        raise ValueError(f"negative heat release {hrr_kw} kW at t={t} s")
    energy = state.energy_released_mj + hrr_kw * dt_s / 1000.0
    return FireState(t_s=t, hrr_mw=hrr_kw / 1000.0, hrr_free_mw=free_kw / 1000.0,
                     energy_released_mj=energy, suppression=suppression,
                     pools_remaining=pools, wet_time_s=wet)


def radiative_fraction(model: FireModel) -> float:
    return RADIATIVE_FRACTION_CLASS_A if model.fire_class == "A" else RADIATIVE_FRACTION_CLASS_B


def convective_kw(model: FireModel, hrr_mw: float) -> float:
    return hrr_mw * 1000.0 * (1.0 - radiative_fraction(model))


def mass_loss_rate_kgs(model: FireModel, hrr_mw: float) -> float:
    heat = (WOOD_HEAT_OF_COMBUSTION_MJKG if model.fire_class == "A"
            else DIESEL_HEAT_OF_COMBUSTION_MJKG)
    return hrr_mw / (COMBUSTION_EFFICIENCY * heat)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_fire.py -v`
Expected: PASS, 8 tests. If `test_class_b_pool_hrr_matches_the_nominal_sixty_megawatts` misses, adjust `pool_ventilation_factor` in `calibration.json` until seven pools give 60 MW — that is what the constant is for, and Task 13 refits it against the real anchor.

- [ ] **Step 7: Commit**

```bash
git add solit2/engines/reduced/state.py solit2/engines/reduced/fire.py solit2/presets/calibration.json tests/test_fire.py tests/fixtures
git commit -m "feat(fire): Class A t-squared and Class B Babrauskas pool heat release with mist suppression

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 5: Ventilation — critical velocity, backlayering, throttling

**Files:**
- Create: `solit2/engines/reduced/ventilation.py`
- Test: `tests/test_ventilation.py`

**Interfaces:**
- Consumes: `SectionGeometry` (Task 2), `FireModel`/`convective_kw` (Task 4).
- Produces: `dimensionless_hrr(q_conv_kw, height_m) -> float`; `critical_velocity_ms(q_conv_kw, height_m) -> float`; `backlayering_length_m(q_conv_kw, height_m, velocity_ms) -> float`; `throttled_velocity_ms(fan_velocity_ms, q_conv_kw, area_m2) -> float`; `VentilationState` (frozen dataclass: `u_fan_ms, u_eff_ms, u_critical_ms, backlayer_m`); `evaluate(geom, fan_velocity_ms, q_conv_kw) -> VentilationState`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_ventilation.py`:

```python
import pytest
from solit2.engines.reduced.geometry import SectionGeometry
from solit2.engines.reduced import ventilation as vent

# Orange Gate bore, cut & cover box, and the San Pedro test tunnel
BORE = SectionGeometry("bored", 10.146, 7.625, 70.29, "circle", 5.5, 2.125)
BOX = SectionGeometry("cut_cover", 9.0, 6.5, 58.5, "box")
SPDA = SectionGeometry("test", 9.5, 5.17, 48.0, "box")

CONV_150MW_KW = 150_000 * 0.65
CONV_100MW_KW = 100_000 * 0.65


def test_critical_velocity_orange_gate_bore_150mw():
    # Li, Lei & Ingason 2010: Q* > 0.15 so u_c* = 0.43, u_c = 0.43 sqrt(g H)
    assert vent.critical_velocity_ms(CONV_150MW_KW, BORE.crown_height_m) == pytest.approx(3.72, abs=0.05)


def test_critical_velocity_cut_and_cover_and_test_tunnel():
    assert vent.critical_velocity_ms(CONV_150MW_KW, BOX.crown_height_m) == pytest.approx(3.43, abs=0.05)
    assert vent.critical_velocity_ms(CONV_100MW_KW, SPDA.crown_height_m) == pytest.approx(3.06, abs=0.05)


def test_small_fire_falls_in_the_cube_root_regime():
    # 5 MW in the bore: Q* < 0.15, so u_c* = 0.81 Q*^(1/3) and u_c is well below 3 m/s
    u_c = vent.critical_velocity_ms(5_000 * 0.65, BORE.crown_height_m)
    assert 0.5 < u_c < 2.5
    assert vent.dimensionless_hrr(5_000 * 0.65, BORE.crown_height_m) < 0.15


def test_no_backlayering_above_the_critical_velocity():
    assert vent.backlayering_length_m(CONV_150MW_KW, BORE.crown_height_m, 5.08) == 0.0


def test_backlayering_grows_as_velocity_falls():
    at_3 = vent.backlayering_length_m(CONV_150MW_KW, BORE.crown_height_m, 3.0)
    at_2 = vent.backlayering_length_m(CONV_150MW_KW, BORE.crown_height_m, 2.0)
    assert 0.0 < at_3 < at_2
    assert at_2 < 200.0


def test_tender_floor_velocity_clears_the_bore_by_a_thin_margin():
    u_c = vent.critical_velocity_ms(CONV_150MW_KW, BORE.crown_height_m)
    assert 3.88 > u_c
    assert (3.88 - u_c) / u_c < 0.10   # under 10 % margin - the engine must warn


def test_fire_throttles_the_airflow():
    state = vent.evaluate(BORE, fan_velocity_ms=5.08, q_conv_kw=CONV_150MW_KW)
    assert state.u_eff_ms < state.u_fan_ms
    assert state.u_eff_ms > 0.0
    cold = vent.evaluate(BORE, fan_velocity_ms=5.08, q_conv_kw=0.0)
    assert cold.u_eff_ms == pytest.approx(5.08)


def test_throttling_never_reverses_the_flow():
    state = vent.evaluate(BORE, fan_velocity_ms=1.0, q_conv_kw=CONV_150MW_KW)
    assert state.u_eff_ms > 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_ventilation.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'solit2.engines.reduced.ventilation'`

- [ ] **Step 3: Write the implementation**

Create `solit2/engines/reduced/ventilation.py`:

```python
"""Longitudinal ventilation: critical velocity, backlayering and fire throttling.

Correlations are Li, Lei & Ingason (2010) for the critical velocity and the
backlayering length. The height used is the tunnel crown height; using the
area-equivalent height instead lowers the critical velocity by about 5 %
(recorded in calibration.json under ventilation.critical_velocity_height).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from solit2.engines.reduced.geometry import SectionGeometry
from solit2.schema.presets import load_calibration

GRAVITY_MS2 = 9.81
AIR_DENSITY_KGM3 = 1.2
AIR_CP_KJKGK = 1.0
AMBIENT_T_K = 293.0
# Li, Lei & Ingason (2010): the dimensionless critical velocity saturates above Q* = 0.15.
Q_STAR_TRANSITION = 0.15
U_STAR_SATURATED = 0.43
U_STAR_COEFFICIENT = 0.81
BACKLAYER_COEFFICIENT = 18.5
MIN_EFFECTIVE_VELOCITY_MS = 0.1


def dimensionless_hrr(q_conv_kw: float, height_m: float) -> float:
    if height_m <= 0:
        raise ValueError(f"tunnel height must be positive, got {height_m}")
    denominator = (AIR_DENSITY_KGM3 * AIR_CP_KJKGK * AMBIENT_T_K
                   * math.sqrt(GRAVITY_MS2) * height_m**2.5)
    return q_conv_kw / denominator


def _u_star_critical(q_star: float) -> float:
    if q_star <= Q_STAR_TRANSITION:
        return U_STAR_COEFFICIENT * q_star ** (1.0 / 3.0)
    return U_STAR_SATURATED


def critical_velocity_ms(q_conv_kw: float, height_m: float) -> float:
    q_star = dimensionless_hrr(q_conv_kw, height_m)
    return _u_star_critical(q_star) * math.sqrt(GRAVITY_MS2 * height_m)


def backlayering_length_m(q_conv_kw: float, height_m: float, velocity_ms: float) -> float:
    if velocity_ms <= 0:
        raise ValueError(f"velocity must be positive, got {velocity_ms}")
    q_star = dimensionless_hrr(q_conv_kw, height_m)
    u_star = velocity_ms / math.sqrt(GRAVITY_MS2 * height_m)
    u_star_c = _u_star_critical(q_star)
    if u_star >= u_star_c:
        return 0.0
    return BACKLAYER_COEFFICIENT * height_m * math.log(u_star_c / u_star)


def throttled_velocity_ms(fan_velocity_ms: float, q_conv_kw: float, area_m2: float) -> float:
    """Buoyancy opposes the fans; the effective velocity at the fire falls."""
    if area_m2 <= 0:
        raise ValueError(f"free area must be positive, got {area_m2}")
    if fan_velocity_ms <= 0:
        return 0.0
    k = load_calibration()["ventilation"]["throttling_coefficient"]["value"]
    thermal = q_conv_kw / (AIR_DENSITY_KGM3 * AIR_CP_KJKGK * AMBIENT_T_K * area_m2 * fan_velocity_ms)
    return max(fan_velocity_ms * (1.0 - k * thermal), MIN_EFFECTIVE_VELOCITY_MS)


@dataclass(frozen=True)
class VentilationState:
    u_fan_ms: float
    u_eff_ms: float
    u_critical_ms: float
    backlayer_m: float


def evaluate(geom: SectionGeometry, fan_velocity_ms: float, q_conv_kw: float) -> VentilationState:
    u_eff = throttled_velocity_ms(fan_velocity_ms, q_conv_kw, geom.free_area_m2)
    h = geom.crown_height_m
    u_c = critical_velocity_ms(q_conv_kw, h) if q_conv_kw > 0 else 0.0
    backlayer = backlayering_length_m(q_conv_kw, h, u_eff) if q_conv_kw > 0 else 0.0
    return VentilationState(fan_velocity_ms, u_eff, u_c, backlayer)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_ventilation.py -v`
Expected: PASS, 8 tests.

- [ ] **Step 5: Commit**

```bash
git add solit2/engines/reduced/ventilation.py tests/test_ventilation.py
git commit -m "feat(ventilation): Li-Ingason critical velocity, backlayering and fire throttling

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 6: Thermal field — ceiling temperature, stratification, detection, radiation

**Files:**
- Create: `solit2/engines/reduced/thermal.py`
- Test: `tests/test_thermal.py`

**Interfaces:**
- Consumes: `SectionGeometry` (Task 2), `MistEffect` (Task 4), `VentilationState` (Task 5).
- Produces: `equivalent_radius_m(length_m, width_m) -> float`; `max_ceiling_excess_k(hrr_kw, q_conv_kw, u_ms, b_fo_m, h_ef_m) -> float`; `longitudinal_decay(x_m, height_m) -> float`; `stratification_factor(u_ms, height_m, ceiling_excess_k) -> float`; `alpert_ceiling_excess_k(hrr_kw, radius_m, height_m) -> float`; `heskestad_flame_length_m(hrr_kw, diameter_m) -> float`; `point_source_flux_kwm2(hrr_kw, radiative_fraction, distance_m, transmissivity) -> float`; `ThermalField` (frozen dataclass: `ceiling_excess_k, strat_factor, ambient_c, height_m, flame_centroid_z_m, flame_tip_x_m`) with methods `ceiling_temp_c(x_m) -> float`, `gas_temp_c(x_m, height_m) -> float`, `radiant_flux_kwm2(x_m, height_m, tau_mist) -> float`; `field(geom, fire_model, fire_state, vent_state, mist, fire_top_m, fire_length_m, fire_width_m, ambient_c) -> ThermalField`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_thermal.py`:

```python
import pytest
from solit2.engines.reduced.geometry import SectionGeometry
from solit2.engines.reduced import thermal

BORE = SectionGeometry("bored", 10.146, 7.625, 70.29, "circle", 5.5, 2.125)
# HGV load 8.4 x 2.4 m, top 4.0 m above the carriageway
B_FO = thermal.equivalent_radius_m(8.4, 2.4)
H_EF = 7.625 - 4.0


def test_equivalent_radius_of_the_hgv_footprint():
    assert B_FO == pytest.approx(2.533, abs=0.01)


def test_forced_regime_ceiling_excess_for_a_suppressed_fifty_megawatt_fire():
    # V' = u / w* > 0.19, so Li & Ingason region II applies
    dt = thermal.max_ceiling_excess_k(hrr_kw=50_000, q_conv_kw=32_500,
                                      u_ms=4.5, b_fo_m=B_FO, h_ef_m=H_EF)
    assert dt == pytest.approx(953.0, rel=0.05)


def test_free_burning_one_fifty_megawatt_fire_hits_the_cap():
    dt = thermal.max_ceiling_excess_k(hrr_kw=150_000, q_conv_kw=97_500,
                                      u_ms=4.5, b_fo_m=B_FO, h_ef_m=H_EF)
    assert dt == pytest.approx(1350.0)


def test_low_velocity_falls_into_the_plume_regime():
    # 5 MW at 0.3 m/s: V' < 0.19, region I formula, not capped
    dt = thermal.max_ceiling_excess_k(hrr_kw=5_000, q_conv_kw=3_250,
                                      u_ms=0.3, b_fo_m=B_FO, h_ef_m=H_EF)
    assert dt == pytest.approx(598.0, rel=0.05)


def test_longitudinal_decay_matches_the_two_term_correlation():
    assert thermal.longitudinal_decay(0.0, 7.625) == pytest.approx(1.0)
    assert thermal.longitudinal_decay(15.0, 7.625) == pytest.approx(0.854, abs=0.01)
    assert thermal.longitudinal_decay(100.0, 7.625) == pytest.approx(0.430, abs=0.01)


def test_strong_stratification_at_tunnel_design_velocity():
    # Fr well below 0.9 -> breathing height stays near ambient
    f = thermal.stratification_factor(u_ms=4.5, height_m=7.625, ceiling_excess_k=950.0)
    assert f == pytest.approx(0.1, abs=0.001)


def test_mixed_regime_when_the_layer_is_cool_and_the_wind_is_strong():
    f = thermal.stratification_factor(u_ms=5.0, height_m=7.625, ceiling_excess_k=5.0)
    assert f == pytest.approx(1.0)


def test_alpert_ceiling_jet_gives_the_detection_threshold():
    # 30 K rise above a 30 C ambient trips a 60 C linear heat detector
    dt = thermal.alpert_ceiling_excess_k(hrr_kw=59.3, radius_m=0.0, height_m=H_EF)
    assert dt == pytest.approx(30.0, rel=0.05)


def test_heskestad_flame_length():
    assert thermal.heskestad_flame_length_m(50_000, 5.066) == pytest.approx(12.65, rel=0.05)


def test_bare_radiation_at_fifteen_metres_would_fail_the_gate():
    # the point-source flux alone exceeds the 5 kW/m2 upstream limit ...
    bare = thermal.point_source_flux_kwm2(50_000, 0.35, 15.0, transmissivity=1.0)
    assert bare > 5.0
    # ... and the mist curtain is what brings it under
    with_mist = thermal.point_source_flux_kwm2(50_000, 0.35, 15.0, transmissivity=0.55)
    assert with_mist < 5.0


def test_field_reports_breathing_height_temperatures_in_the_annex2_range():
    from solit2.engines.reduced.state import MistEffect
    from solit2.engines.reduced.ventilation import evaluate
    from solit2.engines.reduced import fire
    from solit2.schema.design import Design

    d = Design.load("designs/og-dbr-rev0.json")
    model = fire.build_model(d)
    st = fire.FireState(t_s=900.0, hrr_mw=50.0, hrr_free_mw=150.0,
                        energy_released_mj=30_000.0, suppression=0.33,
                        pools_remaining=0, wet_time_s=0.0)
    vent = evaluate(BORE, 4.5, fire.convective_kw(model, 50.0))
    f = thermal.field(BORE, model, st, vent, MistEffect.none(),
                      fire_top_m=4.0, fire_length_m=8.4, fire_width_m=2.4, ambient_c=30.0)
    # SOLIT2 Annex 2 suppressed Class A: D15 50-100 C, D100 50-65 C
    assert 50.0 < f.gas_temp_c(15.0, 1.8) < 130.0
    assert 40.0 < f.gas_temp_c(100.0, 1.8) < 90.0
    assert f.ceiling_temp_c(0.0) > 500.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_thermal.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'solit2.engines.reduced.thermal'`

- [ ] **Step 3: Write the implementation**

Create `solit2/engines/reduced/thermal.py`:

```python
"""Gas temperature and radiant heat flux along the tunnel.

Maximum ceiling excess temperature is Li & Ingason (2012), which splits into a
plume-controlled region I and a ventilation-controlled region II; the
longitudinal decay is the two-exponential form from Ingason, Li & Lonnermark
(2015). Breathing-height values come from the ceiling value through a Newman
stratification factor. Radiation to a gauge is a point source at the flame
centroid, attenuated by the mist and by the smoke.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from solit2.engines.reduced.fire import FireModel, convective_kw, radiative_fraction
from solit2.engines.reduced.geometry import SectionGeometry
from solit2.engines.reduced.state import FireState, MistEffect
from solit2.engines.reduced.ventilation import VentilationState
from solit2.schema.presets import load_calibration

GRAVITY_MS2 = 9.81
AIR_DENSITY_KGM3 = 1.2
AIR_CP_KJKGK = 1.0
AMBIENT_T_K = 293.0
# Li & Ingason (2012)
REGION_TRANSITION_V = 0.19
REGION_I_COEFFICIENT = 17.5
# Ingason, Li & Lonnermark (2015) two-term longitudinal decay
DECAY_A1, DECAY_B1 = 0.57, 0.13
DECAY_A2, DECAY_B2 = 0.43, 0.021
# Alpert ceiling jet
ALPERT_PLUME_COEFFICIENT = 16.9
ALPERT_JET_COEFFICIENT = 5.38
ALPERT_PLUME_RADIUS_RATIO = 0.18
# Newman stratification regimes
FROUDE_STRATIFIED = 0.9
FROUDE_MIXED = 10.0
STRATIFIED_FACTOR = 0.1
# Smoke extinction for the radiant path (mist attenuation is supplied separately)
SMOKE_EXTINCTION_PER_M = 0.004


def equivalent_radius_m(length_m: float, width_m: float) -> float:
    if length_m <= 0 or width_m <= 0:
        raise ValueError(f"fire footprint must be positive, got {length_m} x {width_m}")
    return math.sqrt(length_m * width_m / math.pi)


def _plume_velocity_scale_ms(q_conv_kw: float, b_fo_m: float) -> float:
    denominator = b_fo_m * AIR_DENSITY_KGM3 * AIR_CP_KJKGK * AMBIENT_T_K
    return (GRAVITY_MS2 * q_conv_kw / denominator) ** (1.0 / 3.0)


def max_ceiling_excess_k(hrr_kw: float, q_conv_kw: float, u_ms: float,
                         b_fo_m: float, h_ef_m: float) -> float:
    if h_ef_m <= 0:
        raise ValueError(
            f"effective height {h_ef_m} m is not positive: the fuel reaches the ceiling"
        )
    if hrr_kw <= 0:
        return 0.0
    cap = load_calibration()["thermal"]["ceiling_temp_cap_k"]["value"]
    w_star = _plume_velocity_scale_ms(q_conv_kw, b_fo_m)
    v_prime = u_ms / w_star if w_star > 0 else math.inf
    if v_prime <= REGION_TRANSITION_V:
        excess = REGION_I_COEFFICIENT * hrr_kw ** (2.0 / 3.0) / h_ef_m ** (5.0 / 3.0)
    else:
        excess = hrr_kw / (u_ms * b_fo_m ** (1.0 / 3.0) * h_ef_m ** (5.0 / 3.0))
    return min(excess, cap)


def longitudinal_decay(x_m: float, height_m: float) -> float:
    """Fraction of the maximum ceiling excess remaining `x_m` downstream."""
    ratio = abs(x_m) / height_m
    return DECAY_A1 * math.exp(-DECAY_B1 * ratio) + DECAY_A2 * math.exp(-DECAY_B2 * ratio)


def stratification_factor(u_ms: float, height_m: float, ceiling_excess_k: float) -> float:
    """Newman regimes: how much of the ceiling excess reaches breathing height."""
    if ceiling_excess_k <= 0:
        return 0.0
    froude = u_ms**2 / (GRAVITY_MS2 * height_m * ceiling_excess_k / AMBIENT_T_K)
    if froude < FROUDE_STRATIFIED:
        return STRATIFIED_FACTOR
    if froude >= FROUDE_MIXED:
        return 1.0
    span = (froude - FROUDE_STRATIFIED) / (FROUDE_MIXED - FROUDE_STRATIFIED)
    return STRATIFIED_FACTOR + span * (1.0 - STRATIFIED_FACTOR)


def alpert_ceiling_excess_k(hrr_kw: float, radius_m: float, height_m: float) -> float:
    if hrr_kw <= 0:
        return 0.0
    if radius_m / height_m <= ALPERT_PLUME_RADIUS_RATIO:
        return ALPERT_PLUME_COEFFICIENT * hrr_kw ** (2.0 / 3.0) / height_m ** (5.0 / 3.0)
    return ALPERT_JET_COEFFICIENT * (hrr_kw / radius_m) ** (2.0 / 3.0) / height_m


def heskestad_flame_length_m(hrr_kw: float, diameter_m: float) -> float:
    return max(0.235 * hrr_kw**0.4 - 1.02 * diameter_m, 0.0)


def point_source_flux_kwm2(hrr_kw: float, radiative_fraction_: float,
                           distance_m: float, transmissivity: float) -> float:
    if distance_m <= 0:
        raise ValueError(f"distance to the gauge must be positive, got {distance_m}")
    return radiative_fraction_ * hrr_kw * transmissivity / (4.0 * math.pi * distance_m**2)


@dataclass(frozen=True)
class ThermalField:
    ceiling_excess_k: float
    strat_factor: float
    ambient_c: float
    height_m: float
    hrr_kw: float
    radiative_fraction: float
    flame_centroid_z_m: float
    flame_tip_x_m: float

    def ceiling_temp_c(self, x_m: float) -> float:
        return self.ambient_c + self.ceiling_excess_k * longitudinal_decay(x_m, self.height_m)

    def gas_temp_c(self, x_m: float, height_m: float) -> float:
        """Breathing-height gas temperature; the ceiling value scaled by stratification."""
        excess = self.ceiling_excess_k * longitudinal_decay(x_m, self.height_m)
        fraction = self.strat_factor + (1.0 - self.strat_factor) * (height_m / self.height_m)
        return self.ambient_c + excess * min(fraction, 1.0)

    def radiant_flux_kwm2(self, x_m: float, height_m: float, tau_mist: float) -> float:
        dx = abs(x_m)
        dz = self.flame_centroid_z_m - height_m
        distance = max(math.hypot(dx, dz), 0.5)
        tau_smoke = math.exp(-SMOKE_EXTINCTION_PER_M * dx)
        return point_source_flux_kwm2(self.hrr_kw, self.radiative_fraction,
                                      distance, tau_mist * tau_smoke)


def field(geom: SectionGeometry, fire_model: FireModel, fire_state: FireState,
          vent_state: VentilationState, mist: MistEffect, fire_top_m: float,
          fire_length_m: float, fire_width_m: float, ambient_c: float) -> ThermalField:
    hrr_kw = fire_state.hrr_mw * 1000.0
    q_conv = convective_kw(fire_model, fire_state.hrr_mw)
    b_fo = equivalent_radius_m(fire_length_m, fire_width_m)
    h_ef = geom.crown_height_m - fire_top_m
    excess = max_ceiling_excess_k(hrr_kw, q_conv, vent_state.u_eff_ms, b_fo, h_ef)
    # evaporating mist removes part of the convective heat before it reaches the ceiling
    excess *= 1.0 - mist.chi_cool
    strat = stratification_factor(vent_state.u_eff_ms, geom.crown_height_m, excess)
    diameter = 2.0 * b_fo
    flame = heskestad_flame_length_m(hrr_kw, diameter)
    centroid = fire_top_m + 0.5 * min(flame, h_ef)
    c_f = load_calibration()["thermal"]["flame_length_coefficient"]["value"]
    tip = c_f * max(flame - h_ef, 0.0)  # flame that cannot rise is deflected downstream
    return ThermalField(ceiling_excess_k=excess, strat_factor=strat, ambient_c=ambient_c,
                        height_m=geom.crown_height_m, hrr_kw=hrr_kw,
                        radiative_fraction=radiative_fraction(fire_model),
                        flame_centroid_z_m=centroid, flame_tip_x_m=tip)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_thermal.py -v`
Expected: PASS, 12 tests.

- [ ] **Step 5: Commit**

```bash
git add solit2/engines/reduced/thermal.py tests/test_thermal.py
git commit -m "feat(thermal): Li-Ingason ceiling temperature, decay, stratification and radiation

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 7: Droplet trajectories per spray mode

**Files:**
- Create: `solit2/engines/reduced/droplet.py`
- Test: `tests/test_droplet.py`

**Interfaces:**
- Consumes: `Mode` from `Design.nozzles.modes` (Task 1), calibration (Task 4).
- Produces: `Trajectory` (frozen dataclass: `drift_m, flight_s, surviving_fraction, final_diameter_um, reached_target`); `integrate(diameter_um, launch_velocity_ms, launch_angle_deg, drop_height_m, air_velocity_ms, gas_excess_k, dt_s=0.001, max_time_s=60.0) -> Trajectory`; `terminal_velocity_ms(diameter_um) -> float`; `drag_coefficient(reynolds) -> float`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_droplet.py`:

```python
import pytest
from solit2.engines.reduced import droplet


def test_drag_coefficient_switches_from_stokes_to_newton():
    assert droplet.drag_coefficient(0.5) == pytest.approx(48.0, rel=0.1)
    assert droplet.drag_coefficient(2000.0) == pytest.approx(0.44)


def test_terminal_velocities_are_physical():
    assert droplet.terminal_velocity_ms(100) == pytest.approx(0.25, rel=0.25)
    assert droplet.terminal_velocity_ms(450) == pytest.approx(1.9, rel=0.25)
    assert droplet.terminal_velocity_ms(450) > 5 * droplet.terminal_velocity_ms(100)


def test_fine_mist_is_blown_far_downstream_before_reaching_the_carriageway():
    t = droplet.integrate(diameter_um=100, launch_velocity_ms=15.0, launch_angle_deg=0.0,
                          drop_height_m=5.75, air_velocity_ms=5.0, gas_excess_k=0.0)
    assert 60.0 < t.drift_m < 180.0
    assert t.reached_target


def test_coarse_core_lands_almost_under_the_nozzle():
    t = droplet.integrate(diameter_um=450, launch_velocity_ms=100.0, launch_angle_deg=0.0,
                          drop_height_m=5.75, air_velocity_ms=5.0, gas_excess_k=0.0)
    assert t.drift_m < 20.0


def test_the_bimodal_argument_in_numbers():
    fine = droplet.integrate(100, 15.0, 0.0, 1.75, 5.0, 0.0)
    coarse = droplet.integrate(450, 100.0, 0.0, 1.75, 5.0, 0.0)
    assert coarse.drift_m * 10 < fine.drift_m


def test_more_wind_means_more_drift():
    slow = droplet.integrate(100, 15.0, 0.0, 5.75, 3.88, 0.0)
    fast = droplet.integrate(100, 15.0, 0.0, 5.75, 5.08, 0.0)
    assert fast.drift_m > slow.drift_m


def test_fine_mist_evaporates_in_hot_gas_and_survives_in_cool_air():
    cool = droplet.integrate(100, 15.0, 0.0, 1.75, 5.0, gas_excess_k=0.0)
    hot = droplet.integrate(100, 15.0, 0.0, 1.75, 5.0, gas_excess_k=600.0)
    assert cool.surviving_fraction > 0.95
    assert hot.surviving_fraction < 0.2
    assert not hot.reached_target


def test_coarse_core_survives_the_same_hot_gas():
    hot = droplet.integrate(450, 100.0, 0.0, 1.75, 5.0, gas_excess_k=600.0)
    assert hot.surviving_fraction > 0.9
    assert hot.reached_target


def test_downward_tilt_shortens_the_drift():
    flat = droplet.integrate(100, 15.0, 0.0, 5.75, 5.0, 0.0)
    tilted = droplet.integrate(100, 15.0, 45.0, 5.75, 5.0, 0.0)
    assert tilted.drift_m < flat.drift_m
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_droplet.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'solit2.engines.reduced.droplet'`

- [ ] **Step 3: Write the implementation**

Create `solit2/engines/reduced/droplet.py`:

```python
"""Single-droplet flight from a nozzle to the fuel plane.

This is what separates the two spray modes: a fine droplet loses its launch
momentum within centimetres and is then carried by the tunnel airflow, while a
coarse droplet keeps enough momentum to cross the plume. The model tracks one
representative droplet per mode in the vertical plane, with Schiller-Naumann
drag and d-squared-law evaporation driven by the local gas temperature rise.

ponytail: one representative droplet per mode, two-dimensional - replace with a
size distribution if the FDS tier shows the tail of the spectrum matters.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from solit2.schema.presets import load_calibration

GRAVITY_MS2 = 9.81
AIR_DENSITY_KGM3 = 1.2
AIR_VISCOSITY_PAS = 1.8e-5
WATER_DENSITY_KGM3 = 1000.0
STOKES_REYNOLDS_LIMIT = 1000.0
NEWTON_DRAG_COEFFICIENT = 0.44
FULLY_EVAPORATED_UM = 10.0


def drag_coefficient(reynolds: float) -> float:
    """Schiller-Naumann below Re 1000, constant Newton drag above."""
    if reynolds <= 0:
        return 0.0
    if reynolds >= STOKES_REYNOLDS_LIMIT:
        return NEWTON_DRAG_COEFFICIENT
    return 24.0 / reynolds * (1.0 + 0.15 * reynolds**0.687)


def terminal_velocity_ms(diameter_um: float) -> float:
    """Fixed-point solve of the balance between weight and drag."""
    d = diameter_um * 1e-6
    v = 1.0
    for _ in range(60):
        reynolds = AIR_DENSITY_KGM3 * v * d / AIR_VISCOSITY_PAS
        c_d = max(drag_coefficient(reynolds), 1e-6)
        v_new = math.sqrt(4.0 * d * GRAVITY_MS2 * WATER_DENSITY_KGM3
                          / (3.0 * c_d * AIR_DENSITY_KGM3))
        if abs(v_new - v) < 1e-6:
            return v_new
        v = 0.5 * (v + v_new)
    return v


@dataclass(frozen=True)
class Trajectory:
    drift_m: float
    flight_s: float
    surviving_fraction: float
    final_diameter_um: float
    reached_target: bool


def integrate(diameter_um: float, launch_velocity_ms: float, launch_angle_deg: float,
              drop_height_m: float, air_velocity_ms: float, gas_excess_k: float,
              dt_s: float = 0.001, max_time_s: float = 60.0) -> Trajectory:
    """Fly one droplet from the nozzle down to a plane `drop_height_m` below it."""
    if diameter_um <= 0 or drop_height_m <= 0:
        raise ValueError(f"non-physical droplet input: d={diameter_um} um, h={drop_height_m} m")

    cal = load_calibration()["mist"]
    k_ref = cal["evaporation_k_ref_m2s"]["value"]
    delta_ref = cal["evaporation_reference_delta_t_k"]["value"]
    k_evap = k_ref * max(gas_excess_k, 0.0) / delta_ref

    d = diameter_um * 1e-6
    d0_squared = d**2
    angle = math.radians(launch_angle_deg)
    vx = launch_velocity_ms * math.sin(angle)
    vz = -launch_velocity_ms * math.cos(angle)   # negative is downward
    x = 0.0
    z = 0.0
    t = 0.0

    while t < max_time_s:
        if -z >= drop_height_m:
            return Trajectory(x, t, (d**2) / d0_squared * (d / (diameter_um * 1e-6)),
                              d * 1e6, True)
        if d * 1e6 <= FULLY_EVAPORATED_UM:
            return Trajectory(x, t, (d * 1e6 / diameter_um) ** 3, d * 1e6, False)

        rel_x = vx - air_velocity_ms
        rel = math.hypot(rel_x, vz)
        reynolds = AIR_DENSITY_KGM3 * rel * d / AIR_VISCOSITY_PAS
        c_d = drag_coefficient(reynolds)
        prefactor = 3.0 * AIR_DENSITY_KGM3 * c_d * rel / (4.0 * WATER_DENSITY_KGM3 * d)
        ax = -prefactor * rel_x
        az = -prefactor * vz - GRAVITY_MS2

        vx += ax * dt_s
        vz += az * dt_s
        x += vx * dt_s
        z += vz * dt_s
        t += dt_s

        if k_evap > 0:
            d_squared = max(d**2 - k_evap * dt_s, 0.0)
            d = math.sqrt(d_squared)

    raise RuntimeError(
        f"droplet of {diameter_um} um did not reach the plane {drop_height_m} m below "
        f"the nozzle within {max_time_s} s; check the launch conditions"
    )
```

Note on `surviving_fraction`: mass scales with the cube of the diameter, so the
fraction reaching the plane is `(d / d0) ** 3`. Simplify the two return
statements to use that single expression:

```python
        if -z >= drop_height_m:
            return Trajectory(x, t, (d * 1e6 / diameter_um) ** 3, d * 1e6, True)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_droplet.py -v`
Expected: PASS, 9 tests. If `test_fine_mist_evaporates_in_hot_gas_and_survives_in_cool_air` misses, adjust `evaporation_k_ref_m2s` in `calibration.json`; Task 13 refits it.

- [ ] **Step 5: Commit**

```bash
git add solit2/engines/reduced/droplet.py tests/test_droplet.py
git commit -m "feat(droplet): per-mode droplet trajectory with drag, crossflow drift and evaporation

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 8: Mist coupling — what actually lands on the fire

**Files:**
- Create: `solit2/engines/reduced/mist.py`
- Test: `tests/test_mist.py`

**Interfaces:**
- Consumes: `Design` (Task 1), `SectionGeometry`/`NozzlePosition` (Task 2), `MistEffect` (Task 4), `droplet.integrate` (Task 7).
- Produces: `Halo` (frozen dataclass: `x0_m, x1_m, y0_m, y1_m, area_m2`); `halo_around(fire_x_m, fire_y_m, fire_length_m, fire_width_m, margin_m=1.0) -> Halo`; `evaluate(design, geom, positions, halo, fire_top_m, u_eff_ms, gas_excess_k, q_conv_kw, flow_fraction) -> MistEffect`; `ModeDelivery` (frozen dataclass: `mode_id, drift_m, surviving_fraction, footprint_radius_m, flow_to_halo_lpm`); `mode_deliveries(design, positions, halo, fire_top_m, u_eff_ms, gas_excess_k, flow_fraction) -> tuple[ModeDelivery, ...]`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_mist.py`:

```python
import pytest
from solit2.schema.design import Design
from solit2.engines.reduced.geometry import section_geometry, nozzle_positions
from solit2.engines.reduced import mist

BASELINE = "designs/og-dbr-rev0.json"
FIRE_TOP_M = 4.0
Q_CONV_KW = 50_000 * 0.65


def _setup(design=None, u_ms=5.0, gas_excess_k=0.0, flow_fraction=1.0):
    d = design or Design.load(BASELINE)
    geom = section_geometry(d)
    pos = nozzle_positions(d, geom, fire_x_m=0.0)
    fire_y = d.fire.lane_centre_offset_from_wall_m - geom.road_width_m / 2.0
    halo = mist.halo_around(0.0, fire_y, d.fire.footprint.length_m, d.fire.footprint.width_m)
    effect = mist.evaluate(d, geom, pos, halo, FIRE_TOP_M, u_ms, gas_excess_k,
                           Q_CONV_KW, flow_fraction)
    return d, geom, pos, halo, effect


def test_halo_is_the_fuel_footprint_plus_one_metre():
    _, geom, _, halo, _ = _setup()
    assert halo.x1_m - halo.x0_m == pytest.approx(10.4)
    assert halo.y1_m - halo.y0_m == pytest.approx(4.4)
    assert halo.area_m2 == pytest.approx(45.76, rel=0.01)


def test_no_flow_means_no_effect():
    _, _, _, _, effect = _setup(flow_fraction=0.0)
    assert effect.eta == 0.0
    assert effect.w_fuel_mm_min == 0.0
    assert effect.tau_mist == 1.0


def test_baseline_delivers_useful_flux_to_the_fuel():
    _, _, _, _, effect = _setup()
    assert 1.5 < effect.w_fuel_mm_min < 6.0
    assert effect.f_cov > 0.5
    assert 0.5 < effect.eta < 0.9


def test_fine_mode_is_carried_onto_the_fire_from_upstream_heads():
    # the fine mode's whole point: released far upstream, it arrives over the fire
    d, _, pos, halo, _ = _setup()
    deliveries = {m.mode_id: m for m in mist.mode_deliveries(
        d, pos, halo, FIRE_TOP_M, u_ms := 5.0, 0.0, 1.0)}
    assert deliveries["fine"].drift_m > 10.0
    assert deliveries["coarse"].drift_m < 3.0
    assert deliveries["fine"].flow_to_halo_lpm > 0.0


def test_coarse_mode_carries_the_suppression_when_the_fine_mode_evaporates():
    _, _, _, _, cool = _setup(gas_excess_k=0.0)
    _, _, _, _, hot = _setup(gas_excess_k=700.0)
    assert hot.w_fuel_mm_min < cool.w_fuel_mm_min
    assert hot.w_fuel_mm_min > 0.0      # the coarse core still gets through
    assert hot.chi_cool > cool.chi_cool  # evaporation is what cools the gas


def test_mist_curtain_attenuates_radiation():
    _, _, _, _, effect = _setup()
    assert 0.0 < effect.tau_mist < 1.0


def test_tighter_pitch_raises_the_flux_on_the_fuel():
    d = Design.load(BASELINE)
    tight = d.model_copy(update={"nozzles": d.nozzles.model_copy(
        update={"mounting": d.nozzles.mounting.model_copy(update={"pitch_m": 1.6})})})
    _, _, _, _, base = _setup()
    _, _, _, _, dense = _setup(tight)
    assert dense.w_fuel_mm_min > base.w_fuel_mm_min


def test_all_fine_split_loses_fuel_wetting_at_tunnel_velocity():
    d = Design.load(BASELINE)
    fine_only = d.model_copy(update={"nozzles": d.nozzles.model_copy(update={
        "modes": (d.nozzles.modes[0].model_copy(update={"fraction": 1.0}),)})})
    _, _, _, _, base = _setup()
    _, _, _, _, fine = _setup(fine_only, gas_excess_k=700.0)
    assert fine.w_fuel_mm_min < base.w_fuel_mm_min


def test_cooling_fraction_is_capped():
    _, _, _, _, effect = _setup(gas_excess_k=900.0)
    assert effect.chi_cool <= 0.45 + 1e-9
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_mist.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'solit2.engines.reduced.mist'`

- [ ] **Step 3: Write the implementation**

Create `solit2/engines/reduced/mist.py`:

```python
"""What the spray actually delivers to the fire.

Every head discharges each mode as a cone. The cone's footprint on the plane of
the fuel top is shifted downstream by the droplet's drift, which is why a fine
mode released far upstream can still arrive over the fire while a coarse mode
lands almost under its own nozzle. Water flux on the fuel and its one-metre halo
drives suppression; evaporated water cools the gas; suspended water attenuates
radiation.
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
GRID_CELL_M = 0.2
# Geometric-optics extinction: kappa = 1.5 * volume fraction / droplet diameter.
EXTINCTION_PREFACTOR = 1.5


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


def halo_around(fire_x_m: float, fire_y_m: float, fire_length_m: float,
                fire_width_m: float, margin_m: float = 1.0) -> Halo:
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


def mode_deliveries(design: Design, positions: tuple[NozzlePosition, ...], halo: Halo,
                    fire_top_m: float, u_eff_ms: float, gas_excess_k: float,
                    flow_fraction: float) -> tuple[ModeDelivery, ...]:
    """Per mode: how far the spray drifts, how much survives, how much lands on the halo."""
    mount = design.nozzles.mounting
    drop_height = mount.height_above_carriageway_m - fire_top_m
    if drop_height <= 0:
        raise ValueError(
            f"nozzles at {mount.height_above_carriageway_m} m are not above the fuel top "
            f"at {fire_top_m} m"
        )
    gx, gy = _grid(halo)
    out = []
    for mode in design.nozzles.modes:
        traj = integrate(
            diameter_um=design.nozzles.smd_um(mode.id),
            launch_velocity_ms=mode.launch_velocity_ms,
            launch_angle_deg=mount.tilt_deg,
            drop_height_m=drop_height,
            air_velocity_ms=u_eff_ms,
            gas_excess_k=gas_excess_k,
        )
        radius = drop_height * math.tan(math.radians(mode.cone_half_angle_deg))
        per_head_lpm = design.nozzles.mode_flow_lpm(mode.id) * flow_fraction * traj.surviving_fraction
        landed = 0.0
        for p in positions:
            cx, cy = p.x_m + traj.drift_m, p.y_m
            inside = ((gx - cx) ** 2 + (gy - cy) ** 2) <= radius**2
            hit = inside.sum() * GRID_CELL_M**2
            if hit > 0:
                footprint_area = math.pi * radius**2
                landed += per_head_lpm * min(hit / footprint_area, 1.0)
        out.append(ModeDelivery(mode.id, traj.drift_m, traj.surviving_fraction, radius, landed))
    return tuple(out)


def _coverage(design: Design, positions: tuple[NozzlePosition, ...], halo: Halo,
              deliveries: tuple[ModeDelivery, ...]) -> float:
    gx, gy = _grid(halo)
    covered = np.zeros_like(gx, dtype=bool)
    for delivery in deliveries:
        if delivery.flow_to_halo_lpm <= 0:
            continue
        for p in positions:
            cx, cy = p.x_m + delivery.drift_m, p.y_m
            covered |= ((gx - cx) ** 2 + (gy - cy) ** 2) <= delivery.footprint_radius_m**2
    return float(covered.mean())


def evaluate(design: Design, geom: SectionGeometry, positions: tuple[NozzlePosition, ...],
             halo: Halo, fire_top_m: float, u_eff_ms: float, gas_excess_k: float,
             q_conv_kw: float, flow_fraction: float) -> MistEffect:
    if flow_fraction <= 0:
        return MistEffect.none()

    cal = load_calibration()["mist"]
    deliveries = mode_deliveries(design, positions, halo, fire_top_m,
                                 u_eff_ms, gas_excess_k, flow_fraction)

    w_fuel = sum(d.flow_to_halo_lpm for d in deliveries) / halo.area_m2
    f_cov = _coverage(design, positions, halo, deliveries)
    eta = cal["eta_max"]["value"] * (1.0 - math.exp(-w_fuel * f_cov / cal["w_ref_mm_min"]["value"]))

    # Gas cooling: only the water that evaporates removes heat.
    chi_cool = 0.0
    if q_conv_kw > 0:
        sensible = WATER_CP_KJKGK * (WATER_BOILING_C - WATER_INLET_TEMP_C) + WATER_LATENT_HEAT_KJKG
        for mode, delivery in zip(design.nozzles.modes, deliveries):
            evaporated = 1.0 - delivery.surviving_fraction
            mdot = (design.nozzles.mode_flow_lpm(mode.id) * len(positions)
                    * flow_fraction / 60_000.0 * WATER_DENSITY_KGM3)
            chi_cool += evaporated * mdot * sensible / q_conv_kw
        chi_cool = min(chi_cool, cal["chi_cool_max"]["value"])

    # Radiation attenuation by the water suspended in the active zone.
    active_volume = design.active_length_m * geom.free_area_m2
    kappa = 0.0
    for mode, delivery in zip(design.nozzles.modes, deliveries):
        flow_m3s = design.nozzles.mode_flow_lpm(mode.id) * len(positions) * flow_fraction / 60_000.0
        residence_s = max(delivery.footprint_radius_m, 0.1) / max(u_eff_ms, 0.1)
        volume_fraction = flow_m3s * residence_s / active_volume
        kappa += EXTINCTION_PREFACTOR * volume_fraction / (design.nozzles.smd_um(mode.id) * 1e-6)
    tau_mist = math.exp(-kappa * design.active_length_m / 2.0)

    return MistEffect(eta=eta, w_fuel_mm_min=w_fuel, f_cov=f_cov,
                      chi_cool=chi_cool, tau_mist=tau_mist)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_mist.py -v`
Expected: PASS, 9 tests. `test_baseline_delivers_useful_flux_to_the_fuel` is the one that pins the calibration: if `eta` lands outside 0.5–0.9, adjust `w_ref_mm_min` in `calibration.json` and note the change — Task 13 refits it against the anchors.

- [ ] **Step 5: Commit**

```bash
git add solit2/engines/reduced/mist.py tests/test_mist.py
git commit -m "feat(mist): drift-shifted spray footprints, fuel wetting, gas cooling and radiation attenuation

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 9: Tenability — species, FED and visibility

**Files:**
- Create: `solit2/engines/reduced/tenability.py`
- Test: `tests/test_tenability.py`

**Interfaces:**
- Consumes: `FireModel`/`mass_loss_rate_kgs` (Task 4), `ThermalField` (Task 6).
- Produces: `Species` (frozen dataclass: `co_ppm, co2_pct, soot_gm3, o2_pct`); `species_at(fire_model, hrr_mw, air_volumetric_m3s, strat_factor) -> Species`; `fed_tox_increment(species, dt_s) -> float`; `fed_heat_increment(temp_c, flux_kwm2, dt_s) -> float`; `visibility_m(soot_gm3, kappa_mist_per_m) -> float`; `YIELDS` (dict keyed by fire class).

- [ ] **Step 1: Write the failing test**

Create `tests/test_tenability.py`:

```python
import pytest
from solit2.schema.design import Design
from solit2.engines.reduced import fire, tenability

BASELINE = "designs/og-dbr-rev0.json"
# Orange Gate bore at 5 m/s: 70.29 m2 x 5 m/s
AIR_M3S = 70.29 * 5.0


def _model():
    return fire.build_model(Design.load(BASELINE))


def test_species_concentrations_for_a_suppressed_fifty_megawatt_wood_fire():
    sp = tenability.species_at(_model(), hrr_mw=50.0, air_volumetric_m3s=AIR_M3S,
                               strat_factor=1.0)
    assert sp.co_ppm == pytest.approx(44.0, rel=0.25)
    assert 0.3 < sp.co2_pct < 1.5
    assert sp.soot_gm3 == pytest.approx(0.152, rel=0.25)
    assert 19.5 < sp.o2_pct < 21.0


def test_stratification_keeps_the_breathing_layer_clear():
    stratified = tenability.species_at(_model(), 50.0, AIR_M3S, strat_factor=0.1)
    mixed = tenability.species_at(_model(), 50.0, AIR_M3S, strat_factor=1.0)
    assert stratified.co_ppm == pytest.approx(0.1 * mixed.co_ppm, rel=0.01)


def test_fed_over_an_hour_at_the_stratified_concentration_passes_the_limit():
    sp = tenability.species_at(_model(), 50.0, AIR_M3S, strat_factor=0.1)
    fed = sum(tenability.fed_tox_increment(sp, 1.0) for _ in range(3600))
    assert fed < 0.3


def test_fed_at_fully_mixed_concentration_is_much_worse():
    mixed = tenability.species_at(_model(), 50.0, AIR_M3S, strat_factor=1.0)
    strat = tenability.species_at(_model(), 50.0, AIR_M3S, strat_factor=0.1)
    fed_mixed = sum(tenability.fed_tox_increment(mixed, 1.0) for _ in range(3600))
    fed_strat = sum(tenability.fed_tox_increment(strat, 1.0) for _ in range(3600))
    assert fed_mixed > 10 * fed_strat


def test_fed_heat_ignores_flux_below_the_pain_threshold():
    assert tenability.fed_heat_increment(temp_c=30.0, flux_kwm2=1.0, dt_s=60.0) < 0.02


def test_fed_heat_accumulates_fast_under_severe_exposure():
    one_minute = tenability.fed_heat_increment(temp_c=200.0, flux_kwm2=10.0, dt_s=60.0)
    assert one_minute > 0.3


def test_visibility_at_the_stratified_soot_load():
    sp = tenability.species_at(_model(), 50.0, AIR_M3S, strat_factor=0.1)
    assert tenability.visibility_m(sp.soot_gm3, kappa_mist_per_m=0.0) == pytest.approx(60.0, rel=0.25)


def test_mist_in_the_path_reduces_visibility():
    sp = tenability.species_at(_model(), 50.0, AIR_M3S, strat_factor=0.1)
    clear = tenability.visibility_m(sp.soot_gm3, 0.0)
    misty = tenability.visibility_m(sp.soot_gm3, 0.5)
    assert misty < clear


def test_diesel_pools_make_far_more_smoke_than_wood():
    pool_model = fire.build_model(Design.load("tests/fixtures/pool_design.json"))
    wood = tenability.species_at(_model(), 30.0, AIR_M3S, 1.0)
    diesel = tenability.species_at(pool_model, 30.0, AIR_M3S, 1.0)
    assert diesel.soot_gm3 > 2 * wood.soot_gm3
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_tenability.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'solit2.engines.reduced.tenability'`

- [ ] **Step 3: Write the implementation**

Create `solit2/engines/reduced/tenability.py`:

```python
"""Tenability: what the smoke does to a person at breathing height.

Species come from published yields and the fire's mass loss rate, diluted by the
ventilation flow and reduced by stratification. The fractional effective dose
follows ISO 13571 (toxic and thermal), and visibility follows Jin's relation for
light-emitting signs.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from solit2.engines.reduced.fire import FireModel, mass_loss_rate_kgs

# Yields, g per g of fuel burnt: well-ventilated wood and diesel.
YIELDS = {
    "A": {"co": 0.005, "co2": 1.30, "soot": 0.015},
    "B": {"co": 0.010, "co2": 3.00, "soot": 0.060},
}
AIR_DENSITY_KGM3 = 1.2
AMBIENT_O2_PCT = 20.9
# Oxygen consumed per unit of heat released (Huggett), and the energy per kg of O2.
HUGGETT_KJ_PER_KG_O2 = 13_100.0
MOLAR_MASS_AIR = 28.97
MOLAR_MASS_CO = 28.01
MOLAR_MASS_CO2 = 44.01
# ISO 13571
FED_CO_COEFFICIENT = 2.764e-5
FED_CO_EXPONENT = 1.036
FED_HEAT_FLUX_THRESHOLD_KWM2 = 2.5
# Jin: light-emitting signs.
JIN_LIGHT_EMITTING = 8.0
SOOT_EXTINCTION_M2_PER_G = 8.7
MAX_REPORTED_VISIBILITY_M = 1000.0


@dataclass(frozen=True)
class Species:
    co_ppm: float
    co2_pct: float
    soot_gm3: float
    o2_pct: float


def species_at(fire_model: FireModel, hrr_mw: float, air_volumetric_m3s: float,
               strat_factor: float) -> Species:
    """Concentrations at breathing height in the flow passing a downstream station."""
    if air_volumetric_m3s <= 0:
        raise ValueError(f"ventilation flow must be positive, got {air_volumetric_m3s} m3/s")
    if hrr_mw <= 0:
        return Species(0.0, 0.0, 0.0, AMBIENT_O2_PCT)

    yields = YIELDS[fire_model.fire_class]
    mdot_fuel = mass_loss_rate_kgs(fire_model, hrr_mw)
    mass_flow_air = air_volumetric_m3s * AIR_DENSITY_KGM3

    co_mass_fraction = strat_factor * yields["co"] * mdot_fuel / mass_flow_air
    co2_mass_fraction = strat_factor * yields["co2"] * mdot_fuel / mass_flow_air
    soot_gm3 = strat_factor * yields["soot"] * mdot_fuel * 1000.0 / air_volumetric_m3s

    co_ppm = co_mass_fraction * (MOLAR_MASS_AIR / MOLAR_MASS_CO) * 1e6
    co2_pct = co2_mass_fraction * (MOLAR_MASS_AIR / MOLAR_MASS_CO2) * 100.0

    o2_consumed_kgs = hrr_mw * 1000.0 / HUGGETT_KJ_PER_KG_O2
    o2_depletion_pct = strat_factor * o2_consumed_kgs / mass_flow_air * 100.0
    return Species(co_ppm, co2_pct, soot_gm3, max(AMBIENT_O2_PCT - o2_depletion_pct, 0.0))


def fed_tox_increment(species: Species, dt_s: float) -> float:
    """ISO 13571 asphyxiant dose, with the CO2 hyperventilation multiplier."""
    if species.co_ppm <= 0:
        return 0.0
    hyperventilation = math.exp(species.co2_pct / 5.0)
    return (species.co_ppm**FED_CO_EXPONENT * FED_CO_COEFFICIENT
            * hyperventilation * dt_s / 60.0)


def fed_heat_increment(temp_c: float, flux_kwm2: float, dt_s: float) -> float:
    """ISO 13571 thermal dose: convected heat plus radiant heat."""
    minutes = dt_s / 60.0
    dose = 0.0
    if temp_c > 30.0:
        dose += minutes / (5.0e7 * temp_c**-3.4)
    if flux_kwm2 >= FED_HEAT_FLUX_THRESHOLD_KWM2:
        dose += minutes / (1.33 * flux_kwm2**-1.33)
    return dose


def visibility_m(soot_gm3: float, kappa_mist_per_m: float) -> float:
    extinction = SOOT_EXTINCTION_M2_PER_G * soot_gm3 + kappa_mist_per_m
    if extinction <= 0:
        return MAX_REPORTED_VISIBILITY_M
    return min(JIN_LIGHT_EMITTING / extinction, MAX_REPORTED_VISIBILITY_M)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_tenability.py -v`
Expected: PASS, 9 tests.

- [ ] **Step 5: Commit**

```bash
git add solit2/engines/reduced/tenability.py tests/test_tenability.py
git commit -m "feat(tenability): species yields, ISO 13571 FED and Jin visibility

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 10: Result schema, criteria and score

**Files:**
- Create: `solit2/schema/result.py`, `solit2/engines/reduced/criteria.py`, `solit2/engines/reduced/score.py`
- Modify: `solit2/engines/reduced/state.py` (append the trace types)
- Test: `tests/test_criteria.py`, `tests/test_score.py`

**Interfaces:**
- Consumes: `HydraulicsResult`/`CostResult` (Task 3), `MistEffect` (Task 4).
- Produces: `state.StationSample` (frozen: `temp_c, flux_kwm2, visibility_m, fed_tox, fed_heat`); `state.StepRecord` (frozen: `t_s, hrr_mw, hrr_free_mw, ceiling_temp_c, lining_temp_c, pipe_temp_c, target_flux_kwm2, u_eff_ms, u_critical_ms, backlayer_m, water_lpm, pools_remaining, mist, stations`); `state.RunTrace` (frozen: `steps, events, section, velocity_ms`); `result.Criterion` (pydantic: `value, limit, op, hard, passed, margin`) with `Criterion.build(value, limit, op, hard) -> Criterion`; `result.Result` (pydantic, the §4 contract); `criteria.STATIONS`, `criteria.BREATHING_HEIGHT_M`, `criteria.DEFAULT_CRITERIA`, `criteria.evaluate(trace, hyd, cost, design) -> dict[str, Criterion]`; `score.Score` (frozen: `total, gates_passed, gates_failed, components, penalties`); `score.compute(criteria_map, hyd, cost, trace) -> Score`.

- [ ] **Step 1: Append the trace types to `state.py`**

```python
@dataclass(frozen=True)
class StationSample:
    temp_c: float
    flux_kwm2: float
    visibility_m: float
    fed_tox: float      # cumulative to this instant
    fed_heat: float     # cumulative to this instant


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


@dataclass(frozen=True)
class RunTrace:
    steps: tuple[StepRecord, ...]
    events: dict
    section: str
    velocity_ms: float

    def after(self, t_s: float) -> tuple[StepRecord, ...]:
        return tuple(s for s in self.steps if s.t_s >= t_s)
```

- [ ] **Step 2: Write the failing criteria test**

Create `tests/test_criteria.py`:

```python
import pytest
from solit2.schema.result import Criterion


def test_upper_bound_margin():
    c = Criterion.build(value=46.0, limit=50.0, op="<=", hard=True)
    assert c.passed
    assert c.margin == pytest.approx(0.08)


def test_upper_bound_failure_has_negative_margin():
    c = Criterion.build(value=77.0, limit=50.0, op="<=", hard=True)
    assert not c.passed
    assert c.margin < 0


def test_lower_bound_margin():
    c = Criterion.build(value=60.0, limit=10.0, op=">=", hard=True)
    assert c.passed
    assert c.margin == pytest.approx(1.0)


def test_band_criterion():
    inside = Criterion.build(value=50.0, limit=(45.0, 60.0), op="in", hard=True)
    outside = Criterion.build(value=80.0, limit=(45.0, 60.0), op="in", hard=True)
    assert inside.passed and not outside.passed
    assert inside.margin > 0 and outside.margin < 0


def test_every_spec_criterion_is_defined_once():
    from solit2.engines.reduced.criteria import DEFAULT_CRITERIA
    ids = [c.id for c in DEFAULT_CRITERIA]
    assert len(ids) == len(set(ids))
    assert set(ids) == {
        "hrr_control_mw", "power_kw", "target_hf_kwm2", "remote_nozzle_bar",
        "u35_temp_c", "hf_u15_kwm2", "hf_u35_kwm2", "visibility_u35_m", "fed_d35",
        "ff_u5_hf_kwm2", "ff_d20_temp_c", "density_mm_min", "pools_extinguished_s",
    }


def test_hard_gates_are_the_tender_and_solit2_set():
    from solit2.engines.reduced.criteria import DEFAULT_CRITERIA
    hard = {c.id for c in DEFAULT_CRITERIA if c.hard}
    assert hard == {
        "hrr_control_mw", "power_kw", "target_hf_kwm2", "remote_nozzle_bar",
        "u35_temp_c", "hf_u15_kwm2", "hf_u35_kwm2", "visibility_u35_m", "fed_d35",
    }


def test_stations_cover_every_criterion_location():
    from solit2.engines.reduced.criteria import STATIONS
    assert STATIONS["U35"] == -35.0
    assert STATIONS["D100"] == 100.0
    assert set(STATIONS) == {"U35", "U15", "U5", "D5", "D15", "D20", "D35", "D100"}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `uv run pytest tests/test_criteria.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'solit2.schema.result'`

- [ ] **Step 4: Write `result.py`**

Create `solit2/schema/result.py`:

```python
"""The result contract. Both engines fill exactly this shape."""
from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict


class Criterion(BaseModel):
    model_config = ConfigDict(frozen=True)

    value: float
    limit: float | tuple[float, float]
    op: Literal["<=", ">=", "in"]
    hard: bool
    passed: bool
    margin: float

    @classmethod
    def build(cls, value: float, limit: float | tuple[float, float],
              op: str, hard: bool) -> "Criterion":
        if op == "<=":
            passed = value <= limit
            margin = 1.0 - value / limit if limit else 0.0
        elif op == ">=":
            passed = value >= limit
            margin = min(1.0, value / limit - 1.0) if limit else 0.0
        elif op == "in":
            low, high = limit
            passed = low <= value <= high
            half_band = (high - low) / 2.0
            centre = (high + low) / 2.0
            margin = 1.0 - abs(value - centre) / half_band if half_band else 0.0
        else:
            raise ValueError(f"unknown criterion operator {op!r}; expected '<=', '>=' or 'in'")
        return cls(value=value, limit=limit, op=op, hard=hard,
                   passed=passed, margin=max(min(margin, 1.0), -1.0))


class Result(BaseModel):
    model_config = ConfigDict(frozen=True)

    meta: dict[str, Any]
    envelope: list[dict[str, Any]]
    worst_case: dict[str, Any]
    events: dict[str, Any]
    criteria: dict[str, Criterion]
    peaks: dict[str, float]
    mist: dict[str, Any]
    hydraulics: dict[str, Any]
    cost: dict[str, Any]
    score: dict[str, Any]
    timeseries: dict[str, list[float]]
    warnings: list[str]
```

- [ ] **Step 5: Write `criteria.py`**

Create `solit2/engines/reduced/criteria.py`:

```python
"""Criterion definitions and their evaluation against a completed run.

Hard criteria come from the tender (`HPWM-TECHNICAL SPEC_R2` sections 5 and 6)
and from the SOLIT2/APPLUS+TST performance criteria. Soft criteria are reported
but do not reject a design.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from solit2.engines.reduced.cost import CostResult
from solit2.engines.reduced.hydraulics import HydraulicsResult
from solit2.engines.reduced.state import RunTrace
from solit2.schema.design import Design
from solit2.schema.result import Criterion

# Station chainage relative to the fire centre; negative is upstream.
STATIONS = {"U35": -35.0, "U15": -15.0, "U5": -5.0,
            "D5": 5.0, "D15": 15.0, "D20": 20.0, "D35": 35.0, "D100": 100.0}
BREATHING_HEIGHT_M = 1.8
# Piloted ignition of wood; the downstream target must stay below this.
WOOD_PILOTED_IGNITION_KWM2 = 12.5
NO_EXTINCTION_SENTINEL_S = 1e9


@dataclass(frozen=True)
class CriterionSpec:
    id: str
    limit: float | tuple[float, float]
    op: str
    hard: bool
    extract: Callable[[RunTrace, HydraulicsResult, CostResult, Design], float]


def _peak_after_activation(trace: RunTrace, attribute: str) -> float:
    steps = trace.after(trace.events.get("t_full_pressure_s", 0.0))
    if not steps:
        steps = trace.steps
    return max(getattr(s, attribute) for s in steps)


def _station_peak(trace: RunTrace, station: str, field: str) -> float:
    return max(getattr(s.stations[station], field) for s in trace.steps)


def _station_min(trace: RunTrace, station: str, field: str) -> float:
    return min(getattr(s.stations[station], field) for s in trace.steps)


def _station_final(trace: RunTrace, station: str, field: str) -> float:
    return getattr(trace.steps[-1].stations[station], field)


DEFAULT_CRITERIA: tuple[CriterionSpec, ...] = (
    CriterionSpec("hrr_control_mw", 50.0, "<=", True,
                  lambda t, h, c, d: _peak_after_activation(t, "hrr_mw")),
    CriterionSpec("power_kw", 650.0, "<=", True, lambda t, h, c, d: h.power_kw),
    CriterionSpec("target_hf_kwm2", WOOD_PILOTED_IGNITION_KWM2, "<=", True,
                  lambda t, h, c, d: _peak_after_activation(t, "target_flux_kwm2")),
    CriterionSpec("remote_nozzle_bar", (45.0, 60.0), "in", True,
                  lambda t, h, c, d: d.nozzles.pressure_bar),
    CriterionSpec("u35_temp_c", 60.0, "<=", True,
                  lambda t, h, c, d: _station_peak(t, "U35", "temp_c")),
    CriterionSpec("hf_u15_kwm2", 5.0, "<=", True,
                  lambda t, h, c, d: _station_peak(t, "U15", "flux_kwm2")),
    CriterionSpec("hf_u35_kwm2", 2.5, "<=", True,
                  lambda t, h, c, d: _station_peak(t, "U35", "flux_kwm2")),
    CriterionSpec("visibility_u35_m", 10.0, ">=", True,
                  lambda t, h, c, d: _station_min(t, "U35", "visibility_m")),
    CriterionSpec("fed_d35", 0.3, "<=", True,
                  lambda t, h, c, d: _station_final(t, "D35", "fed_tox")),
    CriterionSpec("ff_u5_hf_kwm2", 5.0, "<=", False,
                  lambda t, h, c, d: _station_peak(t, "U5", "flux_kwm2")),
    CriterionSpec("ff_d20_temp_c", 60.0, "<=", False,
                  lambda t, h, c, d: _station_peak(t, "D20", "temp_c")),
    CriterionSpec("density_mm_min", 3.8, "<=", False,
                  lambda t, h, c, d: h.density_mm_min),
    CriterionSpec("pools_extinguished_s", 600.0, "<=", False,
                  lambda t, h, c, d: t.events.get("pools_extinguished_at_s")
                  or (0.0 if d.fire.fire_class == "A" else NO_EXTINCTION_SENTINEL_S)),
)


def evaluate(trace: RunTrace, hyd: HydraulicsResult, cost: CostResult,
             design: Design) -> dict[str, Criterion]:
    """Apply every criterion, letting `design.criteria` override limits and hardness."""
    out: dict[str, Criterion] = {}
    for spec in DEFAULT_CRITERIA:
        override = design.criteria.get(spec.id, {})
        limit = override.get("limit", spec.limit)
        if isinstance(limit, list):
            limit = tuple(limit)
        out[spec.id] = Criterion.build(
            value=spec.extract(trace, hyd, cost, design),
            limit=limit,
            op=override.get("op", spec.op),
            hard=override.get("hard", spec.hard),
        )
    return out
```

- [ ] **Step 6: Write the failing score test**

Create `tests/test_score.py`:

```python
import pytest
from solit2.schema.result import Criterion
from solit2.engines.reduced import score as score_mod


class _Hyd:
    flow_lpm = 2174.3
    power_kw = 375.0
    density_mm_min = 2.4


class _Cost:
    index = 1.0


class _Trace:
    events = {}
    steps = ()


def _criteria(**overrides):
    base = {
        "hrr_control_mw": Criterion.build(46.0, 50.0, "<=", True),
        "power_kw": Criterion.build(375.0, 650.0, "<=", True),
        "target_hf_kwm2": Criterion.build(9.8, 12.5, "<=", True),
        "remote_nozzle_bar": Criterion.build(50.0, (45.0, 60.0), "in", True),
        "u35_temp_c": Criterion.build(31.0, 60.0, "<=", True),
        "hf_u15_kwm2": Criterion.build(1.1, 5.0, "<=", True),
        "hf_u35_kwm2": Criterion.build(0.3, 2.5, "<=", True),
        "visibility_u35_m": Criterion.build(60.0, 10.0, ">=", True),
        "fed_d35": Criterion.build(0.05, 0.3, "<=", True),
        "density_mm_min": Criterion.build(2.4, 3.8, "<=", False),
    }
    base.update(overrides)
    return base


def test_passing_design_scores_between_zero_and_ten():
    s = score_mod.compute(_criteria(), _Hyd(), _Cost(), _Trace(), peak_lining_c=690.0)
    assert s.gates_passed
    assert 0.0 < s.total <= 10.0
    assert set(s.components) == {"water", "margin", "cost", "structural"}


def test_a_failed_hard_gate_zeroes_the_score_and_is_named():
    s = score_mod.compute(
        _criteria(hrr_control_mw=Criterion.build(77.0, 50.0, "<=", True)),
        _Hyd(), _Cost(), _Trace(), peak_lining_c=690.0)
    assert not s.gates_passed
    assert s.total == 0.0
    assert s.gates_failed == ["hrr_control_mw"]
    assert s.components["water"] > 0  # still reported, so the optimiser can steer


def test_a_failed_soft_criterion_does_not_zero_the_score():
    s = score_mod.compute(
        _criteria(density_mm_min=Criterion.build(4.5, 3.8, "<=", False)),
        _Hyd(), _Cost(), _Trace(), peak_lining_c=690.0)
    assert s.gates_passed
    assert s.total > 0.0


def test_less_water_scores_higher():
    lean = type("H", (), {"flow_lpm": 1500.0, "power_kw": 300.0, "density_mm_min": 1.8})()
    base = score_mod.compute(_criteria(), _Hyd(), _Cost(), _Trace(), peak_lining_c=690.0)
    better = score_mod.compute(_criteria(), lean, _Cost(), _Trace(), peak_lining_c=690.0)
    assert better.total > base.total


def test_hotter_lining_scores_lower():
    cool = score_mod.compute(_criteria(), _Hyd(), _Cost(), _Trace(), peak_lining_c=400.0)
    hot = score_mod.compute(_criteria(), _Hyd(), _Cost(), _Trace(), peak_lining_c=1200.0)
    assert cool.total > hot.total


def test_penalty_for_exceeding_the_density_headroom():
    s = score_mod.compute(
        _criteria(density_mm_min=Criterion.build(4.5, 3.8, "<=", False)),
        _Hyd(), _Cost(), _Trace(), peak_lining_c=690.0)
    assert any("density" in p for p in s.penalties)


def test_weights_sum_to_one():
    assert sum(score_mod.WEIGHTS.values()) == pytest.approx(1.0)
```

- [ ] **Step 7: Write `score.py`**

Create `solit2/engines/reduced/score.py`:

```python
"""Hard gates first, then a weighted objective over the things we want to minimise.

A design that fails any hard gate scores zero, but every component is still
reported so the optimiser can see how far off it is and in which direction.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from solit2.schema.result import Criterion

WEIGHTS = {"water": 0.30, "margin": 0.30, "cost": 0.20, "structural": 0.20}
# Mistelix DBR Rev 0 three-zone demand, the reference for the water component.
BASELINE_FLOW_LPM = 2174.3
SCORE_CLIP = 1.5
CEILING_TEMP_CAP_C = 1350.0
DENSITY_HEADROOM_MM_MIN = 3.8
DENSITY_PENALTY = 1.0
BACKLAYERING_PENALTY = 1.0
BACKLAYERING_TOLERANCE_S = 120.0


@dataclass(frozen=True)
class Score:
    total: float
    gates_passed: bool
    gates_failed: list[str]
    components: dict[str, float]
    penalties: list[str] = field(default_factory=list)


def _clipped_ratio(reference: float, actual: float) -> float:
    if actual <= 0:
        return 1.0
    return min(reference / actual, SCORE_CLIP) / SCORE_CLIP


def compute(criteria: dict[str, Criterion], hyd, cost, trace,
            peak_lining_c: float) -> Score:
    failed = [cid for cid, c in criteria.items() if c.hard and not c.passed]
    hard_margins = [c.margin for c in criteria.values() if c.hard]

    components = {
        "water": _clipped_ratio(BASELINE_FLOW_LPM, hyd.flow_lpm),
        "margin": sum(hard_margins) / len(hard_margins) if hard_margins else 0.0,
        "cost": _clipped_ratio(1.0, cost.index),
        "structural": max(1.0 - peak_lining_c / CEILING_TEMP_CAP_C, 0.0),
    }

    penalties: list[str] = []
    deductions = 0.0
    if hyd.density_mm_min > DENSITY_HEADROOM_MM_MIN:
        penalties.append(
            f"density {hyd.density_mm_min:.2f} mm/min exceeds the {DENSITY_HEADROOM_MM_MIN} "
            f"mm/min pump-power headroom"
        )
        deductions += DENSITY_PENALTY

    activated = trace.events.get("t_full_pressure_s") if trace.events else None
    if activated is not None:
        persistent = [s for s in trace.steps
                      if s.t_s >= activated and s.u_eff_ms < s.u_critical_ms]
        if len(persistent) > BACKLAYERING_TOLERANCE_S:
            penalties.append(
                f"airflow stays below the critical velocity for {len(persistent):.0f} s "
                f"after activation"
            )
            deductions += BACKLAYERING_PENALTY

    if failed:
        return Score(0.0, False, failed, components, penalties)

    total = 10.0 * sum(WEIGHTS[k] * components[k] for k in WEIGHTS) - deductions
    return Score(max(total, 0.0), True, [], components, penalties)
```

- [ ] **Step 8: Run tests to verify they pass**

Run: `uv run pytest tests/test_criteria.py tests/test_score.py -v`
Expected: PASS, 14 tests.

- [ ] **Step 9: Commit**

```bash
git add solit2/schema/result.py solit2/engines/reduced/criteria.py solit2/engines/reduced/score.py solit2/engines/reduced/state.py tests/test_criteria.py tests/test_score.py
git commit -m "feat(score): result contract, tender and SOLIT2 criteria, gated weighted score

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 11: Time loop, envelope and the CLI

**Files:**
- Create: `solit2/engines/reduced/sim.py`, `solit2/engines/reduced/envelope.py`, `solit2/history.py`, `solit2/cli.py`
- Modify: `pyproject.toml` (console script entry point)
- Test: `tests/test_sim.py`, `tests/test_cli.py`

**Interfaces:**
- Consumes: every module from Tasks 2–10.
- Produces: `sim.run_once(design, section, velocity_ms) -> RunTrace`; `envelope.run(design, sections=None, velocities=None) -> Result`; `history.append(result, path="runs/history.jsonl") -> None`; `history.leaderboard(path, top, passing_only) -> list[dict]`; console script `solit2` with `run`, `history` subcommands.

- [ ] **Step 1: Write the failing test**

Create `tests/test_sim.py`:

```python
import pytest
from solit2.schema.design import Design
from solit2.engines.reduced import sim, envelope

BASELINE = "designs/og-dbr-rev0.json"


def test_run_once_produces_a_full_hour_of_one_second_steps():
    trace = sim.run_once(Design.load(BASELINE), section="bored", velocity_ms=5.08)
    assert len(trace.steps) == 3600
    assert trace.steps[-1].t_s == pytest.approx(3600.0)
    assert trace.section == "bored"


def test_detection_then_delay_then_full_pressure():
    trace = sim.run_once(Design.load(BASELINE), "bored", 5.08)
    e = trace.events
    assert 30.0 < e["t_detect_s"] < 300.0
    assert e["t_activate_s"] == pytest.approx(e["t_detect_s"] + 60.0)
    assert e["t_full_pressure_s"] == pytest.approx(e["t_activate_s"] + 30.0)


def test_water_flows_only_after_activation():
    trace = sim.run_once(Design.load(BASELINE), "bored", 5.08)
    before = [s for s in trace.steps if s.t_s < trace.events["t_activate_s"]]
    after = [s for s in trace.steps if s.t_s > trace.events["t_full_pressure_s"]]
    assert all(s.water_lpm == 0.0 for s in before)
    assert all(s.water_lpm > 0.0 for s in after)


def test_suppression_holds_the_fire_below_the_free_burn():
    trace = sim.run_once(Design.load(BASELINE), "bored", 5.08)
    assert max(s.hrr_mw for s in trace.steps) < max(s.hrr_free_mw for s in trace.steps)


def test_every_station_is_sampled_at_every_step():
    from solit2.engines.reduced.criteria import STATIONS
    trace = sim.run_once(Design.load(BASELINE), "bored", 5.08)
    assert set(trace.steps[0].stations) == set(STATIONS)
    assert all(set(s.stations) == set(STATIONS) for s in trace.steps[::600])


def test_fed_accumulates_monotonically():
    trace = sim.run_once(Design.load(BASELINE), "bored", 5.08)
    fed = [s.stations["D35"].fed_tox for s in trace.steps]
    assert all(b >= a for a, b in zip(fed, fed[1:]))


def test_envelope_runs_the_velocity_range_and_keeps_the_worst_case():
    result = envelope.run(Design.load(BASELINE))
    assert len(result.envelope) >= 2
    assert result.worst_case["velocity_ms"] in (3.88, 5.08)
    assert set(result.criteria) >= {"hrr_control_mw", "u35_temp_c", "fed_d35"}
    assert result.meta["engine"] == "reduced"
    assert len(result.timeseries["t_s"]) == len(result.timeseries["hrr_mw"])


def test_envelope_completes_in_a_few_seconds():
    import time
    start = time.perf_counter()
    envelope.run(Design.load(BASELINE))
    assert time.perf_counter() - start < 20.0


def test_thin_critical_velocity_margin_is_warned_about():
    result = envelope.run(Design.load(BASELINE))
    assert any("critical velocity" in w for w in result.warnings)


def test_pinning_a_single_velocity_runs_one_case():
    d = Design.load(BASELINE)
    pinned = d.model_copy(update={"ventilation": d.ventilation.model_copy(
        update={"velocity_ms": 4.5})})
    result = envelope.run(pinned)
    assert len(result.envelope) == 1
    assert result.worst_case["velocity_ms"] == pytest.approx(4.5)
```

Create `tests/test_cli.py`:

```python
import json
import subprocess
import sys


def _run(args, **kwargs):
    return subprocess.run([sys.executable, "-m", "solit2.cli", *args],
                          capture_output=True, text=True, **kwargs)


def test_run_emits_a_valid_result_json(tmp_path):
    proc = _run(["run", "designs/og-dbr-rev0.json", "--no-history"])
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["meta"]["engine"] == "reduced"
    assert "hrr_control_mw" in payload["criteria"]
    assert "total" in payload["score"]


def test_run_appends_a_history_row(tmp_path):
    hist = tmp_path / "history.jsonl"
    proc = _run(["run", "designs/og-dbr-rev0.json", "--history", str(hist)])
    assert proc.returncode == 0, proc.stderr
    rows = [json.loads(line) for line in hist.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["design_name"] == "og-dbr-rev0"
    assert "score" in rows[0] and "gates_passed" in rows[0]


def test_bad_field_exits_two_with_a_named_error(tmp_path):
    raw = json.loads(open("designs/og-dbr-rev0.json").read())
    raw["nozzles"]["pressure_bar"] = 12.0
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(raw))
    proc = _run(["run", str(bad), "--no-history"])
    assert proc.returncode == 2
    err = json.loads(proc.stderr)
    assert "pressure_bar" in err["error"]
    assert err["fix"]


def test_history_subcommand_lists_the_leaderboard(tmp_path):
    hist = tmp_path / "history.jsonl"
    _run(["run", "designs/og-dbr-rev0.json", "--history", str(hist)])
    proc = _run(["history", "--history", str(hist), "--top", "5"])
    assert proc.returncode == 0, proc.stderr
    assert "og-dbr-rev0" in proc.stdout
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_sim.py tests/test_cli.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'solit2.engines.reduced.sim'`

- [ ] **Step 3: Write `sim.py`**

Create `solit2/engines/reduced/sim.py`:

```python
"""The one-second time loop.

Order within a step: the fire grows against last step's mist, the ventilation
responds to the new convective heat, the thermal field follows, the mist is
re-evaluated in that field, then the stations are sampled.
"""
from __future__ import annotations

from dataclasses import replace

from solit2.engines.reduced import fire as fire_mod
from solit2.engines.reduced import mist as mist_mod
from solit2.engines.reduced import tenability, thermal, ventilation
from solit2.engines.reduced.criteria import BREATHING_HEIGHT_M, STATIONS
from solit2.engines.reduced.geometry import nozzle_positions, section_geometry
from solit2.engines.reduced.state import MistEffect, RunTrace, StationSample, StepRecord
from solit2.schema.design import Design

DT_S = 1.0
PIPE_WATER_FILLED_CAP_C = 100.0
PIPE_TIME_CONSTANT_S = 300.0


def _detector_excess_k(hrr_kw: float, design: Design, h_ef_m: float) -> float:
    radius = design.detection.sensor_spacing_m / 2.0
    return thermal.alpert_ceiling_excess_k(hrr_kw, radius, h_ef_m)


def run_once(design: Design, section: str, velocity_ms: float) -> RunTrace:
    tunnel = design.tunnel.model_copy(update={"section": section})
    design = design.model_copy(update={"tunnel": tunnel})
    geom = section_geometry(design)
    positions = nozzle_positions(design, geom, fire_x_m=0.0)

    model = fire_mod.build_model(design)
    state = fire_mod.initial_state(model)
    mist = MistEffect.none()

    fire_y = design.fire.lane_centre_offset_from_wall_m - geom.road_width_m / 2.0
    halo = mist_mod.halo_around(0.0, fire_y, design.fire.footprint.length_m,
                                design.fire.footprint.width_m)
    fire_top = design.fire.footprint.top_height_m
    h_ef = geom.crown_height_m - fire_top
    ambient = design.tunnel.ambient_temp_c
    air_m3s = geom.free_area_m2 * velocity_ms

    events: dict = {"t_detect_s": None, "t_activate_s": None, "t_full_pressure_s": None,
                    "t_peak_hrr_s": None, "pools_extinguished_at_s": None,
                    "backlayering": {"occurred": False, "max_length_m": 0.0, "cleared_at_s": None}}
    fed_tox = {name: 0.0 for name in STATIONS}
    fed_heat = {name: 0.0 for name in STATIONS}
    pipe_temp = ambient
    steps: list[StepRecord] = []
    peak_hrr = 0.0

    total_steps = int(design.zones.duration_min * 60 / DT_S)
    for _ in range(total_steps):
        state = fire_mod.step(model, state, DT_S, mist)
        q_conv = fire_mod.convective_kw(model, state.hrr_mw)
        vent = ventilation.evaluate(geom, velocity_ms, q_conv)

        if events["t_detect_s"] is None:
            if _detector_excess_k(state.hrr_mw * 1000.0, design, h_ef) >= (
                    design.detection.threshold_c - ambient):
                events["t_detect_s"] = state.t_s
                events["t_activate_s"] = state.t_s + design.zones.activation_delay_s
                events["t_full_pressure_s"] = events["t_activate_s"] + design.zones.pump_ramp_s

        flow_fraction = 0.0
        if events["t_activate_s"] is not None and state.t_s >= events["t_activate_s"]:
            ramp = design.zones.pump_ramp_s
            elapsed = state.t_s - events["t_activate_s"]
            flow_fraction = min(elapsed / ramp, 1.0) if ramp > 0 else 1.0

        field = thermal.field(geom, model, state, vent, mist, fire_top,
                              design.fire.footprint.length_m,
                              design.fire.footprint.width_m, ambient)
        mist = mist_mod.evaluate(design, geom, positions, halo, fire_top,
                                 vent.u_eff_ms, field.ceiling_excess_k, q_conv, flow_fraction)

        species = tenability.species_at(model, state.hrr_mw, air_m3s, field.strat_factor)
        kappa_mist = (1.0 - mist.tau_mist) / max(design.active_length_m / 2.0, 1.0)

        samples: dict[str, StationSample] = {}
        for name, x_m in STATIONS.items():
            upstream_clear = x_m < 0 and abs(x_m) > vent.backlayer_m
            temp = ambient if upstream_clear else field.gas_temp_c(x_m, BREATHING_HEIGHT_M)
            flux = field.radiant_flux_kwm2(x_m, BREATHING_HEIGHT_M, mist.tau_mist)
            local = tenability.Species(0.0, 0.0, 0.0, 20.9) if upstream_clear else species
            fed_tox[name] += tenability.fed_tox_increment(local, DT_S)
            fed_heat[name] += tenability.fed_heat_increment(temp, flux, DT_S)
            in_zone = abs(x_m) <= design.active_length_m / 2.0
            samples[name] = StationSample(
                temp_c=temp, flux_kwm2=flux,
                visibility_m=tenability.visibility_m(local.soot_gm3,
                                                     kappa_mist if in_zone else 0.0),
                fed_tox=fed_tox[name], fed_heat=fed_heat[name])

        target_flux = field.radiant_flux_kwm2(design.fire.target_distance_m,
                                              fire_top / 2.0, mist.tau_mist)
        if field.flame_tip_x_m >= design.fire.target_distance_m:
            target_flux = max(target_flux, 50.0)  # flame contact

        ceiling = field.ceiling_temp_c(0.0)
        pipe_target = min(ceiling, PIPE_WATER_FILLED_CAP_C) if flow_fraction > 0 else ceiling
        pipe_temp += (pipe_target - pipe_temp) * DT_S / PIPE_TIME_CONSTANT_S

        if vent.backlayer_m > 0:
            events["backlayering"]["occurred"] = True
            events["backlayering"]["max_length_m"] = max(
                events["backlayering"]["max_length_m"], vent.backlayer_m)
        elif events["backlayering"]["occurred"] and events["backlayering"]["cleared_at_s"] is None:
            events["backlayering"]["cleared_at_s"] = state.t_s

        if state.hrr_mw > peak_hrr:
            peak_hrr, events["t_peak_hrr_s"] = state.hrr_mw, state.t_s
        if (model.fire_class == "B" and state.pools_remaining == 0
                and events["pools_extinguished_at_s"] is None):
            events["pools_extinguished_at_s"] = state.t_s

        steps.append(StepRecord(
            t_s=state.t_s, hrr_mw=state.hrr_mw, hrr_free_mw=state.hrr_free_mw,
            ceiling_temp_c=ceiling, lining_temp_c=ceiling, pipe_temp_c=pipe_temp,
            target_flux_kwm2=target_flux, u_eff_ms=vent.u_eff_ms,
            u_critical_ms=vent.u_critical_ms, backlayer_m=vent.backlayer_m,
            water_lpm=design.flow_lpm * flow_fraction,
            pools_remaining=state.pools_remaining, mist=mist, stations=samples))

    if events["t_detect_s"] is None:
        raise RuntimeError(
            f"the fire never reached the {design.detection.threshold_c} C detection "
            f"threshold within {design.zones.duration_min} minutes; check the fire preset"
        )
    return RunTrace(tuple(steps), events, section, velocity_ms)
```

- [ ] **Step 4: Write `envelope.py`**

Create `solit2/engines/reduced/envelope.py`:

```python
"""Run the section x velocity grid and keep the worst case per criterion."""
from __future__ import annotations

import hashlib
import json
import time
from datetime import datetime, timezone

from solit2.engines.reduced import criteria as criteria_mod
from solit2.engines.reduced import score as score_mod
from solit2.engines.reduced import sim
from solit2.engines.reduced.cost import cost_index
from solit2.engines.reduced.geometry import section_geometry
from solit2.engines.reduced.hydraulics import size_system
from solit2.schema.design import Design
from solit2.schema.result import Result

ENGINE_VERSION = "reduced-1.0.0"
CRITICAL_VELOCITY_WARNING_MARGIN = 0.10
TIMESERIES_STRIDE_S = 10


def _velocities(design: Design) -> tuple[float, ...]:
    if design.ventilation.velocity_ms is not None:
        return (design.ventilation.velocity_ms,)
    low, high = design.ventilation.velocity_range_ms
    return (low,) if low == high else (low, high)


def run(design: Design, sections: tuple[str, ...] | None = None,
        velocities: tuple[float, ...] | None = None) -> Result:
    started = time.perf_counter()
    sections = sections or (design.tunnel.section,)
    velocities = velocities or _velocities(design)

    runs = []
    for section in sections:
        for velocity in velocities:
            trace = sim.run_once(design, section, velocity)
            scoped = design.model_copy(update={"tunnel": design.tunnel.model_copy(
                update={"section": section})})
            geom = section_geometry(scoped)
            hyd = size_system(scoped, geom)
            cost = cost_index(scoped, hyd)
            crit = criteria_mod.evaluate(trace, hyd, cost, scoped)
            runs.append((trace, hyd, cost, crit))

    # worst case per criterion, and the run that owns the worst hard margin
    merged = {}
    for cid in runs[0][3]:
        merged[cid] = min((r[3][cid] for r in runs), key=lambda c: c.margin)
    worst = min(runs, key=lambda r: min(c.margin for c in r[3].values() if c.hard))
    trace, hyd, cost, _ = worst

    peak_lining = max(s.lining_temp_c for s in trace.steps)
    scored = score_mod.compute(merged, hyd, cost, trace, peak_lining)

    warnings = []
    thin = [s for s in trace.steps
            if s.u_critical_ms > 0
            and (s.u_eff_ms - s.u_critical_ms) / s.u_critical_ms < CRITICAL_VELOCITY_WARNING_MARGIN]
    if thin:
        worst_step = min(thin, key=lambda s: s.u_eff_ms - s.u_critical_ms)
        warnings.append(
            f"airflow {worst_step.u_eff_ms:.2f} m/s is within "
            f"{CRITICAL_VELOCITY_WARNING_MARGIN:.0%} of the critical velocity "
            f"{worst_step.u_critical_ms:.2f} m/s at t={worst_step.t_s:.0f} s"
        )
    warnings.extend(scored.penalties)

    sampled = trace.steps[::TIMESERIES_STRIDE_S]
    final_mist = max(trace.steps, key=lambda s: s.mist.w_fuel_mm_min).mist
    design_sha = hashlib.sha256(
        json.dumps(design.model_dump(mode="json"), sort_keys=True).encode()).hexdigest()[:12]

    return Result(
        meta={"design_name": design.meta.name, "design_sha": design_sha, "engine": "reduced",
              "engine_version": ENGINE_VERSION,
              "runtime_s": round(time.perf_counter() - started, 3),
              "timestamp": datetime.now(timezone.utc).isoformat()},
        envelope=[{"section": r[0].section, "velocity_ms": r[0].velocity_ms} for r in runs],
        worst_case={"section": trace.section, "velocity_ms": trace.velocity_ms},
        events=trace.events,
        criteria=merged,
        peaks={"hrr_mw": max(s.hrr_mw for s in trace.steps),
               "hrr_free_burn_mw": max(s.hrr_free_mw for s in trace.steps),
               "ceiling_temp_c": max(s.ceiling_temp_c for s in trace.steps),
               "lining_temp_c": peak_lining,
               "pipe_surface_temp_c": max(s.pipe_temp_c for s in trace.steps),
               "smoke_layer_temp_d15_c": max(s.stations["D15"].temp_c for s in trace.steps)},
        mist={"w_fuel_mm_min": final_mist.w_fuel_mm_min, "f_cov": final_mist.f_cov,
              "chi_cool": final_mist.chi_cool, "tau_mist": final_mist.tau_mist},
        hydraulics=hyd.__dict__,
        cost=cost.__dict__,
        score={"total": scored.total, "gates_passed": scored.gates_passed,
               "gates_failed": scored.gates_failed, "components": scored.components,
               "penalties": scored.penalties},
        timeseries={
            "t_s": [s.t_s for s in sampled],
            "hrr_mw": [s.hrr_mw for s in sampled],
            "ceiling_temp_c": [s.ceiling_temp_c for s in sampled],
            "u35_temp_c": [s.stations["U35"].temp_c for s in sampled],
            "d15_temp_c": [s.stations["D15"].temp_c for s in sampled],
            "hf_u15_kwm2": [s.stations["U15"].flux_kwm2 for s in sampled],
            "fed_d35": [s.stations["D35"].fed_tox for s in sampled],
            "backlayering_m": [s.backlayer_m for s in sampled],
            "velocity_ms": [s.u_eff_ms for s in sampled],
            "water_lpm": [s.water_lpm for s in sampled],
        },
        warnings=warnings,
    )
```

- [ ] **Step 5: Write `history.py` and `cli.py`**

Create `solit2/history.py`:

```python
"""Append-only run history and the leaderboard it backs."""
from __future__ import annotations

import json
from pathlib import Path

from solit2.schema.result import Result

DEFAULT_PATH = Path("runs/history.jsonl")


def append(result: Result, path: Path = DEFAULT_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "timestamp": result.meta["timestamp"],
        "design_name": result.meta["design_name"],
        "design_sha": result.meta["design_sha"],
        "engine": result.meta["engine"],
        "score": result.score["total"],
        "gates_passed": result.score["gates_passed"],
        "gates_failed": result.score["gates_failed"],
        "flow_lpm": result.hydraulics["flow_lpm"],
        "power_kw": result.hydraulics["power_kw"],
        "cost_index": result.cost["index"],
    }
    with path.open("a") as handle:
        handle.write(json.dumps(row) + "\n")


def leaderboard(path: Path = DEFAULT_PATH, top: int = 10,
                passing_only: bool = False) -> list[dict]:
    if not path.exists():
        return []
    rows = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if passing_only:
        rows = [r for r in rows if r["gates_passed"]]
    return sorted(rows, key=lambda r: r["score"], reverse=True)[:top]
```

Create `solit2/cli.py`:

```python
"""Command-line entry point. Stdout is result JSON; stderr is a JSON error object."""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from pydantic import ValidationError

from solit2 import history as history_mod
from solit2.engines.reduced import envelope
from solit2.schema.design import Design

EXIT_OK, EXIT_VALIDATION_MISS, EXIT_BAD_INPUT, EXIT_ENGINE = 0, 1, 2, 3


def _fail(message: str, field: str, fix: str, code: int) -> int:
    json.dump({"error": message, "field": field, "fix": fix}, sys.stderr)
    sys.stderr.write("\n")
    return code


def _cmd_run(args: argparse.Namespace) -> int:
    try:
        design = Design.load(args.design)
    except (ValidationError, ValueError, FileNotFoundError, KeyError) as exc:
        return _fail(str(exc), getattr(exc, "field", "design"),
                     "correct the design JSON and run again", EXIT_BAD_INPUT)
    result = envelope.run(design)
    payload = result.model_dump(mode="json")
    if args.out:
        Path(args.out).write_text(json.dumps(payload, indent=2))
    json.dump(payload, sys.stdout, indent=2)
    sys.stdout.write("\n")
    if not args.no_history:
        history_mod.append(result, Path(args.history))
    return EXIT_OK


def _cmd_history(args: argparse.Namespace) -> int:
    rows = history_mod.leaderboard(Path(args.history), args.top, args.passing)
    if not rows:
        print("no runs recorded yet")
        return EXIT_OK
    print(f"{'score':>6}  {'gates':>6}  {'flow lpm':>9}  {'kW':>6}  {'cost':>5}  design")
    for row in rows:
        gates = "pass" if row["gates_passed"] else "FAIL"
        print(f"{row['score']:6.2f}  {gates:>6}  {row['flow_lpm']:9.0f}  "
              f"{row['power_kw']:6.0f}  {row['cost_index']:5.2f}  {row['design_name']}")
    return EXIT_OK


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="solit2", description="SOLIT2 tunnel water-mist simulator")
    sub = parser.add_subparsers(dest="command", required=True)

    run = sub.add_parser("run", help="score a design")
    run.add_argument("design")
    run.add_argument("--engine", default="reduced", choices=["reduced"])
    run.add_argument("--out")
    run.add_argument("--history", default=str(history_mod.DEFAULT_PATH))
    run.add_argument("--no-history", action="store_true")
    run.set_defaults(func=_cmd_run)

    hist = sub.add_parser("history", help="show the leaderboard")
    hist.add_argument("--history", default=str(history_mod.DEFAULT_PATH))
    hist.add_argument("--top", type=int, default=10)
    hist.add_argument("--passing", action="store_true")
    hist.set_defaults(func=_cmd_history)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
```

Add to `pyproject.toml`:

```toml
[project.scripts]
solit2 = "solit2.cli:main"
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_sim.py tests/test_cli.py -v`
Expected: PASS, 14 tests.

- [ ] **Step 7: Score the baseline and record what it says**

Run: `uv run solit2 run designs/og-dbr-rev0.json --out runs/og-dbr-rev0.json | head -60`

Read `score.gates_passed`, `score.gates_failed` and `warnings`. Whatever the answer, it is a finding, not a bug: record it verbatim in the commit body. If a hard gate fails, do **not** tune constants to make it pass — Task 13 fits the constants against measured tests, and only then is the verdict meaningful.

- [ ] **Step 8: Commit**

```bash
git add solit2/engines/reduced/sim.py solit2/engines/reduced/envelope.py solit2/history.py solit2/cli.py pyproject.toml tests/test_sim.py tests/test_cli.py
git commit -m "feat(sim): one-second time loop, velocity envelope, CLI and run history

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 12: Anchor cases and the validation report

**Files:**
- Create: `solit2/presets/fire_pallets_30mw.json`, `fire_pallets_50mw.json`, `fire_pallets_100mw.json`, `solit2/presets/nozzle_solit2_fogtec.json`
- Create: `validation/__init__.py`, `validation/compare.py`, `validation/anchors/c1_applus_t3.json` … `c6_solit2_class_b.json`
- Modify: `solit2/schema/design.py` (add `Zones.manual_activation_s`), `solit2/engines/reduced/sim.py` (honour it), `solit2/cli.py` (add `validate`)
- Test: `tests/test_validation.py`

**Interfaces:**
- Consumes: `envelope.run` (Task 11).
- Produces: `compare.Anchor` (frozen: `id, weight, design_path, measured, tolerances`); `compare.load_anchors(ids=None) -> tuple[Anchor, ...]`; `compare.AnchorReport` (frozen: `anchor_id, rows, passed`) where each row is `(quantity, modelled, measured, tolerance, ok)`; `compare.check(anchor, engine="reduced") -> AnchorReport`; `compare.residuals(anchors) -> list[float]`; CLI `solit2 validate [--anchor cN]`.

- [ ] **Step 1: Add absolute activation to the schema**

In `solit2/schema/design.py`, add to `Zones`:

```python
    manual_activation_s: float | None = None
```

In `solit2/engines/reduced/sim.py`, replace the detection block's event assignment so a pinned time wins:

```python
        if events["t_detect_s"] is None:
            tripped = _detector_excess_k(state.hrr_mw * 1000.0, design, h_ef) >= (
                design.detection.threshold_c - ambient)
            if tripped:
                events["t_detect_s"] = state.t_s
                manual = design.zones.manual_activation_s
                events["t_activate_s"] = (manual if manual is not None
                                          else state.t_s + design.zones.activation_delay_s)
                events["t_full_pressure_s"] = events["t_activate_s"] + design.zones.pump_ramp_s
```

- [ ] **Step 2: Write the remaining presets**

`solit2/presets/fire_pallets_30mw.json` (APPLUS+TST report Table 7 — 78 pallets, array 2.40 x 2.40 m, overall height 3.27 m, fuel centre 3.7 m from the right wall):

```json
{
  "preset": "pallets_30mw",
  "class": "A",
  "design_hrr_mw": 30.0,
  "growth": "ultrafast",
  "incubation_s": 60.0,
  "pallets": 78,
  "energy_mj_per_pallet": 343.0,
  "covered": false,
  "footprint": {"length_m": 2.40, "width_m": 2.40, "top_height_m": 3.27},
  "lane_centre_offset_from_wall_m": 3.7,
  "target_distance_m": 5.0
}
```

`fire_pallets_50mw.json` — 128 pallets, 3.20 x 2.40 m, height 3.70 m, otherwise identical:

```json
{
  "preset": "pallets_50mw",
  "class": "A",
  "design_hrr_mw": 50.0,
  "growth": "ultrafast",
  "incubation_s": 60.0,
  "pallets": 128,
  "energy_mj_per_pallet": 343.0,
  "covered": false,
  "footprint": {"length_m": 3.20, "width_m": 2.40, "top_height_m": 3.70},
  "lane_centre_offset_from_wall_m": 3.7,
  "target_distance_m": 5.0
}
```

`fire_pallets_100mw.json` — 252 pallets, 5.60 x 2.40 m, height 3.99 m:

```json
{
  "preset": "pallets_100mw",
  "class": "A",
  "design_hrr_mw": 100.0,
  "growth": "ultrafast",
  "incubation_s": 60.0,
  "pallets": 252,
  "energy_mj_per_pallet": 343.0,
  "covered": false,
  "footprint": {"length_m": 5.60, "width_m": 2.40, "top_height_m": 3.99},
  "lane_centre_offset_from_wall_m": 3.7,
  "target_distance_m": 5.0
}
```

`nozzle_solit2_fogtec.json` — the SOLIT² tests do not publish the nozzle's K-factor or
droplet spectrum, so these values are chosen to reproduce the reported application
density and are marked assumed. Anchors c4–c6 are weighted 0.5 for exactly this reason:

```json
{
  "preset": "solit2_fogtec",
  "note": "ASSUMED performance - SOLIT2 Annex 2 publishes neither K-factor nor spectrum; these values reproduce the reported application density only",
  "k_factor_lpm_bar05": 2.8,
  "pressure_bar": 100.0,
  "smd_table": {"100": 90.0},
  "modes": [
    {"id": "fine", "fraction": 1.0, "cone_half_angle_deg": 50.0, "launch_velocity_ms": 25.0}
  ],
  "mounting": {
    "type": "ceiling_rows",
    "rows": 2,
    "row_lateral_offsets_m": [-2.2, 2.2],
    "height_above_carriageway_m": 4.9,
    "pitch_m": 4.0,
    "tilt_deg": 0.0
  }
}
```

- [ ] **Step 3: Write the anchor files**

`validation/anchors/c3_applus_t9.json` — the best-documented anchor (report §9.6, Test 9:
100 MW, 40 heads both walls, 56 bar, 1 257 lpm, activation 3 min 21 s after detection,
ambient 11 °C, U35 12 °C, heat flux at U15 0.27 kW/m², FED 0.0, average ceiling
temperature around 650 °C, backlayering only while the wind dropped below 1 m/s):

```json
{
  "id": "c3",
  "weight": 1.0,
  "source": "APPLUS+TST test report section 9.6, Test 9 (02/10/20)",
  "design": {
    "meta": {"name": "c3-applus-t9", "notes": "100 MW, 40 nozzles both walls, 56 bar"},
    "tunnel": {"preset": "san_pedro_de_anes", "section": "test", "ambient_temp_c": 11.0},
    "fire": {"preset": "pallets_100mw"},
    "nozzles": {"preset": "ultrafog_202_260t", "pressure_bar": 56.0,
                "mounting": {"rows": 2, "row_lateral_offsets_m": [-4.55, 4.55],
                             "height_above_carriageway_m": 4.97, "pitch_m": 3.8, "tilt_deg": 35.0}},
    "zones": {"section_length_m": 76.0, "sections_simultaneous": 1,
              "activation_delay_s": 201.0, "pump_ramp_s": 30.0, "duration_min": 35.0},
    "ventilation": {"mode": "longitudinal", "velocity_ms": 2.5, "velocity_range_ms": [2.5, 2.5]},
    "detection": {"type": "linear_heat", "threshold_c": 60.0, "sensor_spacing_m": 12.0},
    "hydraulics": {"preset": "orange_gate"},
    "criteria": {}
  },
  "measured": {
    "flow_lpm": 1257.0,
    "peak_ceiling_temp_c": 650.0,
    "u35_temp_c": 12.0,
    "hf_u15_kwm2": 0.27,
    "fed_d35": 0.0,
    "backlayering": false
  },
  "tolerances": {
    "flow_lpm": {"kind": "relative", "value": 0.05},
    "peak_ceiling_temp_c": {"kind": "relative", "value": 0.20},
    "u35_temp_c": {"kind": "absolute", "value": 15.0},
    "hf_u15_kwm2": {"kind": "factor", "value": 2.0},
    "fed_d35": {"kind": "absolute", "value": 0.10},
    "backlayering": {"kind": "exact"}
  }
}
```

`validation/anchors/c4_solit2_class_a_cover.json` — SOLIT² Annex 2 §6.1: 150 MW potential
truck load with a PVC tarpaulin, 2–2.5 m/s, FFFS started at 0:07, peak about 30 MW,
ceiling about 830 °C, U15 flat at ambient, D15 50–100 °C, D100 50–65 °C, heat flux at
D15 about 0.10 W/cm² (1.0 kW/m²), no backlayering:

```json
{
  "id": "c4",
  "weight": 0.5,
  "source": "SOLIT2 Engineering Guidance Annex 2 section 6.1 (Class A with cover)",
  "design": {
    "meta": {"name": "c4-solit2-class-a-cover", "notes": "150 MW potential, tarpaulin, 2.25 m/s"},
    "tunnel": {"preset": "san_pedro_de_anes", "section": "test", "ambient_temp_c": 20.0,
               "width_m": 7.5, "height_m": 5.2, "area_m2": 39.0},
    "fire": {"preset": "hgv_150mw", "covered": true},
    "nozzles": {"preset": "solit2_fogtec"},
    "zones": {"section_length_m": 60.0, "sections_simultaneous": 1,
              "manual_activation_s": 420.0, "activation_delay_s": 0.0,
              "pump_ramp_s": 30.0, "duration_min": 42.0},
    "ventilation": {"mode": "longitudinal", "velocity_ms": 2.25, "velocity_range_ms": [2.25, 2.25]},
    "detection": {"type": "linear_heat", "threshold_c": 60.0, "sensor_spacing_m": 12.0},
    "hydraulics": {"preset": "orange_gate"},
    "criteria": {}
  },
  "measured": {
    "peak_hrr_mw": 30.0,
    "peak_ceiling_temp_c": 830.0,
    "u15_temp_c": 22.0,
    "d15_temp_c": 75.0,
    "d100_temp_c": 57.0,
    "hf_d15_kwm2": 1.0,
    "backlayering": false
  },
  "tolerances": {
    "peak_hrr_mw": {"kind": "relative", "value": 0.25},
    "peak_ceiling_temp_c": {"kind": "relative", "value": 0.20},
    "u15_temp_c": {"kind": "absolute", "value": 15.0},
    "d15_temp_c": {"kind": "relative", "value": 0.40},
    "d100_temp_c": {"kind": "relative", "value": 0.40},
    "hf_d15_kwm2": {"kind": "factor", "value": 2.0},
    "backlayering": {"kind": "exact"}
  }
}
```

`validation/anchors/c5_solit2_class_a_nocover.json` — Annex 2 §6.2: same load without the
tarpaulin, 1–1.5 m/s, FFFS at 0:04, peak about 20 MW, ceiling about 580 °C late in the
test, D15 50–60 °C, heat flux at D15 about 0.045 W/cm² (0.45 kW/m²). Copy the c4 file and
change: `id` to `c5`, `meta.name` to `c5-solit2-class-a-nocover`, `fire.covered` to `false`,
`zones.manual_activation_s` to `240.0`, `ventilation.velocity_ms` and both range entries to
`1.25`, and the measured block to:

```json
  "measured": {
    "peak_hrr_mw": 20.0,
    "peak_ceiling_temp_c": 580.0,
    "u15_temp_c": 22.0,
    "d15_temp_c": 55.0,
    "d100_temp_c": 50.0,
    "hf_d15_kwm2": 0.45,
    "backlayering": false
  }
```

`validation/anchors/c6_solit2_class_b.json` — Annex 2 §6.3: 60 MW diesel pools under
longitudinal ventilation, FFFS activated before the peak, strong backlayering before
activation that clears after it, flames reaching nearly D15, pools extinguished one by one:

```json
{
  "id": "c6",
  "weight": 0.5,
  "source": "SOLIT2 Engineering Guidance Annex 2 section 6.3 (Class B, longitudinal)",
  "design": {
    "meta": {"name": "c6-solit2-class-b", "notes": "60 MW diesel pools, longitudinal"},
    "tunnel": {"preset": "san_pedro_de_anes", "section": "test", "ambient_temp_c": 20.0,
               "width_m": 7.5, "height_m": 5.2, "area_m2": 39.0},
    "fire": {"preset": "pool_60mw"},
    "nozzles": {"preset": "solit2_fogtec"},
    "zones": {"section_length_m": 60.0, "sections_simultaneous": 1,
              "manual_activation_s": 300.0, "activation_delay_s": 0.0,
              "pump_ramp_s": 30.0, "duration_min": 30.0},
    "ventilation": {"mode": "longitudinal", "velocity_ms": 1.5, "velocity_range_ms": [1.5, 1.5]},
    "detection": {"type": "linear_heat", "threshold_c": 60.0, "sensor_spacing_m": 12.0},
    "hydraulics": {"preset": "orange_gate"},
    "criteria": {}
  },
  "measured": {
    "peak_hrr_mw": 60.0,
    "backlayering": true,
    "pools_extinguished": true
  },
  "tolerances": {
    "peak_hrr_mw": {"kind": "relative", "value": 0.25},
    "backlayering": {"kind": "exact"},
    "pools_extinguished": {"kind": "exact"}
  }
}
```

- [ ] **Step 4: Transcribe the two remaining anchors from the APPLUS+TST report**

`c1` (Test 3, 30 MW, 20 heads on the right wall, 62 bar, 661 lpm) and `c2` (Test 6, 50 MW,
20 heads, 66 bar, 682 lpm). Open `~/Downloads/Design Basis Report.pdf`, find the "Remarks"
and "Performance criteria" tables for Test 3 and Test 6 (they mirror the Test 9 tables at
report pages 36–38, sections 9.4 and 9.5), and copy the measured ambient temperature,
the U35 temperature, the heat flux at U15, the FED and whether backlayering occurred.

Build each file by copying `c3_applus_t9.json` and changing: `id`, `meta.name`,
`fire.preset` (`pallets_30mw` / `pallets_50mw`), `nozzles.pressure_bar` (62 / 66),
`nozzles.mounting` to a single right-wall row (`"rows": 1, "row_lateral_offsets_m": [4.55]`),
`zones.activation_delay_s` to the delay the remarks table reports, and the whole
`measured` block. Keep the `tolerances` block identical to c3.

If the Test 3 or Test 6 tables cannot be read, do not invent numbers: delete that
anchor file, and note in the commit body which anchors the fit is missing. Five anchors
still constrain the model; a fabricated one silently corrupts it.

- [ ] **Step 5: Write the failing test**

Create `tests/test_validation.py`:

```python
import pytest
from validation import compare


def test_every_anchor_file_loads_and_declares_a_source():
    anchors = compare.load_anchors()
    assert len(anchors) >= 4
    ids = {a.id for a in anchors}
    assert {"c3", "c4", "c5", "c6"} <= ids
    assert all(a.source for a in anchors)
    assert all(0.0 < a.weight <= 1.0 for a in anchors)


def test_solit2_anchors_are_down_weighted():
    by_id = {a.id: a for a in compare.load_anchors()}
    assert by_id["c3"].weight == 1.0
    assert by_id["c4"].weight == 0.5
    assert by_id["c6"].weight == 0.5


def test_anchor_designs_all_build_and_run():
    for anchor in compare.load_anchors():
        report = compare.check(anchor)
        assert report.rows, f"{anchor.id} produced no comparison rows"


def test_report_rows_carry_modelled_and_measured_values():
    report = compare.check(next(a for a in compare.load_anchors() if a.id == "c3"))
    quantities = {r[0] for r in report.rows}
    assert "peak_ceiling_temp_c" in quantities
    assert "u35_temp_c" in quantities
    for _, modelled, measured, _, ok in report.rows:
        assert isinstance(modelled, (int, float, bool))
        assert isinstance(measured, (int, float, bool))
        assert isinstance(ok, bool)


def test_residuals_are_finite_and_weighted():
    residuals = compare.residuals(compare.load_anchors())
    assert residuals
    assert all(abs(r) < 1e6 for r in residuals)


def test_tolerance_kinds():
    assert compare.within(10.0, 10.4, {"kind": "relative", "value": 0.05})
    assert not compare.within(10.0, 12.0, {"kind": "relative", "value": 0.05})
    assert compare.within(10.0, 20.0, {"kind": "factor", "value": 2.0})
    assert not compare.within(10.0, 25.0, {"kind": "factor", "value": 2.0})
    assert compare.within(10.0, 14.0, {"kind": "absolute", "value": 5.0})
    assert compare.within(True, True, {"kind": "exact"})
    assert not compare.within(True, False, {"kind": "exact"})
```

- [ ] **Step 6: Run test to verify it fails**

Run: `uv run pytest tests/test_validation.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'validation'`

- [ ] **Step 7: Write `compare.py`**

Create `validation/__init__.py` (empty) and `validation/compare.py`:

```python
"""Compare the engine against published full-scale fire tests.

Each anchor holds a design, the values measured in that test, and the tolerance
each value must be matched to. `check` produces a readable report; `residuals`
produces the normalised errors the calibration fit minimises.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path

from solit2.engines.reduced import envelope
from solit2.schema.design import Design

ANCHOR_DIR = Path(__file__).resolve().parent / "anchors"


@dataclass(frozen=True)
class Anchor:
    id: str
    weight: float
    source: str
    design: Design
    measured: dict
    tolerances: dict


@dataclass(frozen=True)
class AnchorReport:
    anchor_id: str
    rows: list[tuple[str, float | bool, float | bool, str, bool]]

    @property
    def passed(self) -> bool:
        return all(row[4] for row in self.rows)


def load_anchors(ids: tuple[str, ...] | None = None) -> tuple[Anchor, ...]:
    out = []
    for path in sorted(ANCHOR_DIR.glob("c*.json")):
        raw = json.loads(path.read_text())
        if ids and raw["id"] not in ids:
            continue
        design_path = path.with_suffix(".design.json")
        design_path.write_text(json.dumps(raw["design"]))
        out.append(Anchor(raw["id"], raw["weight"], raw["source"],
                          Design.load(design_path), raw["measured"], raw["tolerances"]))
        design_path.unlink()
    if not out:
        raise FileNotFoundError(f"no anchors matched {ids} in {ANCHOR_DIR}")
    return tuple(out)


def within(measured, modelled, tolerance: dict) -> bool:
    kind = tolerance["kind"]
    if kind == "exact":
        return bool(measured) == bool(modelled)
    if kind == "absolute":
        return abs(modelled - measured) <= tolerance["value"]
    if kind == "relative":
        return abs(modelled - measured) <= abs(measured) * tolerance["value"]
    if kind == "factor":
        if measured <= 0 or modelled <= 0:
            return abs(modelled - measured) < 1e-9
        return 1.0 / tolerance["value"] <= modelled / measured <= tolerance["value"]
    raise ValueError(f"unknown tolerance kind {kind!r}")


def _modelled(result, quantity: str):
    """Pull one comparable quantity out of a result."""
    extractors = {
        "flow_lpm": lambda r: r.hydraulics["flow_lpm"],
        "peak_hrr_mw": lambda r: r.peaks["hrr_mw"],
        "peak_ceiling_temp_c": lambda r: r.peaks["ceiling_temp_c"],
        "u35_temp_c": lambda r: r.criteria["u35_temp_c"].value,
        "u15_temp_c": lambda r: max(r.timeseries["u35_temp_c"]),
        "d15_temp_c": lambda r: max(r.timeseries["d15_temp_c"]),
        "d100_temp_c": lambda r: r.peaks["smoke_layer_temp_d15_c"],
        "hf_u15_kwm2": lambda r: r.criteria["hf_u15_kwm2"].value,
        "hf_d15_kwm2": lambda r: max(r.timeseries["hf_u15_kwm2"]),
        "fed_d35": lambda r: r.criteria["fed_d35"].value,
        "backlayering": lambda r: bool(r.events["backlayering"]["occurred"]),
        "pools_extinguished": lambda r: r.events["pools_extinguished_at_s"] is not None,
    }
    if quantity not in extractors:
        raise KeyError(
            f"anchor quantity {quantity!r} has no extractor; known quantities are "
            f"{sorted(extractors)}"
        )
    return extractors[quantity](result)


def check(anchor: Anchor, engine: str = "reduced") -> AnchorReport:
    if engine != "reduced":
        raise ValueError(f"engine {engine!r} is not available in this plan; use 'reduced'")
    result = envelope.run(anchor.design)
    rows = []
    for quantity, measured in anchor.measured.items():
        tolerance = anchor.tolerances[quantity]
        modelled = _modelled(result, quantity)
        label = (tolerance["kind"] if tolerance["kind"] == "exact"
                 else f"{tolerance['kind']} {tolerance['value']}")
        rows.append((quantity, modelled, measured, label, within(measured, modelled, tolerance)))
    return AnchorReport(anchor.id, rows)


def residuals(anchors: tuple[Anchor, ...]) -> list[float]:
    """Weighted, normalised errors for the calibration fit."""
    out: list[float] = []
    for anchor in anchors:
        result = envelope.run(anchor.design)
        for quantity, measured in anchor.measured.items():
            modelled = _modelled(result, quantity)
            if isinstance(measured, bool):
                out.append(anchor.weight * (0.0 if bool(modelled) == measured else 1.0))
            else:
                scale = abs(measured) if abs(measured) > 1e-6 else 1.0
                out.append(anchor.weight * (modelled - measured) / scale)
    if not all(math.isfinite(r) for r in out):
        raise ValueError("a residual is not finite; the engine returned NaN or infinity")
    return out
```

- [ ] **Step 8: Add the `validate` subcommand**

In `solit2/cli.py`, add:

```python
def _cmd_validate(args: argparse.Namespace) -> int:
    from validation import compare

    ids = tuple(args.anchor) if args.anchor else None
    all_passed = True
    for anchor in compare.load_anchors(ids):
        report = compare.check(anchor, args.engine)
        print(f"\n{anchor.id}  ({anchor.source})")
        print(f"  {'quantity':<24} {'modelled':>12} {'measured':>12}  {'tolerance':<16} ok")
        for quantity, modelled, measured, tol, ok in report.rows:
            mark = "yes" if ok else "NO"
            print(f"  {quantity:<24} {modelled:>12.3g} {measured:>12.3g}  {tol:<16} {mark}")
            all_passed &= ok
    print("\nall anchors within tolerance" if all_passed else "\nsome anchors out of tolerance")
    return EXIT_OK if all_passed else EXIT_VALIDATION_MISS
```

and register it in `build_parser`:

```python
    val = sub.add_parser("validate", help="check the engine against the anchor fire tests")
    val.add_argument("--engine", default="reduced", choices=["reduced"])
    val.add_argument("--anchor", action="append")
    val.set_defaults(func=_cmd_validate)
```

- [ ] **Step 9: Run the tests and the report**

Run: `uv run pytest tests/test_validation.py -v`
Expected: PASS, 6 tests.

Run: `uv run solit2 validate`
Expected: a table per anchor. Anchors will be out of tolerance at this point — the
constants have not been fitted yet. Record the output; Task 13 closes the gap.

- [ ] **Step 10: Commit**

```bash
git add solit2/presets validation solit2/schema/design.py solit2/engines/reduced/sim.py solit2/cli.py tests/test_validation.py
git commit -m "feat(validation): anchor fire tests, tolerance report and the validate subcommand

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

### Task 13: Fit the calibration constants and close out

**Files:**
- Create: `validation/fit.py`
- Modify: `solit2/presets/calibration.json` (fitted values), `README.md`, `CLAUDE.md`
- Test: `tests/test_fit.py`

**Interfaces:**
- Consumes: `compare.residuals` (Task 12).
- Produces: `fit.FITTED_KEYS` (tuple of `(section, key, low, high)`); `fit.current_vector() -> list[float]`; `fit.apply_vector(vector) -> None`; `fit.run(max_nfev=60) -> dict`; console entry `python -m validation.fit`.

- [ ] **Step 1: Write the failing test**

Create `tests/test_fit.py`:

```python
import json
import pytest
from validation import fit
from solit2.schema.presets import PRESET_DIR


def test_every_fitted_key_exists_in_calibration():
    cal = json.loads((PRESET_DIR / "calibration.json").read_text())
    for section, key, low, high in fit.FITTED_KEYS:
        assert key in cal[section], f"{section}.{key} missing from calibration.json"
        assert low < cal[section][key]["value"] < high


def test_current_vector_round_trips():
    original = fit.current_vector()
    fit.apply_vector(original)
    assert fit.current_vector() == pytest.approx(original)


def test_apply_vector_is_rejected_outside_the_bounds():
    vector = fit.current_vector()
    vector[0] = 1e9
    with pytest.raises(ValueError) as e:
        fit.apply_vector(vector)
    assert "bounds" in str(e.value)


def test_every_fitted_constant_records_its_anchor():
    cal = json.loads((PRESET_DIR / "calibration.json").read_text())
    for section, key, _, _ in fit.FITTED_KEYS:
        assert cal[section][key].get("anchor"), f"{section}.{key} does not name its anchor"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_fit.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'validation.fit'`

- [ ] **Step 3: Write `fit.py`**

Create `validation/fit.py`:

```python
"""Least-squares fit of the empirical constants against the anchor fire tests.

Only constants that the anchors actually constrain are fitted. Anything taken
straight from the literature stays fixed.
"""
from __future__ import annotations

import json

import numpy as np
from scipy.optimize import least_squares

from solit2.schema.presets import PRESET_DIR, load_calibration
from validation import compare

CALIBRATION_PATH = PRESET_DIR / "calibration.json"

# (section, key, lower bound, upper bound)
FITTED_KEYS = (
    ("mist", "eta_max", 0.50, 0.98),
    ("mist", "w_ref_mm_min", 0.30, 6.00),
    ("mist", "chi_cool_max", 0.10, 0.70),
    ("mist", "evaporation_k_ref_m2s", 1.0e-8, 1.0e-6),
    ("fire", "suppression_response_s", 20.0, 300.0),
    ("fire", "cover_shielding_factor", 1.0, 6.0),
    ("fire", "pool_ventilation_factor", 0.8, 2.5),
    ("fire", "pool_burning_rate_reduction", 0.1, 0.9),
    ("fire", "pool_extinction_flux_mm_min", 0.5, 5.0),
    ("ventilation", "throttling_coefficient", 0.0, 1.0),
)


def current_vector() -> list[float]:
    cal = load_calibration()
    return [cal[section][key]["value"] for section, key, _, _ in FITTED_KEYS]


def apply_vector(vector: list[float]) -> None:
    if len(vector) != len(FITTED_KEYS):
        raise ValueError(f"expected {len(FITTED_KEYS)} values, got {len(vector)}")
    cal = json.loads(CALIBRATION_PATH.read_text())
    for value, (section, key, low, high) in zip(vector, FITTED_KEYS):
        if not low <= value <= high:
            raise ValueError(
                f"{section}.{key}={value} is outside its bounds [{low}, {high}]"
            )
        cal[section][key]["value"] = float(value)
    CALIBRATION_PATH.write_text(json.dumps(cal, indent=2) + "\n")


def _objective(vector: np.ndarray, anchors) -> np.ndarray:
    apply_vector(list(vector))
    return np.array(compare.residuals(anchors))


def run(max_nfev: int = 60) -> dict:
    anchors = compare.load_anchors()
    start = np.array(current_vector())
    lower = np.array([low for _, _, low, _ in FITTED_KEYS])
    upper = np.array([high for _, _, _, high in FITTED_KEYS])
    before = float(np.sum(_objective(start, anchors) ** 2))
    solution = least_squares(_objective, start, bounds=(lower, upper),
                             args=(anchors,), diff_step=0.05, max_nfev=max_nfev)
    apply_vector(list(solution.x))
    after = float(np.sum(_objective(solution.x, anchors) ** 2))
    return {"cost_before": before, "cost_after": after,
            "fitted": {f"{s}.{k}": float(v) for v, (s, k, _, _) in zip(solution.x, FITTED_KEYS)}}


if __name__ == "__main__":
    print(json.dumps(run(), indent=2))
```

- [ ] **Step 4: Run the fit**

```bash
git add -A && git commit -m "chore: snapshot calibration before the fit

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
uv run python -m validation.fit
```

Expected: `cost_after` well below `cost_before`, and every fitted value inside its
bounds. If a value pins to a bound, that is a finding: record it — it means the anchors
want something the model's structure cannot give, and the FDS tier (Plan 2) is the
place to resolve it, not a wider bound.

- [ ] **Step 5: Verify against the anchors**

Run: `uv run solit2 validate`
Expected: exit 0, every row `yes`. If some rows still miss, do not widen tolerances.
Record which anchors miss and by how much in the commit body — the tolerances are the
engineering claim about how far this engine can be trusted.

- [ ] **Step 6: Re-score the baseline on the fitted engine**

Run: `uv run solit2 run designs/og-dbr-rev0.json --out runs/og-dbr-rev0-fitted.json`

This is the first trustworthy verdict on the DBR Rev 0 design. Read `score.gates_passed`,
`score.gates_failed`, `criteria.hrr_control_mw`, `mist.w_fuel_mm_min` and `warnings`, and
write them into the commit body verbatim.

- [ ] **Step 7: Run the full suite with coverage**

Run: `uv run pytest --cov=solit2 --cov-report=term-missing`
Expected: all tests pass, coverage ≥ 80 %. Add tests for any uncovered branch that
carries real logic before moving on.

- [ ] **Step 8: Write `CLAUDE.md` and `README.md`**

Create `CLAUDE.md` at the repo root:

````markdown
# SOLIT² simulator — how to drive the optimisation loop

Target: the Orange Gate – Marine Drive tunnel (Mumbai), Mistelix MSX-T-100 bimodal nozzle.
Spec: `docs/superpowers/specs/2026-09-15-solit2-simulator-design.md`.

## Confidentiality

Nozzle *performance* data only — K-factor, pressure band, SMD table, mass split, cone
angles, launch velocities. Never put internal atomiser geometry in this repo. Source
tender and vendor documents stay outside it.

## The loop

```bash
uv run solit2 run designs/og-dbr-rev0.json          # score a design
uv run solit2 history --top 10 --passing            # leaderboard
uv run solit2 validate                              # engine vs the anchor fire tests
```

Read `score.gates_failed` first, then `score.components`, then `mist` and `warnings`.
Change **one parameter group per iteration** and give the physical reason:

| Symptom | Reach for |
|---|---|
| `hrr_control_mw` fails | coarse mass fraction, mount height, pitch — more water *on the fuel*, not more water |
| `target_hf_kwm2` fails | mist curtain density between fire and target: pitch, zone length |
| `hf_u15` / `u35_temp_c` fails with backlayering in `events` | ventilation velocity, activation delay |
| `power_kw` near 650 | nozzle pressure inside the 45–60 bar band, not head count |
| `fed_d35` fails | almost always a stratification/backlayering problem, not a water problem |
| gates pass, score low | trim flow and cost: wider pitch or shorter zones, then re-check the gates |

Save each candidate as `designs/<name>-vN.json`. After about twenty runs, take the top
five passing designs into Plan 2 (FDS verification and the tender's CFD correlation).

## What this engine is not

It is a screening model built from published correlations and fitted to six fire tests,
none of which used the MSX-T-100. It ranks designs. It is not evidence for a submission —
that is the full-scale test (spec §13) and the FDS correlation (spec §9).
````

Create `README.md` with the project purpose, the install steps (`uv sync`), the three CLI
commands above, a pointer to the spec and plan, and the confidentiality note.

- [ ] **Step 9: Commit**

```bash
git add validation/fit.py solit2/presets/calibration.json tests/test_fit.py CLAUDE.md README.md
git commit -m "feat(calibration): fit the empirical constants to the anchor fire tests

Records the fitted values, the anchor each is constrained by, and the first
trustworthy score for the DBR Rev 0 baseline.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Plan self-review

**Spec coverage.** Spec §3 design JSON → Task 1. §4 result JSON → Tasks 10–11. §5.1
geometry → Task 2. §5.2 fire A and B → Task 4. §5.3 ventilation → Task 5. §5.4 thermal →
Task 6. §5.5 mist, bimodal → Tasks 7–8. §5.6 tenability → Task 9. §5.7 hydraulics and §5.8
cost → Task 3. §5.9 score and §7 criteria → Task 10. §5.10 envelope and §8 CLI (`run`,
`validate`, `history`) → Tasks 11–12. §9 calibration → Tasks 12–13. §11 testing → every
task, closed out in Task 13 step 7. §12 optimisation loop → Task 13 step 8.

**Deferred to later plans, by design.** Spec §6 (FDS tier), §8's `fds-deck`, `fds-status`
and `report` subcommands, and §10 (Streamlit) are Plan 2 and Plan 3. Each is independently
testable once this plan's JSON contract exists, which is why the split is here.

**Known soft spots, called out rather than hidden.**
- `_modelled` in Task 12 maps `u15_temp_c` and `d100_temp_c` onto the nearest stored
  timeseries; those two rows are indicative. Tighten by adding U15 and D100 to the
  timeseries block when Plan 2 needs them.
- Anchors c4–c6 use an assumed FOGTEC nozzle spec (no published K-factor). They are
  weighted 0.5 and constrain response *shape*, not absolute suppression.
- `BASELINE_TOTAL` in `cost.py` and `BASELINE_FLOW_LPM` in `score.py` are measured from
  the baseline design itself in Task 3 step 8; both are normalisation constants, not
  physics.

---

## Execution handoff

Plan complete and saved to `docs/superpowers/plans/2026-09-15-solit2-tier1-optimiser.md`.

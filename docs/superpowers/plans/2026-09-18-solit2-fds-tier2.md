# SOLIT2 Tier 2 (FDS/CFD) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Tier 2 FDS pipeline — deck generation, run management, output parsing into the existing `Result` contract, CLI wiring, and the Verify view — testable end to end without a live FDS install.

**Architecture:** `deck.py` turns a `Design` into deterministic FDS namelist text, reusing Tier 1's own geometry and station definitions so both tiers describe the same tunnel and measure the same points. `runner.py` handles pre-flight/launch/status. `reader.py` parses FDS's CSV output into the same frozen `RunTrace` dataclasses Tier 1 produces, then calls Tier 1's `criteria.evaluate()` unchanged — so an FDS result is scored by identical Annex 7 logic and is interchangeable with a Tier 1 result everywhere downstream.

**Tech Stack:** Python 3.12, `uv`, pydantic v2, pytest, Streamlit 1.37, FDS 6.11.1 namelist format (no FDS binary required to build or test this).

**Spec:** [docs/superpowers/specs/2026-09-18-solit2-fds-tier2-design.md](../specs/2026-09-18-solit2-fds-tier2-design.md) (parent: [2026-09-15-solit2-simulator-design.md](../specs/2026-09-15-solit2-simulator-design.md))

## Global Constraints

- **Single-mode nozzle only.** One `&PROP`/`&PART`/`&DEVC` per head. Never emit the spec's bimodal `NOZ_FINE` + `NOZ_COARSE` pair, whatever parent spec §6 says. This is a standing user decision.
- **No live FDS.** Nothing in this plan may require the `fds` binary to run. Every test uses golden files, mocks, or fixtures.
- **Reuse, never reimplement.** Tunnel geometry comes from `solit2.engines.reduced.geometry`; station positions and instruments from `solit2.engines.reduced.criteria`; criteria evaluation, hydraulics and cost from their existing Tier 1 functions. Do NOT reimplement `fire.py`/`mist.py`/`ventilation.py`/`thermal.py` physics — FDS computes that directly.
- **Commit messages:** conventional commits (`feat:`, `fix:`, `docs:`, `test:`). No `Co-Authored-By` trailer — attribution is disabled globally for this user.
- **Style:** files ≤ 400 lines target, functions ≤ 50 lines, frozen dataclasses, no in-place mutation, `from __future__ import annotations` at the top of every module. Run `uv run ruff check` before every commit.
- **Test command:** `uv run pytest -q` from the repo root. App/view tests resolve `AppTest.from_file("../app/streamlit_app.py")` relative to the *test file's* directory — this exact relative path, not a repo-root path.
- **Absent is not zero.** `StationSample` optional fields are `None` where Annex 7 Table 5 places no sensor. Never write `0.0` for a missing reading.

---

## File Structure

| File | Responsibility |
|---|---|
| `designs/og-dbr-rev0.json` | The Orange Gate baseline design — golden-deck fixture and the starting point `CLAUDE.md` §12's loop needs. Built on the neutral `examples/presets/` with every DBR figure as an explicit inline override |
| `solit2/engines/fds/__init__.py` | Package marker |
| `solit2/engines/fds/deck.py` | `generate(design) -> str`; deterministic namelist text |
| `solit2/engines/fds/runner.py` | `preflight()`, `run()`, `status()` |
| `solit2/engines/fds/reader.py` | `read(run_dir, design) -> Result` |
| `solit2/cli.py` | + `fds-deck`, `fds-status`, `--engine fds` |
| `app/views/verify.py` | Rewritten: pre-flight, deck, run, progress, Tier 1 vs Tier 2 |
| `tests/fixtures/fds/*` | Golden decks and the synthetic device-output fixture |

---

## Task 1: Orange Gate preset and baseline design

**Files:**
- Create: `designs/og-dbr-rev0.json`
- Test: `tests/test_orange_gate_baseline.py`

**CORRECTION (made during execution, after this task's first review round).** An earlier
version of this task created `solit2/presets/tunnel_orange_gate.json` and two sibling presets.
That violates `INDEPENDENCE.md` rule 1 — "Nothing inside `solit2/` describes any real product"
— which is enforced by `tests/test_independence.py::test_no_file_in_the_package_names_a_vendor_or_a_project`
and, for the 4240 m tube length, by `test_no_retired_tube_length_survives_in_the_package_or_the_examples`.
The parent spec's repo layout (which names `tunnel_orange_gate.json` in `solit2/presets/`)
predates that architecture; the shipped tests are the binding authority. Project data lives in
`designs/`, which both independence scans deliberately exclude. Every DBR figure is an explicit
override in the design file — never inherited silently from an illustration preset whose own
note says to replace it.

**Interfaces:**
- Consumes: `Design.load(path)`, `envelope.run(design)` (both existing).
- Produces: `designs/og-dbr-rev0.json`, loadable by `Design.load`, used as a golden-deck input by Tasks 2, 3 and 6.

Context: `designs/` does not exist yet. `examples/presets/tunnel_twin_bore_11m.json` is a deliberately genericised illustration — an 11 m circular twin bore, which is the right shape here — and the baseline references it while overriding every project figure explicitly. Depending on `examples/` is fine for a design in `designs/`: the "must not depend on optional `examples/`" rule governs what the package SHIPS, and `designs/` ships nothing.

- [ ] **Step 1: Write the failing test**

Create `tests/test_orange_gate_baseline.py`:

```python
import pytest

from solit2.engines.reduced import envelope
from solit2.schema.design import Design

BASELINE = "designs/og-dbr-rev0.json"


def test_the_orange_gate_baseline_loads():
    design = Design.load(BASELINE)
    assert design.meta.name == "og-dbr-rev0"
    assert design.tunnel.shape == "circle"


def test_the_dbr_figures_are_stated_in_the_design_not_inherited():
    """A preset under examples/ is an illustration whose own note says to
    replace it. If one of these values ever arrives by inheritance, an edit to
    that illustration silently moves this project's baseline."""
    design = Design.load(BASELINE)
    assert design.nozzles.k_factor_lpm_bar05 == 4.1
    assert design.nozzles.pressure_bar == 50.0
    assert design.tunnel.internal_diameter_m == 11.0
    assert design.nozzles.mounting.height_above_carriageway_m == 5.5


def test_the_baseline_matches_the_dbr_hydraulics_numbers():
    design = Design.load(BASELINE)
    # DBR: K 4.1, 50 bar -> 29.0 lpm per head; 25 heads per 30 m zone;
    # 3 zones simultaneous. The spec reaches 2175 by rounding per-head to 29.0
    # first; flow_lpm multiplies the unrounded 28.9914 and reaches 2174.35.
    # Parent spec section 5.7 checks hydraulics figures to +/-0.5%.
    assert round(design.nozzles.flow_per_head_lpm, 1) == 29.0
    assert design.active_heads == 75
    assert design.flow_lpm == pytest.approx(2175.0, rel=0.005)


def test_the_baseline_runs_through_tier_1():
    result = envelope.run(Design.load(BASELINE))
    assert result.meta["design_name"] == "og-dbr-rev0"
    assert "target_ignited" in result.criteria


def test_the_baseline_is_not_reported_as_a_placeholder_illustration():
    result = envelope.run(Design.load(BASELINE))
    assert not [w for w in result.warnings if "placeholder" in w.lower()]
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `uv run pytest tests/test_orange_gate_baseline.py -q`
Expected: FAIL — `FileNotFoundError` on `designs/og-dbr-rev0.json`.

- [ ] **Step 3 and 4: Write the baseline design**

Create `designs/og-dbr-rev0.json`. Copy `examples/designs/road-tunnel-twin-bore-single-mode.json` as the structural starting point (same single-mode nozzle shape), keep its neutral preset references (`twin_bore_11m`, `hgv_150mw`, `single_mode_fine_example`, `example`), and set `meta.name` to `"og-dbr-rev0"`.

Every DBR figure goes in as an **explicit override**, never left to resolve from the preset — an illustration preset's value silently becoming a project baseline's input is the defect this task already had once:

`tunnel.section` `"bored"`, `tunnel.internal_diameter_m` `11.0`, `tunnel.deck_below_centre_m` `2.125`, `tunnel.length_m` `4240.0`, `tunnel.gradient_pct` `0.0`, `nozzles.k_factor_lpm_bar05` `4.1`, `nozzles.pressure_bar` `50.0`, the fine mode's `smd_um` `100`, `nozzles.mounting.height_above_carriageway_m` `5.5`, `zones.section_length_m` `30.0`, `zones.sections_simultaneous` `3`, `ventilation.velocity_range_ms` `[3.88, 5.08]`.

Do NOT use the `template` presets — `envelope._placeholder_warnings` fires on `preset == "template"` and would stamp "this result is an illustration and not an assessment" onto a design carrying real data.

`meta.notes` records that these are DBR Rev 0 figures, that this file is the optimisation loop's baseline, and — by field name — which values are still inherited from the illustration presets rather than measured (`cone_half_angle_deg`, `launch_velocity_ms`, `hydraulics.static_head_bar`, `hydraulics.fittings_loss_bar`), so nobody mistakes the file for a complete DBR transcription. Keep `ahj` empty — Annex 7 §7.1 leaves every acceptance limit to the authority.

Verify `active_heads` lands on 75: `heads_per_zone` must resolve to 25 for a 30 m zone, which it does when `mounting.pitch_m` is 2.4 with 2 rows. If it does not, adjust `zones.heads_per_zone` explicitly to 25 rather than fighting the pitch.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_orange_gate_baseline.py -q`
Expected: PASS (3 tests).

- [ ] **Step 6: Commit**

```bash
git add designs/og-dbr-rev0.json tests/test_orange_gate_baseline.py
git commit -m "feat(presets): Orange Gate tunnel preset and the DBR Rev 0 baseline design"
```

---

## Task 2: Deck structure — header, mesh, tunnel envelope, portals

**Files:**
- Create: `solit2/engines/fds/__init__.py`, `solit2/engines/fds/deck.py`
- Modify: `.gitignore` (negate the fixture directory)
- Test: `tests/test_fds_deck.py`

**Interfaces:**
- Consumes: `geometry.section_geometry(design) -> SectionGeometry` (fields `road_width_m`, `crown_height_m`, `free_area_m2`, `shape`, `radius_m`, `deck_below_centre_m`, method `width_at(h)`); `envelope._design_sha(design) -> str`.
- Produces: `deck.generate(design: Design, fine_dx_m: float = FINE_DX_M) -> str`, `deck.FIRE_X_M = 0.0`, `deck.WINDOW_M = (-360.0, 240.0)`, `deck.CORE_M = (-60.0, 120.0)`, `deck.FINE_DX_M = 0.5`, `deck.COARSE_RATIO = 3`. Task 3 extends `generate`; Task 6 calls it from the CLI; Task 7 calls it from the Verify view.

**Why the domain is 600 m, not the spec's 180 m.** `criteria.evaluate` reads all fifteen Annex 7 Table 5 stations, which span U340 to D215 — 555 m. The parent spec's `U60 → D120` window predates the code's move to the real Table 5 station set and holds only twelve of them; a deck built to it produces a `RunTrace` missing `U340`, `U100` and `D215`, and `criteria._worst_station_value` raises `KeyError` on the first one it reaches. Widening the domain uniformly would triple the cell count, so the domain is **nested**: fine cells over the core where the fire is, coarse cells over the far approach and exit, which carry near-uniform flow and exist only so those three far stations are measured rather than absent.

| Mesh | Span | dx | Cells |
|---|---|---|---|
| far upstream | −360 → −60 m | 1.5 m | 200 × 7 × 5 ≈ 7 k |
| core | −60 → +120 m | 0.5 m | 360 × 22 × 15 ≈ 119 k |
| far downstream | +120 → +240 m | 1.5 m | 80 × 7 × 5 ≈ 3 k |

≈ 129 k cells, under the parent spec's own ~180 k screening budget. At 150 MW, `D* = 7.1 m`, so the core's `D*/dx = 14.2` — inside the spec's stated 10–16 band. The coarse meshes are far below it deliberately: there is no fire there. The 3:1 ratio and the mesh boundaries at −60/+120 make every mesh's span an exact multiple of its own `dx`, which is what keeps the interfaces aligned.

**CRITICAL — `.gitignore` collision:** the repo ignores `*.fds`, `*_devc.csv` and `*_hrr.csv` (run outputs). The golden decks and the reader fixture are deliberately-committed test data with those exact extensions. Without a negation they are written, never committed, and every test passes locally then fails in a fresh clone.

- [ ] **Step 1: Negate the fixture directory in `.gitignore`**

Append to the "run outputs" block in `.gitignore`:

```
# ...but test fixtures with those extensions ARE committed on purpose
!tests/fixtures/fds/
!tests/fixtures/fds/**
```

Verify: `mkdir -p tests/fixtures/fds && touch tests/fixtures/fds/probe.fds && git check-ignore -v tests/fixtures/fds/probe.fds` must print nothing (exit 1). Then `rm tests/fixtures/fds/probe.fds`.

- [ ] **Step 2: Write the failing test**

Create `tests/test_fds_deck.py`:

```python
from solit2.engines.fds import deck
from solit2.schema.design import Design

BASELINE = "designs/og-dbr-rev0.json"
TEST_RIG = "examples/designs/solit2-test-protocol.json"


def test_the_deck_opens_with_head_and_closes_with_tail():
    text = deck.generate(Design.load(BASELINE))
    assert text.startswith("&HEAD")
    assert text.rstrip().endswith("&TAIL /")


def test_the_deck_is_deterministic():
    design = Design.load(BASELINE)
    assert deck.generate(design) == deck.generate(design)


def test_the_chid_is_the_design_sha():
    from solit2.engines.reduced.envelope import _design_sha
    design = Design.load(BASELINE)
    assert f"CHID='{_design_sha(design)}'" in deck.generate(design)


def test_the_domain_holds_every_station_the_criteria_read():
    from solit2.engines.reduced.criteria import STATIONS
    text = deck.generate(Design.load(BASELINE))
    mesh_lines = [ln for ln in text.splitlines() if ln.startswith("&MESH")]
    assert len(mesh_lines) == 3, "far upstream, core, far downstream"
    assert str(deck.WINDOW_M[0]) in mesh_lines[0]
    assert str(deck.WINDOW_M[1]) in mesh_lines[-1]
    for x_m in STATIONS.values():
        assert deck.WINDOW_M[0] <= x_m <= deck.WINDOW_M[1]


def test_the_core_mesh_is_finer_than_the_far_field():
    text = deck.generate(Design.load(BASELINE))
    mesh_lines = [ln for ln in text.splitlines() if ln.startswith("&MESH")]

    def i_cells(line: str) -> int:
        return int(line.split("IJK=")[1].split(",")[0])

    # the core spans 180 m against the far upstream's 300 m, and still has more
    # cells along x -- that is what "finer" means here
    assert i_cells(mesh_lines[1]) > i_cells(mesh_lines[0])


def test_mesh_spans_are_exact_multiples_of_their_own_dx():
    # misaligned interfaces are the classic multi-mesh FDS bug
    core_span = deck.CORE_M[1] - deck.CORE_M[0]
    up_span = deck.CORE_M[0] - deck.WINDOW_M[0]
    down_span = deck.WINDOW_M[1] - deck.CORE_M[1]
    coarse = deck.FINE_DX_M * deck.COARSE_RATIO
    assert core_span % deck.FINE_DX_M == 0
    assert up_span % coarse == 0
    assert down_span % coarse == 0


def test_the_portals_supply_upstream_and_open_downstream():
    text = deck.generate(Design.load(BASELINE))
    assert "MB='XMIN'" in text and "SURF_ID='SUPPLY'" in text
    assert "MB='XMAX'" in text and "SURF_ID='OPEN'" in text
    # inflow is a NEGATIVE velocity on XMIN
    assert "VEL=-" in text


def test_a_bored_tunnel_is_stair_stepped_and_a_test_rig_is_a_box():
    bored = deck.generate(Design.load(BASELINE))
    boxed = deck.generate(Design.load(TEST_RIG))
    # the circular bore needs many OBST rows to approximate the arc;
    # the rectangular rig needs only its walls
    assert bored.count("&OBST") > boxed.count("&OBST")
```

- [ ] **Step 3: Run it to make sure it fails**

Run: `uv run pytest tests/test_fds_deck.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'solit2.engines.fds'`.

- [ ] **Step 4: Create the package marker**

Create `solit2/engines/fds/__init__.py` as an empty file (matches `solit2/engines/reduced/__init__.py`).

- [ ] **Step 5: Write the deck structure**

Create `solit2/engines/fds/deck.py`:

```python
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
```

`_tunnel` takes the FINE dx: the stair-stepped bore is built once at the finest step so the wall is the same solid in every mesh. An `&OBST` snaps to whichever mesh's cells it falls in, so a single fine-stepped ring is correct in the coarse meshes too.

- [ ] **Step 6: Run the tests**

Run: `uv run pytest tests/test_fds_deck.py -q`
Expected: PASS (6 tests).

- [ ] **Step 7: Lint and commit**

```bash
uv run ruff check solit2/ tests/
git add .gitignore solit2/engines/fds/ tests/test_fds_deck.py
git commit -m "feat(fds): deck structure -- mesh, tunnel envelope and portals"
```

---

## Task 3: Deck instrumentation — fire, nozzles, detection, stations, output

**Files:**
- Modify: `solit2/engines/fds/deck.py`
- Create: `tests/fixtures/fds/og-dbr-rev0.fds`, `tests/fixtures/fds/solit2-test-protocol.fds` (golden files)
- Test: `tests/test_fds_deck.py` (extend)

**Interfaces:**
- Consumes: `criteria.STATIONS: dict[str, float]`, `criteria.INSTRUMENTS: dict[str, Instruments]`, `criteria.thermocouple_heights_m(count, crown_height_m) -> tuple[float, ...]`, `criteria.BREATHING_HEIGHT_M = 1.8`, `criteria.HEAT_FLUX_HEIGHT_M = 1.5`, `criteria.VISIBILITY_HEIGHT_M = 1.5`; `geometry.nozzle_positions(design, geom, fire_x_m) -> tuple[NozzlePosition, ...]` (fields `x_m`, `y_m`, `z_m`, `row`, `tilt_deg`); `design.nozzles.flow_per_head_lpm`.
- Produces: `deck.generate` emitting the complete deck. `deck.CEILING_TC_SPACING_M = 5.0`, `deck.TARGET_GAUGE_ID = "TARGET_FLUX"`, `deck.CEILING_TC_PREFIX = "CEIL"` — Task 5's reader reads devices by exactly these names.

**Two devices the physical Table 5 does not list, which the criteria nonetheless need:**
1. A heat-flux gauge at the target (`STATIONS["Target"]`). `criteria._target_ignited` reads `StepRecord.target_flux_kwm2`; Annex 7 §7.2.1 is judged by *observing* ignition in a real test, which is why Table 5 puts no gauge there — a simulation has to measure it.
2. A line of ceiling thermocouples every `CEILING_TC_SPACING_M` along the window. `structure_exposure_length_m` is "how many metres of ceiling exceeded the threshold", which needs a spatial profile, not station points.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_fds_deck.py`:

```python
def test_every_annex_7_station_gets_its_thermocouple_tree():
    from solit2.engines.reduced.criteria import INSTRUMENTS, STATIONS
    text = deck.generate(Design.load(BASELINE))
    for name, x_m in STATIONS.items():
        if not (deck.WINDOW_M[0] <= x_m <= deck.WINDOW_M[1]):
            continue
        for rung in range(INSTRUMENTS[name].thermocouples):
            assert f"ID='{name}_TC{rung}'" in text


def test_only_the_stations_table_5_instruments_get_a_flux_gauge():
    from solit2.engines.reduced.criteria import INSTRUMENTS, STATIONS
    text = deck.generate(Design.load(BASELINE))
    for name, x_m in STATIONS.items():
        if not (deck.WINDOW_M[0] <= x_m <= deck.WINDOW_M[1]):
            continue
        present = f"ID='{name}_HF'" in text
        assert present == INSTRUMENTS[name].heat_flux, name


def test_the_target_carries_its_own_flux_gauge():
    # Table 5 lists no gauge at the target -- a real test observes ignition.
    # A simulation has to measure it, so the deck adds one.
    assert f"ID='{deck.TARGET_GAUGE_ID}'" in deck.generate(Design.load(BASELINE))


def test_a_ceiling_thermocouple_line_spans_the_core():
    # structure exposure is a near-fire quantity; the far meshes exist only so
    # the three far stations are measured, not to resolve a hot ceiling
    text = deck.generate(Design.load(BASELINE))
    assert f"ID='{deck.CEILING_TC_PREFIX}0'" in text
    span = deck.CORE_M[1] - deck.CORE_M[0]
    expected = int(span / deck.CEILING_TC_SPACING_M)
    assert text.count(f"ID='{deck.CEILING_TC_PREFIX}") == expected


def test_one_devc_per_head_and_exactly_one_particle_class():
    design = Design.load(BASELINE)
    text = deck.generate(design)
    assert text.count("PROP_ID='NOZ_FINE'") == design.active_heads
    # single-mode: one PART, one PROP, for the whole deck
    assert text.count("&PART ID=") == 1
    assert text.count("&PROP ID=") == 1
    assert "NOZ_COARSE" not in text


def test_the_nozzle_flow_rate_is_k_root_p():
    design = Design.load(BASELINE)
    text = deck.generate(design)
    assert f"FLOW_RATE={design.nozzles.flow_per_head_lpm:.2f}" in text


def test_detection_drives_activation_through_a_time_delay_control():
    design = Design.load(BASELINE)
    text = deck.generate(design)
    assert f"SETPOINT={design.detection.threshold_c:.1f}" in text
    assert "FUNCTION_TYPE='TIME_DELAY'" in text
    assert f"DELAY={design.zones.activation_delay_s:.1f}" in text
    assert "&CTRL ID='ACT'" in text


def test_the_fire_ramps_to_the_design_hrr():
    design = Design.load(BASELINE)
    text = deck.generate(design)
    assert "&SURF ID='FIRE'" in text
    assert "RAMP_Q='FIRE_RAMP'" in text
    assert "E_COEFFICIENT" in text


def test_the_deck_matches_its_golden_file():
    from pathlib import Path
    golden = Path("tests/fixtures/fds/og-dbr-rev0.fds")
    assert deck.generate(Design.load(BASELINE)) == golden.read_text()


def test_the_test_rig_deck_matches_its_golden_file():
    from pathlib import Path
    golden = Path("tests/fixtures/fds/solit2-test-protocol.fds")
    assert deck.generate(Design.load(TEST_RIG)) == golden.read_text()
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `uv run pytest tests/test_fds_deck.py -q`
Expected: FAIL — `AttributeError: module 'solit2.engines.fds.deck' has no attribute 'TARGET_GAUGE_ID'`.

- [ ] **Step 3: Add the instrumentation blocks**

In `solit2/engines/fds/deck.py`, add these constants below `COARSE_RATIO`:

```python
CEILING_TC_SPACING_M = 5.0
CEILING_TC_PREFIX = "CEIL"
TARGET_GAUGE_ID = "TARGET_FLUX"
CEILING_OFFSET_M = 0.15      # below the crown, matching Tier 1's ceiling definition
DEVC_DT_S = 1.0
```

Add these functions, and extend `generate` to include them:

```python
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
                f"QUANTITY='VOLUME FRACTION', SPEC_ID='CARBON MONOXIDE' /",
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
```

Then update `generate`:

```python
def generate(design: Design, fine_dx_m: float = FINE_DX_M) -> str:
    geom = section_geometry(design)
    blocks = (_head(design) + _time(design) + _meshes(geom, fine_dx_m)
              + _tunnel(geom, fine_dx_m) + _portals(design) + _fire(design)
              + _nozzles(design, geom) + _detection(design)
              + _stations(design, geom) + _output() + ["&TAIL /"])
    return "\n".join(blocks)
```

- [ ] **Step 4: Run the non-golden tests**

Run: `uv run pytest tests/test_fds_deck.py -q -k "not golden"`
Expected: PASS — everything except the two golden-file tests.

- [ ] **Step 5: Write the golden files**

```bash
mkdir -p tests/fixtures/fds
uv run python -c "
from solit2.engines.fds import deck
from solit2.schema.design import Design
from pathlib import Path
for src, out in [('designs/og-dbr-rev0.json', 'og-dbr-rev0'),
                 ('examples/designs/solit2-test-protocol.json', 'solit2-test-protocol')]:
    Path(f'tests/fixtures/fds/{out}.fds').write_text(deck.generate(Design.load(src)))
"
```

Then READ both generated files. This is the review gate on the deck itself: check that the `&MESH` extents enclose the tunnel, the `&OBST` ring narrows toward the crown, nozzle `XYZ` values sit at the mounting height, and no `NOZ_COARSE` appears anywhere. A golden file committed without being read is a snapshot of a bug.

- [ ] **Step 6: Run the full file**

Run: `uv run pytest tests/test_fds_deck.py -q`
Expected: PASS (16 tests).

- [ ] **Step 7: Verify the fixtures are actually committable**

Run: `git status --short tests/fixtures/fds/`
Expected: both `.fds` files show as untracked (`??`), NOT absent. If they do not appear, the `.gitignore` negation from Task 2 Step 1 did not take.

- [ ] **Step 8: Lint and commit**

```bash
uv run ruff check solit2/ tests/
git add solit2/engines/fds/deck.py tests/test_fds_deck.py tests/fixtures/fds/
git commit -m "feat(fds): deck instrumentation -- fire, nozzles, detection and Table 5 stations"
```

---

## Task 4: Runner — pre-flight, launch, status

**Files:**
- Create: `solit2/engines/fds/runner.py`
- Test: `tests/test_fds_runner.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (it takes a deck path, not a `Design`).
- Produces: `runner.preflight() -> list[str]` (empty = ready), `runner.run(deck_path: Path, out_dir: Path) -> str` (returns the run id), `runner.status(run_dir: Path) -> dict` with keys `state` (`"running"|"done"|"failed"`) and `progress` (float 0-1), `runner.MIN_FREE_BYTES`, `runner.REMOTE_ENV = "SOLIT2_FDS_HOST"`, `runner.BIN_ENV = "SOLIT2_FDS_BIN"`. Tasks 6 and 7 call all three.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_fds_runner.py`:

```python
import shutil
from pathlib import Path

import pytest

from solit2.engines.fds import runner


@pytest.fixture
def ready(monkeypatch, tmp_path):
    """An environment where every pre-flight check passes."""
    monkeypatch.delenv(runner.REMOTE_ENV, raising=False)
    monkeypatch.delenv(runner.BIN_ENV, raising=False)
    monkeypatch.setattr(shutil, "which", lambda name: f"/usr/local/bin/{name}")
    monkeypatch.setattr(shutil, "disk_usage",
                        lambda p: shutil._ntuple_diskusage(0, 0, runner.MIN_FREE_BYTES * 2))
    return tmp_path


def test_preflight_passes_when_everything_is_present(ready):
    assert runner.preflight() == []


def test_preflight_reports_a_missing_fds_binary(ready, monkeypatch):
    monkeypatch.setattr(shutil, "which", lambda name: None if name == "fds" else "/usr/bin/x")
    problems = runner.preflight()
    assert any("fds" in p for p in problems)


def test_an_explicit_binary_path_satisfies_the_binary_check(ready, monkeypatch, tmp_path):
    monkeypatch.setattr(shutil, "which", lambda name: None if name == "fds" else "/usr/bin/x")
    binary = tmp_path / "fds"
    binary.write_text("#!/bin/sh\n")
    monkeypatch.setenv(runner.BIN_ENV, str(binary))
    assert runner.preflight() == []


def test_preflight_reports_missing_mpiexec(ready, monkeypatch):
    monkeypatch.setattr(shutil, "which",
                        lambda name: None if name == "mpiexec" else "/usr/local/bin/fds")
    assert any("mpiexec" in p for p in runner.preflight())


def test_preflight_reports_insufficient_disk(ready, monkeypatch):
    monkeypatch.setattr(shutil, "disk_usage",
                        lambda p: shutil._ntuple_diskusage(0, 0, 1024))
    assert any("disk" in p.lower() for p in runner.preflight())


def test_a_remote_host_is_reported_as_not_implemented(ready, monkeypatch):
    monkeypatch.setenv(runner.REMOTE_ENV, "someone@hpc.example")
    problems = runner.preflight()
    assert len(problems) == 1
    assert "remote" in problems[0].lower()


def test_status_reports_failed_when_there_is_no_log(tmp_path):
    assert runner.status(tmp_path)["state"] == "failed"


def test_status_reports_progress_from_the_fds_log(tmp_path):
    (tmp_path / "run.out").write_text(
        "Time Step       100   March 15, 2026  10:00:00\n"
        "Total Time:        250.000 s\n")
    (tmp_path / "deck.fds").write_text("&TIME T_END=1000.0 /\n")
    state = runner.status(tmp_path)
    assert state["state"] == "running"
    assert state["progress"] == pytest.approx(0.25)


def test_status_reports_done_when_fds_says_it_completed(tmp_path):
    (tmp_path / "run.out").write_text("Total Time:      1000.000 s\nSTOP: FDS completed successfully\n")
    (tmp_path / "deck.fds").write_text("&TIME T_END=1000.0 /\n")
    state = runner.status(tmp_path)
    assert state["state"] == "done"
    assert state["progress"] == 1.0
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `uv run pytest tests/test_fds_runner.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'solit2.engines.fds.runner'`.

- [ ] **Step 3: Write the runner**

Create `solit2/engines/fds/runner.py`:

```python
"""Pre-flight, launch and status for an FDS run.

Every check here is a filesystem or environment lookup, so the whole module is
testable by monkeypatching `shutil` and the environment -- which is the only way
it CAN be tested, since no FDS install exists yet.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
from pathlib import Path

BIN_ENV = "SOLIT2_FDS_BIN"
REMOTE_ENV = "SOLIT2_FDS_HOST"
MIN_FREE_BYTES = 10 * 1024**3          # parent spec: 10 GB floor
LOG_NAME = "run.out"
_TOTAL_TIME = re.compile(r"Total Time:\s+([\d.]+)\s*s")
_T_END = re.compile(r"T_END\s*=\s*([\d.]+)")
_DONE = "STOP: FDS completed successfully"


def _binary() -> str | None:
    explicit = os.environ.get(BIN_ENV)
    if explicit and Path(explicit).exists():
        return explicit
    return shutil.which("fds")


def preflight() -> list[str]:
    """Blocking problems, in the order a user should fix them. Empty = ready."""
    if os.environ.get(REMOTE_ENV):
        # Deliberate: guessing at SSH-vs-queue semantics with no host to test
        # against would be building against an imagined system.
        return [f"remote execution via {REMOTE_ENV} is not implemented; "
                f"unset it to run locally"]
    problems = []
    if _binary() is None:
        problems.append(f"the fds binary is not on PATH and {BIN_ENV} is not set")
    if shutil.which("mpiexec") is None:
        problems.append("mpiexec is not on PATH (FDS runs the mesh set under MPI)")
    if shutil.disk_usage(Path.cwd()).free < MIN_FREE_BYTES:
        problems.append(f"less than {MIN_FREE_BYTES // 1024**3} GB of free disk")
    return problems


def run(deck_path: Path, out_dir: Path) -> str:
    """Launch FDS detached and return immediately.

    A run is hours long; the Verify view polls `status()` rather than blocking
    on it, and the CLI does its own waiting.
    """
    problems = preflight()
    if problems:
        raise RuntimeError("; ".join(problems))
    out_dir.mkdir(parents=True, exist_ok=True)
    local_deck = out_dir / "deck.fds"
    if Path(deck_path).resolve() != local_deck.resolve():
        shutil.copy(deck_path, local_deck)
    with (out_dir / LOG_NAME).open("w") as log:
        subprocess.Popen([_binary(), local_deck.name], cwd=out_dir,
                         stdout=log, stderr=subprocess.STDOUT,
                         start_new_session=True)
    return out_dir.name


def status(run_dir: Path) -> dict:
    """Progress from FDS's own log, against the deck's T_END."""
    log = Path(run_dir) / LOG_NAME
    deck = Path(run_dir) / "deck.fds"
    if not log.exists():
        return {"state": "failed", "progress": 0.0,
                "detail": f"no {LOG_NAME} in {run_dir}"}
    text = log.read_text()
    if _DONE in text:
        return {"state": "done", "progress": 1.0, "detail": ""}
    elapsed = _TOTAL_TIME.findall(text)
    end = _T_END.search(deck.read_text()) if deck.exists() else None
    if not elapsed or end is None:
        return {"state": "failed", "progress": 0.0,
                "detail": "the log carries no simulated time"}
    progress = min(float(elapsed[-1]) / float(end.group(1)), 1.0)
    return {"state": "running", "progress": progress, "detail": ""}
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_fds_runner.py -q`
Expected: PASS (9 tests).

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check solit2/ tests/
git add solit2/engines/fds/runner.py tests/test_fds_runner.py
git commit -m "feat(fds): runner -- pre-flight checks, detached launch and status"
```

---

## Task 5: Reader — FDS output to `Result`

**Files:**
- Create: `solit2/engines/fds/reader.py`, `tests/fixtures/fds/sample_devc.csv`, `tests/fixtures/fds/sample_hrr.csv`
- Test: `tests/test_fds_reader.py`

**Interfaces:**
- Consumes: `deck.TARGET_GAUGE_ID`, `deck.CEILING_TC_PREFIX`, `deck.CEILING_TC_SPACING_M`; `criteria.STATIONS`, `criteria.INSTRUMENTS`, `criteria.evaluate(trace, hyd, cost, design)`, `criteria.thermocouple_heights_m`, `criteria.BREATHING_HEIGHT_M`; `state.RunTrace/StepRecord/StationSample/MistEffect`; `geometry.section_geometry`; `hydraulics.size_system(design, geom) -> HydraulicsResult`; `cost.cost_index(design, hyd) -> CostResult`; `score.compute(criteria, hyd, cost, trace, peak_lining_c, density_limit_mm_min) -> Score`; `constraints.evaluate(hyd, design)`.
- Produces: `reader.read(run_dir: Path, design: Design) -> Result`, `reader.ENGINE = "fds"`, `reader.ENGINE_VERSION = "fds-6.11.1"`.

FDS writes `<CHID>_devc.csv` with two header rows (units, then device IDs) and `<CHID>_hrr.csv` likewise. The reader matches columns by the device IDs Task 3 emitted.

Quantities FDS does not produce, and what to do about each — this is the whole design of this module:

| `StepRecord` field | Source |
|---|---|
| `hrr_mw` | `_hrr.csv` `HRR` column, kW → MW |
| `hrr_free_mw` | **not measurable** — FDS ran the suppressed fire. Set equal to `hrr_mw`; no criterion reads it, and inventing a counterfactual free-burn curve would be a Tier 1 number wearing a Tier 2 label |
| `ceiling_temp_c` | max over the `CEIL*` line at that timestep |
| `lining_temp_c` | the `CEIL*` device nearest the fire (Tier 1's own definition: ceiling gas above the fire) |
| `pipe_temp_c` | **not measured** — no pipe in the deck. `0.0` is wrong, but the field is non-optional and only `_peaks` reads it; carry the ambient temperature, which is what an unheated water-filled pipe reads |
| `target_flux_kwm2` | the `TARGET_FLUX` gauge |
| `target_exposure_s` | `sim.target_exposure_s(previous_s, target_flux_kwm2, dt_s)` — the existing Tier 1 accumulator (threshold `criteria.WOOD_PILOTED_IGNITION_KWM2 = 12.5`); do not reimplement the reset rule |
| `structure_exposure_length_m` | count of `CEIL*` devices above `design.ahj.structure_temp_threshold_c`, × `CEILING_TC_SPACING_M` |
| `u_eff_ms`, `u_critical_ms`, `backlayer_m` | `u_eff` from a station velocity device; the other two are Tier 1 correlation outputs with no FDS equivalent — carry `0.0` and say so in a comment. No criterion reads them |
| `water_lpm` | deterministic from the design: `design.flow_lpm` once `t >= activation`, else `0.0` |
| `mist` | `MistEffect.none()` — every field on it is a reduced-order construct FDS does not compute |

- [ ] **Step 1: Write the fixture**

Create `tests/fixtures/fds/sample_hrr.csv` exactly — two header rows, then three timesteps:

```
s,kW,kW,kW
Time,HRR,Q_RADI,Q_CONV
0.0,0.0,0.0,0.0
1.0,15000.0,-5250.0,9750.0
2.0,22000.0,-7700.0,14300.0
```

Generate `sample_devc.csv` from the golden deck, so its device IDs cannot drift from what `deck.py` actually writes. Save this as `tests/fixtures/fds/make_fixture.py` and run it — keeping the generator in the repo means a future deck change can regenerate the fixture instead of someone hand-patching 60 columns:

```python
"""Regenerate sample_devc.csv from the committed golden deck.

Run: uv run python tests/fixtures/fds/make_fixture.py
The values are deliberately simple -- ambient, then rising -- because this
fixture exists to prove parsing and assembly, not to be a realistic fire.
"""
import re
from pathlib import Path

HERE = Path(__file__).parent
AMBIENT_C = 33.0

UNITS = {"_TC": "C", "_HF": "kW/m2", "_VIS": "m", "_CO": "ppm",
         "_FED": "1", "_U": "m/s", "CEIL": "C", "TARGET_FLUX": "kW/m2"}
# (t=0, t=1, t=2) per quantity: ambient, then a developing fire
SERIES = {"C": (AMBIENT_C, 120.0, 260.0), "kW/m2": (0.0, 3.5, 9.0),
          "m": (30.0, 18.0, 7.0), "ppm": (0.0, 40.0, 150.0),
          "1": (0.0, 0.01, 0.04), "m/s": (4.5, 4.4, 4.2)}


def unit_of(device: str) -> str:
    for marker, unit in UNITS.items():
        if marker in device:
            return unit
    raise ValueError(f"no unit rule for device {device!r}")


def main() -> None:
    deck_text = (HERE / "og-dbr-rev0.fds").read_text()
    ids = [d for d in re.findall(r"&DEVC ID='([^']+)'", deck_text)
           if not d.startswith(("NOZ", "LHD"))]
    units = [unit_of(d) for d in ids]
    rows = [[SERIES[u][step] for u in units] for step in range(3)]
    lines = ["s," + ",".join(units), "Time," + ",".join(ids)]
    lines += [f"{float(step)}," + ",".join(f"{v:.3f}" for v in row)
              for step, row in enumerate(rows)]
    (HERE / "sample_devc.csv").write_text("\n".join(lines) + "\n")
    print(f"wrote {len(ids)} device columns")


if __name__ == "__main__":
    main()
```

Run it: `uv run python tests/fixtures/fds/make_fixture.py`. It must print a device count > 50. If it raises `no unit rule for device`, `deck.py` emitted a device whose ID does not match any known suffix — fix the ID in `deck.py` rather than loosening the rule here, since the reader matches on those same suffixes.

- [ ] **Step 2: Write the failing tests**

Create `tests/test_fds_reader.py`:

```python
import shutil
from pathlib import Path

import pytest

from solit2.engines.fds import reader
from solit2.schema.design import Design

BASELINE = "designs/og-dbr-rev0.json"
FIXTURES = Path("tests/fixtures/fds")


@pytest.fixture
def run_dir(tmp_path):
    """A finished run directory, named the way `deck.generate` names its CHID."""
    from solit2.engines.reduced.envelope import _design_sha
    chid = _design_sha(Design.load(BASELINE))
    shutil.copy(FIXTURES / "sample_devc.csv", tmp_path / f"{chid}_devc.csv")
    shutil.copy(FIXTURES / "sample_hrr.csv", tmp_path / f"{chid}_hrr.csv")
    return tmp_path


def test_the_reader_fills_the_same_result_contract_tier_1_does(run_dir):
    result = reader.read(run_dir, Design.load(BASELINE))
    assert result.meta["engine"] == "fds"
    assert result.meta["design_name"] == "og-dbr-rev0"
    assert set(result.criteria) >= {"target_ignited", "max_air_temp_c"}
    assert "hrr_mw" in result.peaks
    assert "total" in result.score


def test_the_hrr_peak_comes_from_the_hrr_csv_in_megawatts(run_dir):
    result = reader.read(run_dir, Design.load(BASELINE))
    assert result.peaks["hrr_mw"] == pytest.approx(22.0)


def test_a_missing_device_column_is_fatal(run_dir):
    from solit2.engines.reduced.envelope import _design_sha
    chid = _design_sha(Design.load(BASELINE))
    devc = run_dir / f"{chid}_devc.csv"
    lines = devc.read_text().splitlines()
    # drop the target gauge column entirely
    header = lines[1].split(",")
    drop = header.index("TARGET_FLUX")
    devc.write_text("\n".join(
        ",".join(p for i, p in enumerate(ln.split(",")) if i != drop) for ln in lines))
    with pytest.raises(KeyError, match="TARGET_FLUX"):
        reader.read(run_dir, Design.load(BASELINE))


def test_mist_is_reported_empty_rather_than_zero(run_dir):
    # every MistEffect field is a reduced-order construct; FDS computes none of
    # them, and a zero would read as a measurement
    result = reader.read(run_dir, Design.load(BASELINE))
    assert result.mist == {}


def test_the_result_round_trips_through_json(run_dir):
    from solit2.schema.result import Result
    result = reader.read(run_dir, Design.load(BASELINE))
    assert Result.model_validate_json(result.model_dump_json()) == result
```

- [ ] **Step 3: Run them to make sure they fail**

Run: `uv run pytest tests/test_fds_reader.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'solit2.engines.fds.reader'`.

- [ ] **Step 4: Write the reader**

Create `solit2/engines/fds/reader.py`:

```python
"""FDS device output -> the same `Result` Tier 1 produces.

The point of this module is that it does NOT re-score anything. It rebuilds the
frozen dataclasses Tier 1's own engine produces (`RunTrace` of `StepRecord` of
`StationSample`) out of what FDS measured, then hands them to Tier 1's
`criteria.evaluate` untouched -- so an FDS result is judged by identical Annex 7
logic and is interchangeable with a Tier 1 result everywhere downstream.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from solit2.engines.fds import deck as deck_mod
from solit2.engines.reduced.constraints import evaluate as evaluate_constraints
from solit2.engines.reduced.cost import cost_index
from solit2.engines.reduced.criteria import (BREATHING_HEIGHT_M, INSTRUMENTS, STATIONS,
                                             evaluate, thermocouple_heights_m)
from solit2.engines.reduced.envelope import _design_sha
from solit2.engines.reduced.geometry import section_geometry
from solit2.engines.reduced.hydraulics import size_system
from solit2.engines.reduced.score import compute as compute_score
from solit2.engines.reduced.sim import target_exposure_s
from solit2.engines.reduced.state import MistEffect, RunTrace, StationSample, StepRecord
from solit2.schema.design import Design
from solit2.schema.result import Result

ENGINE = "fds"
ENGINE_VERSION = "fds-6.11.1"


def _read_csv(path: Path) -> tuple[list[str], list[list[float]]]:
    """FDS CSV: row 1 is units, row 2 is device IDs, the rest is data."""
    lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
    ids = [c.strip() for c in lines[1].split(",")]
    rows = [[float(c) for c in ln.split(",")] for ln in lines[2:]]
    return ids, rows


def _at(ids: list[str], row: list[float], device: str) -> float:
    """A device the deck promised and the output does not carry is fatal.

    The parent spec makes a missing device column fatal on purpose: a default
    here would let a deck/reader mismatch through as a plausible-looking result.
    """
    if device not in ids:
        raise KeyError(device)
    return row[ids.index(device)]


def _station(ids: list[str], row: list[float], name: str,
             heights: tuple[float, ...]) -> StationSample:
    """One Table 5 location's readings. Absent where Table 5 has no sensor."""
    kit = INSTRUMENTS[name]
    temps = tuple(_at(ids, row, f"{name}_TC{i}") for i in range(kit.thermocouples))
    breathing = min(range(len(heights)), key=lambda i: abs(heights[i] - BREATHING_HEIGHT_M))
    return StationSample(
        temp_c=temps[breathing],
        flux_kwm2=_at(ids, row, f"{name}_HF") if kit.heat_flux else None,
        visibility_m=_at(ids, row, f"{name}_VIS") if kit.visibility else None,
        # FDS's FED device is the asphyxiant dose; the thermal dose has no
        # single FDS device, so it stays absent rather than being invented.
        fed_tox=_at(ids, row, f"{name}_FED") if kit.toxic_gas else None,
        fed_heat=None,
        co_ppm=_at(ids, row, f"{name}_CO") if kit.toxic_gas else None,
        air_velocity_ms=_at(ids, row, f"{name}_U") if kit.air_velocity else None,
        temps_c=temps,
        heights_m=heights,
    )


def _in_window(x_m: float) -> bool:
    return deck_mod.WINDOW_M[0] <= x_m <= deck_mod.WINDOW_M[1]


def _ceiling_ids(ids: list[str]) -> list[str]:
    return [i for i in ids if i.startswith(deck_mod.CEILING_TC_PREFIX)]


def read(run_dir: Path, design: Design) -> Result:
    run_dir = Path(run_dir)
    chid = _design_sha(design)
    devc_ids, devc_rows = _read_csv(run_dir / f"{chid}_devc.csv")
    _, hrr_rows = _read_csv(run_dir / f"{chid}_hrr.csv")

    geom = section_geometry(design)
    modelled = [n for n, x in STATIONS.items() if _in_window(x)]
    heights = {n: thermocouple_heights_m(INSTRUMENTS[n].thermocouples, geom.crown_height_m)
               for n in modelled}
    ceiling = _ceiling_ids(devc_ids)
    threshold_c = design.ahj.structure_temp_threshold_c
    activation_s = design.zones.activation_delay_s
    full_pressure_s = activation_s + design.zones.pump_ramp_s

    steps: list[StepRecord] = []
    exposure_s = 0.0
    for i, row in enumerate(devc_rows):
        t_s = row[0]
        dt_s = t_s - devc_rows[i - 1][0] if i else 0.0
        hrr_mw = (hrr_rows[i][1] if i < len(hrr_rows) else hrr_rows[-1][1]) / 1000.0
        ceiling_temps = [_at(devc_ids, row, c) for c in ceiling]
        target_flux = _at(devc_ids, row, deck_mod.TARGET_GAUGE_ID)
        exposure_s = target_exposure_s(exposure_s, target_flux, dt_s)
        hot = sum(1 for t in ceiling_temps if t > threshold_c)
        steps.append(StepRecord(
            t_s=t_s,
            hrr_mw=hrr_mw,
            # FDS ran the SUPPRESSED fire. There is no free-burn curve to read,
            # and deriving one would be a Tier 1 number wearing a Tier 2 label.
            hrr_free_mw=hrr_mw,
            ceiling_temp_c=max(ceiling_temps),
            # Tier 1's own definition: the ceiling gas above the fire.
            lining_temp_c=ceiling_temps[len(ceiling_temps) // 2],
            # No pipe in the deck. A water-filled pipe that nothing has heated
            # reads ambient; 0.0 would be a colder-than-air measurement.
            pipe_temp_c=design.tunnel.ambient_temp_c,
            target_flux_kwm2=target_flux,
            u_eff_ms=_at(devc_ids, row, "D45_U"),
            # Tier 1 correlation outputs with no FDS equivalent. No criterion
            # reads either, and FDS resolves backlayering in the slice files.
            u_critical_ms=0.0,
            backlayer_m=0.0,
            water_lpm=design.flow_lpm if t_s >= full_pressure_s else 0.0,
            pools_remaining=design.fire.pools.count if design.fire.pools else 0,
            # Every MistEffect field is a reduced-order construct: efficiency,
            # coverage fraction, cooling fraction, transmissivity. FDS computes
            # droplets, not these.
            mist=MistEffect.none(),
            stations={n: _station(devc_ids, row, n, heights[n]) for n in modelled},
            target_exposure_s=exposure_s,
            structure_exposure_length_m=hot * deck_mod.CEILING_TC_SPACING_M,
        ))

    velocity = design.ventilation.velocity_ms or max(design.ventilation.velocity_range_ms)
    trace = RunTrace(steps=tuple(steps),
                     events={"t_activation_s": activation_s,
                             "t_full_pressure_s": full_pressure_s},
                     section=design.tunnel.section, velocity_ms=velocity)

    hyd = size_system(design, geom)
    cost = cost_index(design, hyd)
    criteria = evaluate(trace, hyd, cost, design)
    peak_lining = max(s.lining_temp_c for s in trace.steps)
    scored = compute_score(criteria, hyd, cost, trace, peak_lining,
                           design.constraints.max_application_density_mm_min)
    skipped = sorted(set(STATIONS) - set(modelled))

    return Result(
        # No calibration_* keys: Tier 1 carries them because it is fitted to the
        # anchors. FDS is not, and claiming that provenance would be a lie.
        meta={"design_name": design.meta.name, "design_sha": chid,
              "engine": ENGINE, "engine_version": ENGINE_VERSION,
              "timestamp": datetime.now(timezone.utc).isoformat(),
              "window_m": list(deck_mod.WINDOW_M)},
        envelope=[{"section": trace.section, "velocity_ms": trace.velocity_ms}],
        worst_case={"section": trace.section, "velocity_ms": trace.velocity_ms},
        events=trace.events,
        criteria=criteria,
        criteria_cases={},
        constraints=evaluate_constraints(hyd, design),
        peaks={"hrr_mw": max(s.hrr_mw for s in steps),
               "hrr_free_burn_mw": max(s.hrr_free_mw for s in steps),
               "ceiling_temp_c": max(s.ceiling_temp_c for s in steps),
               "lining_temp_c": peak_lining,
               "pipe_surface_temp_c": max(s.pipe_temp_c for s in steps),
               "target_peak_flux_kwm2": max(s.target_flux_kwm2 for s in steps),
               "target_max_exposure_s": max(s.target_exposure_s for s in steps),
               "structure_exposure_length_m": max(s.structure_exposure_length_m
                                                  for s in steps)},
        mist={},
        hydraulics=hyd.__dict__,
        cost=cost.__dict__,
        score={"total": scored.total, "gates_passed": scored.gates_passed,
               "gates_failed": scored.gates_failed, "components": scored.components,
               "penalties": scored.penalties, "criteria_unset": scored.criteria_unset},
        timeseries={"t_s": [s.t_s for s in steps],
                    "hrr_mw": [s.hrr_mw for s in steps],
                    "ceiling_temp_c": [s.ceiling_temp_c for s in steps]},
        warnings=(["hrr_free_mw mirrors hrr_mw -- FDS ran the suppressed fire, "
                   "so no free-burn curve exists to report"]
                  + ([f"stations outside the {deck_mod.WINDOW_M} m deck window were "
                      f"not modelled: {', '.join(skipped)}"] if skipped else [])),
    )
```

Note the two `peaks` keys `envelope._peaks` carries that this one does not: `smoke_layer_temp_d15_c` and `smoke_layer_temp_d100_c`. Add them the same way (`max(s.stations["D15"].temp_c for s in steps)`), but only for stations in `modelled` — D100 sits at the window edge, and reading a station the deck never instrumented would raise `KeyError` at result-assembly time rather than at parse time.

- [ ] **Step 5: Run the tests**

Run: `uv run pytest tests/test_fds_reader.py -q`
Expected: PASS (5 tests).

- [ ] **Step 6: Lint and commit**

```bash
uv run ruff check solit2/ tests/
git add solit2/engines/fds/reader.py tests/test_fds_reader.py tests/fixtures/fds/
git commit -m "feat(fds): reader -- FDS device output into the Tier 1 Result contract"
```

---

## Task 6: CLI — `fds-deck`, `fds-status`, `run --engine fds`

**Files:**
- Modify: `solit2/cli.py`
- Test: `tests/test_cli.py` (extend)

**Interfaces:**
- Consumes: `deck.generate(design, dx_m)`, `runner.preflight()`, `runner.run(deck_path, out_dir)`, `runner.status(run_dir)`, `reader.read(run_dir, design)`.
- Produces: no new Python interfaces; three CLI surfaces.

Existing patterns to follow exactly: `_fail(message, field, fix, code)` writes `{"error","field","fix"}` to stderr; `EXIT_OK=0`, `EXIT_VALIDATION_MISS=1`, `EXIT_BAD_INPUT=2`, `EXIT_ENGINE=3`; each subcommand is a `_cmd_*` function registered with `sub.add_parser(...).set_defaults(func=...)`. `solit2/cli.py:96-130` is the parser builder.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_cli.py`:

```python
def test_fds_deck_writes_a_namelist(tmp_path):
    out = tmp_path / "case.fds"
    proc = _run(["fds-deck", "designs/og-dbr-rev0.json", "--out", str(out)])
    assert proc.returncode == 0, proc.stderr
    text = out.read_text()
    assert text.startswith("&HEAD")
    assert "&TAIL /" in text


def test_fds_deck_honours_the_dx_override(tmp_path):
    coarse = _run(["fds-deck", "designs/og-dbr-rev0.json", "--dx", "0.9"]).stdout
    fine = _run(["fds-deck", "designs/og-dbr-rev0.json", "--dx", "0.25"]).stdout
    assert coarse != fine


def test_fds_deck_on_a_bad_design_exits_two(tmp_path):
    raw = json.loads(open("designs/og-dbr-rev0.json").read())
    raw["nozzles"]["pressure_bar"] = 12.0
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(raw))
    proc = _run(["fds-deck", str(bad)])
    assert proc.returncode == 2
    assert json.loads(proc.stderr)["fix"]


def test_fds_status_reports_a_missing_run(tmp_path):
    proc = _run(["fds-status", str(tmp_path / "nope")])
    assert proc.returncode == 0, proc.stderr
    assert "failed" in proc.stdout


def test_run_with_engine_fds_refuses_without_a_binary(tmp_path):
    # no FDS on this machine: the pre-flight must say so plainly, not crash
    proc = _run(["run", "designs/og-dbr-rev0.json", "--engine", "fds", "--no-history"])
    assert proc.returncode == 3
    err = json.loads(proc.stderr)
    assert "fds" in err["error"]
    assert err["fix"]
```

- [ ] **Step 2: Run them to make sure they fail**

Run: `uv run pytest tests/test_cli.py -q -k "fds"`
Expected: FAIL — argparse rejects `fds-deck` and exits 2 with usage text, so the JSON parse of stderr fails.

- [ ] **Step 3: Wire the CLI**

In `solit2/cli.py`, add to the imports:

```python
from solit2.engines.fds import deck as fds_deck
from solit2.engines.fds import reader as fds_reader
from solit2.engines.fds import runner as fds_runner
```

Add the command functions:

```python
def _cmd_fds_deck(args: argparse.Namespace) -> int:
    try:
        design = Design.load(args.design)
    except (ValidationError, ValueError, FileNotFoundError, KeyError) as exc:
        return _fail(str(exc), getattr(exc, "field", "design"),
                     "correct the design JSON and try again", EXIT_BAD_INPUT)
    text = fds_deck.generate(design, fine_dx_m=args.dx)
    print(text)
    if args.out:
        try:
            Path(args.out).parent.mkdir(parents=True, exist_ok=True)
            Path(args.out).write_text(text + "\n")
        except OSError as exc:
            return _fail(str(exc), "--out", "choose a writable output path", EXIT_BAD_INPUT)
    return EXIT_OK


def _cmd_fds_status(args: argparse.Namespace) -> int:
    state = fds_runner.status(Path(args.run_dir))
    print(f"{state['state']}  {state['progress'] * 100:.0f}%  {state.get('detail', '')}".rstrip())
    return EXIT_OK
```

Extend `_cmd_run` so `--engine fds` takes the FDS path. Keep the reduced path byte-identical to what it does today:

```python
def _run_fds(design: argparse.Namespace, args: argparse.Namespace):
    """Generate, launch, wait, read. Hours, not seconds -- by design."""
    problems = fds_runner.preflight()
    if problems:
        raise RuntimeError("; ".join(problems))
    out_dir = Path(args.history).parent / _design_sha_for(design)
    out_dir.mkdir(parents=True, exist_ok=True)
    deck_path = out_dir / "deck.fds"
    deck_path.write_text(fds_deck.generate(design))
    fds_runner.run(deck_path, out_dir)
    while fds_runner.status(out_dir)["state"] == "running":
        time.sleep(FDS_POLL_S)
    if fds_runner.status(out_dir)["state"] == "failed":
        raise RuntimeError(f"the FDS run in {out_dir} failed; see {out_dir / 'run.out'}")
    return fds_reader.read(out_dir, design)
```

with `FDS_POLL_S = 30.0` at module level and `_design_sha_for` importing `envelope._design_sha`. In `_cmd_run`, replace the single `envelope.run(design)` call with a branch on `args.engine`, keeping the existing `except (ArithmeticError, RuntimeError, ValueError, KeyError)` handler — a pre-flight failure raises `RuntimeError` and lands there as exit 3, which is what the test expects.

Register the parsers beside the existing ones:

```python
    fdeck = sub.add_parser("fds-deck", help="write the FDS input deck for a design")
    fdeck.add_argument("design")
    fdeck.add_argument("--dx", type=float, default=fds_deck.FINE_DX_M,
                       help="cell size in the fine core mesh; the far meshes "
                            "scale with it")
    fdeck.add_argument("--out")
    fdeck.set_defaults(func=_cmd_fds_deck)

    fstat = sub.add_parser("fds-status", help="progress of an FDS run directory")
    fstat.add_argument("run_dir")
    fstat.set_defaults(func=_cmd_fds_status)
```

and change the existing `run` parser's engine choices:

```python
    run.add_argument("--engine", default="reduced", choices=["reduced", "fds"],
                     help="'fds' generates a deck, runs it and parses the result; "
                          "a Tier 2 run takes hours, not seconds")
```

- [ ] **Step 4: Run the tests**

Run: `uv run pytest tests/test_cli.py -q`
Expected: PASS — the 6 existing tests plus 5 new ones.

- [ ] **Step 5: Lint and commit**

```bash
uv run ruff check solit2/ tests/
git add solit2/cli.py tests/test_cli.py
git commit -m "feat(cli): fds-deck, fds-status and run --engine fds"
```

---

## Task 7: Verify view

**Files:**
- Modify: `app/views/verify.py` (full rewrite), `README.md`
- Test: `tests/test_app_verify_view.py` (rewrite)

**Interfaces:**
- Consumes: `app.state.get_design()`, `app.state.get_result()`; `fds_deck.generate(design)`; `fds_runner.preflight()`, `runner.status(run_dir)`; `solit2.reports.correlation.render(test_result, site_result)`; `solit2.schema.result.Result`.
- Produces: `render() -> None` (the `PAGES["Verify"]` entry, already wired in `app/streamlit_app.py`).

The existing test file asserts the stub's text and must be replaced, not appended to.

- [ ] **Step 1: Rewrite the test**

Replace `tests/test_app_verify_view.py` entirely:

```python
from streamlit.testing.v1 import AppTest


def test_verify_page_shows_preflight_status():
    at = AppTest.from_file("../app/streamlit_app.py")
    at.run()
    at.sidebar.radio[0].set_value("Verify").run()
    assert not at.exception
    # no FDS on a dev machine or in CI: the page must say so, honestly
    body = " ".join(e.value for e in at.markdown) + " ".join(w.value for w in at.warning)
    assert "fds" in body.lower()


def test_verify_page_generates_a_deck_for_the_current_design():
    at = AppTest.from_file("../app/streamlit_app.py")
    at.run()
    at.sidebar.radio[0].set_value("Design").run()
    at.button[0].click().run()          # "Build design"
    at.sidebar.radio[0].set_value("Verify").run()
    # the deck button is the first on this page
    at.button[0].click().run()
    assert not at.exception
    assert any("&HEAD" in e.value for e in at.code)


def test_verify_page_prompts_for_a_design_when_none_is_built():
    at = AppTest.from_file("../app/streamlit_app.py")
    at.run()
    at.sidebar.radio[0].set_value("Verify").run()
    assert any("design" in w.value.lower() for w in at.warning)
```

- [ ] **Step 2: Run it to make sure it fails**

Run: `uv run pytest tests/test_app_verify_view.py -q`
Expected: FAIL — the stub renders `st.info`, not a deck button or pre-flight output.

- [ ] **Step 3: Rewrite the view**

Replace `app/views/verify.py`:

```python
"""The Verify view: Tier 2 (FDS) pre-flight, deck, run and comparison.

Deck generation works on any machine. Running needs an FDS install, which this
page reports on honestly rather than offering a button that cannot work.
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from app import state
from solit2.engines.fds import deck as fds_deck
from solit2.engines.fds import runner as fds_runner
from solit2.reports import correlation
from solit2.schema.result import Result


def _render_preflight() -> list[str]:
    st.subheader("Pre-flight")
    problems = fds_runner.preflight()
    if problems:
        for problem in problems:
            st.warning(problem)
    else:
        st.success("FDS is available -- a Tier 2 run can be started from here.")
    return problems


def _render_deck(design) -> None:
    st.subheader("Deck")
    if st.button("Generate FDS deck"):
        text = fds_deck.generate(design)
        st.code(text[:4000], language="text")
        st.download_button("Download deck (.fds)", text,
                           file_name=f"{design.meta.name}.fds")


def _render_run(design, blocked: list[str]) -> None:
    st.subheader("Run")
    if blocked:
        st.info("A Tier 2 run needs the pre-flight above to pass first.")
        return
    st.caption("A Tier 2 run takes hours. It is launched in the background; "
              "come back to this page for progress.")
    if st.button("Start FDS run", type="primary"):
        out_dir = Path("runs") / design.meta.name
        out_dir.mkdir(parents=True, exist_ok=True)
        deck_path = out_dir / "deck.fds"
        deck_path.write_text(fds_deck.generate(design))
        fds_runner.run(deck_path, out_dir)
        st.success(f"Launched in {out_dir}")
    run_dir = Path("runs") / design.meta.name
    if run_dir.exists():
        status = fds_runner.status(run_dir)
        st.progress(status["progress"], text=f"{status['state']} -- "
                                            f"{status['progress'] * 100:.0f}%")


def _render_comparison() -> None:
    st.subheader("Tier 1 vs Tier 2")
    tier1 = state.get_result()
    if tier1 is None:
        st.info("Run the design on the Run page to get a Tier 1 result to compare against.")
        return
    uploaded = st.file_uploader("Tier 2 result JSON", type="json", key="verify_tier2")
    if uploaded is None:
        return
    try:
        tier2 = Result.model_validate_json(uploaded.getvalue())
    except ValueError as exc:
        st.error(f"Could not read that result: {exc}")
        return
    st.markdown(correlation.render(tier1, tier2))


def render() -> None:
    st.header("Verify")
    design = state.get_design()
    if design is None:
        st.warning("Build a design on the Design page first.")
        return
    problems = _render_preflight()
    _render_deck(design)
    _render_run(design, problems)
    st.divider()
    _render_comparison()
```

- [ ] **Step 4: Run the view tests**

Run: `uv run pytest tests/test_app_verify_view.py -q`
Expected: PASS (3 tests).

- [ ] **Step 5: Update the README**

In `README.md`, the CLI table gains two rows and the app section's Verify description changes from "stub -- FDS/CFD tier is a separate, unstarted plan" to a real description:

```
| `solit2 fds-deck <design.json>` | Write the FDS input deck for a design |
| `solit2 fds-status <run-dir>` | Progress of an FDS run |
```

and in "Running the app", replace the Verify clause with: `Verify (Tier 2 FDS pre-flight, deck generation, run, and a Tier 1 vs Tier 2 comparison)`.

- [ ] **Step 6: Full suite, lint, commit**

```bash
uv run pytest -q
uv run ruff check app/ solit2/ tests/
git add app/views/verify.py tests/test_app_verify_view.py README.md
git commit -m "feat(app): Verify view -- FDS pre-flight, deck, run and Tier 1 vs Tier 2"
```

---

## Notes for the executor

- **The golden files are a review surface, not a snapshot ritual.** Task 3 Step 5 says to read both decks before committing them. If a `&MESH` does not enclose the tunnel or a nozzle sits above the crown, the golden test will happily lock that in forever.
- **`SPRAY_ANGLE` vs `SPRAY_PATTERN_TABLE`:** real FDS accepts both; this plan uses the direct `SPRAY_ANGLE=lower,upper` form, which is what a single uniform cone needs. If FDS 6.11.1 rejects it during a future live run, the fix is a `&TABL` block — see `firemodels/fds` `Verification/Sprinklers_and_Sprays/activate_sprinklers.fds` for that form.
- **No live FDS means the decks are unvalidated by FDS itself.** Every test here proves the deck is what this code intends to write, not that FDS accepts it. The first live run is where that gets tested; expect to fix namelist details then, and treat that as planned work rather than a defect in this plan.

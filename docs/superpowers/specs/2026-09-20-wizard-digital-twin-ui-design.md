# Wizard + Digital-Twin UI — Design

**Date:** 2026-09-20
**Supersedes:** section 10 of `2026-09-15-solit2-simulator-design.md` (front end) and the
Verify/Reports pages built from `2026-09-17-solit2-streamlit-ui.md`.
**Depends on:** `2026-09-18-solit2-fds-tier2-design.md` (deck, runner, reader — unchanged
except the two `&SLCF` lines in §7.3).

## 1. Purpose

Turn the six independent Streamlit pages into a guided, five-step wizard that a
non-specialist can follow end to end without moving files by hand, and make the
simulation *watchable*: a to-scale digital twin of the Annex 7 fire test that plays out in
time, driven by Tier 1 instantly and by Tier 2 CFD when a run exists.

Requirements, from the user:

1. Visually appealing.
2. Easy to understand and use.
3. Visual display of the simulation, including an actual CFD view.
4. No download/upload between steps — state passes automatically.
5. A "digital twin" feel for the fire test.

## 2. Decisions taken in brainstorming

| Question | Decision |
|---|---|
| Wizard shape | Linear stepper at the top; sidebar radio removed. Leaderboard folds into step 2. |
| CFD view | In-page Plotly heatmap parsed from FDS `.sf` slice files, live during the run, plus an "Open in Smokeview" button that launches the desktop app. Smokeview is never embedded or driven headless. |
| Correlation's second run | Auto-built **test-facility twin** of the current design, run in Tier 1 on entry to step 5. No upload. |
| Exports | Allowed only on step 5, as *exports* (reports, JSON). Never as a hand-off to another step. |
| Rendering stack | Plotly only (already a dependency). No new Python or JS dependency. |

## 3. Navigation and state

### 3.1 Stepper

`app/components/stepper.py` renders a row of five step pills at the top of every page and a
Back / Next footer at the bottom.

| # | Label | Reachable when |
|---|---|---|
| 1 | Design | always |
| 2 | Result | a design exists |
| 3 | Fire test | a design exists |
| 4 | CFD verify | a design exists |
| 5 | Reports | a design exists |

- The current step is highlighted; completed steps show a check mark; unreachable steps are
  disabled buttons. Clicking a reachable pill jumps to it.
- Next on step 1 is "Build & continue →" (builds the design, then advances). Next on step 5
  is absent. Back on step 1 is absent.
- The step index lives in session state under one key, read and written only through
  `app/state.py`.

### 3.2 State (`app/state.py`)

Extend the existing typed accessors. Keys and invalidation:

| Key | Type | Set by | Invalidated by |
|---|---|---|---|
| `step` | `int` (1–5) | stepper | never |
| `design` | `Design` | step 1 | — |
| `result` | `Result` (Tier 1, site) | step 2 auto-run | `set_design` |
| `twin_result` | `Result` (Tier 1, test facility) | step 5 auto-run | `set_design` |
| `tier2_result` | `Result` (FDS) | step 4 when the run is `done` | `set_design` |

The Tier 2 run directory is **derived**, never stored: `runs/<design_sha>`, exactly as the
CLI and the deck's CHID already do. The filesystem is the Tier 2 state, so a run launched
from the CLI or survived across an app restart is picked up, not relaunched.

### 3.3 Auto-run rule

Entering a step whose prerequisite is missing computes it on the spot inside a spinner:
step 2 runs `envelope.run(design)`; step 3 runs `sim.run_once(design, worst_section,
worst_velocity)` (already cached with `st.cache_data`); step 5 builds and runs the twin.
Tier 1 takes seconds, so no step ever shows a "run" button for Tier 1. Step 4's FDS run is
the one thing that needs an explicit Start, because it costs hours.

## 4. Steps

### 4.1 Step 1 — Design

The existing form (`app/views/design.py`) restyled: preset pickers, the nine parameters,
and a **summary card** that updates as inputs change: heads per zone, flow per head
(L/min), zone flow (L/min), working pressure (bar), tank volume for `duration_min` — all
from `hydraulics.size_system`. Building a design calls `state.set_design` and advances to
step 2. The "Download design JSON" button moves to step 5.

### 4.2 Step 2 — Result (Tier 1)

Auto-runs. Layout, top to bottom:

1. **Verdict banner**: `PASS` (all hard gates passed) or `FAIL` (any gate failed), score
   `total`, and the count of `criteria_unset` with the words "not judged — no AHJ limit
   set" when it is non-zero. The banner may never read PASS while `gates_failed` is
   non-empty, and must show the unset count whenever it is non-zero (CLAUDE.md: never
   present `gates_passed: true` as approval when `criteria_unset` is non-empty).
2. **Gate chips**: one chip per hard criterion, coloured pass / fail / unset.
3. **Peaks** as metric tiles (existing).
4. **Criteria table** (existing `criteria_table`) with the `status` column styled.
5. **Site constraints** table when present (existing).
6. **Timeseries** (existing chart).
7. **Warnings** (existing).
8. Expander **"Compare with earlier designs"**: `history.leaderboard(top=20)` with the
   current design's row highlighted by `design_sha`, and a "passing only" checkbox.

Every Tier 1 run appends to `runs/history.jsonl` via `history.append` — the CLI default.
Duplicate rows for the same `design_sha` are acceptable and appear as separate rows.

### 4.3 Step 3 — Fire test (digital twin)

See §5 and §6. This step shows the HMI strip, the twin canvas with play/scrub, the event
timeline, and a station strip chart. It is driven by the Tier 1 `RunTrace` of the worst
case (`result.worst_case`), as the Tunnel view already is.

### 4.4 Step 4 — CFD verify (Tier 2)

Top to bottom:

1. **Pre-flight chips**: one chip per `fds_runner.preflight()` problem (red) or a single
   green "FDS ready" chip.
2. **Run control** (only when pre-flight passes and no run is in progress for this sha):
   a duration picker with options `5 min`, `10 min`, `20 min`, `Full (design duration)`,
   default `20 min`; a **Start FDS run** button. Start writes
   `fds_deck.generate(design, t_end_s=minutes*60)` (or `t_end_s=None` for Full) to
   `runs/<sha>/deck.fds` and calls `fds_runner.run`. The picker maps to the existing
   `--minutes` semantics and never edits `zones.duration_min`.
3. **Progress**: inside `st.fragment(run_every="10s")` while `status()["state"] ==
   "running"`: a progress bar, the simulated time reached, and elapsed wall time. The
   fragment stops re-running when the state is `done` or `failed`.
4. **Twin canvas with the CFD layer** (§5.6): tabs **Temperature / Smoke / Mist**, each a
   heatmap inside the tunnel outline, with the station masts overlaid. The heatmap frames
   come from the `.sf` slices present on disk at render time; while running, the fragment
   above triggers a re-read, so the field extends as FDS writes. Caption states the last
   frame time and, while running, "preliminary — run at t = X s of Y s".
5. **Open in Smokeview** button: enabled when a Smokeview binary is found (§7.4) and the
   run directory holds `<chid>.smv`; launches `smokeview <chid>.smv` detached with
   `cwd=runs/<sha>`. Disabled with a caption naming the missing piece otherwise.
6. **Tier 1 vs Tier 2** (only when `done`): `fds_reader.read(run_dir, design)` →
   `state.set_tier2_result`; Tier 2 warnings shown first, then
   `correlation.render(tier1, tier2)`.

A run directory that already exists for this sha (from the CLI or a previous session) is
shown in place; the Start button is hidden while its state is `running` and re-appears,
labelled **Re-run**, when it is `done` or `failed`.

### 4.5 Step 5 — Reports

1. **Test plan**: `test_plan.render(design, result)` as markdown.
2. **Site vs test facility**: builds `twin.test_facility_twin(design)`, runs it in Tier 1
   (spinner, cached in `twin_result`), shows the twin's `meta.notes` (which states the
   mounting rule of §8) as an info box, then `correlation.render(twin_result, result)`.
3. **Tier 1 vs Tier 2**: shown when `tier2_result` exists; otherwise one line: "Run the
   CFD step to add the Tier 2 comparison."
4. **Exports**: download buttons for test plan `.md`, each correlation `.md`, design JSON,
   Tier 1 result JSON, twin result JSON, Tier 2 result JSON when present.

## 5. Digital-twin canvas (`app/components/twin_canvas.py`)

One Plotly figure, longitudinal section (x along the tunnel, z height), built from
**pure layer functions** that each return a list of traces and/or shapes so they can be
unit-tested without a browser:

```python
def tunnel_layer(design: Design, geom: SectionGeometry, window_m: tuple[float, float],
                 step: StepRecord, target_ignited: bool = False) -> Layer
def instrument_layer(design: Design, geom: SectionGeometry, step: StepRecord) -> Layer
def fire_layer(design: Design, step: StepRecord) -> Layer
def mist_layer(design: Design, geom: SectionGeometry, step: StepRecord) -> Layer
def cfd_layer(slice_: Slice, frame_index: int) -> Layer
def frames(design: Design, geom: SectionGeometry, trace: RunTrace, stride_s: float) -> list[go.Frame]
def figure(design: Design, trace: RunTrace, *, cfd: Slice | None = None) -> go.Figure
```

`Layer = tuple[list[go.BaseTraceType], list[dict]]` (traces, layout shapes).

### 5.1 Coordinates and window

x = 0 at the longitudinal middle of the HGV mock-up — Annex 7 §6.3's frame, which the
engine, `STATIONS` and the FDS deck (`FIRE_X_M = 0.0`) all share; the mock-up ends sit at
U5 and D5 and the target at D10.
Default window `(-360.0, 240.0)` — the FDS deck's `WINDOW_M`, so Tier 1 and Tier 2 share
one frame. A range slider on x lets the user zoom to the core. z from carriageway 0 to
`geom.crown_height_m`.

### 5.2 Tunnel layer

- Carriageway line at z=0 and crown line at `geom.crown_height_m` across the window; for
  the `solit2_test` preset the crown is the suspended ceiling (5.2 m).
- Gradient shown as a label only (`tunnel.gradient_pct`), not as a tilted drawing.
- **HGV mock-up**: rectangle x ∈ [−`length_m`/2, +`length_m`/2] (from `fire.footprint`),
  z ∈ [`base_height_m`, `top_height_m`].
- **Target**: rectangle of the same size starting at `fire.target_x_m`, outlined and
  labelled "target — {target_distance_m} m". `tunnel_layer` takes
  `target_ignited: bool`; when True (from `result.criteria["target_ignited"].value`)
  the rectangle is filled fail-red in every frame — ignition is a result-level
  boolean in the engine, not a timed event.
- **Nozzle heads**: `geometry.nozzle_positions(design, geom, fire_x_m=0.0)` gives every
  head's (x, y, z); drawn as small markers at (x, z). Grey when `step.water_lpm == 0`,
  primary-teal when `> 0`.
- **Detection line**: a thin dashed line just under the crown across the active length,
  labelled with `detection.type` and `threshold_c`.
- **Ventilation arrow**: an annotation arrow at the upstream edge, text
  `u = {step.u_eff_ms:.1f} m/s (critical {step.u_critical_ms:.1f})`, coloured fail-red
  when `u_eff_ms < u_critical_ms`.

### 5.3 Instrument layer

One mast per station in `STATIONS` inside the window: a vertical line at `x_m` from 0 to
the crown, thermocouple dots at `step.stations[name].heights_m` coloured by
`temps_c` on the temperature colour scale (§9.3), a station label above the crown. Stations
whose `INSTRUMENTS` kit has `heat_flux`, `visibility`, or `carbon_monoxide > 0` get a
distinct glyph at breathing height (1.8 m) whose hover text shows that reading. Hover text
on every dot: `station · z m · value unit`.

### 5.4 Fire layer

A marker at (0, `top_height_m`) with symbol `triangle-up`, size
proportional to `step.hrr_mw` (linear, 6 px at 0 MW to 60 px at `fire.design_hrr_mw`),
colour on the temperature scale by `step.ceiling_temp_c`. Hover:
`HRR {hrr_mw:.1f} MW (free burn {hrr_free_mw:.1f})`. A translucent **backlayering band**
rectangle from `-step.backlayer_m` to 0 across the upper third of the section when
`backlayer_m > 1.0`.

### 5.5 Mist layer

When `step.water_lpm > 0`: a rectangle over the active length (`section_length_m ×
sections_simultaneous`, centred on the fire's zone as `nozzle_positions` already centres
it) from `mounting.height_above_carriageway_m` down to 0, primary-teal fill with opacity
`0.10 + 0.40 * step.mist.chi_cool` (bounded to [0.1, 0.5]). Hover:
`{water_lpm:.0f} L/min · cooling {chi_cool:.0%} · radiant transmission {tau_mist:.0%}`.

### 5.6 CFD layer

`go.Heatmap(x=slice_.x_m, y=slice_.z_m, z=slice_.frames[frame_index], colorscale=…,
zmin/zmax fixed across frames)`, drawn **beneath** the structure and instrument traces so
the masts stay readable. Colour scales per quantity: `TEMPERATURE` → `Inferno`,
`SOOT DENSITY` → `Greys`, `MPUV` → `Blues`. Colour-bar title = `quantity (unit)` from the
slice header. When a CFD slice is supplied, the frames come from the slice's time base,
not the Tier 1 trace, and the instrument dots are read from the Tier 1 step nearest in time
(so both tiers sit on one picture).

### 5.7 Frames and playback

`frames()` samples `trace.steps` every `TWIN_FRAME_STRIDE_S = 30.0` s (the engine's
`DT_S` is 1 s; a 60-min trace becomes 121 frames), builds a frame per sample containing the
instrument, fire and mist traces, and returns Plotly frames plus `updatemenus` (Play /
Pause) and a `sliders` entry labelled `mm:ss`. The tunnel layer is static and drawn once.
Frame duration 150 ms.

## 6. HMI strip and timeline

### 6.1 `app/components/hmi.py`

`render(step: StepRecord, events: dict, design: Design) -> None` renders one row of
`st.metric` tiles: clock `mm:ss`, HRR `x.x MW` with delta vs free burn, water `L/min`,
tank remaining `m³` (`hydraulics.tank_m3 − water discharged so far`), `u / u_crit`. Under
them four **status lamps** — Detection, Activation, Full pressure, Discharge — as small
coloured squares with labels, lit when `step.t_s ≥ events["t_detect_s" | "t_activate_s" |
"t_full_pressure_s"]` and `step.water_lpm > 0` respectively. Lamps are plain HTML spans
styled by the CSS block of §9.2.

The HMI reads the step selected by a **time scrubber** (`st.slider` over frame indices,
shared key with the canvas's initial frame) so the strip and the canvas agree; playing
the Plotly animation does not move the Streamlit slider (Plotly runs client-side), which
is acceptable: the slider selects the frame the HMI describes, the canvas plays on its
own.

### 6.2 `app/components/timeline.py`

`render(events: dict, criteria: dict[str, Criterion], t_end_s: float) -> None` draws a
horizontal Plotly strip (height 120 px) from 0 to `t_end_s` with tick markers for
`t_detect_s`, `t_activate_s`, `t_full_pressure_s`, `t_peak_hrr_s`,
`pools_extinguished_at_s`, and `backlayering.cleared_at_s` when set; each labelled. Failed
criteria are listed as red chips beneath the strip (criteria are result-level, not
timed).

## 7. CFD data path

### 7.1 `solit2/engines/fds/slices.py`

```python
@dataclass(frozen=True)
class SliceMeta:  # one SLCF entry of the .smv
    mesh: int; path: Path; quantity: str; short: str; unit: str
    i1: int; i2: int; j1: int; j2: int; k1: int; k2: int

@dataclass(frozen=True)
class MeshGrid:   # TRNX/TRNY/TRNZ node coordinates of one mesh
    mesh: int; x_m: tuple[float, ...]; y_m: tuple[float, ...]; z_m: tuple[float, ...]

@dataclass(frozen=True)
class Slice:      # one plane, one quantity, all meshes stitched
    quantity: str; unit: str
    x_m: np.ndarray; z_m: np.ndarray; t_s: np.ndarray; frames: np.ndarray  # [t, z, x]

def read_smv(path: Path) -> tuple[list[SliceMeta], dict[int, MeshGrid]]
def read_sf(path: Path) -> tuple[tuple[str, str, str], tuple[int, ...], np.ndarray, np.ndarray]
def load_centreline(run_dir: Path, quantity: str) -> Slice | None
```

- `read_smv` parses `SLCF <mesh> # STRUCTURED & i1 i2 j1 j2 k1 k2 ! …` header lines with
  the four following lines (file, quantity, short name, unit), and the `GRID`/`TRNX`/
  `TRNY`/`TRNZ` blocks (each `TRN*` block: a count line, then `index coordinate` lines).
- `read_sf` reads Fortran sequential unformatted records (4-byte little-endian length
  marker, payload, marker): three 30-char headers, one 6-int bounds record, then repeated
  `(time: 1 float32)`, `(data: ni·nj·nk float32)`. It **stops at the first incomplete
  record** and returns what it has — FDS appends to these files while running.
- `load_centreline` selects the SLCF entries whose `j1 == j2` (a constant-y plane) and
  whose `quantity` matches, reads each, converts node indices to metres through the
  mesh's `TRNX`/`TRNZ`, drops the last frame of any mesh that has more frames than the
  minimum across meshes (so every mesh is at the same time), and concatenates along x in
  ascending `x_m`. Returns `None` when no matching entry exists yet. Never raises on a
  truncated file; raises `ValueError` on a malformed header.

### 7.2 Performance bound

A 600 m × 7.6 m centreline at dx = 0.6 m is ~1000 × 13 nodes = 13 k floats per frame; a
20-min run at the default slice interval writes on the order of a few hundred frames → a
few tens of MB read per refresh. `load_centreline` is wrapped in `st.cache_data` keyed on
the `.sf` files' sizes and mtimes, so an unchanged run is not re-parsed. Frames shown in
the canvas are subsampled to at most `CFD_MAX_FRAMES = 120` evenly in time.

### 7.3 Deck additions (`solit2/engines/fds/deck.py`, `_output()`)

Two lines appended after the existing two `&SLCF`:

```
&SLCF PBY=0.0, QUANTITY='SOOT DENSITY' /
&SLCF PBY=0.0, QUANTITY='MPUV', PART_ID='FINE' /
```

`PART_ID='FINE'` is the deck's own particle class. Existing tests asserting exact
`_output()` content are updated; a new test asserts both lines. A 30-second real FDS run
of `examples/designs/road-tunnel-twin-bore.json` at `--minutes 0.5` confirms FDS accepts
both quantities (the binary is on this machine).

### 7.4 Smokeview launch (`solit2/engines/fds/runner.py`)

```python
SMV_ENV = "SOLIT2_SMV_BIN"
def smokeview_binary() -> str | None   # $SOLIT2_SMV_BIN if it exists, else shutil.which("smokeview")
def open_smokeview(run_dir: Path) -> None   # Popen([bin, f"{chid}.smv"], cwd=run_dir, start_new_session=True)
```

`open_smokeview` raises `FileNotFoundError` naming the missing binary or `.smv`; the view
turns that into a disabled button with a caption. `.claude/launch.json` adds
`$HOME/FDS/FDS6/smvbin` to the PATH it exports, next to the FDS path already there. No
path inside `solit2/` names a machine-specific directory.

## 8. Test-facility twin (`solit2/reports/twin.py`)

```python
def test_facility_twin(design: Design) -> Design
```

Builds a design dict and returns `Design.from_dict(...)`:

| Block | Source |
|---|---|
| `meta` | `name = f"{design.meta.name}-test-facility"`, `notes` = the sentence below |
| `tunnel` | `{"preset": "solit2_test", "section": "test"}` |
| `fire` | `{"preset": design.fire.preset, "covered": true}` — the site's fire load, covered as Annex 7 5.2.5 prescribes |
| `nozzles` | `design.nozzles.model_dump(mode="json")` with `mounting.height_above_carriageway_m` replaced per the rule below |
| `hydraulics` | `design.hydraulics.model_dump(mode="json")` |
| `zones` | `{"section_length_m": 20.0, "sections_simultaneous": 3, "activation_delay_s": 60.0, "pump_ramp_s": 30.0, "duration_min": 35.0}` (Annex 7 test protocol, as `examples/designs/solit2-test-protocol.json` already encodes) |
| `ventilation` | `{"mode": "longitudinal", "velocity_range_ms": [1.5, 3.0]}` (Annex 7 5.2.7) |
| `detection` | `{"type": "linear_heat", "threshold_c": 60.0, "sensor_spacing_m": 12.0}` |
| `constraints` | omitted — site constraints do not apply in the test gallery |
| `ahj` | `design.ahj` unchanged — the acceptance limits belong to the project, not the tunnel |

**Mounting rule.** `drop = section_geometry(design).crown_height_m −
design.nozzles.mounting.height_above_carriageway_m`; twin height = `gallery_height −
drop`, where `gallery_height` is `height_m` read from the `solit2_test` tunnel preset
(5.2 m today), never hard-coded. If the result is ≤ 0 the function raises
`ValueError("nozzle mounting cannot be reproduced in the <h> m test gallery: the site's
drop below the crown is <drop> m")` and the Reports step shows that message. No silent
clamp. `meta.notes` states: "Test-facility twin of
<name>: the site's nozzle and hydraulics blocks in the SOLIT2 Annex 7 gallery. Heads
mounted <h> m above the carriageway, keeping the site's <drop> m drop below the crown."

`solit2_test` is a core preset (`solit2/presets/tunnel_solit2_test.json`), so this module
does not depend on `examples/`.

## 9. Visual design

### 9.1 Theme (`.streamlit/config.toml`)

Both themes are defined so the viewer's light/dark choice works.

| Token | Light | Dark |
|---|---|---|
| `backgroundColor` | `#F3F5F8` (cool off-white) | `#1B2230` (blue-grey, not near-black) |
| `secondaryBackgroundColor` | `#E6EAF0` | `#242D3D` |
| `textColor` | `#1C2432` | `#E4E9F0` |
| `primaryColor` | `#1D8F8A` (mist teal) | `#3FB8B0` |
| `borderColor` | `#CBD3DE` | `#34405A` |
| `redColor` / fail | `#C4452B` (ember) | `#E0654A` |
| `greenColor` / pass | `#2E8B57` | `#4FB57C` |
| `orangeColor` / unset | `#C98A1E` | `#E0A73A` |

`font = "IBM Plex Sans"`, `headingFont = "IBM Plex Sans"`, `codeFont = "IBM Plex Mono"`,
loaded through `[[theme.fontFaces]]` entries pointing at Google Fonts URLs; `baseRadius
= "0.375rem"`; `chartSequentialColors` set to the Inferno ramp so Streamlit-native charts
match the CFD scale; `metricValueFontSize = "1.6rem"`.

### 9.2 Custom CSS

One `st.markdown(..., unsafe_allow_html=True)` block in `app/theme.py`, injected once per
run, covering only: the stepper pills (done/current/disabled), the verdict banner, and the
HMI lamps. Everything else uses Streamlit's own widgets under the theme above.

### 9.3 Chart palette

- Temperature scale everywhere (instrument dots, fire marker, CFD temperature): Plotly
  `Inferno`, fixed `cmin = 20`, `cmax = max(400, peak ceiling temp rounded up to 100)`.
- Smoke: `Greys`; mist: `Blues`; structure lines: theme `borderColor`; mist fill and lit
  nozzles: `primaryColor`; fail states: `redColor`.

### 9.4 Copy

Buttons say what happens: "Build & continue →", "Start FDS run (20 min)", "Open in
Smokeview". Empty states say what to do next in one sentence. Units on every number.

## 10. Error handling

| Situation | Behaviour |
|---|---|
| No design | Steps 2–5 disabled in the stepper; if `step` > 1 with no design (e.g. after a reset) the page shows one line and a "Go to Design" button. |
| `Design.from_dict` fails on step 1 | `st.error` with the validation message (existing). |
| `envelope.run` raises | `st.error` naming the engine error; stepper stays usable. |
| FDS / mpiexec missing | Step 4 shows the pre-flight chips and no Start; steps 1–3, 5 unaffected. |
| `.sf` truncated mid-write | `read_sf` returns complete frames only; caption "last complete frame t = X s". |
| `.smv` absent (run just launched) | CFD panel shows "FDS has not written its geometry file yet"; fragment retries. |
| Smokeview binary missing | Button disabled; caption "Smokeview not found on PATH; set SOLIT2_SMV_BIN". |
| Twin cannot be built | Reports step shows the `ValueError` text under the correlation heading; test plan and exports still render. |
| `fds_reader.read` fails on a `done` run | `st.error` with the message; the CFD canvas still shows. |

## 11. Testing

- **AppTest** (`tests/test_app_wizard.py` replaces the six `test_app_*_view.py` files):
  landing shows step 1 and disabled pills 2–5; building a design enables them and advances
  to step 2; step 2 auto-runs (session state has a `result` without any button click);
  Back/Next move `step`; **no `file_uploader` element exists on any step**; step 5 has
  `twin_result` after entry; step 4 without FDS shows pre-flight text containing "fds".
- **Twin canvas** (`tests/test_twin_canvas.py`): `tunnel_layer` places the target at
  `fire.target_x_m`; `instrument_layer` emits one mast per in-window station with as many
  dots as `heights_m`; `fire_layer` marker size grows with `hrr_mw`; `mist_layer` returns
  no shape when `water_lpm == 0` and one when `> 0`; `frames` returns
  `len(range(0, t_end, 30)) + 1` frames; `figure` with a `Slice` includes one heatmap trace.
- **Slices** (`tests/test_fds_slices.py`): synthetic two-mesh `.sf` pair + minimal `.smv`
  written by the test with known values → `load_centreline` stitches to the expected x
  order and values; a truncated file yields one fewer frame; the committed real slice
  `tests/fixtures/fds/sample_1_1.sf` (29 KB, copied from `runs/dcfb87012b57`) parses to
  6 frames with header `('TEMPERATURE', 'temp', 'C')`.
- **Twin builder** (`tests/test_twin.py`): nozzle and hydraulics blocks equal the site's
  except mounting height; tunnel preset is `solit2_test`; mounting rule holds on a design
  with a 1.0 m drop; a drop of 6 m raises `ValueError`; the twin validates and runs in
  Tier 1.
- **Deck**: `_output()` contains both new `&SLCF` lines; existing exact-content tests
  updated.
- **Runner**: `smokeview_binary()` honours `SOLIT2_SMV_BIN`; `open_smokeview` raises
  `FileNotFoundError` without an `.smv`.
- **Independence scan** (`test_no_file_in_the_package_names_a_vendor_or_a_project`)
  must still pass: nothing under `solit2/` names a project, vendor, or machine path.

## 12. Files

| Path | Change |
|---|---|
| `app/streamlit_app.py` | stepper instead of sidebar radio; theme injection |
| `app/state.py` | `step`, `twin_result`, `tier2_result`; invalidation |
| `app/theme.py` | new — CSS block |
| `app/components/stepper.py` | new |
| `app/components/twin_canvas.py` | new |
| `app/components/hmi.py` | new |
| `app/components/timeline.py` | new |
| `app/views/design.py` | summary card; download moved out |
| `app/views/result.py` | new — replaces `run.py` + `leaderboard.py` |
| `app/views/fire_test.py` | new — replaces `tunnel.py` |
| `app/views/cfd.py` | new — replaces `verify.py` |
| `app/views/reports.py` | rewritten — no uploaders; twin; exports |
| `app/views/run.py`, `tunnel.py`, `leaderboard.py`, `verify.py` | deleted |
| `solit2/engines/fds/slices.py` | new |
| `solit2/engines/fds/deck.py` | two `&SLCF` lines |
| `solit2/engines/fds/runner.py` | `smokeview_binary`, `open_smokeview` |
| `solit2/reports/twin.py` | new |
| `.streamlit/config.toml` | new |
| `.claude/launch.json` | add Smokeview dir to PATH (also commits the FDS PATH change already made) |
| `tests/…` | as §11; the six old view tests deleted |

## 13. Out of scope

- Embedding or headless-driving Smokeview.
- Parsing `.prt5` particle files or `.s3d` smoke3d files (mist is shown from the `MPUV`
  slice instead).
- Remote / cloud execution of FDS.
- Any change to the physics engine, criteria, scoring or the reader.
- Plan-view (top-down) drawing of the tunnel.

## 14. Constraints carried from the project

- INDEPENDENCE rules 1 and 2 apply unchanged: nothing in `solit2/` or `app/` names a
  project, vendor or product; no acceptance limit is invented by the UI.
- Conventional commits, **no `Co-Authored-By` trailer** (user's global git rules).
- Python 3.12 via `uv`; files ≤ 400 lines target, 800 max; functions ≤ 50 lines.
- Frozen dataclasses; layer functions are pure.
- No new dependencies.

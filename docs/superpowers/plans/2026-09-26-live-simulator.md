# Live Simulator Screen Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A new landing screen: design knobs in the sidebar, reading tiles, and one animated
Plotly figure (six live gauges, a 3D tunnel, three charts) that replays the Tier 1 virtual fire
test from ignition, plus a live panel for any FDS run of the same design — and a dark theme
app-wide.

**Architecture:** Pure builders (`readings`, `tunnel3d`, `live_figure`) turn a design, its Tier 1
`Result` and the worst case's `RunTrace` into Plotly traces and frames, with no Streamlit import,
so every number can be asserted on without a browser. The Streamlit view (`simulator.py`) only
edits the shared current design, runs the engine through the existing `ensure_result` /
`ensure_trace`, and draws. A top-level view switch (`simulator` | `wizard` | `runs`) replaces the
run manager's boolean toggle.

**Tech Stack:** Python 3.13, Streamlit 1.64 (AppTest), Plotly 7 (`make_subplots`, `Indicator`,
`Scatter3d`, `Mesh3d`, `Surface`, `Cone`, frames), numpy, pydantic v2, pytest via `uv`.

**Spec:** `docs/superpowers/specs/2026-09-26-live-simulator-design.md`

## Global Constraints

- No new dependencies. Everything used here (streamlit, plotly, numpy, pydantic) is installed.
- No project or vendor names under `solit2/`, `app/`, `examples/` — `tests/test_independence.py` must pass.
- Every number the screen shows is the engine's own output for that design; nothing is smoothed, extrapolated or invented. A value the engine does not compute is not shown.
- A gauge gets a red band only where the design's `ahj` sets that gauge's criterion limit. Gauge ranges come from the run's own peak and the limit, never from a threshold nobody set.
- The score is always shown with how many criteria are set; `gates_passed` is never presented as approval while `criteria_unset` is non-empty.
- Schematic elements (smoke plane height, spray volume, the enlarged cross-section) are labelled schematic on screen.
- Tests never start a real FDS process.
- Match the code style: frozen dataclasses, named constants with a comment saying why, actionable `ValueError` messages that name the valid values.
- `app/theme.py`'s `CSS` block must contain no blank lines (`tests/test_app_theme.py` checks it).
- Commit messages: conventional (`feat:`, `fix:`, `test:`, `refactor:`, `docs:`), **no Co-Authored-By trailer**.
- Run tests with `uv run pytest` — **never add `-q`** (pyproject already adds it; a second `-q` hides the "N passed" line). Wrap every call in a hard timeout: `timeout 300 uv run pytest tests/<file> -x` for focused runs, and for the full suite strip FDS from PATH: `PATH=$(echo "$PATH" | tr ':' '\n' | grep -v -i fds | paste -sd: -) timeout 900 uv run pytest`.

**Base:** `main` after the CFD run-manager branch has merged (it adds `app/views/runs.py`,
`state.in_manager_view()` / `state.set_manager_view()` and a `manager_toggle` header button).
Work in a worktree: `git worktree add .worktrees/simulator -b feat/live-simulator main`.

## File structure

| File | Responsibility |
|---|---|
| `app/state.py` (modify) | `get_view()` / `set_view()` replace the run manager's boolean |
| `app/components/nav.py` (create) | the three top-level nav buttons |
| `app/streamlit_app.py` (modify) | routes the three screens |
| `solit2/schema/presets.py` (modify) | `calibration_hash()` — one statement of the provenance hash |
| `solit2/compliance/check.py` (modify) | uses `calibration_hash()` |
| `app/components/readings.py` (create) | gauges' values, limits and ranges; tiles; diagnostics line |
| `app/palette.py` (modify) | `FLAME` token |
| `app/components/twin_canvas.py` (modify) | `play_menu`, `time_slider`, `target_ignition_progress` made public |
| `app/components/tunnel3d.py` (create) | the 3D tunnel's static and per-instant traces |
| `app/components/live_figure.py` (create) | gauges + 3D + charts in one animated figure |
| `app/components/cfd_live.py` (create) | one FDS run's state and readings for the panel |
| `app/views/simulator.py` (create in Task 1, complete in Task 5) | the landing screen |
| `app/plot_theme.py` (create) | Plotly template chosen from the viewer's Streamlit theme |
| `app/theme.py`, `.streamlit/config.toml` (modify) | dark default and instrument styling |
| `README.md` (modify) | the simulator screen under "Running the app" |

---

### Task 1: Top-level views and navigation

**Files:**
- Modify: `app/state.py`
- Create: `app/components/nav.py`
- Modify: `app/streamlit_app.py`
- Create: `app/views/simulator.py` (minimal; completed in Task 5)
- Modify: `tests/test_app_wizard.py`, `tests/test_app_compliance_step.py`, and every test that uses `manager_view` / `manager_toggle`
- Test: `tests/test_app_nav.py`

**Interfaces:**
- Produces: `state.VIEWS = ("simulator", "wizard", "runs")`, `state.DEFAULT_VIEW = "simulator"`,
  `state.get_view() -> str`, `state.set_view(view: str) -> None` (raises `ValueError` on an
  unknown view). Button keys `nav_simulator`, `nav_wizard`, `nav_runs`; `sim_open_wizard` on the
  simulator screen.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_app_nav.py`:

```python
"""The app's three top-level screens and the nav between them."""
from streamlit.testing.v1 import AppTest

from app.views import cfd
from solit2 import history

APP = "../app/streamlit_app.py"


def _app(monkeypatch, tmp_path) -> AppTest:
    monkeypatch.setattr(history, "DEFAULT_PATH", tmp_path / "h.jsonl")
    monkeypatch.setattr(cfd, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setenv("SOLIT2_RUN_ROOTS", str(tmp_path / "runs"))
    monkeypatch.setenv("SOLIT2_CFD_STATE_DIR", str(tmp_path / "state"))
    at = AppTest.from_file(APP, default_timeout=180)
    at.run()
    return at


def _keys(at: AppTest) -> set[str]:
    return {b.key for b in at.button}


def test_the_app_opens_on_the_simulator(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    assert not at.exception
    assert {"nav_simulator", "nav_wizard", "nav_runs"} <= _keys(at)
    assert "step_1" not in _keys(at)


def test_the_nav_opens_the_wizard_and_comes_back(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    at.button(key="nav_wizard").click().run()
    assert not at.exception
    assert "step_1" in _keys(at)
    at.button(key="nav_simulator").click().run()
    assert "step_1" not in _keys(at)


def test_the_nav_opens_the_runs_manager(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    at.button(key="nav_runs").click().run()
    assert not at.exception
    assert at.session_state["view"] == "runs"


def test_set_view_refuses_an_unknown_view():
    at = AppTest.from_string("from app import state\nstate.set_view('nowhere')\n")
    at.run()
    assert at.exception
    assert "unknown view" in at.exception[0].value
```

- [ ] **Step 2: Run them to see them fail**

Run: `timeout 300 uv run pytest tests/test_app_nav.py -x`
Expected: FAIL (`nav_simulator` missing / `set_view` not defined).

- [ ] **Step 3: Add the view accessors to `app/state.py`**

Remove the run manager's `_MANAGER_KEY`, `in_manager_view()` and `set_manager_view()`, and add,
after `STEP_MIN, STEP_MAX = 1, 6`:

```python
_VIEW_KEY = "view"
# The app's three top-level screens: the live simulator is the landing screen,
# the wizard carries the formal record, the runs manager watches the FDS fleet.
VIEWS = ("simulator", "wizard", "runs")
DEFAULT_VIEW = "simulator"


def get_view() -> str:
    view = st.session_state.get(_VIEW_KEY, DEFAULT_VIEW)
    return view if view in VIEWS else DEFAULT_VIEW


def set_view(view: str) -> None:
    if view not in VIEWS:
        raise ValueError(f"unknown view {view!r}; expected one of {', '.join(VIEWS)}")
    st.session_state[_VIEW_KEY] = view
```

Update the module docstring's list of keys to include `view`.

- [ ] **Step 4: Migrate every caller of the old toggle**

Run: `grep -rn "manager_view\|manager_toggle\|in_manager_view\|set_manager_view" app tests`

Replace each hit:
- `state.in_manager_view()` → `state.get_view() == "runs"`
- `state.set_manager_view(True)` → `state.set_view("runs")`; `state.set_manager_view(False)` → `state.set_view("wizard")`
- `at.session_state["manager_view"] = True` → `at.session_state["view"] = "runs"`
- a test clicking `manager_toggle` to open the manager → click `nav_runs`; to leave it → click `nav_wizard`
- a "← Back to design" button inside `app/views/runs.py`, if any, is removed: the nav row replaces it.

- [ ] **Step 5: Create `app/components/nav.py`**

```python
"""The top-level nav: one button per screen, the current one highlighted."""
from __future__ import annotations

import streamlit as st

from app import state

LABELS = {"simulator": "Simulator", "wizard": "Wizard", "runs": "CFD runs"}
# Three narrow buttons on the left, the rest of the row left empty.
NAV_COLUMNS = (1, 1, 1, 5)


def render() -> None:
    current = state.get_view()
    for col, (view, label) in zip(st.columns(NAV_COLUMNS), LABELS.items()):
        kind = "primary" if view == current else "secondary"
        if col.button(label, key=f"nav_{view}", type=kind, width="stretch"):
            state.set_view(view)
            st.rerun()
```

- [ ] **Step 6: Create the minimal `app/views/simulator.py`**

```python
"""The landing screen. This task gives it its heading and the way into the wizard;
the sidebar, tiles, live figure and CFD panel arrive in Task 5."""
from __future__ import annotations

import streamlit as st

from app import state


def render() -> None:
    st.markdown('<div class="sim-head">SOLIT² VIRTUAL FIRE TEST · Tier 1 · PREDICTION</div>',
                unsafe_allow_html=True)
    if st.button("Open the wizard →", key="sim_open_wizard"):
        state.set_view("wizard")
        st.rerun()
```

- [ ] **Step 7: Route the screens in `app/streamlit_app.py`**

Replace the file with:

```python
"""Entry point. Run with: uv run streamlit run app/streamlit_app.py"""
from __future__ import annotations

import streamlit as st

from app import state, theme
from app.components import nav, stepper
from app.views import cfd, compliance, design, fire_test, reports, result, runs, simulator

st.set_page_config(page_title="SOLIT2 Simulator", layout="wide",
                   initial_sidebar_state="expanded")
theme.inject()

STEP_VIEWS = {1: design.render, 2: result.render, 3: fire_test.render,
              4: cfd.render, 5: compliance.render, 6: reports.render}


def _wizard() -> None:
    stepper.render_header()
    step = state.get_step()
    if step > state.STEP_MIN and state.get_design() is None:
        st.info("Build a design first — every later step is computed from it.")
        if st.button("Go to Design", key="goto_design", type="primary"):
            state.set_step(state.STEP_MIN)
            st.rerun()
    else:
        STEP_VIEWS[step]()
    stepper.render_footer()


SCREENS = {"simulator": simulator.render, "wizard": _wizard, "runs": runs.render}

nav.render()
SCREENS[state.get_view()]()
```

- [ ] **Step 8: Point the whole-app tests at the wizard**

In `tests/test_app_wizard.py`, set the view before the first run in `_app`:

```python
    at = AppTest.from_file(APP, default_timeout=180)
    at.session_state["view"] = "wizard"
    at.run()
```

and rename `test_landing_is_the_design_step_with_later_steps_locked` to
`test_the_wizard_opens_on_the_design_step_with_later_steps_locked` (the landing screen is now
the simulator; this test is about the wizard). In `tests/test_app_compliance_step.py` add
`at.session_state["view"] = "wizard"` beside `at.session_state["step"] = 5`.

- [ ] **Step 9: Run the tests**

Run: `timeout 300 uv run pytest tests/test_app_nav.py tests/test_app_wizard.py tests/test_app_compliance_step.py tests/test_app_runs_step.py -x`
Expected: PASS.

- [ ] **Step 10: Commit**

```bash
git add app/state.py app/components/nav.py app/streamlit_app.py app/views/simulator.py app/views/runs.py tests/
git commit -m "feat(app): three top-level screens, the simulator as the landing one"
```

---

### Task 2: Gauge readings, tiles and the diagnostics line

**Files:**
- Modify: `solit2/schema/presets.py`, `solit2/compliance/check.py`
- Create: `app/components/readings.py`
- Test: `tests/test_simulator_readings.py`

**Interfaces:**
- Produces:
  - `solit2.schema.presets.CALIBRATION_HASH_CHARS = 12`, `calibration_hash() -> str`
  - `readings.Gauge(key: str, label: str, unit: str, criterion: str | None, lower_is_worse: bool = False)` (frozen)
  - `readings.GAUGES: tuple[Gauge, ...]` in this order: `hrr_mw`, `air_temp_c`, `heat_flux_kwm2`, `visibility_m`, `air_velocity_ms`, `water_lpm`
  - `readings.reading(step: StepRecord, key: str) -> float`
  - `readings.limit(result: Result, gauge: Gauge) -> float | None`
  - `readings.axis_max(trace: RunTrace, gauge: Gauge, limit_value: float | None) -> float`
  - `readings.Tile(label: str, value: str, note: str)` (frozen); `readings.tiles(result: Result) -> tuple[Tile, ...]`
  - `readings.criteria_set(result: Result) -> tuple[int, int]` (set, total)
  - `readings.diagnostics(result: Result) -> str`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_simulator_readings.py`:

```python
"""The simulator's readings are the engine's own, read the way the criteria read them."""
import pytest

from app.components import readings
from solit2.engines.reduced import envelope
from solit2.engines.reduced.criteria import (
    HEAT_FLUX_STATIONS, THERMOCOUPLE_STATIONS, VISIBILITY_STATIONS,
)
from solit2.engines.reduced.sim import run_once
from solit2.schema.design import Design
from solit2.schema.presets import calibration_hash

PROTOCOL = "examples/designs/solit2-test-protocol.json"


@pytest.fixture(scope="module")
def run():
    design = Design.load(PROTOCOL)
    result = envelope.run(design)
    trace = run_once(design, result.worst_case["section"], result.worst_case["velocity_ms"])
    return design, result, trace


def _gauge(key: str) -> readings.Gauge:
    return next(g for g in readings.GAUGES if g.key == key)


def _with_limit(design: Design, field: str, value: float) -> Design:
    raw = design.model_dump(by_alias=True, mode="json")
    raw["ahj"][field] = value      # a synthetic limit, set by this test only
    return Design.from_dict(raw)


def test_air_temperature_is_the_worst_breathing_height_reading_at_that_instant(run):
    step = run[2].steps[len(run[2].steps) // 2]
    assert readings.reading(step, "air_temp_c") == max(
        step.stations[n].temp_c for n in THERMOCOUPLE_STATIONS)


def test_flux_and_visibility_read_only_the_stations_that_carry_the_instrument(run):
    step = run[2].steps[len(run[2].steps) // 2]
    assert readings.reading(step, "heat_flux_kwm2") == max(
        step.stations[n].flux_kwm2 for n in HEAT_FLUX_STATIONS)
    assert readings.reading(step, "visibility_m") == min(
        step.stations[n].visibility_m for n in VISIBILITY_STATIONS)


def test_the_plain_gauges_are_the_steps_own_fields(run):
    step = run[2].steps[-1]
    assert readings.reading(step, "hrr_mw") == step.hrr_mw
    assert readings.reading(step, "air_velocity_ms") == step.u_eff_ms
    assert readings.reading(step, "water_lpm") == step.water_lpm


def test_an_unknown_gauge_is_refused_with_the_valid_names(run):
    with pytest.raises(ValueError, match="unknown gauge 'co_ppm'.*hrr_mw"):
        readings.reading(run[2].steps[0], "co_ppm")


def test_a_gauges_limit_is_exactly_what_the_design_declares(run):
    design, result, _ = run
    assert readings.limit(result, _gauge("air_temp_c")) == design.ahj.max_air_temp_c
    assert readings.limit(result, _gauge("hrr_mw")) == design.ahj.tvs_design_fire_mw


def test_a_set_limit_is_the_criterions_own(run):
    result = envelope.run(_with_limit(run[0], "max_air_temp_c", 60.0))
    assert readings.limit(result, _gauge("air_temp_c")) == 60.0


def test_velocity_and_water_never_carry_a_limit(run):
    for key in ("air_velocity_ms", "water_lpm"):
        assert _gauge(key).criterion is None
        assert readings.limit(run[1], _gauge(key)) is None


def test_the_axis_covers_the_peak_and_the_limit(run):
    trace = run[2]
    peak = max(s.hrr_mw for s in trace.steps)
    assert readings.axis_max(trace, _gauge("hrr_mw"), None) >= peak
    assert readings.axis_max(trace, _gauge("hrr_mw"), 10 * peak) >= 10 * peak


def test_the_score_tile_says_how_many_criteria_are_set(run):
    result = run[1]
    n_set, total = readings.criteria_set(result)
    assert total == len(result.criteria)
    assert n_set == total - len(result.score["criteria_unset"])
    score = next(t for t in readings.tiles(result) if t.label == "Score")
    assert score.value == f"{result.score['total']:.1f}"
    assert (score.note == f"{n_set} of {total} criteria set"
            or score.note.startswith("gates failed"))


def test_the_tiles_carry_the_results_own_peaks(run):
    result = run[1]
    hrr = next(t for t in readings.tiles(result) if t.label == "Peak heat release")
    assert hrr.value == f"{result.peaks['hrr_mw']:.1f} MW"
    assert hrr.note == f"free burn {result.peaks['hrr_free_burn_mw']:.1f} MW"


def test_the_diagnostics_line_names_the_worst_case_and_the_calibration(run):
    line = readings.diagnostics(run[1])
    assert "playback: worst case" in line
    assert f"calibration {calibration_hash()}" in line
```

- [ ] **Step 2: Run them to see them fail**

Run: `timeout 300 uv run pytest tests/test_simulator_readings.py -x`
Expected: FAIL with `ImportError` (`readings` / `calibration_hash`).

- [ ] **Step 3: Add `calibration_hash()` to `solit2/schema/presets.py`**

Add `import hashlib` beside the existing `import json`, then below `load_calibration()`:

```python
# The provenance hash of a calibration is the first 12 hex digits of SHA-256,
# long enough to tell two fits apart and short enough to read in a report.
CALIBRATION_HASH_CHARS = 12


def calibration_hash() -> str:
    """The calibration the engine is actually using, fingerprinted.

    Hashes `load_calibration()` -- the process-cached content every Tier 1 run
    reads -- rather than a fresh read of the file, so the hash can never name a
    calibration the runs did not use (see `reload_calibration`)."""
    text = json.dumps(load_calibration(), sort_keys=True).encode()
    return hashlib.sha256(text).hexdigest()[:CALIBRATION_HASH_CHARS]
```

In `solit2/compliance/check.py`, replace the local `CALIBRATION_HASH_CHARS = 12` with an import
(`from solit2.schema.presets import CALIBRATION_HASH_CHARS, calibration_hash`) and replace the
two lines that build `calibration` and `provenance["calibration"]` with
`provenance["calibration"] = calibration_hash()`. Remove imports that become unused (`json`,
`hashlib` if nothing else uses them, `load_calibration`).

- [ ] **Step 4: Create `app/components/readings.py`**

```python
"""What the simulator's gauges and tiles read -- every value the engine's own.

Four gauges are the quantities Annex 7 section 7.2 judges, read exactly the way
`solit2.engines.reduced.criteria` reads them: the worst value, at one instant,
over the Table 5 stations that carry that instrument and no others. That is what
lets a gauge's red band be the criterion's own limit and nothing else. The other
two gauges (air velocity, water flow) have no Annex 7 limit, so they never get one.

No Streamlit import: the figure builders and their tests use this directly.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from solit2.engines.reduced.criteria import (
    HEAT_FLUX_STATIONS, THERMOCOUPLE_STATIONS, VISIBILITY_STATIONS,
)
from solit2.engines.reduced.state import RunTrace, StepRecord
from solit2.schema.presets import calibration_hash
from solit2.schema.result import Result

# The dial ends 10 % above the larger of the run's own peak and the limit, so the
# needle never pins and a limit is never drawn off the dial.
RANGE_HEADROOM = 1.1


@dataclass(frozen=True)
class Gauge:
    key: str
    label: str
    unit: str
    criterion: str | None         # the criterion whose `ahj` limit bands this gauge
    lower_is_worse: bool = False  # visibility: the limit is a floor, not a ceiling


GAUGES: tuple[Gauge, ...] = (
    Gauge("hrr_mw", "Heat release", "MW", "hrr_below_tvs_design_mw"),
    Gauge("air_temp_c", "Air temperature", "°C", "max_air_temp_c"),
    Gauge("heat_flux_kwm2", "Heat flux", "kW/m²", "max_heat_flux_kwm2"),
    Gauge("visibility_m", "Visibility", "m", "min_visibility_m", lower_is_worse=True),
    Gauge("air_velocity_ms", "Air velocity", "m/s", None),
    Gauge("water_lpm", "Water flow", "L/min", None),
)

_READERS: dict[str, Callable[[StepRecord], float]] = {
    "hrr_mw": lambda s: s.hrr_mw,
    "air_temp_c": lambda s: max(s.stations[n].temp_c for n in THERMOCOUPLE_STATIONS),
    "heat_flux_kwm2": lambda s: max(s.stations[n].flux_kwm2 for n in HEAT_FLUX_STATIONS),
    "visibility_m": lambda s: min(s.stations[n].visibility_m for n in VISIBILITY_STATIONS),
    "air_velocity_ms": lambda s: s.u_eff_ms,
    "water_lpm": lambda s: s.water_lpm,
}


def reading(step: StepRecord, key: str) -> float:
    """One gauge's value at one instant."""
    reader = _READERS.get(key)
    if reader is None:
        raise ValueError(f"unknown gauge {key!r}; expected one of {', '.join(_READERS)}")
    return float(reader(step))


def limit(result: Result, gauge: Gauge) -> float | None:
    """The authority's limit for this gauge's criterion, or None where nobody set one."""
    if gauge.criterion is None:
        return None
    criterion = result.criteria.get(gauge.criterion)
    if criterion is None or criterion.limit is None:
        return None
    return float(criterion.limit)


def axis_max(trace: RunTrace, gauge: Gauge, limit_value: float | None) -> float:
    peak = max(reading(s, gauge.key) for s in trace.steps)
    top = max(peak, limit_value if limit_value is not None else 0.0) * RANGE_HEADROOM
    return top if top > 0 else 1.0


@dataclass(frozen=True)
class Tile:
    label: str
    value: str
    note: str


def criteria_set(result: Result) -> tuple[int, int]:
    """How many of the Annex 7 criteria have a limit to be judged against, of how many."""
    total = len(result.criteria)
    return total - len(result.score.get("criteria_unset", [])), total


def tiles(result: Result) -> tuple[Tile, ...]:
    peaks, events, score = result.peaks, result.events, result.score
    n_set, total = criteria_set(result)
    full = events.get("t_full_pressure_s")
    ignited = bool(result.criteria["target_ignited"].value)
    failed = list(score.get("gates_failed") or [])
    return (
        Tile("Peak heat release", f"{peaks['hrr_mw']:.1f} MW",
             f"free burn {peaks['hrr_free_burn_mw']:.1f} MW"),
        Tile("Peak ceiling gas", f"{peaks['ceiling_temp_c']:.0f} °C", "under the ceiling"),
        Tile("Target", "ignited" if ignited else "not ignited", "Annex 7 §7.2.1"),
        Tile("Full pressure", f"{full:.0f} s" if full is not None else "never reached",
             "after ignition"),
        Tile("Score", f"{score['total']:.1f}",
             "gates failed: " + ", ".join(failed) if failed
             else f"{n_set} of {total} criteria set"),
    )


_EVENT_LABELS = (("t_detect_s", "detect"), ("t_activate_s", "activate"),
                 ("t_full_pressure_s", "full pressure"), ("t_peak_hrr_s", "peak HRR"))


def diagnostics(result: Result) -> str:
    """The run's events, what is judged, which case plays, and the calibration."""
    events = result.events
    parts = [f"{label} {events[key]:.0f} s" if events.get(key) is not None else f"{label} —"
             for key, label in _EVENT_LABELS]
    back = events.get("backlayering") or {}
    if back.get("occurred"):
        cleared = back.get("cleared_at_s")
        parts.append(f"backlayering {back['max_length_m']:.0f} m"
                     + (f", cleared {cleared:.0f} s" if cleared is not None else ", not cleared"))
    n_set, total = criteria_set(result)
    parts.append(f"criteria set {n_set}/{total}")
    case = result.worst_case
    parts.append(f"playback: worst case, {case['section']} section at "
                 f"{case['velocity_ms']:.2f} m/s")
    parts.append(f"calibration {calibration_hash()}")
    return " · ".join(parts)
```

- [ ] **Step 5: Run the tests**

Run: `timeout 300 uv run pytest tests/test_simulator_readings.py tests/test_compliance_check.py -x`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add solit2/schema/presets.py solit2/compliance/check.py app/components/readings.py tests/test_simulator_readings.py
git commit -m "feat(app): gauge readings read the way the Annex 7 criteria read them"
```

---

### Task 3: The 3D tunnel

**Files:**
- Modify: `app/palette.py` (add `FLAME`)
- Modify: `app/components/twin_canvas.py` (public `play_menu`, `time_slider`, `target_ignition_progress`)
- Modify: `tests/test_twin_canvas.py` (two references to the renamed function)
- Create: `app/components/tunnel3d.py`
- Test: `tests/test_tunnel3d.py`

**Interfaces:**
- Consumes: `twin_canvas.core_window_m(design)`, `twin_canvas.temp_max_c(trace)`, `twin_canvas.BACKLAYER_MIN_M`, `twin_canvas.TEMP_SCALE`, `twin_canvas.TEMP_MIN_C`, `twin_canvas.BREATHING_HEIGHT_M`, `twin_canvas.FIRE_MARKER_MIN_PX/MAX_PX`, `cross_section.tunnel_outline(geom)`, `geometry.nozzle_positions(design, geom, fire_x_m)`, `geometry.fire_lateral_m(design, geom)`.
- Produces:
  - `palette.FLAME = "#F28C28"`
  - `twin_canvas.play_menu(x: float = 0.0, y: float = 1.30) -> dict`, `twin_canvas.time_slider(names: list[str], active: int, y: float = 1.16) -> dict`, `twin_canvas.target_ignition_progress(step) -> float`
  - `tunnel3d.box(x, y, z, *, name, colour, opacity) -> go.Mesh3d`
  - `tunnel3d.static_traces(design, geom, window_m) -> list` — names: `"tunnel"`, `"carriageway"`, `"fire load"`, `"stations (breathing height)"`
  - `tunnel3d.dynamic_traces(design, geom, step, window_m, *, hrr_peak_mw: float, cmax_c: float) -> list` — always 6 traces in this order: flame, target, heads, spray, smoke, airflow
  - `tunnel3d.smoke_profile(step, xs: np.ndarray) -> np.ndarray`
  - `tunnel3d.scene_layout(geom, window_m) -> dict`

- [ ] **Step 1: Write the failing tests**

Create `tests/test_tunnel3d.py`:

```python
"""The 3D tunnel is the design's geometry and the engine's state, nothing more."""
from dataclasses import replace

import numpy as np
import pytest

from app import palette
from app.components import tunnel3d, twin_canvas
from solit2.engines.reduced import envelope
from solit2.engines.reduced.criteria import STATIONS
from solit2.engines.reduced.geometry import section_geometry
from solit2.engines.reduced.sim import run_once
from solit2.schema.design import Design

PROTOCOL = "examples/designs/solit2-test-protocol.json"


@pytest.fixture(scope="module")
def run():
    design = Design.load(PROTOCOL)
    result = envelope.run(design)
    trace = run_once(design, result.worst_case["section"], result.worst_case["velocity_ms"])
    return design, section_geometry(design), trace, twin_canvas.core_window_m(design)


def _dynamic(run, step):
    design, geom, trace, window = run
    return tunnel3d.dynamic_traces(design, geom, step, window,
                                   hrr_peak_mw=max(s.hrr_mw for s in trace.steps),
                                   cmax_c=twin_canvas.temp_max_c(trace))


def test_a_box_has_eight_corners_at_its_extents_and_twelve_triangles():
    b = tunnel3d.box((0.0, 2.0), (-1.0, 1.0), (0.0, 3.0), name="b", colour="#000000", opacity=1.0)
    assert sorted(set(b.x)) == [0.0, 2.0]
    assert sorted(set(b.y)) == [-1.0, 1.0]
    assert sorted(set(b.z)) == [0.0, 3.0]
    assert len(b.i) == len(b.j) == len(b.k) == 12


def test_the_fire_load_is_the_footprint(run):
    design, geom, _, window = run
    fire = next(t for t in tunnel3d.static_traces(design, geom, window) if t.name == "fire load")
    fp = design.fire.footprint
    assert (min(fire.x), max(fire.x)) == (-fp.length_m / 2, fp.length_m / 2)
    assert (min(fire.z), max(fire.z)) == (fp.base_height_m, fp.top_height_m)


def test_there_are_always_six_dynamic_traces_in_a_fixed_order(run):
    traces = _dynamic(run, run[2].steps[0])
    assert [t.type for t in traces] == ["scatter3d", "mesh3d", "scatter3d", "mesh3d",
                                        "surface", "cone"]


def test_heads_take_the_mist_colour_only_while_water_flows(run):
    dry = next(s for s in run[2].steps if s.water_lpm == 0)
    wet = next(s for s in run[2].steps if s.water_lpm > 0)
    assert _dynamic(run, dry)[2].marker.color == palette.GREY
    assert _dynamic(run, wet)[2].marker.color == palette.PRIMARY


def test_the_spray_is_invisible_before_discharge(run):
    dry = next(s for s in run[2].steps if s.water_lpm == 0)
    wet = next(s for s in run[2].steps if s.water_lpm > 0)
    assert _dynamic(run, dry)[3].opacity == 0.0
    assert _dynamic(run, wet)[3].opacity > 0.0


def test_smoke_starts_at_the_backlayering_front(run):
    window = run[3]
    step = run[2].steps[len(run[2].steps) // 2]
    back = replace(step, backlayer_m=12.0)
    assert _dynamic(run, back)[4].x[0] == pytest.approx(max(-12.0, window[0]))
    none = replace(step, backlayer_m=0.0)
    assert _dynamic(run, none)[4].x[0] == pytest.approx(0.0)


def test_smoke_colour_at_a_station_is_that_stations_top_thermocouple(run):
    step = run[2].steps[len(run[2].steps) // 2]
    at_d15 = tunnel3d.smoke_profile(step, np.array([STATIONS["D15"]]))[0]
    assert at_d15 == pytest.approx(step.stations["D15"].temps_c[-1])


def test_the_flame_marker_grows_with_heat_release(run):
    steps = run[2].steps
    peak = max(steps, key=lambda s: s.hrr_mw)
    small = min((s for s in steps if s.hrr_mw > 0), key=lambda s: s.hrr_mw)
    assert _dynamic(run, peak)[0].marker.size == pytest.approx(twin_canvas.FIRE_MARKER_MAX_PX)
    assert _dynamic(run, small)[0].marker.size < _dynamic(run, peak)[0].marker.size
```

- [ ] **Step 2: Run them to see them fail**

Run: `timeout 300 uv run pytest tests/test_tunnel3d.py -x`
Expected: FAIL with `ImportError: cannot import name 'tunnel3d'`.

- [ ] **Step 3: Add the flame token and make three twin helpers public**

In `app/palette.py`, below `STEAM`:

```python
FLAME = "#F28C28"        # the fire itself -- warm, and apart from FAIL's red so a burning mock-up does not read as a failed check
```

In `app/components/twin_canvas.py`:
- rename `_target_ignition_progress` → `target_ignition_progress` (definition and its call site in `tunnel_layer`);
- replace `_play_menu()` with `play_menu(x: float = 0.0, y: float = 1.30) -> dict` — same body, with `"x": x, "y": y` in place of the literals;
- replace `_slider(names, active)` with `time_slider(names: list[str], active: int, y: float = 1.16) -> dict` — same body, with `"y": y`;
- update `figure()` to call `play_menu()` and `time_slider(names, k0)`; add the three names to `__all__`.

In `tests/test_twin_canvas.py` replace both `tc._target_ignition_progress` with
`tc.target_ignition_progress`.

- [ ] **Step 4: Create `app/components/tunnel3d.py`**

```python
"""The simulator's 3D tunnel: geometry from the design, state from one Tier 1 step.

Pure builders -- Plotly traces only, no Streamlit -- so every element can be
asserted on without a browser. x = 0 is the mock-up's longitudinal middle
(Annex 7 section 6.3), y = 0 the tunnel centreline, z the height above the
carriageway: the frame the engine, `STATIONS` and the FDS deck share.

Two elements are schematic and say so in their names: the smoke plane's height
(the engine computes no layer depth) and the spray volume (the engine models the
mist's effect, not its shape). The smoke's COLOUR is the engine's own gas
temperature at the stations, interpolated between them. Everything else is the
design's geometry or the engine's output.
"""
from __future__ import annotations

import numpy as np
import plotly.graph_objects as go

from app import palette
from app.components import cross_section, twin_canvas
from solit2.engines.reduced.criteria import STATIONS
from solit2.engines.reduced.geometry import SectionGeometry, fire_lateral_m, nozzle_positions
from solit2.engines.reduced.state import StationSample, StepRecord
from solit2.schema.design import Design

RING_SPACING_M = 20.0         # a wireframe cross-section ring every 20 m
EDGE_EVERY = 6                # a longitudinal edge through every 6th outline point
SMOKE_DEPTH_FRACTION = 0.1    # schematic: the smoke plane sits 10 % of the crown height below it
SMOKE_SAMPLE_M = 5.0          # the smoke colour is sampled every 5 m along the tunnel
SMOKE_OPACITY = 0.75
SPRAY_OPACITY = 0.12
SPRAY_SPREAD_M = 1.0          # schematic: the spray volume reaches 1 m beyond the outer rows
ROAD_OPACITY = 0.25
FIRE_LOAD_OPACITY = 0.6
TARGET_MIN_OPACITY, TARGET_MAX_OPACITY = 0.25, 0.85
AIR_ARROW_M = 3.0             # the airflow cone's length; its label carries the speed
POST_STATIONS = ("U45", "U15", "D15", "D45", "D100")
# Every station with a thermocouple tree along the tunnel. "Target" is the target's
# own thermocouples, not a cross-section, so it does not colour the smoke.
SMOKE_STATIONS = tuple(n for n in sorted(STATIONS, key=STATIONS.get) if n != "Target")

# A box's 8 corners: 0-3 the bottom face, 4-7 the top, each counter-clockwise.
# Two triangles per face, 12 in all.
_BOX_I = [0, 0, 4, 4, 0, 0, 3, 3, 0, 0, 1, 1]
_BOX_J = [1, 2, 5, 6, 1, 5, 2, 6, 3, 7, 2, 6]
_BOX_K = [2, 3, 6, 7, 5, 4, 6, 7, 7, 4, 6, 5]


def box(x: tuple[float, float], y: tuple[float, float], z: tuple[float, float], *,
        name: str, colour: str, opacity: float) -> go.Mesh3d:
    (x0, x1), (y0, y1), (z0, z1) = x, y, z
    return go.Mesh3d(x=[x0, x1, x1, x0, x0, x1, x1, x0],
                     y=[y0, y0, y1, y1, y0, y0, y1, y1],
                     z=[z0, z0, z0, z0, z1, z1, z1, z1],
                     i=_BOX_I, j=_BOX_J, k=_BOX_K, color=colour, opacity=opacity,
                     name=name, showlegend=True, hoverinfo="name", flatshading=True)


def _shell(geom: SectionGeometry, window_m: tuple[float, float]) -> go.Scatter3d:
    """Wireframe rings every RING_SPACING_M and a few longitudinal edges, from the
    same outline `cross_section.tunnel_outline` samples off `width_at(height)`."""
    outline = cross_section.tunnel_outline(geom)
    ys, zs = list(outline.x), list(outline.y)
    x0, x1 = window_m
    first = np.ceil(x0 / RING_SPACING_M) * RING_SPACING_M
    xs_all: list[float | None] = []
    ys_all: list[float | None] = []
    zs_all: list[float | None] = []
    for x in np.arange(first, x1 + 1e-9, RING_SPACING_M):
        xs_all += [float(x)] * len(ys) + [None]
        ys_all += ys + [None]
        zs_all += zs + [None]
    for idx in range(0, len(ys), EDGE_EVERY):
        xs_all += [x0, x1, None]
        ys_all += [ys[idx], ys[idx], None]
        zs_all += [zs[idx], zs[idx], None]
    return go.Scatter3d(x=xs_all, y=ys_all, z=zs_all, mode="lines", name="tunnel",
                        line={"color": palette.GREY, "width": 2}, hoverinfo="skip")


def _stations(window_m: tuple[float, float]) -> go.Scatter3d:
    names = [n for n in POST_STATIONS if window_m[0] <= STATIONS[n] <= window_m[1]]
    return go.Scatter3d(x=[STATIONS[n] for n in names], y=[0.0] * len(names),
                        z=[twin_canvas.BREATHING_HEIGHT_M] * len(names),
                        mode="markers+text", text=names, textposition="top center",
                        name="stations (breathing height)", hoverinfo="text",
                        marker={"size": 3, "color": palette.GREY, "symbol": "diamond"})


def static_traces(design: Design, geom: SectionGeometry,
                  window_m: tuple[float, float]) -> list:
    """Everything that does not change during the test."""
    x0, x1 = window_m
    half = geom.road_width_m / 2.0
    fp = design.fire.footprint
    y = fire_lateral_m(design, geom)
    return [
        _shell(geom, window_m),
        box((x0, x1), (-half, half), (0.0, 0.02), name="carriageway",
            colour=palette.GREY, opacity=ROAD_OPACITY),
        box((-fp.length_m / 2, fp.length_m / 2), (y - fp.width_m / 2, y + fp.width_m / 2),
            (fp.base_height_m, fp.top_height_m), name="fire load",
            colour=palette.GREY, opacity=FIRE_LOAD_OPACITY),
        _stations(window_m),
    ]


def _flame(design: Design, geom: SectionGeometry, step: StepRecord,
           hrr_peak_mw: float) -> go.Scatter3d:
    share = min(max(step.hrr_mw / hrr_peak_mw, 0.0), 1.0) if hrr_peak_mw > 0 else 0.0
    size = (twin_canvas.FIRE_MARKER_MIN_PX
            + (twin_canvas.FIRE_MARKER_MAX_PX - twin_canvas.FIRE_MARKER_MIN_PX) * share)
    return go.Scatter3d(x=[0.0], y=[fire_lateral_m(design, geom)],
                        z=[design.fire.footprint.top_height_m], mode="markers",
                        name="flame (size follows heat release)", hoverinfo="text",
                        hovertext=[f"{step.hrr_mw:.1f} MW"],
                        marker={"size": size, "color": palette.FLAME, "opacity": 0.85})


def _target(design: Design, geom: SectionGeometry, step: StepRecord) -> go.Mesh3d:
    """Annex 7 section 5.2.6 gives the target's width and height, not its length along
    the tunnel; like the 2D twin, its length is taken as its width."""
    fp = design.fire.footprint
    y = fire_lateral_m(design, geom)
    progress = twin_canvas.target_ignition_progress(step)
    x0 = design.fire.target_x_m
    return box((x0, x0 + fp.width_m), (y - fp.width_m / 2, y + fp.width_m / 2),
               (fp.base_height_m, fp.top_height_m), name="target (ignition progress)",
               colour=palette.FAIL if progress > 0 else palette.GREY,
               opacity=TARGET_MIN_OPACITY + (TARGET_MAX_OPACITY - TARGET_MIN_OPACITY) * progress)


def _heads(design: Design, geom: SectionGeometry, step: StepRecord) -> go.Scatter3d:
    heads = nozzle_positions(design, geom, fire_x_m=0.0)
    colour = palette.PRIMARY if step.water_lpm > 0.0 else palette.GREY
    return go.Scatter3d(x=[h.x_m for h in heads], y=[h.y_m for h in heads],
                        z=[h.z_m for h in heads], mode="markers",
                        name="nozzle heads (active length)", hoverinfo="skip",
                        marker={"size": 3, "color": colour})


def _spray(design: Design, geom: SectionGeometry, step: StepRecord) -> go.Mesh3d:
    mount = design.nozzles.mounting
    half_length = design.active_length_m / 2.0
    half_road = geom.road_width_m / 2.0
    y0 = max(min(mount.row_lateral_offsets_m) - SPRAY_SPREAD_M, -half_road)
    y1 = min(max(mount.row_lateral_offsets_m) + SPRAY_SPREAD_M, half_road)
    return box((-half_length, half_length), (y0, y1), (0.0, mount.height_above_carriageway_m),
               name="spray (schematic volume)", colour=palette.PRIMARY,
               opacity=SPRAY_OPACITY if step.water_lpm > 0.0 else 0.0)


def _top_rung(sample: StationSample) -> float:
    """The thermocouple nearest the ceiling (`temps_c` runs floor upwards)."""
    return sample.temps_c[-1] if sample.temps_c else sample.temp_c


def smoke_profile(step: StepRecord, xs: np.ndarray) -> np.ndarray:
    """Gas temperature under the ceiling along the tunnel: each station's top
    thermocouple, linearly interpolated between stations and held flat beyond
    the end ones."""
    station_x = np.array([STATIONS[n] for n in SMOKE_STATIONS])
    station_t = np.array([_top_rung(step.stations[n]) for n in SMOKE_STATIONS])
    return np.interp(xs, station_x, station_t)


def _smoke(geom: SectionGeometry, step: StepRecord, window_m: tuple[float, float],
           cmax_c: float) -> go.Surface:
    x0, x1 = window_m
    start = -step.backlayer_m if step.backlayer_m >= twin_canvas.BACKLAYER_MIN_M else 0.0
    start = max(start, x0)
    xs = np.arange(start, x1 + 1e-9, SMOKE_SAMPLE_M)
    if len(xs) < 2:
        xs = np.array([start, x1])
    temps = smoke_profile(step, xs)
    z = geom.crown_height_m * (1.0 - SMOKE_DEPTH_FRACTION)
    half = geom.width_at(z) / 2.0
    return go.Surface(x=xs, y=np.array([-half, half]), z=np.full((2, len(xs)), z),
                      surfacecolor=np.vstack([temps, temps]),
                      cmin=twin_canvas.TEMP_MIN_C, cmax=cmax_c,
                      colorscale=twin_canvas.TEMP_SCALE, opacity=SMOKE_OPACITY,
                      showscale=True, colorbar={"title": {"text": "gas °C"}, "len": 0.45},
                      name="smoke (engine temperature; height schematic)", hoverinfo="skip")


def _airflow(geom: SectionGeometry, step: StepRecord,
             window_m: tuple[float, float]) -> go.Cone:
    return go.Cone(x=[window_m[0] + AIR_ARROW_M], y=[0.0], z=[geom.crown_height_m / 2.0],
                   u=[1.0], v=[0.0], w=[0.0], sizemode="absolute", sizeref=AIR_ARROW_M,
                   anchor="tail", showscale=False,
                   colorscale=[[0.0, palette.PRIMARY], [1.0, palette.PRIMARY]],
                   name=f"air {step.u_eff_ms:.2f} m/s", hoverinfo="text",
                   hovertext=[f"air {step.u_eff_ms:.2f} m/s"])


def dynamic_traces(design: Design, geom: SectionGeometry, step: StepRecord,
                   window_m: tuple[float, float], *, hrr_peak_mw: float,
                   cmax_c: float) -> list:
    """The six traces that change from instant to instant, always in this order:
    flame, target, heads, spray, smoke, airflow. `live_figure` indexes frames by it."""
    return [_flame(design, geom, step, hrr_peak_mw), _target(design, geom, step),
            _heads(design, geom, step), _spray(design, geom, step),
            _smoke(geom, step, window_m, cmax_c), _airflow(geom, step, window_m)]


# Across the tunnel the picture is enlarged for legibility: a 150 m window drawn to
# true scale would leave a 10 m bore as a sliver. The screen's caption says so.
ASPECT = {"x": 3.0, "y": 1.0, "z": 0.7}


def scene_layout(geom: SectionGeometry, window_m: tuple[float, float]) -> dict:
    """Fixed axis ranges, so the scene never rescales between frames."""
    half = geom.road_width_m / 2.0 + 0.5
    return {"xaxis": {"title": {"text": "along the tunnel (m)"}, "range": list(window_m)},
            "yaxis": {"title": {"text": "across (m)"}, "range": [-half, half]},
            "zaxis": {"title": {"text": "height (m)"},
                      "range": [0.0, geom.crown_height_m + 0.5]},
            "aspectmode": "manual", "aspectratio": ASPECT,
            "camera": {"eye": {"x": -1.4, "y": -1.8, "z": 0.9}}}
```

- [ ] **Step 5: Run the tests**

Run: `timeout 300 uv run pytest tests/test_tunnel3d.py tests/test_twin_canvas.py tests/test_app_fire_test_step.py -x`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add app/palette.py app/components/twin_canvas.py app/components/tunnel3d.py tests/test_tunnel3d.py tests/test_twin_canvas.py
git commit -m "feat(app): a 3D tunnel built from the design and one Tier 1 step"
```

---

### Task 4: The animated figure

**Files:**
- Create: `app/components/live_figure.py`
- Test: `tests/test_live_figure.py`

**Interfaces:**
- Consumes: everything Task 2 and Task 3 produce; `twin_canvas.sample_steps`, `twin_canvas.mmss`, `twin_canvas.TWIN_FRAME_STRIDE_S`, `twin_canvas.play_menu`, `twin_canvas.time_slider`.
- Produces: `live_figure.figure(design, result, trace, *, window_m, stride_s=twin_canvas.TWIN_FRAME_STRIDE_S, template=None) -> go.Figure`; `live_figure.FIGURE_BUDGET_BYTES`; `live_figure.CHART_STATIONS`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_live_figure.py`:

```python
"""One figure, one clock: every gauge, the 3D scene and the chart cursors share a frame."""
import pytest

from app.components import live_figure, readings, twin_canvas
from solit2.engines.reduced import envelope
from solit2.engines.reduced.sim import run_once
from solit2.schema.design import Design

PROTOCOL = "examples/designs/solit2-test-protocol.json"


def _build(design: Design):
    result = envelope.run(design)
    trace = run_once(design, result.worst_case["section"], result.worst_case["velocity_ms"])
    fig = live_figure.figure(design, result, trace, window_m=twin_canvas.core_window_m(design))
    steps = twin_canvas.sample_steps(trace, twin_canvas.TWIN_FRAME_STRIDE_S)
    return result, trace, fig, steps


@pytest.fixture(scope="module")
def built():
    return _build(Design.load(PROTOCOL))


def _indicators(data):
    return [d for d in data if d.type == "indicator"]


def test_one_frame_per_sampled_step(built):
    _, _, fig, steps = built
    assert len(fig.frames) == len(steps)


def test_frame_gauges_are_the_engines_readings_at_that_instant(built):
    _, _, fig, steps = built
    for k in (0, len(steps) // 2, len(steps) - 1):
        values = [d.value for d in _indicators(fig.frames[k].data)]
        wanted = [readings.reading(steps[k], g.key) for g in readings.GAUGES]
        assert values == pytest.approx(wanted)


def test_the_chart_cursors_sit_on_the_frames_instant(built):
    _, _, fig, steps = built
    k = len(steps) // 2
    cursors = [d for d in fig.frames[k].data if d.type == "scatter"]
    assert len(cursors) == 3
    assert all(list(c.x) == [steps[k].t_s, steps[k].t_s] for c in cursors)


def test_frames_update_exactly_the_dynamic_traces(built):
    _, _, fig, _ = built
    indices = list(fig.frames[0].traces)
    assert len(indices) == len(fig.frames[0].data)
    assert indices == list(range(len(fig.data) - len(indices), len(fig.data)))


def test_a_gauge_has_a_band_only_where_its_limit_is_set(built):
    result, _, fig, _ = built
    for d, gauge in zip(_indicators(fig.data), readings.GAUGES):
        lim = readings.limit(result, gauge)
        if lim is None:
            assert not d.gauge.steps and d.gauge.threshold.value is None
        else:
            assert d.gauge.threshold.value == lim


def test_a_set_limit_draws_its_band_from_the_limit_up():
    raw = Design.load(PROTOCOL).model_dump(by_alias=True, mode="json")
    raw["ahj"]["max_heat_flux_kwm2"] = 5.0   # a synthetic limit, set by this test only
    _, _, fig, _ = _build(Design.from_dict(raw))
    flux = _indicators(fig.data)[[g.key for g in readings.GAUGES].index("heat_flux_kwm2")]
    assert flux.gauge.threshold.value == 5.0
    assert flux.gauge.steps[0].range[0] == 5.0


def test_the_figure_stays_inside_its_size_budget(built):
    assert len(built[2].to_json()) < live_figure.FIGURE_BUDGET_BYTES
```

- [ ] **Step 2: Run them to see them fail**

Run: `timeout 300 uv run pytest tests/test_live_figure.py -x`
Expected: FAIL with `ImportError: cannot import name 'live_figure'`.

- [ ] **Step 3: Create `app/components/live_figure.py`**

```python
"""The simulator's animated figure: gauges, the 3D tunnel and three charts in ONE
Plotly figure, so a single Play button and a single time slider keep every
element on the same instant -- entirely in the browser, with no server round
trip per frame, so playback is as smooth on the remote server as it is locally.

Frames update only the dynamic traces, which sit after every static one; the
frames' `traces` list names their indices.
"""
from __future__ import annotations

import plotly.graph_objects as go
from plotly.subplots import make_subplots

from app import palette
from app.components import readings, tunnel3d, twin_canvas
from solit2.engines.reduced.geometry import section_geometry
from solit2.engines.reduced.state import RunTrace, StepRecord
from solit2.schema.design import Design
from solit2.schema.result import Result

FIGURE_HEIGHT_PX = 1180
ROW_HEIGHTS = (0.16, 0.56, 0.28)
CHART_COLUMNS = (1, 3, 5)          # each chart spans two of the six columns
CHART_TITLES = ("Heat release (MW)", "Breathing-height air (°C)", "Heat flux (kW/m²)")
CHART_STATIONS = ("U45", "U15", "D15", "D45", "D100")
CHART_HEADROOM = 1.05
# A whole run's figure, every frame included, stays under this many bytes of JSON:
# a 45 min test at the twin's 30 s stride is about 90 frames.
FIGURE_BUDGET_BYTES = 6_000_000
GAUGE_BAND_ALPHA = 0.35


def _gauge(gauge: readings.Gauge, value: float, top: float,
           limit: float | None) -> go.Indicator:
    spec: dict = {"axis": {"range": [0.0, top]}, "bar": {"color": palette.PRIMARY}}
    if limit is not None:
        band = [0.0, limit] if gauge.lower_is_worse else [limit, top]
        spec["steps"] = [{"range": band, "color": palette.rgba(palette.FAIL, GAUGE_BAND_ALPHA)}]
        spec["threshold"] = {"line": {"color": palette.FAIL, "width": 3}, "value": limit}
    return go.Indicator(mode="gauge+number", value=value, gauge=spec,
                        number={"suffix": f" {gauge.unit}", "valueformat": ".1f"},
                        title={"text": gauge.label.upper(), "font": {"size": 12}})


def _series(trace: RunTrace) -> list[tuple[int, go.Scatter]]:
    """(chart column, line) for every static chart line."""
    t = [s.t_s for s in trace.steps]
    lines = [
        (1, go.Scatter(x=t, y=[s.hrr_mw for s in trace.steps], name="heat release",
                       mode="lines", line={"color": palette.FLAME})),
        (1, go.Scatter(x=t, y=[s.hrr_free_mw for s in trace.steps],
                       name="free burn (engine)", mode="lines",
                       line={"color": palette.GREY, "dash": "dash"})),
    ]
    for name in CHART_STATIONS:
        lines.append((3, go.Scatter(x=t, y=[s.stations[name].temp_c for s in trace.steps],
                                    name=f"{name} air", mode="lines")))
    lines.append((5, go.Scatter(x=t, y=[readings.reading(s, "heat_flux_kwm2")
                                        for s in trace.steps],
                                name="worst station flux", mode="lines")))
    lines.append((5, go.Scatter(x=t, y=[s.target_flux_kwm2 for s in trace.steps],
                                name="flux at the target", mode="lines",
                                line={"dash": "dot"})))
    return lines


def _cursor(t_s: float, top: float) -> go.Scatter:
    return go.Scatter(x=[t_s, t_s], y=[0.0, top], mode="lines", showlegend=False,
                      hoverinfo="skip", line={"color": palette.UNSET, "width": 2})


def figure(design: Design, result: Result, trace: RunTrace, *,
           window_m: tuple[float, float],
           stride_s: float = twin_canvas.TWIN_FRAME_STRIDE_S,
           template: go.layout.Template | str | None = None) -> go.Figure:
    geom = section_geometry(design)
    steps = twin_canvas.sample_steps(trace, stride_s)
    names = [twin_canvas.mmss(s.t_s) for s in steps]
    hrr_peak = max(s.hrr_mw for s in trace.steps)
    cmax = twin_canvas.temp_max_c(trace)
    limits = [readings.limit(result, g) for g in readings.GAUGES]
    tops = [readings.axis_max(trace, g, lim) for g, lim in zip(readings.GAUGES, limits)]

    fig = make_subplots(
        rows=3, cols=6, row_heights=list(ROW_HEIGHTS), vertical_spacing=0.05,
        specs=[[{"type": "indicator"}] * 6,
               [{"type": "scene", "colspan": 6}] + [None] * 5,
               [{"type": "xy", "colspan": 2}, None, {"type": "xy", "colspan": 2}, None,
                {"type": "xy", "colspan": 2}, None]])

    # Static traces first: the geometry and the chart lines never change.
    for static in tunnel3d.static_traces(design, geom, window_m):
        fig.add_trace(static, row=2, col=1)
    series = _series(trace)
    for col, line in series:
        fig.add_trace(line, row=3, col=col)
    chart_top = {col: (max(max(line.y) for c, line in series if c == col) * CHART_HEADROOM
                       or 1.0) for col in CHART_COLUMNS}

    def dynamic(step: StepRecord) -> list[tuple[object, int, int]]:
        out: list[tuple[object, int, int]] = [
            (_gauge(g, readings.reading(step, g.key), top, lim), 1, i + 1)
            for i, (g, lim, top) in enumerate(zip(readings.GAUGES, limits, tops))]
        out += [(t, 2, 1) for t in tunnel3d.dynamic_traces(
            design, geom, step, window_m, hrr_peak_mw=hrr_peak, cmax_c=cmax)]
        out += [(_cursor(step.t_s, chart_top[col]), 3, col) for col in CHART_COLUMNS]
        return out

    first = len(fig.data)
    for trace_, row, col in dynamic(steps[0]):
        fig.add_trace(trace_, row=row, col=col)
    indices = list(range(first, len(fig.data)))
    fig.frames = [go.Frame(name=names[k], traces=indices,
                           data=[t for t, _, _ in dynamic(step)])
                  for k, step in enumerate(steps)]

    fig.update_layout(
        height=FIGURE_HEIGHT_PX, template=template,
        margin={"l": 40, "r": 20, "t": 30, "b": 170},
        scene=tunnel3d.scene_layout(geom, window_m),
        legend={"orientation": "h", "y": -0.16},
        updatemenus=[twin_canvas.play_menu(y=-0.03)],
        sliders=[twin_canvas.time_slider(names, 0, y=-0.03)])
    for col, title in zip(CHART_COLUMNS, CHART_TITLES):
        fig.update_xaxes(title_text="test clock (s)", row=3, col=col)
        fig.update_yaxes(title_text=title, row=3, col=col)
    return fig
```

- [ ] **Step 4: Run the tests**

Run: `timeout 300 uv run pytest tests/test_live_figure.py -x`
Expected: PASS. If the budget test fails, report the measured size in the task report rather
than raising the budget.

- [ ] **Step 5: Commit**

```bash
git add app/components/live_figure.py tests/test_live_figure.py
git commit -m "feat(app): one animated figure for gauges, 3D tunnel and charts"
```

---

### Task 5: The simulator screen

**Files:**
- Create: `app/components/cfd_live.py`
- Modify (complete): `app/views/simulator.py`
- Test: `tests/test_app_simulator.py`

**Interfaces:**
- Consumes: Tasks 1-4; `result.ensure_result(design)`, `fire_test.ensure_trace(design, result)`, `cfd.run_dir_for(design)`, `cfd.live_metrics(live)`, `fds_runner.status(run_dir)`, `fds_runner.live(run_dir)`, `spec.is_design_payload(raw)`.
- Produces: `simulator.render()`, `simulator.edited(design, changes) -> Design`, `simulator.preset_files() -> list[Path]`, `simulator.DEFAULT_PRESET`; widget keys `sim_preset`, `sim_pressure`, `sim_k`, `sim_mount`, `sim_heads`, `sim_section`, `sim_sections`, `sim_velocity`, `sim_open_wizard`, `sim_open_cfd`; `cfd_live.Panel`, `cfd_live.panel(design) -> Panel | None`, `cfd_live.REFRESH_S = 10`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_app_simulator.py`:

```python
"""The landing screen, headless: live readings of the engine's own output."""
from streamlit.testing.v1 import AppTest

from app.views import cfd, simulator
from solit2 import history
from solit2.engines.fds import deck
from solit2.schema.design import Design

APP = "../app/streamlit_app.py"


def _app(monkeypatch, tmp_path) -> AppTest:
    monkeypatch.setattr(history, "DEFAULT_PATH", tmp_path / "h.jsonl")
    monkeypatch.setattr(cfd, "RUNS_DIR", tmp_path / "runs")
    at = AppTest.from_file(APP, default_timeout=180)
    at.run()
    return at


def _text(at: AppTest) -> str:
    return " ".join(m.value for m in at.markdown)


def test_the_landing_screen_is_the_live_simulator(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    assert not at.exception
    assert "VIRTUAL FIRE TEST" in _text(at)
    assert "TIER 1 · PREDICTION" in _text(at)
    assert at.session_state["design"] is not None


def test_the_tiles_show_the_results_own_peaks(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    result = at.session_state["result"]
    assert f"{result.peaks['hrr_mw']:.1f} MW" in _text(at)
    assert f"free burn {result.peaks['hrr_free_burn_mw']:.1f} MW" in _text(at)


def test_the_calibration_note_is_on_screen(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    note = at.session_state["result"].meta["calibration_note"]
    assert any(note in c.value for c in at.caption)


def test_moving_a_slider_rebuilds_the_design_and_reruns_the_engine(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    before = at.session_state["result"].meta["design_sha"]
    at.sidebar.slider(key="sim_pressure").set_value(60.0).run()
    assert not at.exception
    assert at.session_state["design"].nozzles.pressure_bar == 60.0
    assert at.session_state["result"].meta["design_sha"] != before


def test_settings_that_make_no_valid_design_are_reported_and_the_last_design_kept(
        monkeypatch, tmp_path):
    def refuse(design, changes):
        raise ValueError("synthetic refusal")
    at = _app(monkeypatch, tmp_path)
    before = at.session_state["design"]
    monkeypatch.setattr(simulator, "edited", refuse)
    at.sidebar.slider(key="sim_pressure").set_value(61.0).run()
    assert any("synthetic refusal" in e.value for e in at.error)
    assert at.session_state["design"] == before


def test_a_preset_loads_that_design_file(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    at.session_state["sim_preset"] = "solit2-test-protocol-class-b"
    at.run()
    expected = Design.load("examples/designs/solit2-test-protocol-class-b.json")
    assert at.session_state["design"] == expected


def test_open_the_wizard_lands_on_the_result_step_with_the_same_design(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    sha = at.session_state["result"].meta["design_sha"]
    at.sidebar.button(key="sim_open_wizard").click().run()
    assert at.session_state["view"] == "wizard"
    assert at.session_state["step"] == 2
    assert at.session_state["result"].meta["design_sha"] == sha


def test_the_cfd_panel_says_when_no_run_exists(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    assert any("CFD not run for this design" in c.value for c in at.caption)


def test_the_cfd_panel_reads_a_run_of_this_design(monkeypatch, tmp_path):
    chid = deck.chid(Design.load(simulator.DEFAULT_PRESET))
    run_dir = tmp_path / "runs" / chid
    run_dir.mkdir(parents=True)
    (run_dir / "deck.fds").write_text(f"&HEAD CHID='{chid}' /\n&TIME T_END=1200.0 /\n")
    (run_dir / f"{chid}.out").write_text("Time Step 10\n Total Time:  120.0 s\n")
    at = _app(monkeypatch, tmp_path)
    assert not at.exception
    assert any(m.label == "Simulated" for m in at.metric)
```

- [ ] **Step 2: Run them to see them fail**

Run: `timeout 600 uv run pytest tests/test_app_simulator.py -x`
Expected: FAIL (no tiles / no `simulator.edited`).

- [ ] **Step 3: Create `app/components/cfd_live.py`**

```python
"""The simulator's CFD panel: what an FDS run of this exact design is doing, read
from the run's own files. A run belongs to a design when its CHID is the design's
SHA (`deck.chid`) -- the CFD step names its run directories that way, so the
panel finds a run without anyone linking it by hand."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from app.views import cfd
from solit2.engines.fds import runner as fds_runner
from solit2.schema.design import Design

# How often the panel re-reads the run's files: the same cadence as the runs manager.
REFRESH_S = 10
# The four readings worth a glance beside the figure; the CFD step shows them all.
PANEL_METRICS = ("Simulated", "Speed", "Left, at this speed", "Heat release")


@dataclass(frozen=True)
class Panel:
    run_dir: Path
    state: str
    progress: float
    detail: str
    metrics: tuple[tuple[str, str, str | None], ...]


def panel(design: Design) -> Panel | None:
    """The run of this design, or None when there is none."""
    run_dir = cfd.run_dir_for(design)
    if not (run_dir / "deck.fds").exists():
        return None
    try:
        status = fds_runner.status(run_dir)
        live = fds_runner.live(run_dir)
    except OSError as exc:
        return Panel(run_dir, "unreadable", 0.0, f"{run_dir}: {exc}", ())
    metrics = tuple(m for m in cfd.live_metrics(live) if m[0] in PANEL_METRICS)
    return Panel(run_dir, str(status["state"]), float(status.get("progress") or 0.0),
                 str(status.get("detail") or ""), metrics)
```

- [ ] **Step 4: Replace `app/views/simulator.py` with the full screen**

```python
"""The landing screen: move a design knob and watch the virtual fire test replay,
every reading moving together. Tier 1 runs a whole test in about a second, so the
answer is on screen as soon as a slider is released.

The sliders edit the SHARED current design (`state.get_design()`), the one the
wizard's later steps read: the design is dumped, the changed fields are set, and
it is rebuilt through `Design.from_dict`, so everything the sliders do not show
survives unchanged. The test protocol's own values are shown, not edited.
"""
from __future__ import annotations

import html
import json
from dataclasses import dataclass
from pathlib import Path

import streamlit as st

from app import state
from app.components import cfd_live, live_figure, readings, twin_canvas
from app.views.fire_test import ensure_trace
from app.views.result import ensure_result
from solit2.compliance.spec import is_design_payload
from solit2.engines.reduced.geometry import nozzle_positions, section_geometry
from solit2.schema.design import Design

PRESET_ROOTS = (Path("designs"), Path("examples/designs"))
DEFAULT_PRESET = Path("examples/designs/solit2-test-protocol.json")
_APPLIED_PRESET = "_sim_applied_preset"
_SEEDED_FROM = "_sim_seeded_from"
VELOCITY_KEY = "sim_velocity"
VELOCITY_PATH = ("ventilation", "velocity_range_ms")
VELOCITY_RANGE_MS = (0.0, 8.0)     # the schema's own bounds on a ventilation velocity
CHIP = {"done": "pass", "running": "pass", "failed": "fail", "stopped": "fail",
        "unreadable": "fail"}
CAPTION = (
    "Every reading is the Tier 1 engine's own output for this design: a prediction, not a "
    "measurement. Gauges show the worst of the Annex 7 Table 5 stations that carry each "
    "instrument; a red band is the authority's limit and appears only where one is set. "
    "Across the tunnel the picture is enlarged for legibility. The smoke plane's height and "
    "the spray volume are schematic; the smoke's colour is the engine's temperature at the "
    "stations, interpolated between them.")


@dataclass(frozen=True)
class Slider:
    key: str
    label: str
    path: tuple[str, ...]
    low: float
    high: float
    step: float


SLIDERS: tuple[Slider, ...] = (
    Slider("sim_pressure", "Nozzle pressure (bar)", ("nozzles", "pressure_bar"), 34.5, 140.0, 0.5),
    Slider("sim_k", "K-factor (L/min·bar⁰·⁵)", ("nozzles", "k_factor_lpm_bar05"), 0.6, 20.0, 0.1),
    Slider("sim_mount", "Mounting height (m)",
           ("nozzles", "mounting", "height_above_carriageway_m"), 1.0, 12.0, 0.1),
    Slider("sim_heads", "Heads per zone", ("zones", "heads_per_zone"), 1, 200, 1),
    Slider("sim_section", "Section length (m)", ("zones", "section_length_m"), 8.0, 100.0, 1.0),
    Slider("sim_sections", "Sections simultaneous", ("zones", "sections_simultaneous"), 1, 6, 1),
)


def preset_files() -> list[Path]:
    """Design files in the user's own space and in the shipped examples; a compliance
    spec or a project rules file is not a design and is left out."""
    found = []
    for root in PRESET_ROOTS:
        if not root.is_dir():
            continue
        for path in sorted(root.glob("*.json")):
            try:
                raw = json.loads(path.read_text())
            except (OSError, ValueError):
                continue
            if is_design_payload(raw):
                found.append(path)
    return found


def _get(raw: dict, path: tuple) -> object:
    node = raw
    for step in path:
        node = node[step]
    return node


def _set(raw: dict, path: tuple, value: object) -> None:
    node = raw
    for step in path[:-1]:
        node = node[step]
    node[path[-1]] = value


def edited(design: Design, changes: dict[tuple, object]) -> Design:
    """`design` with each path set to its value, everything else untouched, checked
    that its nozzle rows fit the section at the mounting height."""
    raw = design.model_dump(by_alias=True, mode="json")
    for path, value in changes.items():
        _set(raw, path, value)
    candidate = Design.from_dict(raw)
    nozzle_positions(candidate, section_geometry(candidate), fire_x_m=0.0)
    return candidate


def _current(design: Design, raw: dict, slider: Slider) -> float:
    if slider.path == ("zones", "heads_per_zone"):
        return design.heads_per_zone      # computed from the pitch when the file pins none
    return _get(raw, slider.path)


def _bounds(slider: Slider, value: float, design: Design) -> tuple[float, float]:
    """The slider's range, widened to hold the design's own value -- a range that
    clipped it would edit the design the moment it loaded."""
    high = slider.high
    if slider.key == "sim_mount":
        high = section_geometry(design).crown_height_m
    return min(slider.low, value), max(high, value)


def _seed(design: Design) -> None:
    """Write the design's values into the sliders' own state before they render."""
    raw = design.model_dump(by_alias=True, mode="json")
    for slider in SLIDERS:
        st.session_state[slider.key] = _current(design, raw, slider)
    lo, hi = _get(raw, VELOCITY_PATH)
    st.session_state[VELOCITY_KEY] = (float(lo), float(hi))
    st.session_state[_SEEDED_FROM] = design


def _presets() -> None:
    files = preset_files()
    labels = [p.stem for p in files]
    chosen = st.pills("Design file", labels, key="sim_preset", label_visibility="collapsed")
    if chosen is None:
        st.session_state[_APPLIED_PRESET] = None
    elif st.session_state.get(_APPLIED_PRESET) != chosen:
        st.session_state[_APPLIED_PRESET] = chosen
        state.set_design(Design.load(files[labels.index(chosen)]))
        st.rerun()


def _protocol(design: Design) -> None:
    zones, det = design.zones, design.detection
    manual = (f" · manual start {zones.manual_activation_s:.0f} s"
              if zones.manual_activation_s is not None else "")
    st.markdown('<div class="sim-label">Protocol (read-only)</div>', unsafe_allow_html=True)
    st.caption(f"activation delay {zones.activation_delay_s:.0f} s · pump ramp "
               f"{zones.pump_ramp_s:.0f} s · duration {zones.duration_min:.0f} min · "
               f"detector {det.threshold_c:.0f} °C every {det.sensor_spacing_m:.0f} m{manual}")


def _sidebar(design: Design) -> dict[tuple, object]:
    """The knobs; returns the fields the sliders now set differently from the design."""
    changes: dict[tuple, object] = {}
    with st.sidebar:
        st.markdown('<div class="sim-label">Presets</div>', unsafe_allow_html=True)
        _presets()
        st.markdown('<div class="sim-label">Parameters</div>', unsafe_allow_html=True)
        st.caption("Drag a slider — the result updates when you let go.")
        raw = design.model_dump(by_alias=True, mode="json")
        for slider in SLIDERS:
            value_now = _current(design, raw, slider)
            low, high = _bounds(slider, value_now, design)
            chosen = st.slider(slider.label, min_value=low, max_value=high,
                               step=slider.step, key=slider.key)
            if chosen != value_now:
                changes[slider.path] = chosen
        lo, hi = _get(raw, VELOCITY_PATH)
        v_lo, v_hi = st.slider("Ventilation velocity (m/s)", *VELOCITY_RANGE_MS, step=0.1,
                               key=VELOCITY_KEY)
        if (v_lo, v_hi) != (lo, hi):
            changes[VELOCITY_PATH] = [float(v_lo), float(v_hi)]
        _protocol(design)
        if st.button("Open the wizard →", key="sim_open_wizard", width="stretch"):
            state.set_view("wizard")
            state.set_step(2)
            st.rerun()
    return changes


def _header(design: Design, result) -> None:
    tiles = "".join(
        f'<div class="tile"><div class="tile-label">{html.escape(t.label)}</div>'
        f'<div class="tile-value">{html.escape(t.value)}</div>'
        f'<div class="tile-note">{html.escape(t.note)}</div></div>'
        for t in readings.tiles(result))
    st.markdown(
        f'<div class="sim-head">◉ SOLIT² VIRTUAL FIRE TEST · '
        f'{html.escape(str(result.meta["engine_version"]))} · Tier 1 · '
        f'{html.escape(design.meta.name)} '
        f'<span class="chip unset">Class {html.escape(design.fire.fire_class)}</span></div>'
        f'<div class="tiles">{tiles}</div>'
        f'<div class="diag"><span class="pill"><span class="dot"></span>TIER 1 · PREDICTION'
        f'</span> {html.escape(readings.diagnostics(result))}</div>',
        unsafe_allow_html=True)
    st.caption(str(result.meta.get("calibration_note", "")))


@st.fragment(run_every=cfd_live.REFRESH_S)
def _cfd_panel(design: Design) -> None:
    st.markdown('<div class="sim-label">CFD · LIVE</div>', unsafe_allow_html=True)
    found = cfd_live.panel(design)
    if found is None:
        st.caption("CFD not run for this design.")
        if st.button("Set up a CFD run →", key="sim_open_cfd", width="stretch"):
            state.set_view("wizard")
            state.set_step(4)
            st.rerun()
        return
    chip = CHIP.get(found.state, "unset")
    st.markdown(f'<span class="chip {chip}">{html.escape(found.state)}</span>',
                unsafe_allow_html=True)
    st.progress(min(max(found.progress, 0.0), 1.0))
    if found.detail:
        st.caption(found.detail)
    for label, value, help_text in found.metrics:
        st.metric(label, value, help=help_text)


def render() -> None:
    design = state.get_design()
    if design is None:
        design = Design.load(DEFAULT_PRESET)
        state.set_design(design)
    if st.session_state.get(_SEEDED_FROM) != design:
        _seed(design)
    changes = _sidebar(design)
    if changes:
        try:
            candidate = edited(design, changes)
        except ValueError as exc:   # pydantic's ValidationError is a ValueError
            st.error(f"Those settings do not make a valid design: {exc}. "
                     "The screen shows the last valid design.")
        else:
            state.set_design(candidate)
            st.rerun()
    result = ensure_result(design)
    trace = ensure_trace(design, result)
    _header(design, result)
    main, side = st.columns([5, 1])
    with main:
        fig = live_figure.figure(design, result, trace,
                                 window_m=twin_canvas.core_window_m(design))
        st.plotly_chart(fig, key="sim_figure", theme=None)
        st.caption(CAPTION)
    with side:
        _cfd_panel(design)
```

- [ ] **Step 5: Run the tests**

Run: `timeout 600 uv run pytest tests/test_app_simulator.py tests/test_app_nav.py -x`
Expected: PASS.

- [ ] **Step 6: Look at it**

Run the app (`uv run streamlit run app/streamlit_app.py`), open http://localhost:8501, press
▶ Play once and confirm the gauges, the 3D scene and the three cursors move together. Note in
the report anything that renders badly (overlapping legend, clipped slider). Stop the server.

- [ ] **Step 7: Commit**

```bash
git add app/components/cfd_live.py app/views/simulator.py tests/test_app_simulator.py
git commit -m "feat(app): the live simulator screen, with a CFD panel for this design's run"
```

---

### Task 6: Dark theme, instrument styling, plot template, docs

**Files:**
- Modify: `.streamlit/config.toml`, `app/theme.py`
- Create: `app/plot_theme.py`
- Modify: `app/views/simulator.py`, `app/views/fire_test.py`, `app/views/design.py`, `app/views/cfd.py` (the `theme=None` call sites)
- Modify: `tests/test_app_theme.py`, `README.md`
- Test: `tests/test_plot_theme.py`

**Interfaces:**
- Produces: `plot_theme.template(theme_type: str | None) -> go.layout.Template`, `plot_theme.current() -> go.layout.Template`; CSS classes `.sim-head`, `.sim-label`, `.tiles`, `.tile`, `.tile-label`, `.tile-value`, `.tile-note`, `.diag`, `.pill`, `.dot`.

- [ ] **Step 1: Write the failing tests**

Create `tests/test_plot_theme.py`:

```python
"""Figures drawn with theme=None follow the viewer's Streamlit theme."""
import tomllib
from pathlib import Path

from app import plot_theme

CONFIG = tomllib.loads(Path(".streamlit/config.toml").read_text())["theme"]


def test_the_dark_template_uses_the_dark_palette():
    t = plot_theme.template("dark")
    assert t.layout.paper_bgcolor.upper() == CONFIG["dark"]["backgroundColor"].upper()
    assert t.layout.font.color.upper() == CONFIG["dark"]["textColor"].upper()


def test_the_light_template_uses_the_light_palette():
    t = plot_theme.template("light")
    assert t.layout.paper_bgcolor.upper() == CONFIG["light"]["backgroundColor"].upper()


def test_an_unknown_theme_falls_back_to_dark():
    assert plot_theme.template(None).layout.paper_bgcolor == plot_theme.template("dark").layout.paper_bgcolor
```

Add to `tests/test_app_theme.py`:

```python
def test_dark_is_the_default_theme():
    cfg = tomllib.loads(Path(".streamlit/config.toml").read_text())
    assert cfg["theme"]["base"] == "dark"


def test_the_instrument_styles_are_defined_and_respect_reduced_motion():
    from app import theme

    for cls in (".sim-head", ".sim-label", ".tiles", ".tile-value", ".diag", ".pill", ".dot"):
        assert cls in theme.CSS, cls
    assert "prefers-reduced-motion" in theme.CSS
```

- [ ] **Step 2: Run them to see them fail**

Run: `timeout 300 uv run pytest tests/test_plot_theme.py tests/test_app_theme.py -x`
Expected: FAIL (`plot_theme` missing; no `base`).

- [ ] **Step 3: Make dark the default**

In `.streamlit/config.toml`, add as the first line under `[theme]`:

```toml
# Dark by default; the light palette below stays selectable in Streamlit's settings.
base = "dark"
```

- [ ] **Step 4: Create `app/plot_theme.py`**

```python
"""The Plotly template for figures drawn with `theme=None`.

Those figures opt out of Streamlit's own chart theme (it rewrites near-black
colours, which breaks the temperature scales), so they must be given the app's
colours explicitly. The viewer's theme comes from `st.context.theme.type`, which
Streamlit infers from the page background; it can be unknown on a session's
first run, and the app is dark by default, so unknown means dark.

The colours are read from `.streamlit/config.toml` rather than restated: that
file is where Streamlit takes them from, so the two cannot drift apart.
"""
from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

CONFIG = Path(".streamlit/config.toml")
FONT_FAMILY = "IBM Plex Sans, sans-serif"


@lru_cache(maxsize=1)
def _palettes() -> dict:
    return tomllib.loads(CONFIG.read_text())["theme"]


def template(theme_type: str | None) -> go.layout.Template:
    variant = "light" if theme_type == "light" else "dark"
    colours = _palettes()[variant]
    base = pio.templates["plotly_white" if variant == "light" else "plotly_dark"]
    out = go.layout.Template(base)
    out.layout.paper_bgcolor = colours["backgroundColor"]
    out.layout.plot_bgcolor = colours["backgroundColor"]
    out.layout.font = {"family": FONT_FAMILY, "color": colours["textColor"]}
    return out


def current() -> go.layout.Template:
    return template(getattr(st.context.theme, "type", None))
```

- [ ] **Step 5: Apply the template at every `theme=None` call site**

Run: `grep -n "theme=None" app/views/*.py`. At each hit, pass the template to the figure just
before it is drawn:
- `app/views/simulator.py`: `live_figure.figure(..., template=plot_theme.current())`.
- `app/views/fire_test.py` (twin canvas and cross-section), `app/views/design.py` (overview),
  `app/views/cfd.py`: `fig.update_layout(template=plot_theme.current())` on the figure object
  before `st.plotly_chart(...)` (assign the figure to a local first where it is built inline).

Add `from app import plot_theme` to each of those modules.

- [ ] **Step 6: Add the instrument styles to `app/theme.py`**

Append inside `CSS`, before `</style>` (no blank lines):

```css
.sim-head {{ font-family: "IBM Plex Mono", monospace; font-size: 0.85rem; letter-spacing: 0.18em;
            text-transform: uppercase; opacity: 0.9; margin: 0.2rem 0 0.8rem; }}
.sim-label {{ font-family: "IBM Plex Mono", monospace; font-size: 0.72rem; letter-spacing: 0.14em;
             text-transform: uppercase; opacity: 0.75; margin: 0.9rem 0 0.3rem; }}
.tiles {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr)); gap: 0.75rem;
         margin-bottom: 0.8rem; }}
.tile {{ border: 1px solid {GREY}55; border-radius: 0.5rem; padding: 0.7rem 0.9rem; }}
.tile-label {{ font-family: "IBM Plex Mono", monospace; font-size: 0.7rem; letter-spacing: 0.12em;
              text-transform: uppercase; opacity: 0.75; }}
.tile-value {{ font-size: 1.7rem; font-weight: 500; font-variant-numeric: tabular-nums; margin-top: 0.2rem; }}
.tile-note {{ font-size: 0.78rem; opacity: 0.7; }}
.diag {{ font-family: "IBM Plex Mono", monospace; font-size: 0.78rem; opacity: 0.85;
        display: flex; gap: 0.8rem; align-items: center; flex-wrap: wrap; margin-bottom: 0.4rem; }}
.pill {{ border: 1px solid {PRIMARY}; color: {PRIMARY}; border-radius: 999px; padding: 0.1rem 0.6rem;
        letter-spacing: 0.12em; white-space: nowrap; }}
.dot {{ display: inline-block; width: 0.5rem; height: 0.5rem; border-radius: 50%; background: {PRIMARY};
       margin-right: 0.4rem; animation: sim-pulse 1.6s ease-in-out infinite; }}
@keyframes sim-pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.25; }} }}
@media (prefers-reduced-motion: reduce) {{ .dot {{ animation: none; }} }}
```

- [ ] **Step 7: Document the screen in `README.md`**

Under `## Running the app`, add:

```markdown
The app opens on the **Simulator**: presets and design knobs in the sidebar, the run's peaks in
tiles, and one figure that replays the Tier 1 virtual fire test — press ▶ Play and six gauges,
a 3D tunnel and three charts move together. Every value is the engine's own; a gauge has a red
band only where the design's `ahj` block sets that criterion's limit. The **Wizard** keeps the
formal record (fire test, CFD, compliance, reports) and **CFD runs** manages the FDS fleet.
The app is dark by default; Streamlit's settings menu switches it to light.
```

- [ ] **Step 8: Run the tests**

Run: `timeout 600 uv run pytest tests/test_plot_theme.py tests/test_app_theme.py tests/test_app_wizard.py tests/test_app_simulator.py tests/test_independence.py -x`
Expected: PASS.

- [ ] **Step 9: Full suite**

Run: `PATH=$(echo "$PATH" | tr ':' '\n' | grep -v -i fds | paste -sd: -) timeout 900 uv run pytest`
Expected: all pass; paste the "N passed" line in the report.

- [ ] **Step 10: Commit**

```bash
git add .streamlit/config.toml app/theme.py app/plot_theme.py app/views/ tests/test_plot_theme.py tests/test_app_theme.py README.md
git commit -m "feat(app): dark by default, instrument styling, one plot template"
```

**Controller check after this task (browser):** open the app, confirm it starts dark, that
Streamlit's settings menu still offers Light and every screen reads on both, and that ▶ Play
runs smoothly. If `base = "dark"` removes the Light choice in Streamlit 1.64, remove the `base`
line (the app then follows the viewer's system theme) and update `test_dark_is_the_default_theme`
to assert the light and dark palettes instead — a spec deviation to record in the ledger.

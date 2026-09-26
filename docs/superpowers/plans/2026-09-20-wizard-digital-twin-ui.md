# Wizard + Digital-Twin UI Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the six independent Streamlit pages with a five-step wizard whose centrepiece is a to-scale, time-playing digital twin of the Annex 7 fire test, driven by Tier 1 instantly and overlaid with FDS slice data when a Tier 2 run exists — with state handed between steps automatically and no upload/download anywhere but the final exports.

**Architecture:** A stepper component owns navigation through `app/state.py`; each step is a view module whose `render()` auto-computes its prerequisite from session state. The twin is a set of pure Plotly layer functions (`app/components/twin_canvas.py`) that take engine dataclasses and return traces/shapes, composed into one animated figure. FDS slice files are parsed by a new engine module (`solit2/engines/fds/slices.py`) into arrays the same canvas draws as a heatmap layer. The correlation report's second run is an auto-built test-facility twin of the design (`solit2/reports/twin.py`). No physics, criteria, scoring or reader code changes.

**Tech Stack:** Python 3.12 via `uv`, Streamlit 1.64 (`st.fragment(run_every=…)`, `[theme.light]`/`[theme.dark]`, `st.button(width="stretch")`), Plotly, numpy, pandas. `streamlit.testing.v1.AppTest` for view tests.

**Spec:** `docs/superpowers/specs/2026-09-20-wizard-digital-twin-ui-design.md` — read it first; section numbers below refer to it.

## Global Constraints

- Every command is `uv run …`. Never the system Python.
- **No new dependencies.** `pyproject.toml`'s dependency list is not edited.
- INDEPENDENCE rules 1 and 2 (`INDEPENDENCE.md`): nothing under `solit2/` or `app/` names a project, vendor, product or machine-specific path; `tests/test_independence.py::test_no_file_in_the_package_names_a_vendor_or_a_project` must stay green. The UI never invents an acceptance limit.
- The verdict banner never reads `PASS` while `score["gates_failed"]` is non-empty, and always shows the `criteria_unset` count when it is non-zero (spec §4.2, CLAUDE.md).
- Files ≤ 400 lines target, 800 hard; functions ≤ 50 lines; nesting ≤ 4.
- Frozen dataclasses; layer functions are pure (no `st.*` calls inside `twin_canvas.py`, `slices.py`, `twin.py`).
- **Every Streamlit widget in `app/` has an explicit `key=`** — AppTest addresses widgets by key and the CSS targets `.st-key-<key>`.
- Copy: buttons say what happens ("Build & continue →", "Start FDS run (20 min)", "Open in Smokeview"); every number carries a unit.
- Theme tokens exactly as spec §9.1; semantic colours in CSS: pass `#2E8B57`, fail `#C4452B`, unset `#C98A1E`, mist/primary `#1D8F8A`, structure grey `#8A94A6`.
- Tests that append run history must redirect it: views call `history.append(result, history.DEFAULT_PATH)` / `history.leaderboard(history.DEFAULT_PATH, …)` so tests can `monkeypatch.setattr(history, "DEFAULT_PATH", tmp_path / "h.jsonl")`.
- Views never touch a hard-coded `runs/` path directly: `app/views/cfd.py` exposes `RUNS_DIR = Path("runs")` for tests to monkeypatch.
- Conventional commits; **no `Co-Authored-By` trailer** (user's global git rules). Stage files by explicit path — never `git add -A` / `git add .`.
- Run `uv run ruff check app solit2 tests` and `uv run pytest -q` before every commit; commit only on green.
- Test data: `examples/designs/road-tunnel-twin-bore.json` (`EXAMPLE_DESIGN` below). Tests never read or write the real `runs/` directory.

---

## File structure

| Path | Responsibility | Task |
|---|---|---|
| `.streamlit/config.toml` | theme tokens, both variants | 1 |
| `app/theme.py` | Google Fonts link + the one CSS block (stepper, verdict, chips, lamps) | 1 |
| `.claude/launch.json` | dev-server PATH incl. FDS + Smokeview dirs | 1 |
| `app/state.py` | typed session-state accessors incl. `step`, `twin_result`, `tier2_result` | 2 |
| `app/components/stepper.py` | step pills header + Back/Next footer | 2 |
| `solit2/engines/fds/slices.py` | `.smv`/`.sf` parsing, centreline stitching | 3 |
| `tests/fixtures/fds/sample_1_1.sf` | real 29 KB slice from an FDS run | 3 |
| `solit2/engines/fds/deck.py` | two more `&SLCF` lines | 4 |
| `solit2/engines/fds/runner.py` | `smokeview_binary()`, `open_smokeview()` | 4 |
| `solit2/reports/twin.py` | test-facility twin of a design | 5 |
| `app/components/twin_canvas.py` | pure layers, frames, figure | 6, 7 |
| `app/components/hmi.py` | clock/readouts/lamps strip | 8 |
| `app/components/timeline.py` | events strip + failed-criteria chips | 8 |
| `tests/app_helpers.py` | AppTest script builder shared by view tests | 9 |
| `app/views/design.py` | step 1: form + live summary card + Build & continue | 9 |
| `app/views/result.py` | step 2: verdict, chips, tables, leaderboard; `ensure_result()` | 10 |
| `app/views/fire_test.py` | step 3: HMI + twin canvas + timeline + station chart; `ensure_trace()` | 11 |
| `app/views/cfd.py` | step 4: pre-flight, duration, start, live progress, CFD canvas, Smokeview, Tier 1 vs 2 | 12 |
| `app/views/reports.py` | step 5: test plan, site vs twin, Tier 1 vs 2, exports | 13 |
| `app/streamlit_app.py` | shell: theme, stepper, view dispatch | 14 |
| `tests/test_app_wizard.py` | end-to-end AppTest on the real app | 14 |
| deleted: `app/views/run.py`, `tunnel.py`, `leaderboard.py`, `verify.py`, `tests/test_app_*_view.py` | | 14 |

`app/components/charts.py` (`criteria_table`, `timeseries_chart`) stays and is reused by the result view.

---

### Task 1: Theme, fonts and dev-server PATH

**Files:**
- Create: `.streamlit/config.toml`
- Create: `app/theme.py`
- Modify: `.claude/launch.json`
- Test: `tests/test_app_theme.py`

**Interfaces:**
- Produces: `app.theme.inject() -> None` (call once per script run, before any widget); CSS classes `verdict pass|fail`, `verdict-label`, `verdict-score`, `verdict-note`, `chip pass|fail|unset`, `lamps`, `lamp on`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_app_theme.py
"""The theme is configuration; these tests pin the contract the views rely on."""
import tomllib
from pathlib import Path

from streamlit.testing.v1 import AppTest

REQUIRED_TOKENS = {"primaryColor", "backgroundColor", "secondaryBackgroundColor",
                   "textColor", "borderColor", "redColor", "greenColor", "orangeColor"}


def test_theme_defines_light_and_dark_with_every_token():
    cfg = tomllib.loads(Path(".streamlit/config.toml").read_text())
    for variant in ("light", "dark"):
        assert REQUIRED_TOKENS <= set(cfg["theme"][variant]), variant
    assert cfg["theme"]["font"].startswith("IBM Plex Sans")
    assert cfg["theme"]["codeFont"].startswith("IBM Plex Mono")
    assert cfg["theme"]["light"]["primaryColor"] == "#1D8F8A"
    assert cfg["theme"]["dark"]["backgroundColor"] == "#1B2230"


def test_inject_renders_exactly_one_style_block():
    at = AppTest.from_string("from app import theme\ntheme.inject()\n")
    at.run()
    assert not at.exception
    assert sum("<style>" in m.value for m in at.markdown) == 1
    assert any("fonts.googleapis.com" in m.value for m in at.markdown)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_app_theme.py -q`
Expected: FAIL — `FileNotFoundError: .streamlit/config.toml` and `ModuleNotFoundError: app.theme`.

- [ ] **Step 3: Write the theme config**

```toml
# .streamlit/config.toml
[theme]
font = "IBM Plex Sans, sans-serif"
headingFont = "IBM Plex Sans, sans-serif"
codeFont = "IBM Plex Mono, monospace"
baseRadius = "0.375rem"
buttonRadius = "0.375rem"
metricValueFontSize = "1.6rem"
# Inferno, so Streamlit-native sequential charts match the twin's temperature scale.
chartSequentialColors = ["#000004", "#1B0C41", "#4A0C6B", "#781C6D", "#A52C60",
                         "#CF4446", "#ED6925", "#FB9B06", "#F7D13D", "#FCFFA4"]

[theme.light]
backgroundColor = "#F3F5F8"
secondaryBackgroundColor = "#E6EAF0"
textColor = "#1C2432"
primaryColor = "#1D8F8A"
borderColor = "#CBD3DE"
redColor = "#C4452B"
greenColor = "#2E8B57"
orangeColor = "#C98A1E"

[theme.dark]
backgroundColor = "#1B2230"
secondaryBackgroundColor = "#242D3D"
textColor = "#E4E9F0"
primaryColor = "#3FB8B0"
borderColor = "#34405A"
redColor = "#E0654A"
greenColor = "#4FB57C"
orangeColor = "#E0A73A"

[server]
headless = true
```

- [ ] **Step 4: Write `app/theme.py`**

```python
"""Fonts and the handful of CSS rules Streamlit's theme options cannot express.

Everything colour- and type-related that CAN live in `.streamlit/config.toml`
does; this block covers only the stepper pills, the verdict banner, status
chips and the HMI lamps. Semantic colours are repeated here as literals
because CSS cannot read the TOML tokens.
"""
from __future__ import annotations

import streamlit as st

PASS, FAIL, UNSET, PRIMARY, GREY = "#2E8B57", "#C4452B", "#C98A1E", "#1D8F8A", "#8A94A6"

FONT_LINK = (
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2'
    '?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500'
    '&display=swap">'
)

CSS = f"""
<style>
[class*="st-key-step_"] button {{ border-radius: 999px; font-weight: 500; }}
[class*="st-key-step_"] button:disabled {{ opacity: 0.45; }}

.verdict {{ display: flex; gap: 1.25rem; align-items: baseline; flex-wrap: wrap;
           padding: 0.9rem 1.2rem; border-radius: 0.5rem; margin-bottom: 1rem;
           border: 1px solid {GREY}55; }}
.verdict.pass {{ border-left: 6px solid {PASS}; }}
.verdict.fail {{ border-left: 6px solid {FAIL}; }}
.verdict-label {{ font-size: 1.8rem; font-weight: 600; letter-spacing: 0.04em; }}
.verdict.pass .verdict-label {{ color: {PASS}; }}
.verdict.fail .verdict-label {{ color: {FAIL}; }}
.verdict-score {{ font-family: "IBM Plex Mono", monospace; font-size: 1.2rem;
                 font-variant-numeric: tabular-nums; }}
.verdict-note {{ opacity: 0.8; }}

.chip {{ display: inline-block; padding: 0.15rem 0.6rem; border-radius: 999px;
        font-size: 0.8rem; margin: 0 0.3rem 0.3rem 0; border: 1px solid transparent; }}
.chip.pass {{ background: {PASS}26; color: {PASS}; border-color: {PASS}; }}
.chip.fail {{ background: {FAIL}26; color: {FAIL}; border-color: {FAIL}; }}
.chip.unset {{ background: {UNSET}26; color: {UNSET}; border-color: {UNSET}; }}

.lamps {{ display: flex; gap: 1.5rem; font-size: 0.9rem; margin: 0.3rem 0 1rem; }}
.lamp {{ display: inline-block; width: 0.8rem; height: 0.8rem; border-radius: 2px;
        margin-right: 0.4rem; vertical-align: middle; background: {GREY}; opacity: 0.4; }}
.lamp.on {{ background: {PASS}; opacity: 1; box-shadow: 0 0 6px {PASS}; }}
</style>
"""


def inject() -> None:
    """Emit the font link and the CSS once per script run."""
    st.markdown(FONT_LINK + CSS, unsafe_allow_html=True)
```

- [ ] **Step 5: Update `.claude/launch.json`**

Replace the `runtimeArgs` second element so the exported PATH also carries Smokeview:

```json
"export PATH=\"$HOME/FDS/native/bin:$HOME/FDS/FDS6/smvbin:/opt/homebrew/bin:$PATH\"; exec uv run streamlit run app/streamlit_app.py --server.headless true"
```

(The FDS path was already there uncommitted; this task commits both.)

- [ ] **Step 6: Run tests**

Run: `uv run pytest tests/test_app_theme.py -q`
Expected: 2 passed.

- [ ] **Step 7: Commit**

```bash
uv run ruff check app tests && git add .streamlit/config.toml app/theme.py .claude/launch.json tests/test_app_theme.py && git commit -m "feat(ui): theme tokens for light and dark, Plex fonts, launch PATH with Smokeview"
```

---

### Task 2: Wizard state and the stepper component

**Files:**
- Modify: `app/state.py`
- Create: `app/components/stepper.py`
- Test: `tests/test_app_stepper.py`

**Interfaces:**
- Produces (`app.state`): `STEP_MIN = 1`, `STEP_MAX = 5`, `get_step() -> int`, `set_step(step: int) -> None`, `get_twin_result() / set_twin_result(Result)`, `get_tier2_result() / set_tier2_result(Result)`; `set_design()` now also clears `twin_result` and `tier2_result`.
- Produces (`app.components.stepper`): `STEPS = ("Design", "Result", "Fire test", "CFD verify", "Reports")`, `reachable(step: int) -> bool`, `render_header() -> None`, `render_footer() -> None`. Widget keys: `step_1`…`step_5`, `nav_back`, `nav_next`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_app_stepper.py
"""Stepper navigation on a minimal script; the real app is exercised in test_app_wizard."""
from streamlit.testing.v1 import AppTest

from app import state

SCRIPT = """
import streamlit as st
from app import state
from app.components import stepper
from solit2.schema.design import Design
if st.session_state.get("_seed") and state.get_design() is None:
    state.set_design(Design.load("examples/designs/road-tunnel-twin-bore.json"))
stepper.render_header()
st.write(f"step={state.get_step()}")
stepper.render_footer()
"""


def _keys(at):
    return {b.key for b in at.button}


def test_without_a_design_only_step_one_is_enabled_and_there_is_no_back_button():
    at = AppTest.from_string(SCRIPT)
    at.run()
    assert not at.exception
    assert not at.button(key="step_1").disabled
    for i in range(2, 6):
        assert at.button(key=f"step_{i}").disabled, i
    assert "nav_back" not in _keys(at)
    assert at.button(key="nav_next").disabled


def test_with_a_design_next_back_and_jump_move_the_step():
    at = AppTest.from_string(SCRIPT)
    at.session_state["_seed"] = True
    at.run()
    assert all(not at.button(key=f"step_{i}").disabled for i in range(1, 6))
    at.button(key="nav_next").click().run()
    assert at.session_state["step"] == 2
    at.button(key="nav_back").click().run()
    assert at.session_state["step"] == 1
    at.button(key="step_5").click().run()
    assert at.session_state["step"] == 5
    assert "nav_next" not in _keys(at)


def test_set_design_invalidates_every_downstream_result(monkeypatch):
    fake = {"result": "r", "twin_result": "t", "tier2_result": "f"}
    monkeypatch.setattr(state.st, "session_state", fake)
    state.set_design("design")
    assert fake == {"design": "design"}


def test_set_step_clamps_to_the_wizard_range(monkeypatch):
    fake = {}
    monkeypatch.setattr(state.st, "session_state", fake)
    state.set_step(0)
    assert fake["step"] == state.STEP_MIN
    state.set_step(99)
    assert fake["step"] == state.STEP_MAX
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_app_stepper.py -q`
Expected: FAIL — `ModuleNotFoundError: app.components.stepper` / `AttributeError: set_step`.

- [ ] **Step 3: Extend `app/state.py`**

Replace the file's body below the docstring with:

```python
from __future__ import annotations

import streamlit as st

from solit2.schema.design import Design
from solit2.schema.result import Result

_DESIGN_KEY = "design"
_RESULT_KEY = "result"
_TWIN_KEY = "twin_result"
_TIER2_KEY = "tier2_result"
_STEP_KEY = "step"
STEP_MIN, STEP_MAX = 1, 5
_DERIVED_KEYS = (_RESULT_KEY, _TWIN_KEY, _TIER2_KEY)


def get_step() -> int:
    return int(st.session_state.get(_STEP_KEY, STEP_MIN))


def set_step(step: int) -> None:
    st.session_state[_STEP_KEY] = min(max(int(step), STEP_MIN), STEP_MAX)


def get_design() -> Design | None:
    return st.session_state.get(_DESIGN_KEY)


def set_design(design: Design) -> None:
    st.session_state[_DESIGN_KEY] = design
    # A new design invalidates everything computed from the old one.
    for key in _DERIVED_KEYS:
        st.session_state.pop(key, None)


def get_result() -> Result | None:
    return st.session_state.get(_RESULT_KEY)


def set_result(result: Result) -> None:
    st.session_state[_RESULT_KEY] = result


def get_twin_result() -> Result | None:
    return st.session_state.get(_TWIN_KEY)


def set_twin_result(result: Result) -> None:
    st.session_state[_TWIN_KEY] = result


def get_tier2_result() -> Result | None:
    return st.session_state.get(_TIER2_KEY)


def set_tier2_result(result: Result) -> None:
    st.session_state[_TIER2_KEY] = result
```

Update the module docstring's "two keys" sentence to "the keys in use — design, result, twin_result, tier2_result and step — are named in exactly one place."

- [ ] **Step 4: Write `app/components/stepper.py`**

```python
"""The wizard's navigation: five step pills on top, Back / Next underneath.

Reachability is deliberately simple: step 1 is always open and every other
step opens once a design exists, because each of them auto-computes what it
needs from the design (spec §3.3). The stepper never runs the engine itself.
"""
from __future__ import annotations

import streamlit as st

from app import state

STEPS = ("Design", "Result", "Fire test", "CFD verify", "Reports")


def reachable(step: int) -> bool:
    return step == state.STEP_MIN or state.get_design() is not None


def _go(step: int) -> None:
    state.set_step(step)
    st.rerun()


def render_header() -> None:
    current = state.get_step()
    for i, (col, label) in enumerate(zip(st.columns(len(STEPS)), STEPS), start=state.STEP_MIN):
        done = i < current and reachable(i)
        text = f"{'✓' if done else i}  {label}"
        kind = "primary" if i == current else "secondary"
        if col.button(text, key=f"step_{i}", type=kind, disabled=not reachable(i),
                      width="stretch"):
            _go(i)


def render_footer() -> None:
    current = state.get_step()
    st.divider()
    back, _, nxt = st.columns([1, 4, 1])
    if current > state.STEP_MIN and back.button("← Back", key="nav_back", width="stretch"):
        _go(current - 1)
    if current < state.STEP_MAX and nxt.button(
            "Next →", key="nav_next", type="primary", width="stretch",
            disabled=not reachable(current + 1)):
        _go(current + 1)
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_app_stepper.py -q`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
uv run ruff check app tests && git add app/state.py app/components/stepper.py tests/test_app_stepper.py && git commit -m "feat(ui): wizard step state and stepper header/footer"
```

---

### Task 3: FDS slice reader (`slices.py`)

**Files:**
- Create: `solit2/engines/fds/slices.py`
- Create: `tests/fixtures/fds/sample_1_1.sf` (copy of `runs/dcfb87012b57/dcfb87012b57_1_1.sf`)
- Test: `tests/test_fds_slices.py`

**Interfaces:**
- Produces: `SliceMeta`, `MeshGrid`, `Slice(quantity: str, unit: str, x_m: np.ndarray, z_m: np.ndarray, t_s: np.ndarray, frames: np.ndarray)` with `frames.shape == (len(t_s), len(z_m), len(x_m))`; `read_sf(path) -> tuple[tuple[str, str, str], tuple[int, ...], np.ndarray, np.ndarray]` (header, bounds, times, frames `[t, k, j, i]`); `read_smv(path) -> tuple[list[SliceMeta], dict[int, MeshGrid]]`; `load_centreline(run_dir: Path, quantity: str) -> Slice | None`.

- [ ] **Step 1: Copy the real fixture**

```bash
cp runs/dcfb87012b57/dcfb87012b57_1_1.sf tests/fixtures/fds/sample_1_1.sf
```

(`.gitignore` already whitelists `tests/fixtures/fds/**`.)

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_fds_slices.py
"""Slice parsing on synthetic files with known values, and on one real FDS file."""
import struct
from pathlib import Path

import numpy as np
import pytest

from solit2.engines.fds import slices

FIXTURE = Path("tests/fixtures/fds/sample_1_1.sf")


def _rec(payload: bytes) -> bytes:
    return struct.pack("<i", len(payload)) + payload + struct.pack("<i", len(payload))


def _write_sf(path: Path, header, bounds, times, frames) -> None:
    """frames: list of arrays shaped (nk, nj, ni), written in FDS's Fortran order."""
    out = b"".join(_rec(h.ljust(30).encode()) for h in header)
    out += _rec(struct.pack("<6i", *bounds))
    for t, f in zip(times, frames):
        out += _rec(struct.pack("<f", t)) + _rec(np.asarray(f, dtype="<f4").tobytes())
    path.write_bytes(out)


def _write_smv(path: Path, chid: str) -> None:
    """Two meshes side by side on x: nodes 0,1,2 and 2,3,4; y nodes -1,0,1; z nodes 0,1,2."""
    def mesh(n, xs):
        lines = [f"GRID   MESH_{n:07d}", "   2   2   2   0   0   0   0   0   0", "",
                 "TRNX", "    0"] + [f"    {i}   {x:.5f}" for i, x in enumerate(xs)] + [
                 "TRNY", "    0", "    0  -1.00000", "    1   0.00000", "    2   1.00000",
                 "TRNZ", "    0", "    0   0.00000", "    1   1.00000", "    2   2.00000", ""]
        return lines
    slcf = []
    for n in (1, 2):
        slcf += [f"SLCF     {n} # STRUCTURED &     0     2     1     1     0     2 !      1      0      2",
                 f" {chid}_{n}_1.sf", " TEMPERATURE", " temp", " C"]
    path.write_text("\n".join(mesh(1, [0.0, 1.0, 2.0]) + mesh(2, [2.0, 3.0, 4.0]) + slcf) + "\n")


def _frame(xs, scale=1.0):
    # value = 10*k + x, so every stitched cell is checkable
    return np.array([[[10 * k + x for x in xs] for _ in range(3)] for k in range(3)]) * scale


@pytest.fixture
def run_dir(tmp_path):
    _write_smv(tmp_path / "case.smv", "case")
    bounds = (0, 2, 1, 1, 0, 2)
    _write_sf(tmp_path / "case_1_1.sf", ("TEMPERATURE", "temp", "C"), bounds,
              [0.0, 5.0], [_frame([0, 1, 2]), _frame([0, 1, 2], 2.0)])
    _write_sf(tmp_path / "case_2_1.sf", ("TEMPERATURE", "temp", "C"), bounds,
              [0.0, 5.0, 10.0], [_frame([2, 3, 4]), _frame([2, 3, 4], 2.0), _frame([2, 3, 4], 3.0)])
    return tmp_path


def test_read_sf_parses_the_real_fixture():
    header, bounds, times, frames = slices.read_sf(FIXTURE)
    assert header == ("TEMPERATURE", "temp", "C")
    assert bounds == (0, 200, 4, 4, 0, 5)
    assert len(times) == 6 and times[-1] == pytest.approx(18.0)
    assert frames.shape == (6, 6, 1, 201)


def test_read_sf_stops_at_a_truncated_record(tmp_path):
    src = FIXTURE.read_bytes()
    cut = tmp_path / "cut.sf"
    cut.write_bytes(src[:-100])
    _, _, times, frames = slices.read_sf(cut)
    assert len(times) == 5 and frames.shape[0] == 5


def test_read_smv_lists_slices_and_grids(run_dir):
    metas, grids = slices.read_smv(run_dir / "case.smv")
    assert [m.mesh for m in metas] == [1, 2]
    assert metas[0].quantity == "TEMPERATURE" and metas[0].unit == "C"
    assert (metas[0].i1, metas[0].i2, metas[0].j1, metas[0].j2) == (0, 2, 1, 1)
    assert grids[2].x_m == (2.0, 3.0, 4.0) and grids[1].z_m == (0.0, 1.0, 2.0)


def test_load_centreline_stitches_meshes_in_x_and_trims_to_the_common_time(run_dir):
    sl = slices.load_centreline(run_dir, "TEMPERATURE")
    assert sl is not None and sl.unit == "C"
    assert list(sl.x_m) == [0.0, 1.0, 2.0, 3.0, 4.0]       # shared node at x=2 kept once
    assert list(sl.z_m) == [0.0, 1.0, 2.0]
    assert list(sl.t_s) == [0.0, 5.0]                     # mesh 1 has two frames; mesh 2 three
    assert sl.frames.shape == (2, 3, 5)
    assert sl.frames[0, 2, :].tolist() == [20.0, 21.0, 22.0, 23.0, 24.0]
    assert sl.frames[1, 0, 4] == pytest.approx(8.0)       # frame 2 is scaled by 2: (0*10+4)*2


def test_load_centreline_is_none_when_nothing_matches(run_dir, tmp_path):
    assert slices.load_centreline(run_dir, "SOOT DENSITY") is None
    assert slices.load_centreline(tmp_path / "empty", "TEMPERATURE") is None
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_fds_slices.py -q`
Expected: FAIL — `ImportError: cannot import name 'slices'`.

- [ ] **Step 4: Write `solit2/engines/fds/slices.py`**

```python
"""Read FDS slice output (`.sf`) and the mesh geometry Smokeview lists (`.smv`).

FDS writes one slice file per (mesh, `&SLCF` line) as Fortran sequential
unformatted records: a 4-byte little-endian record length, the payload, the
same 4 bytes again. Three 30-character header records (quantity, short name,
unit), one record of six int32 node bounds (i1 i2 j1 j2 k1 k2), then for every
output time a one-float32 record (time) and one record of
(i2-i1+1)(j2-j1+1)(k2-k1+1) float32 in Fortran order (i fastest). FDS appends
while it runs, so the final record may be incomplete: readers stop there and
return the complete frames.

The `.smv` file is text. Per mesh: `GRID <name>` then `ibar jbar kbar ...`,
then `TRNX`/`TRNY`/`TRNZ` blocks (a count of extra lines to skip, then
`index coordinate` for every node). Each `&SLCF` appears as
`SLCF <mesh> # STRUCTURED & i1 i2 j1 j2 k1 k2 ! ...` followed by four indented
lines: file name, quantity, short name, unit.
"""
from __future__ import annotations

import struct
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import numpy as np

_HEADER_RECORDS = 3
_MARKER = struct.Struct("<i")
_BOUNDS = struct.Struct("<6i")
_TIME = struct.Struct("<f")
_AXES = "xyz"


@dataclass(frozen=True)
class SliceMeta:
    mesh: int
    path: Path
    quantity: str
    short: str
    unit: str
    i1: int
    i2: int
    j1: int
    j2: int
    k1: int
    k2: int


@dataclass(frozen=True)
class MeshGrid:
    mesh: int
    x_m: tuple[float, ...]
    y_m: tuple[float, ...]
    z_m: tuple[float, ...]


@dataclass(frozen=True)
class Slice:
    quantity: str
    unit: str
    x_m: np.ndarray
    z_m: np.ndarray
    t_s: np.ndarray
    frames: np.ndarray  # [t, z, x]


def _records(data: bytes) -> Iterator[bytes]:
    """Yield complete Fortran records; stop at the first truncated one."""
    pos, n = 0, len(data)
    while pos + _MARKER.size <= n:
        (length,) = _MARKER.unpack_from(data, pos)
        end = pos + _MARKER.size + length + _MARKER.size
        if length < 0 or end > n:
            return
        yield data[pos + _MARKER.size:pos + _MARKER.size + length]
        pos = end


def read_sf(path: Path) -> tuple[tuple[str, str, str], tuple[int, ...], np.ndarray, np.ndarray]:
    recs = _records(Path(path).read_bytes())
    try:
        header = tuple(next(recs).decode("ascii", "replace").strip() for _ in range(_HEADER_RECORDS))
        bounds = _BOUNDS.unpack(next(recs))
    except (StopIteration, struct.error) as exc:
        raise ValueError(f"{path}: slice header is incomplete") from exc
    ni, nj, nk = (bounds[1] - bounds[0] + 1, bounds[3] - bounds[2] + 1, bounds[5] - bounds[4] + 1)
    times: list[float] = []
    frames: list[np.ndarray] = []
    for rec in recs:
        payload = next(recs, None)
        if len(rec) != _TIME.size or payload is None or len(payload) != 4 * ni * nj * nk:
            break
        times.append(_TIME.unpack(rec)[0])
        frames.append(np.frombuffer(payload, dtype="<f4").reshape(nk, nj, ni))
    stacked = np.stack(frames) if frames else np.empty((0, nk, nj, ni), dtype=np.float32)
    return header, bounds, np.asarray(times, dtype=np.float32), stacked


def _read_trn(lines: list[str], start: int, count: int) -> tuple[tuple[float, ...], int]:
    """A TRN* block: skip-count line, that many lines, then `count` node lines."""
    skip = int(lines[start + 1])
    first = start + 2 + skip
    coords = tuple(float(lines[k].split()[1]) for k in range(first, first + count))
    return coords, first + count


def read_smv(path: Path) -> tuple[list[SliceMeta], dict[int, MeshGrid]]:
    lines = Path(path).read_text().splitlines()
    metas: list[SliceMeta] = []
    dims: dict[int, tuple[int, int, int]] = {}
    axes: dict[int, dict[str, tuple[float, ...]]] = {}
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("GRID"):
            mesh = len(dims) + 1  # meshes are listed in order
            ibar, jbar, kbar = (int(v) for v in lines[i + 1].split()[:3])
            dims[mesh] = (ibar, jbar, kbar)
            i += 2
        elif line.startswith(("TRNX", "TRNY", "TRNZ")):
            mesh, axis = len(dims), line[3].lower()
            coords, i = _read_trn(lines, i, dims[mesh][_AXES.index(axis)] + 1)
            axes.setdefault(mesh, {})[axis] = coords
        elif line.startswith("SLCF"):
            head = line.split()
            b = [int(v) for v in head[head.index("&") + 1:head.index("&") + 7]]
            metas.append(SliceMeta(int(head[1]), Path(path).parent / lines[i + 1].strip(),
                                   lines[i + 2].strip(), lines[i + 3].strip(),
                                   lines[i + 4].strip(), *b))
            i += 5
        else:
            i += 1
    grids = {m: MeshGrid(m, a["x"], a["y"], a["z"]) for m, a in axes.items()}
    return metas, grids


def _part(meta: SliceMeta, grid: MeshGrid):
    header, _, t, frames = read_sf(meta.path)
    if len(t) == 0:
        return None
    x = np.asarray(grid.x_m[meta.i1:meta.i2 + 1])
    z = np.asarray(grid.z_m[meta.k1:meta.k2 + 1])
    return x, z, t, frames[:, :, 0, :], header[2]


def load_centreline(run_dir: Path, quantity: str) -> Slice | None:
    """Every constant-y slice of `quantity`, stitched along x at the common frame count."""
    smv = next(iter(sorted(Path(run_dir).glob("*.smv"))), None) if Path(run_dir).exists() else None
    if smv is None:
        return None
    metas, grids = read_smv(smv)
    wanted = [m for m in metas if m.quantity == quantity and m.j1 == m.j2 and m.path.exists()]
    parts = [p for p in (_part(m, grids[m.mesh]) for m in wanted) if p is not None]
    if not parts:
        return None
    parts.sort(key=lambda p: float(p[0][0]))
    n = min(len(p[2]) for p in parts)
    z = parts[0][1]
    xs, blocks = [parts[0][0]], [parts[0][3][:n]]
    for x, z_i, _, frames, _ in parts[1:]:
        if len(z_i) != len(z):
            raise ValueError("meshes on the centreline do not share a z grid")
        drop = 1 if np.isclose(x[0], xs[-1][-1]) else 0   # shared boundary node
        xs.append(x[drop:])
        blocks.append(frames[:n, :, drop:])
    return Slice(quantity, parts[0][4], np.concatenate(xs), z, parts[0][2][:n],
                 np.concatenate(blocks, axis=2))
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_fds_slices.py -q`
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
uv run ruff check solit2 tests && git add solit2/engines/fds/slices.py tests/test_fds_slices.py tests/fixtures/fds/sample_1_1.sf && git commit -m "feat(fds): read .smv geometry and .sf slices into stitched centreline arrays"
```

---

### Task 4: Smoke and mist slices in the deck; Smokeview launch in the runner

**Files:**
- Modify: `solit2/engines/fds/deck.py` (`_output()`)
- Modify: `solit2/engines/fds/runner.py`
- Test: `tests/test_fds_deck.py`, `tests/test_fds_runner.py`

**Interfaces:**
- Produces (`runner`): `SMV_ENV = "SOLIT2_SMV_BIN"`, `smokeview_binary() -> str | None`, `open_smokeview(run_dir: Path) -> None` (raises `FileNotFoundError`).

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_fds_deck.py` (use the names that file already imports the deck module and `Design` under — check its head first):

```python
def test_output_carries_centreline_slices_for_temperature_smoke_and_mist():
    text = deck.generate(Design.load("examples/designs/road-tunnel-twin-bore.json"))
    assert "&SLCF PBY=0.0, QUANTITY='TEMPERATURE' /" in text
    assert "&SLCF PBY=0.0, QUANTITY='SOOT DENSITY' /" in text
    assert "&SLCF PBY=0.0, QUANTITY='MPUV', PART_ID='FINE' /" in text
```

Append to `tests/test_fds_runner.py` (match its existing import of the runner module; add `import pytest` if absent):

```python
def test_smokeview_binary_prefers_the_env_var_then_path(monkeypatch, tmp_path):
    fake = tmp_path / "smokeview"
    fake.write_text("")
    monkeypatch.setenv(runner.SMV_ENV, str(fake))
    assert runner.smokeview_binary() == str(fake)
    monkeypatch.delenv(runner.SMV_ENV)
    monkeypatch.setattr(runner.shutil, "which",
                        lambda name: "/usr/bin/smv" if name == "smokeview" else None)
    assert runner.smokeview_binary() == "/usr/bin/smv"


def test_open_smokeview_launches_on_the_run_dirs_smv(monkeypatch, tmp_path):
    (tmp_path / "abc.smv").write_text("")
    monkeypatch.setattr(runner, "smokeview_binary", lambda: "/usr/bin/smv")
    calls = []
    monkeypatch.setattr(runner.subprocess, "Popen", lambda *a, **kw: calls.append((a, kw)))
    runner.open_smokeview(tmp_path)
    (args,), kw = calls[0]
    assert args == ["/usr/bin/smv", "abc.smv"] and kw["cwd"] == tmp_path


def test_open_smokeview_names_what_is_missing(monkeypatch, tmp_path):
    monkeypatch.setattr(runner, "smokeview_binary", lambda: None)
    with pytest.raises(FileNotFoundError, match="smokeview"):
        runner.open_smokeview(tmp_path)
    monkeypatch.setattr(runner, "smokeview_binary", lambda: "/usr/bin/smv")
    with pytest.raises(FileNotFoundError, match=r"\.smv"):
        runner.open_smokeview(tmp_path)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_fds_deck.py tests/test_fds_runner.py -q`
Expected: 4 new failures (`SOOT DENSITY` missing; `AttributeError: SMV_ENV`).

- [ ] **Step 3: Extend `_output()` in `deck.py`**

```python
def _output() -> list[str]:
    # Four centreline slices feed the twin canvas: gas temperature and axial
    # velocity as before, soot density for the smoke layer, and the water mass
    # per unit volume of the FINE particle class for the mist layer.
    return [f"&DUMP DT_DEVC={DEVC_DT_S:.1f}, DT_HRR={DEVC_DT_S:.1f} /",
            "&SLCF PBY=0.0, QUANTITY='TEMPERATURE' /",
            "&SLCF PBY=0.0, QUANTITY='U-VELOCITY' /",
            "&SLCF PBY=0.0, QUANTITY='SOOT DENSITY' /",
            "&SLCF PBY=0.0, QUANTITY='MPUV', PART_ID='FINE' /", ""]
```

- [ ] **Step 4: Add Smokeview helpers to `runner.py`**

Below `BIN_ENV`/`REMOTE_ENV`:

```python
SMV_ENV = "SOLIT2_SMV_BIN"
```

At the end of the module:

```python
def smokeview_binary() -> str | None:
    """`$SOLIT2_SMV_BIN` if it points at a file, else `smokeview` on PATH."""
    explicit = os.environ.get(SMV_ENV)
    if explicit and Path(explicit).exists():
        return explicit
    return shutil.which("smokeview")


def open_smokeview(run_dir: Path) -> None:
    """Open the run's `.smv` in the desktop Smokeview, detached.

    Smokeview is a GL desktop application; it is launched beside the app, not
    embedded in it. Raises `FileNotFoundError` naming the missing piece.
    """
    binary = smokeview_binary()
    if binary is None:
        raise FileNotFoundError(f"no smokeview binary on PATH and {SMV_ENV} is not set")
    smv = sorted(Path(run_dir).glob("*.smv"))
    if not smv:
        raise FileNotFoundError(f"no .smv file in {run_dir} yet")
    subprocess.Popen([binary, smv[0].name], cwd=Path(run_dir), start_new_session=True)
```

- [ ] **Step 5: Run the whole FDS test set**

Run: `uv run pytest tests/test_fds_deck.py tests/test_fds_runner.py tests/test_fds_reader.py tests/test_cli.py -q`
Expected: all pass. If an existing deck test asserts the exact old `_output()` list, update it to include the two new lines.

- [ ] **Step 6: Prove FDS accepts both quantities (only if `fds` is on PATH)**

```bash
D=/private/tmp/claude-501/-Users-sajil-Solit2-simulator/ad578238-7861-48dd-911d-b39ed3859aa2/scratchpad/slcf-smoke && mkdir -p $D && uv run solit2 fds-deck examples/designs/road-tunnel-twin-bore.json --dx 1.2 --minutes 0.25 --out $D/deck.fds >/dev/null && cd $D && mpiexec -np $(grep -c '^&MESH' deck.fds) fds deck.fds > run.out 2>&1; grep -c "ERROR" *.out; ls *_3.sf *_4.sf 2>/dev/null | head -3; grep -m1 "STOP" *.out
```

Expected: `0` errors, slice files `_<mesh>_3.sf` and `_<mesh>_4.sf` present, `STOP: FDS completed successfully`. If `fds` is not on PATH, record "not checked against a live FDS" in the task report and move on — the deck tests still gate the change.

- [ ] **Step 7: Commit**

```bash
uv run ruff check solit2 tests && git add solit2/engines/fds/deck.py solit2/engines/fds/runner.py tests/test_fds_deck.py tests/test_fds_runner.py && git commit -m "feat(fds): soot and water-mass centreline slices; launch Smokeview on a run"
```

---

### Task 5: Test-facility twin (`solit2/reports/twin.py`)

**Files:**
- Create: `solit2/reports/twin.py`
- Test: `tests/test_twin.py`

**Interfaces:**
- Consumes: `solit2.schema.presets.load_preset(kind, name) -> dict`, `Design.from_dict(raw)`.
- Produces: `GALLERY_TUNNEL = "solit2_test"`, `REFERENCE_NOZZLE = "solit2_reference"`, `gallery_mount_height_m(design: Design) -> tuple[float, str]` (height, one-sentence reason), `test_facility_twin(design: Design) -> Design`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_twin.py
"""The twin keeps the system under test and swaps everything else for the Annex 7 gallery."""
import json

import pytest

from solit2.engines.reduced import envelope
from solit2.reports import twin
from solit2.schema.design import Design

EXAMPLE = "examples/designs/road-tunnel-twin-bore.json"


def _design_with_mount(height_m: float) -> Design:
    raw = json.loads(open(EXAMPLE).read())
    raw["nozzles"]["mounting"] = {**raw["nozzles"].get("mounting", {}),
                                  "height_above_carriageway_m": height_m}
    return Design.from_dict(raw)


def _without_mount(block: dict) -> dict:
    return {k: v for k, v in block.items() if k != "mounting"}


def test_twin_keeps_nozzles_and_hydraulics_and_swaps_in_the_gallery_protocol():
    site = _design_with_mount(4.5)
    t = twin.test_facility_twin(site)
    assert t.tunnel.preset == twin.GALLERY_TUNNEL and t.tunnel.section == "test"
    assert t.fire.covered is True and t.fire.preset == site.fire.preset
    assert t.ventilation.velocity_range_ms == (1.5, 3.0) or list(t.ventilation.velocity_range_ms) == [1.5, 3.0]
    assert (t.zones.section_length_m, t.zones.sections_simultaneous, t.zones.duration_min) == (20.0, 3, 35.0)
    assert t.detection.sensor_spacing_m == 12.0
    assert _without_mount(t.nozzles.model_dump(mode="json", by_alias=True)) == \
        _without_mount(site.nozzles.model_dump(mode="json", by_alias=True))
    assert t.hydraulics.model_dump(mode="json") == site.hydraulics.model_dump(mode="json")
    assert t.ahj.model_dump(mode="json") == site.ahj.model_dump(mode="json")
    assert t.meta.name == f"{site.meta.name}-test-facility"


def test_a_site_height_that_fits_the_gallery_is_kept():
    height, reason = twin.gallery_mount_height_m(_design_with_mount(4.5))
    assert height == 4.5 and "site's own" in reason


def test_a_site_height_above_the_gallery_ceiling_falls_back_to_the_reference_tests():
    site = _design_with_mount(6.5)
    height, reason = twin.gallery_mount_height_m(site)
    assert height == 4.9 and "reference" in reason
    t = twin.test_facility_twin(site)
    assert t.nozzles.mounting.height_above_carriageway_m == 4.9
    assert "4.90 m" in t.meta.notes and "6.50 m" in t.meta.notes


def test_the_twin_validates_and_runs_in_tier_one():
    result = envelope.run(twin.test_facility_twin(_design_with_mount(6.5)))
    assert result.meta["design_name"].endswith("-test-facility")
    assert result.worst_case["velocity_ms"] in (1.5, 3.0)


def test_an_impossible_gallery_raises_instead_of_clamping(monkeypatch):
    # a fuel taller than the reference mounting height leaves no valid height
    site = _design_with_mount(6.5)
    monkeypatch.setattr(twin, "load_preset", lambda kind, name: (
        {"height_m": 5.2} if kind == "tunnel" else {"mounting": {"height_above_carriageway_m": 3.5}}))
    with pytest.raises(ValueError, match="gallery"):
        twin.gallery_mount_height_m(site)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_twin.py -q`
Expected: FAIL — `ImportError: cannot import name 'twin'`.

- [ ] **Step 3: Write `solit2/reports/twin.py`**

```python
"""The test-facility twin: one design's nozzle system, as Annex 7 would test it.

Annex 7 tests the fixed fire-fighting system in the SOLIT2 gallery, then §3.3
governs transferring the result to the site. The twin is therefore the SITE's
`nozzles` and `hydraulics` blocks — the thing being assessed — dropped into
the gallery's tunnel, fire, ventilation, zoning and detection as the protocol
prescribes. `ahj` travels unchanged: acceptance limits belong to the project,
not to the tunnel they are measured in. Site constraints do not apply in the
gallery and are dropped.
"""
from __future__ import annotations

from solit2.schema.design import Design
from solit2.schema.presets import load_preset

GALLERY_TUNNEL = "solit2_test"
REFERENCE_NOZZLE = "solit2_reference"
# Annex 7 test protocol, as examples/designs/solit2-test-protocol.json encodes it.
PROTOCOL_ZONES = {"section_length_m": 20.0, "sections_simultaneous": 3,
                  "activation_delay_s": 60.0, "pump_ramp_s": 30.0, "duration_min": 35.0}
PROTOCOL_VENTILATION = {"mode": "longitudinal", "velocity_range_ms": [1.5, 3.0]}  # §5.2.7
PROTOCOL_DETECTION = {"type": "linear_heat", "threshold_c": 60.0, "sensor_spacing_m": 12.0}


def gallery_mount_height_m(design: Design) -> tuple[float, str]:
    """Where the heads go in the gallery, and the one-sentence reason why.

    The site's own height when it fits between the fuel top and the gallery
    ceiling — the system is tested as it will be installed. Otherwise the
    height the SOLIT2 reference tests used in this same gallery, which is a
    fact about the standard's facility, not a vendor figure.
    """
    gallery_m = float(load_preset("tunnel", GALLERY_TUNNEL)["height_m"])
    site_m = design.nozzles.mounting.height_above_carriageway_m
    fuel_top_m = design.fire.footprint.top_height_m
    if fuel_top_m < site_m < gallery_m:
        return site_m, (f"heads at the site's own {site_m:.2f} m, which fits under the "
                        f"{gallery_m:.2f} m gallery ceiling")
    ref_m = float(load_preset("nozzle", REFERENCE_NOZZLE)["mounting"]["height_above_carriageway_m"])
    if not fuel_top_m < ref_m < gallery_m:
        raise ValueError(
            f"nozzle mounting cannot be reproduced in the {gallery_m:.2f} m test gallery: "
            f"the site's {site_m:.2f} m and the reference tests' {ref_m:.2f} m both fall "
            f"outside the {fuel_top_m:.2f} m fuel top to ceiling range")
    return ref_m, (f"heads at {ref_m:.2f} m, where the SOLIT2 reference tests mounted theirs: "
                   f"the site's {site_m:.2f} m does not fit between the {fuel_top_m:.2f} m "
                   f"fuel top and the {gallery_m:.2f} m gallery ceiling")


def test_facility_twin(design: Design) -> Design:
    height_m, reason = gallery_mount_height_m(design)
    nozzles = design.nozzles.model_dump(mode="json", by_alias=True)
    nozzles = {**nozzles, "mounting": {**nozzles["mounting"],
                                       "height_above_carriageway_m": height_m}}
    raw = {
        "meta": {"name": f"{design.meta.name}-test-facility",
                 "notes": (f"Test-facility twin of {design.meta.name}: the site's nozzle and "
                           f"hydraulics blocks in the SOLIT2 Annex 7 gallery. Heads {reason}.")},
        "tunnel": {"preset": GALLERY_TUNNEL, "section": "test"},
        "fire": {**design.fire.model_dump(mode="json", by_alias=True), "covered": True},
        "nozzles": nozzles,
        "hydraulics": design.hydraulics.model_dump(mode="json", by_alias=True),
        "zones": dict(PROTOCOL_ZONES),
        "ventilation": dict(PROTOCOL_VENTILATION),
        "detection": dict(PROTOCOL_DETECTION),
        "ahj": design.ahj.model_dump(mode="json", by_alias=True),
        "constraints": {},
    }
    return Design.from_dict(raw)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_twin.py tests/test_independence.py -q`
Expected: all pass (the independence scan confirms no banned term entered `solit2/`).

- [ ] **Step 5: Commit**

```bash
uv run ruff check solit2 tests && git add solit2/reports/twin.py tests/test_twin.py && git commit -m "feat(reports): build the test-facility twin of a design for correlation"
```

---

### Task 6: Twin canvas — structure, instrument, fire and mist layers

**Files:**
- Create: `app/components/twin_canvas.py`
- Test: `tests/test_twin_canvas.py`

**Interfaces:**
- Consumes: `solit2.engines.reduced.geometry.section_geometry(design) -> SectionGeometry`, `nozzle_positions(design, geom, fire_x_m) -> tuple[NozzlePosition, ...]` (`.x_m .y_m .z_m`), `solit2.engines.reduced.criteria.STATIONS: dict[str, float]`, `INSTRUMENTS: dict[str, Instruments]` (`.heat_flux: bool`, `.visibility: bool`, `.carbon_monoxide: int`), `StepRecord` (`t_s hrr_mw hrr_free_mw ceiling_temp_c u_eff_ms u_critical_ms backlayer_m water_lpm mist.chi_cool mist.tau_mist stations[name]`), `StationSample` (`temps_c heights_m flux_kwm2 visibility_m co_ppm`), `solit2.engines.fds.deck.WINDOW_M`, `CORE_M`.
- Produces: `Layer = tuple[list, list[dict]]`; constants `TEMP_SCALE = "Inferno"`, `TEMP_MIN_C = 20.0`, `BREATHING_HEIGHT_M = 1.8`, `TWIN_FRAME_STRIDE_S = 30.0`, `BACKLAYER_MIN_M = 1.0`; `temp_max_c(trace) -> float`; `tunnel_layer(design, geom, window_m, step, target_ignited=False) -> Layer` (3 traces), `instrument_layer(design, geom, step, window_m, cmax_c) -> Layer` (3 traces), `fire_layer(design, geom, step, cmax_c) -> Layer` (1 trace), `mist_layer(design, geom, step) -> Layer` (always exactly 1 trace; 0 or 1 shape). Trace counts are constant so frames can address them by index (Task 7).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_twin_canvas.py
"""Layer functions are pure: every assertion here is on traces/shapes, no browser."""
import plotly.graph_objects as go
import pytest

from app.components import twin_canvas as tc
from solit2.engines.reduced.criteria import STATIONS
from solit2.engines.reduced.geometry import nozzle_positions, section_geometry
from solit2.engines.reduced.sim import run_once
from solit2.schema.design import Design

EXAMPLE = "examples/designs/road-tunnel-twin-bore.json"


@pytest.fixture(scope="module")
def design():
    return Design.load(EXAMPLE)


@pytest.fixture(scope="module")
def trace(design):
    return run_once(design, design.tunnel.section, design.ventilation.velocity_range_ms[0])


@pytest.fixture(scope="module")
def geom(design):
    return section_geometry(design)


def _wet_step(trace):
    return next(s for s in trace.steps if s.water_lpm > 0)


def _shapes_of_type(shapes, kind):
    return [s for s in shapes if s["type"] == kind]


def test_tunnel_layer_places_mock_up_target_and_every_head(design, geom, trace):
    step = trace.steps[0]
    traces, shapes = tc.tunnel_layer(design, geom, tc.WINDOW_M, step)
    rects = _shapes_of_type(shapes, "rect")
    fp = design.fire.footprint
    assert (rects[0]["x0"], rects[0]["x1"]) == (-fp.length_m / 2, fp.length_m / 2)
    assert rects[1]["x0"] == pytest.approx(design.fire.target_x_m)
    heads = traces[0]
    assert len(heads.x) == len(nozzle_positions(design, geom, 0.0))
    assert len(traces) == 3


def test_tunnel_layer_fills_the_target_red_only_when_it_ignited(design, geom, trace):
    step = trace.steps[0]
    _, plain = tc.tunnel_layer(design, geom, tc.WINDOW_M, step)
    _, lit = tc.tunnel_layer(design, geom, tc.WINDOW_M, step, target_ignited=True)
    assert _shapes_of_type(plain, "rect")[1]["fillcolor"] == "rgba(0,0,0,0)"
    assert "196,69,43" in _shapes_of_type(lit, "rect")[1]["fillcolor"]


def test_nozzle_heads_light_up_when_water_flows(design, geom, trace):
    idle, _ = tc.tunnel_layer(design, geom, tc.WINDOW_M, trace.steps[0])
    wet, _ = tc.tunnel_layer(design, geom, tc.WINDOW_M, _wet_step(trace))
    assert idle[0].marker.color != wet[0].marker.color
    assert wet[0].marker.color == tc.MIST_COLOUR


def test_instrument_layer_has_one_mast_per_station_and_one_dot_per_thermocouple(design, geom, trace):
    step = trace.steps[len(trace.steps) // 2]
    traces, shapes = tc.instrument_layer(design, geom, step, tc.WINDOW_M, 400.0)
    in_window = [n for n, x in STATIONS.items() if tc.WINDOW_M[0] <= x <= tc.WINDOW_M[1]]
    assert len(_shapes_of_type(shapes, "line")) == len(in_window)
    assert len(traces[0].x) == sum(len(step.stations[n].heights_m) for n in in_window)
    assert len(traces) == 3 and list(traces[2].text) == sorted(in_window, key=STATIONS.get)


def test_fire_marker_grows_with_heat_release(design, geom, trace):
    cold = tc.fire_layer(design, geom, trace.steps[0], 400.0)[0][0]
    peak = max(trace.steps, key=lambda s: s.hrr_mw)
    hot = tc.fire_layer(design, geom, peak, 400.0)[0][0]
    assert hot.marker.size > cold.marker.size
    assert cold.marker.size >= tc.FIRE_MARKER_MIN_PX and hot.marker.size <= tc.FIRE_MARKER_MAX_PX


def test_mist_layer_is_one_trace_always_and_one_rectangle_only_when_discharging(design, geom, trace):
    dry_traces, dry_shapes = tc.mist_layer(design, geom, trace.steps[0])
    wet_traces, wet_shapes = tc.mist_layer(design, geom, _wet_step(trace))
    assert len(dry_traces) == 1 and dry_shapes == []
    assert len(wet_traces) == 1 and len(wet_shapes) == 1
    half = design.zones.section_length_m * design.zones.sections_simultaneous / 2
    assert (wet_shapes[0]["x0"], wet_shapes[0]["x1"]) == (-half, half)
    assert wet_shapes[0]["y1"] == design.nozzles.mounting.height_above_carriageway_m


def test_temp_max_rounds_the_peak_up_to_the_next_hundred_but_never_below_400(trace):
    assert tc.temp_max_c(trace) >= 400.0
    assert tc.temp_max_c(trace) % 100 == 0


def test_every_layer_returns_plotly_traces(design, geom, trace):
    step = trace.steps[-1]
    for traces, _ in (tc.tunnel_layer(design, geom, tc.WINDOW_M, step),
                      tc.instrument_layer(design, geom, step, tc.WINDOW_M, 400.0),
                      tc.fire_layer(design, geom, step, 400.0),
                      tc.mist_layer(design, geom, step)):
        assert all(isinstance(t, go.BaseTraceType) for t in traces)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_twin_canvas.py -q`
Expected: FAIL — `ModuleNotFoundError: app.components.twin_canvas`.

- [ ] **Step 3: Write the layer half of `app/components/twin_canvas.py`**

```python
"""Pure builders for the fire-test twin: a to-scale longitudinal section of the
tunnel with the mock-up, target, heads, Annex 7 station masts, fire and mist,
drawn for one instant of a Tier 1 `RunTrace`. Each layer returns Plotly traces
and layout shapes so the picture can be asserted on without a browser; Task 7
composes them into frames and a figure.

x = 0 is the longitudinal middle of the HGV mock-up (Annex 7 §6.3), the frame
the engine, `STATIONS` and the FDS deck share.
"""
from __future__ import annotations

import math
from typing import Any

import plotly.graph_objects as go

from solit2.engines.fds.deck import CORE_M, WINDOW_M
from solit2.engines.reduced.criteria import INSTRUMENTS, STATIONS
from solit2.engines.reduced.geometry import SectionGeometry, nozzle_positions
from solit2.engines.reduced.state import RunTrace, StepRecord
from solit2.schema.design import Design

Layer = tuple[list[Any], list[dict]]

TEMP_SCALE = "Inferno"
TEMP_MIN_C = 20.0
BREATHING_HEIGHT_M = 1.8
TWIN_FRAME_STRIDE_S = 30.0
BACKLAYER_MIN_M = 1.0
FIRE_MARKER_MIN_PX, FIRE_MARKER_MAX_PX = 6.0, 60.0
MIST_COLOUR = "#1D8F8A"
FAIL_COLOUR = "#C4452B"
STRUCTURE_COLOUR = "#8A94A6"
IDLE_HEAD_COLOUR = "#8A94A6"
TRANSPARENT = "rgba(0,0,0,0)"
CORE_WINDOW_M = CORE_M

__all__ = ["Layer", "WINDOW_M", "CORE_WINDOW_M", "TEMP_SCALE", "TEMP_MIN_C", "TWIN_FRAME_STRIDE_S",
           "temp_max_c", "tunnel_layer", "instrument_layer", "fire_layer", "mist_layer"]


def temp_max_c(trace: RunTrace) -> float:
    """Top of the shared temperature scale: the peak ceiling temperature rounded up
    to the next 100 °C, never below 400 °C so a cool run still reads as cool."""
    peak = max(s.ceiling_temp_c for s in trace.steps)
    return max(400.0, math.ceil(peak / 100.0) * 100.0)


def _rect(x0: float, x1: float, z0: float, z1: float, **style: Any) -> dict:
    return {"type": "rect", "x0": x0, "x1": x1, "y0": z0, "y1": z1, "layer": "below", **style}


def _line(x0: float, x1: float, z0: float, z1: float, **style: Any) -> dict:
    return {"type": "line", "x0": x0, "x1": x1, "y0": z0, "y1": z1, "layer": "below", **style}


def tunnel_layer(design: Design, geom: SectionGeometry, window_m: tuple[float, float],
                 step: StepRecord, target_ignited: bool = False) -> Layer:
    x0, x1 = window_m
    crown, fp = geom.crown_height_m, design.fire.footprint
    half_active = design.zones.section_length_m * design.zones.sections_simultaneous / 2.0
    structure = {"color": STRUCTURE_COLOUR}
    shapes = [
        _rect(-fp.length_m / 2, fp.length_m / 2, fp.base_height_m, fp.top_height_m,
              line=structure, fillcolor="rgba(138,148,166,0.35)"),
        _rect(design.fire.target_x_m, design.fire.target_x_m + fp.length_m,
              fp.base_height_m, fp.top_height_m,
              line={"color": FAIL_COLOUR if target_ignited else STRUCTURE_COLOUR, "dash": "dot"},
              fillcolor="rgba(196,69,43,0.5)" if target_ignited else TRANSPARENT),
        _line(x0, x1, 0.0, 0.0, line={**structure, "width": 2}),
        _line(x0, x1, crown, crown, line={**structure, "width": 2}),
        _line(-half_active, half_active, crown - 0.15, crown - 0.15,
              line={**structure, "width": 1, "dash": "dash"}),
    ]
    heads = nozzle_positions(design, geom, fire_x_m=0.0)
    head_colour = MIST_COLOUR if step.water_lpm > 0 else IDLE_HEAD_COLOUR
    vent_ok = step.u_eff_ms >= step.u_critical_ms
    traces = [
        go.Scatter(x=[h.x_m for h in heads], y=[h.z_m for h in heads], mode="markers",
                   name="nozzle heads", marker={"symbol": "triangle-down", "size": 7,
                                                "color": head_colour},
                   hovertemplate="head · x %{x:.1f} m · z %{y:.2f} m<extra></extra>"),
        go.Scatter(x=[design.fire.target_x_m + fp.length_m / 2, -half_active, x1 - 0.05 * (x1 - x0)],
                   y=[fp.top_height_m + 0.4, crown - 0.5, crown + 0.35], mode="text",
                   text=[f"target — {design.fire.target_distance_m:.0f} m",
                         f"{design.detection.type} {design.detection.threshold_c:.0f} °C",
                         f"gradient {design.tunnel.gradient_pct:+.1f} %"],
                   textfont={"size": 10, "color": STRUCTURE_COLOUR}, showlegend=False,
                   hoverinfo="skip", name="labels"),
        go.Scatter(x=[x0 + 0.04 * (x1 - x0)], y=[crown * 0.5], mode="text",
                   text=[f"→ u {step.u_eff_ms:.1f} m/s (critical {step.u_critical_ms:.1f})"],
                   textfont={"size": 11, "color": STRUCTURE_COLOUR if vent_ok else FAIL_COLOUR},
                   showlegend=False, hoverinfo="skip", name="ventilation"),
    ]
    return traces, shapes


def _gas_readings(sample, kit) -> list[str]:
    out = []
    if kit.heat_flux and sample.flux_kwm2 is not None:
        out.append(f"{sample.flux_kwm2:.1f} kW/m²")
    if kit.visibility and sample.visibility_m is not None:
        out.append(f"visibility {sample.visibility_m:.0f} m")
    if kit.carbon_monoxide > 0 and sample.co_ppm is not None:
        out.append(f"CO {sample.co_ppm:.0f} ppm")
    return out


def instrument_layer(design: Design, geom: SectionGeometry, step: StepRecord,
                     window_m: tuple[float, float], cmax_c: float) -> Layer:
    xs, zs, temps, hover = [], [], [], []
    gx, gz, ghover, names_x, names = [], [], [], [], []
    shapes = []
    for name, x in sorted(STATIONS.items(), key=lambda kv: kv[1]):
        if not window_m[0] <= x <= window_m[1]:
            continue
        sample = step.stations[name]
        shapes.append(_line(x, x, 0.0, geom.crown_height_m,
                            line={"color": STRUCTURE_COLOUR, "width": 1}))
        names_x.append(x)
        names.append(name)
        for z, t in zip(sample.heights_m, sample.temps_c):
            xs.append(x)
            zs.append(z)
            temps.append(t)
            hover.append(f"{name} · {z:.1f} m · {t:.0f} °C")
        readings = _gas_readings(sample, INSTRUMENTS[name])
        if readings:
            gx.append(x)
            gz.append(BREATHING_HEIGHT_M)
            ghover.append(f"{name} · " + " · ".join(readings))
    traces = [
        go.Scatter(x=xs, y=zs, mode="markers", name="thermocouples", text=hover, hoverinfo="text",
                   marker={"size": 8, "color": temps, "colorscale": TEMP_SCALE, "cmin": TEMP_MIN_C,
                           "cmax": cmax_c, "colorbar": {"title": "°C", "x": 1.02, "len": 0.8}}),
        go.Scatter(x=gx, y=gz, mode="markers", name="gas · flux · visibility", text=ghover,
                   hoverinfo="text", marker={"symbol": "diamond", "size": 11, "color": MIST_COLOUR,
                                             "line": {"color": "#1C2432", "width": 1}}),
        go.Scatter(x=names_x, y=[geom.crown_height_m + 0.35] * len(names_x), mode="text",
                   text=names, textfont={"size": 10, "color": STRUCTURE_COLOUR},
                   showlegend=False, hoverinfo="skip", name="stations"),
    ]
    return traces, shapes


def fire_layer(design: Design, geom: SectionGeometry, step: StepRecord, cmax_c: float) -> Layer:
    fp = design.fire.footprint
    frac = min(step.hrr_mw / design.fire.design_hrr_mw, 1.0)
    size = FIRE_MARKER_MIN_PX + (FIRE_MARKER_MAX_PX - FIRE_MARKER_MIN_PX) * frac
    marker = go.Scatter(
        x=[0.0], y=[fp.top_height_m], mode="markers", name="fire", hoverinfo="text",
        text=[f"HRR {step.hrr_mw:.1f} MW (free burn {step.hrr_free_mw:.1f}) · "
              f"ceiling {step.ceiling_temp_c:.0f} °C"],
        marker={"symbol": "triangle-up", "size": size, "color": [step.ceiling_temp_c],
                "colorscale": TEMP_SCALE, "cmin": TEMP_MIN_C, "cmax": cmax_c, "showscale": False,
                "line": {"color": FAIL_COLOUR, "width": 1}})
    shapes = []
    if step.backlayer_m > BACKLAYER_MIN_M:
        shapes.append(_rect(-step.backlayer_m, 0.0, geom.crown_height_m * 2 / 3, geom.crown_height_m,
                            line={"width": 0}, fillcolor="rgba(138,148,166,0.25)"))
    return [marker], shapes


def mist_layer(design: Design, geom: SectionGeometry, step: StepRecord) -> Layer:
    """Always one (possibly empty) trace so frame trace indices stay stable."""
    half = design.zones.section_length_m * design.zones.sections_simultaneous / 2.0
    top = design.nozzles.mounting.height_above_carriageway_m
    if step.water_lpm <= 0:
        return [go.Scatter(x=[], y=[], mode="markers", name="mist", showlegend=False)], []
    alpha = min(max(0.10 + 0.40 * step.mist.chi_cool, 0.10), 0.50)
    hover = go.Scatter(x=[0.0], y=[top / 2], mode="markers", name="mist", showlegend=False,
                       marker={"size": 40, "opacity": 0.0}, hoverinfo="text",
                       text=[f"{step.water_lpm:.0f} L/min · cooling {step.mist.chi_cool:.0%} · "
                             f"radiant transmission {step.mist.tau_mist:.0%}"])
    return [hover], [_rect(-half, half, 0.0, top, line={"width": 0},
                           fillcolor=f"rgba(29,143,138,{alpha:.2f})")]
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_twin_canvas.py -q`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
uv run ruff check app tests && git add app/components/twin_canvas.py tests/test_twin_canvas.py && git commit -m "feat(ui): pure twin-canvas layers for tunnel, instruments, fire and mist"
```

---

### Task 7: Twin canvas — CFD layer, frames and the animated figure

**Files:**
- Modify: `app/components/twin_canvas.py` (append)
- Test: `tests/test_twin_canvas.py` (append)

**Interfaces:**
- Consumes: `solit2.engines.fds.slices.Slice`; Task 6 layers.
- Produces: `CFD_SCALES = {"TEMPERATURE": "Inferno", "SOOT DENSITY": "Greys", "MPUV": "Blues"}`, `CFD_MAX_FRAMES = 120`, `mmss(t_s: float) -> str`, `sample_steps(trace, stride_s) -> list[StepRecord]`, `nearest_step(trace, t_s) -> StepRecord`, `cfd_layer(slice_, frame_index) -> Layer` (1 heatmap), `figure(design, trace, *, cfd=None, initial_frame=0, window_m=WINDOW_M, target_ignited=False, stride_s=TWIN_FRAME_STRIDE_S) -> go.Figure`.

- [ ] **Step 1: Append the failing tests**

```python
# append to tests/test_twin_canvas.py
import numpy as np

from solit2.engines.fds.slices import Slice


def _fake_slice(n_frames=30):
    x = np.linspace(-360.0, 240.0, 11)
    z = np.linspace(0.0, 7.0, 4)
    t = np.arange(n_frames, dtype=float) * 10.0
    frames = np.tile(z[:, None] * 10.0, (n_frames, 1, len(x))) + t[:, None, None]
    return Slice("TEMPERATURE", "C", x, z, t, frames)


def test_mmss_formats_the_test_clock():
    assert tc.mmss(0) == "00:00" and tc.mmss(90) == "01:30" and tc.mmss(3599.6) == "60:00"


def test_sample_steps_takes_one_step_per_stride_starting_at_zero(trace):
    steps = tc.sample_steps(trace, 30.0)
    t_end = trace.steps[-1].t_s
    assert steps[0].t_s == 0.0 and len(steps) == int(t_end // 30.0) + 1
    assert all(b.t_s - a.t_s == pytest.approx(30.0, abs=1.0) for a, b in zip(steps, steps[1:]))


def test_figure_has_one_frame_per_sample_and_a_constant_trace_count(design, trace):
    fig = tc.figure(design, trace)
    assert len(fig.frames) == len(tc.sample_steps(trace, tc.TWIN_FRAME_STRIDE_S))
    n = len(fig.data)
    assert all(len(f.data) == n and list(f.traces) == list(range(n)) for f in fig.frames)
    assert fig.frames[3].name == tc.mmss(90.0)
    assert fig.layout.updatemenus and fig.layout.sliders


def test_figure_with_a_slice_leads_with_a_heatmap_on_the_slice_time_base(design, trace):
    fig = tc.figure(design, trace, cfd=_fake_slice(30))
    assert isinstance(fig.data[0], go.Heatmap)
    assert len(fig.frames) == 30
    assert fig.frames[-1].name == tc.mmss(290.0)


def test_figure_caps_cfd_frames(design, trace):
    fig = tc.figure(design, trace, cfd=_fake_slice(500))
    assert len(fig.frames) <= tc.CFD_MAX_FRAMES


def test_figure_honours_the_window_and_initial_frame(design, trace):
    fig = tc.figure(design, trace, window_m=tc.CORE_WINDOW_M, initial_frame=2)
    assert list(fig.layout.xaxis.range) == list(tc.CORE_WINDOW_M)
    assert fig.layout.sliders[0].active == 2
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_twin_canvas.py -q`
Expected: 6 new failures — `AttributeError: module has no attribute 'mmss'` etc.

- [ ] **Step 3: Append the composition half to `twin_canvas.py`**

Add to the imports: `from solit2.engines.fds.slices import Slice` and `from solit2.engines.reduced.geometry import section_geometry`. Extend `__all__` with `"CFD_SCALES", "CFD_MAX_FRAMES", "mmss", "sample_steps", "nearest_step", "cfd_layer", "figure"`. Then append:

```python
CFD_SCALES = {"TEMPERATURE": "Inferno", "SOOT DENSITY": "Greys", "MPUV": "Blues"}
CFD_MAX_FRAMES = 120
FRAME_MS = 150


def mmss(t_s: float) -> str:
    minutes, seconds = divmod(int(round(t_s)), 60)
    return f"{minutes:02d}:{seconds:02d}"


def sample_steps(trace: RunTrace, stride_s: float) -> list[StepRecord]:
    """One step per `stride_s`, starting at t = 0 (the engine steps every second)."""
    out, next_t = [], 0.0
    for step in trace.steps:
        if step.t_s + 1e-9 >= next_t:
            out.append(step)
            next_t += stride_s
    return out


def nearest_step(trace: RunTrace, t_s: float) -> StepRecord:
    return min(trace.steps, key=lambda s: abs(s.t_s - t_s))


def cfd_layer(slice_: Slice, frame_index: int) -> Layer:
    heat = go.Heatmap(
        x=slice_.x_m, y=slice_.z_m, z=slice_.frames[frame_index], name=slice_.quantity,
        colorscale=CFD_SCALES.get(slice_.quantity, "Viridis"),
        zmin=float(slice_.frames.min()), zmax=float(slice_.frames.max()),
        colorbar={"title": f"{slice_.quantity} ({slice_.unit})", "x": 1.12, "len": 0.8},
        hovertemplate="x %{x:.1f} m · z %{y:.1f} m · %{z:.3g}<extra></extra>")
    return [heat], []


def _instant(design: Design, geom: SectionGeometry, step: StepRecord, cmax_c: float,
             window_m: tuple[float, float], target_ignited: bool) -> Layer:
    """Every Tier 1 layer for one step, traces in a fixed order."""
    traces, shapes = [], []
    for layer in (tunnel_layer(design, geom, window_m, step, target_ignited),
                  instrument_layer(design, geom, step, window_m, cmax_c),
                  fire_layer(design, geom, step, cmax_c),
                  mist_layer(design, geom, step)):
        traces += layer[0]
        shapes += layer[1]
    return traces, shapes


def _cfd_indices(n_frames: int) -> list[int]:
    if n_frames <= CFD_MAX_FRAMES:
        return list(range(n_frames))
    return sorted({round(i * (n_frames - 1) / (CFD_MAX_FRAMES - 1)) for i in range(CFD_MAX_FRAMES)})


def _play_menu() -> dict:
    return {"type": "buttons", "showactive": False, "x": 0.0, "y": 1.14, "xanchor": "left",
            "buttons": [
                {"label": "▶ Play", "method": "animate",
                 "args": [None, {"frame": {"duration": FRAME_MS, "redraw": True},
                                 "fromcurrent": True, "transition": {"duration": 0}}]},
                {"label": "❚❚ Pause", "method": "animate",
                 "args": [[None], {"frame": {"duration": 0, "redraw": False},
                                   "mode": "immediate"}]}]}


def _slider(names: list[str], active: int) -> dict:
    return {"active": active, "x": 0.12, "len": 0.88, "y": 1.1, "pad": {"t": 0},
            "currentvalue": {"prefix": "t = ", "visible": True},
            "steps": [{"label": n, "method": "animate",
                       "args": [[n], {"frame": {"duration": 0, "redraw": True},
                                      "mode": "immediate"}]} for n in names]}


def figure(design: Design, trace: RunTrace, *, cfd: Slice | None = None, initial_frame: int = 0,
           window_m: tuple[float, float] = WINDOW_M, target_ignited: bool = False,
           stride_s: float = TWIN_FRAME_STRIDE_S) -> go.Figure:
    """The animated twin. Without `cfd` the frames are Tier 1 steps every `stride_s`;
    with it they follow the slice's own time base and each frame pairs a heatmap with
    the Tier 1 step nearest in time, so both tiers sit on one picture."""
    geom, cmax_c = section_geometry(design), temp_max_c(trace)
    if cfd is None:
        steps = sample_steps(trace, stride_s)
        times, cfd_idx = [s.t_s for s in steps], [None] * len(steps)
    else:
        cfd_idx = _cfd_indices(len(cfd.t_s))
        times = [float(cfd.t_s[i]) for i in cfd_idx]
        steps = [nearest_step(trace, t) for t in times]

    def instant(k: int) -> Layer:
        traces, shapes = _instant(design, geom, steps[k], cmax_c, window_m, target_ignited)
        if cfd is not None:
            traces = cfd_layer(cfd, cfd_idx[k])[0] + traces
        return traces, shapes

    k0 = min(max(initial_frame, 0), len(steps) - 1)
    traces0, shapes0 = instant(k0)
    names = [mmss(t) for t in times]
    frames = []
    for k in range(len(steps)):
        traces_k, shapes_k = instant(k)
        frames.append(go.Frame(data=traces_k, traces=list(range(len(traces_k))), name=names[k],
                               layout=go.Layout(shapes=shapes_k)))
    fig = go.Figure(data=traces0, frames=frames)
    fig.update_layout(
        shapes=shapes0, height=540, margin={"l": 10, "r": 10, "t": 60, "b": 10},
        xaxis={"title": "distance from mock-up centre (m)", "range": list(window_m), "zeroline": False},
        yaxis={"title": "height (m)", "range": [-0.3, geom.crown_height_m + 1.0]},
        legend={"orientation": "h", "y": -0.2}, updatemenus=[_play_menu()],
        sliders=[_slider(names, k0)])
    return fig
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_twin_canvas.py -q`
Expected: 14 passed.

- [ ] **Step 5: Commit**

```bash
uv run ruff check app tests && git add app/components/twin_canvas.py tests/test_twin_canvas.py && git commit -m "feat(ui): animated twin figure with optional CFD heatmap layer"
```

---

### Task 8: HMI strip and event timeline

**Files:**
- Create: `app/components/hmi.py`
- Create: `app/components/timeline.py`
- Test: `tests/test_app_hmi_timeline.py`

**Interfaces:**
- Consumes: `twin_canvas.mmss`, `solit2.engines.reduced.sim.DT_S`, `HydraulicsResult.tank_m3`, `RunTrace.events` keys `t_detect_s t_activate_s t_full_pressure_s t_peak_hrr_s pools_extinguished_at_s backlayering.cleared_at_s`, `Criterion.status`.
- Produces (`hmi`): `LAMPS = (("Detection", "t_detect_s"), ("Activation", "t_activate_s"), ("Full pressure", "t_full_pressure_s"))`, `water_discharged_m3(steps, upto_t_s) -> float`, `lamp_states(step, events) -> dict[str, bool]` (adds `"Discharge"`), `render(step, trace, design, hyd) -> None`.
- Produces (`timeline`): `EVENT_LABELS`, `event_marks(events) -> list[tuple[float, str]]`, `figure(events, t_end_s) -> go.Figure`, `render(events, criteria, t_end_s) -> None` (widget key `timeline`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_app_hmi_timeline.py
import pytest
from streamlit.testing.v1 import AppTest

from app.components import hmi, timeline
from solit2.engines.reduced.sim import run_once
from solit2.schema.design import Design

EXAMPLE = "examples/designs/road-tunnel-twin-bore.json"


@pytest.fixture(scope="module")
def trace():
    d = Design.load(EXAMPLE)
    return run_once(d, d.tunnel.section, d.ventilation.velocity_range_ms[0])


def _step_at(trace, t):
    return min(trace.steps, key=lambda s: abs(s.t_s - t))


def test_lamps_light_in_sequence(trace):
    ev = trace.events
    before = hmi.lamp_states(_step_at(trace, ev["t_detect_s"] - 5), ev)
    after = hmi.lamp_states(_step_at(trace, ev["t_full_pressure_s"] + 5), ev)
    assert list(before) == ["Detection", "Activation", "Full pressure", "Discharge"]
    assert not any(before.values())
    assert after["Detection"] and after["Activation"] and after["Full pressure"] and after["Discharge"]


def test_water_discharged_is_zero_before_activation_and_grows_after(trace):
    ev = trace.events
    assert hmi.water_discharged_m3(trace.steps, ev["t_activate_s"] - 1) == 0.0
    late = hmi.water_discharged_m3(trace.steps, trace.steps[-1].t_s)
    mid = hmi.water_discharged_m3(trace.steps, ev["t_full_pressure_s"] + 60)
    assert late > mid > 0.0


def test_event_marks_are_sorted_and_skip_unset_events():
    marks = timeline.event_marks({"t_detect_s": 90.0, "t_activate_s": 150.0, "t_full_pressure_s": 180.0,
                                  "t_peak_hrr_s": 60.0, "pools_extinguished_at_s": None,
                                  "backlayering": {"occurred": True, "cleared_at_s": 400.0}})
    assert [t for t, _ in marks] == [60.0, 90.0, 150.0, 180.0, 400.0]
    assert marks[-1][1] == "Backlayer cleared"


def test_hmi_and_timeline_render_without_error():
    script = """
from app.components import hmi, timeline
from solit2.engines.reduced.geometry import section_geometry
from solit2.engines.reduced.hydraulics import size_system
from solit2.engines.reduced.sim import run_once
from solit2.engines.reduced import envelope
from solit2.schema.design import Design
d = Design.load("examples/designs/road-tunnel-twin-bore.json")
tr = run_once(d, d.tunnel.section, d.ventilation.velocity_range_ms[0])
res = envelope.run(d)
hmi.render(tr.steps[200], tr, d, size_system(d, section_geometry(d)))
timeline.render(tr.events, res.criteria, tr.steps[-1].t_s)
"""
    at = AppTest.from_string(script, default_timeout=60)
    at.run()
    assert not at.exception
    assert [m.label for m in at.metric][:2] == ["Test clock", "HRR"]
    assert any('class="lamps"' in m.value for m in at.markdown)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_app_hmi_timeline.py -q`
Expected: FAIL — `ModuleNotFoundError: app.components.hmi`.

- [ ] **Step 3: Write `app/components/hmi.py`**

```python
"""The test-rig strip above the twin: clock, live readouts and status lamps."""
from __future__ import annotations

import streamlit as st

from app.components.twin_canvas import mmss
from solit2.engines.reduced.hydraulics import HydraulicsResult
from solit2.engines.reduced.sim import DT_S
from solit2.engines.reduced.state import RunTrace, StepRecord
from solit2.schema.design import Design

LAMPS = (("Detection", "t_detect_s"), ("Activation", "t_activate_s"),
         ("Full pressure", "t_full_pressure_s"))


def water_discharged_m3(steps: tuple[StepRecord, ...], upto_t_s: float) -> float:
    """Litres per minute integrated over the engine's fixed step, in cubic metres."""
    lpm = sum(s.water_lpm for s in steps if s.t_s <= upto_t_s)
    return lpm * DT_S / 60.0 / 1000.0


def lamp_states(step: StepRecord, events: dict) -> dict[str, bool]:
    states = {label: events.get(key) is not None and step.t_s >= events[key]
              for label, key in LAMPS}
    states["Discharge"] = step.water_lpm > 0
    return states


def render(step: StepRecord, trace: RunTrace, design: Design, hyd: HydraulicsResult) -> None:
    clock, hrr, water, tank, vent = st.columns(5)
    clock.metric("Test clock", mmss(step.t_s))
    hrr.metric("HRR", f"{step.hrr_mw:.1f} MW",
               delta=f"{step.hrr_mw - step.hrr_free_mw:+.1f} MW vs free burn", delta_color="inverse")
    water.metric("Water", f"{step.water_lpm:.0f} L/min")
    used = water_discharged_m3(trace.steps, step.t_s)
    tank.metric("Tank remaining", f"{max(hyd.tank_m3 - used, 0.0):.1f} m³", delta=f"-{used:.1f} m³",
                delta_color="off")
    vent.metric("Ventilation", f"{step.u_eff_ms:.2f} m/s",
                delta=f"{step.u_eff_ms - step.u_critical_ms:+.2f} m/s vs critical")
    lamps = "".join(f'<span><span class="lamp {"on" if on else ""}"></span>{label}</span>'
                    for label, on in lamp_states(step, trace.events).items())
    st.markdown(f'<div class="lamps">{lamps}</div>', unsafe_allow_html=True)
```

- [ ] **Step 4: Write `app/components/timeline.py`**

```python
"""Where the test's events fall on the clock, and which criteria failed."""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from app.components.twin_canvas import MIST_COLOUR, STRUCTURE_COLOUR, mmss
from solit2.schema.result import Criterion

EVENT_LABELS = (("t_detect_s", "Detection"), ("t_activate_s", "Activation"),
                ("t_full_pressure_s", "Full pressure"), ("t_peak_hrr_s", "Peak HRR"),
                ("pools_extinguished_at_s", "Pools out"))


def event_marks(events: dict) -> list[tuple[float, str]]:
    marks = [(float(events[key]), label) for key, label in EVENT_LABELS
             if events.get(key) is not None]
    cleared = (events.get("backlayering") or {}).get("cleared_at_s")
    if cleared is not None:
        marks.append((float(cleared), "Backlayer cleared"))
    return sorted(marks)


def figure(events: dict, t_end_s: float) -> go.Figure:
    marks = event_marks(events)
    fig = go.Figure()
    fig.add_shape(type="line", x0=0, x1=t_end_s, y0=0, y1=0, line={"color": STRUCTURE_COLOUR, "width": 2})
    fig.add_trace(go.Scatter(x=[t for t, _ in marks], y=[0] * len(marks), mode="markers+text",
                             text=[f"{label}<br>{mmss(t)}" for t, label in marks],
                             textposition="top center",
                             marker={"size": 10, "color": MIST_COLOUR}, hoverinfo="skip"))
    fig.update_layout(height=130, margin={"l": 10, "r": 10, "t": 10, "b": 10}, showlegend=False,
                      xaxis={"range": [0, t_end_s], "title": "test clock (s)"},
                      yaxis={"visible": False, "range": [-1, 1]})
    return fig


def render(events: dict, criteria: dict[str, Criterion], t_end_s: float) -> None:
    st.plotly_chart(figure(events, t_end_s), key="timeline")
    failed = [name for name, c in criteria.items() if c.status == "fail"]
    if failed:
        chips = "".join(f'<span class="chip fail">{n}</span>' for n in failed)
        st.markdown(f"Failed criteria: {chips}", unsafe_allow_html=True)
```

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_app_hmi_timeline.py -q`
Expected: 4 passed.

- [ ] **Step 6: Commit**

```bash
uv run ruff check app tests && git add app/components/hmi.py app/components/timeline.py tests/test_app_hmi_timeline.py && git commit -m "feat(ui): HMI readout strip with status lamps and an event timeline"
```

---

### Task 9: Step 1 — Design view with a live summary card

**Files:**
- Create: `tests/conftest.py`
- Modify: `app/views/design.py`
- Test: `tests/test_app_design_step.py`

**Interfaces:**
- Consumes: `app.state.set_design / set_step`, `solit2.engines.reduced.hydraulics.size_system(design, geom) -> HydraulicsResult` (`.active_heads .flow_lpm .power_kw .tank_m3 .density_mm_min`), `section_geometry`.
- Produces (`tests/conftest.py`): fixture `run_view(view: str, seed_design: bool = True, timeout: float = 90.0) -> AppTest`; constant `EXAMPLE_DESIGN`.
- Produces (`design.py`): widget keys `d_tunnel d_fire d_nozzle d_hydraulics d_k d_pressure d_rows d_pitch d_section_len d_sections d_v_lo d_v_hi build_design`; metric labels `Active heads`, `Per head`, `Zone flow`, `Pump power`, `Tank`, `Density`.

- [ ] **Step 1: Write the shared test scaffold**

```python
# tests/conftest.py
"""Shared AppTest scaffolding: render one view the way the shell does (theme +
optional seeded design), without the stepper so buttons are addressed by key only."""
import pytest
from streamlit.testing.v1 import AppTest

EXAMPLE_DESIGN = "examples/designs/road-tunnel-twin-bore.json"


def view_script(view: str, seed_design: bool) -> str:
    seed = (f'if state.get_design() is None:\n'
            f'    state.set_design(Design.load("{EXAMPLE_DESIGN}"))\n') if seed_design else ""
    return ("import streamlit as st\n"
            "from app import state, theme\n"
            f"from app.views import {view} as view\n"
            "from solit2.schema.design import Design\n"
            "theme.inject()\n"
            f"{seed}"
            "view.render()\n")


@pytest.fixture
def run_view():
    def _run(view: str, seed_design: bool = True, timeout: float = 90.0) -> AppTest:
        at = AppTest.from_string(view_script(view, seed_design), default_timeout=timeout)
        at.run()
        return at
    return _run
```

- [ ] **Step 2: Write the failing tests**

```python
# tests/test_app_design_step.py
def test_summary_card_shows_live_hydraulics_before_building(run_view):
    at = run_view("design", seed_design=False)
    assert not at.exception
    labels = [m.label for m in at.metric]
    assert labels[:3] == ["Active heads", "Per head", "Zone flow"]
    assert "L/min" in at.metric[2].value and "m³" in at.metric[4].value


def test_build_and_continue_sets_the_design_and_advances(run_view):
    at = run_view("design", seed_design=False)
    assert "design" not in at.session_state
    at.button(key="build_design").click().run()
    assert not at.exception
    assert at.session_state["design"].meta.name == "streamlit-design"
    assert at.session_state["step"] == 2


def test_design_step_has_no_download_or_upload(run_view):
    at = run_view("design", seed_design=False)
    assert not at.get("download_button") and not at.get("file_uploader")


def test_changing_pressure_changes_the_summary(run_view):
    at = run_view("design", seed_design=False)
    before = at.metric[1].value
    at.number_input(key="d_pressure").set_value(100.0).run()
    assert at.metric[1].value != before
```

- [ ] **Step 3: Run to verify failure**

Run: `uv run pytest tests/test_app_design_step.py -q`
Expected: FAIL — no metrics, `KeyError`/`ValueError` for key `build_design`.

- [ ] **Step 4: Modify `app/views/design.py`**

Add imports:

```python
from solit2.engines.reduced.geometry import section_geometry
from solit2.engines.reduced.hydraulics import size_system
```

Add `key=` to every widget in the four `_render_*` helpers, using the names listed under Interfaces (`d_tunnel`, `d_fire`, `d_nozzle`, `d_hydraulics`, `d_k`, `d_pressure`, `d_rows`, `d_pitch`, `d_section_len`, `d_sections`, `d_v_lo`, `d_v_hi`). Then replace `render()` with:

```python
def _render_summary(raw: dict) -> None:
    """What the inputs above add up to, before anything is built."""
    st.subheader("This system")
    try:
        design = Design.from_dict(raw)
    except Exception as exc:  # noqa: BLE001 -- shown inline, so the user can fix the input
        st.caption(f"Not a valid design yet: {exc}")
        return
    hyd = size_system(design, section_geometry(design))
    per_head_lpm = design.nozzles.k_factor_lpm_bar05 * design.nozzles.pressure_bar ** 0.5
    cols = st.columns(6)
    cols[0].metric("Active heads", f"{hyd.active_heads}")
    cols[1].metric("Per head", f"{per_head_lpm:.1f} L/min")
    cols[2].metric("Zone flow", f"{hyd.flow_lpm:.0f} L/min")
    cols[3].metric("Pump power", f"{hyd.power_kw:.0f} kW")
    cols[4].metric("Tank", f"{hyd.tank_m3:.1f} m³")
    cols[5].metric("Density", f"{hyd.density_mm_min:.2f} mm/min")


def render() -> None:
    st.header("Design")
    st.caption("Pick a starting preset for each block, then set the parameters an engineer "
               "actually varies. Everything else comes from the presets.")
    tunnel_preset, fire_preset, nozzle_preset, hydraulics_preset = _render_preset_pickers()
    k_factor, pressure_bar, rows, pitch_m = _render_nozzle_hydraulics_inputs()
    section_length_m, sections_simultaneous = _render_zoning_inputs()
    velocity_lo, velocity_hi = _render_ventilation_inputs()
    raw = _assemble(tunnel_preset, fire_preset, nozzle_preset, hydraulics_preset,
                    k_factor, pressure_bar, int(rows), pitch_m,
                    section_length_m, int(sections_simultaneous), velocity_lo, velocity_hi)
    _render_summary(raw)
    if st.button("Build & continue →", key="build_design", type="primary"):
        try:
            design = Design.from_dict(raw)
        except Exception as exc:  # noqa: BLE001 -- surfaced to the user, not swallowed
            st.error(f"Could not build a valid design: {exc}")
            return
        state.set_design(design)
        state.set_step(2)
        st.rerun()
```

Delete the old "Current design" `st.json` + `st.download_button` block entirely.

- [ ] **Step 5: Run tests**

Run: `uv run pytest tests/test_app_design_step.py -q`
Expected: 4 passed. (The old `tests/test_app_design_view.py` may now fail on the removed download button — that file is deleted in Task 14; do not fix it here.)

- [ ] **Step 6: Commit**

```bash
uv run ruff check app tests && git add tests/conftest.py app/views/design.py tests/test_app_design_step.py && git commit -m "feat(ui): design step with live hydraulics summary and build-and-continue"
```

---

### Task 10: Step 2 — Result view (verdict, chips, leaderboard)

**Files:**
- Create: `app/views/result.py`
- Test: `tests/test_app_result_step.py`

**Interfaces:**
- Consumes: `app.components.charts.criteria_table / timeseries_chart`, `solit2.history.append(result, path)`, `history.leaderboard(path, top, passing_only)`, `envelope.run(design)`.
- Produces: `ensure_result(design: Design) -> Result` (imported by steps 3–5); widget keys `lb_passing leaderboard criteria constraints series timeseries`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_app_result_step.py
from solit2 import history


def _redirect_history(monkeypatch, tmp_path):
    path = tmp_path / "history.jsonl"
    monkeypatch.setattr(history, "DEFAULT_PATH", path)
    return path


def test_result_step_auto_runs_records_history_and_shows_an_honest_verdict(run_view, monkeypatch, tmp_path):
    path = _redirect_history(monkeypatch, tmp_path)
    at = run_view("result")
    assert not at.exception and not at.button  # no "run" button anywhere
    result = at.session_state["result"]
    assert result is not None and len(path.read_text().splitlines()) == 1
    banner = next(m.value for m in at.markdown if 'class="verdict' in m.value)
    assert ("PASS" in banner) == (not result.score["gates_failed"])
    unset = result.score["criteria_unset"]
    assert (f"{len(unset)} criteria not judged" in banner) == bool(unset)


def test_a_rerun_does_not_append_history_again(run_view, monkeypatch, tmp_path):
    path = _redirect_history(monkeypatch, tmp_path)
    at = run_view("result")
    at.run()
    assert len(path.read_text().splitlines()) == 1


def test_gate_chips_carry_each_hard_criterions_status(run_view, monkeypatch, tmp_path):
    _redirect_history(monkeypatch, tmp_path)
    at = run_view("result")
    result = at.session_state["result"]
    chips = next(m.value for m in at.markdown if 'class="chip' in m.value)
    for name, c in result.criteria.items():
        if c.hard:
            assert f'class="chip {c.status}">{name}<' in chips


def test_leaderboard_marks_the_current_design(run_view, monkeypatch, tmp_path):
    _redirect_history(monkeypatch, tmp_path)
    at = run_view("result")
    table = next(d.value for d in at.dataframe if "this" in d.value.columns)
    assert list(table["this"]) == ["◀"]
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_app_result_step.py -q`
Expected: FAIL — `ModuleNotFoundError: app.views.result`.

- [ ] **Step 3: Write `app/views/result.py`**

```python
"""Step 2: the Tier 1 verdict on the current design, and how it ranks.

The engine runs the moment this step is opened — a Tier 1 run takes seconds,
so there is nothing to click. Every run is recorded to the history file, as
`solit2 run` does by default.
"""
from __future__ import annotations

import pandas as pd
import streamlit as st

from app import state
from app.components.charts import criteria_table, timeseries_chart
from solit2 import history
from solit2.engines.reduced import envelope
from solit2.schema.design import Design
from solit2.schema.result import Result

PEAK_TILES = 4
SERIES_DEFAULT = 3
LEADERBOARD_TOP = 20


def ensure_result(design: Design) -> Result:
    """The Tier 1 result for `design`, computing and recording it on first use."""
    result = state.get_result()
    if result is None:
        try:
            with st.spinner("Running the reduced-order engine…"):
                result = envelope.run(design)
        except (ArithmeticError, RuntimeError, ValueError, KeyError) as exc:
            # The stepper header is already drawn, so the user can go back and fix the design.
            st.error(f"The engine could not finish this design: {exc}")
            st.stop()
        state.set_result(result)
        history.append(result, history.DEFAULT_PATH)
    return result


def _verdict(result: Result) -> None:
    failed, unset = result.score["gates_failed"], result.score["criteria_unset"]
    label, cls = ("FAIL", "fail") if failed else ("PASS", "pass")
    note = (f"{len(unset)} criteria not judged — no AHJ limit set" if unset
            else "every criterion judged")
    st.markdown(
        f'<div class="verdict {cls}"><span class="verdict-label">{label}</span>'
        f'<span class="verdict-score">score {result.score["total"]:.2f} / 10</span>'
        f'<span class="verdict-note">{note}</span></div>', unsafe_allow_html=True)


def _chips(result: Result) -> None:
    chips = "".join(f'<span class="chip {c.status}">{name}</span>'
                    for name, c in result.criteria.items() if c.hard)
    st.markdown(chips, unsafe_allow_html=True)


def _leaderboard(result: Result) -> None:
    with st.expander("Compare with earlier designs"):
        passing = st.checkbox("Passing designs only", key="lb_passing")
        rows = history.leaderboard(history.DEFAULT_PATH, top=LEADERBOARD_TOP, passing_only=passing)
        if not rows:
            st.info("No earlier runs recorded yet.")
            return
        table = pd.DataFrame(rows)
        table.insert(0, "this", table["design_sha"].eq(result.meta["design_sha"])
                     .map({True: "◀", False: ""}))
        st.dataframe(table, key="leaderboard", hide_index=True)


def render() -> None:
    st.header("Result — Tier 1")
    design = state.get_design()
    if design is None:
        st.info("Build a design first.")
        return
    result = ensure_result(design)
    st.caption(f"Design **{design.meta.name}** · worst case: {result.worst_case['section']} "
               f"section at {result.worst_case['velocity_ms']:.2f} m/s")
    _verdict(result)
    _chips(result)

    st.subheader("Peaks")
    for col, (name, value) in zip(st.columns(PEAK_TILES), list(result.peaks.items())[:PEAK_TILES]):
        col.metric(name, f"{value:.1f}")
    st.subheader("Acceptance criteria")
    st.dataframe(criteria_table(result.criteria), key="criteria", hide_index=True)
    if result.constraints:
        st.subheader("Site constraints (not SOLIT2 acceptance criteria)")
        st.dataframe(criteria_table(result.constraints), key="constraints", hide_index=True)

    st.subheader("Timeseries")
    available = [k for k in result.timeseries if k != "t_s"]
    chosen = st.multiselect("Series", available, default=available[:SERIES_DEFAULT], key="series")
    if chosen:
        st.plotly_chart(timeseries_chart(result.timeseries, chosen), key="timeseries")
    for warning in result.warnings:
        st.warning(warning)
    _leaderboard(result)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_app_result_step.py -q`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
uv run ruff check app tests && git add app/views/result.py tests/test_app_result_step.py && git commit -m "feat(ui): result step with verdict banner, gate chips and inline leaderboard"
```

---

### Task 11: Step 3 — Fire test view (the digital twin)

**Files:**
- Create: `app/views/fire_test.py`
- Test: `tests/test_app_fire_test_step.py`

**Interfaces:**
- Consumes: `ensure_result`, `twin_canvas.figure / sample_steps / mmss / WINDOW_M / CORE_WINDOW_M / TWIN_FRAME_STRIDE_S`, `hmi.render`, `timeline.render`, `sim.run_once`, `size_system`, `section_geometry`, `STATIONS`, `INSTRUMENTS`.
- Produces: `ensure_trace(design: Design, result: Result) -> RunTrace` (imported by step 4); widget keys `twin_clock twin_zoom twin_canvas station station_chart`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_app_fire_test_step.py
from solit2 import history


def test_fire_test_step_renders_hmi_canvas_timeline_and_station_chart(run_view, monkeypatch, tmp_path):
    monkeypatch.setattr(history, "DEFAULT_PATH", tmp_path / "h.jsonl")
    at = run_view("fire_test")
    assert not at.exception
    assert [m.label for m in at.metric][:5] == ["Test clock", "HRR", "Water", "Tank remaining", "Ventilation"]
    assert len(at.select_slider) == 1 and len(at.toggle) == 1 and len(at.selectbox) == 1
    assert any('class="lamps"' in m.value for m in at.markdown)
    assert not at.get("file_uploader") and not at.get("download_button")


def test_the_clock_slider_drives_the_readouts(run_view, monkeypatch, tmp_path):
    monkeypatch.setattr(history, "DEFAULT_PATH", tmp_path / "h.jsonl")
    at = run_view("fire_test")
    at.select_slider(key="twin_clock").set_value("00:00").run()
    assert at.metric[0].value == "00:00" and at.metric[2].value == "0 L/min"
    last = at.select_slider(key="twin_clock").options[-1]
    at.select_slider(key="twin_clock").set_value(last).run()
    assert at.metric[0].value == last


def test_zoom_toggle_and_station_pick_rerender_cleanly(run_view, monkeypatch, tmp_path):
    monkeypatch.setattr(history, "DEFAULT_PATH", tmp_path / "h.jsonl")
    at = run_view("fire_test")
    at.toggle(key="twin_zoom").set_value(True).run()
    at.selectbox(key="station").set_value("U45").run()
    assert not at.exception
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_app_fire_test_step.py -q`
Expected: FAIL — `ModuleNotFoundError: app.views.fire_test`.

- [ ] **Step 3: Write `app/views/fire_test.py`**

```python
"""Step 3: the fire test as a digital twin — watch the Tier 1 worst case play out
in a to-scale tunnel with the Annex 7 instrumentation reading live."""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from app import state
from app.components import hmi, timeline, twin_canvas
from app.views.result import ensure_result
from solit2.engines.reduced.criteria import INSTRUMENTS, STATIONS
from solit2.engines.reduced.geometry import section_geometry
from solit2.engines.reduced.hydraulics import size_system
from solit2.engines.reduced.sim import run_once
from solit2.engines.reduced.state import RunTrace
from solit2.schema.design import Design
from solit2.schema.result import Result

CHART_HEIGHT = 300


@st.cache_data(show_spinner="Replaying the worst case…")
def _trace(design: Design, section: str, velocity_ms: float) -> RunTrace:
    return run_once(design, section, velocity_ms)


def ensure_trace(design: Design, result: Result) -> RunTrace:
    """The step-by-step trace of the result's worst case (the envelope keeps only summaries)."""
    return _trace(design, result.worst_case["section"], result.worst_case["velocity_ms"])


def _kit_caption(name: str) -> str:
    kit = INSTRUMENTS[name]
    extras = [label for flag, label in ((kit.heat_flux, "heat-flux gauge"),
                                        (kit.visibility, "visibility meter"),
                                        (kit.carbon_monoxide > 0, "CO analyser"),
                                        (kit.ultrasonic > 0, "air-velocity probe")) if flag]
    return (f"{name} at {STATIONS[name]:+.0f} m from the mock-up centre — "
            f"{kit.thermocouples} thermocouples" + "".join(f", {e}" for e in extras))


def _station_chart(trace: RunTrace) -> None:
    names = sorted(STATIONS, key=STATIONS.get)
    first_downstream = next(i for i, n in enumerate(names) if STATIONS[n] > 0)
    name = st.selectbox("Station", names, index=first_downstream, key="station")
    heights = trace.steps[0].stations[name].heights_m
    fig = go.Figure()
    for i, z in enumerate(heights):
        fig.add_trace(go.Scatter(x=[s.t_s for s in trace.steps],
                                 y=[s.stations[name].temps_c[i] for s in trace.steps],
                                 mode="lines", name=f"{z:.1f} m"))
    fig.update_layout(height=CHART_HEIGHT, xaxis_title="test clock (s)",
                      yaxis_title="gas temperature (°C)", legend_title="height",
                      margin={"l": 10, "r": 10, "t": 10, "b": 10})
    st.plotly_chart(fig, key="station_chart")
    st.caption(_kit_caption(name))


def render() -> None:
    st.header("Fire test — digital twin")
    design = state.get_design()
    if design is None:
        st.info("Build a design first.")
        return
    result = ensure_result(design)
    trace = ensure_trace(design, result)

    steps = twin_canvas.sample_steps(trace, twin_canvas.TWIN_FRAME_STRIDE_S)
    labels = [twin_canvas.mmss(s.t_s) for s in steps]
    chosen = st.select_slider("Test clock", options=labels, value=labels[len(labels) // 3],
                              key="twin_clock")
    k = labels.index(chosen)
    hmi.render(steps[k], trace, design, size_system(design, section_geometry(design)))

    zoom = st.toggle("Zoom to the fire zone", key="twin_zoom")
    window = twin_canvas.CORE_WINDOW_M if zoom else twin_canvas.WINDOW_M
    fig = twin_canvas.figure(design, trace, initial_frame=k, window_m=window,
                             target_ignited=bool(result.criteria["target_ignited"].value))
    st.plotly_chart(fig, key="twin_canvas")
    st.caption("▶ Play runs the twin on its own clock inside the picture; the Test clock "
               "slider above sets the instant the readouts describe.")

    timeline.render(trace.events, result.criteria, trace.steps[-1].t_s)
    st.subheader("Station readings")
    _station_chart(trace)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_app_fire_test_step.py -q`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
uv run ruff check app tests && git add app/views/fire_test.py tests/test_app_fire_test_step.py && git commit -m "feat(ui): fire-test step — HMI strip, animated twin canvas, timeline, station chart"
```

---

### Task 12: Step 4 — CFD verify view

**Files:**
- Create: `app/views/cfd.py`
- Test: `tests/test_app_cfd_step.py`

**Interfaces:**
- Consumes: `ensure_result`, `ensure_trace`, `twin_canvas.figure(design, trace, cfd=Slice)`, `fds_deck.generate(design, t_end_s=…)`, `fds_runner.preflight / run / status / smokeview_binary / open_smokeview`, `fds_reader.read(run_dir, design)`, `slices.load_centreline`, `envelope._design_sha`, `correlation.render(tier1, tier2)`.
- Produces: `RUNS_DIR = Path("runs")`, `DURATIONS`, `DEFAULT_DURATION = "20 min"`, `QUANTITIES`, `run_dir_for(design) -> Path`, `stamp(run_dir) -> tuple`; widget keys `fds_minutes fds_start open_smv cfd_TEMPERATURE cfd_SOOT DENSITY cfd_MPUV`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_app_cfd_step.py
"""No FDS is assumed: the runner is stubbed at the module boundary."""
from pathlib import Path

from solit2 import history
from solit2.engines.fds import reader as fds_reader
from solit2.engines.fds import runner as fds_runner
from solit2.engines.reduced import envelope
from solit2.engines.reduced.envelope import _design_sha
from solit2.schema.design import Design

EXAMPLE = "examples/designs/road-tunnel-twin-bore.json"


def _isolate(monkeypatch, tmp_path, problems):
    from app.views import cfd
    monkeypatch.setattr(history, "DEFAULT_PATH", tmp_path / "h.jsonl")
    monkeypatch.setattr(cfd, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(fds_runner, "preflight", lambda: problems)
    monkeypatch.setattr(fds_runner, "smokeview_binary", lambda: None)
    return tmp_path / "runs" / _design_sha(Design.load(EXAMPLE))


def _fake_run(run_dir: Path, log: str, t_end: float = 1200.0) -> None:
    run_dir.mkdir(parents=True)
    (run_dir / "deck.fds").write_text(f"&HEAD CHID='x' /\n&TIME T_END={t_end} /\n")
    (run_dir / "x.out").write_text(log)


def test_without_fds_the_step_says_so_and_offers_no_start(run_view, monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path, ["the fds binary is not on PATH"])
    at = run_view("cfd")
    assert not at.exception
    assert any("fds binary" in m.value for m in at.markdown)
    assert all(b.key != "fds_start" for b in at.button)
    assert not at.get("file_uploader")


def test_with_fds_ready_the_start_button_names_the_default_window(run_view, monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path, [])
    at = run_view("cfd")
    assert at.radio(key="fds_minutes").value == "20 min"
    assert at.button(key="fds_start").label == "Start FDS run (20 min)"


def test_start_writes_the_shortened_deck_and_launches(run_view, monkeypatch, tmp_path):
    run_dir = _isolate(monkeypatch, tmp_path, [])
    launched = []
    monkeypatch.setattr(fds_runner, "run", lambda deck, out: launched.append((deck, out)) or out.name)
    at = run_view("cfd")
    at.radio(key="fds_minutes").set_value("5 min").run()
    at.button(key="fds_start").click().run()
    assert launched and launched[0][1] == run_dir
    assert "T_END=300.0" in (run_dir / "deck.fds").read_text()


def test_a_running_run_shows_progress_and_hides_start(run_view, monkeypatch, tmp_path):
    run_dir = _isolate(monkeypatch, tmp_path, [])
    _fake_run(run_dir, "Time Step 10\n Total Time:  120.0 s\n")
    at = run_view("cfd")
    assert not at.exception
    assert at.get("progress") and all(b.key != "fds_start" for b in at.button)
    assert any("Preliminary" in c.value or "not written" in c.value for c in at.info + at.caption)


def test_a_finished_run_reads_tier_two_and_correlates(run_view, monkeypatch, tmp_path):
    run_dir = _isolate(monkeypatch, tmp_path, [])
    _fake_run(run_dir, "Total Time: 1200.0 s\nSTOP: FDS completed successfully\n")
    tier1 = envelope.run(Design.load(EXAMPLE))
    monkeypatch.setattr(fds_reader, "read", lambda d, design: tier1)
    at = run_view("cfd")
    assert not at.exception
    assert at.session_state["tier2_result"] is not None
    assert any(m.value.startswith("# Correlation") for m in at.markdown)
    assert at.button(key="open_smv").disabled
    assert at.button(key="fds_start").label.startswith("Re-run FDS")


def test_stamp_changes_when_a_slice_file_changes(tmp_path):
    from app.views import cfd
    (tmp_path / "a_1_1.sf").write_bytes(b"1")
    before = cfd.stamp(tmp_path)
    (tmp_path / "a_1_1.sf").write_bytes(b"12")
    assert cfd.stamp(tmp_path) != before
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_app_cfd_step.py -q`
Expected: FAIL — `ModuleNotFoundError: app.views.cfd`.

- [ ] **Step 3: Write `app/views/cfd.py`**

```python
"""Step 4: run the design in FDS and watch the CFD field on the same twin canvas.

Deck generation works anywhere; running needs FDS, which the pre-flight reports
honestly. The run directory is `runs/<design sha>` — the CLI's and the deck's
own CHID — so a run launched from the terminal, or one that outlived an app
restart, is picked up rather than relaunched.
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from app import state
from app.components import twin_canvas
from app.views.fire_test import ensure_trace
from app.views.result import ensure_result
from solit2.engines.fds import deck as fds_deck
from solit2.engines.fds import reader as fds_reader
from solit2.engines.fds import runner as fds_runner
from solit2.engines.fds import slices
from solit2.engines.reduced.envelope import _design_sha
from solit2.engines.reduced.state import RunTrace
from solit2.reports import correlation
from solit2.schema.design import Design
from solit2.schema.result import Result

RUNS_DIR = Path("runs")
DURATIONS = {"5 min": 5.0, "10 min": 10.0, "20 min": 20.0, "Full (design duration)": None}
DEFAULT_DURATION = "20 min"
QUANTITIES = (("Temperature", "TEMPERATURE"), ("Smoke", "SOOT DENSITY"), ("Mist", "MPUV"))
POLL = "10s"


def run_dir_for(design: Design) -> Path:
    return RUNS_DIR / _design_sha(design)


def stamp(run_dir: Path) -> tuple:
    """Names, sizes and mtimes of the slice files: the cache key for a re-read."""
    return tuple(sorted((p.name, p.stat().st_size, p.stat().st_mtime_ns)
                        for p in Path(run_dir).glob("*.sf")))


@st.cache_data(show_spinner=False)
def _load_slice(run_dir: str, quantity: str, stamp_key: tuple):
    """`stamp_key` is unused in the body: it exists so the cache re-reads when a file grows."""
    return slices.load_centreline(Path(run_dir), quantity)


def _preflight() -> list[str]:
    problems = fds_runner.preflight()
    chips = ("".join(f'<span class="chip fail">{p}</span>' for p in problems)
             or '<span class="chip pass">FDS ready</span>')
    st.markdown(chips, unsafe_allow_html=True)
    return problems


def _start_controls(design: Design, run_dir: Path, verb: str) -> None:
    st.caption("A Tier 2 run takes hours. It runs in the background; this page keeps up with it.")
    choice = st.radio("Simulated window", list(DURATIONS), horizontal=True, key="fds_minutes",
                      index=list(DURATIONS).index(DEFAULT_DURATION),
                      help="Shortens the run, not the system: the tank and the cost index "
                           "still size on the design's full discharge duration.")
    minutes = DURATIONS[choice]
    if st.button(f"{verb} ({choice})", key="fds_start", type="primary"):
        run_dir.mkdir(parents=True, exist_ok=True)
        deck_path = run_dir / "deck.fds"
        deck_path.write_text(fds_deck.generate(
            design, t_end_s=None if minutes is None else minutes * 60.0))
        fds_runner.run(deck_path, run_dir)
        st.rerun()


@st.fragment(run_every=POLL)
def _live_progress(run_dir: Path) -> None:
    status = fds_runner.status(run_dir)
    st.progress(min(status["progress"], 1.0),
                text=f"FDS running — {status['progress'] * 100:.0f} % of the simulated window. "
                     f"{status['detail']}".strip())
    if status["state"] != "running":
        st.rerun(scope="app")


def _canvas(design: Design, trace: RunTrace, run_dir: Path, running: bool) -> None:
    for tab, (label, quantity) in zip(st.tabs([label for label, _ in QUANTITIES]), QUANTITIES):
        with tab:
            slice_ = _load_slice(str(run_dir), quantity, stamp(run_dir))
            if slice_ is None:
                st.info("FDS has not written this slice yet." if running
                        else f"This run holds no {label.lower()} slice.")
                continue
            st.plotly_chart(twin_canvas.figure(design, trace, cfd=slice_), key=f"cfd_{quantity}")
            last = float(slice_.t_s[-1])
            st.caption(f"Preliminary — last complete frame at t = {last:.0f} s; the run is still going."
                       if running else f"{len(slice_.t_s)} frames to t = {last:.0f} s.")


def _smokeview(run_dir: Path) -> None:
    ready = fds_runner.smokeview_binary() is not None and any(run_dir.glob("*.smv"))
    if st.button("Open in Smokeview", key="open_smv", disabled=not ready):
        fds_runner.open_smokeview(run_dir)
    if not ready:
        st.caption("Smokeview opens on this machine once the run has written its .smv file "
                   f"and a smokeview binary is on PATH (or {fds_runner.SMV_ENV} is set).")


def _tier2(design: Design, run_dir: Path, tier1: Result) -> None:
    tier2 = state.get_tier2_result()
    if tier2 is None:
        try:
            tier2 = fds_reader.read(run_dir, design)
        except (OSError, ValueError, KeyError) as exc:
            st.error(f"The run finished but its result could not be read: {exc}")
            return
        state.set_tier2_result(tier2)
    st.subheader("Tier 1 vs Tier 2")
    for warning in tier2.warnings:
        st.warning(warning)
    st.markdown(correlation.render(tier1, tier2))


def render() -> None:
    st.header("CFD verify — Tier 2")
    design = state.get_design()
    if design is None:
        st.info("Build a design first.")
        return
    result = ensure_result(design)
    trace = ensure_trace(design, result)
    problems = _preflight()
    run_dir = run_dir_for(design)
    status = fds_runner.status(run_dir) if run_dir.exists() else None
    running = status is not None and status["state"] == "running"

    if running:
        _live_progress(run_dir)
    elif not problems:
        _start_controls(design, run_dir, "Re-run FDS" if status else "Start FDS run")
    if status is not None and status["state"] == "failed":
        st.error(f"The last FDS run did not finish: {status['detail']}")
    if status is None:
        st.info("Start a run to see the CFD field here.")
        return
    _canvas(design, trace, run_dir, running)
    _smokeview(run_dir)
    if status["state"] == "done":
        _tier2(design, run_dir, result)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_app_cfd_step.py -q`
Expected: 6 passed.

- [ ] **Step 5: Commit**

```bash
uv run ruff check app tests && git add app/views/cfd.py tests/test_app_cfd_step.py && git commit -m "feat(ui): CFD step — duration picker, live progress, slice heatmaps, Smokeview, Tier 1 vs 2"
```

---

### Task 13: Step 5 — Reports view (twin correlation, exports)

**Files:**
- Modify: `app/views/reports.py` (rewrite)
- Test: `tests/test_app_reports_step.py`

**Interfaces:**
- Consumes: `ensure_result`, `twin.test_facility_twin`, `envelope.run`, `test_plan.render(design, result)`, `correlation.render(test_result, site_result)`.
- Produces: `ensure_twin_result(design) -> tuple[Design, Result] | None`; download-button keys `export_0 … export_N`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_app_reports_step.py
from solit2 import history
from solit2.reports import twin


def test_reports_step_builds_and_runs_the_twin_and_offers_exports(run_view, monkeypatch, tmp_path):
    monkeypatch.setattr(history, "DEFAULT_PATH", tmp_path / "h.jsonl")
    at = run_view("reports", timeout=180)
    assert not at.exception
    assert at.session_state["twin_result"] is not None
    bodies = [m.value for m in at.markdown]
    assert any(b.startswith("# Test Plan") for b in bodies)
    assert any(b.startswith("# Correlation") for b in bodies)
    assert any("gallery" in i.value for i in at.info)
    assert any("Run the CFD step" in c.value for c in at.caption)
    assert len(at.get("download_button")) >= 5 and not at.get("file_uploader")


def test_a_twin_that_cannot_be_built_is_reported_and_the_rest_still_renders(run_view, monkeypatch, tmp_path):
    monkeypatch.setattr(history, "DEFAULT_PATH", tmp_path / "h.jsonl")
    def boom(design):
        raise ValueError("nozzle mounting cannot be reproduced in the 5.20 m test gallery")
    monkeypatch.setattr(twin, "test_facility_twin", boom)
    at = run_view("reports", timeout=180)
    assert not at.exception
    assert any("test gallery" in e.value for e in at.error)
    assert any(m.value.startswith("# Test Plan") for m in at.markdown)
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_app_reports_step.py -q`
Expected: FAIL — the current view shows `file_uploader`s and never sets `twin_result`.

- [ ] **Step 3: Rewrite `app/views/reports.py`**

```python
"""Step 5: the documents this design produces. Nothing here is uploaded — every
input is what the earlier steps already computed, and the exports are the
only downloads in the wizard."""
from __future__ import annotations

import streamlit as st

from app import state
from app.views.result import ensure_result
from solit2.engines.reduced import envelope
from solit2.reports import correlation, test_plan, twin
from solit2.schema.design import Design
from solit2.schema.result import Result

EXPORT_COLUMNS = 3


def ensure_twin_result(design: Design) -> tuple[Design, Result] | None:
    """The test-facility twin and its Tier 1 result, or None after reporting why not."""
    try:
        twin_design = twin.test_facility_twin(design)
    except ValueError as exc:
        st.error(f"The test-facility twin could not be built: {exc}")
        return None
    result = state.get_twin_result()
    if result is None:
        try:
            with st.spinner("Running the test-facility twin…"):
                result = envelope.run(twin_design)
        except (ArithmeticError, RuntimeError, ValueError, KeyError) as exc:
            st.error(f"The test-facility twin could not be run: {exc}")
            return None
        state.set_twin_result(result)
    return twin_design, result


def _exports(items: list[tuple[str, str, str]]) -> None:
    st.subheader("Export")
    columns = st.columns(EXPORT_COLUMNS)
    for i, (file_name, data, label) in enumerate(items):
        columns[i % EXPORT_COLUMNS].download_button(label, data, file_name=file_name,
                                                    key=f"export_{i}", width="stretch")


def render() -> None:
    st.header("Reports")
    design = state.get_design()
    if design is None:
        st.info("Build a design first.")
        return
    result = ensure_result(design)
    name = design.meta.name
    exports = [(f"{name}.json", design.model_dump_json(indent=2), "Design JSON"),
               (f"{name}-result.json", result.model_dump_json(indent=2), "Tier 1 result JSON")]

    st.subheader("Test plan")
    plan_md = test_plan.render(design, result)
    st.markdown(plan_md)
    exports.append((f"{name}-test-plan.md", plan_md, "Test plan (.md)"))

    st.subheader("Site vs test facility")
    pair = ensure_twin_result(design)
    if pair is not None:
        twin_design, twin_result = pair
        st.info(twin_design.meta.notes)
        site_vs_test = correlation.render(twin_result, result)
        st.markdown(site_vs_test)
        exports += [("correlation-site-vs-test-facility.md", site_vs_test,
                     "Site vs test facility (.md)"),
                    (f"{twin_design.meta.name}-result.json", twin_result.model_dump_json(indent=2),
                     "Twin result JSON")]

    st.subheader("Tier 1 vs Tier 2")
    tier2 = state.get_tier2_result()
    if tier2 is None:
        st.caption("Run the CFD step to add the Tier 2 comparison.")
    else:
        tiers = correlation.render(result, tier2)
        st.markdown(tiers)
        exports += [("correlation-tier1-vs-tier2.md", tiers, "Tier 1 vs Tier 2 (.md)"),
                    (f"{name}-fds-result.json", tier2.model_dump_json(indent=2),
                     "Tier 2 result JSON")]
    _exports(exports)
```

- [ ] **Step 4: Run tests**

Run: `uv run pytest tests/test_app_reports_step.py -q`
Expected: 2 passed. (`tests/test_app_reports_view.py` will now fail — deleted in Task 14.)

- [ ] **Step 5: Commit**

```bash
uv run ruff check app tests && git add app/views/reports.py tests/test_app_reports_step.py && git commit -m "feat(ui): reports step correlates against the auto-built test-facility twin; exports only"
```

---

### Task 14: Wire the shell, retire the old pages, end-to-end wizard test

**Files:**
- Modify: `app/streamlit_app.py` (rewrite)
- Delete: `app/views/run.py`, `app/views/tunnel.py`, `app/views/leaderboard.py`, `app/views/verify.py`, `tests/test_app_design_view.py`, `tests/test_app_run_view.py`, `tests/test_app_tunnel_view.py`, `tests/test_app_leaderboard_view.py`, `tests/test_app_verify_view.py`, `tests/test_app_reports_view.py`
- Test: `tests/test_app_wizard.py`

**Interfaces:**
- Consumes: everything above. Widget key `goto_design`.

- [ ] **Step 1: Write the failing end-to-end test**

```python
# tests/test_app_wizard.py
"""The real app, headless: five steps, automatic hand-off, no file movement."""
from streamlit.testing.v1 import AppTest

from app.views import cfd
from solit2 import history

APP = "../app/streamlit_app.py"


def _app(monkeypatch, tmp_path) -> AppTest:
    monkeypatch.setattr(history, "DEFAULT_PATH", tmp_path / "h.jsonl")
    monkeypatch.setattr(cfd, "RUNS_DIR", tmp_path / "runs")
    at = AppTest.from_file(APP, default_timeout=180)
    at.run()
    return at


def test_landing_is_the_design_step_with_later_steps_locked(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    assert not at.exception
    assert at.session_state.get("step", 1) == 1
    assert not at.button(key="step_1").disabled
    assert all(at.button(key=f"step_{i}").disabled for i in range(2, 6))
    assert not at.sidebar.radio


def test_build_and_continue_runs_tier_one_without_another_click(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    at.button(key="build_design").click().run()
    assert at.session_state["step"] == 2
    assert at.session_state["result"] is not None
    assert any('class="verdict' in m.value for m in at.markdown)
    assert (tmp_path / "h.jsonl").exists()


def test_every_step_renders_and_none_asks_for_a_file(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    at.button(key="build_design").click().run()
    for i in range(2, 6):
        at.button(key=f"step_{i}").click().run()
        assert not at.exception, i
        assert at.session_state["step"] == i
        assert not at.get("file_uploader"), i
    assert at.session_state["twin_result"] is not None
    assert at.get("download_button")            # exports live on the last step only


def test_back_and_next_walk_the_wizard(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    at.button(key="build_design").click().run()
    at.button(key="nav_next").click().run()
    assert at.session_state["step"] == 3
    at.button(key="nav_back").click().run()
    at.button(key="nav_back").click().run()
    assert at.session_state["step"] == 1


def test_a_later_step_without_a_design_offers_the_way_back(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    at.session_state["step"] = 3
    at.run()
    assert not at.exception
    at.button(key="goto_design").click().run()
    assert at.session_state["step"] == 1
```

- [ ] **Step 2: Run to verify failure**

Run: `uv run pytest tests/test_app_wizard.py -q`
Expected: FAIL — the sidebar radio still exists; no `step_1` button.

- [ ] **Step 3: Rewrite `app/streamlit_app.py`**

```python
"""Entry point. Run with: uv run streamlit run app/streamlit_app.py"""
from __future__ import annotations

import streamlit as st

from app import state, theme
from app.components import stepper
from app.views import cfd, design, fire_test, reports, result

st.set_page_config(page_title="SOLIT2 Simulator", layout="wide",
                   initial_sidebar_state="collapsed")
theme.inject()

VIEWS = {1: design.render, 2: result.render, 3: fire_test.render,
         4: cfd.render, 5: reports.render}

stepper.render_header()
step = state.get_step()
if step > state.STEP_MIN and state.get_design() is None:
    st.info("Build a design first — every later step is computed from it.")
    if st.button("Go to Design", key="goto_design", type="primary"):
        state.set_step(state.STEP_MIN)
        st.rerun()
else:
    VIEWS[step]()
stepper.render_footer()
```

- [ ] **Step 4: Delete the retired pages and their tests**

```bash
git rm -q app/views/run.py app/views/tunnel.py app/views/leaderboard.py app/views/verify.py tests/test_app_design_view.py tests/test_app_run_view.py tests/test_app_tunnel_view.py tests/test_app_leaderboard_view.py tests/test_app_verify_view.py tests/test_app_reports_view.py
```

Then `grep -rn "views import\|views\.\(run\|tunnel\|leaderboard\|verify\)" app tests` must show only the five live views.

- [ ] **Step 5: Run the full suite and lint**

Run: `uv run ruff check app solit2 tests && uv run pytest -q`
Expected: all pass, including `tests/test_independence.py`. If `test_cli.py::test_run_with_engine_fds_refuses_without_a_binary` fails because FDS *is* on this machine's PATH, that is pre-existing and environment-dependent — note it in the report; do not change the test.

- [ ] **Step 6: Commit**

```bash
git add app/streamlit_app.py tests/test_app_wizard.py && git commit -m "feat(ui): five-step wizard shell replaces the six pages; retire the old views"
```

---

## Execution notes

- **Order matters only where interfaces flow:** 1 → 2 (theme classes, state) → 6 → 7 (canvas) → 8 (hmi imports `mmss`) → 9 (conftest) → 10 (`ensure_result`) → 11 (`ensure_trace`) → 12 → 13 → 14. Tasks 3, 4, 5 are independent of the UI chain and can be done in any order after Task 2, but never in parallel with another implementer (one worktree).
- **Model tiers:** Tasks 1, 2, 4, 5, 9, 10, 13 are transcription-plus-tests — cheap tier. Tasks 3, 6, 7, 8, 11, 12, 14 touch several interfaces or Plotly/Streamlit behaviour — mid tier. Reviews: mid tier throughout; the final whole-branch review on the most capable tier.
- **Browser check (controller, after Task 14, not the implementer):** restart the `solit2-streamlit` preview, build a design, walk steps 2 → 5, and confirm: pills highlight and lock correctly; the verdict banner colours; the twin plays (▶) and the clock slider moves the readouts; the CFD step shows "FDS ready" and the 20-min default; the Reports step shows the twin note and exports. Screenshot each step for the user. Then run `git status` — `.claude/launch.json` must no longer be dirty.
- **Known environment dependency:** `tests/test_cli.py::test_run_with_engine_fds_refuses_without_a_binary` assumes no FDS on PATH; on this machine FDS is installed at `~/FDS/native/bin` but not on the shell PATH by default, so it passes under plain `uv run pytest`. Do not run the suite from a shell that has exported the launch.json PATH.

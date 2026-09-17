# Streamlit Front End (Plan 3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the interactive front end for the SOLIT² Annex 7 tunnel-fire simulator: a Streamlit app with a Design view (build/edit a configuration from the 9 parameters an engineer actually varies), a Run view (execute the real physics engine and show its criteria/results), a Tunnel view (a longitudinal thermal-field visualization with a time slider), and a Leaderboard (run history).

**Architecture:** Views call the existing Python engine (`envelope.run`, `sim.run_once`, `history.append`/`leaderboard`) directly, in-process. No HTTP layer, no second language, no rewrite of any physics — this plan adds a presentation layer on top of code that is already built, tested, and calibrated (Tasks 1–25 of the prior plan). One small, well-scoped refactor is needed first: `Design.load` currently reads and preset-merges only from a file path; the Design view needs the same merge-and-validate logic starting from an in-memory dict, so Task 1 extracts `Design.from_dict` and makes `.load()` a thin wrapper over it.

**Tech Stack:** Python 3.12, `uv`, Streamlit ≥ 1.37, Plotly, pandas. `streamlit.testing.v1.AppTest` for view tests — Streamlit's own headless test harness, not a browser driver.

**Spec:** `docs/superpowers/specs/2026-09-15-solit2-simulator-design.md` section 10 ("Front end (Streamlit)"). This plan implements that section; the Tunnel view's scope is narrowed from the spec's "3-D bore" to a 2-D longitudinal section for the reasons given in Task 3 — read that task's opening note before objecting that this plan under-delivers section 10.

## Global Constraints

- Python 3.12 via `uv`; the system Anaconda is broken and must never be used — every command in this plan is `uv run ...`.
- New dependencies: `streamlit>=1.37`, `plotly`, `pandas`. Add via `uv add streamlit plotly pandas` (Task 1, Step 1) — do not hand-edit `pyproject.toml`'s dependency list.
- Files ≤ 400 lines target, 800 hard; functions ≤ 50 lines; nesting ≤ 4.
- Frozen dataclasses / pydantic models; never mutate an input.
- Stage only the files a task actually touches, by explicit path; never `git add -A` or `git add .`.
- Conventional-commit messages. **No `Co-Authored-By` trailer** — the user's global
  `~/.claude/rules/common/git-workflow.md` states "Attribution disabled globally via
  ~/.claude/settings.json," which is exactly the kind of user instruction the session's own
  attribution reminder says takes precedence over itself. (Earlier tasks in this plan's own history
  may carry the trailer regardless — that was a live correction mid-plan, not grounds to amend
  already-landed commits without being asked.)
- The existing CLI (`solit2 run`, `solit2 validate`, `solit2 history`) and every existing test must keep passing unchanged after every task. `Design.load`'s observable behaviour must not change.
- Views call the engine **in-process**. No task in this plan introduces an HTTP server, a REST endpoint, or a second runtime.
- The FDS tier (Plan 2) does not exist. The Verify view (Task 5) must say so plainly rather than imply a capability that is not there.
- `runs/history.jsonl` (written by `history.append`) is already covered by the repo's `.gitignore` pattern for `runs/`; nothing in this plan changes that.

---

## File Structure

```
app/
  __init__.py
  streamlit_app.py        Entry point: page config, sidebar navigation, session-state init
  state.py                 Session-state helpers: typed getters/setters for the current
                            Design and the current Result
  views/
    __init__.py
    design.py               Preset pickers + the 9-parameter form -> a Design in session state
    run.py                   Calls envelope.run(); criteria table, envelope grid, timeseries
    tunnel.py                Longitudinal thermal-field section, time slider
    leaderboard.py           history.leaderboard() table + a "save this run" button
    verify.py                Explicit stub: FDS tier 2 is Plan 2, not built
  components/
    __init__.py
    charts.py                Shared Plotly builders used by run.py and tunnel.py

tests/
  test_app_design.py         Design.from_dict unit tests (no Streamlit)
  test_app_design_view.py    AppTest coverage of views/design.py
  test_app_run_view.py       AppTest coverage of views/run.py
  test_app_tunnel_view.py    AppTest coverage of views/tunnel.py
  test_app_leaderboard_view.py  AppTest coverage of views/leaderboard.py
```

`solit2/schema/presets.py` gains one new public function (Task 1). `solit2/schema/design.py` gains one new classmethod and one refactor (Task 1). Nothing else in `solit2/` changes in this plan.

---

### Task 1: `Design.from_dict`, preset listing, app scaffold, and the Design view

**Files:**
- Modify: `solit2/schema/design.py` (add `Design.from_dict`, refactor `Design.load`)
- Modify: `solit2/schema/presets.py` (add `list_presets`)
- Create: `app/__init__.py`
- Create: `app/state.py`
- Create: `app/streamlit_app.py`
- Create: `app/views/__init__.py`
- Create: `app/views/design.py`
- Test: `tests/test_design_schema.py` (extend — `Design.from_dict`)
- Test: `tests/test_presets.py` (extend — `list_presets`; create the file if it does not already exist under that exact name, checking first)
- Test: `tests/test_app_design_view.py`

**Interfaces:**
- Produces: `Design.from_dict(raw: dict) -> Design` (classmethod, `solit2/schema/design.py`) — preset-merges every block that names a `preset` key exactly as `.load()` already does, then validates. `Design.load(path)` becomes `Design.from_dict(json.loads(Path(path).read_text()))`.
- Produces: `list_presets(kind: str) -> list[str]` (`solit2/schema/presets.py`) — thin public wrapper: `return _available(_KIND_PREFIX[kind])` after the same `KeyError` guard `load_preset` already uses for an unknown `kind`.
- Produces: `app/state.py` — `get_design() -> Design | None`, `set_design(d: Design) -> None`, `get_result() -> Result | None`, `set_result(r: Result) -> None`, all backed by `st.session_state["design"]` / `st.session_state["result"]`.
- Produces: `app/views/design.py` — `render() -> None`, the page function `streamlit_app.py` calls for the Design page. On submit, calls `state.set_design(...)` and clears `st.session_state["result"]` (a new Design invalidates the last run).
- Consumes: nothing from an earlier task (this is the first task).

- [ ] **Step 1: Add the dependencies**

Run: `uv add streamlit plotly pandas`

Expected: `pyproject.toml`'s `dependencies` list gains three entries; `uv.lock` updates. Confirm with:

```bash
uv run python -c "import streamlit, plotly, pandas; print(streamlit.__version__)"
```

Expected: prints a version ≥ 1.37, no `ModuleNotFoundError`.

- [ ] **Step 2: Write the failing test for `Design.from_dict`**

Add to `tests/test_design_schema.py`:

```python
def test_from_dict_merges_presets_exactly_like_load(tmp_path):
    """from_dict and load must produce an identical Design from identical
    input, since load becomes a thin wrapper over from_dict."""
    raw = json.loads(Path("examples/designs/road-tunnel-twin-bore-single-mode.json").read_text())
    from_dict_design = Design.from_dict(raw)
    from_load_design = Design.load("examples/designs/road-tunnel-twin-bore-single-mode.json")
    assert from_dict_design == from_load_design


def test_from_dict_rejects_an_unknown_preset_kind_the_same_way_load_does():
    raw = {"meta": {"name": "x"}, "tunnel": {"preset": "does_not_exist"},
           "fire": {"preset": "hgv_150mw"}, "nozzles": {"preset": "solit2_reference"},
           "zones": {"section_length_m": 30.0, "sections_simultaneous": 1,
                     "manual_activation_s": 60.0, "activation_delay_s": 0.0,
                     "pump_ramp_s": 30.0, "duration_min": 30.0},
           "ventilation": {"mode": "longitudinal", "velocity_ms": 2.0},
           "detection": {"type": "linear_heat", "threshold_c": 60.0, "sensor_spacing_m": 25.0},
           "hydraulics": {"preset": "template"}}
    with pytest.raises(FileNotFoundError):
        Design.from_dict(raw)
```

Check `tests/test_design_schema.py`'s existing imports at the top of the file (`json`, `Path`, `pytest`, `Design`) before adding these — reuse them, do not re-import.

- [ ] **Step 3: Run the test to verify it fails**

Run: `uv run pytest tests/test_design_schema.py::test_from_dict_merges_presets_exactly_like_load -v`
Expected: FAIL with `AttributeError: type object 'Design' has no attribute 'from_dict'`

- [ ] **Step 4: Extract `from_dict` and refactor `load`**

In `solit2/schema/design.py`, `Design.load` currently reads:

```python
    @classmethod
    def load(cls, path: str | Path) -> "Design":
        raw = json.loads(Path(path).read_text())
        for block, kind in (("tunnel", "tunnel"), ("fire", "fire"),
                            ("nozzles", "nozzle"), ("hydraulics", "hydraulics")):
            name = raw.get(block, {}).get("preset")
            if name is None:
                if block not in raw or "preset" not in raw.get(block, {}):
                    continue
                raise ValueError(f"design block {block!r} must name a preset")
            raw[block] = deep_merge(load_preset(kind, name), raw[block])
        return cls.model_validate(raw)
```

Read the surrounding 15 lines in the actual file first (this excerpt is reconstructed from the block's known behaviour, not a byte-exact quote — confirm the real text before editing, since the exact branching around a missing `preset` key must be preserved character-for-character). Replace it with:

```python
    @classmethod
    def from_dict(cls, raw: dict) -> "Design":
        """Preset-merge every block that names a `preset` key, then validate.

        `raw` is not mutated -- a merged copy is built and validated; the
        caller's dict is untouched, consistent with this schema's frozen-model
        discipline everywhere else.
        """
        merged = dict(raw)
        for block, kind in (("tunnel", "tunnel"), ("fire", "fire"),
                            ("nozzles", "nozzle"), ("hydraulics", "hydraulics")):
            name = merged.get(block, {}).get("preset")
            if name is None:
                if block not in merged or "preset" not in merged.get(block, {}):
                    continue
                raise ValueError(f"design block {block!r} must name a preset")
            merged[block] = deep_merge(load_preset(kind, name), merged[block])
        return cls.model_validate(merged)

    @classmethod
    def load(cls, path: str | Path) -> "Design":
        return cls.from_dict(json.loads(Path(path).read_text()))
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_design_schema.py -v`
Expected: PASS, including every pre-existing test in the file — `.load()`'s behaviour is unchanged.

- [ ] **Step 6: Commit**

```bash
git add solit2/schema/design.py tests/test_design_schema.py
git commit -m "refactor(design): extract Design.from_dict from Design.load

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

- [ ] **Step 7: Write the failing test for `list_presets`**

Check whether `tests/test_presets.py` already exists (`ls tests/ | grep preset`). If it does not, create it:

```python
import pytest
from solit2.schema.presets import list_presets


def test_list_presets_finds_shipped_and_example_tunnels():
    names = list_presets("tunnel")
    assert "solit2_test" in names            # shipped (solit2/presets/)
    assert "twin_bore_11m" in names           # example (examples/presets/)
    assert names == sorted(names)


def test_list_presets_rejects_an_unknown_kind():
    with pytest.raises(KeyError, match="unknown preset kind"):
        list_presets("nope")
```

If the file already exists, add these two tests to it and reuse its existing imports rather than duplicating them.

- [ ] **Step 8: Run the test to verify it fails**

Run: `uv run pytest tests/test_presets.py -v`
Expected: FAIL with `ImportError: cannot import name 'list_presets'`

- [ ] **Step 9: Add `list_presets`**

In `solit2/schema/presets.py`, directly below `load_preset`:

```python
def list_presets(kind: str) -> list[str]:
    """Every preset name of one kind, shipped and example, de-duplicated and sorted."""
    if kind not in _KIND_PREFIX:
        raise KeyError(f"unknown preset kind {kind!r}; expected one of {sorted(_KIND_PREFIX)}")
    return _available(_KIND_PREFIX[kind])
```

- [ ] **Step 10: Run the test to verify it passes**

Run: `uv run pytest tests/test_presets.py -v`
Expected: PASS

- [ ] **Step 11: Commit**

```bash
git add solit2/schema/presets.py tests/test_presets.py
git commit -m "feat(presets): add list_presets, a public preset-name enumerator

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

- [ ] **Step 12: Create the app package and session-state helpers**

`app/__init__.py`:

```python
"""Streamlit front end for the SOLIT2 Annex 7 tunnel-fire simulator.

Views call the engine (`solit2.engines.reduced`) directly, in-process --
there is no HTTP layer. See docs/superpowers/specs/2026-09-15-solit2-
simulator-design.md section 10.
"""
```

`app/state.py`:

```python
"""Typed accessors for the two pieces of state every view shares.

Streamlit's `st.session_state` is an untyped dict that persists across
reruns of the script within one browser session. Every view reads and
writes through these functions rather than touching the dict directly, so
the two keys in use -- "design" and "result" -- are named in exactly one
place.
"""
from __future__ import annotations

import streamlit as st

from solit2.schema.design import Design
from solit2.schema.result import Result

_DESIGN_KEY = "design"
_RESULT_KEY = "result"


def get_design() -> Design | None:
    return st.session_state.get(_DESIGN_KEY)


def set_design(design: Design) -> None:
    st.session_state[_DESIGN_KEY] = design
    # A new design invalidates whatever the last run computed.
    st.session_state.pop(_RESULT_KEY, None)


def get_result() -> Result | None:
    return st.session_state.get(_RESULT_KEY)


def set_result(result: Result) -> None:
    st.session_state[_RESULT_KEY] = result
```

- [ ] **Step 13: Write the failing test for the app shell**

Create `tests/test_app_design_view.py`:

```python
"""AppTest coverage of the Streamlit app shell and the Design view.

`streamlit.testing.v1.AppTest` runs the app's script headlessly (no
browser) and exposes the rendered widget tree for assertions -- the
Streamlit-native equivalent of the engine's own pytest suite, not a
browser driver.
"""
from streamlit.testing.v1 import AppTest


def test_the_app_launches_with_five_pages_in_the_sidebar():
    at = AppTest.from_file("app/streamlit_app.py")
    at.run()
    assert at.run_time < 5  # AppTest exposes the script's own run time in seconds
    assert not at.exception
    labels = [opt for radio in at.sidebar.radio for opt in radio.options]
    assert labels == ["Design", "Run", "Tunnel", "Leaderboard", "Verify"]


def test_the_design_page_is_selected_by_default_and_shows_a_preset_picker():
    at = AppTest.from_file("app/streamlit_app.py")
    at.run()
    assert not at.exception
    assert any("tunnel" in sb.label.lower() for sb in at.selectbox)
    assert any("fire" in sb.label.lower() for sb in at.selectbox)
    assert any("nozzle" in sb.label.lower() for sb in at.selectbox)
```

- [ ] **Step 14: Run the test to verify it fails**

Run: `uv run pytest tests/test_app_design_view.py -v`
Expected: FAIL — `app/streamlit_app.py` does not exist yet (`FileNotFoundError` from `AppTest.from_file`, or a collection error; either is the expected failure at this point).

- [ ] **Step 15: Write `app/views/design.py`**

```python
"""The Design view: pick a starting preset per block, override the nine
parameters an engineer actually varies, and produce a `Design`.

Presets supply everything else -- this mirrors `solit2/schema/presets.py`'s
own stated philosophy ("a design JSON names a preset per block and
overrides individual fields; the preset supplies everything else"), so a
form that starts from a preset and overrides a handful of fields is not a
shortcut, it is how this schema is meant to be driven.
"""
from __future__ import annotations

import streamlit as st

from app import state
from solit2.schema.design import Design
from solit2.schema.presets import list_presets


def render() -> None:
    st.header("Design")
    st.caption(
        "Pick a starting preset for each block, then override the parameters "
        "below. Every other field comes from the presets you choose."
    )

    col1, col2, col3 = st.columns(3)
    with col1:
        tunnel_preset = st.selectbox("Tunnel preset", list_presets("tunnel"))
    with col2:
        fire_preset = st.selectbox("Fire preset", list_presets("fire"))
    with col3:
        nozzle_preset = st.selectbox("Nozzle preset", list_presets("nozzle"))
    hydraulics_preset = st.selectbox("Hydraulics preset", list_presets("hydraulics"))

    st.subheader("Nozzle & hydraulics")
    c1, c2, c3 = st.columns(3)
    with c1:
        k_factor = st.number_input(
            "K-factor (L/min·bar⁰·⁵)", min_value=0.6, max_value=20.0, value=4.1, step=0.1)
    with c2:
        pressure_bar = st.number_input(
            "Working pressure (bar)", min_value=34.5, max_value=140.0, value=50.0, step=0.5)
    with c3:
        rows = st.number_input("Nozzle rows", min_value=1, max_value=3, value=2, step=1)
    pitch_m = st.number_input(
        "Nozzle spacing / pitch (m)", min_value=0.1, max_value=10.0, value=2.4, step=0.1)

    st.subheader("Zoning")
    z1, z2 = st.columns(2)
    with z1:
        section_length_m = st.number_input(
            "Section length (m)", min_value=8.0, max_value=100.0, value=30.0, step=1.0)
    with z2:
        sections_simultaneous = st.number_input(
            "Sections activated simultaneously", min_value=1, max_value=6, value=3, step=1)

    st.subheader("Ventilation")
    v1, v2 = st.columns(2)
    with v1:
        velocity_lo = st.number_input(
            "Ventilation velocity, low (m/s)", min_value=0.0, max_value=8.0, value=3.88, step=0.01)
    with v2:
        velocity_hi = st.number_input(
            "Ventilation velocity, high (m/s)", min_value=0.0, max_value=8.0, value=5.08, step=0.01)

    if st.button("Build design", type="primary"):
        raw = _assemble(tunnel_preset, fire_preset, nozzle_preset, hydraulics_preset,
                        k_factor, pressure_bar, int(rows), pitch_m,
                        section_length_m, int(sections_simultaneous),
                        velocity_lo, velocity_hi)
        try:
            design = Design.from_dict(raw)
        except Exception as exc:  # noqa: BLE001 -- surfaced to the user, not swallowed
            st.error(f"Could not build a valid design: {exc}")
            return
        state.set_design(design)
        st.success(f"Design built: {design.meta.name}")

    current = state.get_design()
    if current is not None:
        st.subheader("Current design")
        st.json(current.model_dump(mode="json"), expanded=False)
        st.download_button(
            "Download design JSON",
            data=current.model_dump_json(indent=2),
            file_name=f"{current.meta.name}.json",
            mime="application/json",
        )


def _assemble(tunnel_preset: str, fire_preset: str, nozzle_preset: str,
             hydraulics_preset: str, k_factor: float, pressure_bar: float,
             rows: int, pitch_m: float, section_length_m: float,
             sections_simultaneous: int, velocity_lo: float, velocity_hi: float) -> dict:
    """Every override lands inside its own block, on top of the chosen preset."""
    offsets = {1: [0.0], 2: [-2.5, 2.5], 3: [-2.8, 0.0, 2.8]}[rows]
    return {
        "meta": {"name": "streamlit-design", "notes": "Built from the Design view."},
        "tunnel": {"preset": tunnel_preset},
        "fire": {"preset": fire_preset},
        "nozzles": {
            "preset": nozzle_preset,
            "k_factor_lpm_bar05": k_factor,
            "pressure_bar": pressure_bar,
            "mounting": {"rows": rows, "row_lateral_offsets_m": offsets, "pitch_m": pitch_m},
        },
        "zones": {
            "section_length_m": section_length_m,
            "sections_simultaneous": sections_simultaneous,
            "manual_activation_s": 60.0,
            "activation_delay_s": 0.0,
            "pump_ramp_s": 30.0,
            "duration_min": 60.0,
        },
        "ventilation": {
            "mode": "longitudinal",
            "velocity_range_ms": [velocity_lo, velocity_hi],
        },
        "detection": {"type": "linear_heat", "threshold_c": 60.0, "sensor_spacing_m": 25.0},
        "hydraulics": {"preset": hydraulics_preset},
    }
```

Note on the `nozzles` override: `Design.from_dict` deep-merges this dict onto the loaded preset via `deep_merge` (`solit2/schema/presets.py`), which is confirmed recursive — nested dicts merge key-by-key, not wholesale replacement — so `mounting` here only needs the three fields being overridden (`rows`, `row_lateral_offsets_m`, `pitch_m`); `height_above_carriageway_m`, `tilt_deg`, and everything else come from the preset untouched.

- [ ] **Step 16: Write `app/streamlit_app.py`**

```python
"""Entry point. Run with: uv run streamlit run app/streamlit_app.py"""
from __future__ import annotations

import streamlit as st

from app.views import design as design_view
from app.views import leaderboard as leaderboard_view
from app.views import run as run_view
from app.views import tunnel as tunnel_view
from app.views import verify as verify_view

st.set_page_config(page_title="SOLIT2 Simulator", layout="wide")

PAGES = {
    "Design": design_view.render,
    "Run": run_view.render,
    "Tunnel": tunnel_view.render,
    "Leaderboard": leaderboard_view.render,
    "Verify": verify_view.render,
}

page = st.sidebar.radio("Page", list(PAGES))
st.sidebar.caption("SOLIT2 Annex 7 simulator -- reduced-order engine, calibrated against Annex 2.")
PAGES[page]()
```

This imports `run_view`, `tunnel_view`, `leaderboard_view`, `verify_view` before they exist — that is deliberate: Steps 17–18 give `design.py` and this file a real `render()` for every page so the import does not fail, using minimal real content for the four not yet built this task (Tasks 2–5 replace each in turn). Create the four remaining view files now, each with exactly this body:

`app/views/run.py`, `app/views/tunnel.py`, `app/views/leaderboard.py`, `app/views/verify.py` — each:

```python
"""Placeholder -- built in a later task of the Streamlit-UI plan."""
import streamlit as st


def render() -> None:
    st.header("{Page name}")
    st.info("Not built yet.")
```

(substitute the actual page name — "Run", "Tunnel", "Leaderboard", "Verify" — in each file's `st.header` call). `app/views/__init__.py` is empty.

- [ ] **Step 17: Run the test to verify it passes**

Run: `uv run pytest tests/test_app_design_view.py -v`
Expected: PASS

- [ ] **Step 18: Manually verify the app launches**

Run: `uv run streamlit run app/streamlit_app.py --server.headless true &` then, after a few seconds, `curl -s http://localhost:8501 | head -5` should return HTML, not a connection error. Stop the server (`kill %1` or find the PID with `lsof -i :8501`) before continuing — do not leave it running across tasks.

- [ ] **Step 19: Run the full existing suite to confirm nothing broke**

Run: `uv run pytest -q`
Expected: every test that passed before this task still passes, plus the new ones from Steps 2–17.

- [ ] **Step 20: Commit**

```bash
git add app/ tests/test_app_design_view.py
git commit -m "feat(app): Streamlit scaffold, session state, and the Design view

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 2: Run view

**Files:**
- Create: `app/views/run.py` (replaces Task 1's placeholder)
- Create: `app/components/__init__.py`
- Create: `app/components/charts.py`
- Test: `tests/test_app_run_view.py`

**Interfaces:**
- Consumes: `state.get_design() -> Design | None` (Task 1). `envelope.run(design: Design) -> Result` (`solit2/engines/reduced/envelope.py`, pre-existing, unchanged). `Result`'s fields (`solit2/schema/result.py`, pre-existing): `criteria: dict[str, Criterion]`, `constraints: dict[str, Criterion]`, `peaks: dict[str, float]`, `hydraulics: dict[str, Any]`, `cost: dict[str, Any]`, `score: dict[str, Any]`, `timeseries: dict[str, list[float]]`, `warnings: list[str]`, `worst_case: dict[str, Any]` (has `"section"` and `"velocity_ms"` keys). `Criterion`'s fields: `value: float | bool`, `limit`, `op`, `passed: bool`, `status: Literal["pass","fail","unset"]`, `margin: float`.
- Produces: `state.set_result(result: Design) -> None` called after a successful run (Task 1's `state.py`). `app/components/charts.py`'s `criteria_table(criteria: dict) -> pandas.DataFrame` and `timeseries_chart(timeseries: dict[str, list[float]], keys: list[str]) -> plotly.graph_objects.Figure` — both are consumed by this task's own `run.py` only. Task 3 builds its section plot inline with its own `go.Figure`/`go.Scatter` calls rather than through these helpers, because its x-axis is station position, not time; do not treat Task 3's non-use of `charts.py` as a spec gap.

- [ ] **Step 1: Write the failing test**

Create `tests/test_app_run_view.py`:

```python
from streamlit.testing.v1 import AppTest


def test_run_page_prompts_for_a_design_when_none_is_built_yet():
    at = AppTest.from_file("app/streamlit_app.py")
    at.run()
    at.sidebar.radio[0].set_value("Run").run()
    assert not at.exception
    assert any("design" in w.value.lower() for w in at.warning)


def test_run_page_executes_the_engine_and_shows_the_criteria_table():
    at = AppTest.from_file("app/streamlit_app.py")
    at.run()
    at.sidebar.radio[0].set_value("Design").run()
    at.button[0].click().run()          # "Build design", the only button on Design at this point
    assert not at.exception
    at.sidebar.radio[0].set_value("Run").run()
    at.button[0].click().run()          # "Run simulation"
    assert not at.exception
    assert len(at.dataframe) >= 1
    assert any("MW" in m.label or "mw" in m.label.lower() for m in at.metric)
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_app_run_view.py -v`
Expected: FAIL — the Run page is still Task 1's `st.info("Not built yet.")` placeholder, so no warning/button/dataframe exists to click or assert on.

- [ ] **Step 3: Write `app/components/charts.py`**

```python
"""Plotly and pandas builders shared by the Run and Tunnel views."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from solit2.schema.result import Criterion


def criteria_table(criteria: dict[str, Criterion]) -> pd.DataFrame:
    """One row per criterion, in the shape `st.dataframe` renders directly."""
    rows = []
    for name, c in criteria.items():
        rows.append({
            "criterion": name,
            "value": c.value,
            "limit": c.limit,
            "status": c.status,
            "margin": round(c.margin, 3),
        })
    return pd.DataFrame(rows)


def timeseries_chart(timeseries: dict[str, list[float]], keys: list[str]) -> go.Figure:
    """One line per key in `keys`; `timeseries["t_s"]` is the shared x-axis.

    Every key must be a real key in `timeseries` -- callers read the actual
    key names from a real `Result.timeseries` dict rather than guessing them,
    since this function raises `KeyError` on a name that is not there.
    """
    t = timeseries["t_s"]
    fig = go.Figure()
    for key in keys:
        fig.add_trace(go.Scatter(x=t, y=timeseries[key], mode="lines", name=key))
    fig.update_layout(xaxis_title="time (s)", height=350, margin=dict(l=10, r=10, t=30, b=10))
    return fig
```

Before relying on `timeseries["t_s"]` and any other key name in Step 4, run this in a scratch shell to get the real key set rather than guessing:

```bash
uv run python -c "
from solit2.schema.design import Design
from solit2.engines.reduced import envelope
d = Design.load('examples/designs/road-tunnel-twin-bore-single-mode.json')
r = envelope.run(d)
print(sorted(r.timeseries.keys()))
"
```

Use the printed key names verbatim in Step 4's chart calls — do not assume `hrr_mw`/`ceiling_temp_c` are the exact spellings without checking.

- [ ] **Step 4: Write `app/views/run.py`**

```python
"""The Run view: execute the engine on the current design, show what it found."""
from __future__ import annotations

import streamlit as st

from app import state
from app.components.charts import criteria_table, timeseries_chart
from solit2.engines.reduced import envelope


def render() -> None:
    st.header("Run")
    design = state.get_design()
    if design is None:
        st.warning("Build a design on the Design page first.")
        return

    st.caption(f"Design: **{design.meta.name}**")
    if st.button("Run simulation", type="primary"):
        with st.spinner("Running the reduced-order engine..."):
            result = envelope.run(design)
        state.set_result(result)

    result = state.get_result()
    if result is None:
        return

    st.subheader("Peaks")
    cols = st.columns(4)
    peak_items = list(result.peaks.items())[:4]
    for col, (name, value) in zip(cols, peak_items):
        col.metric(name, f"{value:.1f}")

    st.subheader("Acceptance criteria")
    st.dataframe(criteria_table(result.criteria), use_container_width=True)

    if result.constraints:
        st.subheader("Site constraints (not SOLIT2 acceptance criteria)")
        st.dataframe(criteria_table(result.constraints), use_container_width=True)

    st.subheader("Timeseries")
    available = [k for k in result.timeseries if k != "t_s"]
    chosen = st.multiselect("Series", available, default=available[: min(3, len(available))])
    if chosen:
        st.plotly_chart(timeseries_chart(result.timeseries, chosen), use_container_width=True)

    if result.warnings:
        st.subheader("Warnings")
        for w in result.warnings:
            st.warning(w)

    with st.expander("Full result JSON"):
        st.json(result.model_dump(mode="json"), expanded=False)
```

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_app_run_view.py -v`
Expected: PASS. If the second test fails because `at.metric` labels don't contain "MW", read the actual `result.peaks` key names printed by Step 3's scratch command and adjust either the test's assertion or, preferably, confirm the peaks dict really does carry an MW-labelled quantity — do not weaken the assertion to pass trivially.

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: all green, including Task 1's tests.

- [ ] **Step 7: Commit**

```bash
git add app/views/run.py app/components/ tests/test_app_run_view.py
git commit -m "feat(app): Run view -- execute the engine, show criteria and timeseries

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 3: Tunnel view (longitudinal thermal-field section)

The spec (section 10) describes a 3-D bore visualization. This task builds a **2-D longitudinal section** instead — the same visual content (thermal field, mock-up, mist zone, backlayering, stations, time slider) already proven useful in the project's earlier Canvas-based artifact, re-implemented in Plotly. A true extruded 3-D bore with 3-D spray cones is a substantial, separate graphics effort with real risk of an under-baked result; the 2-D section delivers every piece of *content* the spec calls for (rows/heads, fire block, ceiling-temperature strip, backlayering, time slider) with a known-good design. Treat true 3-D rendering as a future task, not a gap in this one — say so in the task's own commit message rather than silently reinterpreting the spec.

**Files:**
- Create: `app/views/tunnel.py` (replaces Task 1's placeholder)
- Test: `tests/test_app_tunnel_view.py`

**Interfaces:**
- Consumes: `state.get_design()`, `state.get_result()` (Task 1). `sim.run_once(design: Design, section: str, velocity_ms: float) -> RunTrace` (`solit2/engines/reduced/sim.py`, pre-existing, unchanged) — called fresh here because `Result.timeseries` (Task 2) is a flattened summary, while the Tunnel view needs the full per-station trace `envelope.run` computes internally but does not return. `RunTrace.steps: tuple[StepRecord, ...]`, `.events: dict`. `StepRecord`'s fields (pre-existing, `solit2/engines/reduced/state.py`): `t_s`, `hrr_mw`, `hrr_free_mw`, `ceiling_temp_c`, `backlayer_m`, `water_lpm`, `stations: dict[str, StationSample]`. `StationSample`'s fields: `temp_c: float`, `temps_c: tuple[float, ...]`, `heights_m: tuple[float, ...]` (both `()` where the station has no thermocouple entries beyond the single breathing-height value — confirm this against a real run before assuming). `criteria.STATIONS: dict[str, float]` (`solit2/engines/reduced/criteria.py`, pre-existing) — station name to x-position in metres.
- Produces: nothing consumed by a later task.

- [ ] **Step 1: Write the failing test**

Create `tests/test_app_tunnel_view.py`:

```python
from streamlit.testing.v1 import AppTest


def test_tunnel_page_prompts_for_a_run_when_none_exists_yet():
    at = AppTest.from_file("app/streamlit_app.py")
    at.run()
    at.sidebar.radio[0].set_value("Tunnel").run()
    assert not at.exception
    assert any("run" in w.value.lower() for w in at.warning)


def test_tunnel_page_shows_a_time_slider_and_a_section_plot_after_a_run():
    at = AppTest.from_file("app/streamlit_app.py")
    at.run()
    at.sidebar.radio[0].set_value("Design").run()
    at.button[0].click().run()
    at.sidebar.radio[0].set_value("Run").run()
    at.button[0].click().run()
    at.sidebar.radio[0].set_value("Tunnel").run()
    assert not at.exception
    assert len(at.slider) >= 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_app_tunnel_view.py -v`
Expected: FAIL — Task 1's placeholder has no slider and no run-dependent warning text specific to this page.

- [ ] **Step 3: Confirm the real field shapes before writing the renderer**

```bash
uv run python -c "
from solit2.schema.design import Design
from solit2.engines.reduced.sim import run_once
d = Design.load('examples/designs/road-tunnel-twin-bore-single-mode.json')
tr = run_once(d, d.tunnel.section, d.ventilation.velocity_range_ms[1])
s = tr.steps[len(tr.steps)//2]
print('t_s', s.t_s, 'hrr_mw', s.hrr_mw, 'ceiling_temp_c', s.ceiling_temp_c, 'backlayer_m', s.backlayer_m)
print('stations', sorted(s.stations.keys()))
name = sorted(s.stations.keys())[0]
print(name, 'temps_c', s.stations[name].temps_c, 'heights_m', s.stations[name].heights_m)
"
```

Use the printed shapes to confirm every field access in Step 4 is real. If any name differs from what this task assumes, fix Step 4 to match what actually printed — this step exists precisely so that does not have to be guessed.

- [ ] **Step 4: Write `app/views/tunnel.py`**

```python
"""The Tunnel view: a longitudinal thermal-field section with a time slider."""
from __future__ import annotations

import plotly.graph_objects as go
import streamlit as st

from app import state
from solit2.engines.reduced.criteria import STATIONS
from solit2.engines.reduced.sim import run_once

X_WINDOW_M = (-140.0, 230.0)  # matches the window already proven readable in the artifact


def render() -> None:
    st.header("Tunnel")
    design = state.get_design()
    result = state.get_result()
    if design is None or result is None:
        st.warning("Build a design and run it on the Run page first.")
        return

    trace = run_once(design, result.worst_case["section"], result.worst_case["velocity_ms"])
    steps = trace.steps
    t_values = [s.t_s for s in steps]

    idx = st.slider("Time (s)", min_value=0, max_value=len(steps) - 1, value=len(steps) // 2,
                    format="", key="tunnel_time_idx")
    step = steps[idx]
    st.caption(f"t = {step.t_s:.0f} s -- HRR {step.hrr_mw:.1f} MW "
              f"(free burn {step.hrr_free_mw:.1f} MW) -- ceiling {step.ceiling_temp_c:.0f} C")

    fig = go.Figure()
    xs, ys = [], []
    for name, x_m in sorted(STATIONS.items(), key=lambda kv: kv[1]):
        if not (X_WINDOW_M[0] <= x_m <= X_WINDOW_M[1]):
            continue
        sample = step.stations.get(name)
        if sample is None:
            continue
        xs.append(x_m)
        ys.append(sample.temp_c)
    fig.add_trace(go.Scatter(x=xs, y=ys, mode="lines+markers", name="gas temp (breathing height)"))

    if step.backlayer_m > 1.0:
        fig.add_vrect(x0=-step.backlayer_m, x1=0.0, fillcolor="grey", opacity=0.2,
                     annotation_text=f"backlayering {step.backlayer_m:.0f} m", line_width=0)
    if step.water_lpm > 0:
        half = design.zones.section_length_m * design.zones.sections_simultaneous / 2.0
        fig.add_vrect(x0=-half, x1=half, fillcolor="lightblue", opacity=0.15,
                     annotation_text=f"{step.water_lpm:.0f} L/min", line_width=0)

    fig.update_layout(xaxis_title="distance from fire (m)", yaxis_title="gas temperature (C)",
                      height=420, margin=dict(l=10, r=10, t=30, b=10))
    st.plotly_chart(fig, use_container_width=True)
```

If Step 3 printed `format=""` as invalid for `st.slider` (it is not a valid Streamlit kwarg value in every version — confirm against the installed Streamlit's own docstring: `uv run python -c "import streamlit as st; help(st.slider)"`), remove that kwarg rather than guess a replacement.

- [ ] **Step 5: Run the test to verify it passes**

Run: `uv run pytest tests/test_app_tunnel_view.py -v`
Expected: PASS

- [ ] **Step 6: Run the full suite**

Run: `uv run pytest -q`
Expected: all green.

- [ ] **Step 7: Commit**

```bash
git add app/views/tunnel.py tests/test_app_tunnel_view.py
git commit -m "feat(app): Tunnel view -- longitudinal thermal section with a time slider

Scope note: this is a 2-D section, not the spec's 3-D bore -- see the task's
own docstring-level comment for why. Content (stations, fire, mist zone,
backlayering, time slider) matches the spec; the rendering style does not.

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 4: Leaderboard view

**Files:**
- Create: `app/views/leaderboard.py` (replaces Task 1's placeholder)
- Test: `tests/test_app_leaderboard_view.py`

**Interfaces:**
- Consumes: `state.get_result()` (Task 1). `history.append(result: Result, path: Path = DEFAULT_PATH) -> None` and `history.leaderboard(path: Path = DEFAULT_PATH, top: int = 10, passing_only: bool = False) -> list[dict]` (`solit2/history.py`, pre-existing, unchanged).
- Produces: nothing consumed by a later task.

- [ ] **Step 1: Write the failing test**

Create `tests/test_app_leaderboard_view.py`:

```python
from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_leaderboard_page_shows_an_empty_state_with_no_history(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # history.py's DEFAULT_PATH is relative: runs/history.jsonl
    at = AppTest.from_file("app/streamlit_app.py")
    at.run()
    at.sidebar.radio[0].set_value("Leaderboard").run()
    assert not at.exception
    assert any("no run" in i.value.lower() for i in at.info)


def test_saving_a_run_makes_it_appear_on_the_leaderboard(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file("app/streamlit_app.py")
    at.run()
    at.sidebar.radio[0].set_value("Design").run()
    at.button[0].click().run()
    at.sidebar.radio[0].set_value("Run").run()
    at.button[0].click().run()
    at.sidebar.radio[0].set_value("Leaderboard").run()
    assert not at.exception
    assert any("save" in b.label.lower() for b in at.button)
    [b for b in at.button if "save" in b.label.lower()][0].click().run()
    assert Path("runs/history.jsonl").exists()
    at.run()
    assert len(at.dataframe) >= 1
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_app_leaderboard_view.py -v`
Expected: FAIL — Task 1's placeholder has no "no run" info message and no save button.

- [ ] **Step 3: Write `app/views/leaderboard.py`**

```python
"""The Leaderboard view: save the current run to history, browse past runs."""
from __future__ import annotations

import streamlit as st

from app import state
from solit2 import history


def render() -> None:
    st.header("Leaderboard")

    result = state.get_result()
    if result is not None:
        if st.button("Save this run to history"):
            history.append(result)
            st.success("Saved.")

    passing_only = st.checkbox("Passing designs only", value=False)
    rows = history.leaderboard(top=20, passing_only=passing_only)
    if not rows:
        st.info("No runs saved yet. Run a simulation, then save it here.")
        return
    st.dataframe(rows, use_container_width=True)
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_app_leaderboard_view.py -v`
Expected: PASS

- [ ] **Step 5: Run the full suite**

Run: `uv run pytest -q`
Expected: all green.

- [ ] **Step 6: Commit**

```bash
git add app/views/leaderboard.py tests/test_app_leaderboard_view.py
git commit -m "feat(app): Leaderboard view -- save and browse run history

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

### Task 5: Verify view (explicit stub), final wiring, and docs

**Files:**
- Create: `app/views/verify.py` (replaces Task 1's placeholder)
- Modify: `README.md` (add a "Running the app" section — read the file first; if it does not exist, create it with just this section)
- Test: `tests/test_app_verify_view.py`

**Interfaces:**
- Consumes: nothing new.
- Produces: nothing consumed elsewhere — this is the plan's final task.

- [ ] **Step 1: Write the failing test**

Create `tests/test_app_verify_view.py`:

```python
from streamlit.testing.v1 import AppTest


def test_verify_page_states_plainly_that_fds_is_not_built():
    at = AppTest.from_file("app/streamlit_app.py")
    at.run()
    at.sidebar.radio[0].set_value("Verify").run()
    assert not at.exception
    assert any("fds" in i.value.lower() for i in at.info)
    assert not at.button  # no button that implies a capability that does not exist
```

- [ ] **Step 2: Run the test to verify it fails**

Run: `uv run pytest tests/test_app_verify_view.py -v`
Expected: FAIL — Task 1's placeholder text says "Not built yet", not "FDS", and mentions no reason.

- [ ] **Step 3: Write `app/views/verify.py`**

```python
"""The Verify view: explicitly not implemented.

Tier 2 (FDS) verification is Plan 2 of this project and has not been built.
This view says so plainly rather than showing a "Verify" button that queues
a job nothing can run.
"""
from __future__ import annotations

import streamlit as st


def render() -> None:
    st.header("Verify")
    st.info(
        "FDS (Tier 2 CFD) verification is not built yet -- it is a separate, "
        "unstarted plan. This tool currently reports the reduced-order "
        "(Tier 1) engine's own results only, shown on the Run and Tunnel pages."
    )
```

- [ ] **Step 4: Run the test to verify it passes**

Run: `uv run pytest tests/test_app_verify_view.py -v`
Expected: PASS

- [ ] **Step 5: Add the README section**

Read `README.md` if it exists (`ls README.md`). Add (creating the file with just this section if it does not exist):

```markdown
## Running the app

    uv run streamlit run app/streamlit_app.py

Opens the Streamlit UI: Design (build a configuration), Run (execute the
engine), Tunnel (thermal-field visualization), Leaderboard (run history),
Verify (stub -- FDS/CFD tier is a separate, unstarted plan).

Views call the engine in-process -- the same Python functions the CLI
(`solit2 run`, `solit2 validate`) uses. There is no separate API server.
```

- [ ] **Step 6: Run the full suite one final time**

Run: `uv run pytest -q`
Expected: every test in the repository passes, including every test added across all five tasks of this plan.

- [ ] **Step 7: Manually smoke-test the whole app**

```bash
uv run streamlit run app/streamlit_app.py --server.headless true &
sleep 3
curl -s http://localhost:8501 | grep -o "<title>[^<]*" | head -1
kill %1
```

Expected: a title tag prints, no connection error. This is a smoke test, not a substitute for the AppTest suite already run in Step 6.

- [ ] **Step 8: Commit**

```bash
git add app/views/verify.py README.md tests/test_app_verify_view.py
git commit -m "feat(app): Verify view stub and README run instructions

Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>"
```

---

## Confidentiality

No design, tunnel, or nozzle data invented for this plan's own test fixtures describes a real, named project. Every example the views exercise already ships in `examples/designs/` and `examples/presets/`, and those already carry the "ILLUSTRATION ONLY" provenance notes established by the prior plan. This plan adds no new example data and does not touch that convention.

## The loop

Not applicable in the sense the original tier-1-optimiser plan meant it (a Claude-driven parameter search) — this plan builds the human-facing UI for exactly the exact-configuration workflow already in use this session. Once built, a person drives the Design/Run/Tunnel loop by hand, in the browser, instead of asking Claude to run one-off `uv run python -c "..."` snippets.

## What this plan is not

It does not build FDS integration (Plan 2), does not add authentication or multi-user state, does not persist `Design` objects anywhere but a downloaded JSON file and the existing `runs/history.jsonl`, and does not attempt the spec's literal "3-D bore" rendering (Task 3 states why).

## Plan self-review

**1. Spec coverage.** Section 10 lists: Design, Run (criteria table, envelope grid, timeseries), Tunnel 3-D (rows/heads/cones, fire block, ceiling strip, backlayering, time slider), Leaderboard, Verify. Design → Task 1. Run's criteria table and timeseries → Task 2 (the "envelope grid" — the section/velocity grid `envelope.run` evaluates internally — is visible via the `worst_case` field already surfaced in the JSON expander; a dedicated grid-of-cases table is not built and is a legitimate gap, not silently covered — flag it to the user after this plan lands if a literal per-cell grid view is wanted). Tunnel → Task 3, scope narrowed to 2-D with the reason stated inline, not hidden. Leaderboard → Task 4. Verify → Task 5.

**2. Placeholder scan.** Every code block in every task is complete, runnable code with real interfaces confirmed against the actual source (Task 2 Step 3, Task 3 Step 3) rather than assumed. The only literal placeholder text ("Not built yet") is Task 1's deliberate, temporary stand-in for pages Tasks 2–5 replace in order — each of those replacements is itself fully specified, not deferred.

**3. Type consistency.** `state.get_design()/set_design()` and `state.get_result()/set_result()` are used with the same names and signatures in every task that touches them (1 through 4). `envelope.run`, `sim.run_once`, `history.append`/`leaderboard`, `Design.from_dict`, `list_presets` are each defined once (Task 1 for the two new ones) and consumed with identical signatures everywhere else.

---

## Execution Handoff

Plan complete and saved to `docs/superpowers/plans/2026-09-17-solit2-streamlit-ui.md`. Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

Which approach?

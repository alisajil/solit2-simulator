# SOLIT² Actual Values in the Fire Test — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The Fire test step shows the SOLIT² Annex 7 test run with the tester's own nozzle, and every number it uses is a published SOLIT² value, a published correlation, or a value the tester typed in. Nothing is assumed.

**Architecture:** Four changes. (1) Ceiling temperature goes back to the published Li & Ingason correlation, and its fitted 0.314 multiplier is removed. (2) The droplet spread comes from the tester's measured Dv50/Dv90, not a hard-coded 2.5. (3) The SOLIT² reference nozzle behind the c4–c6 calibration becomes tester-supplied data, not an invented preset. (4) `solit2/reports/twin.py` builds the Annex 7 test from Annex 7 clauses only, with the unsourced values turned into required inputs, and the Fire test page runs it.

**Tech Stack:** Python 3.12, pydantic v2, Streamlit 1.64, plotly, pytest, `uv run`.

**Spec:** This plan is its own spec. The decisions below come from the user in the 2026-09-27 session.

## Why (evidence, 2026-09-27)

- `uv run solit2 validate`: c4 peak ceiling 201 °C modelled vs 830 °C measured; c5 227 vs 580; D15/D100 about half.
- `thermal.ceiling_excess_coefficient` = 0.314 sits on the 0.3 floor in `validation/fit.py`. `sim.run_once` passes the same scaled excess to `mist_mod.evaluate` as the gas the droplets fall through. At 1.0 the assumed 90 µm spray evaporates and c4 HRR goes from 35 to 92 MW, so the fit bought correct HRR with temperatures 3× too low. `docs/accuracy-roadmap.md` item 3 already records this.
- The UI charts plot the trace directly. They are correct; the numbers they are given are not.
- Scratch test: with the coefficient at 1.0 and a 200 µm reference SMD, c4 gives 29.3 MW / 657 °C / 70.5 °C D15 and c5 gives 15.0 MW / 476 °C / 56 °C. Both HRR and temperatures are back inside tolerance. The unknown is the reference spray, not the correlation.
- SOLIT² Annex 2 publishes **no** nozzle data for its test system: no K-factor, pressure, spectrum or mounting. Annex 3 §2.1 only defines water mist as Dv0.90 < 1 mm at 1 m. `solit2/presets/nozzle_solit2_reference.json` (K 2.8, 100 bar, SMD 90 µm) is back-figured, i.e. assumed.

## User decisions (binding)

1. "Strictly follow the SOLIT² actual reference test, not OEM test."
2. "No assumptions, only actual values used for SOLIT² actual test."
3. "Nozzle details: ask the tester to input."
4. The Fire test page simulates the **SOLIT² Annex 7 test** with the tester's nozzle, not the project tunnel.
5. Reference nozzle: **tester inputs it**. Delete the assumed values. Validation and the refit refuse to run without it.

## Global Constraints

- No value may enter a Fire-test run unless it has a SOLIT² clause citation, a published-correlation citation, or came from tester input. A code comment naming the clause is the citation.
- No fallback defaults for tester inputs. When one is missing, refuse with a message naming the field and where to enter it.
- Never scale a displayed value to look right. Runtime code reports only what the engine produced (memory: feedback-no-fabricated-values).
- Project and product data live in `designs/` only, never in `solit2/` or `examples/` (CLAUDE.md, INDEPENDENCE.md).
- The nozzle is single-mode in this project's UI. The schema keeps multi-mode for files.
- Test fixtures are labelled `TEST FIXTURE, NOT DATA` in their `note`.
- Run tests with `uv run pytest -q`. Commit after each task. Messages use conventional prefixes and end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.

## File map

| File | Change |
|---|---|
| `solit2/presets/calibration.json` | `ceiling_excess_coefficient` → 1.0 and marked not fitted; remove `droplet_size_spread`; rewrite `provenance.note` |
| `validation/fit.py` | drop the coefficient from `FITTED_KEYS`; add `--reference-nozzle` |
| `solit2/schema/design.py` | `Mode.dv50_um`, `Mode.dv90_um`; `Nozzles.spread_n()`; `MissingNozzleData`; `from_dict` accepts a preset-free `nozzles` block |
| `solit2/engines/reduced/droplet.py` | `size_distribution(smd_um, spread_n, bin_count=None)` |
| `solit2/engines/reduced/mist.py` | pass `design.nozzles.spread_n(mode.id)` |
| `solit2/engines/reduced/sim.py` | skip `_require_detection` when activation is manual |
| `solit2/presets/nozzle_solit2_reference.json` | **delete** |
| `validation/anchors/c4/c5/c6*.json` | remove the `nozzles` block |
| `validation/compare.py` | `load_reference_nozzle()`, `ReferenceNozzleMissing`; `load_anchors` injects the tester's reference nozzle |
| `solit2/cli.py` | `validate --reference-nozzle`; clean refusal |
| `solit2/reports/twin.py` | Annex 7-only builder `test_facility_twin(design, inputs)` plus `Annex7Inputs` |
| `app/views/design.py` | every nozzle field is tester input with no default; nozzle preset picker removed |
| `app/views/fire_test.py` | runs the Annex 7 twin; asks for the Annex 7 inputs; class and velocity selectors |
| `app/views/reports.py` | passes the stored Annex 7 inputs to the twin |
| `tests/conftest.py` | points `SOLIT2_REFERENCE_NOZZLE` at the fixture |
| `tests/fixtures/solit2_reference_nozzle_TEST_FIXTURE.json` | the withdrawn preset's values, labelled fixture |
| `examples/presets/nozzle_*.json`, `solit2/presets/nozzle_template.json` | add `dv50_um`/`dv90_um` so examples still run (illustrations, never defaults) |
| `docs/accuracy-roadmap.md`, `INDEPENDENCE.md` | record what changed |

Rosin-Rammler facts used below. Volume fraction coarser than d is `exp(-(d/X)^n)`. So `Dv50 = X·(ln 2)^(1/n)`, `Dv90 = X·(ln 10)^(1/n)`, which gives **`n = ln(ln10/ln2) / ln(Dv90/Dv50)`** in closed form. Sauter mean `D32 = X / Γ(1 − 1/n)`. For n = 2.5: `Dv50 = 1.28604·D32` and `Dv90 = 2.07876·D32`, and the ratio `Dv90/Dv50 = 1.616398` reproduces n = 2.5000. Note that the error message in `droplet.size_distribution` says "X * gamma(1 - 1/n)", but the code (`scale_um = smd · Σ v/u`) implements `X / Γ` correctly. Fix the message in Task 2.

---

### Task 1: Ceiling temperature on the published correlation

**Files:**
- Modify: `solit2/presets/calibration.json` (entry `thermal.ceiling_excess_coefficient`)
- Modify: `validation/fit.py:51` (remove the tuple)
- Test: `tests/test_thermal.py`, `tests/test_fit.py:85-88`

**Interfaces:**
- Produces: `load_calibration()["thermal"]["ceiling_excess_coefficient"]["value"] == 1.0`; no `FITTED_KEYS` entry names it.

- [ ] **Step 1: Write the failing tests**

In `tests/test_thermal.py` append:

```python
def test_ceiling_excess_is_the_published_li_ingason_correlation_unscaled():
    """Region II of Li & Ingason (2012): dT = Q / (V b^(1/3) H^(5/3)), no multiplier.

    The fitted 0.314 made every plotted temperature 3x low against SOLIT2
    Annex 2 (c4 201 C vs 830 C measured); see docs/accuracy-roadmap.md item 3.
    """
    hrr_kw, q_conv_kw, u_ms, b_m, h_m = 14_500.0, 9_425.0, 5.08, 2.764, 6.125
    expected = hrr_kw / (u_ms * b_m ** (1 / 3) * h_m ** (5 / 3))
    assert thermal.max_ceiling_excess_k(hrr_kw, q_conv_kw, u_ms, b_m, h_m) == pytest.approx(expected)
```

Replace `tests/test_fit.py:85-88` (`test_fitted_keys_includes_the_ceiling_excess_coefficient`) with:

```python
def test_ceiling_excess_coefficient_is_published_not_fitted():
    """The fit may not move the ceiling correlation: at its 0.3 floor it was
    buying suppressed HRR with 3x-low temperatures (accuracy-roadmap item 3)."""
    assert all(name != "ceiling_excess_coefficient" for _, name, _, _ in fit.FITTED_KEYS)
    assert load_calibration()["thermal"]["ceiling_excess_coefficient"]["value"] == 1.0
```

(Add `from solit2.schema.presets import load_calibration` at the top of `tests/test_fit.py` if it is not already imported. Keep the `restored_calibration` fixture off this test: it reads, never writes.)

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_thermal.py::test_ceiling_excess_is_the_published_li_ingason_correlation_unscaled tests/test_fit.py::test_ceiling_excess_coefficient_is_published_not_fitted -v`
Expected: both FAIL (0.314× the expected value; the key is still in `FITTED_KEYS`).

- [ ] **Step 3: Implement**

In `validation/fit.py` delete the line `("thermal", "ceiling_excess_coefficient", 0.3, 2.0),`.

In `solit2/presets/calibration.json` replace the `ceiling_excess_coefficient` line with:

```json
    "ceiling_excess_coefficient": {"value": 1.0, "anchor": "none", "note": "SET, NOT FITTED: the published Li & Ingason (2012) maximum ceiling excess, unscaled. Was 0.314, pinned at the fit's 0.3 floor, because the same scaled excess is the gas the mist droplets fall through: the fit bought correct suppressed heat release with gas temperatures 3x below SOLIT2 Annex 2 (c4 201 C vs 830 C). Removed from validation/fit.py FITTED_KEYS on 2026-09-27; see docs/accuracy-roadmap.md item 3."}
```

- [ ] **Step 4: Run the whole suite and triage**

Run: `uv run pytest -q`
Expected: the two new tests PASS. Some anchor and snapshot tests may fail because the mist now sees real gas temperatures (c4 HRR is about 92 MW on the assumed nozzle). For each failure, read the assertion. If it pins a calibration-dependent number, or asserts that c4/c5 are inside tolerance, mark it `@pytest.mark.xfail(strict=True, reason="engine awaits refit against a tester-supplied SOLIT2 reference nozzle (Task 3); ceiling correlation is now the published one")`. Do not change the expected number to match. If it asserts a law (monotonicity, a cap, units), it must still pass. If it doesn't, stop and report.

- [ ] **Step 5: Commit**

```bash
git add solit2/presets/calibration.json validation/fit.py tests/
git commit -m "fix(thermal): report gas temperature on the published Li & Ingason correlation

The fitted 0.314 multiplier sat on its bound because the same excess is the
gas the spray falls through; it held suppressed HRR by making every plotted
temperature about 3x low against SOLIT2 Annex 2.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: Droplet spread from the tester's measured Dv50 / Dv90

**Files:**
- Modify: `solit2/schema/design.py` (`Mode`, `Nozzles`, new `MissingNozzleData`)
- Modify: `solit2/engines/reduced/droplet.py:160-205` (`size_distribution`)
- Modify: `solit2/engines/reduced/mist.py:340`
- Modify: `solit2/presets/calibration.json` (delete `mist.droplet_size_spread`)
- Modify: `solit2/presets/nozzle_template.json`, `examples/presets/nozzle_single_mode_example.json`, `examples/presets/nozzle_single_mode_fine_example.json`, `examples/presets/nozzle_bimodal_example.json`, `solit2/presets/nozzle_solit2_reference.json` (deleted in Task 3; add the fields here so Task 2's suite stays green)
- Test: `tests/test_design_schema.py`, `tests/test_droplet.py`

**Interfaces:**
- Produces: `class MissingNozzleData(ValueError)`; `Mode.dv50_um: float | None`, `Mode.dv90_um: float | None`; `Nozzles.spread_n(mode_id: str) -> float`; `droplet.size_distribution(smd_um: float, spread_n: float, bin_count: int | None = None) -> tuple[SizeBin, ...]`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_design_schema.py`:

```python
import math

from solit2.schema.design import MissingNozzleData, Nozzles


def _nozzles(**mode_extra):
    mode = {"id": "fine", "fraction": 1.0, "smd_um": 90.0,
            "cone_half_angle_deg": 50.0, "launch_velocity_ms": 25.0, **mode_extra}
    return Nozzles.model_validate({
        "preset": "tester_input", "k_factor_lpm_bar05": 2.8, "pressure_bar": 100.0,
        "modes": [mode],
        "mounting": {"rows": 2, "row_lateral_offsets_m": [-2.2, 2.2],
                     "height_above_carriageway_m": 4.9, "pitch_m": 4.0}})


def test_spread_is_solved_from_the_testers_dv50_and_dv90():
    n = _nozzles(dv50_um=100.0, dv90_um=161.6398).spread_n("fine")
    assert n == pytest.approx(2.5, abs=1e-4)
    assert n == pytest.approx(math.log(math.log(10) / math.log(2)) / math.log(1.616398), rel=1e-6)


def test_a_mode_without_a_measured_spectrum_refuses_rather_than_assuming_one():
    with pytest.raises(MissingNozzleData, match="Dv50 and Dv90"):
        _nozzles().spread_n("fine")


def test_dv90_must_be_coarser_than_dv50():
    with pytest.raises(MissingNozzleData, match="coarser"):
        _nozzles(dv50_um=150.0, dv90_um=120.0).spread_n("fine")
```

In `tests/test_droplet.py`, add near the other constants `REFERENCE_SPREAD_N = 2.5  # test value, matches the withdrawn calibration constant`. Change every `droplet.size_distribution(X)` or `droplet.size_distribution(X, k)` call (lines 235, 251, 259, 270, 301, 336, 338, 350) to pass `REFERENCE_SPREAD_N` as the second positional argument, with `bin_count` moving to third (e.g. `droplet.size_distribution(REFERENCE_SMD_UM, REFERENCE_SPREAD_N, bin_count)`). Add:

```python
def test_size_distribution_takes_the_spread_from_its_caller_not_calibration():
    wide = droplet.size_distribution(REFERENCE_SMD_UM, 1.8)
    narrow = droplet.size_distribution(REFERENCE_SMD_UM, 4.0)
    assert wide[-1].diameter_um > narrow[-1].diameter_um
```

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_design_schema.py tests/test_droplet.py -q`
Expected: FAIL (`MissingNozzleData` import error; `size_distribution` rejects the extra argument).

- [ ] **Step 3: Implement the schema**

In `solit2/schema/design.py`, above `class Mode`:

```python
# Rosin-Rammler: Dv50 = X (ln 2)^(1/n) and Dv90 = X (ln 10)^(1/n), so the ratio
# fixes n in closed form. Both come from the tester's own drop-size measurement.
_RR_DV90_DV50_LOG = math.log(math.log(10.0) / math.log(2.0))


class MissingNozzleData(ValueError):
    """A nozzle quantity the engine needs was not supplied by the tester."""
```

Add to `Mode`:

```python
    # Volume-median and 90th-percentile diameters, from the tester's drop-size
    # measurement at the working pressure. Optional in the schema so an older
    # design file still loads and the refusal can say exactly what to add.
    dv50_um: float | None = Field(default=None, gt=0)
    dv90_um: float | None = Field(default=None, gt=0)
```

Add to `Nozzles`:

```python
    def spread_n(self, mode_id: str) -> float:
        """The mode's Rosin-Rammler spread exponent, from its measured Dv50 and Dv90."""
        mode = self._mode(mode_id)
        if mode.dv50_um is None or mode.dv90_um is None:
            raise MissingNozzleData(
                f"nozzle mode {mode_id!r} has no measured drop spectrum: enter Dv50 and Dv90 "
                f"(um, measured at the working pressure). The tool does not assume a spread.")
        if mode.dv90_um <= mode.dv50_um:
            raise MissingNozzleData(
                f"nozzle mode {mode_id!r}: Dv90 {mode.dv90_um} um must be coarser than "
                f"Dv50 {mode.dv50_um} um")
        n = _RR_DV90_DV50_LOG / math.log(mode.dv90_um / mode.dv50_um)
        if n <= 1.0:
            raise MissingNozzleData(
                f"nozzle mode {mode_id!r}: Dv90/Dv50 = {mode.dv90_um / mode.dv50_um:.2f} is a "
                f"spectrum too wide to have a finite Sauter mean (Rosin-Rammler n = {n:.2f} <= 1)")
        return n
```

- [ ] **Step 4: Implement the engine**

In `solit2/engines/reduced/droplet.py`, change the signature to `def size_distribution(smd_um: float, spread_n: float, bin_count: int | None = None)`. Delete the `spread = load_calibration()[...]` line, use `spread = spread_n`, and change the `spread <= 1.0` error text to `"... the Rosin-Rammler Sauter mean is X / gamma(1 - 1/n), which diverges at n = 1 ..."`. In the docstring, replace "(`droplet_size_spread` in calibration.json; lower is wider)" with "(from the mode's measured Dv50/Dv90, `Nozzles.spread_n`; lower is wider)". If `load_calibration` is no longer used in `droplet.py`, remove that import.

In `solit2/engines/reduced/mist.py:340`: `for size_bin in size_distribution(smd_um, design.nozzles.spread_n(mode.id)):`

In `solit2/presets/calibration.json`, delete the `"droplet_size_spread": {...}` line (mind the trailing comma).

- [ ] **Step 5: Give the illustrative presets a spectrum**

These are illustrations, never defaults. Add to every mode in the listed preset files the pair that reproduces n = 2.5 for that mode's SMD. For a mode with `smd_um` S (or, when the mode reads `smd_table`, the table's entry at the preset's own `pressure_bar`): `"dv50_um": round(1.28604 * S, 3)`, `"dv90_um": round(2.07876 * S, 3)`. For the 90 µm reference preset that is `115.744` / `187.088`. Keep each file's `note` and add the sentence: "Dv50/Dv90 are illustrative, chosen to reproduce a Rosin-Rammler n of 2.5; replace with measured values."

- [ ] **Step 6: Run the suite**

Run: `uv run pytest -q`
Expected: new tests PASS. Nothing that passed after Task 1 now fails: n is still 2.5 for every shipped illustration, so the numbers do not move. Any `KeyError: 'droplet_size_spread'` means a reader you missed. `grep -rn droplet_size_spread solit2 tests validation app` must return nothing.

- [ ] **Step 7: Commit**

```bash
git add -A solit2 examples tests
git commit -m "feat(nozzle): the droplet spread comes from the tester's measured Dv50/Dv90

Removes the hard-coded Rosin-Rammler n = 2.5; a mode without a measured
spectrum now refuses to run instead of assuming one.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The SOLIT² reference nozzle is tester-supplied

**Files:**
- Delete: `solit2/presets/nozzle_solit2_reference.json`
- Modify: `validation/anchors/c4_solit2_class_a_cover.json`, `c5_solit2_class_a_nocover.json`, `c6_solit2_class_b.json` (remove `design.nozzles`)
- Modify: `validation/compare.py:61-72` (`load_anchors`), add `load_reference_nozzle`, `ReferenceNozzleMissing`
- Modify: `solit2/schema/design.py:319-333` (`from_dict`: a `nozzles` block may be preset-free); `Nozzles.preset: str = "tester_input"`
- Modify: `solit2/cli.py` (`_cmd_validate` around line 238; the other `load_anchors` callers at 99 and 477 need no change)
- Modify: `validation/fit.py` `_main` (`--reference-nozzle`)
- Create: `tests/fixtures/solit2_reference_nozzle_TEST_FIXTURE.json`, `tests/conftest.py` (or extend the existing one)
- Modify: `tests/test_mist.py:85-91` (`_solit2_reference_design`), `tests/test_design_schema.py:213`
- Test: `tests/test_validation.py`

**Interfaces:**
- Consumes: `Nozzles`, `MissingNozzleData`, `Nozzles.spread_n` (Task 2).
- Produces: `validation.compare.REFERENCE_NOZZLE_ENV = "SOLIT2_REFERENCE_NOZZLE"`; `validation.compare.DEFAULT_REFERENCE_NOZZLE_PATH = <repo>/designs/solit2-reference-nozzle.json`; `class ReferenceNozzleMissing(FileNotFoundError)`; `load_reference_nozzle(path: Path | None = None) -> dict`; `load_anchors(ids=None, *, reference_nozzle: dict | None = None)`.

- [ ] **Step 1: Create the fixture**

`tests/fixtures/solit2_reference_nozzle_TEST_FIXTURE.json`:

```json
{
  "preset": "tester_input",
  "note": "TEST FIXTURE, NOT DATA. The values of the withdrawn nozzle_solit2_reference preset (back-figured, never published by SOLIT2), kept only so the test suite exercises the anchors. Never read by the product.",
  "k_factor_lpm_bar05": 2.8,
  "pressure_bar": 100.0,
  "modes": [
    {"id": "fine", "fraction": 1.0, "smd_um": 90.0, "dv50_um": 115.744, "dv90_um": 187.088,
     "cone_half_angle_deg": 50.0, "launch_velocity_ms": 25.0}
  ],
  "mounting": {"type": "ceiling_rows", "rows": 2, "row_lateral_offsets_m": [-2.2, 2.2],
               "height_above_carriageway_m": 4.9, "pitch_m": 4.0, "tilt_deg": 0.0}
}
```

Create or extend `tests/conftest.py`:

```python
from pathlib import Path

import pytest

REFERENCE_NOZZLE_FIXTURE = Path(__file__).parent / "fixtures" / "solit2_reference_nozzle_TEST_FIXTURE.json"


@pytest.fixture(autouse=True)
def _reference_nozzle_fixture(monkeypatch):
    """Anchors run on the labelled fixture; the product reads the tester's own file."""
    monkeypatch.setenv("SOLIT2_REFERENCE_NOZZLE", str(REFERENCE_NOZZLE_FIXTURE))
```

- [ ] **Step 2: Write the failing tests**

Append to `tests/test_validation.py`:

```python
from validation.compare import ReferenceNozzleMissing, load_reference_nozzle


def test_no_reference_nozzle_ships_with_the_tool():
    from solit2.schema.presets import list_presets
    assert "solit2_reference" not in list_presets("nozzle")


def test_anchors_refuse_without_a_tester_supplied_reference_nozzle(monkeypatch, tmp_path):
    monkeypatch.setenv("SOLIT2_REFERENCE_NOZZLE", str(tmp_path / "absent.json"))
    with pytest.raises(ReferenceNozzleMissing, match="SOLIT2 reference test nozzle"):
        compare.load_anchors()


def test_anchor_designs_carry_the_testers_reference_nozzle():
    nozzle = load_reference_nozzle()
    for anchor in compare.load_anchors():
        assert anchor.design.nozzles.k_factor_lpm_bar05 == nozzle["k_factor_lpm_bar05"]
        assert anchor.design.nozzles.spread_n("fine") == pytest.approx(2.5, abs=1e-3)
```

- [ ] **Step 3: Run to verify they fail**

Run: `uv run pytest tests/test_validation.py -q -k "reference_nozzle"`
Expected: FAIL (`ImportError: ReferenceNozzleMissing`).

- [ ] **Step 4: Implement**

`solit2/schema/design.py`: change `Nozzles.preset: str` to `preset: str = "tester_input"`. In `from_dict`, replace the loop body with:

```python
            block_raw = merged.get(block, {})
            name = block_raw.get("preset")
            if block == "nozzles" and name in (None, "tester_input"):
                # The tester typed every field (or supplied a file of them); there is
                # no preset to merge and nothing may be filled in behind their back.
                merged[block] = {**block_raw, "preset": "tester_input"}
                continue
            if name is None:
                raise ValueError(f"design block {block!r} must name a preset")
            merged[block] = deep_merge(load_preset(kind, name), block_raw)
```

`validation/compare.py`: add at module level:

```python
import os

REFERENCE_NOZZLE_ENV = "SOLIT2_REFERENCE_NOZZLE"
DEFAULT_REFERENCE_NOZZLE_PATH = Path(__file__).resolve().parent.parent / "designs" / "solit2-reference-nozzle.json"
REFERENCE_NOZZLE_FIELDS = ("k_factor_lpm_bar05", "pressure_bar",
                           "modes[].smd_um / dv50_um / dv90_um / cone_half_angle_deg / launch_velocity_ms",
                           "mounting.rows / row_lateral_offsets_m / height_above_carriageway_m / pitch_m / tilt_deg")


class ReferenceNozzleMissing(FileNotFoundError):
    """The SOLIT2 reference test nozzle's data has not been supplied."""


def load_reference_nozzle(path: Path | None = None) -> dict:
    """The nozzle of the SOLIT2 reference tests, as the tester supplied it.

    SOLIT2 Annex 2 publishes the measured results of c4-c6 but none of the test
    system's nozzle data (K-factor, pressure, drop spectrum, mounting), so the
    anchors cannot be run until someone who holds that data enters it. Nothing
    here is filled in on their behalf.
    """
    path = path or Path(os.environ.get(REFERENCE_NOZZLE_ENV) or DEFAULT_REFERENCE_NOZZLE_PATH)
    if not path.exists():
        raise ReferenceNozzleMissing(
            f"no SOLIT2 reference test nozzle at {path}. SOLIT2 Annex 2 does not publish it; "
            f"create that file with the reference test system's measured {', '.join(REFERENCE_NOZZLE_FIELDS)}.")
    raw = json.loads(path.read_text())
    nozzles = Nozzles.model_validate({**raw, "preset": "tester_input"})
    for mode in nozzles.modes:
        nozzles.spread_n(mode.id)  # raises MissingNozzleData naming the missing field
    return {**raw, "preset": "tester_input"}
```

(Import `Nozzles` from `solit2.schema.design` next to the existing `Design` import.) In `load_anchors`, add the keyword `*, reference_nozzle: dict | None = None`, resolve it once with `nozzle = reference_nozzle if reference_nozzle is not None else load_reference_nozzle()`, and pass `{**raw["design"], "nozzles": nozzle}` to `_load_design` in place of `raw["design"]`.

Remove the `"nozzles": {...}` block from each of the three anchor JSON files. Delete `solit2/presets/nozzle_solit2_reference.json`.

`solit2/cli.py` `_cmd_validate`: wrap the `compare.load_anchors(ids)` call:

```python
    try:
        anchors = compare.load_anchors(ids)
    except (compare.ReferenceNozzleMissing, MissingNozzleData) as exc:
        return _fail(str(exc), "reference_nozzle",
                     f"create {compare.DEFAULT_REFERENCE_NOZZLE_PATH} (or set "
                     f"{compare.REFERENCE_NOZZLE_ENV}) with the SOLIT2 reference test nozzle's data", 2)
    for anchor in anchors:
```

and add a `--reference-nozzle` option to the `validate` subparser that, when given, sets `os.environ[compare.REFERENCE_NOZZLE_ENV]` before the call. Do the same `--reference-nozzle` option in `validation/fit.py` `_main`.

`tests/test_mist.py` `_solit2_reference_design`: it already returns `compare.load_anchors(("c4",))[0].design` (line 91), so it keeps working through the conftest fixture. If a helper above it builds from `{"preset": "solit2_reference"}`, replace that dict with `json.loads(REFERENCE_NOZZLE_FIXTURE.read_text())` imported from `tests.conftest`. `tests/test_design_schema.py:213`: replace `{"preset": "solit2_reference"}` with the fixture's JSON the same way.

`solit2/reports/twin.py:17,35-44` still reads the deleted preset. That is Task 4's to remove. For now, make `gallery_mount_height_m` raise instead of falling back: replace the `ref_m = ...` fallback block with `raise ValueError(f"nozzle mounting cannot be reproduced in the {gallery_m:.2f} m test gallery: the tester's {site_m:.2f} m head height does not fit between the {fuel_top_m:.2f} m fuel top and the ceiling; enter a gallery mounting height")`, and delete `REFERENCE_NOZZLE`. Update `tests/test_twin.py:46-48,65` so they expect that `ValueError` rather than the reference height.

- [ ] **Step 5: Run the suite**

Run: `uv run pytest -q`
Expected: PASS apart from the xfails Task 1 introduced. Also run `SOLIT2_REFERENCE_NOZZLE=/nonexistent uv run solit2 validate; echo "exit $?"`. Expected: the refusal message and exit 2, no traceback.

- [ ] **Step 6: Record provenance**

`solit2/presets/calibration.json` `provenance.note`: prepend "2026-09-27: the reference nozzle these constants were fitted with (K 2.8, 100 bar, SMD 90 um) was back-figured, not published by SOLIT2, and has been withdrawn; the ceiling correlation is now the published one (1.0). Every fitted constant below therefore carries an assumed nozzle and a superseded 0.314 multiplier until refit against a tester-supplied reference nozzle (`uv run python -m validation.fit --reference-nozzle PATH`)." In `INDEPENDENCE.md` §3, add one paragraph saying the same.

- [ ] **Step 7: Commit**

```bash
git add -A solit2 validation tests INDEPENDENCE.md
git commit -m "feat(validation): the SOLIT2 reference nozzle is tester-supplied, never assumed

SOLIT2 Annex 2 publishes no nozzle data for c4-c6. The back-figured preset is
withdrawn; validate and the fit refuse until the tester provides the file.

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: The Annex 7 test built from Annex 7 clauses only

**Files:**
- Modify: `solit2/reports/twin.py` (whole module)
- Modify: `solit2/engines/reduced/sim.py:291-298` (`_require_detection`)
- Test: `tests/test_twin.py`

**Interfaces:**
- Consumes: `Design.from_dict` preset-free `nozzles` (Task 3).
- Produces:

```python
@dataclass(frozen=True)
class Annex7Inputs:
    fire_class: Literal["A", "B"]
    activation_s: float        # AHJ trigger; A: >= 60 s (5.2.8), B: <= 120 s (5.3.7)
    ambient_c: float           # test-day gallery air temperature
    ambient_rh_pct: float      # test-day relative humidity
    growth_alpha_kw_s2: float  # free-burn t^2 growth of the mock-up: AHJ design fire / lab calibration
    incubation_s: float        # ignition to start of t^2 growth: AHJ design fire / lab calibration
def test_facility_twin(design: Design, inputs: Annex7Inputs) -> Design
ANNEX7_VELOCITIES_MS = (1.5, 3.0)
```

Clause map. This is every value the builder writes and where it comes from:

| Field | Value | Source |
|---|---|---|
| tunnel | `solit2_test` + `ambient_temp_c`/`ambient_rh_pct` from inputs | Annex 2 §2 geometry; ambient = tester |
| fire A | `hgv_150mw`, `covered: true` | Annex 7 5.2.1, 5.2.2, Table 4 rows 1–2 |
| fire B | `pool_60mw` | Annex 7 5.3.1, 5.3.2, Table 4 rows 3–4 |
| fire growth | `alpha_kw_s2 = inputs.growth_alpha_kw_s2`, `incubation_s = inputs.incubation_s` (overriding the presets' uncited `ultrafast`/60 s and `fast`/0 s) | Annex 7 sets the fuel, not its growth law; the free-burn law is not observable in a suppressed SOLIT² test (c4 anchor note), so it is AHJ/tester input |
| ventilation | `velocity_range_ms: [1.5, 3.0]` | 5.2.7 (A), 5.3.6 (B) |
| activation | `manual_activation_s = inputs.activation_s`, `activation_delay_s: 0` | 5.2.8 / 5.3.7: manual, AHJ trigger |
| discharge A | `duration_min = ceil((activation_s + 1800) / 60)` | 5.2.8: ≥ 30 min after activation |
| discharge B | `duration_min = 60` run horizon, asserted to end with the fire out | 5.3.7: until extinguished or fuel consumed |
| activation area | tester's `section_length_m × sections_simultaneous`, must be ≥ 3 × mock-up length | 5.2.8 / 5.3.7: manufacturer defines, ≥ 3× |
| nozzles, hydraulics, pump_ramp_s, detection | the tester's design | tester |
| head height | tester's height, or refuse | tester |

- [ ] **Step 1: Write the failing tests**

Replace the construction calls in `tests/test_twin.py` with `twin.test_facility_twin(site, INPUTS)`, where `INPUTS = twin.Annex7Inputs("A", activation_s=150.0, ambient_c=20.0, ambient_rh_pct=60.0, growth_alpha_kw_s2=0.1876, incubation_s=243.0)` (test values; every other `Annex7Inputs(...)` in this task takes the same two trailing arguments), and add:

```python
def test_twin_takes_the_annex7_mockup_not_the_sites_fire():
    site = _design_with_mount(4.5)  # existing helper
    t = twin.test_facility_twin(site, INPUTS)
    assert t.fire.design_hrr_mw == 150.0 and t.fire.covered is True
    assert t.ventilation.velocity_range_ms == (1.5, 3.0)
    assert t.zones.manual_activation_s == 150.0
    assert t.zones.duration_min >= (150.0 + 30 * 60) / 60
    assert t.tunnel.ambient_temp_c == 20.0
    assert t.fire.alpha == 0.1876 and t.fire.incubation_s == 243.0


def test_class_a_activation_before_one_minute_is_refused():
    with pytest.raises(ValueError, match="5.2.8"):
        twin.test_facility_twin(_design_with_mount(4.5),
                                twin.Annex7Inputs("A", 45.0, 20.0, 60.0))


def test_class_b_activation_after_two_minutes_is_refused():
    with pytest.raises(ValueError, match="5.3.7"):
        twin.test_facility_twin(_design_with_mount(4.5),
                                twin.Annex7Inputs("B", 150.0, 20.0, 60.0))


def test_activation_area_shorter_than_three_mockups_is_refused():
    site = _design_with_mount(4.5)
    short = site.model_copy(update={"zones": site.zones.model_copy(
        update={"section_length_m": 8.0, "sections_simultaneous": 1})})
    with pytest.raises(ValueError, match="3 times the length"):
        twin.test_facility_twin(short, INPUTS)
```

(`_design_with_mount` must build its nozzle with `dv50_um`/`dv90_um`. If it uses an example preset, Task 2 already gave it a spectrum.)

- [ ] **Step 2: Run to verify they fail**

Run: `uv run pytest tests/test_twin.py -q`
Expected: FAIL (`Annex7Inputs` undefined).

- [ ] **Step 3: Implement `twin.py`**

Replace the module body after the docstring and imports with:

```python
import math
from dataclasses import dataclass
from typing import Literal

GALLERY_TUNNEL = "solit2_test"
ANNEX7_VELOCITIES_MS = (1.5, 3.0)                  # 5.2.7 (Class A), 5.3.6 (Class B)
ANNEX7_FIRE = {"A": "hgv_150mw", "B": "pool_60mw"}  # 5.2.1-5.2.2, 5.3.1-5.3.2; Table 4
CLASS_A_MIN_ACTIVATION_S = 60.0                    # 5.2.8 A: "Minimum 1 minutes after ignition"
CLASS_B_MAX_ACTIVATION_S = 120.0                   # 5.3.7: "within 2 minutes after ignition"
CLASS_A_MIN_DISCHARGE_S = 30 * 60.0                # 5.2.8: "minimum of 30 minutes after activation"
ACTIVATION_AREA_MOCKUP_MULTIPLE = 3.0              # 5.2.8 / 5.3.7: "minimum 3 times the length of the mock-up"
# 5.3.7 runs Class B "until the fire is extinguished or the fuel is consumed";
# this is only how long the engine is run, and the test asserts it covers that.
CLASS_B_RUN_HORIZON_MIN = 60.0


@dataclass(frozen=True)
class Annex7Inputs:
    """The Annex 7 test conditions that SOLIT2 leaves to the AHJ or the test day."""
    fire_class: Literal["A", "B"]
    activation_s: float
    ambient_c: float
    ambient_rh_pct: float


def _check_activation(inputs: Annex7Inputs) -> None:
    if inputs.fire_class == "A" and inputs.activation_s < CLASS_A_MIN_ACTIVATION_S:
        raise ValueError(f"Annex 7 5.2.8: Class A activation must be at least 60 s after "
                         f"ignition, got {inputs.activation_s:g} s")
    if inputs.fire_class == "B" and inputs.activation_s > CLASS_B_MAX_ACTIVATION_S:
        raise ValueError(f"Annex 7 5.3.7: Class B activation must be within 120 s of "
                         f"ignition, got {inputs.activation_s:g} s")


def gallery_mount_height_m(design: Design, fuel_top_m: float) -> float:
    """The tester's head height, if the SOLIT2 gallery can hold it. Never a substitute."""
    gallery_m = float(load_preset("tunnel", GALLERY_TUNNEL)["height_m"])
    site_m = design.nozzles.mounting.height_above_carriageway_m
    if not fuel_top_m < site_m < gallery_m:
        raise ValueError(
            f"nozzle mounting cannot be reproduced in the {gallery_m:.2f} m SOLIT2 gallery: "
            f"the tester's {site_m:.2f} m head height does not fit between the "
            f"{fuel_top_m:.2f} m fuel top and the ceiling; enter the height the heads "
            f"will be tested at")
    return site_m


def test_facility_twin(design: Design, inputs: Annex7Inputs) -> Design:
    _check_activation(inputs)
    fire = load_preset("fire", ANNEX7_FIRE[inputs.fire_class])
    mockup_m = float(fire["footprint"]["length_m"])
    area_m = design.zones.section_length_m * design.zones.sections_simultaneous
    if area_m < ACTIVATION_AREA_MOCKUP_MULTIPLE * mockup_m:
        raise ValueError(f"Annex 7 5.2.8/5.3.7: the activation area must be at least 3 times "
                         f"the length of the mock-up ({3 * mockup_m:g} m); this system "
                         f"activates {area_m:g} m")
    height_m = gallery_mount_height_m(design, float(fire["footprint"]["top_height_m"]))
    nozzles = design.nozzles.model_dump(mode="json", by_alias=True)
    nozzles["mounting"] = {**nozzles["mounting"], "height_above_carriageway_m": height_m}
    duration_min = (math.ceil((inputs.activation_s + CLASS_A_MIN_DISCHARGE_S) / 60.0)
                    if inputs.fire_class == "A" else CLASS_B_RUN_HORIZON_MIN)
    raw = {
        "meta": {"name": f"{design.meta.name}-annex7-class-{inputs.fire_class.lower()}",
                 "notes": "SOLIT2 Annex 7 test of the tester's nozzle; every other value is "
                          "an Annex 7 clause or a test-day input (solit2/reports/twin.py)."},
        "tunnel": {"preset": GALLERY_TUNNEL, "section": "test",
                   "ambient_temp_c": inputs.ambient_c, "ambient_rh_pct": inputs.ambient_rh_pct},
        "fire": {"preset": ANNEX7_FIRE[inputs.fire_class],
                 "alpha_kw_s2": inputs.growth_alpha_kw_s2, "incubation_s": inputs.incubation_s,
                 **({"covered": True} if inputs.fire_class == "A" else {})},
        "nozzles": nozzles,
        "hydraulics": design.hydraulics.model_dump(mode="json", by_alias=True),
        "zones": {"section_length_m": design.zones.section_length_m,
                  "sections_simultaneous": design.zones.sections_simultaneous,
                  "manual_activation_s": inputs.activation_s, "activation_delay_s": 0.0,
                  "pump_ramp_s": design.zones.pump_ramp_s, "duration_min": duration_min},
        "ventilation": {"mode": "longitudinal", "velocity_range_ms": list(ANNEX7_VELOCITIES_MS)},
        "detection": design.detection.model_dump(mode="json", by_alias=True),
        "ahj": design.ahj.model_dump(mode="json", by_alias=True),
        "constraints": {},
    }
    return Design.from_dict(raw)
```

Delete `PROTOCOL_ZONES`, `PROTOCOL_VENTILATION`, `PROTOCOL_DETECTION`. Update the module docstring: the fire is the Annex 7 mock-up, not the site's fire.

`solit2/engines/reduced/sim.py` `_require_detection`: add as the first line `if design.zones.manual_activation_s is not None: return  # Annex 7 5.2.8/5.3.7: activation is manual`.

- [ ] **Step 4: Class B horizon test**

Append to `tests/test_twin.py`:

```python
def test_class_b_horizon_covers_the_whole_fire():
    from solit2.engines.reduced.sim import run_once
    t = twin.test_facility_twin(_design_with_mount(4.5),
                                twin.Annex7Inputs("B", 100.0, 20.0, 60.0))
    trace = run_once(t, "test", 3.0)
    assert trace.steps[-1].hrr_mw < 0.01 * max(s.hrr_mw for s in trace.steps)
```

If it fails, the horizon is too short. Raise `CLASS_B_RUN_HORIZON_MIN`, never the tolerance.

- [ ] **Step 5: Run and commit**

Run: `uv run pytest tests/test_twin.py tests/test_sim.py -q`, then `uv run pytest -q`.
Expected: PASS apart from the Task 1 xfails.

```bash
git add solit2/reports/twin.py solit2/engines/reduced/sim.py tests/test_twin.py
git commit -m "feat(twin): build the Annex 7 test from Annex 7 clauses and test-day inputs only

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: Design step asks the tester for every nozzle value

**Files:**
- Modify: `app/views/design.py` (`_render_preset_pickers`, `_render_nozzle_hydraulics_inputs`, `_assemble`, `SEEDED_FIELDS`, `render`)
- Test: `tests/test_app_design_step.py` (use the existing app-test file for the Design step; find it with `ls tests | grep -i design`)

**Interfaces:**
- Consumes: preset-free `nozzles` block (Task 3); `Mode.dv50_um`/`dv90_um` (Task 2).
- Produces: `NOZZLE_FIELDS` (tuple of `(widget_key, path, label, min, max, step)`), `nozzle_block(values: dict) -> tuple[dict | None, list[str]]`, which returns the nozzles dict and the labels still missing.

- [ ] **Step 1: Write the failing test**

```python
from app.views import design as design_view


def test_nozzle_block_lists_every_missing_field_and_builds_nothing():
    block, missing = design_view.nozzle_block({})
    assert block is None
    assert "Dv90 (µm)" in missing and "K-factor (L/min·bar⁰·⁵)" in missing


def test_nozzle_block_is_preset_free_and_carries_only_what_was_typed():
    values = {"d_k": 2.8, "d_pressure": 100.0, "d_smd": 90.0, "d_dv50": 115.744,
              "d_dv90": 187.088, "d_cone": 50.0, "d_launch": 25.0, "d_mount_h": 4.9,
              "d_rows": 2, "d_offsets": "-2.2, 2.2", "d_pitch": 4.0, "d_tilt": 0.0}
    block, missing = design_view.nozzle_block(values)
    assert missing == []
    assert block["preset"] == "tester_input"
    assert block["modes"][0]["dv90_um"] == 187.088
    assert block["mounting"]["row_lateral_offsets_m"] == [-2.2, 2.2]
```

- [ ] **Step 2: Run to verify it fails**

Run: `uv run pytest tests/test_app_design_step.py -q -k nozzle_block`
Expected: FAIL (`nozzle_block` undefined).

- [ ] **Step 3: Implement**

In `app/views/design.py`:

```python
NOZZLE_FIELDS = (
    ("d_k", ("nozzles", "k_factor_lpm_bar05"), "K-factor (L/min·bar⁰·⁵)", 0.6, 20.0, 0.1),
    ("d_pressure", ("nozzles", "pressure_bar"), "Working pressure (bar)", 34.5, 140.0, 0.5),
    ("d_smd", ("nozzles", "modes", 0, "smd_um"), "Sauter mean D32 (µm)", 1.0, 3000.0, 1.0),
    ("d_dv50", ("nozzles", "modes", 0, "dv50_um"), "Dv50 (µm)", 1.0, 3000.0, 1.0),
    ("d_dv90", ("nozzles", "modes", 0, "dv90_um"), "Dv90 (µm)", 1.0, 5000.0, 1.0),
    ("d_cone", ("nozzles", "modes", 0, "cone_half_angle_deg"), "Spray cone half-angle (°)", 1.0, 89.0, 1.0),
    ("d_launch", ("nozzles", "modes", 0, "launch_velocity_ms"), "Discharge velocity (m/s)", 0.1, 200.0, 0.5),
    ("d_mount_h", ("nozzles", "mounting", "height_above_carriageway_m"), "Head height above road (m)", 0.1, 20.0, 0.05),
    ("d_rows", ("nozzles", "mounting", "rows"), "Nozzle rows", 1, 3, 1),
    ("d_pitch", ("nozzles", "mounting", "pitch_m"), "Nozzle spacing / pitch (m)", 0.1, 10.0, 0.1),
    ("d_tilt", ("nozzles", "mounting", "tilt_deg"), "Head tilt (°)", -45.0, 45.0, 1.0),
)
OFFSETS_KEY, OFFSETS_LABEL = "d_offsets", "Row lateral offsets from centre line (m, comma-separated)"


def nozzle_block(values: dict) -> tuple[dict | None, list[str]]:
    """The tester's nozzle as a preset-free design block, or the fields still missing."""
    missing = [label for key, _, label, *_ in NOZZLE_FIELDS if values.get(key) is None]
    offsets_text = (values.get(OFFSETS_KEY) or "").strip()
    if not offsets_text:
        missing.append(OFFSETS_LABEL)
    if missing:
        return None, missing
    v = values
    return {
        "preset": "tester_input",
        "k_factor_lpm_bar05": v["d_k"], "pressure_bar": v["d_pressure"],
        "modes": [{"id": "fine", "fraction": 1.0, "smd_um": v["d_smd"], "dv50_um": v["d_dv50"],
                   "dv90_um": v["d_dv90"], "cone_half_angle_deg": v["d_cone"],
                   "launch_velocity_ms": v["d_launch"]}],
        "mounting": {"type": "ceiling_rows", "rows": int(v["d_rows"]),
                     "row_lateral_offsets_m": [float(x) for x in offsets_text.split(",")],
                     "height_above_carriageway_m": v["d_mount_h"], "pitch_m": v["d_pitch"],
                     "tilt_deg": v["d_tilt"]},
    }, []


def _render_nozzle_inputs(raw: dict) -> tuple[dict | None, list[str]]:
    """Every nozzle value the engine uses, typed by the tester. No defaults."""
    st.subheader("Nozzle (tester input)")
    st.caption("Enter the nozzle's measured data. Nothing here is filled in for you, and "
               "the run will not start until every field is set.")
    values = {}
    cols = st.columns(3)
    for i, (key, path, label, low, high, step) in enumerate(NOZZLE_FIELDS):
        seeded = _dig(raw, *path)
        with cols[i % 3]:
            values[key] = st.number_input(
                label, min_value=low, max_value=high, step=step, key=key,
                value=None if seeded is None else min(max(type(low)(seeded), low), high))
    seeded_offsets = _dig(raw, "nozzles", "mounting", "row_lateral_offsets_m")
    values[OFFSETS_KEY] = st.text_input(
        OFFSETS_LABEL, key=OFFSETS_KEY,
        value="" if seeded_offsets is None else ", ".join(f"{x:g}" for x in seeded_offsets))
    return nozzle_block(values)
```

`_dig` must accept integer path steps. It already does (see the `isinstance(step, int)` branch). In `_render_preset_pickers`, delete the nozzle `selectbox` and return a 3-tuple `(tunnel_preset, fire_preset, hydraulics_preset)`. In `render`, replace the `_render_nozzle_hydraulics_inputs` call with `nozzles, missing = _render_nozzle_inputs(raw_source)`. Pass `nozzles` to `_assemble` in place of `nozzle_preset, k_factor, pressure_bar, rows, pitch_m`, and have `_assemble` put `raw["nozzles"] = nozzles` when it is not None. Before the Build button add `if missing: st.warning("Nozzle data still needed: " + ", ".join(missing))` and pass `disabled=bool(missing)` to the button. In `SEEDED_FIELDS`, remove the `d_nozzle`, `d_k`, `d_pressure`, `d_rows` and `d_pitch` rows. Their seeding now happens in `_render_nozzle_inputs` through `_dig(raw, *path)`. `_apply_to_widgets` must also clear or seed the new keys when a design file is picked, so extend it with the `NOZZLE_FIELDS` keys and `OFFSETS_KEY`, using `None`/`""` when the file lacks them. Update the page caption to "Pick a starting preset for the tunnel, fire and hydraulics. The nozzle is yours to enter."

- [ ] **Step 4: Run the tests and the app**

Run: `uv run pytest -q`
Then `preview_start` `solit2-streamlit`. Sign-in needs an account. Create a test account through the project's own accounts store with `SOLIT2_DATA_DIR` pointing at the scratchpad, record the test credentials in that scratch dir only, and never echo them in chat. Confirm: the Design step shows empty nozzle fields, the Build button is disabled with the missing list, and loading `designs/og-dbr-rev0.json` seeds what the file has and lists Dv50/Dv90 as missing.

- [ ] **Step 5: Commit**

```bash
git add app/views/design.py tests/
git commit -m "feat(ui): the Design step asks the tester for every nozzle value, with no defaults

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 6: Fire test page runs the SOLIT² Annex 7 test

**Files:**
- Modify: `app/views/fire_test.py`
- Modify: `app/views/reports.py:22`
- Modify: `app/state.py` (store and read `Annex7Inputs`)
- Test: `tests/test_app_fire_test_step.py` (or the existing fire-test app test; find it with `ls tests | grep -i fire`)

**Interfaces:**
- Consumes: `twin.Annex7Inputs`, `twin.test_facility_twin`, `twin.ANNEX7_VELOCITIES_MS` (Task 4).
- Produces: `state.get_annex7_inputs() -> Annex7Inputs | None`, `state.set_annex7_inputs(inputs: Annex7Inputs) -> None`.

- [ ] **Step 1: Write the failing test**

Using the pattern the existing app tests follow (Streamlit `AppTest`, or calling view helpers directly, whichever `tests/test_app_*` already uses), assert that:
1. with a design lacking Dv50/Dv90, the Fire test page shows an error naming "Dv50 and Dv90" and draws no chart;
2. with a complete tester nozzle and `Annex7Inputs("A", 150, 20, 60)` stored, the page's trace comes from `run_once(test_facility_twin(design, inputs), "test", v)` for the selected `v` in `(1.5, 3.0)`. Monkeypatch `fire_test._trace` to record its arguments and assert `section == "test"` and `velocity_ms in (1.5, 3.0)`.

- [ ] **Step 2: Implement**

In `app/views/fire_test.py`:
- Add `_render_annex7_inputs() -> Annex7Inputs | None`. It shows a Class A / Class B radio, `st.number_input("Activation time after ignition (s) — set by the AHJ", value=None)`, the ambient temperature and RH, `"Fire growth α (kW/s²) — AHJ design fire"` and `"Incubation, ignition to growth (s) — AHJ design fire"`, all `value=None`. It returns `None` and shows `st.info` until every field is set, then stores the inputs with `state.set_annex7_inputs`.
- In `render()`, after `design = state.get_design()`: get the inputs and stop if they are `None`. Then call `test = twin.test_facility_twin(design, inputs)` inside `try/except (ValueError, MissingNozzleData) as exc: st.error(str(exc)); return`. Then add `velocity = st.radio("Annex 7 ventilation (m/s)", twin.ANNEX7_VELOCITIES_MS, horizontal=True, key="annex7_v")`, `result = ensure_result(test)`, `trace = _trace(test, "test", velocity)`, `geom = section_geometry(test)`, and use `test` wherever the view currently uses `design`.
- Header caption: "SOLIT² Annex 7 test of your nozzle in the SOLIT² gallery. Tier 1 prediction, not a measurement."
- `ensure_trace` is no longer used by `render`. Delete it if nothing else imports it (`grep -rn ensure_trace app tests`).

In `app/views/reports.py:22`: `inputs = state.get_annex7_inputs()`. If it is `None`, show `st.info("Enter the Annex 7 test inputs on the Fire test step first.")` and skip the twin section. Otherwise call `twin.test_facility_twin(design, inputs)`. Update `tests/test_app_reports_step.py:22`, whose `boom` monkeypatch must accept `(design, inputs)`.

- [ ] **Step 3: Verify in the browser**

Run `uv run pytest -q`, then drive the preview. Load a design with a complete tester nozzle, set Class A, 150 s, 20 °C, 60 %, and check:
- Station chart at 1.5 m/s: the D-station thermocouple lines separate by height, and U-stations stay near ambient.
- The ceiling temperature in the HMI is not the old ~44 °C.
- Switching to 3.0 m/s changes the trace.

Take a screenshot as proof.

- [ ] **Step 4: Commit**

```bash
git add app tests
git commit -m "feat(ui): the Fire test step runs the SOLIT2 Annex 7 test of the tester's nozzle

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 7: Record it and verify end to end

**Files:**
- Modify: `docs/accuracy-roadmap.md` (item 3 and item 1)
- Modify: `CLAUDE.md` ("Reading a result honestly": the engine's gas temperatures are now the published correlation, and the fitted mist constants await a tester-supplied reference nozzle)

- [ ] **Step 1: Roadmap**

Item 3, "Ceiling temperature is 3× low": tick it with "resolved 2026-09-27 on the temperature side: the correlation is published (1.0) and out of the fit. Open on the spray side: until a tester supplies the SOLIT² reference nozzle, the fitted mist constants were fitted jointly with the superseded 0.314 and an assumed nozzle. Scratch evidence: at 1.0 with a 200 µm reference SMD, c4 29.3 MW / 657 °C and c5 15.0 MW / 476 °C, but that SMD is not SOLIT² data and is not used." Item 1: add "Dv50 and Dv90 now required inputs (Rosin-Rammler n derived; `Nozzles.spread_n`)".

- [ ] **Step 2: Full verification**

Run each and paste the output into the task report:
```bash
uv run pytest -q
SOLIT2_REFERENCE_NOZZLE=/nonexistent uv run solit2 validate; echo "exit $?"
uv run solit2 run designs/og-dbr-rev0.json --no-history | python3 -c "import json,sys; r=json.load(sys.stdin); print(r['peaks'], r['warnings'][:3])"
```
Expected: the suite passes with only the documented xfails; validate refuses with exit 2; the baseline run refuses with `MissingNozzleData` until Dv50/Dv90 are in `designs/og-dbr-rev0.json`. Do not add them yourself. The user supplies the MTX values.

- [ ] **Step 3: Commit**

```bash
git add docs/accuracy-roadmap.md CLAUDE.md
git commit -m "docs: record the published ceiling correlation and the tester-supplied nozzle data

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

## After this plan (needs the user)

1. **MTX Dv50/Dv90** into `designs/og-*.json`. Until then those designs refuse to run.
2. **SOLIT² reference nozzle file** `designs/solit2-reference-nozzle.json`, from whoever holds the SOLIT² test system's data. Then refit with `uv run python -m validation.fit --reference-nozzle designs/solit2-reference-nozzle.json --max-nfev N` (time one `compare.residuals` call first; see `validation/fit.py` `run`), and remove the Task 1 xfails the refit resolves.
3. The deluge / LP / HP designs from the 2026-09-26 session sit untracked in the main checkout (`examples/designs/road-tunnel-twin-bore-*.json`). They also need Dv50/Dv90 before they run.

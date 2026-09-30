# Virtual Fire Test Report Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `uv run solit2 report virtual-test <compliance-spec.json> --out <path.html>`, producing one self-contained, offline HTML document that lays out the SOLIT² Annex 7 tests a compliance spec names (test designs "A" and, when present, "B") in the same shape a real full-scale fire test report uses, entirely from this tool's own Tier 1 output.

**Architecture:** A new `solit2/reports/html.py` gives every report module a shared, dependency-free HTML-document shell (print CSS, a mandatory "prediction, not a measurement" band, a table builder, and offline Plotly-figure embedding). A new `solit2/reports/virtual_test.py` builds the actual document as twelve section-builder functions, each a pure function over already-computed `Design`/`Result`/`RunTrace`/`ComplianceReport` objects — mirroring the existing `solit2/reports/{test_plan,compliance,correlation,assessment}.py` convention of returning a plain string built from a list of lines, except HTML lines instead of markdown. `solit2/cli.py` gains the CLI wiring and does the orchestration (load the spec, run the engine for every test design, run the compliance checker), exactly like `_cmd_report_correlation` already orchestrates two `Result`s before calling a pure `render()`.

**Tech Stack:** Python 3.12, pydantic (existing `Design`/`Result`/`ComplianceSpec` schemas), Plotly `>=7.1.0` (already a dependency — `plotly.io.to_html` for offline embedding), pytest. No new dependency.

**Spec:** `docs/superpowers/specs/2026-09-26-virtual-test-report-design.md`

## Global Constraints

- The output file is one self-contained HTML document: Plotly's JS bundle is embedded inline exactly once; the file makes no network request when opened (no CDN `<script src>`, no external stylesheet, no external font).
- Print CSS gives A4 pages, numbered sections, and a repeating header, so a browser's "Save as PDF" produces a lab-report-shaped PDF.
- A band reading exactly `VIRTUAL TEST — prediction, not a measurement.` appears on every page.
- No laboratory name, logo, signature, witness block, or anything else that reads as a real test.
- A pass/fail limit comes only from the design's own `ahj` block. A criterion whose `status == "unset"` (see `solit2/schema/result.py` `Criterion`) is shown as **limit not set** beside its predicted value — never a value borrowed from anywhere else.
- Every number in the report is this engine's own output. The free-burn heat release rate is `Result.timeseries["hrr_free_burn_mw"]` / `Result.peaks["hrr_free_burn_mw"]` — never a value typed in by hand.
- No content, figure, or limit is taken from any third party's report, and none is cited anywhere in the module or its output.
- `solit2/reports/virtual_test.py` and `solit2/reports/html.py` live under `solit2/`: per `INDEPENDENCE.md` rule 1 and `tests/test_independence.py`, neither file may name a manufacturer, a project, or a vendor — every name that appears in the rendered output comes from the `Design`/`ComplianceSpec` data at render time, never a literal in the module's own source.
- Every test design's own `meta.name` and the installation design's `meta.name` are the only "names" the report ever prints; the module itself prints no name of its own.

---

## Task 1: Engine change — `hrr_free_burn_mw` in the timeseries

**Files:**
- Modify: `solit2/engines/reduced/envelope.py:152-171` (the `_timeseries` function)
- Test: `tests/test_envelope.py` (add to existing file — check it exists first with `ls tests/test_envelope.py`; if the timeseries tests live in a different file, e.g. `tests/test_reduced_envelope.py`, add there instead and note the actual path in your report)

**Interfaces:**
- Consumes: `StepRecord.hrr_free_mw` (already exists, `solit2/engines/reduced/state.py`), already read by `envelope.py:137` for `peaks["hrr_free_burn_mw"]`.
- Produces: `Result.timeseries["hrr_free_burn_mw"]: list[float]`, one entry per sampled step, same length and same order as every other `Result.timeseries` key. Task 6 (the HRR comparison chart) consumes this key by name.

- [ ] **Step 1: Write the failing test**

```python
def test_timeseries_includes_the_free_burn_hrr():
    design = Design.load("examples/designs/road-tunnel-twin-bore.json")
    result = envelope.run(design)
    assert "hrr_free_burn_mw" in result.timeseries
    assert len(result.timeseries["hrr_free_burn_mw"]) == len(result.timeseries["t_s"])
    # Free-burn HRR is never below the suppressed HRR it is measured alongside.
    assert all(free >= actual for free, actual in
              zip(result.timeseries["hrr_free_burn_mw"], result.timeseries["hrr_mw"]))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_envelope.py::test_timeseries_includes_the_free_burn_hrr -v`
Expected: FAIL with `KeyError: 'hrr_free_burn_mw'` or an `assert False` on the `in` check.

- [ ] **Step 3: Write minimal implementation**

In `solit2/engines/reduced/envelope.py`, add one line to `_timeseries`:

```python
def _timeseries(sampled: tuple[StepRecord, ...]) -> dict[str, list[float]]:
    return {
        "t_s": [s.t_s for s in sampled],
        "hrr_mw": [s.hrr_mw for s in sampled],
        "hrr_free_burn_mw": [s.hrr_free_mw for s in sampled],
        "ceiling_temp_c": [s.ceiling_temp_c for s in sampled],
        "u45_temp_c": [s.stations["U45"].temp_c for s in sampled],
        "u15_temp_c": [s.stations["U15"].temp_c for s in sampled],
        "d15_temp_c": [s.stations["D15"].temp_c for s in sampled],
        "d100_temp_c": [s.stations["D100"].temp_c for s in sampled],
        "hf_u15_kwm2": [s.stations["U15"].flux_kwm2 for s in sampled],
        "hf_d15_kwm2": [s.stations["D15"].flux_kwm2 for s in sampled],
        "fed_d45": [s.stations["D45"].fed_tox for s in sampled],
        "backlayering_m": [s.backlayer_m for s in sampled],
        "velocity_ms": [s.u_eff_ms for s in sampled],
        "water_lpm": [s.water_lpm for s in sampled],
    }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_envelope.py::test_timeseries_includes_the_free_burn_hrr -v`
Expected: PASS

- [ ] **Step 5: Run the full existing suite for this file to confirm nothing else asserts an exact key set**

Run: `uv run pytest tests/test_envelope.py -v`
Expected: all PASS. If some test asserts `set(result.timeseries) == {...}` without `hrr_free_burn_mw`, update that assertion to include the new key (this is exactly the kind of test the new key should now satisfy, not break).

- [ ] **Step 6: Commit**

```bash
git add solit2/engines/reduced/envelope.py tests/test_envelope.py
git commit -m "feat(engine): report free-burn HRR in the timeseries"
```

---

## Task 2: The shared HTML report shell

**Files:**
- Create: `solit2/reports/html.py`
- Test: `tests/test_report_html.py`

**Interfaces:**
- Consumes: nothing from earlier tasks (this is infrastructure).
- Produces:
  - `BAND_TEXT = "VIRTUAL TEST — prediction, not a measurement."` (module constant)
  - `PRINT_CSS: str` (module constant, the print stylesheet)
  - `document(title: str, sections: list[tuple[str, str]]) -> str` — `sections` is `(heading, inner_html)` pairs in order; returns the full `<!DOCTYPE html>...</html>` string, numbered `<h2>` per section, a repeating `<header>` (fixed via print CSS `position: running()`-style repeat, see Step 3), the band at the top of every section, and the print stylesheet inlined in a `<style>` tag. No `<script src=...>` and no `<link>` to anything external.
  - `table(headers: list[str], rows: list[list[str]]) -> str` — one `<table>` with a `<thead>` row and one `<tbody>` row per entry in `rows`. Every cell is HTML-escaped (`html.escape`) since cell content comes from `Design.meta.name`, which is user-supplied.
  - `figure_html(fig: "plotly.graph_objects.Figure", *, first: bool) -> str` — `first=True` embeds the Plotly JS bundle inline (`include_plotlyjs="inline"`); every other call in the same document passes `first=False` (`include_plotlyjs=False`), since the bundle only needs to exist once per document. Returns a `<div>` containing the figure's own inline `<script>` (no `full_html`, `include_plotlyjs` controls the bundle, not `full_html`).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_report_html.py
import plotly.graph_objects as go
import pytest

from solit2.reports import html


def test_document_contains_no_network_reference():
    out = html.document("Test", [("Introduction", "<p>hello</p>")])
    assert "http://" not in out and "https://" not in out
    assert "<script src=" not in out
    assert "<link " not in out or 'rel="stylesheet" href="http' not in out


def test_document_carries_the_prediction_band_and_is_well_formed():
    out = html.document("Test", [("Introduction", "<p>hello</p>")])
    assert html.BAND_TEXT in out
    assert out.strip().startswith("<!DOCTYPE html>")
    assert "<h2>1. Introduction</h2>" in out


def test_table_escapes_untrusted_cell_content():
    out = html.table(["Name"], [["<script>alert(1)</script>"]])
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;" in out


def test_only_the_first_figure_embeds_plotly_js():
    fig = go.Figure(data=[go.Scatter(x=[1, 2], y=[3, 4])])
    first = html.figure_html(fig, first=True)
    second = html.figure_html(fig, first=False)
    assert "Plotly.newPlot" in first and html.BUNDLE_MARK in first  # the bundle itself
    assert html.BUNDLE_MARK not in second  # no bundle the second time
    assert "Plotly.newPlot" in second  # but the figure still renders


def test_external_references_finds_a_cdn_script_and_ignores_urls_inside_script_bodies():
    bad = '<html><script src="https://cdn.example/x.js"></script><link href="a.css"></html>'
    assert html.external_references(bad)
    # The embedded Plotly bundle contains https:// strings; they are never fetched.
    fine = "<html><script>var help = 'https://example.org/docs';</script><p>ok</p></html>"
    assert html.external_references(fine) == []
    assert html.external_references('<img src="//host/x.png">')
    assert html.external_references('<p style="background:url(http://h/x)">')


def test_a_real_plotly_bundle_is_not_an_external_reference():
    fig = go.Figure(data=[go.Scatter(x=[1, 2], y=[3, 4])])
    doc = html.document("T", [("Figure", html.figure_html(fig, first=True))])
    assert html.external_references(doc) == []


def test_escape_neutralises_markup():
    assert html.escape("<b>&") == "&lt;b&gt;&amp;"
```

Correction found while writing Tasks 6-10 (checked against plotly 7.1.0, which embeds plotly.js v4):
the minified bundle has no `function Plotly` declaration, so the marker is its licence header
`plotly.js v`, which appears exactly once in an inline bundle and never in a figure rendered with
`include_plotlyjs=False`. The bundle also contains `https://` strings inside its script body, so
"no network reference" cannot be a substring test; `external_references` below is the real check.

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_report_html.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'solit2.reports.html'`

- [ ] **Step 3: Write the implementation**

```python
# solit2/reports/html.py
"""A self-contained HTML document shell shared by every HTML report: the print
stylesheet, the mandatory prediction band, a table builder, and offline Plotly
embedding. No report-specific content lives here.
"""
from __future__ import annotations

import html as _html
import re

import plotly.graph_objects as go
import plotly.io as pio

BAND_TEXT = "VIRTUAL TEST — prediction, not a measurement."
# Appears once in an inline Plotly bundle (its licence header) and nowhere else.
BUNDLE_MARK = "plotly.js v"

PRINT_CSS = """
@page { size: A4; margin: 20mm 16mm; }
body { font-family: -apple-system, Helvetica, Arial, sans-serif; color: #111;
       margin: 0 auto; max-width: 960px; padding: 0 16px; }
header.report-header { position: sticky; top: 0; background: #fff;
       border-bottom: 2px solid #b00; padding: 8px 0; z-index: 1; }
.band { background: #b00; color: #fff; font-weight: 700; text-align: center;
        padding: 6px 0; letter-spacing: 0.02em; }
section { break-inside: avoid-page; margin-top: 24px; }
h2 { border-bottom: 1px solid #ccc; padding-bottom: 4px; }
table { border-collapse: collapse; width: 100%; margin: 12px 0; }
th, td { border: 1px solid #ccc; padding: 4px 8px; text-align: left;
         font-variant-numeric: tabular-nums; }
th { background: #f2f2f2; }
@media print {
  /* position: fixed repeats on every printed page in Chromium and Firefox;
     position: running() is a Paged-Media feature browsers ignore. */
  header.report-header { position: fixed; top: 0; left: 0; right: 0; }
  body { padding-top: 56px; }
  section { page-break-after: always; }
}
"""


def escape(text: str) -> str:
    """HTML-escape untrusted text (design names come from user-supplied files)."""
    return _html.escape(text)


_SCRIPT_BODY = re.compile(r"<script\b[^>]*>.*?</script>", re.DOTALL | re.IGNORECASE)
_SCRIPT_OPEN = re.compile(r"<script\b[^>]*>", re.IGNORECASE)
_EXTERNAL = (
    re.compile(r"<script\b[^>]*\ssrc\s*=", re.IGNORECASE),
    re.compile(r"<link\b", re.IGNORECASE),
    re.compile(r"""\b(?:src|href|action)\s*=\s*["']?(?:https?:)?//""", re.IGNORECASE),
    re.compile(r"@import\b", re.IGNORECASE),
    re.compile(r"""url\(\s*["']?(?:https?:)?//""", re.IGNORECASE),
)


def external_references(document_html: str) -> list[str]:
    """Anything that would make a browser fetch something when the file opens.

    Script BODIES are skipped: the embedded Plotly bundle holds many `https://`
    strings that are never requested. A `<script src=...>` tag is still caught,
    because the opening tag is kept when its body is dropped."""
    outside = _SCRIPT_BODY.sub(lambda m: _SCRIPT_OPEN.match(m.group(0)).group(0) + "</script>",
                               document_html)
    return [m.group(0) for rx in _EXTERNAL for m in rx.finditer(outside)]


def document(title: str, sections: list[tuple[str, str]]) -> str:
    """`sections` is (heading, inner_html) pairs, in the order they appear.
    Every section repeats the band; the header is fixed so it repeats on
    every printed page."""
    safe_title = escape(title)
    body_sections = "\n".join(
        f'<section id="s{i}">\n<div class="band">{BAND_TEXT}</div>\n'
        f"<h2>{i}. {escape(heading)}</h2>\n{inner}\n</section>"
        for i, (heading, inner) in enumerate(sections, start=1))
    return (
        "<!DOCTYPE html>\n"
        f'<html lang="en"><head><meta charset="utf-8"><title>{safe_title}</title>\n'
        f"<style>{PRINT_CSS}</style></head>\n"
        "<body>\n"
        f'<header class="report-header"><div class="band">{BAND_TEXT}</div>'
        f"<strong>{safe_title}</strong></header>\n"
        f"{body_sections}\n"
        "</body></html>\n"
    )


def table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = "\n".join(
        "<tr>" + "".join(f"<td>{escape(str(cell))}</td>" for cell in row) + "</tr>"
        for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>\n{body}\n</tbody></table>"


def figure_html(fig: go.Figure, *, first: bool) -> str:
    """`first=True` embeds the Plotly JS bundle inline (once per document);
    every later figure in the same document passes `first=False`."""
    return pio.to_html(fig, full_html=False,
                       include_plotlyjs="inline" if first else False,
                       config={"displayModeBar": False})
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_report_html.py -v`
Expected: PASS. If `test_document_carries_the_prediction_band_and_is_well_formed` fails on the exact heading string, check whether `document()`'s numbering format matches `<h2>1. Introduction</h2>` exactly (case and punctuation) and adjust the test or the f-string to agree — they must describe the same string.

- [ ] **Step 5: Commit**

```bash
git add solit2/reports/html.py tests/test_report_html.py
git commit -m "feat(reports): shared offline HTML document shell for reports"
```

---

## Task 3: CLI wiring and a minimal end-to-end skeleton

Get the whole pipe working end to end — CLI to a real file on disk — before writing any of the heavy content sections. This proves the wiring, the exit codes, the `--out` handling, and the two constraints that are cheapest to get wrong early: the band appearing, and the file loading offline.

**Files:**
- Modify: `solit2/cli.py` (add the subparser near `solit2/cli.py:672-705`, and a new `_cmd_report_virtual_test` near the other `_cmd_report_*` functions, `solit2/cli.py:293-376`)
- Create: `solit2/reports/virtual_test.py`
- Test: `tests/test_report_virtual_test.py`, `tests/test_cli_report_virtual_test.py`

**Interfaces:**
- Consumes: `html.document`, `html.table`, `html.BAND_TEXT` (Task 2); `solit2.compliance.spec.load_spec`, `solit2.compliance.spec.LoadedSpec` (existing); `solit2.engines.reduced.envelope.run` (existing).
- Produces: `virtual_test.render(loaded: LoadedSpec, results: dict[str, Result]) -> str` (grows more parameters in later tasks — Task 4 onward add `traces`, `compliance`, and CFD lookups; each later task's own Interfaces block states the new signature). The CLI's `_cmd_report_virtual_test(args) -> int` does the loading and running, matching how `_cmd_report_correlation` (`solit2/cli.py:335-344`) orchestrates two `Result`s before handing them to a pure `render()`.

- [ ] **Step 1: Write the failing tests**

Use `examples/compliance/solit2-example.spec.json` for every test in this plan — it is the one compliance spec fixture that runs cleanly today (both `"A"` and `"B"` resolve and pass `envelope.run` without error). Do **not** use `designs/og-test-spec.json`: its three referenced designs currently raise `MissingNozzleData` (a pre-existing, unrelated gap — do not fix it as part of this plan).

```python
# tests/test_report_virtual_test.py
from pathlib import Path

from solit2.compliance.spec import load_spec
from solit2.engines.reduced import envelope
from solit2.reports import virtual_test

SPEC = "examples/compliance/solit2-example.spec.json"


def _loaded_and_results():
    loaded = load_spec(SPEC)
    results = {cls: envelope.run(d) for cls, d in loaded.tests.items()}
    return loaded, results


def test_every_page_carries_the_prediction_band():
    loaded, results = _loaded_and_results()
    out = virtual_test.render(loaded, results)
    # One band per section plus one in the header; at minimum one per rendered section.
    assert out.count(virtual_test.html.BAND_TEXT) >= 2


def test_the_document_names_both_test_designs():
    loaded, results = _loaded_and_results()
    out = virtual_test.render(loaded, results)
    assert loaded.tests["A"].meta.name in out
    assert loaded.tests["B"].meta.name in out


def test_the_document_makes_no_network_reference():
    loaded, results = _loaded_and_results()
    out = virtual_test.render(loaded, results)
    # Not a substring test: once Task 6 embeds Plotly, the bundle's own JS strings
    # contain https:// text that is never fetched. external_references() skips
    # script bodies and catches every tag or CSS rule that would fetch something.
    assert virtual_test.html.external_references(out) == []
```

```python
# tests/test_cli_report_virtual_test.py
import subprocess

SPEC = "examples/compliance/solit2-example.spec.json"


def test_the_cli_writes_an_html_file(tmp_path):
    out = tmp_path / "v.html"
    done = subprocess.run(
        ["uv", "run", "solit2", "report", "virtual-test", SPEC, "--out", str(out)],
        capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    text = out.read_text()
    assert text.strip().startswith("<!DOCTYPE html>")
    assert "VIRTUAL TEST" in text


def test_cli_engine_failure_exits_with_engine_code(monkeypatch, tmp_path):
    from solit2 import cli
    out = tmp_path / "v.html"
    monkeypatch.setattr("solit2.engines.reduced.envelope.run",
                        lambda design, **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    result = cli.main(["report", "virtual-test", SPEC, "--out", str(out)])
    assert result == cli.EXIT_ENGINE
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_report_virtual_test.py tests/test_cli_report_virtual_test.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'solit2.reports.virtual_test'`, and the CLI test fails because `report virtual-test` is not a recognised subcommand (argparse error, nonzero exit).

- [ ] **Step 3: Write the minimal implementation**

```python
# solit2/reports/virtual_test.py
"""The virtual fire test report: a full-scale-test-shaped HTML document
predicting the outcome of the SOLIT2 tests a compliance spec names, entirely
from this tool's own Tier 1 output. Every section builder here is a pure
function over already-computed Design/Result/RunTrace/ComplianceReport
objects; solit2/cli.py does the loading and running.
"""
from __future__ import annotations

from solit2.compliance.spec import LoadedSpec
from solit2.reports import html
from solit2.schema.result import Result


def _introduction() -> str:
    return (
        "<p>This report predicts the outcome of the planned SOLIT² Annex 7 "
        "tests, laid out in the shape a full-scale fire test report uses, so the "
        "real test report can later be placed beside it section by section. "
        "It is not a measurement: every figure in it comes from this tool's own "
        "Tier 1 (and, once run, Tier 2 CFD) engine, never from an instrument.</p>")


def _requested_tests(loaded: LoadedSpec) -> str:
    rows = [[cls, design.meta.name, design.fire.preset,
            f"{design.fire.design_hrr_mw:.0f} MW",
            f"{design.ventilation.velocity_range_ms[0]:.2f}–"
            f"{design.ventilation.velocity_range_ms[1]:.2f} m/s",
            f"{design.zones.duration_min:.0f} min"]
            for cls, design in sorted(loaded.tests.items())]
    return html.table(["Test", "Design", "Fire class", "Design HRR",
                       "Ventilation", "Duration"], rows)


def render(loaded: LoadedSpec, results: dict[str, Result]) -> str:
    sections = [
        ("Introduction", _introduction()),
        ("Requested tests", _requested_tests(loaded)),
    ]
    return html.document(f"Virtual fire test report — {loaded.spec.name}", sections)
```

Wire the CLI. In `solit2/cli.py`, add the subparser next to `ra` (around line 705):

```python
rvt = report_sub.add_parser(
    "virtual-test", help="predicted outcome of the SOLIT2 tests a compliance spec names")
rvt.add_argument("spec")
rvt.add_argument("--out")
rvt.set_defaults(func=_cmd_report_virtual_test)
```

Add the CLI function near the other `_cmd_report_*` functions:

```python
def _cmd_report_virtual_test(args: argparse.Namespace) -> int:
    from solit2.compliance.spec import load_spec
    from solit2.reports import virtual_test
    try:
        loaded = load_spec(args.spec)
    except (ValidationError, ValueError, FileNotFoundError, KeyError) as exc:
        return _fail(str(exc), getattr(exc, "field", "spec"),
                     "correct the compliance spec and try again", EXIT_BAD_INPUT)
    try:
        results = {cls: envelope.run(d) for cls, d in loaded.tests.items()}
    except (ArithmeticError, RuntimeError, ValueError, KeyError) as exc:
        return _fail(str(exc), "engine",
                     "the spec validated but a design could not be run", EXIT_ENGINE)
    return _emit_html_report(virtual_test.render(loaded, results), args.out)
```

`_emit_report` (cli.py:293-302) is markdown-specific (prints the content to stdout and appends `"\n"`). Add a sibling for HTML that does not print the whole document to the terminal:

```python
def _emit_html_report(html_text: str, out: str | None) -> int:
    if not out:
        return _fail("an HTML report needs --out", "--out",
                     "pass --out <path.html>; an HTML document is not printed to the terminal",
                     EXIT_BAD_INPUT)
    try:
        Path(out).parent.mkdir(parents=True, exist_ok=True)
        Path(out).write_text(html_text)
    except OSError as exc:
        return _fail(str(exc), "--out", "choose a writable output path", EXIT_BAD_INPUT)
    print(f"wrote {out}")
    return EXIT_OK
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_report_virtual_test.py tests/test_cli_report_virtual_test.py -v`
Expected: PASS.

- [ ] **Step 5: Run the whole existing CLI test file to confirm the new subparser did not break argument parsing elsewhere**

Run: `uv run pytest tests/test_cli.py -v`
Expected: all PASS.

- [ ] **Step 6: Commit**

```bash
git add solit2/cli.py solit2/reports/virtual_test.py tests/test_report_virtual_test.py tests/test_cli_report_virtual_test.py
git commit -m "feat(reports): wire up solit2 report virtual-test with an introduction skeleton"
```

---

## Task 4: Facility, water-mist system, and fire load sections

**Files:**
- Modify: `solit2/reports/virtual_test.py`
- Test: `tests/test_report_virtual_test.py`

**Interfaces:**
- Consumes: `solit2.engines.reduced.geometry.section_geometry(design: Design) -> SectionGeometry` (fields: `name, road_width_m, crown_height_m, free_area_m2, shape, radius_m, deck_below_centre_m`); `Design.active_heads: int`, `Design.flow_lpm: float` (existing properties, confirmed in `solit2/engines/reduced/hydraulics.py`).
- Produces: `_facility(loaded: LoadedSpec) -> str`, `_water_mist_system(loaded: LoadedSpec) -> str`, `_fire_load(loaded: LoadedSpec) -> str`, each added to `render()`'s `sections` list in this order (spec items 3, 4, 5).

- [ ] **Step 1: Write the failing tests**

```python
def test_facility_section_states_each_designs_own_geometry():
    loaded, results = _loaded_and_results()
    out = virtual_test.render(loaded, results)
    from solit2.engines.reduced.geometry import section_geometry
    for design in loaded.tests.values():
        geom = section_geometry(design)
        assert f"{geom.road_width_m:.2f}" in out


def test_water_mist_system_states_pressure_and_active_head_count():
    loaded, results = _loaded_and_results()
    out = virtual_test.render(loaded, results)
    for design in loaded.tests.values():
        assert f"{design.nozzles.pressure_bar:.1f}" in out
        assert str(design.active_heads) in out


def test_fire_load_states_the_design_hrr_and_covered_flag():
    loaded, results = _loaded_and_results()
    out = virtual_test.render(loaded, results)
    for design in loaded.tests.values():
        assert f"{design.fire.design_hrr_mw:.0f}" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_report_virtual_test.py -v -k "facility or water_mist or fire_load"`
Expected: FAIL — the assertions find nothing, since these sections do not exist yet.

- [ ] **Step 3: Write the implementation**

Add to `solit2/reports/virtual_test.py`:

```python
from solit2.engines.reduced.geometry import section_geometry


def _facility(loaded: LoadedSpec) -> str:
    rows = [[cls, design.meta.name, design.tunnel.preset, design.tunnel.section,
            f"{section_geometry(design).road_width_m:.2f} m",
            f"{section_geometry(design).crown_height_m:.2f} m",
            f"{design.ventilation.velocity_range_ms[0]:.2f}–"
            f"{design.ventilation.velocity_range_ms[1]:.2f} m/s"]
            for cls, design in sorted(loaded.tests.items())]
    return html.table(["Test", "Design", "Tunnel preset", "Section",
                       "Road width", "Crown height", "Ventilation band"], rows)


def _water_mist_system(loaded: LoadedSpec) -> str:
    rows = []
    for cls, design in sorted(loaded.tests.items()):
        n = design.nozzles
        rows.append([cls, n.preset, f"{n.k_factor_lpm_bar05:.2f}", f"{n.pressure_bar:.1f} bar",
                    f"{n.flow_per_head_lpm:.1f} L/min", f"{design.zones.section_length_m:.0f} m",
                    str(design.active_heads),
                    f"{n.k_factor_lpm_bar05 * design.active_heads:.1f}"])
    return html.table(["Test", "Nozzle preset", "K-factor", "Pressure", "Flow per head",
                       "Zone length", "Active heads", "Total K"], rows)


def _fire_load(loaded: LoadedSpec) -> str:
    rows = [[cls, design.fire.preset, "covered" if design.fire.covered else "uncovered",
            f"{design.fire.design_hrr_mw:.0f} MW"]
            for cls, design in sorted(loaded.tests.items())]
    return html.table(["Test", "Fire preset", "Cover", "Design HRR"], rows)
```

Insert the three calls into `render()`'s `sections` list, immediately after `("Requested tests", ...)`:

```python
        ("Requested tests", _requested_tests(loaded)),
        ("Test facility", _facility(loaded)),
        ("Water mist system", _water_mist_system(loaded)),
        ("Fire load and target", _fire_load(loaded)),
```

If `design.tunnel.section` or `design.fire.covered` do not exist under those exact names, run `python3 -c "from solit2.schema.design import Design; d = Design.load('examples/designs/road-tunnel-twin-bore.json'); print(d.tunnel); print(d.fire)"` to read the real field names off a loaded design and correct the code above to match — do not guess a second time.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_report_virtual_test.py -v`
Expected: all PASS, including the tests from Task 3.

- [ ] **Step 5: Commit**

```bash
git add solit2/reports/virtual_test.py tests/test_report_virtual_test.py
git commit -m "feat(reports): facility, water mist system and fire load sections"
```

---

## Task 5: Virtual instruments and procedure sections

**Files:**
- Modify: `solit2/reports/virtual_test.py`
- Test: `tests/test_report_virtual_test.py`

**Interfaces:**
- Consumes: `solit2.engines.reduced.criteria.STATIONS` (the 15-station tuple, `solit2/engines/reduced/criteria.py:48-64`); `app.components.readings.limit(result: Result, gauge: Gauge) -> Band | None` and `app.components.readings.GAUGES` (confirmed pure, no Streamlit import); `solit2.reports.labels.with_unit(key: str, raw: object) -> str`.
- Produces: `_instruments() -> str`, `_procedure(loaded: LoadedSpec, results: dict[str, Result]) -> str`, appended to `render()`'s sections in this order (spec items 6, 7).

- [ ] **Step 1: Write the failing tests**

```python
def test_instruments_section_names_every_modelled_station():
    from solit2.engines.reduced.criteria import STATIONS
    loaded, results = _loaded_and_results()
    out = virtual_test.render(loaded, results)
    for station in STATIONS:
        assert station in out


def test_procedure_section_shows_limit_not_set_for_an_unset_criterion():
    loaded, results = _loaded_and_results()
    out = virtual_test.render(loaded, results)
    # examples/compliance/solit2-example.spec.json's designs carry an empty
    # `ahj` block (see examples/designs/solit2-test-protocol*.json), so every
    # criterion beyond target_ignited is unset.
    assert "limit not set" in out
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_report_virtual_test.py -v -k "instruments or procedure"`
Expected: FAIL.

- [ ] **Step 3: Write the implementation**

```python
from solit2.engines.reduced.criteria import STATIONS


def _instruments() -> str:
    rows = [[station, "temperature, heat flux, visibility, FED, CO, air velocity "
            "(where Annex 7 Table 5 places a sensor at this station)"]
            for station in STATIONS]
    return (
        "<p>Every station below is a modelled point, not a physical sensor: this is a "
        "prediction, and no instrument has been installed yet.</p>"
        + html.table(["Station", "What is modelled there"], rows))


def _procedure(loaded: LoadedSpec, results: dict[str, Result]) -> str:
    parts = [
        "<p>Ignition follows each design's own fire preset; detection is "
        "<code>linear_heat</code> at the threshold and spacing each design declares; "
        "activation follows detection by the design's own delay, or fires at a fixed "
        "time where the design pins it manually; the system then runs for the "
        "design's own declared duration. The performance criteria below are judged "
        "against each design's own <code>ahj</code> block.</p>"]
    for cls, design in sorted(loaded.tests.items()):
        result = results[cls]
        rows = []
        for key, criterion in sorted(result.criteria.items()):
            limit_text = ("limit not set" if criterion.status == "unset"
                         else labels.with_unit(key, criterion.limit))
            rows.append([labels.label(key), limit_text])
        parts.append(f"<h3>Test {cls}: {html.escape(design.meta.name)}</h3>")
        parts.append(html.table(["Criterion", "Limit"], rows))
    return "\n".join(parts)
```

Add the `labels` import at the top of `solit2/reports/virtual_test.py` (alongside the existing `html` import):

```python
from solit2.reports import html, labels
```

Insert the two new calls into `render()`'s `sections` list, immediately after `("Fire load and target", ...)`:

```python
        ("Fire load and target", _fire_load(loaded)),
        ("Virtual instruments", _instruments()),
        ("Procedure", _procedure(loaded, results)),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_report_virtual_test.py -v`
Expected: all PASS, including every test from Tasks 3 and 4.

- [ ] **Step 5: Commit**

```bash
git add solit2/reports/virtual_test.py tests/test_report_virtual_test.py
git commit -m "feat(reports): virtual instruments and procedure sections"
```

---

---

## Task 6: Results summary, HRR comparison and ceiling temperature comparison

Opens section 8, "Results": the table across the tests, then the two comparison charts. Task 7 adds the per-test pages to the same section.

**Files:**
- Modify: `solit2/reports/virtual_test.py`
- Test: `tests/test_report_virtual_test.py`

**Interfaces:**
- Consumes: `Result.timeseries` keys `t_s`, `hrr_mw`, `hrr_free_burn_mw` (Task 1), `ceiling_temp_c`; `Result.peaks` keys `hrr_mw`, `hrr_free_burn_mw`, `ceiling_temp_c`; `Result.worst_case` (`{"section": str, "velocity_ms": float}`); `Result.criteria[key].status` (`"pass" | "fail" | "unset"`); `html.figure_html`, `html.table`, `html.BUNDLE_MARK` (Task 2); `labels.with_unit`, `labels.label`, `labels.unit`, `labels.heading` (existing).
- Produces:
  - `GROWTH_CURVES: tuple[tuple[str, float, str], ...]` — `(name, alpha_kw_per_s2, colour)` for slow, medium, fast, ultra-fast.
  - `class _Figures` with `embed(fig: go.Figure) -> str` — the first call embeds the Plotly bundle, every later call does not. Every later task that embeds a chart takes a `figs: _Figures` argument and calls `figs.embed(fig)`; `render()` creates exactly one `_Figures()`.
  - `_criteria_counts(result: Result) -> tuple[int, int, int]` — `(met, not_met, limit_not_set)`.
  - `_hrr_figure(results: dict[str, Result]) -> go.Figure`, `_ceiling_figure(results: dict[str, Result]) -> go.Figure`.
  - `_results_overview(loaded: LoadedSpec, results: dict[str, Result], figs: _Figures) -> str`. Task 7 keeps this function and calls it from a new `_results`.

The t² reference curves are the one thing in the report that is not the engine's output. They are conventional growth shapes, labelled as such and cited to NFPA 72 and the SFPE Handbook in the text of the report, as the design spec requires.

- [ ] **Step 1: Write the failing tests**

Add to `tests/test_report_virtual_test.py` (add `from solit2.reports import labels` beside the existing imports):

```python
def test_the_results_summary_states_each_tests_engine_peaks():
    loaded, results = _loaded_and_results()
    out = virtual_test.render(loaded, results)
    assert "<h2>8. Results</h2>" in out
    for result in results.values():
        assert labels.with_unit("hrr_mw", result.peaks["hrr_mw"]) in out
        assert labels.with_unit("hrr_free_burn_mw", result.peaks["hrr_free_burn_mw"]) in out
        assert labels.with_unit("ceiling_temp_c", result.peaks["ceiling_temp_c"]) in out


def test_criteria_counts_split_met_not_met_and_not_set():
    from solit2.schema.result import Criterion
    result = _loaded_and_results()[1]["A"].model_copy(update={"criteria": {
        "max_air_temp_c": Criterion.build(300.0, 250.0, "<=", True),      # fail
        "max_heat_flux_kwm2": Criterion.build(2.0, 5.0, "<=", True),       # pass
        "min_visibility_m": Criterion.build(10.0, None, ">=", True),       # unset
        "target_ignited": Criterion.build(False, None, "is_false", True),  # pass
    }})
    assert virtual_test._criteria_counts(result) == (2, 1, 1)


def test_the_hrr_chart_plots_the_engines_own_series_and_four_growth_curves():
    _, results = _loaded_and_results()
    fig = virtual_test._hrr_figure(results)
    by_name = {trace.name: trace for trace in fig.data}
    for cls, result in results.items():
        assert tuple(by_name[f"Test {cls} — suppressed"].y) == tuple(result.timeseries["hrr_mw"])
        assert tuple(by_name[f"Test {cls} — free burn"].y) == tuple(
            result.timeseries["hrr_free_burn_mw"])
    growth = [name for name in by_name if name.startswith("t² ")]
    assert len(growth) == 4
    for name in ("slow", "medium", "fast", "ultra-fast"):
        assert any(g.startswith(f"t² {name} ") for g in growth)


def test_the_growth_curves_are_cited_as_reference_shapes_not_engine_output():
    loaded, results = _loaded_and_results()
    out = virtual_test.render(loaded, results)
    assert "NFPA 72" in out and "SFPE" in out
    assert "not engine output" in out


def test_the_ceiling_chart_has_one_engine_line_per_test():
    _, results = _loaded_and_results()
    fig = virtual_test._ceiling_figure(results)
    assert len(fig.data) == len(results)
    for trace, (cls, result) in zip(fig.data, sorted(results.items())):
        assert trace.name == f"Test {cls}"
        assert tuple(trace.y) == tuple(result.timeseries["ceiling_temp_c"])


def test_the_plotly_bundle_is_embedded_exactly_once_however_many_charts_there_are():
    loaded, results = _loaded_and_results()
    out = virtual_test.render(loaded, results)
    assert out.count(virtual_test.html.BUNDLE_MARK) == 1
    assert out.count("Plotly.newPlot") >= 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_report_virtual_test.py -v -k "summary or criteria_counts or hrr_chart or growth or ceiling_chart or bundle"`
Expected: FAIL — `AttributeError: module 'solit2.reports.virtual_test' has no attribute '_criteria_counts'` (and `_hrr_figure`), and the summary/`<h2>8. Results</h2>` assertions fail.

- [ ] **Step 3: Write the implementation**

Add to `solit2/reports/virtual_test.py` (merge the two new imports into the existing import block):

```python
import plotly.graph_objects as go

# t² growth, Q = alpha * t² (Q in kW, t in s). Slow, medium, fast and ultra-fast
# growth as tabulated in NFPA 72 Annex B and the SFPE Handbook of Fire Protection
# Engineering. Reference shapes only -- see _results_overview's note.
GROWTH_CURVES = (("slow", 0.00293, "#c8c8c8"), ("medium", 0.01172, "#a0a0a0"),
                 ("fast", 0.0469, "#787878"), ("ultra-fast", 0.1876, "#505050"))
GROWTH_CURVE_POINTS = 200
HRR_AXIS_HEADROOM = 1.15   # the HRR axis stops 15 % above the highest engine curve
CHART_HEIGHT_PX = 420
CHART_MARGIN = {"l": 10, "r": 10, "t": 30, "b": 10}


class _Figures:
    """Hands the Plotly bundle to the first chart embedded and to no other.

    ponytail: one mutable flag. The bundle must exist exactly once per document
    and document order is build order; if sections are ever built out of order,
    move the bundle into html.document's <head> instead.
    """

    def __init__(self) -> None:
        self._bundle_written = False

    def embed(self, fig: go.Figure) -> str:
        first = not self._bundle_written
        self._bundle_written = True
        return html.figure_html(fig, first=first)


def _criteria_counts(result: Result) -> tuple[int, int, int]:
    statuses = [c.status for c in result.criteria.values()]
    return statuses.count("pass"), statuses.count("fail"), statuses.count("unset")


def _hrr_figure(results: dict[str, Result]) -> go.Figure:
    fig = go.Figure()
    top = 0.0
    for cls, result in sorted(results.items()):
        ts = result.timeseries
        fig.add_trace(go.Scatter(x=ts["t_s"], y=ts["hrr_mw"], mode="lines",
                                 name=f"Test {cls} — suppressed"))
        fig.add_trace(go.Scatter(x=ts["t_s"], y=ts["hrr_free_burn_mw"], mode="lines",
                                 line={"dash": "dash"}, name=f"Test {cls} — free burn"))
        top = max(top, max(ts["hrr_free_burn_mw"]))
    t_end = max(result.timeseries["t_s"][-1] for result in results.values())
    grid = [t_end * i / GROWTH_CURVE_POINTS for i in range(GROWTH_CURVE_POINTS + 1)]
    for name, alpha, colour in GROWTH_CURVES:
        fig.add_trace(go.Scatter(x=grid, y=[alpha * t * t / 1000.0 for t in grid],
                                 mode="lines", line={"dash": "dot", "color": colour},
                                 name=f"t² {name} (α = {alpha} kW/s²)"))
    fig.update_layout(xaxis_title="test clock (s)", yaxis_title=labels.heading("hrr_mw"),
                      yaxis_range=[0, (top or 1.0) * HRR_AXIS_HEADROOM],
                      height=CHART_HEIGHT_PX, margin=CHART_MARGIN)
    return fig


def _ceiling_figure(results: dict[str, Result]) -> go.Figure:
    fig = go.Figure()
    for cls, result in sorted(results.items()):
        fig.add_trace(go.Scatter(x=result.timeseries["t_s"],
                                 y=result.timeseries["ceiling_temp_c"], mode="lines",
                                 name=f"Test {cls}"))
    fig.update_layout(xaxis_title="test clock (s)",
                      yaxis_title=labels.heading("ceiling_temp_c"),
                      height=CHART_HEIGHT_PX, margin=CHART_MARGIN)
    return fig


def _results_overview(loaded: LoadedSpec, results: dict[str, Result],
                      figs: _Figures) -> str:
    rows = []
    for cls, design in sorted(loaded.tests.items()):
        result = results[cls]
        met, not_met, unset = _criteria_counts(result)
        rows.append([cls, design.meta.name,
                     f"{result.worst_case['section']} at {result.worst_case['velocity_ms']:.2f} m/s",
                     labels.with_unit("hrr_mw", result.peaks["hrr_mw"]),
                     labels.with_unit("hrr_free_burn_mw", result.peaks["hrr_free_burn_mw"]),
                     labels.with_unit("ceiling_temp_c", result.peaks["ceiling_temp_c"]),
                     f"{met} met · {not_met} not met · {unset} limit not set"])
    curves = ", ".join(f"{name} α = {alpha} kW/s²" for name, alpha, _ in GROWTH_CURVES)
    return "\n".join([
        html.table(["Test", "Design", "Worst case", "Peak HRR (suppressed)",
                    "Peak HRR (free burn)", "Peak ceiling temperature", "Criteria"], rows),
        "<h3>Heat release rate</h3>",
        "<p>Solid lines are the engine's suppressed heat release rate; dashed lines are "
        "the same fire burning freely, also the engine's own output. The dotted grey "
        f"lines are conventional t² growth curves, Q = α·t² ({curves}), from NFPA 72 "
        "Annex B and the SFPE Handbook of Fire Protection Engineering. They are "
        "reference shapes, not engine output.</p>",
        figs.embed(_hrr_figure(results)),
        "<h3>Ceiling temperature</h3>",
        figs.embed(_ceiling_figure(results)),
    ])
```

In `render()` create the figure helper and add the Results entry after `("Procedure", ...)`:

```python
def render(loaded: LoadedSpec, results: dict[str, Result]) -> str:
    figs = _Figures()
    sections = [
        ("Introduction", _introduction()),
        ("Requested tests", _requested_tests(loaded)),
        ("Test facility", _facility(loaded)),
        ("Water mist system", _water_mist_system(loaded)),
        ("Fire load and target", _fire_load(loaded)),
        ("Virtual instruments", _instruments()),
        ("Procedure", _procedure(loaded, results)),
        ("Results", _results_overview(loaded, results, figs)),
    ]
    return html.document(f"Virtual fire test report — {loaded.spec.name}", sections)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_report_virtual_test.py tests/test_report_html.py -v`
Expected: all PASS, including Task 3's `test_the_document_makes_no_network_reference` (which now sees the embedded Plotly bundle, and passes only because it uses `external_references` rather than a substring test).

- [ ] **Step 5: Commit**

```bash
git add solit2/reports/virtual_test.py tests/test_report_virtual_test.py
git commit -m "feat(reports): results summary, HRR and ceiling temperature comparison"
```

---

## Task 7: Per-test results pages

For each test: an overview written from its numbers, the configuration tables, a timeline, the criteria checklist, six charts, and the 3D tunnel at peak heat release. This task changes `render()` to take the Tier 1 traces, so it also migrates every earlier test to one shared helper that later tasks extend.

**Files:**
- Modify: `solit2/reports/virtual_test.py`, `solit2/cli.py` (`_cmd_report_virtual_test`)
- Test: `tests/test_report_virtual_test.py`, `tests/test_cli_report_virtual_test.py`

**Interfaces:**
- Consumes: `solit2.engines.reduced.sim.run_once(design, section, velocity_ms) -> RunTrace` (the CLI re-runs each test's worst case, `Result.worst_case["section"]` and `["velocity_ms"]`, to get the per-second steps); `RunTrace.steps: tuple[StepRecord, ...]` (`StepRecord.hrr_mw`, `.t_s`), `RunTrace.events`; `app.components.charts.timeseries_chart(timeseries, keys) -> go.Figure`; `app.components.tunnel3d.static_traces(design, geom, window_m)`, `.dynamic_traces(design, geom, step, window_m, hrr_peak_mw=, cmax_c=)`, `.scene_layout(geom, window_m)`; `app.components.twin_canvas.core_window_m(design)`, `.temp_max_c(trace)`, `.mmss(t_s)`; `Result.events` keys `t_detect_s`, `t_activate_s`, `t_full_pressure_s`, `t_peak_hrr_s`, `backlayering` (`{"occurred", "max_length_m", "cleared_at_s"}`); `_Figures`, `_criteria_counts` (Task 6).
- Produces:
  - `render(loaded, results, *, traces: dict[str, RunTrace]) -> str` — `traces` is keyed like `results` and becomes a required keyword. Tasks 8 and 9 add more required keywords.
  - `CHART_SPECS: tuple[tuple[str, tuple[str, ...]], ...]` — the six per-test charts, `(title, timeseries keys)`.
  - `_timeline_rows(events: dict, t_end_s: float) -> list[list[str]]`, `_criteria_checklist(criteria: dict[str, Criterion]) -> str`, `_tunnel_at_peak(design, trace) -> go.Figure`, `_test_results(cls, design, result, trace, figs) -> str`, `_results(loaded, results, traces, figs) -> str` (replaces Task 6's direct use of `_results_overview` in `render()`).
  - Row helpers `FACILITY_HEADERS`, `_facility_row(cls, design)`, `WATER_MIST_HEADERS`, `_water_mist_row(cls, design)`, extracted from Task 4 so a single test's configuration reuses them.
  - Test helpers `_inputs()` (cached) and `_render(**overrides)` in `tests/test_report_virtual_test.py`.

Layering note: `solit2/reports/virtual_test.py` imports `app.components.*` because the chart and 3D builders already exist there, are pure (no Streamlit), and are the same figures the live simulator shows, which the design spec asks to reuse. `app` is importable in this repo's development install (`packages = ["solit2"]` in `pyproject.toml` builds only `solit2`, so a non-editable wheel would not have `app`). Mark the import with a `ponytail:` comment; promoting `charts.py`/`tunnel3d.py` into `solit2/` is the upgrade path if the CLI is ever shipped without the app.

- [ ] **Step 1: Write the failing tests, and migrate the earlier ones**

At the top of `tests/test_report_virtual_test.py`, replace `_loaded_and_results` and add the shared helpers (add `import functools` and `from solit2.engines.reduced import sim`):

```python
@functools.lru_cache(maxsize=1)
def _loaded_and_results():
    loaded = load_spec(SPEC)
    results = {cls: envelope.run(d) for cls, d in loaded.tests.items()}
    return loaded, results


@functools.lru_cache(maxsize=1)
def _inputs():
    loaded, results = _loaded_and_results()
    traces = {cls: sim.run_once(loaded.tests[cls], r.worst_case["section"],
                                r.worst_case["velocity_ms"])
              for cls, r in results.items()}
    return loaded, results, traces


def _render(**overrides):
    """(loaded, results, html). Later tasks add their required keywords here."""
    loaded, results, traces = _inputs()
    kwargs = {"traces": traces, **overrides}
    return loaded, results, virtual_test.render(loaded, results, **kwargs)
```

Migrate every test from Tasks 3-6 that renders the whole document. Each has the same two adjacent lines; run this once:

```bash
python3 - <<'PY'
import pathlib
p = pathlib.Path("tests/test_report_virtual_test.py")
t = p.read_text()
pair = "    loaded, results = _loaded_and_results()\n    out = virtual_test.render(loaded, results)\n"
print(t.count(pair), "occurrences")
p.write_text(t.replace(pair, "    loaded, results, out = _render()\n"))
PY
```

Expected: prints a count of at least 9. Tests that only need `results` (`_hrr_figure`, `_ceiling_figure`, `_criteria_counts`) keep calling `_loaded_and_results()` and are untouched. `tests/test_cli_report_virtual_test.py` needs no change.

Then add the new tests:

```python
def test_each_test_gets_a_results_page_with_its_timeline_and_all_six_charts():
    loaded, results, out = _render()
    for cls in loaded.tests:
        assert f"Test {cls}:" in out
    for label in ("Ignition", "Detection", "Activation", "Full pressure",
                  "Peak heat release", "Backlayering", "End of test"):
        assert out.count(f"<td>{label}</td>") == len(loaded.tests)
    for title, _keys in virtual_test.CHART_SPECS:
        assert out.count(title) >= len(loaded.tests)
    assert len(virtual_test.CHART_SPECS) == 6


def test_the_3d_tunnel_is_drawn_at_the_traces_peak_heat_release():
    loaded, results, traces = _inputs()
    fig = virtual_test._tunnel_at_peak(loaded.tests["A"], traces["A"])
    peak = max(traces["A"].steps, key=lambda s: s.hrr_mw)
    assert f"t = {peak.t_s:.0f} s" in fig.layout.title.text
    assert len(fig.data) >= 10   # 4 static + 6 dynamic traces


def test_the_trace_is_the_worst_case_the_result_reports():
    _, results, traces = _inputs()
    for cls, result in results.items():
        assert max(s.hrr_mw for s in traces[cls].steps) == result.peaks["hrr_mw"]


def test_the_timeline_marks_an_unreached_event_as_not_reached():
    events = {"t_detect_s": 40.0, "t_activate_s": None, "t_full_pressure_s": None,
              "t_peak_hrr_s": 120.0,
              "backlayering": {"occurred": False, "max_length_m": 0.0, "cleared_at_s": None}}
    rows = dict((r[0], r[1]) for r in virtual_test._timeline_rows(events, 600.0))
    assert rows["Detection"].startswith("40 s")
    assert rows["Activation"] == "not reached"
    assert rows["Backlayering"] == "did not occur"
    assert rows["End of test"].startswith("600 s")


def test_the_checklist_marks_met_not_met_and_limit_not_set():
    from solit2.schema.result import Criterion
    criteria = {
        "max_air_temp_c": Criterion.build(300.0, 250.0, "<=", True),      # not met
        "max_heat_flux_kwm2": Criterion.build(2.0, 5.0, "<=", True),       # met
        "min_visibility_m": Criterion.build(10.0, None, ">=", True),       # unset
        "target_ignited": Criterion.build(False, None, "is_false", True),  # met
    }
    out = virtual_test._criteria_checklist(criteria)
    assert out.count("✓ met") == 2
    assert out.count("✗ not met") == 1
    assert out.count("limit not set") == 1
    # The predicted value is still shown beside a limit that was never set.
    assert labels.with_unit("min_visibility_m", 10.0) in out


def test_a_design_name_with_markup_is_escaped_in_the_results_page():
    loaded, results, traces = _inputs()
    design = loaded.tests["A"]
    hostile = design.model_copy(
        update={"meta": design.meta.model_copy(update={"name": "<script>x</script>"})})
    out = virtual_test._test_results("A", hostile, results["A"], traces["A"],
                                     virtual_test._Figures())
    assert "<script>x</script>" not in out
    assert "&lt;script&gt;x&lt;/script&gt;" in out
```

Add to `tests/test_cli_report_virtual_test.py`:

```python
def test_the_written_file_has_a_results_page_per_test(tmp_path):
    out = tmp_path / "v.html"
    done = subprocess.run(
        ["uv", "run", "solit2", "report", "virtual-test", SPEC, "--out", str(out)],
        capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    assert out.read_text().count("Predicted state at peak HRR") == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_report_virtual_test.py tests/test_cli_report_virtual_test.py -v`
Expected: FAIL — `TypeError: render() got an unexpected keyword argument 'traces'` for everything that goes through `_render()`, plus `AttributeError` for `_tunnel_at_peak`, `_timeline_rows`, `_criteria_checklist`, `_test_results`, `CHART_SPECS`.

- [ ] **Step 3: Extract the Task 4 row helpers**

Replace `_facility` and `_water_mist_system` in `solit2/reports/virtual_test.py` so one design's configuration can be rendered on its own. Keep any field-name correction you made in Task 4 Step 3; only the structure changes:

```python
FACILITY_HEADERS = ["Test", "Design", "Tunnel preset", "Section",
                    "Road width", "Crown height", "Ventilation band"]
WATER_MIST_HEADERS = ["Test", "Nozzle preset", "K-factor", "Pressure", "Flow per head",
                      "Zone length", "Active heads", "Total K"]


def _facility_row(cls: str, design: Design) -> list[str]:
    geom = section_geometry(design)
    return [cls, design.meta.name, design.tunnel.preset, design.tunnel.section,
            f"{geom.road_width_m:.2f} m", f"{geom.crown_height_m:.2f} m",
            f"{design.ventilation.velocity_range_ms[0]:.2f}–"
            f"{design.ventilation.velocity_range_ms[1]:.2f} m/s"]


def _water_mist_row(cls: str, design: Design) -> list[str]:
    n = design.nozzles
    return [cls, n.preset, f"{n.k_factor_lpm_bar05:.2f}", f"{n.pressure_bar:.1f} bar",
            f"{n.flow_per_head_lpm:.1f} L/min", f"{design.zones.section_length_m:.0f} m",
            str(design.active_heads), f"{n.k_factor_lpm_bar05 * design.active_heads:.1f}"]


def _facility(loaded: LoadedSpec) -> str:
    return html.table(FACILITY_HEADERS,
                      [_facility_row(cls, d) for cls, d in sorted(loaded.tests.items())])


def _water_mist_system(loaded: LoadedSpec) -> str:
    return html.table(WATER_MIST_HEADERS,
                      [_water_mist_row(cls, d) for cls, d in sorted(loaded.tests.items())])
```

Add `from solit2.schema.design import Design` to the imports. Run `uv run pytest tests/test_report_virtual_test.py -v -k "facility or water_mist"` — these two Task 4 tests still PASS after the refactor (they are the safety net for it).

- [ ] **Step 4: Write the per-test page**

Add to `solit2/reports/virtual_test.py`:

```python
# ponytail: the chart and 3D builders live in app/ and are pure Plotly. Importing
# them keeps the report identical to the live simulator; promote them into solit2/
# if the CLI is ever shipped without the app package.
from app.components import charts, tunnel3d, twin_canvas
from solit2.engines.reduced.state import RunTrace
from solit2.schema.result import Criterion

# The six per-test charts. Every key is a real key of Result.timeseries. The engine
# samples four gas-temperature stations (U45, U15, D15, D100) plus the ceiling, so
# "every station" means every station the timeseries carries.
CHART_SPECS = (
    ("Heat release rate", ("hrr_mw", "hrr_free_burn_mw")),
    ("Air velocity", ("velocity_ms",)),
    ("Heat flux at U15", ("hf_u15_kwm2",)),
    ("Gas temperature at U15", ("u15_temp_c",)),
    ("Gas temperature at every sampled station",
     ("ceiling_temp_c", "u45_temp_c", "u15_temp_c", "d15_temp_c", "d100_temp_c")),
    ("Water flow", ("water_lpm",)),
)
TUNNEL_HEIGHT_PX = 520
NOT_REACHED = "not reached"


def _clock(t_s: float) -> str:
    return f"{t_s:.0f} s ({twin_canvas.mmss(t_s)})"


def _timeline_rows(events: dict, t_end_s: float) -> list[list[str]]:
    def at(key: str) -> str:
        t = events.get(key)
        return NOT_REACHED if t is None else _clock(float(t))

    back = events.get("backlayering") or {}
    if not back.get("occurred"):
        backlayering = "did not occur"
    elif back.get("cleared_at_s") is None:
        backlayering = f"reached {back['max_length_m']:.0f} m, not cleared"
    else:
        backlayering = (f"reached {back['max_length_m']:.0f} m, cleared at "
                        f"{_clock(float(back['cleared_at_s']))}")
    return [["Ignition", _clock(0.0)],
            ["Detection", at("t_detect_s")],
            ["Activation", at("t_activate_s")],
            ["Full pressure", at("t_full_pressure_s")],
            ["Peak heat release", at("t_peak_hrr_s")],
            ["Backlayering", backlayering],
            ["End of test", _clock(t_end_s)]]


def _criterion_row(key: str, criterion: Criterion) -> list[str]:
    predicted = labels.with_unit(key, criterion.value)
    if criterion.status == "unset":
        return [labels.label(key), predicted, "—", "limit not set"]
    limit = criterion.limit
    limit_text = (" – ".join(labels.with_unit(key, v) for v in limit)
                  if isinstance(limit, tuple) else labels.with_unit(key, limit))
    mark = "✓ met" if criterion.status == "pass" else "✗ not met"
    return [labels.label(key), predicted, limit_text if limit is not None else "—", mark]


def _criteria_checklist(criteria: dict[str, Criterion]) -> str:
    return html.table(["Criterion", "Predicted", "Limit (from the design's own AHJ block)",
                       "Result"],
                      [_criterion_row(k, c) for k, c in sorted(criteria.items())])


def _overview(cls: str, design: Design, result: Result) -> str:
    met, not_met, unset = _criteria_counts(result)
    p = result.peaks
    return (
        f"Test {cls} ({design.meta.name}): the engine's worst case is "
        f"{result.worst_case['section']} at {result.worst_case['velocity_ms']:.2f} m/s "
        f"ventilation. Suppressed heat release peaks at "
        f"{labels.with_unit('hrr_mw', p['hrr_mw'])} against a free-burn peak of "
        f"{labels.with_unit('hrr_free_burn_mw', p['hrr_free_burn_mw'])}, and the ceiling "
        f"reaches {labels.with_unit('ceiling_temp_c', p['ceiling_temp_c'])}. "
        f"{met} criteria are met, {not_met} are not met and {unset} have no limit set.")


def _tunnel_at_peak(design: Design, trace: RunTrace) -> go.Figure:
    geom = section_geometry(design)
    window = twin_canvas.core_window_m(design)
    step = max(trace.steps, key=lambda s: s.hrr_mw)
    fig = go.Figure()
    for static in tunnel3d.static_traces(design, geom, window):
        fig.add_trace(static)
    for dynamic in tunnel3d.dynamic_traces(design, geom, step, window,
                                           hrr_peak_mw=step.hrr_mw,
                                           cmax_c=twin_canvas.temp_max_c(trace)):
        fig.add_trace(dynamic)
    fig.update_layout(
        scene=tunnel3d.scene_layout(geom, window), height=TUNNEL_HEIGHT_PX,
        margin=CHART_MARGIN,
        title=f"Predicted state at peak HRR, t = {step.t_s:.0f} s")
    return fig


def _test_results(cls: str, design: Design, result: Result, trace: RunTrace,
                  figs: _Figures) -> str:
    parts = [f"<h3>Test {cls}: {html.escape(design.meta.name)}</h3>",
             f"<p>{html.escape(_overview(cls, design, result))}</p>",
             "<h4>Configuration</h4>",
             html.table(FACILITY_HEADERS, [_facility_row(cls, design)]),
             html.table(WATER_MIST_HEADERS, [_water_mist_row(cls, design)]),
             "<h4>Timeline</h4>",
             html.table(["Event", "Test clock"],
                        _timeline_rows(result.events, result.timeseries["t_s"][-1])),
             "<h4>Criteria</h4>",
             _criteria_checklist(result.criteria),
             "<h4>Results</h4>"]
    for title, keys in CHART_SPECS:
        fig = charts.timeseries_chart(result.timeseries, list(keys))
        fig.update_layout(title=title)
        fig.update_yaxes(title_text=labels.unit(keys[0]))
        parts.append(figs.embed(fig))
    parts += ["<h4>Tunnel at peak heat release</h4>",
              figs.embed(_tunnel_at_peak(design, trace))]
    return "\n".join(parts)


def _results(loaded: LoadedSpec, results: dict[str, Result],
             traces: dict[str, RunTrace], figs: _Figures) -> str:
    return "\n".join(
        [_results_overview(loaded, results, figs)]
        + [_test_results(cls, design, results[cls], traces[cls], figs)
           for cls, design in sorted(loaded.tests.items())])
```

Change `render()`'s signature and its Results entry:

```python
def render(loaded: LoadedSpec, results: dict[str, Result], *,
           traces: dict[str, RunTrace]) -> str:
    figs = _Figures()
    sections = [
        # ... unchanged entries through ("Procedure", ...)
        ("Results", _results(loaded, results, traces, figs)),
    ]
```

- [ ] **Step 5: Wire the traces through the CLI**

In `solit2/cli.py`, `_cmd_report_virtual_test`, run each test's worst case for the per-second trace and pass it in:

```python
    try:
        from solit2.engines.reduced import sim
        results = {cls: envelope.run(d) for cls, d in loaded.tests.items()}
        traces = {cls: sim.run_once(d, results[cls].worst_case["section"],
                                    results[cls].worst_case["velocity_ms"])
                  for cls, d in loaded.tests.items()}
    except (ArithmeticError, RuntimeError, ValueError, KeyError) as exc:
        return _fail(str(exc), "engine",
                     "the spec validated but a design could not be run", EXIT_ENGINE)
    return _emit_html_report(virtual_test.render(loaded, results, traces=traces), args.out)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_report_virtual_test.py tests/test_cli_report_virtual_test.py tests/test_report_html.py -v`
Expected: all PASS. If `test_the_3d_tunnel_is_drawn_at_the_traces_peak_heat_release` fails on `len(fig.data) >= 10`, count the traces `static_traces` and `dynamic_traces` really return (`tunnel3d.py:91-107` returns 4 static, `:215-227` returns 6 dynamic) and correct the number; do not loosen it to `>= 1`.

- [ ] **Step 7: Commit**

```bash
git add solit2/reports/virtual_test.py solit2/cli.py tests/test_report_virtual_test.py tests/test_cli_report_virtual_test.py
git commit -m "feat(reports): per-test results pages with six charts and the 3D tunnel at peak HRR"
```

---

## Task 8: CFD comparison

Looks up each test design's FDS run (CHID = the design's SHA, in the `runs/` directory) and lays it beside the Tier 1 prediction, or says why there is nothing to lay beside it.

**Files:**
- Create: `solit2/reports/cfd_runs.py`
- Modify: `solit2/reports/virtual_test.py`, `solit2/cli.py`
- Test: `tests/test_cfd_runs.py`, `tests/test_report_virtual_test.py`

**Interfaces:**
- Consumes: `solit2.engines.fds.deck.chid(design, suppression=True) -> str`; `solit2.engines.fds.runner.status(run_dir) -> dict` (`{"state", "progress", "detail"}`; states `pending`, `running`, `pausing`, `paused`, `stopped`, `failed`, `done`), `runner.RUNNING_STATES`; `solit2.engines.fds.reader.read(run_dir, design, *, free_burn_dir=None) -> Result`, which raises `ValueError` for a run whose detectors never tripped. An FDS `Result.timeseries` carries only `t_s`, `hrr_mw`, `hrr_free_mw`, `ceiling_temp_c`, so those are the only series that can be overlaid. `_Figures`, `CHART_MARGIN`, `CHART_HEIGHT_PX` (Task 6).
- Produces:
  - `cfd_runs.CfdRun` — frozen dataclass `(state: str, detail: str, result: Result | None = None)`; `cfd_runs.NOT_RUN = CfdRun("not_run", "CFD not yet run")`; `cfd_runs.lookup(design: Design, runs_dir: Path | str) -> CfdRun`.
  - `render(loaded, results, *, traces, cfd: dict[str, CfdRun]) -> str` — `cfd` keyed like `results`.
  - `CFD_SERIES`, `_cfd_status_line(run: CfdRun) -> str`, `_cfd_figures(cls, tier1: Result, cfd: Result) -> list[go.Figure]`, `_cfd_peaks_table(tier1: Result, cfd: Result) -> str`, `_cfd_comparison(loaded, results, cfd, figs) -> str`.
  - CLI option `--runs-dir` (default `runs`, the directory the CFD step writes to).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_cfd_runs.py
from pathlib import Path

import pytest

from solit2.compliance.spec import load_spec
from solit2.engines.fds import deck, reader, runner
from solit2.reports import cfd_runs

SPEC = "examples/compliance/solit2-example.spec.json"


@pytest.fixture(scope="module")
def design():
    return load_spec(SPEC).tests["A"]


def _run_dir(tmp_path: Path, design, t_end: float = 600.0) -> Path:
    run_dir = tmp_path / deck.chid(design)
    run_dir.mkdir()
    (run_dir / "deck.fds").write_text(f"&TIME T_END={t_end} /\n")
    return run_dir


def test_a_design_with_no_run_directory_is_not_run(tmp_path, design):
    assert cfd_runs.lookup(design, tmp_path) == cfd_runs.NOT_RUN


def test_a_running_run_reports_simulated_time_against_t_end(tmp_path, design, monkeypatch):
    _run_dir(tmp_path, design)
    monkeypatch.setattr(runner, "status",
                        lambda d: {"state": "running", "progress": 0.5, "detail": ""})
    got = cfd_runs.lookup(design, tmp_path)
    assert got.state == "running"
    assert got.detail == "running, 300 of 600 s"
    assert got.result is None


def test_a_failed_run_carries_the_runners_own_reason(tmp_path, design, monkeypatch):
    _run_dir(tmp_path, design)
    monkeypatch.setattr(runner, "status", lambda d: {
        "state": "failed", "progress": 0.2, "detail": "FDS reported an error in run.out"})
    got = cfd_runs.lookup(design, tmp_path)
    assert (got.state, got.detail) == ("failed", "FDS reported an error in run.out")
    assert got.result is None


def test_a_finished_run_is_read_with_the_fds_reader(tmp_path, design, monkeypatch):
    run_dir = _run_dir(tmp_path, design)
    sentinel = object()
    seen = {}

    def fake_read(path, d, *, free_burn_dir=None):
        seen["args"] = (path, free_burn_dir)
        return sentinel

    monkeypatch.setattr(runner, "status",
                        lambda d: {"state": "done", "progress": 1.0, "detail": ""})
    monkeypatch.setattr(reader, "read", fake_read)
    got = cfd_runs.lookup(design, tmp_path)
    assert got.state == "done" and got.result is sentinel
    assert seen["args"] == (run_dir, None)   # no free-burn run exists, so none is passed


def test_a_finished_run_the_reader_refuses_is_reported_not_raised(tmp_path, design, monkeypatch):
    _run_dir(tmp_path, design)
    monkeypatch.setattr(runner, "status",
                        lambda d: {"state": "done", "progress": 1.0, "detail": ""})

    def refuse(path, d, *, free_burn_dir=None):
        raise ValueError("the FDS run's heat detectors never tripped")

    monkeypatch.setattr(reader, "read", refuse)
    got = cfd_runs.lookup(design, tmp_path)
    assert got.state == "unreadable"
    assert "never tripped" in got.detail
```

Add to `tests/test_report_virtual_test.py`; extend `_render` so every full-document render supplies `cfd` (add `from solit2.reports import cfd_runs`):

```python
def _render(**overrides):
    """(loaded, results, html). Later tasks add their required keywords here."""
    loaded, results, traces = _inputs()
    kwargs = {"traces": traces, "cfd": {cls: cfd_runs.NOT_RUN for cls in loaded.tests},
              **overrides}
    return loaded, results, virtual_test.render(loaded, results, **kwargs)


def _finished_run(result, scale=0.8):
    """A stand-in for a finished FDS run: an FDS Result carries these four series."""
    ts = result.timeseries
    return cfd_runs.CfdRun("done", "", result.model_copy(update={
        "timeseries": {"t_s": ts["t_s"],
                       "hrr_mw": [v * scale for v in ts["hrr_mw"]],
                       "hrr_free_mw": [v * scale for v in ts["hrr_free_burn_mw"]],
                       "ceiling_temp_c": [v * scale for v in ts["ceiling_temp_c"]]},
        "peaks": {**result.peaks, "hrr_mw": result.peaks["hrr_mw"] * scale,
                  "ceiling_temp_c": result.peaks["ceiling_temp_c"] * scale},
        "warnings": ["cfd: window ends before the HRR turnover"]}))


def test_without_a_run_the_cfd_section_says_so_for_every_test():
    loaded, _, out = _render()
    assert "<h2>9. CFD comparison</h2>" in out
    assert out.count("CFD not yet run") == len(loaded.tests)


def test_a_running_run_is_reported_with_its_progress():
    running = cfd_runs.CfdRun("running", "running, 300 of 600 s")
    _, _, out = _render(cfd={"A": running, "B": cfd_runs.NOT_RUN})
    assert "running, 300 of 600 s" in out
    assert out.count("CFD not yet run") == 1


def test_a_finished_run_is_overlaid_on_that_tests_charts():
    _, results, _ = _inputs()
    run = _finished_run(results["A"])
    figures = virtual_test._cfd_figures("A", results["A"], run.result)
    assert len(figures) == 2   # HRR and ceiling temperature: the series an FDS Result carries
    for fig in figures:
        names = [t.name for t in fig.data]
        assert names == ["Tier 1 (reduced)", "CFD (FDS)"]
    assert tuple(figures[0].data[1].y) == tuple(run.result.timeseries["hrr_mw"])
    _, _, out = _render(cfd={"A": run, "B": cfd_runs.NOT_RUN})
    assert "CFD (FDS)" in out
    assert "cfd: window ends before the HRR turnover" in out   # the run's own warnings travel


def test_the_cfd_peaks_table_reports_the_difference_without_judging_it():
    _, results, _ = _inputs()
    run = _finished_run(results["A"], scale=0.8)
    table = virtual_test._cfd_peaks_table(results["A"], run.result)
    tier1 = results["A"].peaks["hrr_mw"]
    assert f"{tier1 * 0.8 - tier1:+.1f} MW" in table
    assert "pass" not in table.lower() and "fail" not in table.lower()
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_cfd_runs.py tests/test_report_virtual_test.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'solit2.reports.cfd_runs'`, and `render() got an unexpected keyword argument 'cfd'`.

- [ ] **Step 3: Write `cfd_runs.py`**

```python
# solit2/reports/cfd_runs.py
"""Find the FDS run of a design and say what state it is in.

A run belongs to a design when its CHID is the design's SHA (`deck.chid`), so a
run is found by the design alone -- nobody links it by hand. Reading is I/O, so it
happens here and in the CLI; the report itself only formats a `CfdRun`.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

from solit2.engines.fds import deck, reader, runner
from solit2.schema.design import Design
from solit2.schema.result import Result

_T_END = re.compile(r"T_END\s*=\s*([\d.]+)")


@dataclass(frozen=True)
class CfdRun:
    # "not_run", "unreadable", or one of runner.status()'s states.
    state: str
    detail: str
    result: Result | None = None


NOT_RUN = CfdRun("not_run", "CFD not yet run")


def _t_end_s(deck_path: Path) -> float | None:
    # ponytail: regex on the deck text, as runner.status does; read T_END from the
    # design instead if the deck generator ever lets T_END drift from it.
    found = _T_END.search(deck_path.read_text())
    return float(found.group(1)) if found else None


def lookup(design: Design, runs_dir: Path | str) -> CfdRun:
    root = Path(runs_dir)
    run_dir = root / deck.chid(design)
    if not (run_dir / "deck.fds").exists():
        return NOT_RUN
    status = runner.status(run_dir)
    state = str(status["state"])
    if state in runner.RUNNING_STATES:
        t_end = _t_end_s(run_dir / "deck.fds")
        if t_end is None:
            return CfdRun(state, f"{state}, {float(status['progress']):.0%} complete")
        done = float(status["progress"]) * t_end
        return CfdRun(state, f"running, {done:.0f} of {t_end:.0f} s")
    if state != "done":
        return CfdRun(state, str(status.get("detail") or state))
    free_dir = root / deck.chid(design, suppression=False)
    try:
        result = reader.read(run_dir, design,
                             free_burn_dir=free_dir if (free_dir / "deck.fds").exists() else None)
    except (OSError, ValueError, KeyError) as exc:
        return CfdRun("unreadable", str(exc))
    return CfdRun("done", "", result)
```

- [ ] **Step 4: Write the section and change `render()`**

Add to `solit2/reports/virtual_test.py`:

```python
from solit2.reports.cfd_runs import CfdRun

# The only series an FDS Result carries (fds/reader.py builds its timeseries from
# these four), so the only ones that can be laid over a Tier 1 chart.
CFD_SERIES = (("hrr_mw", "Heat release rate"), ("ceiling_temp_c", "Ceiling temperature"))
CFD_PEAK_KEYS = ("hrr_mw", "ceiling_temp_c")


def _cfd_status_line(run: CfdRun) -> str:
    if run.state in ("not_run", "running", "pausing"):
        return run.detail
    return f"CFD {run.state}: {run.detail}"


def _cfd_figures(cls: str, tier1: Result, cfd: Result) -> list[go.Figure]:
    figures = []
    for key, title in CFD_SERIES:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=tier1.timeseries["t_s"], y=tier1.timeseries[key],
                                 mode="lines", name="Tier 1 (reduced)"))
        fig.add_trace(go.Scatter(x=cfd.timeseries["t_s"], y=cfd.timeseries[key],
                                 mode="lines", name="CFD (FDS)"))
        fig.update_layout(title=f"Test {cls} — {title}", xaxis_title="test clock (s)",
                          yaxis_title=labels.unit(key), height=350, margin=CHART_MARGIN)
        figures.append(fig)
    return figures


def _cfd_peaks_table(tier1: Result, cfd: Result) -> str:
    rows = []
    for key in CFD_PEAK_KEYS:
        a, b = float(tier1.peaks[key]), float(cfd.peaks[key])
        rows.append([labels.label(key), labels.with_unit(key, a), labels.with_unit(key, b),
                     f"{b - a:+.1f} {labels.unit(key)}"])
    return html.table(["Peak", "Tier 1", "CFD", "CFD minus Tier 1"], rows)


def _cfd_comparison(loaded: LoadedSpec, results: dict[str, Result],
                    cfd: dict[str, CfdRun], figs: _Figures) -> str:
    parts = [
        "<p>Each finished FDS run of a test design (its CHID is the design's SHA) is laid "
        "over that test's Tier 1 prediction. The CFD reader exports heat release rate and "
        "ceiling temperature only, so the other four charts on each results page have no "
        "CFD counterpart. Differences are reported, not judged: where the two tiers "
        "disagree, the disagreement is the finding.</p>"]
    for cls, design in sorted(loaded.tests.items()):
        run = cfd[cls]
        parts.append(f"<h3>Test {cls}: {html.escape(design.meta.name)}</h3>")
        parts.append(f"<p>{html.escape(_cfd_status_line(run))}</p>")
        if run.result is None:
            continue
        parts.append(_cfd_peaks_table(results[cls], run.result))
        parts += [figs.embed(fig) for fig in _cfd_figures(cls, results[cls], run.result)]
        if run.result.warnings:
            parts.append("<h4>Warnings from the CFD run</h4><ul>"
                         + "".join(f"<li>{html.escape(w)}</li>" for w in run.result.warnings)
                         + "</ul>")
    return "\n".join(parts)
```

`render()`:

```python
def render(loaded: LoadedSpec, results: dict[str, Result], *,
           traces: dict[str, RunTrace], cfd: dict[str, CfdRun]) -> str:
    figs = _Figures()
    sections = [
        # ... unchanged entries through ("Results", ...)
        ("CFD comparison", _cfd_comparison(loaded, results, cfd, figs)),
    ]
```

- [ ] **Step 5: Wire the CLI**

In `solit2/cli.py` add the option next to `--out` (`rvt.add_argument("--runs-dir", default="runs", help="where the CFD step wrote its run directories")`) and, in `_cmd_report_virtual_test`, after `traces`:

```python
    from solit2.reports import cfd_runs
    try:
        cfd = {cls: cfd_runs.lookup(d, args.runs_dir) for cls, d in loaded.tests.items()}
    except OSError as exc:
        return _fail(str(exc), "--runs-dir", "point at the directory the CFD step wrote to",
                     EXIT_BAD_INPUT)
    return _emit_html_report(virtual_test.render(loaded, results, traces=traces, cfd=cfd),
                             args.out)
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `uv run pytest tests/test_cfd_runs.py tests/test_report_virtual_test.py tests/test_cli_report_virtual_test.py -v`
Expected: all PASS. The CLI test passes without a `runs/` directory because a missing run directory is `NOT_RUN`, not an error.

- [ ] **Step 7: Commit**

```bash
git add solit2/reports/cfd_runs.py solit2/reports/virtual_test.py solit2/cli.py tests/test_cfd_runs.py tests/test_report_virtual_test.py
git commit -m "feat(reports): CFD comparison section with run lookup"
```

---

## Task 9: Compliance summary, conclusion, limitations and provenance

Sections 10, 11 and 12. The compliance summary is the checker's own headline and blocking clauses for the same spec. The conclusion is factual and names every criterion no authority has set. Limitations and provenance carry the calibration note, design SHAs, calibration hash, engine version and git commit.

**Files:**
- Modify: `solit2/reports/virtual_test.py`, `solit2/cli.py`
- Test: `tests/test_report_virtual_test.py`

**Interfaces:**
- Consumes: `solit2.compliance.check.run(spec_path) -> ComplianceReport` with `.spec_name`, `.findings`, `.headline`, `.provenance` (`design_sha.<test>`, `design_sha.installation`, `calibration`), `.blockers` (findings whose verdict is `FAILS` or `NEEDS_EVIDENCE`); `Finding` fields `rule_id, group, clause, requirement, kind, verdict, found, required, basis, basis_kind`; `Headline` fields `applicable, complying, by_deviation, fails, needs_evidence, evidenced, planned, predicted`; `solit2.reports.archive._git_commit() -> str` (the SHA, with `" (working tree modified)"` appended when dirty, or `"unknown"`); `Result.meta` keys `engine_version`, `design_sha`, `calibration_note`, `calibration_reference_nozzle`; `Result.warnings`.
- Produces:
  - `render(loaded, results, *, traces, cfd, compliance: ComplianceReport, commit: str) -> str`.
  - `_compliance_summary(report: ComplianceReport) -> str`, `_unset_criteria(results: dict[str, Result]) -> list[str]`, `_conclusion(loaded, results, report) -> str`, `_limitations(results, report, commit) -> str`.

The wording avoids "laboratory", "approved" and "certified": nothing in the report may read as a real test. The checker's basis kinds are reported as "a full-scale measurement", "a planned design value" and "a Tier 1 prediction".

- [ ] **Step 1: Write the failing tests**

Extend `_render` (add `from solit2.compliance import check as compliance_check` and cached compliance):

```python
@functools.lru_cache(maxsize=1)
def _compliance():
    return compliance_check.run(SPEC)


COMMIT = "0123abc (working tree modified)"


def _render(**overrides):
    """(loaded, results, html). Later tasks add their required keywords here."""
    loaded, results, traces = _inputs()
    kwargs = {"traces": traces, "cfd": {cls: cfd_runs.NOT_RUN for cls in loaded.tests},
              "compliance": _compliance(), "commit": COMMIT, **overrides}
    return loaded, results, virtual_test.render(loaded, results, **kwargs)
```

Add the tests:

```python
def _finding(verdict, clause="§7.2.1", requirement="No fire spread to the target"):
    from solit2.compliance.verdict import Finding
    return Finding(rule_id="r1", group="g", clause=clause, requirement=requirement,
                   kind="predicted", verdict=verdict, found="target ignited",
                   required="not ignited", basis="Tier 1", basis_kind="predicted")


def _report(findings):
    from pathlib import Path
    from solit2.compliance.check import ComplianceReport
    from solit2.compliance.verdict import headline
    return ComplianceReport("Spec <x>", Path("s.json"), tuple(findings),
                            headline(findings), {"calibration": "abc"})


def test_the_compliance_summary_lists_blocking_clauses_and_escapes_the_spec_name():
    from solit2.compliance.verdict import Verdict
    report = _report([_finding(Verdict.FAILS), _finding(Verdict.COMPLIES, clause="§9.9")])
    out = virtual_test._compliance_summary(report)
    assert "§7.2.1" in out and "§9.9" not in out   # only the blocker is tabled
    assert "Spec &lt;x&gt;" in out and "Spec <x>" not in out


def test_the_compliance_summary_says_so_when_nothing_blocks():
    from solit2.compliance.verdict import Verdict
    out = virtual_test._compliance_summary(_report([_finding(Verdict.COMPLIES)]))
    assert "No clause fails or lacks evidence" in out


def test_the_full_document_carries_the_checkers_headline():
    _, _, out = _render()
    report = _compliance()
    assert "<h2>10. Compliance summary</h2>" in out
    assert f"{report.headline.applicable} clauses apply" in out


def test_the_conclusion_names_every_criterion_no_authority_has_set():
    loaded, results, out = _render()
    unset = virtual_test._unset_criteria(results)
    assert unset, "the example spec's designs carry an empty ahj block"
    conclusion = out.split("<h2>11. Conclusion</h2>")[1].split("<h2>12.")[0]
    for label in unset:
        assert label in conclusion
    assert "no authority has set a limit for" in conclusion


def test_the_conclusion_never_reads_as_an_approval():
    _, _, out = _render()
    conclusion = out.split("<h2>11. Conclusion</h2>")[1].split("<h2>12.")[0].lower()
    for word in ("approved", "certified", "accepted", "passes the test"):
        assert word not in conclusion


def test_limitations_carry_the_calibration_note_and_full_provenance():
    loaded, results, out = _render()
    tail = out.split("<h2>12. Limitations and provenance</h2>")[1]
    report = _compliance()
    for result in results.values():
        assert result.meta["design_sha"] in tail
        assert result.meta["engine_version"] in tail
        # The note is HTML-escaped in the page, so compare against the unescaped section.
        assert result.meta["calibration_note"][:60] in stdlib_html.unescape(tail)
    assert report.provenance["calibration"] in tail
    assert COMMIT in tail
```

Add `import html as stdlib_html` to the imports at the top of `tests/test_report_virtual_test.py` (the module `virtual_test.html` is the reports shell, so the standard library one gets its own name here).

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_report_virtual_test.py -v`
Expected: FAIL — `render() got an unexpected keyword argument 'compliance'` for every test through `_render()`, `AttributeError` for `_compliance_summary`, `_unset_criteria`.

- [ ] **Step 3: Write the implementation**

Add to `solit2/reports/virtual_test.py`:

```python
from solit2.compliance.check import ComplianceReport
from solit2.engines.reduced.envelope import ENGINE_VERSION


def _compliance_summary(report: ComplianceReport) -> str:
    h = report.headline
    parts = [
        f"<p>Spec: {html.escape(report.spec_name)}. {h.applicable} clauses apply: "
        f"{h.complying} comply ({h.by_deviation} through an accepted deviation), "
        f"{h.fails} fail and {h.needs_evidence} need evidence. Of those that comply, "
        f"{h.evidenced} rest on a full-scale measurement, {h.planned} on a planned "
        f"design value and {h.predicted} on a Tier 1 prediction.</p>"]
    blockers = report.blockers
    if not blockers:
        parts.append("<p>No clause fails or lacks evidence.</p>")
        return "\n".join(parts)
    parts.append(html.table(
        ["Clause", "Requirement", "Verdict", "Found", "Required"],
        [[f.clause, f.requirement, f.verdict.value.replace("_", " "), f.found, f.required]
         for f in blockers]))
    return "\n".join(parts)


def _unset_criteria(results: dict[str, Result]) -> list[str]:
    """Labels of every criterion no test design's AHJ block set, across all tests."""
    return sorted({labels.label(key) for result in results.values()
                   for key, c in result.criteria.items() if c.status == "unset"})


def _conclusion(loaded: LoadedSpec, results: dict[str, Result],
                report: ComplianceReport) -> str:
    lines = []
    for cls, design in sorted(loaded.tests.items()):
        met, not_met, unset = _criteria_counts(results[cls])
        failed = sorted(labels.label(k) for k, c in results[cls].criteria.items()
                        if c.status == "fail")
        tail = f" Not met: {', '.join(failed)}." if failed else ""
        lines.append(f"<li>Test {cls} ({html.escape(design.meta.name)}): {met} criteria met, "
                     f"{not_met} not met, {unset} with no limit set.{html.escape(tail)}</li>")
    unset_names = _unset_criteria(results)
    unset_text = (f"<p>In at least one test design no authority has set a limit for: "
                  f"{html.escape(', '.join(unset_names))}. They are predicted and shown, and "
                  "not judged.</p>" if unset_names
                  else "<p>Every criterion in every test design has a limit set by its "
                       "authority.</p>")
    h = report.headline
    return "\n".join([
        "<p>This is a prediction from the engine, not a test result.</p>",
        f"<ul>{''.join(lines)}</ul>", unset_text,
        f"<p>The compliance checker finds {h.fails} failing and {h.needs_evidence} "
        f"unevidenced clause(s) of {h.applicable} that apply.</p>"])


def _limitations(results: dict[str, Result], report: ComplianceReport, commit: str) -> str:
    any_result = next(iter(results.values()))
    provenance = [[key.replace("design_sha.", "design SHA, "), value]
                  for key, value in sorted(report.provenance.items())
                  if key != "calibration"]
    provenance += [["calibration hash", report.provenance["calibration"]],
                   ["engine version", ENGINE_VERSION],
                   ["tool commit", commit]]
    warnings = sorted({w for r in results.values() for w in r.warnings})
    return "\n".join([
        f"<p>{html.escape(str(any_result.meta.get('calibration_note', '')))}</p>",
        "<p>Every number in this report is an extrapolation until a full-scale test of the "
        "assessed system exists.</p>",
        "<h3>Provenance</h3>", html.table(["Item", "Value"], provenance),
        "<h3>Warnings the engine raised</h3>",
        ("<ul>" + "".join(f"<li>{html.escape(w)}</li>" for w in warnings) + "</ul>"
         if warnings else "<p>The engine raised no warnings.</p>")])
```

The test above reads `result.meta["engine_version"]`; `ENGINE_VERSION` is that same constant (`envelope.py:25`, written into `meta` by `envelope.run`), so the table and the meta cannot differ.

`render()`:

```python
def render(loaded: LoadedSpec, results: dict[str, Result], *,
           traces: dict[str, RunTrace], cfd: dict[str, CfdRun],
           compliance: ComplianceReport, commit: str) -> str:
    figs = _Figures()
    sections = [
        # ... unchanged entries through ("CFD comparison", ...)
        ("Compliance summary", _compliance_summary(compliance)),
        ("Conclusion", _conclusion(loaded, results, compliance)),
        ("Limitations and provenance", _limitations(results, compliance, commit)),
    ]
    return html.document(f"Virtual fire test report — {loaded.spec.name}", sections)
```

- [ ] **Step 4: Wire the CLI**

In `_cmd_report_virtual_test`, after the CFD lookup:

```python
    from solit2.compliance import check as compliance_check
    try:
        # ponytail: check.run re-runs the envelope for every test design, so the engine
        # runs twice per report. Give check.run a results= parameter if runtime matters.
        compliance = compliance_check.run(args.spec)
    except (ValidationError, ValueError, FileNotFoundError, KeyError) as exc:
        return _fail(str(exc), "spec", "correct the compliance spec and try again",
                     EXIT_BAD_INPUT)
    except (ArithmeticError, RuntimeError) as exc:
        return _fail(str(exc), "engine",
                     "the spec validated but a design or rule could not be evaluated",
                     EXIT_ENGINE)
    # ponytail: reuses archive's private commit helper; make it public when a third
    # caller appears.
    commit = archive_mod._git_commit()
    return _emit_html_report(
        virtual_test.render(loaded, results, traces=traces, cfd=cfd,
                            compliance=compliance, commit=commit),
        args.out)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `uv run pytest tests/test_report_virtual_test.py tests/test_cli_report_virtual_test.py -v`
Expected: all PASS. `test_the_conclusion_never_reads_as_an_approval` scans only section 11; if it fails, fix the wording in `_conclusion` and leave the test as it is.

- [ ] **Step 6: Commit**

```bash
git add solit2/reports/virtual_test.py solit2/cli.py tests/test_report_virtual_test.py
git commit -m "feat(reports): compliance summary, conclusion, limitations and provenance"
```

---

## Task 10: Final assembly and the honesty-rule suite

Every section builder now exists and `render()` already lists them. This task pins their order to the design spec's twelve sections and adds the test suite the spec's "Honesty rules" and "Testing" sections call for, as one file so a reviewer can read the rules and the tests side by side.

**Files:**
- Modify: `solit2/reports/virtual_test.py` (`SECTION_TITLES`), `solit2/reports/html.py` (`without_scripts`)
- Create: `tests/test_report_virtual_test_honesty.py`

**Interfaces:**
- Consumes: everything from Tasks 1-9.
- Produces: `virtual_test.SECTION_TITLES: tuple[str, ...]` (the twelve titles, in the spec's order); `html.without_scripts(document_html: str) -> str` (the document with every `<script>` body removed, for scanning visible text — the Plotly bundle contains words such as "logo" that are not page content).

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_report_virtual_test_honesty.py
"""The virtual test report's honesty rules, one test per rule in the design spec."""
import dataclasses
import functools
import re
from pathlib import Path

import pytest

from solit2.compliance import check as compliance_check
from solit2.compliance.spec import load_spec
from solit2.engines.reduced import envelope, sim
from solit2.reports import cfd_runs, html, labels, virtual_test

SPEC = "examples/compliance/solit2-example.spec.json"
COMMIT = "0123abc"
SPEC_SECTIONS = (
    "Introduction", "Requested tests", "Test facility", "Water mist system",
    "Fire load and target", "Virtual instruments", "Procedure", "Results",
    "CFD comparison", "Compliance summary", "Conclusion", "Limitations and provenance",
)


@functools.lru_cache(maxsize=1)
def _world():
    loaded = load_spec(SPEC)
    results = {cls: envelope.run(d) for cls, d in loaded.tests.items()}
    traces = {cls: sim.run_once(loaded.tests[cls], r.worst_case["section"],
                                r.worst_case["velocity_ms"]) for cls, r in results.items()}
    return loaded, results, traces, compliance_check.run(SPEC)


def _render(cfd=None):
    loaded, results, traces, compliance = _world()
    cfd = cfd or {cls: cfd_runs.NOT_RUN for cls in loaded.tests}
    return virtual_test.render(loaded, results, traces=traces, cfd=cfd,
                               compliance=compliance, commit=COMMIT)


def test_every_section_of_the_design_spec_is_present_in_its_order():
    assert virtual_test.SECTION_TITLES == SPEC_SECTIONS
    headings = re.findall(r"<h2>(\d+)\. (.*?)</h2>", _render())
    assert [(int(n), title) for n, title in headings] == list(enumerate(SPEC_SECTIONS, 1))


def test_the_prediction_band_is_on_every_section_and_in_the_repeating_header():
    out = _render()
    assert out.count(html.BAND_TEXT) == len(SPEC_SECTIONS) + 1


def test_nothing_reads_as_a_real_test():
    visible = html.without_scripts(_render()).lower()
    for word in ("witness", "signature", "signed by", "laboratory", "accredited",
                 "certificate", "logo"):
        assert word not in visible
    assert "<img" not in visible


def test_a_limit_only_ever_comes_from_the_designs_own_ahj_block():
    loaded, _, _, _ = _world()
    designs = {cls: d.model_copy(update={"ahj": d.ahj.model_copy(update={"max_air_temp_c": 123.0})})
               for cls, d in loaded.tests.items()}
    loaded2 = dataclasses.replace(loaded, tests=designs)
    results2 = {cls: envelope.run(d) for cls, d in designs.items()}
    procedure = virtual_test._procedure(loaded2, results2)
    assert "123" in procedure                       # the limit the design's ahj set
    total = sum(len(r.criteria) for r in results2.values())
    unset = sum(1 for r in results2.values() for c in r.criteria.values()
                if c.status == "unset")
    assert procedure.count("<tr>") - len(results2) == total    # one row per criterion
    assert procedure.count("limit not set") == unset           # every unset one says so
    assert 0 < unset < total


def test_the_example_specs_unset_criteria_read_limit_not_set_beside_their_value():
    loaded, results, _, _ = _world()
    out = _render()
    assert "limit not set" in out
    for result in results.values():
        for key, criterion in result.criteria.items():
            if criterion.status == "unset":
                assert labels.with_unit(key, criterion.value) in out


def test_every_free_burn_and_peak_number_is_the_engines_own():
    _, results, _, _ = _world()
    fig = virtual_test._hrr_figure(results)
    by_name = {t.name: t for t in fig.data}
    for cls, result in results.items():
        assert tuple(by_name[f"Test {cls} — free burn"].y) == tuple(
            result.timeseries["hrr_free_burn_mw"])
        assert result.peaks["hrr_free_burn_mw"] == max(result.timeseries["hrr_free_burn_mw"])


def test_the_cfd_placeholder_appears_without_a_run():
    loaded, _, _, _ = _world()
    assert _render().count("CFD not yet run") == len(loaded.tests)


def test_a_finished_run_is_overlaid_and_a_missing_one_still_says_so():
    loaded, results, _, _ = _world()
    ts = results["A"].timeseries
    finished = cfd_runs.CfdRun("done", "", results["A"].model_copy(update={
        "timeseries": {"t_s": ts["t_s"], "hrr_mw": ts["hrr_mw"],
                       "hrr_free_mw": ts["hrr_free_burn_mw"],
                       "ceiling_temp_c": ts["ceiling_temp_c"]}}))
    out = _render({"A": finished, "B": cfd_runs.NOT_RUN})
    assert "CFD (FDS)" in out
    assert out.count("CFD not yet run") == 1


def test_the_document_makes_no_network_request_and_embeds_plotly_once():
    out = _render()
    assert html.external_references(out) == []
    assert out.count(html.BUNDLE_MARK) == 1


def test_a_design_name_cannot_inject_markup_anywhere_in_the_document():
    loaded, results, traces, compliance = _world()
    hostile = "<script>alert(1)</script>"
    designs = {cls: d.model_copy(update={"meta": d.meta.model_copy(update={"name": hostile})})
               for cls, d in loaded.tests.items()}
    out = virtual_test.render(dataclasses.replace(loaded, tests=designs), results,
                              traces=traces,
                              cfd={cls: cfd_runs.NOT_RUN for cls in designs},
                              compliance=compliance, commit=COMMIT)
    assert hostile not in out
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in out


def test_the_cli_writes_a_file_that_passes_every_check_above(tmp_path):
    import subprocess
    out = tmp_path / "virtual-test.html"
    done = subprocess.run(
        ["uv", "run", "solit2", "report", "virtual-test", SPEC, "--out", str(out)],
        capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    text = out.read_text()
    assert html.external_references(text) == []
    assert text.count(html.BAND_TEXT) == len(SPEC_SECTIONS) + 1
    assert text.count(html.BUNDLE_MARK) == 1
```

Add to `tests/test_report_html.py`:

```python
def test_without_scripts_drops_script_bodies_but_keeps_the_page():
    doc = "<p>hello</p><script>var logo = 1;</script><p>world</p>"
    assert html.without_scripts(doc) == "<p>hello</p><p>world</p>"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_report_virtual_test_honesty.py tests/test_report_html.py -v`
Expected: FAIL — `AttributeError: module 'solit2.reports.virtual_test' has no attribute 'SECTION_TITLES'` and `AttributeError: ... 'without_scripts'`; the rest fail on those or pass already.

- [ ] **Step 3: Write the implementation**

In `solit2/reports/html.py`:

```python
def without_scripts(document_html: str) -> str:
    """The page with every <script>...</script> removed, for scanning what a reader sees."""
    return _SCRIPT_BODY.sub("", document_html)
```

In `solit2/reports/virtual_test.py`, name the twelve sections once and use the constant in `render()`, so the order the design spec fixes lives in one place:

```python
SECTION_TITLES = (
    "Introduction", "Requested tests", "Test facility", "Water mist system",
    "Fire load and target", "Virtual instruments", "Procedure", "Results",
    "CFD comparison", "Compliance summary", "Conclusion", "Limitations and provenance",
)
```

```python
def render(loaded: LoadedSpec, results: dict[str, Result], *,
           traces: dict[str, RunTrace], cfd: dict[str, CfdRun],
           compliance: ComplianceReport, commit: str) -> str:
    figs = _Figures()
    bodies = (
        _introduction(),
        _requested_tests(loaded),
        _facility(loaded),
        _water_mist_system(loaded),
        _fire_load(loaded),
        _instruments(),
        _procedure(loaded, results),
        _results(loaded, results, traces, figs),
        _cfd_comparison(loaded, results, cfd, figs),
        _compliance_summary(compliance),
        _conclusion(loaded, results, compliance),
        _limitations(results, compliance, commit),
    )
    assert len(bodies) == len(SECTION_TITLES)   # a builder added without a title is a bug
    out = html.document(f"Virtual fire test report — {loaded.spec.name}",
                        list(zip(SECTION_TITLES, bodies)))
    refs = html.external_references(out)
    if refs:
        raise ValueError(f"the report would fetch something when opened: {refs[:3]}")
    return out
```

The tuple of bodies is evaluated in order, so `figs` still hands the Plotly bundle to the first chart in document order (Results), which is what Task 6's `_Figures` docstring requires.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_report_virtual_test_honesty.py tests/test_report_virtual_test.py tests/test_report_html.py tests/test_cfd_runs.py tests/test_cli_report_virtual_test.py -v`
Expected: all PASS.

- [ ] **Step 5: Run the independence scan**

Run: `uv run pytest tests/test_independence.py -v`
Expected: PASS. If it fails on `solit2/reports/virtual_test.py`, `html.py` or `cfd_runs.py`, the failing line names a banned term (a manufacturer, project or vendor); remove the literal from the source. Names may appear in the report only through `Design`/`ComplianceSpec` data at render time.

- [ ] **Step 6: Run the whole suite**

Run: `uv run pytest -q`
Expected: everything PASS. A failure in a file this plan did not touch is pre-existing: confirm by running that one test on `feat/tier1-optimiser` in the main checkout, and report it rather than fixing it here.

- [ ] **Step 7: Look at the real file**

Run: `uv run solit2 report virtual-test examples/compliance/solit2-example.spec.json --out reports/virtual-test.html`
Open `reports/virtual-test.html` in a browser (no server needed) and confirm: the red band on every section; twelve numbered headings; charts are interactive with the network disabled (browser dev tools → Offline); the 3D tunnel rotates; "Save as PDF" gives A4 pages with the band repeating at the top of each. The file is a build product; do not commit `reports/virtual-test.html`.

- [ ] **Step 8: Commit**

```bash
git add solit2/reports/virtual_test.py solit2/reports/html.py tests/test_report_virtual_test_honesty.py tests/test_report_html.py
git commit -m "feat(reports): pin the twelve sections and add the honesty-rule suite"
```

---

## Self-review

**Spec coverage** (`docs/superpowers/specs/2026-09-26-virtual-test-report-design.md`):

| Spec item | Task |
|---|---|
| Engine change: `hrr_free_burn_mw` in the timeseries | 1 |
| Self-contained HTML, Plotly embedded once, print CSS, A4, numbered sections, repeating header | 2, 6 (once), 10 |
| CLI `report virtual-test <spec> --out` | 3 |
| 1 Introduction; 2 Requested tests; 3 Facility; 4 Water mist; 5 Fire load; 6 Instruments; 7 Procedure | 3, 4, 5 |
| 8 Results: summary table, HRR comparison with t² curves, ceiling comparison | 6 |
| 8 Results: per-test overview, configuration, timeline, criteria checklist, six charts, 3D at peak HRR | 7 |
| 9 CFD comparison: overlay, "not yet run", "running, N of T_END s" | 8 |
| 10 Compliance summary; 11 Conclusion naming unset criteria; 12 Limitations and provenance | 9 |
| Honesty rules: band, no real-test furniture, limits only from `ahj`, every number the engine's | 10 (and 2, 6, 7) |
| Testing list: sections, band, "limit not set", no third-party limits, CFD placeholder and overlay, offline, independence | 10 |

**Not in this plan, on purpose:**
- "The Reports step offers the same file as a download" (spec, Input and output). `app/views/reports.py` works from one design, and the virtual test needs a compliance spec naming tests A and B; where that spec comes from in the wizard is a product decision, so no task guesses at it. The CLI is complete without it.
- `designs/og-test-spec.json` still raises `MissingNozzleData`; every test here uses `examples/compliance/solit2-example.spec.json`.

**Corrections made to Tasks 2, 3 and 5 while writing Tasks 6-10** (each was a defect that would have failed or misled when executed):
1. Task 2's bundle marker `function Plotly` does not exist in plotly.js v4 (bundled by plotly 7.1.0); it is now the licence header `plotly.js v`, which appears once.
2. Task 3's "no `http://`/`https://` in the file" would fail as soon as the Plotly bundle is embedded (it contains dozens of such strings inside script bodies). It is now `html.external_references(out) == []`, a real check that skips script bodies and still catches `<script src>`, `<link>`, `@import`, `url(//…)` and external `href`/`src`.
3. Task 2's print CSS used `position: running()`, which browsers ignore, so the header would not repeat. It is now `position: fixed` in `@media print`.
4. Task 5's `<h3>` printed the design name unescaped; it is now escaped, and Task 7 and Task 10 test that.

**Type consistency:** `render` grows one required keyword per task (`traces` → `cfd` → `compliance`, `commit`), and each task updates the single `_render()` test helper; `_Figures.embed` is the only way a chart reaches the document; `CfdRun`/`NOT_RUN` are defined in Task 8 and used unchanged in Tasks 9-10; `_criteria_counts` is defined in Task 6 and used in Tasks 7 and 9.

**Known risk, not a gap:** `virtual_test.py` imports `app.components.*` (Task 7). It works in the repo's development install; a wheel built from `packages = ["solit2"]` would lack `app`. The `ponytail:` comment names the upgrade path.

---

**Plan complete and saved to `docs/superpowers/plans/2026-09-30-virtual-test-report.md`.** Two execution options:

1. **Subagent-Driven (recommended)** — a fresh subagent per task with review between tasks.
2. **Inline Execution** — run the tasks in this session with checkpoints.

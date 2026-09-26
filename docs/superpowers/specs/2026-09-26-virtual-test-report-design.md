# Virtual fire test report — design

**Status:** approved 2026-09-26 — planned SOLIT² tests, HTML (print to PDF), Tier 1 now with CFD
when ready, interactive Plotly charts; built after the live simulator screen, reusing its figures.

## Why

A full-scale tunnel fire test is reported in a recognisable shape: facility, system, fire load,
instruments, procedure, a results summary, a comparison of the fires, then each test's
configuration, timeline, criteria and results page. A prediction of the planned SOLIT² tests laid
out the same way can be read by the same people, and the real test report can later be placed
beside it section by section. The layout follows the conventional order of such reports; no
content, figure or limit is taken from any third party's report, and none is cited.

## Input and output

`uv run solit2 report virtual-test designs/og-test-spec.json --out reports/virtual-test.html`

The compliance spec names test designs A and B. Each is run through Tier 1 (`envelope.run`, then
`sim.run_once` for the worst case). The output is one self-contained HTML file: interactive
Plotly charts with plotly.js embedded once, so it opens offline and never loads anything from the
network; print CSS gives A4 pages, numbered sections and a repeating header, so "Save as PDF"
produces a lab-style PDF. The Reports step offers the same file as a download.

## Contents

1. **Introduction** — what a virtual test is and what it is not.
2. **Requested tests** — test, fire class, fire load, nominal free-burn HRR, ventilation, duration.
3. **Test facility** — tunnel geometry, ventilation and water supply, from each test design.
4. **Water mist system** — nozzle description; configuration table (K-factor, pressure, flow,
   zone length, heads, total K).
5. **Fire load and target.**
6. **Virtual instruments** — the stations the engine outputs and what is not modelled.
7. **Procedure** — ignition, detection, activation, duration, performance criteria.
8. **Results**
   - summary table across the tests;
   - HRR comparison: suppressed HRR, the engine's free-burn HRR, and t² growth curves
     (slow, medium, fast, ultra-fast; α from NFPA 72 / SFPE, cited in the report);
   - ceiling temperature comparison;
   - per test: an overview written from the numbers, the configuration and water-mist tables,
     a timeline table (ignition, detection, activation, full pressure, peak HRR, backlayering
     cleared, end), a criteria checklist (✓ / ✗ / "limit not set"), and a results page of six
     charts (HRR, air velocity, heat flux at U15, gas temperature at U15, gas temperature at every
     station, water flow) plus the 3D tunnel at peak HRR.
9. **CFD comparison** — each finished FDS run of a test design (CHID = the design's SHA) is
   overlaid on that test's charts; otherwise "CFD not yet run" or "running, N of T_END s".
10. **Compliance summary** — the checker's headline and failing clauses for the same spec.
11. **Conclusion** — factual, naming every criterion no authority has set.
12. **Limitations and provenance** — the calibration note, design SHAs, calibration hash,
    engine version, git commit and dirty flag.

## Honesty rules (not negotiable)

- A band on every page: **VIRTUAL TEST — prediction, not a measurement.**
- No laboratory name, logo, signature, witness block or anything that reads as a real test.
- Pass/fail limits only from each design's `ahj`; an unset limit reads "limit not set" beside the
  predicted value. No limit from any third party's report is used.
- Every number is the engine's output; the free-burn HRR is the engine's own `hrr_free_mw`.

## Engine change

`Result.timeseries` gains `hrr_free_burn_mw` (the engine already computes `hrr_free_mw` at every
step and reports only its peak).

## Testing

Every section present; the band on the page; "limit not set" where a limit is missing; no
third-party limit values appear; the CFD placeholder without a run and the overlay with a
synthetic finished run; the file contains no network URL (offline); the independence scan passes.

# Trust dossier — design

**Status:** approved 2026-09-24 ("I go with your recommendations. make it"). Extends sub-project D
of the digital-twin gap programme (`2026-09-24-solit2-compliance-checker-design.md`). Built after
the compliance checker.

## Why

Customers and authorities trust a CFD result for the reasons ASTM E1355 and the SFPE guide to
substantiating a fire model list, not because of the software's name: the solver is verified,
the model is validated against fires it was not tuned on, the answer does not depend on the grid,
every number carries its uncertainty, and a prediction made before a test is compared with the
test. This design turns each of those into an artefact the software produces, keeps a
tamper-evident log of how each was made, and shows all of it on one screen and in one document.

Nothing here may make a result look more certain than it is. An artefact that has not been
produced is shown as **not yet established**, never omitted.

## What gets built

| # | Piece | Module | Runs without FDS |
|---|---|---|---|
| 1 | Verification record | `solit2/trust/verification.py` | yes |
| 2a | Tier 1 held-out validation (leave one anchor out) | `validation/crossval.py` | yes |
| 2b | Tier 2 held-out E calibration | extends `solit2/engines/fds/calibrate.py` | tooling yes, runs no |
| 3 | Grid convergence | exists (`solit2/engines/fds/grid.py`); the dossier reads its `report.json` | tooling yes, runs no |
| 4 | Uncertainty bands | `solit2/trust/uncertainty.py` | yes |
| 5 | Locked blind prediction | `solit2/trust/prediction.py` | yes |
| — | Audit log (tamper-evident) and diagnostics log | `solit2/audit.py`, `solit2/logs.py` | yes |
| — | Validation dossier report | `solit2/reports/validation_dossier.py`, `solit2 report validation` | yes |
| — | Trust wizard step | `app/views/trust.py` | yes |
| — | Cloud compute guide | `docs/cloud-compute.md` | — |

## Components

### Audit log — `solit2/audit.py`

Append-only `runs/audit.jsonl`. Every record: `timestamp` (UTC ISO 8601), `action`, `subject`
(design name or run dir), `design_sha`, `calibration_hash` (first 12 hex of SHA-256 of
`calibration.json`), `git_commit` and `git_dirty`, `engine_version`, `outcome`, `details` (small
dict), `prev_hash`, `hash`. `hash = sha256(prev_hash + canonical JSON of the record without
hash)`, so the file is a hash chain: editing, reordering or deleting any record breaks every hash
after it. `verify_chain(path) -> ChainStatus(intact: bool, records: int, first_bad: int | None)`.

Actions recorded: `tier1_run`, `fds_launch`, `fds_resume`, `fds_stop`, `fit`, `crossval`,
`uncertainty`, `prediction_lock`, `compliance_check`, `dossier_render`. Instrumented at the call
sites that already exist (CLI `run`, `runner.run/resume/stop`, `validation.fit.run`) and in every
new module.

Stated limit, in the module and in the dossier: a chain proves the log was not edited *in the
middle*; someone could rewrite the whole file. The external anchor is the locked prediction's
fingerprint sent to a third party (piece 5).

### Diagnostics log — `solit2/logs.py`

Standard `logging`: one `configure()` that adds a rotating file handler at `runs/solit2.log`
(1 MB × 5), called once by the CLI entry point and the Streamlit app. Modules log with
`logging.getLogger(__name__)`. Diagnostics only; the audit log is the record.

### 1. Verification record — `solit2/trust/verification.py`

`record(run_root: Path) -> VerificationRecord`: the FDS version and source revision of every
FDS run directory under `run_root` (from `runner.fds_version`/the run's own log), the NIST FDS
Verification Guide as the solver's verification, and the repository's own deck/reader test files
with their test counts (counted by parsing `def test_` in `tests/test_fds_*.py`). No FDS runs
→ the record says so.

### 2a. Tier 1 held-out validation — `validation/crossval.py`

For each anchor: fit the calibration on the other anchors (`validation.fit.run`, bounded
`max_nfev`), then evaluate the held-out anchor with `compare.check`. Report per fold and quantity:
modelled, measured, tolerance, within. Summary: held-out pass count against the in-sample count.

`calibration.json` is **restored byte-for-byte** after every fold in a `finally`, and the restore
is verified by hash; a failed restore raises. Output `runs/trust/crossval.json`. CLI:
`solit2 validate --cross --max-nfev N`.

### 2b. Tier 2 held-out E — `calibrate.py`

`solit2 fds-calibrate-e --fit c4 --holdout c5 c6 ...`: E is fitted on the `--fit` anchors only;
each held-out anchor's modelled peak HRR at that E is interpolated on its own sweep and reported
against its measurement, labelled "interpolated between sweep runs", with the nearest run named.
Without runs it reports that nothing has been run.

### 3. Grid convergence

Unchanged. The dossier reads `<grid out>/<chid>/report.json` when present.

### 4. Uncertainty bands — `solit2/trust/uncertainty.py`

An uncertainty file in `designs/` names input ranges from a fixed allowlist, each with a source:

```json
{"design": "og-ds01-rev00-cd-meas.json", "samples": 40, "seed": 0,
 "inputs": {
   "nozzles.k_factor_lpm_bar05": {"low": 5.29, "high": 5.85,
      "source": {"document": "...", "locator": "..."}}}}
```

Allowlist: `nozzles.k_factor_lpm_bar05`, `nozzles.pressure_bar`, `nozzles.modes.0.smd_um`,
`nozzles.modes.0.cone_half_angle_deg`, `zones.activation_delay_s`, `zones.pump_ramp_s`,
`ventilation.velocity_range_ms.1` (the upper velocity), `fire.incubation_s`.
**A range without a source is refused** ("an uncertainty range with no basis is a guess").

Latin hypercube sampling with the file's seed (reproducible), one Tier 1 `envelope.run` per
sample. Output: P5/P50/P95 of `hrr_mw`, `ceiling_temp_c`, `target_peak_flux_kwm2`,
`smoke_layer_temp_d15_c`; a P5–P95 HRR band over time; per-input Spearman rank correlation as the
sensitivity ranking; how many samples ignited the target. The FDS tier's measured ±6.5 % LES run
scatter is reported alongside as a separate, stated figure. Output
`runs/trust/uncertainty-<design_sha>.json`.

### 5. Locked blind prediction — `solit2/trust/prediction.py`

`lock(design_path, out_dir=Path("designs/predictions")) -> Path` writes
`<name>-<UTC>.lock.json`: the full design, the Tier 1 result's peaks, events and time series,
design SHA, calibration hash, git commit and dirty flag, engine version, timestamp, and
`content_sha256` over the canonical JSON of everything else. A dirty tree is recorded and warned
about, not hidden. `verify(path) -> bool` recomputes the fingerprint. CLI:
`solit2 predict-lock DESIGN` (prints the fingerprint and the advice to send it to the main
contractor before the test) and `solit2 predict-verify LOCKFILE`.

### Validation dossier — `solit2/reports/validation_dossier.py`

`solit2 report validation [--out]` renders, in order: verification; Tier 1 validation against
every anchor (live `compare.check`) and the held-out results; Tier 2 E calibration and held-out
results; grid convergence; uncertainty; locked predictions with their verify status; the audit
chain status; the range of validity (the anchors' tunnel, fire and velocity envelope); known
weaknesses **computed from the live anchor misses**, not prose; and a **"Not yet established"**
list built from every missing artefact. Nothing missing is omitted.

### Trust wizard step — `app/views/trust.py`

Wizard: Design → Result → Fire test → CFD verify → Compliance → **Trust** → Reports (7 steps).
Uses the existing design system (`app/theme.py`, `app/palette.py`: IBM Plex, PASS/FAIL/UNSET
chips, verdict banner, plotly).

- **Top strip:** five status cards (Verification, Validation, Grid, Uncertainty, Blind
  prediction), each with a chip: *established* (PASS), *partial* (UNSET), *not yet* (GREY),
  *failed check* (FAIL) and a one-line reason.
- **Tabs:**
  - *Validation*: parity chart, modelled against measured per anchor quantity with the tolerance
    band, held-out points marked distinctly; the per-fold table; a "Run cross-validation" button.
  - *Uncertainty*: P5–P95 fan over the HRR time series with the P50 line, a tornado bar of
    sensitivities, the percentile table; a "Run uncertainty" button for a chosen uncertainty file.
  - *Grid*: the GCI table from the study report, or "not run — needs mains power or a cloud
    machine" with the command to run.
  - *Blind predictions*: the lock files with verify badges; a "Lock the current design's
    prediction" button that shows the fingerprint to send.
  - *Audit log*: newest-first table, and a chain badge: *chain intact (N records)* or *chain
    BROKEN at record N*.
- **Download:** the dossier markdown.

### Cloud compute guide — `docs/cloud-compute.md`

How to run the Tier 2 campaign on a rented Linux machine through the existing
`SOLIT2_FDS_HOST` remote option: machine class to choose, FDS and MPI install, keeping the run
alive, copying results back, and that prices must be checked at the provider. No figure in the
guide may be presented as measured unless it was.

## Errors

| Condition | Behaviour |
|---|---|
| uncertainty input outside the allowlist, or without a source | refused, naming the input |
| calibration restore after a fold fails its hash check | raise; never continue on a modified calibration |
| lock file edited | `verify` false, the UI badge red, the dossier says so |
| audit chain broken | reported with the first bad record; never repaired silently |
| an artefact missing | "not yet established" in dossier and UI |

## Testing

- Audit: appending three records then editing the middle one makes `verify_chain` report it.
- Cross-validation: `calibration.json` bytes identical after a run; a held-out fold never sees
  its own anchor in the fit (asserted by spying the anchors passed to `fit.run`).
- Uncertainty: an unsourced range is refused; the same seed gives identical percentiles; a
  zero-width range collapses the band to the nominal result.
- Prediction: lock then verify is true; change one number in the file and verify is false.
- Dossier: with no FDS runs, no grid report and no locks, every one is listed under "Not yet
  established".
- App: AppTest renders the Trust step with the five cards and the audit chain badge.
- Independence scan passes.

## Out of scope

Running the FDS campaign itself (needs mains power or the cloud machine); pyrolysis (D4); any
branding. If a company logo is wanted later it loads from a file in `designs/`, never from app
code, to keep the app vendor-neutral.

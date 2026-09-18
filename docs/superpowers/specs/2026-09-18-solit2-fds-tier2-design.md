# SOLIT2 Tier 2 (FDS/CFD) Design

**Parent spec:** [2026-09-15-solit2-simulator-design.md](2026-09-15-solit2-simulator-design.md) §6, §8, §9, §10, §11, §14 — this document is the detailed design for the one major piece that spec left unbuilt. It does not restate Tier 1, the CLI's existing commands, or the Streamlit app's other views; it assumes all of those as-shipped (pushed to `alisajil/solit2-simulator`, `main`).

## 1. Purpose and scope

Tier 1 (`solit2/engines/reduced/`) is a reduced-order model: closed-form correlations, calibrated against six SOLIT²/APPLUS anchor tests. It is fast (~1-2s for a full envelope) and it is the tool the optimisation loop (`CLAUDE.md` §12) iterates against. It is not a physics solver — every module in it (`fire.py`, `mist.py`, `ventilation.py`, `thermal.py`) is a hand-fitted stand-in for physics FDS computes directly.

Tier 2 exists for one reason: **pre-test evidence**. Before Mistelix's own SOLIT² full-scale fire test (which becomes anchor c7 the day it runs), a real CFD run on the actual chosen design, in the actual Orange Gate geometry, is the best evidence available that Tier 1's picked design will behave as scored. It is not a faster or more convenient way to score designs — it is slower (hours per run) and it exists specifically to catch what a correlation-fitted reduced-order model cannot: geometry effects, spray-momentum/ventilation interaction, non-linear coupling Tier 1 flattens into a single calibrated constant.

**This pass builds the full pipeline** — `deck.py`, `runner.py`, `reader.py`, CLI wiring, and the Verify view — tested entirely through golden files, mocked pre-flight checks, and a synthetic output-parsing fixture, **without a live FDS install**. No FDS access exists yet (confirmed with the user before this design started). The one thing this pass cannot verify is whether a real `fds` binary, run against a deck this generates, actually produces output in the shape `reader.py` expects. That is a disclosed, accepted risk — not a blocker — to be closed by a live smoke test the first time real FDS access exists.

## 2. Repository layout (additions)

```
solit2/
  engines/
    fds/
      __init__.py
      deck.py      generate(design) -> str; deterministic FDS namelist text
      runner.py    preflight(), run(), status()
      reader.py    read(run_dir, design) -> Result
designs/
  og-dbr-rev0.json   the Orange Gate baseline the spec names and nothing currently provides
tests/
  test_fds_deck.py
  test_fds_runner.py
  test_fds_reader.py
  fixtures/
    fds/
      sample_devc.csv   synthetic FDS device-output fixture, shaped like real FDS CSV output
      sample_hrr.csv
```

`app/views/verify.py` is rewritten in place (no new file). `solit2/cli.py` gains `fds-deck`, `fds-status`, and an extended `--engine` choice on `run`.

## 3. `deck.py` — namelist generation

`generate(design: Design) -> str`. Pure function, deterministic (same `Design` in, byte-identical text out) — this is what makes golden-file testing possible at all.

**Reuses, does not reimplement:**
- `solit2.engines.reduced.geometry.section_geometry(design)` and `nozzle_positions(design, geom, fire_x_m)` for every tunnel and head-position number. Tier 1 already solved "where is the wall, where is the nozzle" correctly and it is tested; Tier 2 needs the same answer, not a second implementation that could silently drift from the first.
- `solit2.engines.reduced.criteria.STATIONS` and `INSTRUMENTS` for every `&DEVC` measurement point. This is the one non-negotiable reuse: if Tier 1 and Tier 2 measured different points, `solit2 report correlation` would be comparing two different things and calling it agreement or disagreement by accident.

**Single-mode nozzle** (per the user's standing choice — see memory `nozzle-single-mode-only`): one `&PROP`/`&PART`/`&DEVC` per head, not the spec's two (`NOZ_FINE` + `NOZ_COARSE`). `design.nozzles.modes` already collapses to one entry under this choice, so `deck.py` emits exactly what the design contains — no special-casing.

**Namelist blocks** (syntax verified against `firemodels/fds`'s own `Verification/Sprinklers_and_Sprays/activate_sprinklers.fds`, not just the parent spec's compressed table):
- `&HEAD` — `CHID` from the design's sha (matches `envelope._design_sha`, so a deck and its eventual result share an identifier), `TITLE` from `design.meta.name`.
- `&MESH` — window U60→D120 (180 m) from the fire, N meshes along x sized for MPI; `dx` from the spec's `D* = (Q̇/(ρ∞ cₚ T∞ √g))^{2/5}` grid formula, defaulting to the 0.45 m screening resolution (`--dx` CLI override to 0.25 m for a final run).
- Tunnel envelope: stair-stepped `&OBST` ring for `bored` (from `SectionGeometry.width_at()` sampled per mesh cell), rectangular walls for `cut_cover`, rectangle + false ceiling for the `solit2_test` San Pedro geometry.
- `&VENT MB='XMIN' SURF_ID='SUPPLY'` with `SURF VEL=-u` (inflow), `MB='XMAX' SURF_ID='OPEN'`.
- Fire: Class A pallet `&OBST` + `&SURF ID='FIRE' HRRPUA, RAMP_Q` (the free-burn curve, unsuppressed — suppression is FDS's own job via `E_COEFFICIENT`, not pre-baked the way Tier 1 bakes it into `fire.py`); Class B pool `&SURF` per pool.
- Nozzle heads: one `&DEVC PROP_ID='NOZ_FINE' CTRL_ID='ACT'` per position from `nozzle_positions()`, every head referencing a single deck-level `&PROP`/`&PART` pair (defined once, not per head) whose `FLOW_RATE` is `K√P` (the same hydraulics number Tier 1 computes) and whose `DIAMETER` comes from `design.nozzles.smd_table`.
- Detection: `&DEVC THERMOCOUPLE SETPOINT=design.detection.threshold_c` per `sensor_spacing_m` → `&CTRL FUNCTION_TYPE='TIME_DELAY' DELAY=design.zones.activation_delay_s` → `ACT`.
- Stations: `&DEVC` at every `STATIONS`/`INSTRUMENTS` entry — thermocouple tree (matching `criteria.thermocouple_heights_m`), heat-flux gauge where `INSTRUMENTS` says one exists, FED, visibility, velocity.
- Output: `&DUMP DT_DEVC=1 DT_HRR=1`, two `&SLCF` (centreline T, U).

**Not built this pass:** the mesh-cell-count/runtime estimate is reported (from the spec's own formula) but not enforced — a design that would need an infeasible cell count still generates a deck; `runner.preflight()` is where infeasibility gets caught, not `deck.py`.

## 4. `runner.py` — pre-flight, execution, status

`preflight() -> list[str]` — empty list means ready to run. Checks: `fds` on `PATH` or `SOLIT2_FDS_BIN` set; `mpiexec` on `PATH` if the deck's mesh count > 1; `shutil.disk_usage` ≥ 10 GB free (spec's own floor); if `SOLIT2_FDS_HOST` is set, that path is checked instead of the local binary. Every check is independently mockable (`shutil.which`, `os.environ`, `shutil.disk_usage`) — this is what makes the whole module testable without a real install.

`run(deck_path, out_dir) -> str` (returns a run id) — launches `fds <deck>` as a detached subprocess and returns immediately; FDS runs are hours long, and the Verify view needs to poll progress rather than freeze on them. Runs use a working directory of `runs/<sha>/`, the same sha the deck's `CHID` carries.

**Local execution only this pass.** If `SOLIT2_FDS_HOST` is set, `preflight()` returns a single clear failure — remote execution is not implemented — rather than silently running locally or half-attempting a transport. The `preflight`/`run`/`status` interface is what keeps that detail swappable later; guessing at SSH-vs-queue semantics now, with no host to test against, would be building against an imagined system.

`status(run_dir) -> dict` — reads FDS's own `.out` log for elapsed simulated time against the deck's `T_END`, reports `{"state": "running"|"done"|"failed", "progress": 0.0-1.0}`. A missing or malformed log is `"failed"`, not silently `"running"` forever.

## 5. `reader.py` — FDS output to `Result`

`read(run_dir: Path, design: Design) -> Result`. This is the integration-critical piece: it must produce the exact same `Result` contract (§4 of the parent spec: "both engines fill exactly this shape") that `envelope.run()` produces, so `solit2 report correlation`, the Leaderboard, and every existing view treat an FDS result exactly like a Tier 1 one.

**How, concretely:** parses `<chid>_devc.csv` and `<chid>_hrr.csv` into one `StepRecord` per output timestep, each carrying a `StationSample` per `STATIONS` entry built from that timestep's device columns — both are the same frozen dataclasses (`solit2.engines.reduced.state`) Tier 1 already produces. Assembles these into a `RunTrace`, then calls `solit2.engines.reduced.criteria.evaluate(trace, hyd, cost, design)` **unchanged**. `hyd`/`cost` come from `solit2.engines.reduced.hydraulics.compute(design)` / `cost.compute(design)` — these are design properties (pump curve, quantities), not simulation output, identical regardless of which engine ran.

**What is deliberately NOT reused:** `fire.py`, `mist.py`, `ventilation.py`, `thermal.py`. Those are Tier 1's reduced-order *substitutes* for physics; FDS computes that physics directly, and `reader.py`'s job is to read what FDS actually computed, not to re-derive it.

A missing device column is fatal: `reader.read()` raises, matching the parent spec's error-handling rule ("missing-device failures are fatal"). The CLI catches it at its own boundary and reports it through the existing `_fail()` path — `{"error","field","fix"}` on stderr, exit 3 (engine) — exactly as `run --engine reduced` already handles an engine that cannot finish. `Result.meta["engine"] = "fds"`.

## 6. CLI additions

```
solit2 fds-deck design.json [--dx 0.45] [--tunnel orange_gate|san_pedro_de_anes] [--out case.fds]
solit2 fds-status runs/<sha>
solit2 run design.json --engine fds [--out result.json]   # extends the existing --engine choice
```

`fds-deck` calls `deck.generate()`, writes to `--out` or stdout. `fds-status` calls `runner.status()`, prints the state/progress.

`run --engine fds` calls `deck.generate()` → `runner.preflight()` (fails loudly with the same `{"error","field","fix"}` shape as every other CLI error if not ready) → `runner.run()` → polls `runner.status()` until the run leaves the `running` state → `reader.read()` → same stdout/`--out`/history-append behaviour `run --engine reduced` already has. The polling loop is what makes this command block; `runner.run()` itself stays non-blocking so the Verify view can drive the same functions without freezing. This command legitimately takes hours — the accepted cost of invoking it, not a bug — and its `--help` says so.

## 7. Verify view

Replaces the current stub in place. Four sections, matching spec §10's own description:
- **Pre-flight** — calls `runner.preflight()`, shows each check pass/fail. Today this will show "fds not found" — real information, not a fake "not built yet" message, and not a fake success either.
- **Deck** — generates and displays/downloads the `.fds` text for the current session design. Works today, no FDS install needed.
- **Run / progress** — only enabled once pre-flight passes; kicks off `runner.run()`, polls `runner.status()`.
- **Tier 1 vs Tier 2 table** — once both results exist, reuses `solit2.reports.correlation.render()` (already built for the Reports view) rather than a third table implementation.

## 8. Golden fixtures

The parent spec names "OG baseline" and "SPdA c3" as the two golden-deck tests. Neither exists on disk: `designs/` was never created (confirmed — the optimisation loop in `CLAUDE.md` §12 has never been run), and `validation/anchors/` has only c4, c5, c6 (c1–c3 are APPLUS/Ultrafog tests whose source report was never the target, per the DBR's own framing — see memory `mistelix-orange-gate-bid`).

Resolution: create `designs/og-dbr-rev0.json` now, from the real Orange Gate DBR data already used elsewhere in this repo (twin-bore, 4240/4260 m, single-mode fine nozzle, K=4.1, 50 bar, 3×30 m zones) — this is a real, useful artifact independent of Tier 2 (it is what §12's loop is supposed to start from, and it currently doesn't exist). Golden test 2 uses the existing `examples/designs/solit2-test-protocol.json` (the real SOLIT² Annex 7 mock-up design), named accurately as the test-tunnel fixture rather than as a nonexistent "c3".

## 9. Testing strategy

Everything below runs without a live FDS install:
- `deck.py`: golden-file tests — generate from `designs/og-dbr-rev0.json` and `examples/designs/solit2-test-protocol.json`, snapshot-compare the `.fds` text.
- `runner.py`: pre-flight checks tested via `monkeypatch` on `shutil.which`/`os.environ`/`shutil.disk_usage` — every pass/fail branch independently reachable.
- `reader.py`: parses `tests/fixtures/fds/sample_devc.csv`/`sample_hrr.csv` — a synthetic fixture in FDS's real output column shape, not a captured live run — into a `Result`, asserted against the same criteria-evaluation expectations Tier 1's own tests use.
- CLI: `fds-deck`/`fds-status` subprocess tests matching the existing `test_cli.py` pattern; `run --engine fds` tested against the synthetic fixture via a monkeypatched `runner.run()`/`status()`.
- Verify view: `AppTest`, matching the existing view-test pattern — pre-flight section renders and reports "not ready" honestly (no live FDS in CI either).

## 10. Out of scope this pass

- Live FDS execution and end-to-end output-shape verification — first live smoke test happens when real FDS access exists (local install or `SOLIT2_FDS_HOST`).
- The calibration-refit trigger ("Tier 2 vs Tier 1 disagreement beyond §9 tolerance → new anchor, refit, re-rank", parent spec §12 step 4) is a workflow a human/Claude carries out using the tool, not new code — no module implements it.
- Remote execution transport detail (what `SOLIT2_FDS_HOST` actually is — SSH, a queued job submission, something else) is deferred to the implementation plan; `runner.py`'s interface (`preflight`/`run`/`status`) is written so that detail stays swappable.

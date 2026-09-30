# Mist visibility and activation timing — design

**Status:** draft 2026-09-30, for review. Two independent changes in one spec because they answer the
same question a tunnel authority asks of a mist system: *what does it do to what people can see, and
does it matter when it starts?*

- **A. Droplet extinction for visibility** — replace the visibility term the engine already has with
  one derived from droplet optics, and say plainly what it still does not model.
- **B. Activation-timing comparison** — run the same design started at detection and started at a
  time the user supplies, and put the two side by side.

Neither change adds a fitted constant, an acceptance limit, or a verdict.

## Why

Published tunnel work on water mist (a 2018 conference presentation on a road-tunnel study: 15
full-scale tests, then 36 CFD scenarios) reports two effects that bear directly on a design:

1. Water flooding the zone cuts visibility (droplets, and the spray de-stratifying the smoke layer),
   so early activation can worsen conditions for people leaving.
2. Whether the system starts at detection or several minutes later, when a crew arrives, changes the
   heat release control, the temperatures and the visibility, and so changes the trade.

This spec is motivated by that work only. It is not cited in any output, code or test (design spec
for the virtual test report: no content, figure or limit from a third party's report), and none of
its numbers is used.

**Correction to an earlier claim.** The engine is not soot-only for visibility. `sim.py:235` already
adds a mist term, `kappa_mist`. It is crude, and the gap is in how it is built, not in its absence.

### What the engine does today

`mist._curtain_transmissivity` returns `tau_mist = exp(-kappa_rad · L · 0.5)`, where
`kappa_rad = 1.5 · phi / D32` summed over nozzle modes (`phi` the suspended water volume fraction,
`D32` the Sauter mean). That is the *radiant* transmissivity between a fire and a target beside it,
so it carries a half-path factor (`CURTAIN_PATH_FRACTION`) and the radiative prefactor.

`sim._sample_stations` then derives the visibility term from it:

```
kappa_mist = (1 − tau_mist) / half_active_length        # sim.py, per metre, in-zone stations only
visibility = 8 / (8.7 · soot_gm3 + kappa_mist)          # tenability.visibility_m
```

Three things are wrong with that derivation:

| # | Problem | Effect |
|---|---|---|
| 1 | `1 − tau` is the linear form. Beer–Lambert gives `−ln(tau)`. They agree only when `tau → 1` | Understates extinction more as the curtain thickens (tau 0.02 → factor 3.9 low) |
| 2 | Uses the radiative prefactor 1.5 (extinction efficiency `Q = 1`). Visible light through drops much larger than its wavelength has `Q_ext ≈ 2` (geometric optics), i.e. prefactor 3.0 | Factor 2 low |
| 3 | Recovers a per-metre coefficient from a curtain built for a *target* beside the fire, so the half-path factor leaks into a path that runs along the tunnel | Coefficient is a function of an unrelated geometry choice |

Measured on the example spec (`examples/compliance/solit2-example.spec.json`), droplet contribution
alone, in the active zone:

| Test | `tau_mist` | κ now (1/m) | κ from droplet optics (1/m) | Visibility from mist alone, now → proposed |
|---|---|---|---|---|
| A | 0.435 | 0.0188 | 0.0556 (×2.9) | 424 m → 144 m |
| B | 0.021 | 0.0326 | 0.2566 (×7.9) | 245 m → 31 m |

These are the droplet term alone. They are **not reported figures**, and this section originally
overstated them as if they were (see the correction below).

**Correction, found while implementing A (#15).** The Annex 7 visibility stations (U45, D45, D100,
D215; section 6.4.5) all lie outside the 60 m active zone of the example designs, and the droplet term
applies only inside the zone. So on `examples/compliance/solit2-example.spec.json` the reported
minimum visibility is **unchanged** by A: test A 4.14 m and test B 5.6 m, before and after. The term
matters only where the zone is long enough to contain a visibility station (an active length of about
90 m or more). Two consequences:

1. The engine is optimistic about visibility in the flooded zone, but no reported number shows the
   flooded zone at all. The gap is one of *reporting*, not only of the extinction coefficient.
2. The de-stratification warning follows the same rule: it fires only when a reported visibility or dose
   station lies inside the zone. It does not fire on the example designs.

A follow-up, not part of A: an unjudged visibility reading inside the zone (at the fire, or at the zone
edge). Annex 7 places no sensor there, so it could be reported but never be a pass/fail criterion.

## A. Droplet extinction for visibility

### Change

1. `mist.py`: compute the droplet extinction once, per metre, in a form both consumers use.
   - New constant `VISIBLE_EXTINCTION_PREFACTOR = 3.0` beside `EXTINCTION_PREFACTOR = 1.5`, with a
     comment: `Q_ext = 2` for drops ≫ wavelength (van de Hulst), so `kappa = 3 · phi / D32`. This is
     physics, not a fit; it is not in `calibration.json` and no anchor constrains it.
   - `_curtain_transmissivity` keeps returning `tau_mist` unchanged (radiant, half path). A sibling
     `_visible_extinction(...)` returns `kappa_visible = Σ_modes 3 · phi_m / D32_m` from the same `phi`.
     Factor the shared `phi` computation out so the two cannot drift apart.
2. `state.MistEffect` gains `kappa_visible_per_m: float`; `MistEffect.none()` sets `0.0`.
3. `sim._sample_stations`: `kappa_mist = mist.kappa_visible_per_m`. Delete the `(1 − tau)/half_active`
   derivation. The in-zone test (`|x| ≤ half_active_length`) is unchanged.
4. `tenability.visibility_m` is unchanged: extinctions still add (soot + droplets), Jin's
   light-emitting-sign constant 8 still applies.
5. `envelope.ENGINE_VERSION` moves to `reduced-1.1.0`. Results change, and `meta.engine_version` is how a
   reader tells old from new. Rankings in `runs/history.jsonl` recorded before this change are not
   comparable to ones after; the changelog line says so.

### What it still does not model — stated in every result

The presentation's other visibility finding is that the spray *de-stratifies* the smoke layer: it mixes
soot down to breathing height. The engine holds a Newman stratification factor (`thermal.
stratification_factor`, 0.1 when stratified) that the spray never changes, so in the flooded zone soot at
breathing height is under-predicted whenever the layer would be stratified. That errs in the same
direction as the old droplet term: visibility and FED there may be worse than reported.

The slides give no numbers for it, and a mixing factor picked to look right is exactly the fitted barrier
term the accuracy roadmap says not to add. So this change does **not** add one. It adds a warning:

- When flow fraction > 0 at any step and the stratification factor at an in-zone visibility station is
  < 1, `Result.warnings` gains one line (deduplicated): *"mist de-stratification is not modelled;
  visibility and dose at breathing height inside the spray zone may be worse than reported."*
- The virtual test report already prints `Result.warnings` in its limitations section, so it appears
  there with no report change.

Settling the magnitude needs a Tier 2 case (an FDS run of a stratified fire with spray, reading soot
and visibility at breathing height inside and outside the zone) or consortium data. That is the next
step after this change, not part of it.

### Tests

New, in `tests/test_tenability.py` and `tests/test_sim.py`:

- `kappa_visible == 3 · phi / D32` for a hand-computed single-mode case; twice `kappa_rad` for the same
  `phi` (guards the prefactor).
- With no soot, in-zone visibility equals `8 / kappa_visible`.
- Visibility with mist ≤ visibility of the same fire with `flow_fraction = 0` at every in-zone station,
  and equal outside the zone.
- `MistEffect.none()` gives `kappa_visible_per_m == 0.0`; a design whose system never activates has
  visibility identical to before the change (regression).
- Thicker curtain → lower visibility, monotonically (the old linear form flattened out).
- The de-stratification warning appears for a stratified run with an active spray and is absent when the
  system never discharges.

Existing tests that assert the old `(1 − tau)` derivation are rewritten to the new relationship, not
deleted; the plan lists each one before touching it.

### Acceptance

- `uv run pytest -q` passes, `tests/test_independence.py` included.
- `uv run solit2 validate`: the anchor comparison list is identical before and after (no anchor measures
  visibility). Any change there is a bug in this change, not a result.
- On the example spec the reported minimum visibility is **unchanged** (see the correction above); the
  PR description records that, and a test with a zone long enough to contain a station shows the droplet
  term dimming it.

## B. Activation-timing comparison

### Change

A new command, `solit2 report activation-timing <design.json> --late-s <seconds> [--out <path.md>]`,
runs the design twice and prints the two runs side by side.

- **As designed.** The design exactly as declared: activation at detection plus `zones.activation_delay_s`,
  or at `zones.manual_activation_s` if the design already pins one. The label says which.
- **Late.** The same design with `zones.manual_activation_s = late_s`.
- **Free burn** (reference row only): `Result.peaks["hrr_free_burn_mw"]` from the as-designed run. It is
  the engine's own free-burn HRR, not a third run.

`--late-s` is **required and has no default.** Annex 7 leaves activation conditions to the authority, and
the accuracy roadmap's rule is that the tool asks rather than chooses. The help text says the value is set
by the fire strategy or the authority having jurisdiction (for example when a response crew can be on site).
The output states: *"Late activation time: N s, supplied by the user. The tool does not choose it."*

### Output

Markdown, like `report test-plan` and `report compliance`, through the existing `_emit_report`.

1. Header: design name, design SHA, the two timetables (detection, activation, full pressure) for each
   strategy, and the supplied late time.
2. Comparison table, one row per quantity, columns *As designed*, *Late*, *Late − as designed*, all read
   from `Result`:
   - `peaks.hrr_mw`, `peaks.hrr_free_burn_mw`, `peaks.ceiling_temp_c`, `peaks.lining_temp_c`
   - `events.backlayering.max_length_m`
   - the water flow at full pressure and the total volume discharged (from `hydraulics`)
3. Criteria table: each of the nine Annex 7 criteria per strategy — value, limit from the design's own `ahj`
   block, and ✓ / ✗ / **limit not set** — via the same `labels`/`Criterion.status` logic as the compliance
   and virtual-test reports.
4. Facts, and only facts: a sentence for each criterion whose status differs between the strategies
   (*"min visibility: met as designed, not met when started late"*), or *"No criterion changes status."*
   There is **no** "better", "recommended" or ranking. Which strategy suits a tunnel is the authority's
   judgement; the tool shows the consequence of each.
5. Footer: *"Prediction, not a measurement"*, the warnings from both runs, and the calibration note, as in
   the other reports.

If `late_s` is not after the as-designed activation time, the command still runs and the header adds:
*"The supplied time is not later than the as-designed activation ({t} s); the two runs are the same or
reversed."* If `late_s` exceeds the run length (`duration_min · 60`) the command exits with
`EXIT_BAD_INPUT` and names the limit.

### Structure

- `solit2/reports/activation_timing.py` (new, no names of any product, project or vendor):
  - `strategies(design: Design, late_s: float) -> dict[str, Design]` — pure, returns
    `{"as_designed": design, "late": design.model_copy(...)}` with `zones.manual_activation_s` replaced.
  - `render(late_s: float, designs: dict[str, Design], results: dict[str, Result]) -> str`.
- `solit2/cli.py`: `_cmd_report_activation_timing`, following `_cmd_report_correlation`: load the design,
  build the strategies, `envelope.run` each, hand the results to a pure `render`. It does not write to
  `runs/history.jsonl`; a comparison is not a candidate design.
- No engine change. `sim.py:161-163` already honours `manual_activation_s`.
- `CLAUDE.md`, step 2 table: one row — *a visibility or tenability criterion fails in the flooded zone* →
  *run the activation-timing comparison before changing the layout*; *not this* → *adding heads*.

### Tests

New, `tests/test_report_activation_timing.py`:

- `strategies` changes only `zones.manual_activation_s`, and leaves the input design untouched (SHA of the
  original unchanged).
- The late run's `events.t_activate_s == late_s` and its full pressure time is `late_s + pump_ramp_s`.
- Header states the late time as user-supplied; `--late-s` is required (argparse exits nonzero without it).
- A criterion whose status differs between the runs produces the fact sentence; when none differ, the "No
  criterion changes status" sentence appears.
- An unset limit reads **limit not set** beside its value in both columns; no limit appears that is not in
  the design's `ahj`.
- The output contains none of *better*, *worse*, *recommend*, *optimal* (the tool states consequences, not
  preferences).
- `late_s` above the run length exits with the bad-input code; `late_s` not after the as-designed time
  produces the warning line.
- The independence scan passes with the new module.

### Acceptance

- `uv run solit2 report activation-timing examples/designs/road-tunnel-twin-bore.json --late-s 420` prints a
  comparison whose late run activates at 420 s.
- `uv run pytest -q` passes.

## Order and dependencies

- **A after PR 9 (`fix/cooling-location`) is settled.** Both edit `mist.py` (the curtain and the shared
  `phi`), and PR 9 adds `chi_downstream`. Doing A first means resolving conflicts in the same functions
  twice.
- **B is independent** of A and of PR 9, and can go first. When A lands, B's comparison automatically
  shows the corrected visibility, since it reads `Result`.
- The virtual test report (PR 13) needs no change for either. A later, optional follow-up could add an
  *Activation timing* section to it once `--late-s` has a home in the compliance spec; that home would be an
  authority-set field, consistent with the rule that limits and conditions come from the authority.

## Not in this spec

- A de-stratification model (needs Tier 2 data first — see A).
- Egress and firefighter-speed models, and a space–time visibility map.
- A default or preset for the late activation time.
- Any use of the presentation's HRR curves, fire scenarios or numbers.
- Refitting `calibration.json` (nothing here is fitted).

## Open decisions

1. **Order.** B first (independent, small), then A once PR 9's fate is decided — or A first, accepting the
   `mist.py` conflicts. *Recommended: B first.*
2. **History.** After A, should `solit2 history` hide or flag runs recorded under `reduced-1.0.0`?
   *Recommended: flag only; deleting history is not this change's job.*
3. **Where the late time lives.** Command-line flag now. If an authority's crew-arrival time belongs in the
   `ahj` block, that is a schema change to decide separately.

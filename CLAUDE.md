# Driving the optimisation loop

This file is for whoever — human or agent — sits down to turn a baseline design into a
defensible one. It is the loop's operating manual: what to run, what to read, which knob to
turn next and why, and when to stop.

Read [INDEPENDENCE.md](INDEPENDENCE.md) first. The rules there are not style; they decide what
this loop is allowed to change.

---

## Before the loop can mean anything: declare the limits

Run the baseline today and it scores 8.24 with every gate passed. That number is close to
meaningless, and the tool says so itself:

```
criteria_unset: hrr_below_tvs_design_mw, max_air_temp_c, max_heat_flux_kwm2,
                min_visibility_m, max_fed, max_co_ppm,
                structure_exposure_length_m, structure_exposure_duration_s
```

Eight of the nine Annex 7 criteria have no limit to be judged against. Only `target_ignited`
— the one absolute rule Annex 7 states outright — is live. So `score.components.margin`
reads **1.0**, a perfect score, off a single boolean. Margin is 30% of the total. Optimising
against that is optimising against nothing.

**The loop starts when the `ahj` block is filled in**, from the project's own authority —
the tender, the fire strategy, the AHJ's risk analysis. Not from this tool, not from a
vendor's report, and not from the engineer running the loop. That is INDEPENDENCE rule 2, and
it is the difference between evidence and self-assessment.

```json
"ahj": {
  "tvs_design_fire_mw": null,
  "max_air_temp_c": null,
  "max_heat_flux_kwm2": null,
  "min_visibility_m": null,
  "max_fed": null,
  "max_co_ppm": null,
  "max_structure_exposure_length_m": null,
  "max_structure_exposure_duration_s": null
}
```

Every field left `null` is reported `unset` and listed in `score.criteria_unset`, so a design
can never pass by nobody having asked anything of it.

---

## The loop

### 1. Run the baseline and read four things

```bash
uv run solit2 run designs/og-dbr-rev0.json
```

That path is this installation's own baseline, in `designs/` — the user's project space, which
neither independence scan touches by design. Project-named files are fine there and nowhere
else; do not "tidy" one into `solit2/` or `examples/`.

From the result JSON, in this order:

| Read | Why it comes first |
|---|---|
| `score.gates_failed` | A non-empty list zeroes the total. Nothing else matters until it is empty. |
| `score.criteria_unset` | Anything listed here is not being judged. If it is long, go back and fill in `ahj`. |
| `warnings` | Placeholder data in use, breached constraints, thin critical-velocity margin. |
| `score.components` | `water`, `margin`, `cost`, `structural` — which one is actually costing you points. |

### 2. Change ONE parameter group per iteration, with a physical reason

The discipline that makes the loop worth running: never change two things at once, and never
change anything without being able to say what physically improves. Record the reason in the
design's `meta.notes` — the next reader needs to know why, not just what.

| Symptom | Reach for | Not this |
|---|---|---|
| A tenability criterion fails downstream | Lower the mounting height, or tighten `zones.section_length_m` so the active length concentrates | More heads — that buys flow before it buys coverage |
| `target_ignited` is true | More sections simultaneous, so the bracketing covers the target | Raising pressure; the target ignites on radiation, not on flow |
| `power_kw` near the declared cap | Drop `nozzles.pressure_bar` inside its band — flow scales as √P, power as Q·ΔP | Removing heads, which opens coverage gaps |
| `density_mm_min` above a declared limit | Fewer heads per zone, or a longer section | Nothing — this one is a real trade against coverage |
| `cost` component low | Longer `section_length_m` (fewer zones, fewer valves) | Cheaper pipe; the model prices quantities, not procurement |

**This project's nozzle is single-mode.** Advice that turns a coarse/ballistic fraction does
not apply here — there is one mode, and its knobs are `k_factor_lpm_bar05`, `pressure_bar`,
`smd_um` and the mounting geometry. See the memory note on that standing decision before
proposing a bimodal head.

### 3. Rank what you have

```bash
uv run solit2 history --top 5 --passing
```

Every `run` appends to `runs/history.jsonl` unless you pass `--no-history`. Around twenty
iterations is usually where the ranking stops moving.

### 4. Verify the top designs against CFD (Tier 2)

```bash
uv run solit2 fds-deck designs/<candidate>.json --out runs/<candidate>.fds
uv run solit2 run designs/<candidate>.json --engine fds --out runs/<candidate>-fds.json
uv run solit2 report correlation --test runs/<candidate>-fds.json --site runs/<candidate>.json
```

**This needs an FDS binary and none is installed.** `run --engine fds` will refuse with a
pre-flight failure naming what is missing, which is the honest answer rather than a fake run.
`fds-deck` works today and produces a deck you can run elsewhere.

When Tier 1 and Tier 2 disagree by more than the tolerances in the design spec's §9, the
disagreement is the finding — do not quietly prefer the tier you like. It means a new anchor,
a refit, and a re-rank.

### 5. Before the fire test

```bash
uv run solit2 report test-plan designs/<chosen>.json --out reports/test-plan.md
```

That markdown is the test inputs and the predicted outcomes, in one document, for the
full-scale test that turns this from extrapolation into evidence.

---

## What the score is actually made of

```
total = 10 × (0.30·water + 0.30·margin + 0.20·cost + 0.20·structural) − penalties
```

- **water** — `score.BASELINE_FLOW_LPM` over this design's flow, so less water scores higher.
  That constant is a fixed normalisation inherited from the worked example: it sets the scale of
  the score, never whether a design passes.
- **margin** — the mean of the hard criteria's margins, taken over the criteria that are
  actually set. Unset ones are **excluded from the average**, not counted as zero — an absence
  is not a thin pass. Which is exactly why a design with one live criterion and eight unset ones
  scores `margin: 1.0`: the average is over a single passing boolean. Filling in `ahj` is what
  makes this component mean something.
- **cost** — the inverse of the cost index against the baseline.
- **structural** — how far the peak lining temperature sits below 1350 °C.

A failed hard gate sets the total to **0** and everything is still reported. Penalties deduct
but never zero: only a SOLIT² criterion can do that. A user's own declared constraint being
breached is a penalty and a warning — never a gate. That separation is INDEPENDENCE rule 2 and
the loop must not blur it.

---

## Reading a result honestly

The engine is calibrated against reference cases c4–c6, which used a different manufacturer's
nozzle and are weighted 0.5 in the fit. **No reference case uses the head this project is
assessing.** Every number the loop produces for it is an extrapolation until a full-scale test
exists, and `meta.calibration_note` says so in every result.

Two habits that keep the loop honest:

- Run `uv run solit2 validate` when a result surprises you. It reports how far the engine lands
  from each reference case, and a fitted calibration is not a validated one.
- Treat a suppressed HRR far below the design target, or a ceiling temperature that looks too
  cool, as a reason to check the engine rather than as a win.

---

## What this loop may never do

- Write an acceptance limit into `ahj` that no authority set.
- Move project or product data into `solit2/` or `examples/`. Designs live in `designs/`.
- Present `gates_passed: true` as approval when `criteria_unset` is non-empty.
- Prefer a tier because its answer is better.

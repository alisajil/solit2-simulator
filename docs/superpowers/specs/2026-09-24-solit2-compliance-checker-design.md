# SOLIT² compliance checker — design

**Status:** approved in brainstorming, 2026-09-24. Sub-project A of the digital-twin gap programme below.

## Why

The goal is a full-scale fire test that complies with the SOLIT² Engineering Guidance in every
clause, and a software twin that runs the same test virtually and then meets the measured one.
Software cannot make a physical test compliant; the laboratory's test does that. What software
can do is **prove, clause by clause, that the planned test and the installation it is meant to
qualify satisfy SOLIT²** — and say exactly what is still missing. "100 % compliant" then stops
being a claim and becomes a count anyone can audit.

Today the code carries about 35 SOLIT² requirements as cited constants
(`solit2/reports/guidance.py`) and writes them into a test protocol (`solit2/reports/test_plan.py`),
but nothing returns a pass or fail per clause.

## The gap programme (all gaps, as tracked tasks)

Numbers are the audit's gap numbers (2026-09-23/24).

| Sub-project | Gaps | Tasks |
|---|---|---|
| **A. Compliance checker** — this spec | 9, 15, part of 12 | A1 verdicts and findings · A2 SOLIT² rule registry · A3 test-spec schema · A4 tender rule loader · A5 transfer rules · A6 checker and headline · A7 Compliance wizard step · A8 `report compliance` · A9 Orange Gate spec, test design and tender rules in `designs/` |
| **B. Measured-data loop** | 11, 12, 13, 14 | B1 import lab files mapped to Table 5 IDs · B2 locked blind prediction (design SHA + calibration version, frozen before the test) · B3 measured-vs-predicted overlay in the Fire test step · B4 post-test anchor + refit + correlation CFD to the installation · B5 test-series scatter bands |
| **C. Physics fidelity** | 3, 4, 6, 7, 8, then 1 | C1 jet-fan ventilation that throttles (Tier 1 and FDS) · C2 ignition pans on the upstream side · C3 spray deviation in cross-flow at 1/3/5 m/s · C4 one tilt convention across both tiers, wall mounting · C5 backlayer front transient · C6 gas temperature / ceiling multiplier — blocked on E1 |
| **D. CFD credibility** | 2, 5 | D1 grid study · D2 E_COEFFICIENT sweep · D3 run past the peak — all need uninterrupted mains power · D4 decide prescribed burner vs pyrolysis |
| **E. External inputs** (people, not code) | 10, 15, 9 | E1 nozzle lab data TEST-001/003/018 (Mistelix lab) · E2 AHJ acceptance limits (Authority via L&T) · E3 booked test tunnel geometry (test laboratory) · E4 LHDS detection and pump-start times (L&T) |

Order: A → B → C, with D's compute whenever the machine can stay on mains power. E runs in
parallel and feeds A (evidence), C6 and B.

## Design

### Inputs: the designs and an evidence file

SOLIT² judges two different things, so the checker takes three inputs:

- **Test designs** — the system as it will be tested, in the booked test tunnel: one per fire
  class, because Table 4 requires Class A and Class B tests and one design cannot carry both
  fires. Judged by the test clauses (Annex 7 §3–§8, main document §3.6.2). Class A is required;
  if the Class B design is absent, every Class B design clause is Needs evidence.
- **Installation design** — the same system in the real tunnel. Judged by the **transfer** clauses
  against the test design of the same fire class as its design fire (Annex 7 §3.2–§3.4, Annex 3
  §3.3, main document §3.6.2's standoff rule).
- **Test-spec file** — the laboratory's facts, each with its evidence, plus any deviation the
  authority accepted. It names the designs and, optionally, a project rule file.

```json
{
  "spec_version": 1,
  "name": "short name of the planned test",
  "test_designs": {"A": "path/to/test-design-class-a.json",
                   "B": "path/to/test-design-class-b.json"},
  "installation_design": "path/to/installation-design.json",
  "project_rules": "path/to/project.rules.json",
  "facts": {
    "pallet_moisture_pct": {"value": 14.0,
                            "evidence": {"document": "lab pallet certificate", "locator": "p. 2"}}
  },
  "deviations": {
    "annex7.3_6.free_area": {"accepted_by": "authority name", "document": "letter ref",
                             "locator": "§2", "reason": "why the authority accepts it"}
  }
}
```

`facts` is a fixed set of typed, optional fields (`solit2/compliance/spec.py`), not a free
dictionary: the schema is `extra="forbid"`, so a misspelt fact is refused rather than silently
leaving its clause unjudged. Each fact is `{value, evidence: {document, locator}}`; a fact without
evidence is invalid. Paths resolve relative to the spec file.

The fact set covers every lab-side clause in the catalogue: pallet dimensions, mass and moisture;
frame coverage; tarpaulin fitted; ignition pan count, size and petrol volume; Class B free-burn
duration, ignition and trigger times; measured test velocities; flow deviation; per-instrument
range and accuracy; sampling interval; the main document's measurement schedule; HRR method and
delay; calibration fires; the planned test list (class, cover, velocity); number of test series;
droplet-distribution report; tested spray-deviation velocities; the authority's limits document;
LHDS detection time; §5.2.8 activation option.

### Verdicts

| Verdict | Meaning |
|---|---|
| Complies | the requirement is met, from the design or from evidenced facts |
| Fails | it is not met |
| Deviation accepted | not met, but an authority's acceptance is on record — only where SOLIT² allows the authority to accept it (Annex 7 §3.6); elsewhere a deviation entry is refused |
| Needs evidence | the fact that decides it has not been supplied |
| Not applicable | the clause does not apply (e.g. a covered-mock-up clause judged on the Class B pool test) |

**Headline:** "N of M applicable clauses comply (k by accepted deviation)", where M excludes Not
applicable. **100 % is shown only when there are zero Fails and zero Needs evidence.** Needs
evidence never rounds up.

A finding records: rule id, clause reference, the requirement quoted from the source, value found,
value required, basis (design field, fact, or Tier 1 prediction), evidence, verdict.

### Components

| File | Responsibility |
|---|---|
| `solit2/compliance/verdict.py` | `Verdict` enum, frozen `Finding` dataclass |
| `solit2/compliance/rules.py` | the SOLIT² rule registry. A `Rule` is frozen: id, source clause, quoted requirement, applies-to predicate, kind (design / lab / transfer), check function. Every number comes from `guidance.py`, which stays the single source |
| `solit2/compliance/spec.py` | the strict test-spec schema, and loading the designs it names |
| `solit2/compliance/project_rules.py` | loads a declarative project rule file: `{id, source, requirement, quantity, comparator, limit}`, where `quantity` must be one of a fixed allowlist and `comparator` one of `<=, <, >=, >, ==` |
| `solit2/compliance/check.py` | runs Tier 1 on every design, evaluates every rule, returns a `ComplianceReport` (findings, counts, headline, blockers) |
| `app/views/compliance.py` | the new wizard step |
| `solit2/reports/compliance.py` | the markdown report |

Everything under `solit2/` and `app/` is SOLIT²-only: INDEPENDENCE rules 1 and 2 hold and
`tests/test_independence.py` must pass. Project files live in `designs/`.

### Rule catalogue (about 65 rules)

Tags: **D** computed from a design, **L** lab evidence, **T** transfer, **P** project rule file.

| Group | Source | Rules | Kind |
|---|---|---|---|
| Test tunnel | Annex 7 §3.6 + main §3.6.2, stricter of each pair (`STRICTER_OF`) | free area ≥ 40 m²; height ≥ 5.0 m (main, stricter than 4.5); width ≥ 7.0 m; length ≥ 400 m | D; a shortfall against an Annex 7-only figure may be Deviation accepted, the main document's may not |
| Class A load | Annex 7 §5.2.1–§5.2.6 | ≥ 150 MW potential; ≥ 400 pallets and 110–140 GJ; mock-up ≥ 4.0 × 2.4 × 10.0 m with ≥ 2.5 m fuel; wall clearance ≤ 1.5 m; target at D10 (5 m standoff) | D |
| | | pallet 800 × 1200 × 144 mm, 22–25 kg, moisture ≤ 18 %; frames ≤ 10 % of fuel faces; tarpaulin on the required tests; ≥ 2 ignition pans 600 × 150 × 50 mm, 2 L petrol each | L |
| Class B load | Annex 7 §5.3 | ≥ 50 MW; pool ≥ 2.5 × 6.5 m, each pool ≥ 4 m², ≤ 0.5 m above road | D |
| | | ≥ 7 min unsuppressed burn; ignition within 60 s; trigger within 120 s | L |
| Ventilation | Annex 7 §5.2.7, §5.3.6 | tests at 1.5 and 3.0 m/s, measured at U45 (Class A) / U20 (Class B) | D (planned), L (measured) |
| Activation | Annex 7 §5.2.8 | option A ≥ 60 s after ignition and delayed relative to detection; ≥ 30 min discharge after activation; activated length ≥ 3 × mock-up length; option B is blank in Annex 7 | D; option B → Needs evidence |
| System | Annex 7 §4, §6.4.6–§6.4.7 | nozzle pressure spread ≤ 10 % first to last (hydraulics); flow within ± 5 %; pressure at the hydraulically last nozzle | D, L |
| Instruments | Annex 7 §6.4, Table 5, Figure 16; main §3.6.2 | Table 5 station layout; range and accuracy for the 9 `INSTRUMENT_SPEC` types; sampling ≤ 2 s; the 8-item `MAIN_MEASUREMENT_SCHEDULE`; HRR by oxygen consumption, delay ≤ 60 s; calibration fires 5 and 30 MW (§6.2) | layout D; rest L |
| Programme | Annex 7 §5.4 Table 4; main §3.6.2 | the four required tests planned; ≥ 3 test series | L |
| Protocol | Annex 7 §8.2 | the generated protocol contains all 12 `PROTOCOL_CONTENTS` (existing `CONTENT_MARKERS` check) | D |
| Nozzle | main §3.6.2 | the exact nozzle, with its measured droplet distribution; spray deviation defined at 1, 3 and 5 m/s | L |
| Acceptance | Annex 7 §7 | target not ignited (Tier 1 prediction until B supplies measurement); every other limit from a cited authority document | D, L |
| **Transfer** | Annex 7 §3.2–§3.4, Annex 3 §3.3, main §3.6.2 | installation detection-to-full-pressure no slower than the test's; each of the ten `TEST_DERIVED_PARAMETERS` inside the tested range (a single tested value means equality); installation standoff ≤ tested standoff × 1.20; installation velocity range inside the tested velocities; installation fire size at activation ≤ tested; anything outside the envelope is extrapolation, which §3.4 does not allow CFD to supply | T |
| **Project** | tender specification R2, in `designs/` | reduced HRR ≤ 50 MW (§6); pump power ≤ 650 kW (§5a); droplet size < 100 µm with the measure declared (§5d); test velocity 3.88–5.08 m/s (§8); correlation CFD supplied (§9) | P |

Transfer uses Tier 1 predictions where a quantity has not been measured, and the finding's basis
says "predicted". Sub-project B replaces predictions with measurements.

Expected on first run: with a test planned at SOLIT²'s 1.5 and 3.0 m/s, the ventilation transfer
rule **fails** for an installation at 3.88–5.08 m/s. That is the checker working.

### Data flow

1. Load the spec; resolve and load the test designs, the installation design and the optional
   project rules.
2. Run Tier 1 once on each design (seconds).
3. Evaluate every rule against (test designs, installation design, facts, deviations, results).
4. Build findings, counts, headline and the blockers list (every Fails and Needs evidence).
5. Render: the wizard step, the markdown report, and the lab checklist.

Every report carries every design's SHA and the calibration version, so a matrix traces to exact
inputs.

### UI: the Compliance step

The wizard becomes six steps: Design → Result → Fire test → CFD verify → **Compliance** → Reports.

- Pick a spec file from `designs/`.
- Headline, verdict counts, then the **blockers** list: the to-do list.
- The matrix, grouped as in the catalogue, filterable by verdict; each row expands to the quoted
  requirement, found and required values, evidence, and for a deviation, who accepted it.
- **What the lab must supply:** every open evidence item as a checklist to download (markdown).
- Evidence is edited in the JSON file, not in the UI: the file under version control is the record.

### Report

`uv run solit2 report compliance designs/<spec>.json --out reports/compliance.md` — the same
headline, matrix and checklist, for the main contractor and the authority.

### Errors

| Condition | Behaviour |
|---|---|
| spec, design or rule file missing | refused, naming the field and path |
| unknown fact or field | refused by the strict schema |
| fact without evidence | refused |
| deviation entry on a clause SOLIT² does not let the authority waive | refused |
| project rule naming a quantity outside the allowlist | refused |
| a rule raising | the check stops and names the rule — never a silent pass |

## Testing

- **Each rule, both ways,** at the clause's own boundary: e.g. 40.0 m² complies and 39.9 fails;
  height judged against 5.0, not 4.5; 18.1 % moisture fails.
- **Evidence gating:** a lab-side clause with no fact is Needs evidence, never Complies; a
  deviation without acceptance on record is Fails; a deviation on a non-waivable clause is refused.
- **Registry completeness:** every constant in `guidance.py` is read by at least one rule; every
  rule cites a clause and quotes a requirement; rule ids are unique.
- **Headline:** 100 % only with zero Fails and zero Needs evidence.
- **Independence:** `tests/test_independence.py` passes.
- **End to end:** a neutral example spec under `examples/` gives a stable headline; the project
  spec in `designs/` shows the ventilation transfer rule failing for a 3.0 m/s test.
- **App:** a Streamlit AppTest on the Compliance step (headline, blockers, checklist download).

## Out of scope for A

- Physics fidelity of the virtual test — sub-project C.
- Importing measured data — sub-project B. A reads evidence *references*, not data files.
- Filling in any authority limit or laboratory fact. Anything nobody has supplied stays Needs
  evidence; the project spec starts mostly amber, which is the honest starting point.

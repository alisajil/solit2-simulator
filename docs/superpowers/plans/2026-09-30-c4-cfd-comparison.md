# c4 CFD deck and comparison plan

**Anchor:** c4 — SOLIT² Annex 2 §6.1, Class A with tarpaulin cover, 150 MW potential,
2.25 m/s, FFFS started by hand at 420 s (`validation/anchors/c4_solit2_class_a_cover.json`).

**Decks:** `decks/c4/mist/` and `decks/c4/free-burn/`, each a ready run directory
(`deck.fds` + `design.json`), generated from the anchor exactly as `load_anchors` builds it.

**Question this answers:** does FDS, given the same inputs Tier 1 gets, land inside c4's
published tolerances — and where it does not, is it Tier 1 or Tier 2 that sits closer to the
measurement? It is **not** evidence about the Mistelix head (see §5).

---

## 1. What is in the decks

| | mist | free-burn |
|---|---|---|
| CHID | `6f4c7007aaec` | `6f4c7007aaec_free` |
| Mesh | 10 × `IJK=100,17,13`, dx 0.6 m, x ∈ [−360, 240] m (≈221 k cells) | same |
| `T_END` | 2520 s (42 min, `zones.duration_min`) | same |
| Ambient | 20 °C | same |
| Fire | `hgv_150mw`, 16 segment ramps from the free-burn curve, incubation 243 s, `E_COEFFICIENT=0.4` | same, no water |
| Activation | `DEVC 'MANUAL' QUANTITY='TIME' SETPOINT=420.0` → `CTRL 'ACT'`; pump ramp 30 s | same controls, no heads |
| Nozzle | reference-nozzle **placeholder**: 61 heads, 25.31 L/min, D32 90 µm, 70 m/s, 45° cone | — |
| Stations | U15 (TC + HF), D15 (TC + HF), D100, full Annex 7 Fig. 16 trees, 36 ceiling TCs | same |

Regenerate with (idempotent, byte-identical):

```bash
uv run python - <<'EOF'
from pathlib import Path
from solit2.engines.fds import deck
from solit2.engines.fds.exec_run import DESIGN_NAME
from validation.compare import load_anchors
(a,) = load_anchors(("c4",))
for name, sup in (("mist", True), ("free-burn", False)):
    d = Path("decks/c4") / name; d.mkdir(parents=True, exist_ok=True)
    (d / "deck.fds").write_text(deck.generate(a.design, suppression=sup))
    (d / DESIGN_NAME).write_text(a.design.model_dump_json(indent=2, by_alias=True))
EOF
```

### Fixed on the way: manual activation was ignored by the deck

`deck._detection` always opened the heads on the first linear-heat trip plus
`activation_delay_s`. It never read `zones.manual_activation_s`, which Tier 1 honours
(`sim._detect`). For c4, Tier 1's detector trips at **273 s**; the test opened at **420 s**. A
CFD run of the old deck would have wetted a fire 147 s smaller than the one tested — a
different test. The deck now opens the heads on a `TIME` device at the manual time and still
logs `DETECT`, so the reader reports both. Test:
`tests/test_fds_deck.py::test_a_manual_activation_opens_the_heads_at_that_clock_time_not_on_detection`.

This also affects every virtual-test-report fire test (`reports/twin.py` sets
`manual_activation_s`). Any FDS deck issued for those before this fix should be regenerated.

Not verified against an FDS binary (none installed): FDS accepts a `DEVC` as a `CTRL` input,
but the first real run must confirm `ACT` flips at 420 s in `<CHID>_ctrl.csv`.

---

## 2. Known structural gaps — read before reading any number

1. **The cover is not modelled.** The deck has no tarpaulin. In the test it shielded the fuel
   from direct spray; in FDS the water that reaches the fuel surface drives `E_COEFFICIENT`
   suppression directly. Expect FDS to over-suppress c4 relative to the test. c4 and c5 differ
   on cover, incubation, activation time and velocity; with no cover in the deck, the E sweep
   cannot separate the cover effect from the others. A thin inert roof over the fuel box is the
   obvious fix — a model decision, not made here.
2. **E is a fitted constant.** `fds-campaign` sweeps E on c4 and c5 by default. If E is picked
   on c4, then c4's peak HRR is in-sample and proves nothing. See §4 for the hold-out.
3. **Placeholder nozzle.** Same circularity as Tier 1 (`CLAUDE.md`, "Reading a result
   honestly"). The comparison tests FDS + placeholder head against the SOLIT² system, whose
   real nozzle is unpublished.
4. **Prescribed fire.** The free-burn curve is an input. FDS decides only how much of it the
   water removes; fire spread to the target is judged from the target gauge, not burned.

---

## 3. Runs

On the dedicated CFD server (`docs/cloud-compute.md`), never the FareOS cluster.

| # | Run | Purpose | Command |
|---|---|---|---|
| R0 | 8-min smoke test (covers 420 s activation) | deck parses, meshes OK, `ACT` flips at 420 s in `_ctrl.csv` | `uv run solit2 fds-deck decks/c4/mist/design.json --minutes 8 --out runs/c4-smoke/deck.fds`, copy `design.json` beside it, `fds-exec runs/c4-smoke` |
| R1 | c4 mist, full 2520 s, dx 0.6, E 0.4 | the comparison run | copy `decks/c4/mist` → `runs/c4/mist`, `uv run solit2 fds-fleet enqueue runs/c4/mist` |
| R2 | c4 free-burn, same | free-burn HRR the reader needs (`free_burn_dir`), and the suppression ratio | same, `runs/c4/free-burn` |
| R3 | E sweep on **c5 only**, E ∈ {0.1, 0.2, 0.4, 0.8} | pick E without looking at c4 | `uv run solit2 fds-calibrate-e --anchor c5 --e 0.1 0.2 0.4 0.8 --dx 0.6 --out runs/ecal-c5 --run`, then `--report` |
| R4 | c4 mist at the E chosen in R3 (if ≠ 0.4) | out-of-sample c4 prediction | regenerate with `e_coefficient=` |
| R5 | grid study dx 1.2 / 0.75 / 0.6, 600 s window after activation | GCI on peak HRR, ceiling T, D15 T | `solit2 fds-grid-study` |

Order: R0 → R1 + R2 in parallel → R3 → R4 → R5. R5 can run beside R3 if cores allow; the
campaign's own up-front rate estimate is the run-time figure to trust, not a guess here.

---

## 4. Comparison

Score each run against c4 with the anchor's own extractors and tolerances
(`validation.compare.EXTRACTORS`, `within`). `compare.check` refuses `engine != "reduced"`
today, so until it takes a run directory:

```python
from validation.compare import load_anchors, EXTRACTORS, within
from solit2.engines.fds import reader
(a,) = load_anchors(("c4",))
r = reader.read("runs/c4/mist", a.design, free_burn_dir="runs/c4/free-burn")
for q, measured in a.measured.items():
    m = EXTRACTORS[q](r)
    print(f"{q:22} {m!s:>10} {measured!s:>8} {within(measured, m, a.tolerances[q])}")
```

Dry-run that snippet on `tests/fixtures/fds/` output before R1 finishes, so a missing key
surfaces now rather than after a 42-minute simulation.

| Quantity | Measured | Tolerance | Tier 1 today | FDS R1 | FDS R4 |
|---|---|---|---|---|---|
| peak HRR | 30 MW | ±25 % | 27.3 ✓ | | |
| peak ceiling T | 830 °C | ±20 % | 524 ✗ (37 % low) | | |
| U15 T | 22 °C | ±15 K | 20 ✓ | | |
| D15 T | 75 °C | ±40 % | 60 ✓ | | |
| D100 T | 57 °C | ±40 % | 36.8 ✓ | | |
| D15 heat flux | 1.0 kW/m² | ×2 | 0.63 ✓ | | |
| backlayering at U15 | no | exact | no ✓ (see note) | | |
| target ignited | no | exact (inferred) | no ✓ | | |

Also record, not scored: `t_detect_s` / `t_activate_s` from `_ctrl.csv` (activate must read
420), HRR time-history overlay against Annex 2 Fig. 9, and the mist/free-burn HRR ratio.

**How to read the outcome**

- Tier 1's ceiling temperature is the known miss. If FDS lands inside 20 % there, that is the
  first independent signal on the single-cooling-fraction limit (`docs/accuracy-roadmap.md`).
  If FDS is also cold, suspect the placeholder nozzle or the missing cover before either model.
- Tier 1's backlayering pass is not evidence (water downstream credited to the plume). FDS has
  no such credit; an FDS backlayering result at U15 is the one to believe.
- Where Tier 1 and FDS disagree beyond the anchor tolerance, record the disagreement as the
  finding. Do not prefer the tier that lands closer to 30 MW. It triggers new anchor → refit →
  re-rank (`CLAUDE.md` step 4).
- R4 is the only out-of-sample HRR number. R1 is in-sample if E=0.4 was ever chosen by
  looking at c4.

---

## 5. What this never becomes

- Evidence about MTX-REV00/REV01P. That needs the Mistelix full-scale test (anchor c7).
- A reason to write a fitted E into `deck.E_COEFFICIENT`. The sweep reports; a person adopts.
- A tuned cover or barrier to make c4 pass. If the cover roof is added, it is added because
  the test had one, and its effect on c5 is checked in the same step.

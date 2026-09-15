# SOLIT² Simulator — Scope Analysis & Simulation-Engine Selection

Date: 2026-09-15
Status: analysis for decision (pre-spec)
Inputs:
- `Design Basis Report.pdf` — Ultrafog HP water-mist design brief for the Anakkampoyil–Kalladi–Meppadi twin-tube tunnel (Kerala, 8 735 m) + embedded APPLUS+TST full-scale test report (San Pedro de Anes, 2020, Tests 1–9, 30/50/100 MW)
- `SOLIT_EG_Annex2_EN_v2.1.pdf` — SOLIT² Engineering Guidance Annex 2, selected results of >30 full-scale tests (San Pedro de Anes, 2012, FOGTEC FFFS)
- Reference pattern — "Claude as aerospace engineer" talk: geometry system + simulation system, JSON contract, Claude iterates from the terminal, Streamlit/Plotly front end

> **Revision 2 (2026-09-15, later the same day) — target corrected.** The Ultrafog brief describes the *Kerala* tunnel and was supplied as a reference; the tunnel this system is bid for is the **Orange Gate – Marine Drive underground road tunnel, Mumbai** (MMRDA via L&T), with Mistelix's own bimodal **MSX-T-100** nozzle. Sections marked *(rev 1 — Kerala)* below are kept for the reference data they carry; §2.6 and §6 carry the corrected target. Sources added: Mistelix DBR `MSTX-OG-DBR-001 Rev 0`, L&T `HPWM-TECHNICAL SPEC_R2`, GA `EWCR-LNT-430-PD-102886_A1.3`, schematics `EWCR-LNT-460-PD-103750/103752`, alignment drawings.

Decisions already taken in brainstorm: goal = optimise a new design for the Kerala tunnel; all four parameter groups free (nozzle geometry, hydraulics, zone/activation, ventilation); objective = water demand + safety margin + cost proxy + structural protection, gated by the SOLIT² tenability criteria; stack = Python core, JSON CLI, Streamlit + 3D Plotly.

---

## 1. Problem statement

Produce a software test rig that stands in for a full-scale tunnel fire test with a high-pressure water-mist FFFS, so that:

1. a candidate nozzle/zone/hydraulic/ventilation design can be scored against the SOLIT²/APPLUS+TST pass-fail criteria in seconds (Claude's optimisation loop), and
2. the shortlisted designs can be verified with an engine that a fire-safety reviewer will accept as evidence (CFD, industry standard).

Both tiers must consume the **same design JSON** and emit the **same result JSON**, so Claude never has to learn two interfaces.

---

## 2. Data inventory — what the two reports give us

### 2.1 Test facility (both campaigns, same tunnel)

| Item | APPLUS+TST 2020 (Ultrafog) | SOLIT² 2012 (FOGTEC) |
|---|---|---|
| Tunnel | 600 m, 9.50 W × 8.12 H, 1 % grade, 2 % cross-fall | 600 m, 9.5 W × 8.20 H, 1 % grade |
| False ceiling | 5.17 m, pk 155–600, section 48 m² | 5.20 m over 450 m; walls narrowed to 7.50 m near fire |
| Ventilation | longitudinal, 6 jet fans × 45 kW, ≤ 6 m/s; ≥ 2.5 m/s target | longitudinal ≤ 6.5 m/s; semi-transverse 8 dampers ≈ 1 m², 80 / 120 m³/s |
| Fire position | pk 370, 2.4 m off right wall | fire zone U3–D5 |
| Instrumentation | 71 TC, 10 velocity, 3 HF, CO, O₂, CO₂, RH — stations U45…D170 | ≈ 160 sensors — stations U340…D215, HRR by O₂ consumption |

### 2.2 Fire loads

| Load | Pallets | Mass / energy | Potential HRR | Ignition |
|---|---|---|---|---|
| APPLUS 30 MW | 78 (13 × 2 × 3) | — | 30 MW | 2 trays × 2.5 L gasoline |
| APPLUS 50 MW | 128 (16 × 2 × 4) | — | 50 MW | idem |
| APPLUS 100 MW | 252 (18 × 2 × 7), 2.4 × 5.6 m, 3.99 m high | — | 100 MW | idem |
| SOLIT² Class A truck | 408 on 1.5 m or 0.2 m basement, ± PVC tarpaulin 10.5 × 7.5 m | ≈ 9 600 kg, ≈ 140 GJ | 150 MW | 3 pools × 0.15 m² × 2 L gasoline |
| SOLIT² Class B | 7 pools 2.5 × 1.6 × 0.4 m, 90 L diesel each | 630 L, 44.8 MJ/kg | 60 MW nominal (5 / 60 / 100 nominal; 160 real achieved) | 1 L gasoline / pool |
| Target object | — | one stack, same H × W as fire load | — | 5.0 m downstream |

### 2.3 FFFS as tested

| Item | APPLUS+TST (our nozzle) | SOLIT² |
|---|---|---|
| Nozzle | Ultrafog 202-260T-160-O, K = 4.2 lpm/bar⁰·⁵, 35° below horizontal, 200 mm off wall & ceiling; -X-52 variant 40°, 180 mm | FOGTEC, type not disclosed |
| Zone | U38 → D38, 76 m, 20 or 40 nozzles, single or both walls | 60 m installed |
| Pressure / flow | 62 / 66 / 56 bar → 661 / 682 / 1 257 lpm (Tests 3 / 6 / 9) | rpm-controlled diesel pump, 30 s ramp to full power |
| Activation | detection (ceiling TC > 60 °C) + 100 s design; Test 9 actual 3 min 21 s after detection | manual "Start BBA/FFFS" at 0:04–0:07 |
| Layout metric | per-nozzle K / spacing | l/m²/min (mm/min) or l/m³/min; "results only applicable to the same nozzle type" |

### 2.4 Measured outcomes usable as calibration anchors

| Case | u (m/s) | FFFS on | Peak HRR | Peak ceiling T (fire zone) | U15 T | D15 T | D100 T | HF D15 | HF U15 | Backlayering |
|---|---|---|---|---|---|---|---|---|---|---|
| APPLUS T9, 100 MW, 40 nozzles, 56 bar | ≥ 2.5, dropped < 1 at min 26 (wind) | 05:21 | growth ultrafast → medium | ≈ 650 °C avg | 12 °C at U35 | — | — | — | 0.27 kW/m² | yes, min 26–28 only |
| SOLIT² A, cover, 1.5 m basement | 2–2.5 | 0:07 | ≈ 30 MW (of 150) | ≈ 830 °C | ≈ 20 °C flat | 50–100 °C, spikes 200 °C at 5 m | 50–65 °C | ≈ 1.0 kW/m² | ≈ 1.0 kW/m² pre-activation, ≈ 0 after | none |
| SOLIT² A, no cover | 1–1.5 | 0:04 | ≈ 20 MW | ≈ 580 °C late | ≈ 20 °C flat | 50–60 °C | ≈ 50 °C | ≈ 0.45 kW/m² | ≈ 0 after activation | none |
| SOLIT² B, 60 MW, longitudinal | low | before peak | — | — | strong backlayering pre-activation, gone after | flames almost to D15 | — | — | — | yes → cleared |

Pass-fail limits (APPLUS+TST performance criteria, Ultrafog-defined): U35 ambient T ≤ 60 °C · HF U15 ≤ 5 kW/m² · HF U35 ≤ 2.5 kW/m² · visibility to light-emitting objects at U35 · FED ≤ 0.3. Design criteria add: no spread to a target 5 m downstream; fire-fighter access to 5 m upstream and 20 m downstream.

### 2.5 Reference design (Kerala — rev 1, superseded as target)

Twin tube, unidirectional, protected width ≈ 8.00 m, 8 735 m per tube, design fire 100 MW Class A, 60 min duty; baseline K 4.2 · 56 bar · 31.42 lpm · 4 m spacing · 32 m sections · 16 nozzles/section · 3 sections → 48 nozzles → 1 508.59 lpm · 15+1 pumps × 115 lpm · 118 m³ tank. **Cross-section height and area are not in the report** → JSON input with IRC SP 91 default (5.5 m clearance, ≈ 7.5 m crown), flagged as assumption.


### 2.6 Target design (Orange Gate, Mumbai) — rev 2

| Item | Value | Source |
|---|---|---|
| Tubes | 2, unidirectional; LHS 4 240 m (cut & cover 535 + bored 3 705), RHS 4 260 m (520 + 3 740) | Spec R2 §3 (GA rev A1.3 chainages differ — spec used) |
| Bored section | TBM segmental ring, **internal diameter 11.0 m**; pavement 2.125 m below centre (3 375 mm invert-to-pavement) → road width 10.15 m, crown 7.63 m above carriageway, free area ≈ 70 m², width at 5.5 m height 8.7 m | GA section 6 |
| Cut & cover | box 9.0 m clear width, vertical clearance 5.5 m, height above "varies" (assume 6.5 m [C]) | GA section 5 |
| Gradient | tunnel grades −1.5 … +0.3 %; ramps to 5 % outside | alignment sheets |
| Ventilation | longitudinal (TVS) **3.88–5.08 m/s** | Spec R2 §8 |
| Design fire | **150 MW**, controlled to **≤ 50 MW**; Class A and Class B; 3 zones simultaneous | Spec R2 §6 |
| Detection | L&T linear heat detection → RIO panel at every cross passage → section valves | Spec R2 §5.f |
| Pump house | Basement-2, Technical Building, CH 0+400–0+436; feeders 2 × 325 kW; N+1; 3-zone flow + 10 %; head + 10 % | Spec R2 §3, §5.a |
| Water | L&T schematic provisions 2 × 150 m³ for water mist | 460-PD-103750 |
| Mistelix design (DBR Rev 0) | MSX-T-100, K ≈ 4.1, 50 bar (45–60), 29 L/min; bimodal fine ≈ 100 µm SMD (60 %) + coarse 300–600 µm (40 %); 30 m zones, 2 rows, ≈ 25 heads/zone, 725 L/min/zone, 2.2 L/min·m²; 3 zones 2 175 → design 2 393 L/min (143.6 m³/h); 59.4 → 65 bar; ≈ 375 kW (cap 650); tank ≈ 145 m³ (60 min); DN150 SS316L looped cross-tube ring, DN65 zone headers; 283 zones, ≈ 7 100 heads | DBR §§1, 5–10 |
| Tender evidence route | full-scale test to SOLIT²/NFPA 502 (pre-bid, critical path) + **CFD correlating tested tunnel & TVS with Orange Gate & TVS** (post-award) | Spec R2 §8, §9; DBR §13 |
| Consequence for the simulator | two presets (San Pedro de Anes test tunnel, Orange Gate) run on one design JSON = the §9 correlation workflow; bimodal droplet physics is the load-bearing claim and has no test data yet → FDS tier is a tender deliverable, not an optional check | — |

Physics sanity at the target: critical velocity for the free-burning 150 MW fire in the 7.63 m bore ≈ 3.7 m/s — the TVS floor of 3.88 m/s clears it by only 5 %; a 100 µm drop released at 5.75 m into 5 m/s air lands ≈ 100 m downstream, a 450 µm drop launched at ≈ 100 m/s lands within metres — the DBR's fine/coarse argument in numbers, to be reproduced by the model.

---

## 3. Scope

### In scope (v1)
- Class A pallet-array / HGV fires up to 150 MW (t² growth, fuel-limited decay) **and Class B diesel pool fires** (tender §6) — rev 2
- Longitudinal ventilation, 3.88–5.08 m/s envelope (Orange Gate TVS); jet fans
- High-pressure water mist, open nozzles, sectioned deluge, detection → delay → activation
- Orange Gate geometry (circular bore 11.0 m ID + cut & cover box, parametric) and San Pedro de Anes geometry (calibration + §13/§9 correlation)
- The 5 tenability criteria + target-object spread + fire-fighter access, as hard gates
- Hydraulic sizing (flow → pumps → tank) and a cost index
- Two engine tiers with one JSON contract; FDS deck auto-generated from the design JSON
- Streamlit + 3D Plotly viewer; run history / leaderboard; Claude-driven optimisation loop

### Out of scope (v1)
- Semi-transverse ventilation (Orange Gate is longitudinal); spill fires beyond the SOLIT² pool configuration
- Structural FE of lining, spalling; only gas/pipe-surface temperatures are reported
- Evacuation / egress modelling (FDS+Evac possible later)
- Detailed pipe-network hydraulics (Darcy–Weisbach single path only), pump control logic, SIL of valve control, water-quality items
- Regulatory sign-off — the rig produces evidence; it is not the approval

---

## 4. Engine candidates

| Engine | Physics | Water mist | Criteria outputs (TC, HF, FED, visibility) | Tunnel validation base | Run time (100 MW, 40 min) | Licence | Apple-silicon Mac | Reviewer acceptance |
|---|---|---|---|---|---|---|---|---|
| **FDS 6.11.1 (NIST)** | LES CFD, mixing-limited combustion, radiation FVM | Lagrangian droplets: K-factor / pressure / spray angle / size distribution, evaporation, droplet radiation absorption, empirical surface-cooling suppression (`E_COEFFICIENT`) | all built-in `DEVC` quantities | NIST validation guide includes tunnel and sprinkler/mist series; de-facto tool in PIARC / NFPA 502 / SOLIT² Annex 3 practice | hours (see §6) | free, open source | native `_osx.sh` installer (178 MB), MPI included | highest |
| FireFOAM (OpenFOAM) | LES CFD | best-in-class spray & pyrolysis (FM Global) | build your own | few tunnel cases | hours–days | free | Docker only | medium (research) |
| ANSYS Fluent / Star-CCM+ / KOBRA-3D | RANS/LES CFD | yes | build your own | yes | hours | €€€€ | no / partial | high |
| CFAST / two-zone | zone model | none | some | compartments, not tunnels | seconds | free | yes | not for tunnels |
| IDA Tunnel / SES / Camatt | 1-D network aerodynamics + heat | none | none | ventilation design only | seconds | € | partial | ventilation only |
| **Custom reduced-order (this project)** | Ingason–Li HRR/ceiling T, Alpert ceiling jet, Li–Ingason critical velocity, Kurioka backlayering, Hansen–Ingason suppression, Beer–Lambert attenuation, ISO 13571 FED, Jin visibility | semi-empirical, calibrated to APPLUS + SOLIT² anchors | all, by construction | calibrated to 2 campaigns, 5 cases | < 1 s | free (built here) | yes | screening only — never stand-alone |
| ML surrogate on FDS runs | learned | learned | learned | inherits FDS | ms | free | yes | screening only; needs ≥ 50–100 FDS runs first |

### Verdict

- **Best engine for a full-scale fire test digital twin: FDS 6.11.1.** Only free engine that models the mist as droplets (evaporation, momentum, radiation blocking), reports every SOLIT² criterion natively, has a published tunnel validation base, runs natively on this Mac, and is what reviewers expect.
- **Best engine for Claude's 20-run optimisation loop: the reduced-order engine.** FDS cannot iterate interactively.
- **Therefore: tiered.** Tier 1 (reduced-order) for search and ranking; Tier 2 (FDS) for verification of the top 3–5 designs and for periodically re-calibrating Tier 1 where the two test campaigns leave gaps (e.g. Kerala cross-section, both-wall layouts, 4 m spacing). One JSON in, one JSON out, both tiers.

---

## 5. Why not FDS-only, why not reduced-order-only

- FDS-only: an evaluation costs hours → optimisation becomes an overnight batch of a handful of designs; the "Claude iterates with intuition" pattern is lost.
- Reduced-order-only: correlations are tuned to two nozzle types in one tunnel; Annex 2 warns results transfer only to the same nozzle. Extrapolating to a new K-factor, spacing or a 7.5 m crown without a physics check is exactly the failure mode a reviewer will attack.

---

## 6. FDS feasibility on this machine

Machine: Apple M3 Pro, 11 cores (5 P + 6 E), 18 GB RAM, arm64. FDS 6.11.1 (2026-07-10) macOS installer available; Docker daemon present but not running; `uv`, `gfortran`, `cmake` present.

### Resolution (characteristic fire diameter D* = (Q̇ / ρ∞ cₚ T∞ √g)^(2/5))

| Fire | D* | dx at D*/dx = 10 (coarse) | dx at D*/dx = 16 (medium) |
|---|---|---|---|
| 30 MW | 3.7 m | 0.37 m | 0.23 m |
| 50 MW | 4.6 m | 0.46 m | 0.29 m |
| 100 MW | 6.1 m | 0.60 m | 0.38 m |

### Domain
Model U60 → D120 (180 m) of one Orange Gate bore (11.0 m ID circle, deck 2.125 m below centre → 10.15 × 7.63 m envelope, stair-stepped), open portals with imposed upstream velocity 3.88 or 5.08 m/s; covers the 90 m active zone and every criteria station (U35, U15, D5 target, D15, D20, D35, D100). 150 MW → D* ≈ 7.1 m → dx 0.45 m screening (≈ 180 k cells), 0.25 m final (≈ 1.0 M cells).

| dx | Cells | Meshes (MPI) | Steps (40 min) | Rough wall-clock on M3 Pro* | Use |
|---|---|---|---|---|---|
| 0.40 m | ≈ 170 k | 5 | ≈ 120 k | 3–8 h | screening / calibration |
| 0.25 m | ≈ 690 k | 5–10 | ≈ 200 k | 20–40 h | final verification → run on cloud |

*Order-of-magnitude, assuming ≈ 3 × 10⁵ cell-steps/s per core with particles; to be measured on the first run.

Cloud fallback: 16-vCPU x86 instance (AWS c6i.4xlarge ≈ US$0.7/h, Hetzner CCX ≈ €0.1/h) → a 0.25 m run ≈ US$3–15. Claude can drive it over SSH exactly as it drives the local CLI.

### FDS input mapping (auto-generated from the design JSON)

| Design JSON | FDS namelist |
|---|---|
| tunnel dims, portals | `&MESH`, `&OBST`, `&VENT SURF_ID='OPEN'` |
| ventilation velocity | `&SURF VEL=` on upstream portal or `&HVAC` jet fan |
| fire: HRR curve, pallet footprint | `&SURF HRRPUA RAMP_Q` (prescribed) or `&MATL` wood pyrolysis (predictive, needed for HRR reduction by mist) + `E_COEFFICIENT` |
| nozzle K, pressure, angle, offsets, spacing | `&PROP K_FACTOR OPERATING_PRESSURE SPRAY_ANGLE OFFSET PART_ID`, `&DEVC` per nozzle with `ORIENTATION` |
| droplet size | `&PART DIAMETER GAMMA_D MINIMUM_DIAMETER MAXIMUM_DIAMETER SPEC_ID='WATER VAPOR'` |
| detection + delay | `&DEVC QUANTITY='THERMOCOUPLE' SETPOINT=60` → `&CTRL FUNCTION_TYPE='TIME_DELAY' DELAY=` → nozzle activation |
| criteria stations | `&DEVC` `THERMOCOUPLE`, `GAUGE HEAT FLUX`, `FED`, `VISIBILITY`, `VELOCITY` at U35 / U15 / D15 / D35 / D100 |
| output | `_devc.csv`, `_hrr.csv` → parsed back into the same result JSON as Tier 1 |

### Blockers found

| Blocker | Impact | Fix |
|---|---|---|
| **Disk: 6.6 GB free of 460 GB (99 % full)** | FDS install ≈ 1 GB + ≥ 1 GB per run → cannot run locally today | free ≥ 30 GB, or external SSD, or run Tier 2 in the cloud |
| Anaconda base env broken (pandas/pyarrow built for numpy 1.x, numpy 2.4 installed) | Streamlit app would crash on import | project venv via `uv`, pinned deps |
| Docker daemon not running | only matters if we choose the container route for FDS/OpenFOAM | start Docker, or use native installer (preferred) |
| Kerala cross-section unknown | affects ceiling temperature, backlayering, nozzle reach | JSON parameter with stated IRC SP 91 default; request drawing |

---

## 7. Calibration & validation plan

Anchor cases (run in both tiers, San Pedro de Anes geometry):

| # | Case | Compare |
|---|---|---|
| C1 | APPLUS Test 3 — 30 MW, 20 nozzles right wall, 62 bar, 661 lpm | U35 T, HF U15, FED, growth-rate class |
| C2 | APPLUS Test 6 — 50 MW, 20 nozzles, 66 bar, 682 lpm | idem |
| C3 | APPLUS Test 9 — 100 MW, 40 nozzles, 56 bar, 1 257 lpm, activation +3:21 | idem + ≈ 650 °C ceiling avg, backlayering when u < 1 m/s |
| C4 | SOLIT² Class A with cover, u 2–2.5 m/s, FFFS at 0:07 | peak HRR ≈ 30 MW, ceiling ≈ 830 °C, D15 50–100 °C, D100 50–65 °C, HF D15 ≈ 1 kW/m² |
| C5 | SOLIT² Class A no cover, u 1–1.5 m/s, FFFS at 0:04 | peak HRR ≈ 20 MW, ceiling ≈ 580 °C, D15 50–60 °C, HF D15 ≈ 0.45 kW/m² |
| C6 | SOLIT² Class B 60 MW pools, longitudinal, FFFS before peak (rev 2) | backlayering pre-activation cleared after; flames ≈ D15; pools extinguished one by one |

Acceptance tolerances for Tier 1 (screening engine): peak HRR ± 25 %, peak ceiling T ± 20 %, station gas T ± 15 °C or ± 20 %, heat flux within a factor 2, correct backlayering yes/no. Tier 2 (FDS) is judged against the same anchors and against the NIST validation-guide uncertainty bands; C4/C5 use the FOGTEC nozzle, so they calibrate the *shape* of the suppression response, not the absolute constants for the Ultrafog nozzle (Annex 2 §4.1.3 caveat).

---

## 8. Architecture delta versus the brainstormed design

Unchanged: `core/` reduced-order engine, `cli.py`, `app.py`, JSON contract, score function, build order 1–8.

Added:

```
solit2/
  engines/
    reduced/      ← core/ moves here (Tier 1)
    fds/
      deck.py     design JSON → .fds namelist file
      runner.py   local (mpiexec) or remote (ssh) execution, progress polling
      reader.py   _devc.csv / _hrr.csv → result JSON (same schema as Tier 1)
  validation/
    anchors/      C1–C5 as design JSON + measured CSV
    compare.py    tolerance report per anchor, both tiers
```

CLI grows one flag: `solit2 run design.json --engine reduced|fds`. Streamlit gets a "verify with FDS" button that queues a Tier 2 job for the selected leaderboard row.

---

## 9. Risks

| Risk | Likelihood | Mitigation |
|---|---|---|
| Tier 1 mis-ranks designs (suppression correlation wrong outside anchor range) | medium | Tier 2 spot-checks; re-fit constants when FDS disagrees > tolerance |
| FDS prescribed-HRR cannot show mist reducing HRR | certain if prescribed | use `E_COEFFICIENT` or wood pyrolysis for the pallet array; calibrate to C4/C5 HRR curves |
| Coarse 0.4 m grid under-resolves nozzle sprays | medium | nested finer mesh around the active zone; 0.25 m final run |
| Local run time / disk | high (disk is a blocker now) | cloud runner from day one; results stay small (csv, few slices) |
| Kerala geometry assumption wrong | medium | single JSON field; rerun leaderboard |

---

## 10. Recommendation (one paragraph)

Build the reduced-order engine first (it is the optimiser), then the FDS deck generator + reader against the same JSON, install FDS 6.11.1 natively once ≥ 30 GB disk is freed (or point the runner at a cloud box), calibrate both tiers on C1–C6, and only then let Claude optimise the Orange Gate design from the DBR Rev 0 baseline — with FDS runs in both the San Pedro de Anes and Orange Gate presets feeding the tender's §9 correlation and §13 test plan. FDS is the best simulation engine for the full-scale fire test; the reduced-order engine is the best engine for the search — the product is the pair.

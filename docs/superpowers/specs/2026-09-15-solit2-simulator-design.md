# SOLIT² Simulator — Design Specification (rev 2)

Date: 2026-09-15 (rev 2 — target corrected to Orange Gate; rev 1 targeted the Kerala reference tunnel by mistake)
Status: approved architecture, retargeted — ready for implementation planning after review
Companion: [Scope & engine analysis](2026-09-15-solit2-scope-and-engine-analysis.md) — data inventory, engine comparison, feasibility, blockers.

Source documents (confidential, referenced by path, not copied into the repo):
- Mistelix DBR `MSTX-OG-DBR-001 Rev 0` (23-08-2026) — `~/Documents/Claude/Projects/Orange_Gate/DBR.pdf`
- L&T `HPWM-TECHNICAL SPEC_R2` (02-04-2026) and GA drawing `EWCR-LNT-430-PD-102886_A1.3`, schematics `EWCR-LNT-460-PD-103750/103752` — `~/Documents/Claude/Projects/Orange_Gate/Annex-3…`
- Ultrafog design brief + APPLUS+TST test report (2020) — `~/Downloads/Design Basis Report.pdf` (reference nozzle, calibration anchors)
- SOLIT² Engineering Guidance Annex 2 (2012) — `~/Downloads/SOLIT_EG_Annex2_EN_v2.1.pdf` (calibration anchors, Class A truck + Class B pool)

---

## 1. Purpose

Mistelix is bidding the high-pressure water-mist FFFS for the **Orange Gate – Marine Drive underground road tunnel, Mumbai** (MMRDA via L&T). The tender requires: 150 MW design fire controlled to ≤ 50 MW under 3.88–5.08 m/s longitudinal ventilation, Class A and Class B fires, three zones simultaneous per SOLIT²/NFPA, effectiveness proven by SOLIT²/NFPA 502 full-scale test, and — post-award — a **CFD analysis correlating the tested tunnel & TVS with the Orange Gate tunnel & TVS**. The nozzle is Mistelix's own bimodal **MSX-T-100** (fine mist ring + coarse ballistic core), which has no fire-test data yet: the full-scale test is the bid's critical path.

The simulator is therefore three things sharing one design JSON and one result JSON:

1. **Design optimiser** (Tier 1, reduced-order, < 1 s/run) — Claude searches nozzle layout, hydraulics, zoning/activation and the fine/coarse split, against the tender gates and SOLIT² tenability criteria, minimising water, power, cost and lining temperature.
2. **Pre-test predictor and test planner** — the same design run in the San Pedro de Anes test-tunnel preset predicts what the SOLIT²-protocol test will show and fixes the test inputs (pressure, density, split, HRR, velocity).
3. **CFD correlation tier** (Tier 2, FDS 6.11.1) — the tender's §9 deliverable: identical design run in the test-tunnel geometry and in the Orange Gate geometry, criteria side by side. Also verifies the optimiser's top designs and recalibrates Tier 1 where no test data exists (the bimodal claim).

Success = (a) Tier 1 reproduces the six anchor tests within §9 tolerances; (b) from the DBR Rev 0 design as baseline, Claude reaches a gate-passing, better-scoring design in ≈ 20 runs; (c) `solit2 report correlation` produces the §9 skeleton from two FDS runs without manual editing.

---

## 2. Repository layout

```
Solit2_simulator/
  pyproject.toml                  uv-managed, Python 3.12, pinned deps
  CLAUDE.md                       how Claude drives the optimisation loop (§12)
  solit2/
    schema/
      design.py  result.py  presets.py
    presets/
      tunnel_orange_gate.json     two tubes, bored (circular) + cut & cover sections, TVS envelope  [C] items listed inside
      tunnel_san_pedro_de_anes.json  600 m, 9.5 W, false ceiling 5.17 m, 48 m²
      nozzle_mistelix_msx_t100.json  performance data only (K, pressure band, SMD table, split, cone angles)
      nozzle_ultrafog_202_260T.json  reference / calibration nozzle
      fire_hgv_150mw.json  fire_pool_60mw.json  fire_pallets_{30,50,100}mw.json
      hydraulics_orange_gate.json  pump arrangement, ring main, power cap, feeders
      calibration.json            every fitted constant with the anchor it was fitted on
      cost_weights.json           relative unit costs; DBR/BOQ baseline = 1.00
    engines/
      reduced/  geometry.py fire.py ventilation.py thermal.py mist.py tenability.py
                hydraulics.py cost.py score.py sim.py envelope.py
      fds/      deck.py runner.py reader.py
    reports/    test_plan.py correlation.py
    cli.py  history.py
  app/          streamlit_app.py  views/ design.py run.py tunnel3d.py leaderboard.py verify.py
  validation/   anchors/c1…c6.json  compare.py
  designs/      og-dbr-rev0.json (baseline) and Claude's candidates
  runs/         history.jsonl + per-run result JSON (git-ignored)
  tests/
```

Rules: files ≤ 400 lines target, 800 hard; functions ≤ 50 lines; frozen dataclasses / pydantic models, no in-place mutation; every physical constant in `presets/calibration.json` or a named module constant; shortcuts marked `# ponytail: <limit> — <upgrade path>`.

**IP hygiene:** the repo carries nozzle *performance* data only — the same level the DBR discloses. Internal atomiser geometry (orifice diameters, swirl ports) never enters presets, tests or docs. Source PDFs stay outside the repo; `.gitignore` blocks `*.pdf`, `*.docx`, `*.pptx`.

---

## 3. Design JSON (input contract)

```json
{
  "meta":    {"name": "og-dbr-rev0", "notes": "DBR Rev 0 as bid"},
  "tunnel":  {"preset": "orange_gate", "tube": "LHS", "section": "bored",
              "gradient_pct": 0.3, "ambient_temp_c": 30, "ambient_rh_pct": 75},
  "fire":    {"preset": "hgv_150mw", "class": "A",
              "design_hrr_mw": 150, "growth": "fast", "alpha_kw_s2": null,
              "pallets": 408, "energy_mj_per_pallet": 343, "covered": false,
              "footprint": {"length_m": 8.4, "width_m": 2.4, "top_height_m": 4.0},
              "lane_centre_offset_from_wall_m": 3.4, "target_distance_m": 5.0},
  "nozzles": {"preset": "mistelix_msx_t100",
              "k_factor_lpm_bar05": 4.1, "pressure_bar": 50,
              "modes": [{"id": "fine",   "fraction": 0.60},
                        {"id": "coarse", "fraction": 0.40}],
              "mounting": {"type": "ceiling_rows", "rows": 2,
                           "row_lateral_offsets_m": [-2.5, 2.5],
                           "height_above_carriageway_m": 5.75,
                           "pitch_m": 2.4, "nozzles_per_fixing": 1, "tilt_deg": 0}},
  "zones":   {"section_length_m": 30, "heads_per_zone": null,
              "sections_simultaneous": 3, "activation_delay_s": 60,
              "pump_ramp_s": 30, "duration_min": 60},
  "ventilation": {"mode": "longitudinal", "velocity_ms": null,
                  "velocity_range_ms": [3.88, 5.08]},
  "detection":   {"type": "linear_heat", "threshold_c": 60, "sensor_spacing_m": 25},
  "hydraulics":  {"preset": "orange_gate"},
  "criteria": {}
}
```

Presets supply every field not given. Derivations and validation (fail fast, field-named errors):

- **Section geometry.** `bored`: circular, `internal_diameter_m 11.0`, pavement `2.125 m` below centre (GA: 3 375 mm invert-to-pavement) → road width at pavement 10.15 m, crown height 7.63 m, free area 70.3 m², width at 5.5 m above carriageway 8.7 m. `cut_cover`: rectangle 9.0 W × 6.5 H [C — drawing says "varies" above the 5.5 m clearance]. Nozzle rows must sit ≥ `clearance_m` (5.5) and inside the section at that height (both rows at ±2.5 m fit the 8.7 m width — validated).
- `heads_per_zone` null → `rows × round(section_length / pitch)` (2 × 12.5 → 25 for the DBR); if given and inconsistent by > 1 → error.
- `velocity_ms` null → the design is evaluated over `velocity_range_ms` (§5.10 envelope); a number pins a single velocity.
- Mode fractions must sum to 1 ± 0.01. Per-mode droplet sizes from the nozzle preset: fine SMD from the pressure table (34.5 → 118, 45 → 107, 50 → 102, 60 → 95 µm, log-log interpolation), coarse 450 µm (300–600).
- `alpha_kw_s2` null → NFPA 72 class (slow 0.00293, medium 0.01172, fast 0.0469, ultrafast 0.1876 kW/s²). SOLIT² truck: fast after a 1–2 min incubation (Annex 2 summaries).
- Ranges: pressure 34.5–140 bar (34.5 = NFPA 750 floor, hard error below), K 0.5–20, pitch 1–10 m, rows 1–3, velocity 0–8 m/s, HRR 1–300 MW, delay 0–600 s, section length 8–100 m, sections 1–6, duration 10–120 min, mount height `clearance_m`–crown.
- `criteria` overrides limits / `hard` flags of §7.

---

## 4. Result JSON (output contract, both engines)

```json
{
  "meta":   {"design_name": "og-dbr-rev0", "design_sha": "…", "engine": "reduced|fds",
             "engine_version": "…", "runtime_s": 1.6, "timestamp": "…"},
  "envelope": [{"section": "bored", "velocity_ms": 3.88}, {"section": "bored", "velocity_ms": 5.08}],
  "worst_case": {"section": "bored", "velocity_ms": 5.08},
  "events": {"t_detect_s": 75, "t_activate_s": 135, "t_full_pressure_s": 165, "t_peak_hrr_s": 420,
             "backlayering": {"occurred": false, "max_length_m": 0, "cleared_at_s": null},
             "pools_extinguished_at_s": null},
  "criteria": {
    "hrr_control_mw":   {"value": 46,   "limit": 50,   "op": "<=", "hard": true,  "pass": true, "margin": 0.08},
    "power_kw":         {"value": 375,  "limit": 650,  "op": "<=", "hard": true,  "pass": true, "margin": 0.42},
    "target_hf_kwm2":   {"value": 9.8,  "limit": 12.5, "op": "<=", "hard": true,  "pass": true, "margin": 0.22},
    "u35_temp_c":       {"value": 31,   "limit": 60,   "op": "<=", "hard": true,  "pass": true, "margin": 0.48},
    "hf_u15_kwm2":      {"value": 1.1,  "limit": 5.0,  "op": "<=", "hard": true,  "pass": true, "margin": 0.78},
    "hf_u35_kwm2":      {"value": 0.3,  "limit": 2.5,  "op": "<=", "hard": true,  "pass": true, "margin": 0.88},
    "visibility_u35_m": {"value": 60,   "limit": 10,   "op": ">=", "hard": true,  "pass": true, "margin": 1.0},
    "fed_d35":          {"value": 0.05, "limit": 0.3,  "op": "<=", "hard": true,  "pass": true, "margin": 0.83},
    "remote_nozzle_bar":{"value": 50,   "limit": [45, 60], "op": "in", "hard": true, "pass": true, "margin": 0.33},
    "ff_u5_hf_kwm2":    {"value": 3.9,  "limit": 5.0,  "op": "<=", "hard": false, "pass": true, "margin": 0.22},
    "ff_d20_temp_c":    {"value": 71,   "limit": 60,   "op": "<=", "hard": false, "pass": false,"margin": -0.18},
    "density_mm_min":   {"value": 2.4,  "limit": 3.8,  "op": "<=", "hard": false, "pass": true, "margin": 0.37}
  },
  "peaks": {"hrr_mw": 46, "hrr_free_burn_mw": 150, "ceiling_temp_c": 720, "lining_temp_c": 690,
            "pipe_surface_temp_c": 98, "smoke_layer_temp_d15_c": 140},
  "mist":  {"w_fuel_mm_min": 3.1, "f_cov": 0.9, "f_pen": {"fine": 0.05, "coarse": 0.62},
            "evaporated_fraction": {"fine": 0.7, "coarse": 0.1}, "chi_cool": 0.35, "tau_mist_u15": 0.55},
  "hydraulics": {"active_heads": 75, "flow_lpm": 2175, "flow_design_lpm": 2393,
                 "pumps": {"duty": 2, "standby": 1, "unit_m3h": 72, "rated_bar": 65},
                 "required_pump_bar": 59.4, "power_kw": 375, "tank_m3": 143.6,
                 "density_mm_min": 2.4, "density_l_m3_min": 0.34},
  "cost":  {"zones": 283, "heads": 7075, "section_valves": 283, "ring_main_m": 17400,
            "zone_header_m": 8500, "row_pipe_m": 17000, "pumps": 3, "tank_m3": 143.6, "index": 1.00},
  "score": {"total": 6.1, "gates_passed": true, "gates_failed": [],
            "components": {"water": 0.67, "margin": 0.55, "cost": 0.67, "structural": 0.49}, "penalties": []},
  "timeseries": {"t_s": [], "hrr_mw": [], "ceiling_temp_c": [], "u35_temp_c": [], "d15_temp_c": [],
                 "hf_u15_kwm2": [], "fed_d35": [], "backlayering_m": [], "velocity_ms": [], "water_lpm": []},
  "warnings": ["u = 3.88 m/s is within 5 % of critical velocity 3.71 m/s for the free-burning 150 MW fire"]
}
```

Density is computed over `L_act × road_width` (10.15 m in the bore → 2.4 mm/min; the DBR's 2.2 uses the 11 m internal diameter). `margin = 1 − value/limit` for `<=`, `min(1, value/limit − 1)` for `>=`, distance to nearest bound / half-band for `in`; clipped [−1, 1]. Criteria hold the worst case over the envelope; `timeseries` is the worst case's. Both engines fill every field.

---

## 5. Tier 1 — reduced-order engine

Explicit march, Δt = 1 s, `T_END = duration_min × 60`; pure functions over frozen dataclasses; `sim.py` composes, `envelope.py` runs the (section × velocity) grid and takes the worst case. Stations: U35, U15, U5, D0, D5 (target), D15, D20, D35, D100 from fire centre; breathing height 1.8 m; ceiling −0.15 m.

### 5.1 `geometry.py`
Section → `free_area_m2`, `road_width_m`, `crown_height_m` (H for ceiling-jet correlations), `mean_height_m = A / road_width`, `width_at(h)`, `hydraulic_diameter_m`. Circular segment algebra for `bored`; rectangle for `cut_cover`; San Pedro preset = rectangle 9.5 × 5.17. Nozzle positions from `mounting` (rows × pitch over the active length), each with `(x, y, z, orientation)`.

### 5.2 `fire.py`
- **Class A** — free-burn `Q_fb(t) = min(α (t − t_inc)², Q_max)`, incubation `t_inc` 60 s (Annex 2), until `∫Q dt` reaches 80 % of `E = pallets × 343 MJ`, then linear decay. Suppressed `Q = Q_fb · S(t)`, `S = 1 − η (1 − e^{−(t − t_full)/τ_s})`; `covered` multiplies `τ_s` by the shielding factor (Annex 2: tarpaulin delays suppression). `ṁ_f = Q/(χ ΔH_c)`, wood `ΔH_c 17.5 MJ/kg`, `χ 0.8`, `χ_r 0.35`.
- **Class B** — pools: `Q_pool = f_vent · ṁ''∞ (1 − e^{−kβ D}) ΔH_c A_pool` (Babrauskas; diesel `ṁ''∞ 0.035 kg/m²s`, `kβ 1.7 m⁻¹`, `ΔH_c 44.8 MJ/kg`), 150 s ramp to full (Annex 2: 2–3 min), `f_vent` calibrated on c6 (nominal 60 MW from 7 × 4 m² pools). Suppression: burning-rate reduction `η_B` from `w_fuel` and **extinction** of a pool when `w_fuel · f_cov ≥ w_ext` is sustained for `t_ext`; pools go out one by one (Annex 2) → HRR steps down. `χ_r 0.30`, soot yield 0.06 g/g (diesel), CO 0.01 g/g.

### 5.3 `ventilation.py`
`Q* = Q_eff /(ρ∞ cₚ T∞ g^½ H^{5/2})` with `Q_eff` = convective HRR after mist cooling. Critical velocity (Li, Lei & Ingason 2010): `u_c* = 0.81 Q*^{1/3}` (`Q* ≤ 0.15`) else `0.43`; backlayering `L_b = 18.5 H ln(u_c*/u*)` for `u* < u_c*`. Throttling `u_eff = u_fan (1 − k_thr Q_c /(ρ cₚ T∞ A u_fan))`, `k_thr` from Annex 2 Fig. 10/19.
Sanity values recorded as tests: Orange Gate bored (H 7.63 m) 150 MW free burn → `u_c ≈ 3.7 m/s` (design floor 3.88 m/s: 5 % margin → warning); cut & cover (H 6.5 m) → 3.4 m/s; San Pedro (H 5.17 m) 100 MW → 3.06 m/s.

### 5.4 `thermal.py`
Unchanged from rev 1: Li & Ingason `ΔT_max` (Regions I/II, cap 1 350 K) with `H_ef = crown − fuel top`; two-term longitudinal decay; linear upstream decay inside `L_b`; Newman stratification for 1.8 m values; Alpert ceiling-jet detection at the worst sensor offset; point-source radiation `q'' = χ_r Q/(4πR²) · τ_mist · τ_smoke` + hot-layer term for ceiling-facing gauges; Ingason–Li downstream flame length (`C_f` from *Tunnel Fire Dynamics* Ch. 11, recorded in `calibration.json`); lining temperature = ceiling gas above fire; pipe surface lumped model, water-filled → ≤ 100 °C.
Addition: **smoke-layer interface height** `z_i` from the Newman regime (stratified: `z_i = H − 0.3 H`; transitional: linear; mixed: 0) — decides whether nozzle rows at `height_above_carriageway_m` discharge into hot smoke (fine-mode evaporation, §5.5) or into cool air.

### 5.5 `mist.py` — bimodal
- Per head `q = K√P`; per mode `q_m = fraction_m · q`; active heads `n = heads_per_zone × sections`; `Q_w = n q`, ramped over `pump_ramp_s`. Active length `L_act = sections × section_length` centred on fire zone ± 1.
- **Trajectory per mode** (`# ponytail: one representative droplet per mode, 2-D — replace by a size distribution if FDS shows the tail matters`): integrate `d v/dt = −(3 ρ_a C_D /(4 ρ_w d)) |v − u_rel| (v − u_rel) + g` with Schiller–Naumann `C_D`, air velocity `u_rel = (u_eff, 0, w_plume(x))`, launch velocity `v_launch` along the nozzle orientation (fine 15 m/s, coarse 100 m/s ≈ √(2ΔP/ρ_w) — calibration entries), evaporation in transit by the d²-law with `K_evap(T_gas at height)`; stop at the fuel-top plane or when `d < 10 µm` (evaporated). Output per mode: landing offset `Δx_m`, surviving mass fraction `1 − f_evap,m`.
- **Footprints**: each head's mode footprint = ellipse from cone angle at the fuel-top plane, shifted by `Δx_m`. Halo `A_halo` = fuel footprint + 1 m. `Q_hit = Σ_heads Σ_modes q_m (1 − f_evap,m) · overlap(footprint, A_halo)/area(footprint)`; `w_fuel = Q_hit / A_halo` (mm/min); `f_cov` = covered fraction of `A_halo`; `f_pen,m` = hit fraction per mode (reported).
- **Suppression** `η = η_max (1 − e^{−w_fuel f_cov / w_ref})` (Class A); `η_B`, `w_ext`, `t_ext` (Class B).
- **Gas cooling** `χ_cool = min(χ_max, Σ_m f_evap,m ṁ_w,m (cₚ,w ΔT + h_fg) / Q_c)` — the fine mode's job.
- **Radiation attenuation** `κ = Σ_m 1.5 C_v,m / d_m`, `C_v,m` from in-flight residence time; `τ_mist = e^{−κ L_path}`.
- **Drift check**: at 5 m/s a 100 µm drop from 5.75 m lands ≈ 100 m downstream, a 450 µm drop launched at 100 m/s lands within metres — the model must reproduce this ordering (property test).

### 5.6 `tenability.py`
As rev 1 (species from yields and `ṁ_air = ρ u A`, stratification factor, ISO 13571 `FED_tox` with CO₂ hyperventilation, `FED_heat`, Jin visibility with `K_s = 8.7 C_soot + κ_mist`), plus Class B yields. Orange Gate bored: `ṁ_air ≈ 1.2 × 4.5 × 70 ≈ 380 kg/s` — dilution is large; the binding criteria will be heat flux and control, not FED.

### 5.7 `hydraulics.py`
- `flow_design = 1.10 × flow` (spec: 3 zones + 10 %); pump arrangement from preset: main `2 × 50 % duty + 1 × 50 % standby` (DBR) or generic `N + 1` with `unit_m3h`; booster same capacity; jockey. `required_pump_bar = P_nozzle + Δp_ring + Δp_zone + Δp_static + Δp_fittings`; `rated_bar = 1.10 × required` (spec).
- Ring-main friction: Darcy–Weisbach on the worst path of a **looped** DN150 SS316L main, split flow → `Δp_ring ≈ 0.25 × Δp_radial` (DBR §4.5); zone header DN65 + gridded rows from the same solver. `# ponytail: worst-path loop factor 0.25 — replace by a network solve if DN200 option or broken-ring case is studied.`
- Power `P_hyd = Q ΔP`; `P_shaft = P_hyd / η_pump (0.68)`; `P_motor = P_shaft / η_motor (0.93)` — DBR: 237 → 348 → 375 kW. Gate `power_kw ≤ 650` (two 325 kW feeders). Density headroom at cap: `w_max ≈ 3.8 mm/min`.
- Tank `= flow_design × duration / 1 000` → 143.6 m³ (DBR ≈ 145; L&T provision 2 × 150 m³).
- Tests (±0.5 %): `4.1√50 = 29.0`; `25 × 29 = 725`; `3 × 725 = 2 175`; `× 1.1 = 2 393 lpm = 143.6 m³/h`; `59.4 → 65 bar`; `375 kW`; `143.6 m³`.

### 5.8 `cost.py`
Quantities for both tubes: `zones = Σ_tube ceil(L_tube / section_length)` (DBR 141 + 142 = 283); `heads = zones × heads_per_zone` (≈ 7 075; DBR ≈ 7 100); `section_valves = zones`; `ring_main_m ≈ 2 × Σ L_tube + cross-connects`; `zone_header_m`, `row_pipe_m = rows × Σ L_tube`; pumps; tank. `index = cost / cost_DBR_rev0 = 1.00` at baseline.

### 5.9 `score.py`
Hard gates (§7) → fail = `total 0`, everything still reported. Else `total = 10 Σ w_i s_i`, weights water 0.30, margin 0.30, cost 0.20, structural 0.20: `s_water = clip(flow_DBR/flow, 0, 1.5)/1.5`, `s_margin = mean(hard margins)`, `s_cost = clip(1/index, 0, 1.5)/1.5`, `s_structural = 1 − lining_peak/1 350`. Penalties: `u_eff < u_c` persisting > 120 s after activation −1.0; density > 3.8 mm/min −1.0 (power headroom gone); remote nozzle pressure outside 45–60 bar is a hard gate, not a penalty.

### 5.10 `envelope.py`
Grid = `sections × velocity_range` ends (default 2 × 2 = 4 runs, ≈ 1–2 s total). Each criterion takes its worst value over the grid; `worst_case` names the run; `timeseries` from it. Optional `--sweep` adds intermediate velocities.

---

## 6. Tier 2 — FDS engine

| Design field | Namelist |
|---|---|
| bored section | stair-stepped `&OBST` ring at `dx` approximating the 11.0 m circle, deck `&OBST` at −2.125 m; cut & cover: rectangular walls; San Pedro: rectangle + false ceiling |
| window | U60 → D120 (180 m), N MPI meshes along x; portals `&VENT MB='XMIN' SURF_ID='SUPPLY'` with `&SURF VEL=−u` (negative = inflow), `MB='XMAX' SURF_ID='OPEN'` |
| fire A | pallet block `&OBST`, `&SURF ID='FIRE' HRRPUA RAMP_Q` (free-burn curve) + `E_COEFFICIENT` (water cools the surface → HRR falls); fire B: pool `&SURF` with `HRRPUA` per pool + `E_COEFFICIENT` |
| nozzle head | **two co-located `&DEVC`** per head (`PROP_ID='NOZ_FINE'`, `'NOZ_COARSE'`), same `XYZ`, `ORIENTATION` from tilt, `CTRL_ID='ACT'` |
| props | `&PROP ID='NOZ_FINE' PART_ID='FINE' FLOW_RATE=17.4 SPRAY_ANGLE=30,60 PARTICLE_VELOCITY=15`; `&PROP ID='NOZ_COARSE' PART_ID='COARSE' FLOW_RATE=11.6 SPRAY_ANGLE=0,10 PARTICLE_VELOCITY=100` (flows = fraction × K√P; velocities from calibration.json until PDA data) |
| particles | `&PART ID='FINE' SPEC_ID='WATER VAPOR' DIAMETER=102 GAMMA_D=2.4`; `&PART ID='COARSE' … DIAMETER=450 MINIMUM_DIAMETER=300 MAXIMUM_DIAMETER=600` |
| detection | `&DEVC THERMOCOUPLE SETPOINT=60` per `sensor_spacing_m` → `&CTRL FUNCTION_TYPE='TIME_DELAY' DELAY=activation_delay_s` → `ACT`; pump ramp `&RAMP` on flow |
| stations | `&DEVC` at U35/U15/U5/D5/D15/D20/D35/D100: `THERMOCOUPLE` (5 heights), `GAUGE HEAT FLUX` (1.8 m facing fire; D35 facing ceiling), `FED`, `VISIBILITY`, `VELOCITY`; `HRR` from `_hrr.csv` |
| output | `&DUMP DT_DEVC=1 DT_HRR=1`, two `&SLCF` (centreline T, U) — run < 1 GB |

Grid from `D* = (Q̇/(ρ∞ cₚ T∞ √g))^{2/5}`: 150 MW → `D* 7.1 m` → `dx 0.45–0.7 m` (D*/dx 10–16); bored window at 0.45 m ≈ 400 × 25 × 18 ≈ 180 k cells (screening, hours on the M3 Pro); 0.25 m ≈ 1.0 M cells (final, cloud). `runner.py`/`reader.py` as rev 1 (pre-flight: `fds` on PATH or `SOLIT2_FDS_BIN`, ≥ 10 GB free, `mpiexec`; remote via `SOLIT2_FDS_HOST`; missing device column = fatal). Deck is deterministic → golden-file tests for the Orange Gate baseline and the San Pedro anchor.

---

## 7. Criteria (defaults; `design.criteria` overrides limits and `hard`)

| id | where | limit | hard | source |
|---|---|---|---|---|
| hrr_control_mw | peak HRR after `t_full_pressure` | ≤ 50 MW | yes | Spec R2 §6 (150 → ≤ 50 MW) |
| power_kw | pump motor input at design point | ≤ 650 kW | yes | Spec R2 §5.a (2 × 325 kW feeders) |
| target_hf_kwm2 | D5, fuel mid-height, after activation | ≤ 12.5 | yes | "prevent fire from spreading" (§4) — wood piloted ignition |
| remote_nozzle_bar | most remote head, worst 3-zone event | in [45, 60] | yes | DBR band; ≥ 34.5 bar spec floor |
| u35_temp_c | U35, 1.8 m | ≤ 60 °C | yes | SOLIT²/APPLUS a |
| hf_u15_kwm2 | U15, 1.8 m facing fire | ≤ 5.0 | yes | b |
| hf_u35_kwm2 | U35, 1.8 m | ≤ 2.5 | yes | c |
| visibility_u35_m | U35, 1.8 m, light-emitting | ≥ 10 m | yes | d (numeric limit assumed, flagged) |
| fed_d35 | D35, 1.8 m, toxic FED to `T_END` | ≤ 0.3 | yes | e |
| ff_u5_hf_kwm2 (+ T ≤ 60 °C) | U5, 1.8 m | ≤ 5.0 | no | fire-fighter approach |
| ff_d20_temp_c | D20, 1.8 m | ≤ 60 °C | no | downstream access |
| density_mm_min | active zone | ≤ 3.8 | no | DBR power-cap headroom |
| pools_extinguished_s | Class B | ≤ 600 s after full pressure | no | Annex 2 behaviour; reported |

All criteria evaluated over the whole run (worst instantaneous value; FED cumulative) and over the envelope.

---

## 8. CLI

```
solit2 run      design.json [--engine reduced|fds] [--section bored|cut_cover|all] [--velocity U] [--out result.json]
solit2 validate [--engine reduced|fds] [--anchor c1..c6]
solit2 fds-deck design.json [--dx 0.45] [--tunnel orange_gate|san_pedro_de_anes] [--out case.fds]
solit2 fds-status runs/<sha>
solit2 history  [--top 10] [--passing]
solit2 report   test-plan design.json                      → markdown: test inputs + predicted SPdA outcomes
solit2 report   correlation --test result_a.json --site result_b.json → markdown: §9 criteria side by side
```
Stdout = JSON; errors → stderr JSON `{"error","field","fix"}`; exit 0 ok, 1 validation miss, 2 bad input, 3 engine/pre-flight. Every `run` appends to `runs/history.jsonl` (append-only).

---

## 9. Calibration & validation

| id | case | targets |
|---|---|---|
| c1 | APPLUS T3 — 30 MW, Ultrafog 20 heads right wall, 62 bar, 661 lpm | U35 T, HF U15, FED, growth class (values to transcribe from report §9.4) |
| c2 | APPLUS T6 — 50 MW, 20 heads, 66 bar, 682 lpm | idem (§9.5) |
| c3 | APPLUS T9 — 100 MW, 40 heads, 56 bar, 1 257 lpm, act. +3:21 | idem; ceiling ≈ 650 °C avg; backlayering only when u < 1 m/s |
| c4 | SOLIT² A cover, u 2–2.5, FFFS 0:07 | peak ≈ 30 MW, ceiling ≈ 830 °C, D15 50–100 °C, D100 50–65 °C, HF D15 ≈ 1 kW/m² |
| c5 | SOLIT² A no cover, u 1–1.5, FFFS 0:04 | peak ≈ 20 MW, ceiling ≈ 580 °C, D15 50–60 °C, HF D15 ≈ 0.45 kW/m² |
| c6 | SOLIT² B, 60 MW pools, longitudinal, FFFS before peak | strong backlayering pre-activation, cleared after; flames ≈ D15; pools extinguished one by one |

Tolerances: peak HRR ± 25 %; peak ceiling T ± 20 %; station T ± 15 °C or ± 20 %; heat flux ×/÷ 2; backlayering yes/no; pool extinction yes/no and time ×/÷ 2. Fit (`scipy.optimize.least_squares`) over `calibration.json` constants (`η_max, w_ref, τ_s, shielding, χ_max, K_evap scale, v_launch per mode, k_thr, f_vent, η_B, w_ext, t_ext`); FOGTEC anchors c4–c6 weighted 0.5 (different nozzle). **No anchor uses the MSX-T-100** — its bimodal effect is an extrapolation until the fire test; Tier 2 FDS is the pre-test evidence, and the first Mistelix test becomes anchor c7 the day it is run.

---

## 10. Front end (Streamlit)

Design · Run (criteria table, envelope grid, timeseries) · Tunnel 3-D (circular bore or box, 180 m window, rows + heads + two-tone spray cones, fire block, ceiling temperature strip, backlayering, time slider) · Leaderboard · Verify (FDS pre-flight, deck, run, progress, Tier 1 vs Tier 2 table) · Reports (test-plan, correlation). Views call the same Python API as the CLI.

---

## 11. Testing

Unit: `K√P`, DBR hydraulics numbers, `u_c` for the three tunnels, `ΔT_max` regions, circular-segment geometry (70.3 m², 10.15 m, 8.7 m), FED for constant 1 000 ppm, Jin visibility, Beer–Lambert, pool HRR for 28 m² diesel, cost quantities (283 zones, ≈ 7 075 heads). Property: more water → ≤ HRR/T; higher u → shorter `L_b`; larger drop → shorter drift; coarse fraction ↑ → `w_fuel` ↑ and `χ_cool` ↓; result always validates. Anchor regression `solit2 validate`. FDS: golden decks (OG baseline, SPdA c3), reader fixture, pre-flight errors. CLI smoke. Coverage ≥ 80 %.

---

## 12. Claude optimisation loop (`CLAUDE.md`)

1. `solit2 run designs/og-dbr-rev0.json` → read `score`, `gates_failed`, `mist.f_pen`, `warnings`.
2. One parameter group per iteration with a physical reason (e.g. `target_hf` fails at 5.08 m/s → raise coarse fraction or lower mount height before adding heads; `power_kw` near cap → drop pressure inside the band, not heads).
3. ≈ 20 runs → `solit2 history --top 5 --passing` → `solit2 run --engine fds` for each top design in both `san_pedro_de_anes` and `orange_gate` presets → `solit2 report correlation`.
4. Tier 2 vs Tier 1 disagreement beyond §9 tolerance → new anchor, refit, re-rank.
5. Before the fire test: `solit2 report test-plan` on the chosen design = the §13 test inputs.

---

## 13. Error handling
As rev 1: field-named validation errors; physics raises on non-physical states; intentional clamps are named constants and logged in `warnings`; FDS pre-flight and missing-device failures are fatal; `warnings` is the only soft channel.

## 14. Environment
`uv`, Python 3.12, pinned numpy/scipy/pydantic ≥ 2/pandas/plotly/streamlit ≥ 1.37/pytest/pytest-cov/hypothesis; Anaconda base not used. FDS 6.11.1 native once ≥ 30 GB disk is free, else `SOLIT2_FDS_HOST`. `runs/` and all source PDFs git-ignored.

## 15. Build order
1. Skeleton, schema, presets (Orange Gate, San Pedro, MSX-T-100, Ultrafog, fires, hydraulics), CLI `run` stub, history — tests first.
2. `hydraulics.py`, `cost.py` — DBR numbers as tests.
3. `geometry.py`, `fire.py` (A + B), `ventilation.py`, `thermal.py`.
4. `mist.py` bimodal trajectories, `tenability.py`, criteria, `score.py`, `envelope.py`.
5. Anchors c1–c6, `compare.py`, `solit2 validate`, calibration fit.
6. FDS `deck.py` (circular, bimodal), `reader.py`, `runner.py`.
7. `reports/` test-plan and correlation.
8. Streamlit incl. 3-D bore.
9. `CLAUDE.md`, first optimisation from `og-dbr-rev0`, FDS verification of the top design, first correlation report.

## 16. Out of scope (v1)
Semi-transverse ventilation; structural FE / spalling; evacuation modelling; full network hydraulics beyond the looped worst path; pump/valve control logic, SIL, PCMS/MODBUS integration; water treatment; regulatory sign-off (the rig produces evidence for §13/§9, it is not the approval).

## 17. Open items to confirm with L&T / bench
Cut & cover internal height above the 5.5 m clearance; pavement level in the bore (2.125 m below centre inferred from the RHS section); cross-passage spacing; row lateral offsets and mount height against the walkway/utility envelope; fine/coarse split, cone angles and launch velocities (PDA at 45/50/60 bar); segment lengths (GA rev A1.3 2025 vs Spec R2 2026 differ — spec used); visibility limit (assumed 10 m).

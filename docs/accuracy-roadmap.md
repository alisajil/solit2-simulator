# What it would take to make this predict a real fire test

Ordered by how much each item moves the answer, not by effort. Every number
below comes from this repository: `uv run solit2 validate` for the anchor
misses, `score.criteria_unset` for the limits, and the notes in
`solit2/presets/calibration.json`.

The honest summary: the tool reproduces **heat release** well and **gas
temperature** badly. It is calibrated, not validated, and the two are not the
same claim.

---

## Where it actually stands

`uv run solit2 validate` exits non-zero today: 12 of 19 comparisons pass
against the three SOLIT² Annex 2 full-scale reference tests. The misses:

| case | quantity | modelled | measured | verdict |
|---|---|---|---|---|
| c4 | peak ceiling temperature | 201 °C | 830 °C | **4× low** |
| c4 | temperature 15 m downstream | 34.4 °C | 75 °C | **2× low** |
| c4 | temperature 100 m downstream | 26.0 °C | 57 °C | **2× low** |
| c5 | peak heat release | 26.6 MW | 15.5 MW | **1.7× high** |
| c5 | peak ceiling temperature | 227 °C | 580 °C | **2.6× low** |
| c5 | temperature 100 m downstream | 26.9 °C | 50 °C | **2× low** |
| c5 | backlayering at U15 | yes | no | **wrong, before activation only** |

Gas temperature is the defect that is left, and it now costs heat release
too: the fit can only warm the gas by growing the fire, so it accepts c5's
peak 70 % high to buy a few degrees. A tool that gets the gas three times too
cool will pass tenability criteria it should fail.

What changed on 2026-09-23, and why the pass count is not the point: the
anchors were corrected to their own Annex 2 figures (digitised at 250 dpi --
see each anchor's `input_notes` and `measured_notes`), which made c5 HARDER
to pass (its peak HRR was the text's "~20 MW"; Figure 18 shows 15.5), then
the calibration was refit. Every constant finished off its bounds.

---|---|---|---|---|
| c4 | peak heat release | 30.6 MW | 30 MW | pass |
| c4 | peak ceiling temperature | 283 °C | 830 °C | **3× low** |
| c4 | temperature 100 m downstream | 28.8 °C | 57 °C | **2× low** |
| c4 | heat flux at D15 | 2.61 kW/m² | 1 kW/m² | **2.6× high** |
| c4 | backlayering | yes | no | **wrong** |
| c5 | peak ceiling temperature | 197 °C | 580 °C | **3× low** |
| c5 | backlayering | yes | no | **wrong** |
| c6 | pools extinguished | no | yes | **wrong** |

Heat release is right in all three. Almost nothing else is. A tool that gets
the fire size right and the gas temperature three times too low will pass
tenability criteria it should fail.

---

## 1. Get real nozzle data — blocks almost everything else

`docs/nozzle-data-request.md` already lists what is needed. Nothing below can
be honestly completed until this arrives, because the calibration has absorbed
an assumed nozzle and cannot transfer off it.

- [ ] **K-factor** with units stated, plus the flow-versus-pressure table if
      flow is not a true square-root law
- [ ] **Sauter mean diameter (D32)** at three or more pressures, explicitly
      labelled D32 and not Dv50
- [ ] **Drop size distribution** by volume: Dv10/Dv50/Dv90, or a
      Rosin-Rammler spread, or the raw cumulative curve
- [ ] **Spray cone angle**, stated as full or half angle
- [ ] **Discharge velocity** at the orifice, or a note that it is estimated
- [ ] **How the drop data was measured** and at what distance from the orifice

Why this is first: the calibration note records that the assumed 90 µm spray
fully evaporates during its 0.9 m fall to the fuel top at any gas temperature
rise above about 100 K. Almost no water reaches the fuel, so three suppression
constants have no gradient left to fit and did not move during the fit at all.
The model cannot learn suppression from a spray that never lands.

## 2. Fill in the acceptance limits — the score means nothing without them

Seven of the nine Annex 7 criteria have no limit and are reported `unset`.

- [ ] `max_air_temp_c`
- [ ] `max_heat_flux_kwm2`
- [ ] `min_visibility_m`
- [ ] `max_fed`
- [ ] `max_co_ppm`
- [ ] `max_structure_exposure_length_m`
- [ ] `max_structure_exposure_duration_s`

These come from the authority having jurisdiction, from the tender or the fire
strategy. They are not ours to invent, and Annex 7 §7.1 says so outright. Until
they are set, `score.components.margin` averages over one boolean and reads
1.0, a perfect score off a single criterion.

## 3. Close the validation misses

Each is a real disagreement with a measured test, not a tolerance to widen.

- [x] **The tunnel was symmetric about the fire.** The downstream decay
      correlation was applied to `abs(x)`, so the model read 41 C both 15 m
      upstream and 15 m downstream where c4 measured 22 C and 75 C. Hot gas now
      reaches upstream only as far as the backlayer. `u15_temp_c` passes in
      both Class A cases.
- [x] **Ventilation ran on the fire's uncooled convective heat**, while the
      thermal field already removed the mist's share from the same heat.

- [ ] **Ceiling temperature is 3× low, and the cause is now pinned.** It is
      not the correlation. With the decay corrected, setting
      `thermal.ceiling_excess_coefficient` to 1.0 -- the published Li & Ingason
      form with no multiplier -- gives:

      | | modelled | measured |
      |---|---|---|
      | c4 peak ceiling | 897 C | 830 C |
      | c4 D15 | 89.8 C | 75 C |
      | c4 D100 | 49.3 C | 57 C |
      | c5 peak ceiling | 617 C | 580 C |
      | c5 D15 | 67.6 C | 55 C |
      | c5 D100 | 39.9 C | 50 C |

      All six inside tolerance (measured before the 2026-09-23 anchor
      corrections and refit; re-measure before relying on it). The same change takes suppressed heat release
      from 30.6 MW to 67.2 MW on c4 against 30 measured, because at real gas
      temperatures the reference nozzle's assumed 90 um spray evaporates before
      it reaches the fuel. **The 0.30 multiplier is buying correct heat release
      with incorrect temperatures.** Which way to hold that trade is a decision
      about the tool's purpose, and it stops being a trade at all once item 1
      lands: a measured spectrum with a real coarse tail delivers water at
      temperatures the assumed one cannot survive. Do not settle it by
      choosing a multiplier.

- [x] **The mist's cooling fraction was pinned to a fitted constant.** It sat
      at exactly 0.558 for 94 % of every run and at all three of 150, 200 and
      250 MW, so it could not respond to fire size, to more water or to a
      better nozzle. The constant's own note recorded that it had no surviving
      reference case. Replaced by the constraint it was standing in for: the
      spray cannot remove heat that is not there, and it slows itself as it
      cools the gas, so `chi = ratio / (1 + ratio)`. It now takes 38 distinct
      values over a run. **This cost one anchor comparison** -- c5's D15
      temperature fell from 34 C to 29.5 C against 55 C measured, crossing its
      40 % tolerance. That is a fitted constant's error becoming visible
      rather than a new error appearing, and it points at the same place
      everything else does: the assumed spray.

- [x] **Heat flux at D15 was 2.6× high.** Not the radiation model: the c4
      anchor entered activation with a 24 MW fire where Annex 2 Figure 9 shows
      5.85 MW, and the flux peaks just before activation. The anchor keeps the
      preset's ultrafast law and starts it at 243 s (c5: 102 s), matching the
      measured HRR at activation. Now 0.94 against 1.0 kW/m².
- [x] **Backlayering: definition.** Annex 2 judged it off the U15
      thermocouple tree (Figures 11, 20, 29); the comparison now asks whether
      the layer reached U15, not whether a metre of it formed. c4 passes.
- [x] **Backlayering: physics.** The smoke that turns upstream is cooled a
      second time by the upstream half of the spray (`mist.backlayer_heat_kw`),
      following the finding that mist lowers the critical velocity only when it
      cools the backlayering flow as well as the plume. No new constant. c6's
      layer now clears 28 s after activation, as the test reports.
- [ ] **c5 still backlayers before activation**: 39 m in the 60 s before the
      system starts, from a 3.6 MW growing fire at 1.25 m/s; Figure 20 is flat
      then. The Li, Lei & Ingason correlation is a steady-state length applied
      instantly to a growing fire; a real layer takes time to travel 15 m.
      Modelling that needs a front-propagation speed no anchor measures, so it
      is left as a miss rather than given a fitted lag.
- [x] **Pool extinction in c6.** Fine mist never reaches the pools (0.005
      mm/min landed), and wetting was the only way out. Added flame cooling:
      a pool goes out when the spray takes more of its heat than the flame can
      lose above FDS's 1427 °C critical flame temperature (29 %). An upper
      bound -- it counts all the heat the spray takes as taken from the flame.
      Pools out at 504 s against about 570 s in Figure 27.
- [x] **c6's inputs had no source.** Activation 300 s -> 175 s and velocity
      1.5 -> 2.35 m/s, both read off Figures 27-29 on the same convention the
      c4 and c5 anchors already used.

## 4. Earn the Tier 2 numbers

The CFD deck is now geometrically faithful to Tier 1 and instrumented like the
test, but that is self-consistency, not accuracy.

- [ ] **Calibrate `E_COEFFICIENT` against a measured suppression curve.** One
      generic value of 0.4 currently decides how much the mist suppresses the
      burner, and the suppressed heat release scales directly with it.
- [ ] **Run a grid convergence study.** The 0.6 m cell was chosen from D*/dx
      and from stability, never from a convergence study on this geometry. Run
      0.6 m against 0.4 m on a 250 s window and report the drift.
- [ ] **Run past the peak.** Every CFD run so far stops at 250 s, before the
      pumps even reach full pressure. The design peaks at 955 s. Until a run
      passes that, no CFD result describes the fire the system is sized for.
- [ ] **Replace the prescribed burner with pyrolysis**, or accept and state
      that fire growth is imposed rather than predicted. A prescribed fire
      cannot show the mist changing how the fuel burns, only how the gas cools.

## 5. The thing that actually settles it

- [ ] **A full-scale test with this nozzle.** Every number this tool produces
      is an extrapolation from reference cases that used a different
      manufacturer's head. `uv run solit2 report test-plan` already writes the
      inputs and the predictions in one document, which is what makes the test
      a test rather than a demonstration.

---

## What not to do

- Do not widen a tolerance to make `validate` pass. The tolerances are the
  claim.
- Do not tune `E_COEFFICIENT` until a design passes. It is the one knob that
  moves suppression directly, which is exactly why it must be set from a
  measurement and not from the answer wanted.
- Do not fill the `ahj` block from a vendor's report. See INDEPENDENCE.md.
- Do not read agreement between Tier 1 and Tier 2 as accuracy. They now share
  a geometry, a fuel and a radiative fraction by construction, so agreeing is
  the floor and not evidence.

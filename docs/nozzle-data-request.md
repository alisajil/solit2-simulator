# Nozzle data request — for the tunnel fire simulation model

We are running a SOLIT² Annex 7 full-scale test simulation of the water-mist system. The model
currently uses a **reverse-engineered** nozzle: the published SOLIT² test reports give neither a
K-factor nor a drop spectrum, so those values were back-figured to reproduce a reported application
density and nothing else. Every delivery number the model produces inherits that assumption.

Replacing it with real measured data for our own nozzle is the single largest accuracy improvement
available to us, and it is the first thing a reviewer will ask about.

Items are grouped by how much they matter. **Group 1 is what we cannot proceed properly without.**

---

## Group 1 — essential

### 1. K-factor

- **Value, and its units.** Please state the units explicitly: `L/min/bar^0.5` or `gpm/psi^0.5`.
  These differ by a factor of about 14.4 and it is the most common transcription error in this field.
- Over what **pressure range** was it measured?
- Is flow a true square-root law across that range (`Q = K·√P`), or does K drift at the extremes?
  If it drifts, please send the **measured flow-vs-pressure table** instead of a single K — the model
  can use the table directly and will be more accurate for it.
- **Production tolerance** on K — the ± band across units, not just the nominal.

### 2. Operating pressure

- Minimum, nominal and maximum working pressure at the **nozzle** (not at the pump).
- The pressure the droplet data below was measured at.

### 3. Droplet size — Sauter mean diameter (D32)

This drives evaporation and is the most sensitive single input in the model.

- **D32 (Sauter mean) in µm**, at a **minimum of three pressures** spanning the working range —
  ideally low / nominal / high.
- Please confirm it is **D32 (Sauter mean)** and not **Dv50 (volume median)**. These are routinely
  confused and differ substantially for a real spray. If only Dv50 is available, send it clearly
  labelled as Dv50 and we will convert, but tell us which it is.

### 4. Droplet size distribution

A spray is not one droplet size, and this is exactly where our current model is weakest — it treats
the whole spray as a single diameter, which makes water delivery behave as an all-or-nothing switch.
A real distribution is what makes the behaviour physical.

Any **one** of the following, at the same pressures as item 3:

- **Dv10, Dv50, Dv90** (volume percentiles), or
- the **Rosin-Rammler spread parameter `n`** with its characteristic diameter, or
- the **raw cumulative volume distribution** — the most useful of the three if you have it.

Please state whether percentages are by **volume** or by **number**. The model needs volume; number
distributions weight the fine droplets far too heavily and would give a materially wrong answer.

### 5. Spray cone angle

- The angle in degrees, and **whether it is the full included angle or the half angle**. Datasheets
  usually quote the full angle; our model takes the half angle, so an unlabelled figure risks a
  factor-of-two error in spray coverage.
- At what pressure, and does it change appreciably across the working range?

---

## Group 2 — important, with usable fallbacks

### 6. Discharge velocity

- Droplet or jet velocity **at the orifice**, in m/s, at the stated pressures.
- If not measured, say so — it can be estimated from pressure and discharge coefficient, but a
  measured value is better and we will flag an estimate as an assumption in the report.

### 7. How the droplet data was measured

- **Technique**: phase Doppler anemometry, laser diffraction (Malvern-type), or other.
- **Distance from the orifice** at which it was measured, and the position in the spray
  (on-axis, area-averaged, or a traverse). Droplet size varies strongly with distance from the
  orifice, so a number without a measurement distance cannot be used confidently.
- **Standard followed**, if any — for example the drop-size measurement protocol in an ISO 6182 part,
  FM 5560, or a UL listing procedure.
- Who performed the measurement, and is there a report we can cite?

### 8. Orifice configuration

- Number of orifices per nozzle head and their arrangement.
- Whether the quoted K-factor is **per head** or **per orifice** — another common ambiguity.

---

## Group 3 — useful for completeness

### 9. Approvals and listings

- Any FM, UL, VdS or other listing, and the specific application the listing covers
  (road tunnel, machinery space, etc.).
- Any third-party full-scale fire test the nozzle has been used in, with the report reference.

### 10. Installation limits the manufacturer states

- Minimum and maximum mounting height.
- Maximum spacing between heads, and whether that is a tested or an extrapolated figure.
- Any stated limit on the angle from vertical at which the head may be installed.

### 11. Water quality and strainer requirements

- Filtration grade required, and the orifice's minimum free passage.

---

## What we will do with it

- Items 1–5 go directly into the model as inputs and remove the current assumed nozzle entirely.
- Item 4 in particular unblocks a known defect: the model's water delivery currently collapses by
  roughly 100× across a 75 K change in gas temperature, because a single droplet size either survives
  the fall to the fuel or does not. A real distribution replaces that cliff with a physical curve.
- Items 6–8 are recorded as provenance so every number in the output can be traced to a measurement
  or flagged as an engineering assumption. We would rather record "estimated" honestly than present an
  unsourced figure as measured.

**If some of this is not measured yet**, tell us which — a clearly flagged gap is far more useful than
a plausible-looking placeholder, and we will mark those values as assumptions in the report rather
than let them pass as data.

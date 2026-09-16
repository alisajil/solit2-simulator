# Nozzle data — virtual flow test readout, 52 bar

Supplied by the user from their colleague's nozzle development work. Transcribed from the test-bench
readout image; anything not legible in that image is marked unknown rather than guessed.

**PROVENANCE: this is a VIRTUAL flow test — a simulation, not a physical bench measurement.** The
title says so outright. Every value below must be recorded in the model as simulated-source, not
measured, until a physical test confirms it. That distinction is the whole reason the model tracks
provenance at all.

## Test conditions

| | |
|---|---|
| Inlet pressure P1 | 52.2 bar g |
| Orifice ΔP (estimated) | 51.0 bar |
| Mounting height H | 6.5 m |
| Air | still (no longitudinal flow) |
| Phase | continuous discharge, window closed |
| Elapsed at readout | 388.0 s |

## Hydraulics

| | |
|---|---|
| Flow F1 | 38.5 L/min per head |
| K live / K mean / K declared | 5.33 / 5.34 / 5.34 |
| Orifices per head | 29 |
| Volume discharged | 249.0 L |
| Momentum flux | 54.2 N |
| Axial reaction | 38.6 N |

**K consistency check, done here rather than assumed:** 38.5 / sqrt(52.2) = **5.329**, which matches
the declared 5.34. So K is quoted against the **inlet** pressure, not the orifice ΔP — against ΔP it
would read 5.391. Units are therefore L/min/bar^0.5, confirmed by the arithmetic rather than by a
label.

## Spray

| | |
|---|---|
| Spray cone, full angle | 122° (stated as 2 x max ring angle) -> **half angle 61°** |
| Jet velocity, groups A/B/C/D | 79 / 101 / 101 / 78 m/s |
| Dv90 at 1 m, groups A/B/C/D | 181 / 95 / 95 / 157 µm |
| Spectrum | "transported ASM-015 classes" — a full spectrum exists but is not on this readout |

The head has **four orifice groups at different angles**, and they differ in both velocity and drop
size — the coarse groups (181 and 157 µm) sit at the outer angles and the fine ones (95 µm) elsewhere.

## Distribution / coverage

| | |
|---|---|
| Cell density, single head | 0.41 L/min·m² |
| Cell density, array | 1.64 L/min·m² |
| Array cell p10 | 0.28 L/min·m² |
| Collected in cell | 58.50 L |
| Area >= 0.5 L/min·m², single head | 20.3 m² |
| Radius r50 / r90 | 5.10 / 7.68 m |

## Against what the model currently assumes

The shipped `nozzle_solit2_reference` is back-figured from a reported application density and nothing
else. The differences are large:

| | assumed | this readout | ratio |
|---|---|---|---|
| K (L/min/bar^0.5) | 2.8 | **5.34** | 1.91x |
| cone half angle | 50° | **61°** | 1.22x |
| launch velocity | 25 m/s | **78–101 m/s** | ~3.6x |
| drop size | 90 µm SMD | Dv90 95–181 µm by group | not comparable — see gaps |

The launch-velocity difference matters most for the model's current top defect. Time of flight to the
fuel scales inversely with launch velocity, and evaporation scales with time of flight, so a 3.6x
faster launch means substantially less evaporation in transit — which attacks the delivery cliff
directly.

## Gaps — what is still needed before this can replace the assumed nozzle

1. **Dv50 (volume median)** at these conditions. This is the single most important missing number.
   Dv90 alone fixes only the coarse tail; it does not define the distribution.
2. **D32 (Sauter mean)**, which is what the evaporation physics actually consumes. If only volume
   percentiles exist, Dv10 + Dv50 + Dv90 is enough to fit a distribution and derive it.
3. **The ASM-015 class spectrum itself.** The readout says the spectrum was transported, so it exists
   somewhere in the tool that produced this. That would supersede items 1 and 2 entirely.
4. **At least two more pressures** — the model interpolates drop size against pressure and currently
   has a single point. Something like 35 and 70 bar would bracket the working range.
5. **Per-group flow split.** Four groups are named but the share of the 38.5 L/min each carries is not
   on the readout. Needed to weight them correctly.
6. **Confirmation of what "virtual" means here** — CFD, an empirical correlation, or a digital twin of
   a measured head — and whether any physical bench data exists to compare against.

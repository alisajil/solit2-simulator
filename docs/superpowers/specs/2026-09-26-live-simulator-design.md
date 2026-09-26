# Live simulator screen — design

**Status:** approved 2026-09-26 — "New landing 'Simulator'", "Dark app-wide", report after UI.
Reference look: the user's screenshot of a Streamlit + Plotly optimiser (dark instrument panel,
sidebar sliders and presets, a row of reading tiles, a "LIVE" pill with a monospace diagnostics
line, a 3D centre view, a row of live charts). Only the look is borrowed.

## Why

The wizard is right for the formal record (fire test, CFD, compliance, reports) but slow for the
engineer's question "what happens if I move this?". The Tier 1 engine runs a whole test in about
two seconds, so the answer can be on screen as the slider moves, and the test can be replayed from
ignition with every reading moving together.

## What the viewer sees

```
┌ sidebar ──────────────┬──────────────────────────────────────────────────────────┐
│ Test   [Class A|B]    │ ◉ SOLIT² VIRTUAL FIRE TEST · engine vX · Tier 1          │
│ Presets (design files)│ [peak HRR] [peak ceiling °C] [target] [activation] [score]│
│ Nozzle / Zones /      │ ● TIER 1 · PREDICTION   detect 103 s · activate 283 s ·   │
│ Ventilation sliders   │   criteria set 2/9 · calibration a1b2c3                   │
│ "Drag a slider — the  │ ┌ one animated figure ───────────────────┐ ┌ CFD · LIVE ┐ │
│  result updates"      │ │ gauges at t: HRR, ceiling °C, target   │ │ state chip │ │
│ [Open the wizard →]   │ │ flux, air m/s, water L/min, backlayer  │ │ progress   │ │
│                       │ │ 3D tunnel                               │ │ latest HRR │ │
│                       │ │ HRR vs free burn · station temps · flux │ └────────────┘ │
│                       │ │ ▶ Play  ──●── test clock                │                │
│                       │ └─────────────────────────────────────────┘                │
└───────────────────────┴──────────────────────────────────────────────────────────┘
```

- **Tiles** (static per run): peak HRR against the free-burn peak, peak ceiling temperature,
  target ignited or not, time to full pressure, and the score with how many of the nine Annex 7
  criteria are set ("score 7.8 · 2 of 9 criteria set").
- **Pill and diagnostics line:** `● TIER 1 · PREDICTION` and the run's events, the number of
  criteria set, and the calibration hash, in IBM Plex Mono.
- **Animated figure:** one Plotly figure holding every time-varying element, so a single Play
  button and a single time slider keep them in step, client-side, with no server round trips
  during playback (smooth on the remote server as well as locally).
  - Six gauges showing the engine's value at the current instant: HRR (MW), ceiling
    temperature (°C), target heat flux (kW/m²), effective air velocity (m/s), water flow
    (L/min), backlayering length (m).
  - A 3D tunnel (below).
  - Three charts with a cursor at the current instant: HRR with the engine's free-burn HRR,
    gas temperature at every station, heat flux at the target and U15.
- **CFD · LIVE panel:** if an FDS run of this exact design exists (its CHID is the design's SHA,
  `deck.chid`), its state, progress (simulated of T_END s), rate and latest HRR, read from the
  run's own files every 10 s. Otherwise "CFD not run for this design" and a button to the
  wizard's CFD step.

### The 3D tunnel

Built from the design and the worst-case trace, over the zoom window the 2D twin already uses
(`twin_canvas.core_window_m`, `WINDOW_M` for the full view):

- the tunnel shell (box or circular section from `Tunnel.shape`, extruded along the axis) and
  the carriageway;
- the fire load as its `Footprint` box at the mock-up centre, and the target where the design
  puts it; the flame's size and colour follow HRR over its own peak;
- nozzle heads at `Mounting.height_above_carriageway_m`, one line per row offset, at `pitch_m`;
  heads in the active sections turn to the mist colour once full pressure is reached, with a
  translucent spray volume per active section;
- a smoke band under the ceiling from the backlayering front to the window's downstream end,
  coloured by the engine's gas temperature at the stations and linearly interpolated between
  them; the band's **thickness is schematic** (the engine does not compute a layer depth) and the
  legend says so, as it says "interpolated between stations";
- the stations (U45 … D100) as labelled posts, and an airflow arrow labelled with `u_eff_ms`.

### Sidebar

- **Test:** Class A / Class B, selecting the compliance spec's test designs when one is loaded.
- **Presets:** one button per design file in `designs/` and `examples/` (non-design JSON is
  filtered out with `spec.is_design_payload`).
- **Parameters:** nozzle pressure, K-factor, mounting height, head pitch, section length,
  sections simultaneous, activation delay, ventilation velocity, test duration. The sliders use
  the **same session keys and assembly** as the Design step (its input renderers move to a
  shared `app/components/design_inputs.py`), so one design is shared by the simulator and the
  wizard.
- "Drag a slider — the result updates" and **Open the wizard →**.

## Behaviour

- A slider change assembles the design, validates it, runs `envelope.run` (cached by design
  SHA) and replays the worst case with `sim.run_once` (cached), exactly as the Result and Fire
  test steps do today.
- Frames are sampled at the twin's existing stride (`twin_canvas.TWIN_FRAME_STRIDE_S`); each
  frame updates only the traces that change.
- Navigation: a top-level view in session state — `simulator` (the default landing) or
  `wizard` — switched from a small header nav. The wizard's steps are unchanged. The CFD runs
  manager on its own branch adds a third view the same way.
- Theme: dark by default app-wide, from `.streamlit/config.toml`'s existing `[theme.dark]`
  palette; light stays available from Streamlit's settings. Every existing screen and figure is
  checked for legibility on dark (figures that pass `theme=None` get explicit colours from
  `app/palette.py`). Instrument styling (mono uppercase labels, tile cards, the pill's pulsing
  dot) lives in `app/theme.py`; the pulse stops under `prefers-reduced-motion`.

## Honesty rules (not negotiable)

- Every number shown is the engine's own output for this design; nothing is smoothed,
  extrapolated or invented. A value the engine does not compute is not shown.
- A gauge gets a red band only where the design's `ahj` block sets that limit. Gauge ranges
  come from the run's own peak, never from a threshold nobody set.
- The score always shows how many criteria are set; `gates_passed` is never shown as approval
  while `criteria_unset` is non-empty.
- The calibration note (`meta.calibration_note`) is visible on the screen.
- Schematic geometry (smoke thickness, spray volumes) is labelled schematic.

## Errors

| Condition | Behaviour |
|---|---|
| a slider combination the schema rejects | `st.error` naming the field and the rule; the last good result stays visible, marked "not the current settings" |
| an engine error | `st.error` with the message; no figure is drawn from partial data |
| no FDS run for the design | the CFD panel says so; nothing is estimated |
| an FDS run's files unreadable | the panel shows the file and the reason |

## Files

| File | Role |
|---|---|
| `app/views/simulator.py` | the landing screen: sidebar, tiles, pill, figure, CFD panel |
| `app/components/design_inputs.py` | input renderers shared by the Design step and the sidebar |
| `app/components/tunnel3d.py` | the 3D scene's traces for one frame |
| `app/components/live_figure.py` | the animated figure: gauges, 3D scene, charts, frames, Play |
| `app/components/cfd_live.py` | reads one FDS run's state and latest HRR for the panel |
| `app/streamlit_app.py`, `app/state.py` | the top-level view switch |
| `app/theme.py`, `.streamlit/config.toml` | dark default and instrument styling |

## Testing

- AppTest: the app opens on the simulator; the tiles show the result's peaks; moving a slider
  changes the design and the tiles; "Open the wizard" switches view and the Design step shows
  the same design.
- The figure has one frame per sampled step; frame k's gauge values equal the trace's values at
  that step; a gauge has a red band only when its `ahj` limit is set.
- 3D: the fire box equals the footprint; the smoke band starts at `-backlayer_m`; active heads
  appear only at or after full pressure.
- CFD panel: no run → "not run"; a synthetic run directory with the design's CHID → its state
  and progress; tests never start FDS.
- Figure size stays under a stated budget (checked in a test); the independence scan passes.

## Out of scope

An animated particle flow field; FDS smoke rendering (Smokeview); a phone layout beyond
Streamlit's own stacking. The virtual test report is its own spec
(`2026-09-26-virtual-test-report-design.md`) and reuses `tunnel3d` and `live_figure`.

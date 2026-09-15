# solit2

**An independent evaluator of fixed fire-fighting systems in road tunnels,
against the SOLIT² Engineering Guidance, Annex 7.**

- **No affiliation with any manufacturer.** The tool ships no product data and
  endorses nothing.
- **All product and project data are user inputs.** Tunnel geometry, nozzle
  performance, hydraulics and every acceptance limit are supplied by whoever
  runs it.
- **The shipped templates are placeholders, not data.** They exist so the tool
  runs out of the box and immediately shows a result that is obviously a
  placeholder. A result computed from one says so in its own output.

See [INDEPENDENCE.md](INDEPENDENCE.md) for the three rules that keep it neutral
and the tests that enforce them.

## The principle

> The tool ships the standard. The user supplies the product and the project.

| Ships with the tool | Supplied by the user |
|---|---|
| The physics engine | Tunnel geometry |
| SOLIT² Annex 7 test method and fire loads | Nozzle performance |
| SOLIT² acceptance-criteria structure | Every acceptance limit (via the `ahj` block) |
| The SOLIT² reference test cases | Hydraulic and electrical constraints |
| Generic parametric templates | Any project or product data |

Anything traceable to one manufacturer or one project is an illustration, lives
under `examples/`, is labelled as such, and is never a default.

## Install and run

Python 3.12 via [uv](https://docs.astral.sh/uv/):

```bash
uv sync
uv run solit2 run examples/designs/road-tunnel-twin-bore.json
```

Subcommands:

| Command | What it does |
|---|---|
| `solit2 run <design.json>` | Score a design; result JSON on stdout |
| `solit2 history` | Leaderboard of recorded runs |
| `solit2 validate` | Check the engine against the published reference fire tests |

## Writing a design

A design names a preset per block and overrides whatever it needs; the preset
supplies the rest.

```json
{
  "meta": {"name": "my-tunnel-rev-a"},
  "tunnel":     {"preset": "template", "length_m": 2400.0},
  "fire":       {"preset": "hgv_150mw"},
  "nozzles":    {"preset": "my_nozzle"},
  "hydraulics": {"preset": "template"},
  "zones":      {"section_length_m": 30.0, "sections_simultaneous": 3,
                 "activation_delay_s": 60.0, "pump_ramp_s": 30.0,
                 "duration_min": 60.0},
  "ventilation": {"mode": "longitudinal", "velocity_range_ms": [2.5, 4.0]},
  "detection":  {"type": "linear_heat", "threshold_c": 60.0,
                 "sensor_spacing_m": 25.0},
  "ahj":         {"max_air_temp_c": 60.0, "max_fed": 0.3},
  "constraints": {"max_pump_power_kw": 400.0}
}
```

Presets are looked up in `solit2/presets/` first, then `examples/presets/`.

### `ahj` — the acceptance limits

Annex 7 §7.1 leaves every absolute value to the authority having jurisdiction,
so every field here is unset until you set it, and an unset limit is **reported
as unset** — it never silently passes a design. See INDEPENDENCE.md rule 2.

### `constraints` — your own engineering limits

Site and procurement limits: feeder capacity, water volume, a procurement
pressure band. These are checked and reported in their own `constraints` block
of the result. **A breached constraint is not a SOLIT² failure** and never
appears in `gates_failed`.

## What ships in `solit2/presets/`

| Preset | What it is |
|---|---|
| `tunnel_template`, `nozzle_template`, `hydraulics_template` | Placeholders. Replace before any result means anything. |
| `tunnel_solit2_test` | The Annex 7 test tunnel — the standard, not a project. |
| `fire_hgv_150mw`, `fire_pool_60mw` | The Annex 7 Class A and Class B fire loads. |
| `nozzle_solit2_reference` | Assumed values, used only to reproduce the published reference cases. |
| `calibration.json` | The engine's constants and what each one rests on. |

## What ships in `examples/`

Illustrations of how a design is assembled. Never defaults, never
recommendations, and safe to ignore.

| File | What it illustrates |
|---|---|
| `designs/road-tunnel-twin-bore.json` | A complete twin-bore assessment, with site constraints declared |
| `designs/solit2-test-protocol.json` | The Annex 7 test itself: §5.2.7 mandates **both** 1.5 m/s and 3.0 m/s, so both are run |
| `presets/tunnel_twin_bore_11m.json` | An 11 m bored section |
| `presets/nozzle_bimodal_example.json` | A two-mode head |
| `presets/nozzle_single_mode_example.json` | A single-mode head |
| `presets/hydraulics_example.json` | A pumped ring main |

## Reading a result

| Block | What it holds |
|---|---|
| `meta` | Engine version, design hash, and the calibration provenance (`calibration_fitted`, `calibration_anchors`, `calibration_note`) |
| `criteria` | The SOLIT² Annex 7 criteria. `status` is `pass`, `fail` or `unset`. |
| `constraints` | Your own declared limits, judged separately. Never gates. |
| `score` | `gates_passed` / `gates_failed` reflect the SOLIT² criteria only; `criteria_unset` lists what nobody has ruled on. |
| `warnings` | Placeholder data in use, breached constraints, thin critical-velocity margin |

## Development

```bash
uv run pytest
uv run ruff check .
```

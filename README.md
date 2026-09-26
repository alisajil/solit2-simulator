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
| `solit2 report test-plan <design.json>` | Markdown: test inputs and predicted outcomes |
| `solit2 report correlation --test A.json --site B.json` | Markdown: one design's criteria across two runs, side by side |
| `solit2 fds-deck <design.json>` | Write the FDS input deck for a design |
| `solit2 fds-status <run-dir>` | Progress of an FDS run |
| `solit2 run <design.json> --engine fds` | Tier 2: write the deck, run FDS, parse the result back into the same result JSON |

`--engine fds` **blocks for hours, not seconds.** It writes the deck into a
directory named after the design hash beside the history file, launches FDS in
the background and then polls until the run finishes. It needs a real FDS
install -- `fds` and `mpiexec` on `PATH`, or `SOLIT2_FDS_BIN` pointing at the
binary -- and refuses with a named pre-flight problem when one is missing. To
launch and walk away instead, generate the deck with `fds-deck`, start FDS
yourself, and follow the run with `fds-status <run-dir>`.

A Tier 2 result carries `warnings` naming every quantity FDS did not measure:
the free-burn HRR curve, the stepped-versus-smooth section area, the
critical-velocity penalty that cannot apply, and the single ventilation
velocity it covers in place of Tier 1's envelope. Read them before comparing
the two tiers.

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
| `tunnel_solit2_test` | The SOLIT² test gallery **as tested** (7.50 × 5.20 m, 39.0 m²) — the standard, not a project. Annex 2 §2 is quoted in the preset's own note, including that the 5.20 m is a suspended ceiling and the 7.50 m comes from walls added around the fire area. |
| `fire_hgv_150mw`, `fire_pool_60mw` | The Annex 7 Class A and Class B fire loads. |
| `nozzle_solit2_reference` | Assumed values, used only to reproduce the published reference cases. |
| `calibration.json` | The engine's constants and what each one rests on. |

## What ships in `examples/`

Illustrations of how a design is assembled. Never defaults, never
recommendations, and safe to ignore.

| File | What it illustrates |
|---|---|
| `designs/road-tunnel-twin-bore.json` | A complete twin-bore assessment, with site constraints declared |
| `designs/solit2-test-protocol.json` | Annex 7 Table 4 rows 1–2 (**mandatory**): Class A HGV **with** tarpaulin, at both 1.5 m/s and 3.0 m/s (§5.2.7 mandates both) |
| `designs/solit2-test-protocol-nocover.json` | Table 4's two **optional** rows: the same mock-up without the tarpaulin, at both velocities |
| `designs/solit2-test-protocol-class-b.json` | Table 4 rows 3–4 (**mandatory**): Class B liquid fire, min 50 MW, at both velocities |
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

## Running the app

    uv run streamlit run app/streamlit_app.py

Everyone logs in first. A visitor signs up with a name, organisation, email and a password of
at least 12 characters, then waits until an admin approves the account (see
[Accounts](#accounts)). A browser refresh asks for the login again, and a session left idle for
eight hours ends.

Once you are in, the app opens on the **Simulator**: presets and design knobs in the sidebar, the run's peaks in
tiles, and one figure that replays the Tier 1 virtual fire test — press ▶ Play and six gauges,
a 3D tunnel and three charts move together. Every value is the engine's own; a gauge has a red
band only where the design's `ahj` block sets that criterion's limit. The **Wizard** keeps the
formal record (fire test, CFD, compliance, reports) and **CFD runs** manages the FDS fleet.
The app follows your computer's light or dark setting — the dark palette on a dark system, the light one on a light system — and Streamlit's settings menu can switch it either way.

The Wizard is a five-step flow, each step computed from the one before it -- nothing
is downloaded or uploaded in between:

1. **Design** -- pick presets and the parameters an engineer varies, with a live
   hydraulics summary of what they add up to.
2. **Result** -- the Tier 1 verdict, which runs on arrival: banner, per-criterion
   chips, peaks, acceptance table, timeseries and the run-history leaderboard.
3. **Fire test** -- the worst case replayed as a to-scale digital twin: HMI
   readouts and status lamps, an animated tunnel section with the mock-up,
   target, heads, mist and Annex 7 instrument masts, an event timeline and
   per-station temperatures.
4. **CFD verify** -- Tier 2. Pre-flight, a simulated-window picker, the FDS run
   in the background with live progress, its temperature/smoke/mist slices drawn
   on the same twin, a button to open the desktop Smokeview, and Tier 1 vs Tier 2.
5. **Reports** -- the test plan, a correlation against an automatically built
   test-facility twin of the same system, and every export.

Views call the engine in-process -- the same Python functions the CLI
(`solit2 run`, `solit2 validate`, `solit2 report`) uses. There is no
separate API server.

## Accounts

The app asks everyone to log in, and an admin approves every new account as **team** (the
shared project: designs, runs, the CFD runs manager) or **customer**. Customers see a holding
screen until customer workspaces open.

The **Admin** screen (admins only) lists the sign-ups waiting for approval — approve as team or
customer, or reject — and every account with its role, state and last login, with Disable,
Re-enable and Temporary password. A temporary password is shown once, to pass on privately.
Every admin action is kept in the trail at the bottom of the screen. Sign-ups are not verified:
confirm each one with the person, through a channel you already trust, before you approve it.

Create the first admin on the server, from the app's checkout and with the same
`SOLIT2_DATA_DIR` the app's service uses:

- Run the command as the OS user the app's service runs as — the store is owner-only (0600), so
  one created or first opened by another user, root included, becomes unavailable to the app.
- Set `SOLIT2_DATA_DIR` explicitly in the app's service unit; the default `data/` depends on the
  working directory the service happens to start from.
- Run it from the app's checkout with its editable install. It imports `app.accounts`, which the
  published wheel does not carry (the wheel packages only `solit2`).

It asks for the password twice; the password is never an argument:

    SOLIT2_DATA_DIR=/path/to/app-data uv run solit2 accounts create-admin \
        --email you@example.com --name "Your Name" --organisation "Your organisation"

Accounts live in one SQLite file, `$SOLIT2_DATA_DIR/accounts.db` (default `data/accounts.db`,
never committed), readable by its owner only. Back it up into a directory that is owner-only
too — the backup file's own permissions depend on the sqlite3 build and the umask, not on the
original file's mode:
`sqlite3 "$SOLIT2_DATA_DIR/accounts.db" ".backup accounts-backup.db"`.

A forgotten password is reset by an admin, who issues a temporary one; the account must choose
its own at its next login. An admin who forgets their own asks another admin, or makes a second
admin with the command above.

The server keeps its IP allowlist in front of the app until a security review of the accounts
has passed.

## Development

```bash
uv run pytest
uv run ruff check .
```

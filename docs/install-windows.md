# Installing on Windows

Written for Windows 11 on a 6-core desktop. Everything the simulator needs to
run Tier 1 ships in this repository; FDS is a separate install and is only
needed for Tier 2.

**This guide has not been executed on a Windows machine.** The Python code
carries no platform-specific paths, and the two places that did assume POSIX
(how a run is launched, and how its process is checked) now have Windows
branches. Where a step below is an expectation rather than something observed,
it says so.

---

## 1. Tools

Open **PowerShell** (no administrator rights needed for any of this).

```powershell
winget install --id Git.Git -e
winget install --id astral-sh.uv -e
winget install --id GitHub.cli -e
```

Close and reopen PowerShell so the new commands are on `PATH`, then check:

```powershell
git --version; uv --version; gh --version
```

You do not need to install Python. `uv` reads `.python-version` in the
repository and fetches CPython 3.12 itself.

## 2. The repository

It is private, so authenticate first:

```powershell
gh auth login
```

Choose GitHub.com, HTTPS, and authenticate in the browser. Then:

```powershell
cd $HOME
gh repo clone alisajil/solit2-simulator
cd solit2-simulator
```

## 3. Dependencies

```powershell
uv sync
```

This creates `.venv` and installs the exact versions in `uv.lock`, so the
Windows machine runs the same package set as the Mac.

## 4. Check it works before trusting it

```powershell
uv run pytest -q
```

Everything should pass. Then run the engine once end to end:

```powershell
uv run solit2 run designs/og-dbr-rev0.json
```

That is Tier 1 and takes seconds. It needs no FDS.

## 5. The application

```powershell
uv run streamlit run app/streamlit_app.py
```

It prints a `http://localhost:8501` address. Open that in a browser.

To stop it, press Ctrl+C in the PowerShell window.

---

## Tier 2 (FDS) — optional

Tier 1 is complete without this. Install FDS only when you want to run CFD on
this machine.

Download the Windows installer from the FDS releases page
(<https://github.com/firemodels/fds/releases>) and run it. It installs
`fds.exe`, `smokeview.exe` and a bundled MPI, and puts them on `PATH`.

Reopen PowerShell and confirm the simulator can find them:

```powershell
uv run python -c "from solit2.engines.fds import runner; print(runner.preflight() or 'FDS ready')"
```

An empty list, printed as `FDS ready`, means the CFD step will offer to start
runs. Anything else names exactly what is missing.

If the installer did not put FDS on `PATH`, point the simulator at it directly
instead:

```powershell
$env:SOLIT2_FDS_BIN = "C:\Program Files\firemodels\FDS6\bin\fds.exe"
```

### What to expect from this hardware

The deck splits the tunnel into 10 meshes and runs one MPI rank per mesh. An
i5-12400F has **6 physical cores** (12 threads), so 10 ranks oversubscribe it.
It will run, and each rank will be slower than it would be on a machine with a
core to itself.

For scale, measured on an 11-core Mac: 250 seconds of simulated fire took
81 minutes. A full 60-minute fire is a multi-day run. This is normal for FDS at
this resolution and is why the CFD step defaults to a 20-minute window rather
than the full discharge.

If you want the mesh count to match the cores, `MESH_COUNT` in
`solit2/engines/fds/deck.py` must divide the window evenly — 5 meshes of 200
cells fits 6 cores well. Changing it changes every generated deck, so the two
golden-deck tests will need regenerating:

```powershell
uv run python tests/fixtures/fds/make_fixture.py
uv run pytest -q
```

Treat that as a deliberate change to the model, not a tuning knob: decks
generated before and after are not comparable, and the result's own warnings
will say so.

---

## Keeping it up to date

```powershell
git pull
uv sync
uv run pytest -q
```

`uv sync` after a pull picks up any dependency change; the test run is the
cheapest way to know the machine is still in a state you can trust.

## If something fails

- **`uv` not recognised** — PowerShell was not restarted after the install.
- **`gh repo clone` refuses** — the account behind `gh auth login` does not
  have access to the private repository.
- **Tests fail on a fresh clone** — report the failure rather than working
  around it. A clean checkout passing on one machine and failing on another is
  a finding about the code, not about the machine.
- **The CFD step says FDS is missing after installing it** — PowerShell caches
  `PATH`; reopen it, and if that does not help set `SOLIT2_FDS_BIN` as above.

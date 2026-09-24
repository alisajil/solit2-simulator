# Running the FDS campaign on a dedicated server

Tier 2 (`--engine fds`) is hours per run and this project's Mac is not where
that should tie up a machine. This is the walkthrough for running it instead
on one dedicated server: a single box, no cluster, no orchestrator -- FDS
runs directly on the host, queued by a shell script and supervised by
systemd so a run outlives an SSH session or a reboot.

Everything below assumes the server the user actually provisioned: Hetzner
Cloud, Ubuntu 24.04, 32 vCPU, 62 GB RAM, ~387 GB disk, time zone set to
Asia/Kolkata, firewalled to SSH only. If your box differs, the commands are
the same; the resource figures in step 8 and the systemd unit are the ones
to adjust.

Costs are not estimated anywhere in this document. Hetzner bills hourly;
check the current rate and the running total in the Hetzner console
yourself.

---

## 1. Create the server

In the Hetzner Cloud console: choose an EU location, Ubuntu 24.04, and add
your own SSH public key at creation time so you never type a password. This
is a manual console step -- nothing in this repo provisions the server
itself.

## 2. Firewall: SSH only

Either in the Hetzner console's firewall settings or with `ufw` on the box,
allow inbound `22/tcp` and nothing else. This server runs no web service and
its Kubernetes-flavoured cousin was deliberately dropped in favour of this
simpler, direct-host setup -- there is no API or dashboard port to protect
because none is opened. Never expose anything else on this box's public
interface; every command below reaches it over the same SSH connection you
provision the firewall for.

## 3. Log in

```
ssh root@<server-ip>
```

## 4. Install the FDS 6.11 release (pinned, not "latest")

The exact asset, verified against the `firemodels/fds` GitHub Releases API
on 2026-09-24 (`gh api repos/firemodels/fds/releases`): release
**FDS-6.11.1** (published 2026-07-10, the newest non-prerelease 6.11.x tag),
Linux installer asset **`FDS-6.11.1_SMV-6.11.2_lnx.sh`**, 190,069,552 bytes,
at:

```
https://github.com/firemodels/fds/releases/download/FDS-6.11.1/FDS-6.11.1_SMV-6.11.2_lnx.sh
```

Download it, check it against the sha256 digest GitHub's own Releases API
reports for this asset (`gh api repos/firemodels/fds/releases/tags/FDS-6.11.1`
-- also independently reproduced when this doc was written), then run it.
Chained with `&&` rather than run as three separate lines, so a checksum
mismatch stops the sequence right there instead of the installer running
anyway on a corrupted or tampered download:

```
curl -fsSL -o FDS-6.11.1_SMV-6.11.2_lnx.sh \
  https://github.com/firemodels/fds/releases/download/FDS-6.11.1/FDS-6.11.1_SMV-6.11.2_lnx.sh \
  && echo "ba8793b974150fdb778b3db0b69ab8db4e4668d5c52987a317e7f5ed58102ea0  FDS-6.11.1_SMV-6.11.2_lnx.sh" | sha256sum -c - \
  && printf "\n2\nyes\nyes\nyes\n" | bash FDS-6.11.1_SMV-6.11.2_lnx.sh
```

The installer is interactive by default (a license page, then a small menu),
which is what the `printf` sequence above answers on its behalf -- verified
against a real install on the target server, where it installs to
`/opt/FDS/FDS6` and `fds` afterwards reports
`FDS-6.11.1-0-gff928db-release` with Intel MPI 2021.17 bundled underneath it
at `/opt/FDS/FDS6/bin/intelmpi/bin/mpiexec`. If a future release changes the
menu's wording or step count, that `printf` sequence needs re-checking
against it rather than assumed to still match. Source the vars script once
to confirm `fds` resolves on `PATH`:

```
source /opt/FDS/FDS6/bin/FDS6VARS.sh
fds
```

(Running `fds` with no deck argument prints its own version banner and
exits -- that banner is what `solit2.engines.fds.runner.fds_version` reads
back out of a run's log later, so it is worth glancing at here too.)

A `source` line in `.bashrc` only helps an interactive shell -- the systemd
unit in step 8 does not read it, which is why that unit sets `PATH`
explicitly instead.

## 5. Install `uv`

```
curl -LsSf https://astral.sh/uv/install.sh | sh
```

This is Astral's own documented installer, non-interactive by default
(confirmed against `docs.astral.sh/uv/reference/installer/`); it installs to
`/root/.local/bin` (running as root) and does not need `UV_INSTALL_DIR`
pointed anywhere unusual for a single-purpose server like this one.

No separate MPI package install is needed: step 4's installer bundles Intel
MPI at `/opt/FDS/FDS6/bin/intelmpi/bin/mpiexec`, and that is the binary
`solit2 fds-exec` finds once `PATH` includes it (the systemd unit in step 8
sets this explicitly; an interactive shell gets it from `FDS6VARS.sh`).

## 6. Bring the repo over -- rsync from your Mac, not GitHub credentials on the server

```
rsync -az --exclude .venv --exclude runs -e ssh \
  /Users/sajil/Solit2_simulator/ root@<server-ip>:/opt/solit2/
```

The server never needs your GitHub SSH key or a personal access token --
`rsync` only needs the same SSH access you already used to log in, and the
firewall from step 2 means nothing else can reach it to ask.

## 7. Write decks -- on your Mac or on the server, either works

`solit2 fds-deck` / `fds-grid-study` / `fds-calibrate-e` are pure Python; none
of them need FDS installed to WRITE a deck, only `run --engine fds` (or
`fds-exec`, below) needs the binary. Run the same command in either place:

```
uv run solit2 fds-grid-study designs/<design>.json \
  --dx 1.2 0.75 0.6 --t-end 600 --out runs/<study>
```

If you wrote them on the Mac, rsync just the run directories over. Each one
must carry `deck.fds`; also copy the design JSON in as `design.json` next to
it if this run may ever need to resume after an interruption --
`solit2 fds-exec` regenerates a `RESTART=.TRUE.` deck from that file when it
finds restart files but no other way to know what design produced them (see
`solit2/engines/fds/exec_run.py`):

```
rsync -az runs/<study> root@<server-ip>:/opt/solit2/runs/
cp designs/<design>.json runs/<study>/<run-name>/design.json   # per run dir, before the rsync above
```

## 8. Enqueue the runs

```
ssh root@<server-ip>
cd /opt/solit2
mkdir -p /var/lib/solit2-cfd
printf '%s\n' \
  runs/<study>/dx_1.20 \
  runs/<study>/dx_0.75 \
  runs/<study>/dx_0.60 \
  > /var/lib/solit2-cfd/queue.txt
cp deploy/systemd/solit2-cfd.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now solit2-cfd.service
```

`scripts/cfd_queue.sh` (what the unit runs) takes every path in that queue
file and runs at most `SOLIT2_CFD_PARALLEL` of them at a time through
`solit2 fds-exec` -- 3 by default, set in the unit file. Each run dir in
today's decks needs `MESH_COUNT` (10) MPI ranks, so three concurrent runs is
the whole 32-vCPU budget spent once; watch `htop`/`free -h` during the first
run and lower `SOLIT2_CFD_PARALLEL` in the unit if runs are memory-starved
rather than CPU-bound, since nothing here enforces a per-run memory ceiling
the way a container scheduler would.

Three concurrent `mpiexec`s is also why the unit sets `I_MPI_PIN=0`: Intel
MPI's default pins each run's ranks to cores 0..9, so without this every
concurrent run would pile onto the SAME first ten cores instead of spreading
across the 32 available. `I_MPI_PIN=0` leaves placement to the OS scheduler
instead. A hand-launched parallel set outside the queue (not going through
`cfd_queue.sh`) can do better than "off" -- give each `mpiexec` its own
`I_MPI_PIN_PROCESSOR_LIST`, e.g. `0-9`, `10-19`, `20-29` for three ten-rank
runs, which reserves disjoint cores per run rather than leaving it to the
scheduler; the queue itself does not do this because it does not know in
advance which of its `SOLIT2_CFD_PARALLEL` slots a given run dir will land
in.

Two more guards worth knowing about before the first run: `cfd_queue.sh`
takes an `flock` on each run dir before calling `fds-exec`, so a hand-run
invocation that happens to overlap the unit's never double-runs the same
directory: the losing side logs "already running, skipped" and moves on.
And a run dir that fails three times in a row is skipped rather than
retried forever -- "failed 3 times, skipped; inspect run.out" in its
`queue.log` -- because `Restart=on-failure` alone would otherwise have the
unit relaunch a genuinely broken run (a bad deck, a full disk) on an
infinite loop; `StartLimitBurst=3` within `StartLimitIntervalSec=3600` is
the matching, coarser guard one level up, for when the whole unit itself is
what keeps failing to start.

## 9. Watch it

```
journalctl -u solit2-cfd.service -f
tail -f runs/<study>/*/queue.log
uv run solit2 fds-status runs/<study>/dx_0.60
```

An SSH disconnect does not stop anything -- the queue runs under systemd,
not your shell. A reboot brings the unit back up (`Restart=on-failure` plus
`systemctl enable`), and `cfd_queue.sh` skips whatever `solit2 fds-status`
already reads as `done` and resumes the rest from their own restart files,
so a re-run of the same queue file never repeats finished work.

## 10. Bring results back

```
rsync -az root@<server-ip>:/opt/solit2/runs/<study> runs/
```

## 11. Read the reports locally

```
uv run solit2 fds-grid-study designs/<design>.json --dx 1.2 0.75 0.6 --t-end 600 \
  --out runs/<study> --report
```

The same command that wrote the decks in step 7, run again with `--report`:
it reads whatever finished and writes `runs/<study>/report.md` and
`report.json` from what is actually on disk, on your Mac, where you can read
it without an SSH session open. `fds-calibrate-e --report` works the same
way for a calibration sweep.

## 12. Remove the server when done

Delete it from the Hetzner console once the results are pulled back in step
10. Check the console for what the run actually cost -- this document does
not estimate it.

---

## Reference

- `solit2 fds-exec RUN_DIR [--t-end S]` -- runs FDS for one run directory in
  the foreground until it finishes or fails; resumes from restart files when
  present (needs `design.json` alongside `deck.fds`, see step 7); writes an
  IST-stamped line to `RUN_DIR/exec.log` at start, on a resume, and at the
  end; exits non-zero if FDS did not complete. See
  `solit2/engines/fds/exec_run.py`.
- `SOLIT2_MPIEXEC_ARGS` -- extra flags `fds-exec` passes to `mpiexec` (e.g.
  `--oversubscribe`), read fresh at every launch; unset by default.
- `scripts/cfd_queue.sh RUN_DIR [RUN_DIR ...]` -- runs several run
  directories through `fds-exec`, `SOLIT2_CFD_PARALLEL` (default 3) at a
  time, skipping ones `fds-status` already reads as done, skipping (not
  double-running) ones an overlapping invocation already holds the
  `.fds-exec.lock` on, and skipping ones that have failed
  `MAX_FAILURES` (3) times in a row until someone looks at them. Each run
  dir gets its own `queue.log` with an IST-stamped line per start, finish
  (or skip) and exit code.
- `deploy/systemd/solit2-cfd.service` -- the unit template step 8 installs;
  read the comments at its top before changing paths. Sets
  `TimeoutStartSec=infinity` (a oneshot unit's default start timeout would
  otherwise kill an hours-long run), `StartLimitIntervalSec`/
  `StartLimitBurst` to bound the unit's own restarts, and `I_MPI_PIN=0` so
  concurrent runs do not all pin to the same cores.
- This server exposes SSH only. Nothing in this deployment opens another
  port, and nothing here needs one.

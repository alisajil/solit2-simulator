"""`scripts/tier2_campaign.sh` owns exactly two things: refusing to start on
battery power, and wrapping the run in `caffeinate -i -s`. Both are tested
here against FAKE `pmset`/`caffeinate`/`uv` binaries on PATH, so the test
never depends on this machine's actual power state and never launches a real
`solit2 fds-campaign` (which would need FDS).
"""
import os
import stat
import subprocess
from pathlib import Path

SCRIPT = Path("scripts/tier2_campaign.sh").resolve()


def _make_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _fake_bin(tmp_path: Path, *, on_battery: bool) -> tuple[Path, Path]:
    """A directory of stand-ins for pmset, caffeinate and uv, put first on
    PATH. `uv` logs its own arguments instead of doing anything -- that log
    is the whole assertion surface."""
    bindir = tmp_path / "bin"
    bindir.mkdir()
    # Forced to "Darwin" regardless of the platform actually running this
    # test: the script's battery guard is gated on it, and the test must
    # exercise that branch deterministically rather than depend on where
    # pytest happens to run.
    _make_executable(bindir / "uname", '#!/usr/bin/env bash\necho Darwin\n')
    batt_line = ("Now drawing from 'Battery Power'" if on_battery
                else "Now drawing from 'AC Power'")
    _make_executable(bindir / "pmset", f'#!/usr/bin/env bash\necho "{batt_line}"\n')
    # A real caffeinate takes its own single-letter flags before the command
    # it wraps; this fake skips them the same way, then execs what is left,
    # exactly like the real one running the wrapped command to completion.
    _make_executable(bindir / "caffeinate",
                     '#!/usr/bin/env bash\n'
                     'while [[ $# -gt 0 && "$1" == -* ]]; do shift; done\n'
                     'exec "$@"\n')
    log = tmp_path / "uv_called.log"
    _make_executable(bindir / "uv", f'#!/usr/bin/env bash\necho "$@" >> "{log}"\nexit 0\n')
    return bindir, log


def _run_script(tmp_path: Path, args: list[str], *, on_battery: bool):
    bindir, log = _fake_bin(tmp_path, on_battery=on_battery)
    env = {**os.environ, "PATH": f"{bindir}:{os.environ['PATH']}"}
    proc = subprocess.run(["bash", str(SCRIPT), *args],
                          capture_output=True, text=True, env=env)
    return proc, log


def test_refuses_on_battery_power_without_allow_battery(tmp_path):
    proc, log = _run_script(tmp_path, ["design.json", "--out", "x"], on_battery=True)
    assert proc.returncode == 1
    assert "battery power" in proc.stderr.lower()
    assert "--allow-battery" in proc.stderr
    assert not log.exists(), "must refuse before touching fds-campaign at all"


def test_allow_battery_bypasses_the_refusal_and_still_wraps_in_caffeinate(tmp_path):
    proc, log = _run_script(tmp_path, ["design.json", "--out", "x", "--allow-battery"],
                            on_battery=True)
    assert proc.returncode == 0, proc.stderr
    assert log.exists()
    assert log.read_text().strip() == "run solit2 fds-campaign design.json --out x"


def test_runs_normally_on_ac_power_with_no_flag_needed(tmp_path):
    proc, log = _run_script(tmp_path, ["design.json", "--out", "x"], on_battery=False)
    assert proc.returncode == 0, proc.stderr
    assert log.read_text().strip() == "run solit2 fds-campaign design.json --out x"


def test_allow_battery_is_consumed_not_forwarded(tmp_path):
    _, log = _run_script(tmp_path, ["design.json", "--out", "x", "--allow-battery"],
                         on_battery=False)
    assert "--allow-battery" not in log.read_text()


def test_every_other_flag_is_forwarded_verbatim_and_in_order(tmp_path):
    proc, log = _run_script(
        tmp_path,
        ["d.json", "--grid-dx", "1.2", "0.75", "0.6", "--grid-t-end", "600", "--out", "runs/x"],
        on_battery=False)
    assert proc.returncode == 0, proc.stderr
    assert log.read_text().strip() == (
        "run solit2 fds-campaign d.json --grid-dx 1.2 0.75 0.6 --grid-t-end 600 --out runs/x")

"""Pre-flight, launch and status for an FDS run.

Every check here is a filesystem or environment lookup, so the whole module is
testable by monkeypatching `shutil` and the environment -- which is the only way
it CAN be tested, since no FDS install exists yet.
"""
from __future__ import annotations

import os
import re
import shutil
import subprocess
import time
from datetime import datetime
from pathlib import Path

BIN_ENV = "SOLIT2_FDS_BIN"
PID_NAME = "fds.pid"
# A run outlives the app that started it -- hours long, and the CFD step polls
# it rather than holding it open. `start_new_session` does that on POSIX and is
# silently ignored on Windows, where a child dies with its console instead, so
# Windows needs the equivalent creation flags spelled out.
_DETACHED = ({"creationflags": 0x00000008 | 0x00000200}   # DETACHED_PROCESS | NEW_PROCESS_GROUP
             if os.name == "nt" else {"start_new_session": True})
# How long a run may write nothing before it is reported as not advancing.
# FDS writes a progress line every 100 time steps; a 220k-cell road-tunnel deck
# on an 11-core machine managed about one line every five minutes, so this is
# generous enough not to trip a merely slow run and short enough to catch a
# wedged one within one sitting.
# It exists because a deadlocked MPI run keeps every process ALIVE: one real run
# sat at 935.8 s of 3600 s for seven hours with nine ranks spinning at 100% CPU,
# and the app reported "running -- 26%" for all of it.
STALL_AFTER_S = 900.0
REMOTE_ENV = "SOLIT2_FDS_HOST"
SMV_ENV = "SOLIT2_SMV_BIN"
MIN_FREE_BYTES = 10 * 1024**3          # parent spec: 10 GB floor
LOG_NAME = "run.out"
_TOTAL_TIME = re.compile(r"Total Time:\s+([\d.]+)\s*s")
_T_END = re.compile(r"T_END\s*=\s*([\d.]+)")
_DONE = "STOP: FDS completed successfully"
# Anything FDS says that is not the success STOP means the run is over and did
# not finish. Without this, "no progress line yet" and "dead" look identical.
_ERROR = re.compile(r"^[ \t]*(?:ERROR|STOP: (?!FDS completed successfully))",
                    re.MULTILINE)
# FDS banners its build as "Revision : FDS6.9.1-0-g..." or "Version : FDS 6.7.0".
_VERSION = re.compile(r"(?:FDS|Version\s*:)\s*v?(\d+\.\d+(?:\.\d+)?)")
# A build from source often stamps no release number at all -- one on this
# machine banners "Revision : -master" with a date and nothing else. That is
# still provenance, and a poorer answer than "unknown" only if it is dressed up
# as a release, so it is reported in a shape that cannot be mistaken for one.
_REVISION = re.compile(r"^\s*Revision\s*:\s*(\S+)\s*$", re.MULTILINE)
# "Revision Date    : Thu Sep 17 12:46:53 2026 -0400": weekday, month, day,
# clock, year. The clock is what a lazier pattern trips over.
_REVISION_DATE = re.compile(
    r"^\s*Revision Date\s*:\s*\w+\s+(\w+)\s+(\d+)\s+[\d:]+\s+(\d{4})", re.MULTILINE)
_MONTHS = ("Jan", "Feb", "Mar", "Apr", "May", "Jun",
           "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


def _binary() -> str | None:
    explicit = os.environ.get(BIN_ENV)
    if explicit and Path(explicit).exists():
        return explicit
    return shutil.which("fds")


def preflight() -> list[str]:
    """Blocking problems, in the order a user should fix them. Empty = ready."""
    if os.environ.get(REMOTE_ENV):
        # Deliberate: guessing at SSH-vs-queue semantics with no host to test
        # against would be building against an imagined system.
        return [f"remote execution via {REMOTE_ENV} is not implemented; "
                f"unset it to run locally"]
    problems = []
    if _binary() is None:
        problems.append(f"the fds binary is not on PATH and {BIN_ENV} is not set")
    if shutil.which("mpiexec") is None:
        problems.append("mpiexec is not on PATH (FDS runs the mesh set under MPI)")
    if shutil.disk_usage(Path.cwd()).free < MIN_FREE_BYTES:
        problems.append(f"less than {MIN_FREE_BYTES // 1024**3} GB of free disk")
    return problems


def mesh_count(deck_path: Path) -> int:
    """How many `&MESH` lines the deck carries -- one MPI rank each."""
    return sum(1 for ln in Path(deck_path).read_text().splitlines()
               if ln.startswith("&MESH"))


def run(deck_path: Path, out_dir: Path) -> str:
    """Launch FDS detached, one MPI rank per mesh, and return immediately.

    A run is hours long; the CFD step polls `status()` rather than blocking
    on it, and the CLI does its own waiting.

    `mpiexec -np N` with N = the deck's mesh count is the standard FDS mapping:
    FDS assigns meshes to ranks in order. A bare `fds` invocation runs every
    mesh in one process, which is valid but serial -- measured at 2.1x slower
    than three ranks on a three-mesh deck on the machine this was built on.
    """
    problems = preflight()
    if problems:
        raise RuntimeError("; ".join(problems))
    out_dir.mkdir(parents=True, exist_ok=True)
    local_deck = out_dir / "deck.fds"
    if Path(deck_path).resolve() != local_deck.resolve():
        shutil.copy(deck_path, local_deck)
    ranks = max(mesh_count(local_deck), 1)
    with (out_dir / LOG_NAME).open("w") as log:
        process = subprocess.Popen([shutil.which("mpiexec"), "-np", str(ranks),
                                    _binary(), local_deck.name],
                                   cwd=out_dir, stdout=log, stderr=subprocess.STDOUT,
                                   **_DETACHED)
    # So `status` can tell "still going" from "gone". A run launched from the
    # terminal writes no pid file, which is why `status` also watches the clock.
    (out_dir / PID_NAME).write_text(str(process.pid))
    return out_dir.name


def _chid(run_dir: Path) -> str | None:
    """The run's CHID, read off its own deck."""
    deck = Path(run_dir) / "deck.fds"
    if not deck.exists():
        return None
    match = re.search(r"CHID='([^']+)'", deck.read_text())
    return match.group(1) if match else None


def stop_file(run_dir: Path) -> Path | None:
    """`<CHID>.stop`, the file FDS watches for. None if there is no deck."""
    chid = _chid(run_dir)
    return None if chid is None else Path(run_dir) / f"{chid}.stop"


def is_paused(run_dir: Path) -> bool:
    marker = stop_file(run_dir)
    return marker is not None and marker.exists()


def has_restart_files(run_dir: Path) -> bool:
    """Whether FDS left anything to resume FROM."""
    return any(Path(run_dir).glob("*.restart"))


def pause(run_dir: Path) -> Path:
    """Ask FDS to stop gracefully and leave itself somewhere to resume from.

    NOT a kill. FDS checks for `<CHID>.stop` on every time step and, finding
    it, finishes the step, writes its restart files and exits cleanly. Killing
    the processes instead loses whatever was between the last checkpoint and
    the moment of death, and on this machine also has to catch `prterun`,
    which does not match the obvious pattern and restarts its workers.
    """
    marker = stop_file(run_dir)
    if marker is None:
        raise FileNotFoundError(f"no deck.fds in {run_dir}, so no CHID to stop")
    marker.write_text("")
    return marker


def resume(run_dir: Path, design, t_end_s: float | None = None) -> str:
    """Pick a paused run up from where it stopped.

    Clears the stop file first -- FDS reads it on the first step and would
    shut straight back down -- then rewrites the deck with `RESTART=.TRUE.`
    and relaunches. Everything else in the deck is regenerated from the same
    design, so a resumed run cannot silently continue under different physics.
    """
    from solit2.engines.fds import deck as deck_mod

    run_dir = Path(run_dir)
    if not has_restart_files(run_dir):
        raise FileNotFoundError(
            f"{run_dir} holds no .restart files, so there is nothing to resume from. "
            f"FDS writes them on a graceful stop and every "
            f"{deck_mod.DT_RESTART_S:.0f} s of simulated time; a run killed outright "
            f"before its first checkpoint has to start again")
    marker = stop_file(run_dir)
    if marker is not None and marker.exists():
        marker.unlink()
    (run_dir / "deck.fds").write_text(
        deck_mod.generate(design, t_end_s=t_end_s, restart=True))
    return run(run_dir / "deck.fds", run_dir)


def log_path(run_dir: Path) -> Path | None:
    """FDS's own `<CHID>.out` if it is there, else the stdout `run()` captured.

    The progress and version lines this module parses are ones FDS writes to
    `<CHID>.out`. `run()` only captures the process's stdout, and whether that
    carries the same lines is install-dependent -- so FDS's own file wins and
    `run.out` is the fallback.
    """
    run_dir = Path(run_dir)
    own = sorted(p for p in run_dir.glob("*.out") if p.name != LOG_NAME)
    if own:
        return own[0]
    captured = run_dir / LOG_NAME
    return captured if captured.exists() else None


def _source_revision(text: str) -> str | None:
    """A source build's own revision and date, e.g. "master@2026-09-17"."""
    revision = _REVISION.search(text)
    if revision is None:
        return None
    name = revision.group(1).strip("-") or "unnamed"
    date = _REVISION_DATE.search(text)
    if date is None:
        return name
    month, day, year = date.group(1), int(date.group(2)), date.group(3)
    if month not in _MONTHS:
        return name
    return f"{name}@{year}-{_MONTHS.index(month) + 1:02d}-{day:02d}"


def fds_version(run_dir: Path) -> str | None:
    """The FDS that wrote this run, or None when the log does not say.

    A release number when the banner carries one. Otherwise the source
    revision and its date, which is what a locally built FDS stamps instead --
    returned in a form that reads as a revision, never as a release.

    Never guess: an unverified version in `Result.meta` is a provenance claim
    nothing measured.
    """
    log = log_path(run_dir)
    if log is None:
        return None
    text = log.read_text()
    found = _VERSION.search(text)
    return found.group(1) if found else _source_revision(text)


def _pid_alive(pid: int) -> bool:
    """Does a process with this id exist? Asks; never signals.

    NOT `os.kill(pid, 0)`. That is the POSIX idiom and it is correct there, but
    on Windows `os.kill` routes any signal other than CTRL_C_EVENT and
    CTRL_BREAK_EVENT straight to TerminateProcess -- so the liveness CHECK
    would kill the FDS run it was asked about. Windows gets an explicit query
    instead: open the process for status only, and read its exit code.
    """
    if os.name != "nt":
        try:
            os.kill(pid, 0)      # signal 0 tests for existence, sends nothing
        except ProcessLookupError:
            return False
        except PermissionError:  # alive, owned by someone else
            return True
        except (OverflowError, ValueError):
            # A pid too large for the platform cannot name a live process, and
            # a corrupt pid file must not take the status check down with it.
            return False
        return True

    import ctypes
    from ctypes import wintypes

    PROCESS_QUERY_LIMITED_INFORMATION, STILL_ACTIVE = 0x1000, 259
    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
    try:
        handle = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    except (OverflowError, ValueError, ctypes.ArgumentError):
        return False
    if not handle:
        return False             # gone, or not ours to ask about
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True          # it exists; we simply cannot read its status
        return code.value == STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def _launcher_alive(run_dir: Path) -> bool | None:
    """Whether the process `run()` launched is still there; None if unknown.

    Unknown covers a run launched from the terminal, or one whose pid was
    recycled onto another process -- neither is evidence either way, and this
    returns None rather than guessing at it.
    """
    pid_file = Path(run_dir) / PID_NAME
    if not pid_file.exists():
        return None
    try:
        pid = int(pid_file.read_text().strip())
    except ValueError:
        return None
    return _pid_alive(pid)


def silent_for_s(run_dir: Path, now_s: float | None = None) -> float | None:
    """Seconds since this run last wrote ANY of its own output, or None if it
    has written nothing. Every file counts, not just the log: FDS dumps its
    CSVs on their own schedule, so the newest write is the honest signal."""
    times = [p.stat().st_mtime for p in Path(run_dir).glob("*") if p.is_file()]
    if not times:
        return None
    return (time.time() if now_s is None else now_s) - max(times)


def status(run_dir: Path) -> dict:
    """Progress from FDS's own log, against the deck's T_END."""
    log = log_path(run_dir)
    if log is None:
        return {"state": "failed", "progress": 0.0,
                "detail": f"no FDS log in {run_dir}"}
    text = log.read_text()
    if _DONE in text:
        return {"state": "done", "progress": 1.0, "detail": ""}
    if _ERROR.search(text):
        return {"state": "failed", "progress": 0.0,
                "detail": f"FDS reported an error in {log.name}"}
    deck = Path(run_dir) / "deck.fds"
    end = _T_END.search(deck.read_text()) if deck.exists() else None
    if end is None:
        return {"state": "failed", "progress": 0.0,
                "detail": "no deck.fds carrying a T_END to measure progress against"}
    elapsed = _TOTAL_TIME.findall(text)
    progress = min(float(elapsed[-1]) / float(end.group(1)), 1.0) if elapsed else 0.0
    # A run is only "running" while something says it still is. Neither check
    # below can be skipped: a killed run leaves a live-looking log behind, and a
    # DEADLOCKED run leaves live processes behind, so one catches what the other
    # cannot. Reported as failed rather than as a fourth state, because what a
    # caller does with it is exactly what it does with any unfinished run --
    # read the partial output and say it is incomplete.
    if is_paused(run_dir):
        # Asked to stop, so silence is the point rather than a symptom, and
        # neither the pid check nor the stall clock below has anything to say.
        return {"state": "paused", "progress": progress,
                "detail": ("stopped gracefully at "
                           + (f"{float(elapsed[-1]):.0f} s of {float(end.group(1)):.0f} s"
                              if elapsed else "the start")
                           + ("; resumable" if has_restart_files(run_dir)
                              else "; no restart files were written, so it cannot resume"))}
    if _launcher_alive(run_dir) is False:
        return {"state": "failed", "progress": progress,
                "detail": f"the FDS process is gone and never reported success; it stopped "
                          f"at {float(elapsed[-1]):.0f} s of {float(end.group(1)):.0f} s"
                          if elapsed else "the FDS process is gone and never started stepping"}
    silence_s = silent_for_s(run_dir)
    if silence_s is not None and silence_s > STALL_AFTER_S:
        return {"state": "failed", "progress": progress,
                "detail": f"no output for {silence_s / 60:.0f} minutes, so the run is not "
                          f"advancing; its processes may still be alive but wedged"}
    if not elapsed:
        # A run launched seconds ago has an open log and no time step in it yet.
        # Calling that "failed" made `run --engine fds` impossible to complete.
        return {"state": "running", "progress": 0.0,
                "detail": "launched; no simulated time reported yet"}
    return {"state": "running", "progress": progress, "detail": ""}


def smokeview_binary() -> str | None:
    """`$SOLIT2_SMV_BIN` if it points at a file, else `smokeview` on PATH."""
    explicit = os.environ.get(SMV_ENV)
    if explicit and Path(explicit).exists():
        return explicit
    return shutil.which("smokeview")


def open_smokeview(run_dir: Path) -> None:
    """Open the run's `.smv` in the desktop Smokeview, detached.

    Smokeview is a GL desktop application; it is launched beside the app, not
    embedded in it. Raises `FileNotFoundError` naming the missing piece.
    """
    binary = smokeview_binary()
    if binary is None:
        raise FileNotFoundError(f"no smokeview binary on PATH and {SMV_ENV} is not set")
    smv = sorted(Path(run_dir).glob("*.smv"))
    if not smv:
        raise FileNotFoundError(f"no .smv file in {run_dir} yet")
    subprocess.Popen([binary, smv[0].name], cwd=Path(run_dir), **_DETACHED)


# FDS writes one row per time step to `<CHID>_steps.csv`: step number, a real
# wall-clock timestamp, the step size, the simulated time reached, CPU seconds.
# That file is the honest source for live progress -- the `.out` log gives
# simulated time and nothing to measure a rate against.
STEPS_SUFFIX = "_steps.csv"
# How many of the most recent steps the rate is measured over. A run's average
# rate since launch is not its current rate: this one spent a night throttled
# to a thirtieth of its speed, and an average over that would have predicted
# days of remaining work for a run that finished in the hour.
RATE_WINDOW_STEPS = 60


def _read_steps(run_dir: Path) -> list[tuple[int, datetime, float, float]]:
    """(step, wall clock, step size, simulated time) for every complete row."""
    path = next(iter(sorted(Path(run_dir).glob(f"*{STEPS_SUFFIX}"))), None)
    if path is None:
        return []
    rows = []
    for line in path.read_text().splitlines()[2:]:      # units row, header row
        parts = line.split(",")
        if len(parts) < 4:
            continue
        try:
            rows.append((int(parts[0]), datetime.fromisoformat(parts[1].strip()),
                         float(parts[2]), float(parts[3])))
        except ValueError:
            continue                                     # a row still being written
    return rows


def _latest_csv_value(run_dir: Path, suffix: str, column: str) -> float | None:
    """The last value in a named column of one of the run's CSVs."""
    path = next(iter(sorted(Path(run_dir).glob(f"*{suffix}"))), None)
    if path is None:
        return None
    lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
    if len(lines) < 3:
        return None
    header = [c.strip() for c in lines[1].split(",")]
    if column not in header:
        return None
    try:
        return float(lines[-1].split(",")[header.index(column)])
    except (ValueError, IndexError):
        return None


def _control_times(run_dir: Path) -> dict[str, float | None]:
    path = next(iter(sorted(Path(run_dir).glob("*_ctrl.csv"))), None)
    out: dict[str, float | None] = {"detect_s": None, "activate_s": None}
    if path is None:
        return out
    lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
    if len(lines) < 3:
        return out
    header = [c.strip() for c in lines[1].split(",")]
    for key, control in (("detect_s", "DETECT"), ("activate_s", "ACT")):
        if control not in header:
            continue
        column = header.index(control)
        for line in lines[2:]:
            parts = line.split(",")
            try:
                if float(parts[column]) > 0:
                    out[key] = float(parts[0])
                    break
            except (ValueError, IndexError):
                continue
    return out


def live(run_dir: Path, t_end_s: float | None = None) -> dict:
    """What the run is doing right now, polled from its own output.

    Everything here is measured, never assumed: the rate comes from FDS's own
    wall-clock timestamps over the last `RATE_WINDOW_STEPS` steps, so it is
    the speed the run is going at now rather than its average since launch,
    and the estimate it feeds is only offered when there is a window to
    measure over and a target to aim at.
    """
    run_dir = Path(run_dir)
    if t_end_s is None:
        deck = run_dir / "deck.fds"
        match = _T_END.search(deck.read_text()) if deck.exists() else None
        t_end_s = float(match.group(1)) if match else None
    rows = _read_steps(run_dir)
    out: dict = {"time_step": None, "simulated_s": None, "t_end_s": t_end_s,
                 "step_size_s": None, "elapsed_s": None, "rate_s_per_s": None,
                 "eta_s": None, "hrr_mw": None,
                 **_control_times(run_dir)}
    hrr_kw = _latest_csv_value(run_dir, "_hrr.csv", "HRR")
    if hrr_kw is not None:
        out["hrr_mw"] = hrr_kw / 1000.0
    if not rows:
        return out
    step, wall, size, simulated = rows[-1]
    out.update(time_step=step, simulated_s=simulated, step_size_s=size,
               elapsed_s=(wall - rows[0][1]).total_seconds())
    window = rows[-RATE_WINDOW_STEPS:] if len(rows) > 1 else []
    if len(window) > 1:
        wall_span = (window[-1][1] - window[0][1]).total_seconds()
        sim_span = window[-1][3] - window[0][3]
        if wall_span > 0 and sim_span > 0:
            out["rate_s_per_s"] = sim_span / wall_span
            if t_end_s is not None and simulated < t_end_s:
                out["eta_s"] = (t_end_s - simulated) / out["rate_s_per_s"]
    return out


# A live chart wants shape, not every sample: a full-length run writes 3600
# rows and no reader can see that many points on one axis.
MAX_SERIES_POINTS = 400


def series(run_dir: Path, suffix: str, columns: tuple[str, ...],
           max_points: int = MAX_SERIES_POINTS) -> dict[str, list[float]]:
    """Named columns of one of the run's CSVs, against its first column.

    Returns `{"t_s": [...], "<column>": [...]}` for every column present, and
    an empty dict when the file has no complete data row yet. Columns the file
    does not carry are left out rather than filled: a run that has not written
    a device cannot be charted as if it read zero.

    The file is being appended to while it is read, so a half-written last row
    is dropped rather than parsed.
    """
    path = next(iter(sorted(Path(run_dir).glob(f"*{suffix}"))), None)
    if path is None:
        return {}
    try:
        lines = [ln for ln in path.read_text().splitlines() if ln.strip()]
    except OSError:
        return {}
    if len(lines) < 3:
        return {}
    header = [c.strip() for c in lines[1].split(",")]
    wanted = {name: header.index(name) for name in columns if name in header}
    if not wanted:
        return {}
    widest = max(wanted.values())
    rows = []
    for line in lines[2:]:
        parts = line.split(",")
        if len(parts) <= widest:
            continue                       # a row still being written
        try:
            rows.append([float(parts[0])] + [float(parts[i]) for i in wanted.values()])
        except ValueError:
            continue
    if not rows:
        return {}
    stride = max(1, len(rows) // max_points)
    kept = rows[::stride]
    if kept[-1] is not rows[-1]:
        kept.append(rows[-1])              # never drop the newest sample
    out: dict[str, list[float]] = {"t_s": [r[0] for r in kept]}
    for offset, name in enumerate(wanted, start=1):
        out[name] = [r[offset] for r in kept]
    return out

"""Pre-flight, launch and status for an FDS run.

Every check here is a filesystem or environment lookup, so the whole module is
testable by monkeypatching `shutil` and the environment -- which is the only way
it CAN be tested, since no FDS install exists yet.
"""
from __future__ import annotations

import os
import re
import shutil
import signal
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
# FDS is MPI across meshes AND OpenMP inside each mesh, and its OpenMP default
# is one thread per core -- per rank. A ten-mesh deck on an eleven-core machine
# therefore asks for 110 threads, and the ranks spend their time descheduling
# each other instead of solving. Measured on identical 20 s decks, same machine:
#
#   10 ranks x 11 threads (FDS default)   332 s
#   10 ranks x 1 thread                   119 s
#
# One thread per rank, with the rank count already matching the mesh count, is
# the whole core budget spent once. An OMP_NUM_THREADS the caller set is theirs
# and is left alone.
OMP_THREADS_PER_RANK = "1"
REMOTE_ENV = "SOLIT2_FDS_HOST"
SMV_ENV = "SOLIT2_SMV_BIN"
MIN_FREE_BYTES = 10 * 1024**3          # parent spec: 10 GB floor
LOG_NAME = "run.out"
# Every `status()` state where the run's own processes are (or may still be)
# actively computing -- "running" itself, and "pausing" (asked to stop, not
# yet gone: see status()). A caller deciding whether a core is occupied, a
# rate/ETA is meaningful, or a second launch would double up on one directory
# should treat both the same; a bare `== "running"` string check misses
# "pausing" and is exactly the C2 bug (freeing a block, or launching into a
# directory, while the previous run had not actually exited yet).
RUNNING_STATES = frozenset({"running", "pausing"})
_TOTAL_TIME = re.compile(r"Total Time:\s+([\d.]+)\s*s")
_T_END = re.compile(r"T_END\s*=\s*([\d.]+)")
_DONE = "STOP: FDS completed successfully"
# What FDS writes when it exits because it found `<CHID>.stop` -- exactly the
# marker `pause()` leaves. Not a failure: it is the graceful stop pause() asks
# for, working as intended. Seen live: "STOP: FDS stopped by user
# (CHID: eaea401330e8)", so this is a prefix match, not the whole line.
_STOPPED_BY_USER = "STOP: FDS stopped by user"
# Anything FDS says that is not one of the two STOPs above means the run is
# over and did not finish cleanly. Without this, "no progress line yet" and
# "dead" look identical -- and without excluding _STOPPED_BY_USER too, a
# cleanly paused run (is_paused() true, restart files on disk) was reported
# as failed at 0%, because this check runs before the is_paused() branch
# below ever gets a look. A genuine "STOP: Numerical instability..." or any
# other STOP/ERROR line still matches and is still reported failed.
_ERROR = re.compile(
    r"^[ \t]*(?:ERROR|STOP: (?!FDS completed successfully|FDS stopped by user))",
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


def run(deck_path: Path, out_dir: Path, *, extra_env: dict[str, str] | None = None) -> str:
    """Launch FDS detached, one MPI rank per mesh, and return immediately.

    A run is hours long; the CFD step polls `status()` rather than blocking
    on it, and the CLI does its own waiting.

    `mpiexec -np N` with N = the deck's mesh count is the standard FDS mapping:
    FDS assigns meshes to ranks in order. A bare `fds` invocation runs every
    mesh in one process, which is valid but serial -- measured at 2.1x slower
    than three ranks on a three-mesh deck on the machine this was built on.

    Each rank gets one OpenMP thread; see OMP_THREADS_PER_RANK for why.

    `extra_env` merges additional variables over the inherited process
    environment -- e.g. `I_MPI_PIN_PROCESSOR_LIST`, which the fleet scheduler
    sets to one run's own core block (see scheduler.py) so several runs
    launched this way pin to disjoint cores instead of fighting over the
    same ones. Applied after the `OMP_NUM_THREADS` default below, so a caller
    can override that too if it needs to.
    """
    problems = preflight()
    if problems:
        raise RuntimeError("; ".join(problems))
    out_dir.mkdir(parents=True, exist_ok=True)
    local_deck = out_dir / "deck.fds"
    if Path(deck_path).resolve() != local_deck.resolve():
        shutil.copy(deck_path, local_deck)
    ranks = max(mesh_count(local_deck), 1)
    env = {**os.environ}
    env.setdefault("OMP_NUM_THREADS", OMP_THREADS_PER_RANK)
    if extra_env:
        env.update(extra_env)
    with (out_dir / LOG_NAME).open("w") as log:
        process = subprocess.Popen([shutil.which("mpiexec"), "-np", str(ranks),
                                    _binary(), local_deck.name],
                                   cwd=out_dir, stdout=log, stderr=subprocess.STDOUT,
                                   env=env, **_DETACHED)
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


STOPPED_NAME = "stopped.by.user"


def was_stopped(run_dir: Path) -> bool:
    return (Path(run_dir) / STOPPED_NAME).exists()


def stop(run_dir: Path) -> bool:
    """End the run now. Returns whether there was a live process to end.

    The blunt counterpart to `pause`, and it exists because `pause` needs FDS
    to reach another time step to notice the stop file. A wedged run never
    does -- one on this machine sat unmoving for seven hours with every
    process alive -- and then the only way out is to kill it.

    Kills the PROCESS GROUP, not the pid. `run` launches through `mpiexec`,
    which starts its own workers, and signalling the launcher alone leaves
    them running or lets it restart them; this is exactly why a
    `pkill -f "fds deck.fds"` appears to work and does not.

    Whatever restart files the run had already written are left in place, so a
    stopped run can still be resumed from its last checkpoint even though
    stopping is not the graceful way to get there.
    """
    run_dir = Path(run_dir)
    pid_file = run_dir / PID_NAME
    pid = None
    if pid_file.exists():
        try:
            pid = int(pid_file.read_text().strip())
        except ValueError:
            pid = None
    # Establish that the run is over -- or can be ended -- BEFORE marking it
    # stopped. Marking first and discovering afterwards that there was nothing
    # to signal leaves `status` reporting "stopped" over a run whose ranks are
    # still burning CPU, which is the tool describing a state it did not bring
    # about. Seen for real on a run launched outside the app: stop() wrote the
    # marker, found no pid file, returned False, and ten ranks kept going.
    if pid is None:
        raise FileNotFoundError(
            f"{run_dir} has no readable {PID_NAME}, so there is no way to tell which "
            f"processes belong to this run and stopping it here would be a claim, not "
            f"an act. A run launched outside the app writes no pid file. End it from a "
            f"terminal instead -- the launcher needs killing too, so "
            f"`pkill -9 -f \"fds deck.fds\"` on its own is not enough")
    if not _pid_alive(pid):
        (run_dir / STOPPED_NAME).write_text("")
        return False
    if os.name == "nt":
        subprocess.run(["taskkill", "/T", "/F", "/PID", str(pid)],
                       capture_output=True, check=False)
        (run_dir / STOPPED_NAME).write_text("")
        return True
    if not _pid_matches_run_dir(pid, run_dir):
        # I3: `fds.pid` can outlive the process it named -- killed some other
        # way, or the OS has since reused that number for an unrelated
        # process. Signalling it then would not be stopping THIS run; it
        # would be signalling whatever now holds pid, which `_pid_alive`
        # alone cannot tell apart from the real thing.
        raise PermissionError(
            f"{run_dir}'s {PID_NAME} names pid {pid}, but that process no longer looks like "
            f"this run's own launcher (it is not its own process group leader, or its "
            f"working directory is not {run_dir} any more) -- it may be a stale or recycled "
            f"pid. Stopping it here would risk signalling the wrong process; confirm by hand "
            f"(`ps -o pid,pgid,args -p {pid}` and `readlink /proc/{pid}/cwd`) before ending it")
    for signal_number in (signal.SIGTERM, signal.SIGKILL):
        try:
            os.killpg(os.getpgid(pid), signal_number)
        except ProcessLookupError:
            break                          # already gone between the check and the signal
        except (PermissionError, OSError) as exc:
            # Not ours to signal. Saying True here would report a kill that
            # never happened.
            raise PermissionError(
                f"{run_dir} could not be stopped: {exc}. Its processes are not this "
                f"session's to signal") from exc
        time.sleep(2)
        if not _pid_alive(pid):
            break
    (run_dir / STOPPED_NAME).write_text("")
    return True


def _mesh_lines(deck_text: str) -> list[str]:
    """The deck's &MESH lines, which are what a restart file is written against."""
    return [ln.strip() for ln in deck_text.splitlines() if ln.startswith("&MESH")]


def _refuse_on_mesh_change(existing: str, regenerated: str, run_dir: Path) -> None:
    """Refuse a resume whose mesh no longer matches the one on disk.

    A restart file is a per-mesh dump of the solution arrays, so it only means
    anything under the mesh that wrote it. `resume` rebuilds the deck from the
    design to stop a run silently continuing under different physics -- but
    the generator's own mesh layout can move between the checkpoint and the
    resume, and then the rebuilt deck asks FDS to pour old arrays into a
    differently shaped domain. This caught exactly that: a run checkpointed on
    ten uniform 60 m meshes, resumed after the generator started splitting the
    window into a fine core and a coarser far field.

    ponytail: compares the &MESH lines only. They are what the restart files
    are indexed by; a changed obstruction is a physics change and is the
    design's business, not this check's.
    """
    before, after = _mesh_lines(existing), _mesh_lines(regenerated)
    if before == after:
        return
    detail = (f"{len(before)} meshes then, {len(after)} now"
              if len(before) != len(after) else
              next(f"was {a}, now {b}" for a, b in zip(before, after) if a != b))
    raise ValueError(
        f"{run_dir} was checkpointed on a different mesh than this design "
        f"generates now ({detail}). A restart file only means anything under "
        f"the mesh that wrote it, so this run has to start again rather than "
        f"resume")


def prepare_resume(run_dir: Path, design, t_end_s: float | None = None) -> Path:
    """Rewrite `run_dir/deck.fds` with `RESTART=.TRUE.` from `design`, refuse a
    mesh or identity mismatch against the checkpoints already on disk, and
    clear the stop/stopped markers so the deck is ready to relaunch. Returns
    the deck path. Touches nothing else -- launching is the caller's job.

    Split out of `resume` so a caller that must block in the FOREGROUND
    (`fds-exec`, the entry point the CFD server's run queue calls -- see
    exec_run.py) can reuse the exact same regeneration and mesh-change check
    without going through `resume`'s own detached relaunch via `run`.

    Every property that decides WHICH deck this is comes from the run's own
    files, never from a caller-passed default, because the whole point of
    resuming is continuing the SAME experiment:

    - `suppression` (mist vs free burn) from the existing CHID, the same test
      `matches_design` already uses. Getting this wrong regenerates the WRONG
      deck under the RIGHT run dir's name -- caught live: a free-burn run's
      own deck.fds was overwritten with a mist deck carrying the mist CHID.
    - `dx_m` from the existing deck's own mesh (`deck.stored_dx_m`), not this
      module's current default -- caught live: a grid-study point checkpointed
      at dx=0.75 resumed at the default 0.6 was refused as a mesh change, even
      though the run dir's own dx never moved.
    - `e_coefficient` from the run's OWN deck.fds, never taken from the
      module's current default: a calibration run launched at E=0.25 must
      resume at E=0.25, not silently drift to whatever `deck.E_COEFFICIENT`
      happens to be today.
    - `t_end_s` DEFAULTS to the existing deck's own T_END when the caller
      passes none -- caught live: the scheduler's own resume call passes none,
      and used to regenerate at the design's full discharge duration instead
      of the window the run was actually launched for (600 s resumed as
      3600 s). A caller that explicitly wants a different window (`fds-exec
      --t-end`, the app's "resume for longer" picker) still gets it: that is
      a deliberate choice, not drift.

    After regenerating, the CHID must match what was on disk -- if it does
    not, `design` is not the one that produced this run at all (a stale or
    wrong `design.json`), and resuming would attribute one experiment's data
    to a different one's physics. Checked before the mesh comparison, which
    catches a narrower case (same design, moved mesh generator).
    """
    from solit2.engines.fds import deck as deck_mod

    run_dir = Path(run_dir)
    if not has_restart_files(run_dir):
        raise FileNotFoundError(
            f"{run_dir} holds no .restart files, so there is nothing to resume from. "
            f"FDS writes them on a graceful stop and every "
            f"{deck_mod.DT_RESTART_S:.0f} s of simulated time; a run killed outright "
            f"before its first checkpoint has to start again")
    existing = run_dir / "deck.fds"
    if not existing.exists():
        raise FileNotFoundError(
            f"{run_dir} holds checkpoints but no deck.fds, so the mesh they were "
            f"written on cannot be checked against the one this design generates "
            f"now. Resuming would be a guess; start the run again")
    existing_text = existing.read_text()
    existing_chid = _chid(run_dir)
    # Same test `deck.matches_design` uses: the mist CHID is never a substring
    # of a free-burn deck's own HEAD line, so its absence is the free-burn tell.
    suppression = f"CHID='{deck_mod.chid(design, suppression=False)}'" not in existing_text.split(
        "\n", 1)[0]
    expected_chid = deck_mod.chid(design, suppression=suppression)
    if existing_chid != expected_chid:
        raise ValueError(
            f"{run_dir} was checkpointed under CHID {existing_chid!r}, but the design passed "
            f"to resume generates {expected_chid!r} "
            f"({'suppressed' if suppression else 'free burn'}). That is not the design this "
            f"run was launched from -- resuming would attribute a different experiment's "
            f"physics to this run's checkpoints")
    dx_m = deck_mod.stored_dx_m(run_dir)
    if dx_m is None:
        raise ValueError(
            f"{run_dir}'s deck.fds carries no readable &MESH line, so the cell size it "
            f"actually ran at cannot be recovered to resume at the same one")
    e_coefficient = deck_mod.stored_e_coefficient(run_dir)
    if e_coefficient is None:
        e_coefficient = deck_mod.E_COEFFICIENT
    if t_end_s is None:
        existing_t_end = _T_END.search(existing_text)
        t_end_s = float(existing_t_end.group(1)) if existing_t_end else None
    regenerated = deck_mod.generate(design, dx_m=dx_m, t_end_s=t_end_s, restart=True,
                                    suppression=suppression, e_coefficient=e_coefficient)
    _refuse_on_mesh_change(existing_text, regenerated, run_dir)
    # Nothing above this line has changed anything on disk: a refused resume
    # leaves the run exactly as it found it, still stopped and still resumable
    # by whoever fixes the mismatch.
    marker = stop_file(run_dir)
    if marker is not None and marker.exists():
        marker.unlink()
    stopped = run_dir / STOPPED_NAME
    if stopped.exists():
        stopped.unlink()
    existing.write_text(regenerated)
    return existing


def resume(run_dir: Path, design, t_end_s: float | None = None) -> str:
    """Pick a paused run up from where it stopped.

    Clears the stop file first -- FDS reads it on the first step and would
    shut straight back down -- then rewrites the deck with `RESTART=.TRUE.`
    and relaunches (`prepare_resume`). Everything else in the deck is
    regenerated from the same design, so a resumed run cannot silently
    continue under different physics.
    """
    deck_path = prepare_resume(run_dir, design, t_end_s=t_end_s)
    return run(deck_path, run_dir)


def run_or_resume(deck_path: Path, run_dir: Path, design, t_end_s: float | None = None) -> str:
    """Skip a `done` run, resume one with restart files, or launch fresh --
    the one entry point every resumable Tier 2 driver (the E-coefficient
    sweep, the grid-convergence study, the campaign script) launches a run
    through, so "don't waste hours-long compute a previous pass already
    paid for" is implemented once rather than three times.

    Assumes it is not called again for a run already `running` under THIS
    process's own wait loop -- callers poll `status()` themselves after
    calling this once per run directory; calling it concurrently from two
    separate campaigns pointed at the same `run_dir` is not guarded against.
    """
    if status(run_dir)["state"] == "done":
        return "done"
    if has_restart_files(run_dir):
        return resume(run_dir, design, t_end_s=t_end_s)
    return run(deck_path, run_dir)


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


def _pid_matches_run_dir(pid: int, run_dir: Path, *, proc_dir: Path = Path("/proc")) -> bool:
    """I3: is `pid` actually the launcher THIS run dir's own `fds.pid` should
    name, not a stale or recycled number that happens to still exist?

    Two checks, both POSIX-only (callers gate this on `os.name != 'nt'`):

    - `getpgid(pid) == pid`: `run()` launches with `start_new_session=True`,
      which makes the launched process the leader of a brand new session AND
      process group -- so for the real thing this is always true. A pid that
      is no longer its own group leader is not what was launched here.
    - on a system with procfs (Linux -- the deployment target), `/proc/<pid>
      /cwd` must resolve to `run_dir`: FDS is launched with `cwd=run_dir` (see
      `run()`), so the real process's working directory never moves away from
      it. Skipped where there is no procfs at all (macOS/BSD): the getpgid
      check is the only signal available there, same as always.
    """
    try:
        if os.getpgid(pid) != pid:
            return False
    except ProcessLookupError:
        return False
    except OSError:
        pass                                  # not ours to ask; fall through to what we CAN check
    cwd_link = proc_dir / str(pid) / "cwd"
    if not proc_dir.is_dir():
        return True                           # no procfs on this platform; getpgid is the whole check
    if not cwd_link.exists():
        return False                          # procfs exists but this pid does not -- it is gone
    try:
        return cwd_link.resolve() == Path(run_dir).resolve()
    except OSError:
        return False


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
    if was_stopped(run_dir):
        return {"state": "stopped", "progress": progress,
                "detail": ("stopped at "
                           + (f"{float(elapsed[-1]):.0f} s of {float(end.group(1)):.0f} s"
                              if elapsed else "the start")
                           + ("; resumable from its last checkpoint"
                              if has_restart_files(run_dir)
                              else "; it wrote no restart files, so it cannot resume"))}
    if is_paused(run_dir):
        # Asked to stop, so silence is the point rather than a symptom, and
        # neither the stall clock below has anything to say. The pid check
        # DOES still matter here, though: FDS checks for the stop file once
        # per time step, not instantly, so there is a real window -- up to
        # one step, which can be tens of seconds on a large deck -- where the
        # marker exists but the ranks are still finishing. Reporting "paused"
        # for that window made a second launch (Resume, or the scheduler
        # reusing the freed block) start a second FDS in the same directory
        # while the first was still writing to it.
        if _launcher_alive(run_dir) is True:
            return {"state": "pausing", "progress": progress,
                    "detail": ("finishing its current step before stopping at "
                               + (f"{float(elapsed[-1]):.0f} s of {float(end.group(1)):.0f} s"
                                  if elapsed else "the start"))}
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

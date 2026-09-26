"""The CFD run queue as a proper foreground daemon -- what `/opt/cfd-sched.py`,
a plain nohup Python script on the CFD server, has been doing by hand: keep a
fixed set of core blocks busy, one FDS run per block, pinned so concurrent
runs never fight over the same cores.

`solit2 fds-scheduler` is meant to run under systemd
(`deploy/systemd/solit2-scheduler.service`), in the foreground, forever. It
owns three files under `SOLIT2_CFD_STATE_DIR` (default `/var/lib/solit2-cfd`):

    state.json      {"0-9": "<run dir>|null", "10-19": ..., "20-29": ...}
    queue.txt       one run directory per line, next-to-run first
    scheduler.log   one IST-stamped line per state change

`state.json`'s shape is deliberately the interim script's own -- see `adopt()`
-- so this scheduler can take over a live deployment's already-running FDS
processes without stopping them: importing the interim's state and queue
once is enough, because both launch through the same `runner.run()` and
write the same pid/log files underneath.

Every run in the queue is either a fresh launch (`deck.fds` already written,
no restart files yet) or a resume (restart files on disk; the deck is
regenerated with `RESTART=.TRUE.` from the run's own `design.json`, exactly
as `exec_run.run_foreground` does it for the older, blocking queue). A run
whose `design.json` is missing when it needs to resume fails loudly rather
than silently staying a fresh run of stale physics.
"""
from __future__ import annotations

import contextlib
import fcntl
import itertools
import json
import os
import signal
import threading
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from solit2.engines.fds import runner as runner_mod
from solit2.schema.design import Design

IST = ZoneInfo("Asia/Kolkata")
BLOCKS_ENV = "SOLIT2_CFD_BLOCKS"
STATE_DIR_ENV = "SOLIT2_CFD_STATE_DIR"
DEFAULT_BLOCKS = "0-9,10-19,20-29"
# I1: NOT /var/lib/solit2-cfd -- that is scripts/cfd_queue.sh's own state
# directory (see docs/cloud-compute.md's older, still-valid walkthrough),
# and it holds a queue.txt of its own. Sharing the path would have this
# scheduler and `solit2-cfd.service`'s `xargs -a .../queue.txt` both
# consuming (and both rewriting) the SAME queue file with two entirely
# different mechanisms.
DEFAULT_STATE_DIR = Path("/var/lib/solit2-scheduler")

STATE_NAME = "state.json"
QUEUE_NAME = "queue.txt"
LOG_NAME = "scheduler.log"
# The design a queued run's deck was generated from -- same name and same
# convention `exec_run.py` already established for the older, blocking
# queue, so a run dir works with either one.
DESIGN_NAME = "design.json"
# I1: the SAME name `scripts/cfd_queue.sh` locks a run dir with (see its own
# LOCK_BUSY_CODE/flock usage), not a scheduler-specific one -- so if a run
# directory is ever reachable from BOTH the old queue and this one (a
# leftover /var/lib/solit2-cfd/queue.txt entry still naming it, say), they
# still respect each other's hold on it rather than launching FDS twice
# under two different lock files that never see one another.
RUN_LOCK_NAME = ".fds-exec.lock"
QUEUE_LOCK_NAME = ".queue.lock"
FAILURES_NAME = ".fds-scheduler.failures"
PID_NAME = "scheduler.pid"
# I2: held for the whole life of a `run_forever` call (or a one-shot
# `adopt`) -- see `_instance_lock`.
INSTANCE_LOCK_NAME = "scheduler.lock"

# A run dir gets this many launch attempts before the scheduler stops
# retrying it automatically and logs it as skipped -- the same cap and the
# same reasoning as `scripts/cfd_queue.sh`'s MAX_FAILURES: a run that keeps
# failing for a reason relaunching cannot fix (a bad deck, a dead disk) must
# not burn a whole core block forever.
MAX_FAILURES = 3
# How often the loop looks for a free block and reaps a finished run. FDS
# itself reports progress far less often than this (every 100 time steps),
# so polling this often costs only a few cheap file reads per block; the
# payoff is a freed block being reused within POLL_S of freeing up, not up
# to a whole run's length later.
POLL_S = 15.0


def parse_blocks(spec: str) -> tuple[str, ...]:
    """"0-9,10-19,20-29" -> ("0-9", "10-19", "20-29").

    Each label doubles as its own `I_MPI_PIN_PROCESSOR_LIST` value -- Intel
    MPI accepts exactly this "lo-hi" syntax, so no second representation of
    a block is needed anywhere in this module.

    Refuses two blocks that overlap: pinning is the whole point of a block
    (see `scheduler._launch`'s `I_MPI_PIN_PROCESSOR_LIST`), and a shared
    core between two "disjoint" blocks would have two concurrent runs
    fighting over it -- exactly what pinning exists to prevent.

    Deliberately does NOT check the range against this host's actual core
    count: that varies by machine (a dev laptop running the test suite is
    not the 32-vCPU deployment target), so `SOLIT2_CFD_BLOCKS` staying
    inside the real core count is an operator responsibility -- see
    docs/cloud-compute.md's `lscpu -e` step in the takeover checklist.
    """
    blocks = tuple(b.strip() for b in spec.split(",") if b.strip())
    if not blocks:
        raise ValueError(f"{spec!r} names no core blocks")
    spans = []
    for b in blocks:
        lo, _, hi = b.partition("-")
        if not (lo.isdigit() and hi.isdigit() and int(lo) <= int(hi)):
            raise ValueError(f"block {b!r} is not a 'lo-hi' core range, e.g. '0-9'")
        spans.append((int(lo), int(hi), b))
    for (lo1, hi1, b1), (lo2, hi2, b2) in itertools.combinations(spans, 2):
        if lo1 <= hi2 and lo2 <= hi1:
            raise ValueError(
                f"blocks {b1!r} and {b2!r} overlap; each core must be pinned to exactly "
                f"one block or two runs could be scheduled onto the same cores")
    return blocks


def resolve_state_dir(explicit: str | Path | None = None) -> Path:
    if explicit is not None:
        return Path(explicit)
    return Path(os.environ.get(STATE_DIR_ENV, str(DEFAULT_STATE_DIR)))


def resolve_blocks(explicit: str | None = None) -> tuple[str, ...]:
    return parse_blocks(explicit if explicit is not None
                        else os.environ.get(BLOCKS_ENV, DEFAULT_BLOCKS))


# --- state.json / queue.txt: atomic writes (temp + rename), IST logging -----

def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)          # atomic on POSIX: a reader never sees a half-written file


def load_state(state_dir: Path, blocks: tuple[str, ...]) -> dict[str, str | None]:
    """Every block in `blocks`, `None` if state.json has no run for it (or
    does not exist yet -- a scheduler that has never run reports every block
    free, which is the correct starting state)."""
    path = Path(state_dir) / STATE_NAME
    raw: dict = json.loads(path.read_text()) if path.exists() else {}
    return {b: raw.get(b) for b in blocks}


def save_state(state_dir: Path, state: dict[str, str | None]) -> None:
    _write_atomic(Path(state_dir) / STATE_NAME, json.dumps(state, indent=2))


def load_queue(state_dir: Path) -> list[str]:
    path = Path(state_dir) / QUEUE_NAME
    if not path.exists():
        return []
    return [ln.strip() for ln in path.read_text().splitlines() if ln.strip()]


def save_queue(state_dir: Path, queue: list[str]) -> None:
    text = "".join(f"{ln}\n" for ln in queue)
    _write_atomic(Path(state_dir) / QUEUE_NAME, text)


@contextlib.contextmanager
def queue_lock(state_dir: Path):
    """Exclusive lock held for one read-modify-write of queue.txt.

    The scheduler's own loop and every `fleet` action that edits the queue
    (enqueue/dequeue/move) take this same lock, so a queue reorder landing
    between the scheduler reading the file and writing it back can never be
    silently overwritten by either side.
    """
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    handle = (state_dir / QUEUE_LOCK_NAME).open("w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX)
        yield
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


def _stamp() -> str:
    return datetime.now(IST).isoformat(timespec="seconds")


def _log(state_dir: Path, message: str) -> None:
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    with (state_dir / LOG_NAME).open("a") as f:
        f.write(f"{_stamp()}  {message}\n")


# --- per-run-dir lock (never start two runs on one directory) ---------------

def _try_lock_run(run_dir: Path) -> tuple[object | None, str | None]:
    """A non-blocking exclusive lock on `<run_dir>/RUN_LOCK_NAME`.

    Returns `(handle, None)` on success -- keep the handle open for as long
    as the run is considered "this scheduler's own"; closing it releases the
    lock -- or `(None, reason)` when something else already holds it (a
    hand-run `fds-exec` on the same directory, or a second scheduler process
    started by mistake). Guards exactly the case the brief calls out: this
    scheduler must never start two runs on one directory. Callers check
    `run_dir` exists before calling this -- see `step()` -- so the `OSError`
    guard around opening the lock file is defensive only, for a directory
    removed in the gap between that check and this call.

    Opened with `os.open(O_RDWR | O_CREAT)`, not `Path.open("w")`: "w"
    truncates on every call, which bumps the lock file's mtime even when
    its (empty) content never changes -- and `runner.silent_for_s` reads the
    newest mtime across every file in the run dir to decide whether it has
    gone quiet. A held lock re-touched on every poll would have kept a
    genuinely wedged run from ever tripping STALL_AFTER_S.
    """
    try:
        fd = os.open(str(Path(run_dir) / RUN_LOCK_NAME), os.O_RDWR | os.O_CREAT, 0o644)
        handle = os.fdopen(fd)
    except OSError as exc:
        return None, f"could not open a lock file in {run_dir}: {exc}"
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        handle.close()
        return None, "already locked by another process"
    return handle, None


# --- per-run-dir failure count (skip after MAX_FAILURES) --------------------

def _failure_count(run_dir: Path) -> int:
    path = Path(run_dir) / FAILURES_NAME
    if not path.exists():
        return 0
    try:
        return int(path.read_text().strip())
    except ValueError:
        return 0


def _record_failure(run_dir: Path) -> int:
    count = _failure_count(run_dir) + 1
    try:
        (Path(run_dir) / FAILURES_NAME).write_text(str(count))
    except OSError:
        # A run directory named in state.json/queue.txt (by hand, or via
        # adopt() from a stale interim file) that does not actually exist on
        # disk has nowhere to persist this. One bad entry must not take the
        # whole loop down -- the caller still logs the failure itself, this
        # just means the count resets to 1 every poll instead of climbing to
        # MAX_FAILURES, so it keeps showing up rather than crashing silently.
        pass
    return count


def _clear_failures(run_dir: Path) -> None:
    (Path(run_dir) / FAILURES_NAME).unlink(missing_ok=True)


# --- I2: one scheduler process (or one-shot adopt) per state dir, ever -----

@contextlib.contextmanager
def _instance_lock(state_dir: Path):
    """Exclusive, non-blocking lock on `<state_dir>/INSTANCE_LOCK_NAME`, held
    for as long as a scheduler process (or a one-time `adopt`) is actively
    reading and writing `state.json`/`queue.txt`.

    Without this, a second scheduler started by mistake -- a stray `--once`
    run while the persistent unit is already up, most plausibly -- would
    load its own copy of `state.json`, and whichever process saves last
    silently overwrites the other's. Two schedulers can then each believe a
    block is free and launch onto the same cores.
    """
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    handle = (state_dir / INSTANCE_LOCK_NAME).open("w")
    try:
        fcntl.flock(handle, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        handle.close()
        raise RuntimeError(
            f"another solit2 fds-scheduler process already holds "
            f"{state_dir / INSTANCE_LOCK_NAME} -- state.json is shared, and two schedulers "
            f"writing it would double-book cores. Stop the other one first "
            f"(systemctl stop solit2-scheduler.service if it is the unit), or point this "
            f"one at a different --state-dir") from exc
    try:
        yield
    finally:
        fcntl.flock(handle, fcntl.LOCK_UN)
        handle.close()


# --- adoption: take over the interim script's state without stopping it ----

def adopt(state_dir: Path, blocks: tuple[str, ...], adopt_state: Path, adopt_queue: Path) -> None:
    """Import an interim scheduler's `state.json` and `queue.txt` ONCE.

    Called before the loop starts, never from inside it. The FDS processes
    the interim script already launched keep running exactly where they
    are -- this only starts THIS process polling and managing them, via the
    same `runner.status()`/`runner.run()` every other run in this deployment
    goes through.
    """
    with _instance_lock(state_dir):
        raw_state = json.loads(Path(adopt_state).read_text())
        state = {b: raw_state.get(b) for b in blocks}
        save_state(state_dir, state)
        raw_queue = [ln.strip() for ln in Path(adopt_queue).read_text().splitlines()
                    if ln.strip()]
        with queue_lock(state_dir):
            save_queue(state_dir, raw_queue)
        running = sum(1 for v in state.values() if v)
        _log(state_dir, f"adopted state from {adopt_state} ({running} block(s) already "
                         f"running) and queue from {adopt_queue} ({len(raw_queue)} queued)")


# --- scheduler pid (so fleet/UI can tell whether a scheduler is alive) ------

def _write_pid(state_dir: Path) -> None:
    (Path(state_dir) / PID_NAME).write_text(str(os.getpid()))


def is_running(state_dir: Path) -> bool:
    """Whether a scheduler that wrote `PID_NAME` is still alive.

    Unlike `runner._launcher_alive`, this has no "unknown" case: a missing
    pid file always reads as "not running", which is the right default for
    fleet's "does anything work the queue right now?" question -- a
    scheduler that never wrote the file cannot be assumed alive.
    """
    pid_file = Path(state_dir) / PID_NAME
    if not pid_file.exists():
        return False
    try:
        pid = int(pid_file.read_text().strip())
    except ValueError:
        return False
    return runner_mod._pid_alive(pid)


# --- launching a queued run, resume-aware -----------------------------------

def _load_design(run_dir: Path) -> Design:
    design_path = Path(run_dir) / DESIGN_NAME
    if not design_path.exists():
        raise FileNotFoundError(
            f"{run_dir} holds restart files but no {DESIGN_NAME}, so the scheduler cannot "
            f"regenerate its RESTART=.TRUE. deck. Write it beside deck.fds first -- "
            f"`solit2 fds-adopt {run_dir} --design <design.json>` -- then re-enqueue")
    return Design.load(design_path)


def _launch(run_dir: Path, block: str) -> None:
    """Launch (fresh) or resume `run_dir`, pinned to `block`'s cores."""
    run_dir = Path(run_dir)
    extra_env = {"I_MPI_PIN_PROCESSOR_LIST": block}
    if runner_mod.has_restart_files(run_dir):
        design = _load_design(run_dir)
        deck_path = runner_mod.prepare_resume(run_dir, design)
    else:
        deck_path = run_dir / "deck.fds"
        if not deck_path.exists():
            raise FileNotFoundError(f"{run_dir} holds no deck.fds to run")
    runner_mod.run(deck_path, run_dir, extra_env=extra_env)


# --- the loop ----------------------------------------------------------------

def _release_finished(state_dir: Path, state: dict[str, str | None],
                      locks: dict[str, object]) -> dict[str, str | None]:
    """Free every block whose run is no longer occupying its cores -- done
    always frees it; failed, stopped or paused free it too, UNLESS the
    run's own process is still actually alive, in which case the block is
    held rather than freed.

    That exception is C2's fix: `status()` reports "pausing" (in
    `runner.RUNNING_STATES`, skipped above like "running") for the ordinary
    case of a just-asked-to-stop run that has not exited yet, but a run can
    also read "failed" while its processes are alive and well -- wedged
    (silent past STALL_AFTER_S) rather than gone. Freeing the block there let
    the scheduler pin a second FDS onto the SAME cores the wedged one was
    still burning.
    """
    state = dict(state)
    for block, run_dir in list(state.items()):
        if run_dir is None:
            continue
        run_path = Path(run_dir)
        status = runner_mod.status(run_path)
        if status["state"] in runner_mod.RUNNING_STATES:
            continue
        if status["state"] != "done" and runner_mod._launcher_alive(run_path) is True:
            _log(state_dir, f"{run_dir}: reported {status['state']} on block {block} but its "
                             f"process is still alive; held rather than freed")
            continue
        if status["state"] == "done":
            _clear_failures(run_path)
            _log(state_dir, f"{run_dir}: done on block {block}, freed")
        elif status["state"] == "failed":
            count = _record_failure(run_path)
            _log(state_dir, f"{run_dir}: failed on block {block} ({count}/{MAX_FAILURES}) "
                             f"-- {status.get('detail', '')}")
        else:
            _log(state_dir, f"{run_dir}: {status['state']} on block {block}, freed")
        lock = locks.pop(run_dir, None)
        if lock is not None:
            lock.close()
        state[block] = None
    return state


def _next_runnable(state_dir: Path, queue: list[str], logged_skips: set[str],
                   exclude: frozenset[str] = frozenset()) -> tuple[str | None, list[str]]:
    """The first queue entry that has not failed MAX_FAILURES times and is
    not in `exclude`, popped out (the caller decides whether to save the
    result). A run past the cap is skipped in place -- still in the queue,
    still visible to `fds-fleet`, so a human can dequeue or fix it -- and
    logged once per scheduler run rather than once per poll. `exclude` is
    the set of entries this same `step()` call has already tried and put
    back (locked elsewhere, or failed to launch): without it, several free
    blocks in one call would retry -- and re-fail -- the same entry once per
    free block instead of once per poll.
    """
    for i, run_dir in enumerate(queue):
        if run_dir in exclude:
            continue
        if _failure_count(Path(run_dir)) >= MAX_FAILURES:
            if run_dir not in logged_skips:
                count = _failure_count(Path(run_dir))
                _log(state_dir, f"{run_dir}: failed {count} times, skipped; inspect "
                                 f"{Path(run_dir) / runner_mod.LOG_NAME}")
                logged_skips.add(run_dir)
            continue
        return run_dir, queue[:i] + queue[i + 1:]
    return None, queue


def step(state_dir: Path, blocks: tuple[str, ...], state: dict[str, str | None],
         locks: dict[str, object], logged_skips: set[str]) -> dict[str, str | None]:
    """One iteration: free finished blocks, then fill every free block from
    the queue. Returns the new state; the caller persists it and sleeps --
    neither happens in here, which is what makes this directly testable
    without a real clock or a real FDS process.
    """
    state = _release_finished(state_dir, state, locks)
    free_blocks = [b for b in blocks if state[b] is None]
    if not free_blocks:
        return state
    with queue_lock(state_dir):
        queue = load_queue(state_dir)
        # Entries this call has already tried and put back -- a lock held
        # elsewhere, or a launch that failed -- so a second (or third) free
        # block in the SAME call does not immediately retry, and re-fail,
        # the same entry once per free block instead of once per poll.
        unavailable: set[str] = set()
        for block in free_blocks:
            run_dir, queue = _next_runnable(state_dir, queue, logged_skips,
                                            frozenset(unavailable))
            if run_dir is None:
                break
            if not Path(run_dir).is_dir():
                # A state.json/queue.txt entry naming a directory that is not
                # actually on disk (a stale adopted reference, a typo) --
                # counts toward MAX_FAILURES like any other launch problem
                # (see the `except` below), so a permanently bad entry gets
                # skipped in place instead of being retried, and re-logged,
                # forever.
                queue = [run_dir] + queue
                unavailable.add(run_dir)
                count = _record_failure(Path(run_dir))
                _log(state_dir, f"{run_dir}: does not exist on disk "
                                 f"({count}/{MAX_FAILURES}), skipped")
                continue
            if runner_mod._launcher_alive(Path(run_dir)) is True:
                # A live process already sits in this directory that this
                # scheduler instance does not hold the lock for -- an adopted
                # run not yet re-acquired (see run_forever's startup loop), or
                # one launched outside the scheduler entirely (the app's own
                # unpinned CFD step). Never launched into; not a failure of
                # the run itself, so not counted against it.
                queue = [run_dir] + queue
                unavailable.add(run_dir)
                _log(state_dir, f"{run_dir}: already has a live process, skipped")
                continue
            lock, unavailable_reason = _try_lock_run(Path(run_dir))
            if lock is None:
                # `_next_runnable` already popped this entry out of `queue` --
                # put it back (at the front: it was the earliest runnable one
                # found) so a lock held by someone else does not silently
                # drop it from the queue. Not counted as a failure: another
                # process holding this run dir is not this run's own fault.
                queue = [run_dir] + queue
                unavailable.add(run_dir)
                _log(state_dir, f"{run_dir}: {unavailable_reason}, skipped")
                continue
            try:
                _launch(Path(run_dir), block)
            except (FileNotFoundError, ValueError, RuntimeError) as exc:
                lock.close()
                count = _record_failure(Path(run_dir))
                # Stays in the queue (see above) -- a run below MAX_FAILURES
                # gets retried next poll; at the cap, `_next_runnable` starts
                # skipping it in place, which is only visible to a human
                # inspecting the queue if it is actually still in it.
                queue = [run_dir] + queue
                unavailable.add(run_dir)
                _log(state_dir, f"{run_dir}: could not launch on block {block} "
                                 f"({count}/{MAX_FAILURES}) -- {exc}")
                continue
            locks[run_dir] = lock
            state[block] = run_dir
            _log(state_dir, f"{run_dir}: launched on block {block} "
                             f"(I_MPI_PIN_PROCESSOR_LIST={block})")
        save_queue(state_dir, queue)
    return state


def _reacquire_locks(state_dir: Path, state: dict[str, str | None],
                     locks: dict[str, object]) -> None:
    """Re-acquire the per-run-dir lock for every block `state.json` already
    says is running, once, right at startup.

    C2: an OS-level `flock` is held by an open file descriptor, and releases
    the instant the process holding it exits -- so a freshly started (or
    restarted) scheduler process holds NONE of the locks its own state
    claims, even though the FDS runs those locks were protecting are still
    going. Without this, the very first `step()` after a restart could
    launch a second FDS in a directory the state file itself says is
    already occupied (`step()`'s own `_launcher_alive` guard before a launch
    is the OTHER half of this fix -- this one covers "already tracked",
    that one covers "not yet tracked at all").
    """
    for block, run_dir in state.items():
        if run_dir is None:
            continue
        lock, reason = _try_lock_run(Path(run_dir))
        if lock is not None:
            locks[run_dir] = lock
            _log(state_dir, f"{run_dir}: re-acquired the lock for block {block} at startup")
        else:
            _log(state_dir, f"{run_dir}: could not re-acquire the lock for block {block} "
                             f"at startup ({reason})")


# Set from the SIGTERM handler `run_forever` installs, checked between
# iterations of its own loop. A module-level flag rather than an
# instance/closure variable because `signal.signal` can only install a
# plain callable, and `run_forever` clears it on every call so one call's
# shutdown request (a test, in practice -- the systemd unit calls this once)
# can never leak into a later one.
_shutdown_event = threading.Event()


def _handle_sigterm(signum, frame) -> None:
    _shutdown_event.set()


def run_forever(state_dir: Path, blocks: tuple[str, ...], poll_s: float = POLL_S,
                stop_after: int | None = None) -> None:
    """The daemon loop `solit2 fds-scheduler` runs in the foreground.

    `stop_after` bounds the number of iterations; production callers never
    pass it and the loop runs until SIGTERM (systemd's normal stop signal)
    or the process is killed outright (`Restart=always` brings it back
    either way). Writes and then removes `PID_NAME` around the loop so
    `is_running()` can tell whether a scheduler is actually alive.

    C1: SIGTERM sets `_shutdown_event` rather than being left to Python's
    default handling (which raises `KeyboardInterrupt` at an arbitrary
    bytecode boundary -- possibly mid-`step()`, between a launch and the
    `state.json` write that records it). The loop checks the event between
    iterations and blocks its own poll interval on `_shutdown_event.wait`
    instead of `time.sleep`, so a stop is noticed WITHIN the wait rather than
    only after it, and always lands between iterations, never inside one.
    """
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    with _instance_lock(state_dir):
        _write_pid(state_dir)
        _shutdown_event.clear()
        previous_handler = signal.signal(signal.SIGTERM, _handle_sigterm)
        try:
            state = load_state(state_dir, blocks)
            locks: dict[str, object] = {}
            _reacquire_locks(state_dir, state, locks)
            logged_skips: set[str] = set()
            iterations = 0
            while stop_after is None or iterations < stop_after:
                if _shutdown_event.is_set():
                    _log(state_dir, "SIGTERM received; exiting between iterations")
                    break
                state = step(state_dir, blocks, state, locks, logged_skips)
                save_state(state_dir, state)
                iterations += 1
                if stop_after is None or iterations < stop_after:
                    if _shutdown_event.wait(poll_s):
                        _log(state_dir, "SIGTERM received; exiting between iterations")
                        break
        finally:
            signal.signal(signal.SIGTERM, previous_handler)
            (state_dir / PID_NAME).unlink(missing_ok=True)


def eta_ist(eta_s: float | None) -> str | None:
    """A run's `live()['eta_s']` as an IST clock time, for a reader who wants
    to know when a run will finish rather than how many seconds are left."""
    if eta_s is None:
        return None
    return (datetime.now(IST) + timedelta(seconds=eta_s)).isoformat(timespec="minutes")

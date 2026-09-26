"""Fleet-wide view and control of every FDS run directory this deployment
knows about.

`discover()` + `list_runs()` build a `RunInfo` per run directory (any
directory under `SOLIT2_RUN_ROOTS` holding a `deck.fds`) by reading exactly
what that run has produced -- its own deck, its own FDS log, its own CSVs --
plus the scheduler's `state.json`/`queue.txt` for which core block (if any)
it is on and where it sits in the queue. Nothing here is invented: a rate or
an ETA the run has not produced yet is `None`, never guessed at.

`pause`/`stop`/`resume`/`enqueue`/`dequeue`/`move` are the actions a fleet
operator takes on one run. Every one of them appends an IST-stamped JSON
line to `<state dir>/actions.jsonl` -- an audit trail independent of
`scheduler.log`, which records the scheduler's own decisions, not a human's.
"""
from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from solit2.engines.fds import deck as deck_mod
from solit2.engines.fds import runner as runner_mod
from solit2.engines.fds import scheduler as scheduler_mod
from solit2.schema.design import Design

IST = ZoneInfo("Asia/Kolkata")
RUN_ROOTS_ENV = "SOLIT2_RUN_ROOTS"
ACTIONS_LOG_NAME = "actions.jsonl"

_TITLE_RE = re.compile(r"TITLE='([^']*)'")
_DX_FROM_NAME_RE = re.compile(r"dx_([\d.]+)")
# Anything FDS calls out as ERROR or WARNING, in its own log.
_ISSUE_RE = re.compile(r"^[ \t]*(?:ERROR|WARNING)\b.*$", re.MULTILINE)


@dataclass(frozen=True)
class RunInfo:
    path: Path
    chid: str | None
    title: str | None
    dx_m: float | None
    e_coefficient: float | None
    state: str
    progress: float
    detail: str
    simulated_s: float | None
    t_end_s: float | None
    rate_s_per_s: float | None
    eta_s: float | None
    eta_ist: str | None
    core_block: str | None
    queue_position: int | None
    last_issue: str | None


@dataclass(frozen=True)
class FleetSummary:
    running: int
    queued: int
    done: int
    failed_or_stopped: int
    cores_busy: int
    cores_total: int
    scheduler_running: bool


def resolve_roots(explicit: str | None = None) -> tuple[Path, ...]:
    raw = explicit if explicit is not None else os.environ.get(RUN_ROOTS_ENV, "")
    return tuple(Path(p) for p in raw.split(":") if p.strip())


def discover(roots: tuple[Path, ...]) -> list[Path]:
    """Every directory under `roots` that holds its own `deck.fds`.

    A grid study or an E sweep nests several run dirs under one parent
    (`<out>/<chid>/dx_0.60`, `<out>/<anchor>/e_0.400_dx_0.60`), and each leaf
    carries its own `deck.fds` -- so "holds a deck.fds" is enough to find
    every run without needing to know which tool produced it.
    """
    found = []
    for root in roots:
        if not Path(root).is_dir():
            continue
        found += sorted(p.parent for p in Path(root).rglob("deck.fds"))
    return found


def _deck_text(run_dir: Path) -> str | None:
    deck = Path(run_dir) / "deck.fds"
    return deck.read_text() if deck.exists() else None


def _title(text: str | None) -> str | None:
    if text is None:
        return None
    match = _TITLE_RE.search(text)
    return match.group(1) if match else None


def _dx_m(run_dir: Path, text: str | None) -> float | None:
    """From the directory name first (`dx_0.60`, the naming every writer in
    this package uses), the deck's own first &MESH line otherwise (read via
    `deck.stored_dx_m`, the same reader `runner.prepare_resume` trusts for a
    resume) -- a run dir renamed or moved after being written still reports
    the cell size it actually ran at."""
    match = _DX_FROM_NAME_RE.search(Path(run_dir).name)
    if match:
        return float(match.group(1))
    if text is None:
        return None
    return deck_mod.stored_dx_m(run_dir)


def _last_issue(run_dir: Path) -> str | None:
    """The last line FDS or mpiexec itself called out as ERROR/WARNING.

    Reads BOTH `run.out` (mpiexec's own stdout/stderr, captured by
    `runner.run` -- where a launcher-level failure lands: a bad binary, a
    rank that crashed before FDS ever opened its own output file) and the
    run's own `<CHID>.out` (`log_path()`'s usual preference) when they
    differ, so an MPI-level error is never hidden behind a stale FDS log left
    over from an earlier attempt.
    """
    run_dir = Path(run_dir)
    texts = []
    captured = run_dir / runner_mod.LOG_NAME
    if captured.exists():
        texts.append(captured.read_text())
    own = runner_mod.log_path(run_dir)
    if own is not None and own != captured:
        texts.append(own.read_text())
    matches = [m for text in texts for m in _ISSUE_RE.finditer(text)]
    return matches[-1].group(0).strip() if matches else None


def _core_block(run_dir: Path, scheduler_state: dict[str, str | None]) -> str | None:
    for block, assigned in scheduler_state.items():
        if assigned is not None and Path(assigned) == Path(run_dir):
            return block
    return None


def _queue_position(run_dir: Path, queue: list[str]) -> int | None:
    for i, entry in enumerate(queue):
        if Path(entry) == Path(run_dir):
            return i
    return None


def _info(run_dir: Path, scheduler_state: dict[str, str | None], queue: list[str]) -> RunInfo:
    run_dir = Path(run_dir)
    status = runner_mod.status(run_dir)
    live = runner_mod.live(run_dir)
    text = _deck_text(run_dir)
    # I4: a rate or an ETA is only a measurement of something actually
    # advancing right now. Showing the last-known rate for a paused, failed
    # or done run reads as a prediction of a future that will not happen,
    # and a "resumable-in-...-minutes" ETA on a run frozen weeks ago is not
    # a rare edge case, it is the ordinary look of a halted queue.
    is_running = status["state"] in runner_mod.RUNNING_STATES
    return RunInfo(
        path=run_dir,
        chid=runner_mod._chid(run_dir),
        title=_title(text),
        dx_m=_dx_m(run_dir, text),
        e_coefficient=deck_mod.stored_e_coefficient(run_dir),
        state=status["state"],
        progress=status["progress"],
        detail=status.get("detail", ""),
        simulated_s=live["simulated_s"],
        t_end_s=live["t_end_s"],
        rate_s_per_s=live["rate_s_per_s"] if is_running else None,
        eta_s=live["eta_s"] if is_running else None,
        eta_ist=scheduler_mod.eta_ist(live["eta_s"]) if is_running else None,
        core_block=_core_block(run_dir, scheduler_state),
        queue_position=_queue_position(run_dir, queue),
        last_issue=_last_issue(run_dir),
    )


def list_runs(roots: tuple[Path, ...] | None = None, state_dir: Path | None = None,
              blocks: tuple[str, ...] | None = None) -> list[RunInfo]:
    roots = roots if roots is not None else resolve_roots()
    state_dir = state_dir if state_dir is not None else scheduler_mod.resolve_state_dir()
    blocks = blocks if blocks is not None else scheduler_mod.resolve_blocks()
    scheduler_state = scheduler_mod.load_state(state_dir, blocks)
    queue = scheduler_mod.load_queue(state_dir)
    return [_info(run_dir, scheduler_state, queue) for run_dir in discover(roots)]


def _block_width(block: str) -> int:
    """"10-19" -> 10 cores. Every block this scheduler manages is a
    contiguous inclusive core range, so a plain width, not a block count, is
    what "cores busy" should ever have meant."""
    lo, _, hi = block.partition("-")
    return int(hi) - int(lo) + 1


def summarise(infos: list[RunInfo], state_dir: Path | None = None,
             blocks: tuple[str, ...] | None = None) -> FleetSummary:
    state_dir = state_dir if state_dir is not None else scheduler_mod.resolve_state_dir()
    blocks = blocks if blocks is not None else scheduler_mod.resolve_blocks()
    scheduler_state = scheduler_mod.load_state(state_dir, blocks)
    cores_total = sum(_block_width(b) for b in blocks)
    cores_busy = sum(_block_width(b) for b, run_dir in scheduler_state.items()
                     if run_dir is not None)
    managed = {run_dir for run_dir in scheduler_state.values() if run_dir is not None}
    for info in infos:
        if info.state in runner_mod.RUNNING_STATES and str(info.path) not in managed:
            # Running but not pinned to any block -- the web app's own CFD
            # step launches unpinned (see app/views/cfd.py), so its cores are
            # real and busy even though no block accounts for them. One rank
            # per mesh is what `runner.run` actually asks the OS for.
            cores_busy += max(runner_mod.mesh_count(info.path / "deck.fds"), 1)
    return FleetSummary(
        running=sum(1 for i in infos if i.state in runner_mod.RUNNING_STATES),
        queued=sum(1 for i in infos
                  if i.state not in runner_mod.RUNNING_STATES and i.queue_position is not None),
        done=sum(1 for i in infos if i.state == "done"),
        failed_or_stopped=sum(1 for i in infos if i.state in ("failed", "stopped")),
        cores_busy=cores_busy,
        cores_total=cores_total,
        scheduler_running=scheduler_mod.is_running(state_dir),
    )


def to_json(infos: list[RunInfo]) -> list[dict]:
    rows = []
    for info in infos:
        row = asdict(info)
        row["path"] = str(row["path"])
        rows.append(row)
    return rows


def render_status(infos: list[RunInfo], summary: FleetSummary) -> str:
    lines = [
        f"{summary.cores_busy} of {summary.cores_total} cores busy "
        f"(scheduler {'running' if summary.scheduler_running else 'NOT running'})",
        f"running={summary.running} queued={summary.queued} done={summary.done} "
        f"failed_or_stopped={summary.failed_or_stopped}",
        "",
    ]
    if not infos:
        lines.append("no run directories found under SOLIT2_RUN_ROOTS")
        return "\n".join(lines)
    lines.append(f"{'state':<9}{'progress':>9}  {'block':>7}  {'queue':>5}  "
                 f"{'eta (IST)':<19}  run")
    for info in sorted(infos, key=lambda i: (i.queue_position is None, i.queue_position or 0,
                                             str(i.path))):
        queue_col = "" if info.queue_position is None else str(info.queue_position)
        lines.append(f"{info.state:<9}{info.progress * 100:8.0f}%  "
                     f"{info.core_block or '-':>7}  {queue_col:>5}  "
                     f"{info.eta_ist or '-':<19}  {info.path}")
    return "\n".join(lines)


# --- actions: every one logs to actions.jsonl --------------------------------

def _log_action(state_dir: Path, action: str, run_dir: Path, outcome: str) -> None:
    state_dir = Path(state_dir)
    state_dir.mkdir(parents=True, exist_ok=True)
    row = {"timestamp": datetime.now(IST).isoformat(timespec="seconds"),
           "action": action, "run": str(run_dir), "outcome": outcome}
    with (state_dir / ACTIONS_LOG_NAME).open("a") as f:
        f.write(json.dumps(row) + "\n")


def pause(run_dir: Path, state_dir: Path) -> Path:
    """Ask FDS to checkpoint and exit cleanly. Works whether or not a
    scheduler process is running: it signals the run's own process directly,
    the same way `runner.pause` always has."""
    run_dir = Path(run_dir)
    try:
        marker = runner_mod.pause(run_dir)
    except (FileNotFoundError, OSError) as exc:
        _log_action(state_dir, "pause", run_dir, f"failed: {exc}")
        raise
    _log_action(state_dir, "pause", run_dir, "ok")
    return marker


def stop(run_dir: Path, state_dir: Path) -> bool:
    """Kill the run's processes outright. Like `pause`, needs no scheduler
    running -- it acts on the run's own pid, not on the queue."""
    run_dir = Path(run_dir)
    try:
        killed = runner_mod.stop(run_dir)
    except (FileNotFoundError, PermissionError, OSError) as exc:
        _log_action(state_dir, "stop", run_dir, f"failed: {exc}")
        raise
    _log_action(state_dir, "stop", run_dir,
               "ok (processes killed)" if killed else "ok (nothing was running)")
    return killed


def _refuse_if_alive(action: str, run_dir: Path, state_dir: Path) -> None:
    """C2: never queue a directory that already has a live process -- the
    scheduler would eventually pick it up and launch a SECOND FDS on top of
    it. Not a scheduler-running check (that's a different question, see
    `enqueue`'s own docstring): this is "is anything actually running here
    right now", true or not regardless of whether a scheduler is watching."""
    if runner_mod._launcher_alive(Path(run_dir)) is True:
        _log_action(state_dir, action, run_dir, "failed: already running")
        raise ValueError(
            f"{run_dir} already has a live process; {action}ing it would risk launching a "
            f"second FDS in the same directory")


def enqueue(run_dir: Path, state_dir: Path, position: int | None = None) -> None:
    """Add `run_dir` to the scheduler's queue -- appended at the end by
    default, or inserted at `position`. Writing the queue file is all this
    does: nothing runs until a `solit2 fds-scheduler` process is polling it
    (see `scheduler.is_running`), which is why this never raises for "no
    scheduler running" -- the action is still recorded and still correct,
    just not yet acted on.

    I8: `run_dir` is resolved to an absolute path before it is written --
    an unresolved relative path is stored against whatever the SCHEDULER's
    own working directory happens to be at launch, not the caller's, so it
    silently names a different (or no) directory there; and it would never
    match the same run as discovered by `fleet.discover()`, which always
    walks from an absolute `SOLIT2_RUN_ROOTS` entry. Also requires
    `deck.fds` up front -- an empty or non-existent directory has nothing
    for the scheduler to launch, and queuing it would only be discovered as
    a launch failure minutes or hours later.
    """
    run_dir = Path(run_dir).resolve()
    if not (run_dir / "deck.fds").exists():
        raise FileNotFoundError(f"{run_dir} holds no deck.fds; there is nothing to enqueue")
    _refuse_if_alive("enqueue", run_dir, state_dir)
    entry = str(run_dir)
    with scheduler_mod.queue_lock(state_dir):
        queue = [q for q in scheduler_mod.load_queue(state_dir) if q != entry]
        if position is None:
            queue.append(entry)
        else:
            queue.insert(max(0, min(position, len(queue))), entry)
        scheduler_mod.save_queue(state_dir, queue)
    # I6: a human choosing to enqueue (or resume, which calls this) this run
    # again is a deliberate "try it again" -- the failure count from before
    # must not follow it back in and let it get skipped in place on its very
    # next turn, or worse, be one strike from there already.
    scheduler_mod._clear_failures(run_dir)
    _log_action(state_dir, "enqueue", run_dir, "ok")


def dequeue(run_dir: Path, state_dir: Path) -> None:
    run_dir = Path(run_dir)
    entry = str(run_dir)
    with scheduler_mod.queue_lock(state_dir):
        queue = scheduler_mod.load_queue(state_dir)
        if entry not in queue:
            _log_action(state_dir, "dequeue", run_dir, "failed: not queued")
            raise ValueError(f"{run_dir} is not in the queue")
        scheduler_mod.save_queue(state_dir, [q for q in queue if q != entry])
    _log_action(state_dir, "dequeue", run_dir, "ok")


def move(run_dir: Path, state_dir: Path, position: int) -> None:
    run_dir = Path(run_dir)
    entry = str(run_dir)
    with scheduler_mod.queue_lock(state_dir):
        queue = scheduler_mod.load_queue(state_dir)
        if entry not in queue:
            _log_action(state_dir, "move", run_dir, "failed: not queued")
            raise ValueError(f"{run_dir} is not in the queue")
        queue = [q for q in queue if q != entry]
        position = max(0, min(position, len(queue)))
        queue.insert(position, entry)
        scheduler_mod.save_queue(state_dir, queue)
    _log_action(state_dir, "move", run_dir, f"ok (position={position})")


def resume(run_dir: Path, state_dir: Path) -> None:
    """Enqueue a resume: append `run_dir` to the queue so the next free core
    block picks it up and regenerates its RESTART=.TRUE. deck. Refuses up
    front, before ever touching the queue, when there is nothing to resume
    FROM or nothing to resume WITH -- the same two checks `scheduler._launch`
    makes right before it would otherwise launch a resume with stale or
    absent physics.
    """
    run_dir = Path(run_dir)
    _refuse_if_alive("resume", run_dir, state_dir)
    if not runner_mod.has_restart_files(run_dir):
        _log_action(state_dir, "resume", run_dir, "failed: no restart files")
        raise FileNotFoundError(
            f"{run_dir} holds no restart files to resume from; start it again instead")
    design_path = run_dir / scheduler_mod.DESIGN_NAME
    if not design_path.exists():
        _log_action(state_dir, "resume", run_dir, f"failed: no {scheduler_mod.DESIGN_NAME}")
        raise FileNotFoundError(
            f"{run_dir} holds restart files but no {scheduler_mod.DESIGN_NAME}, so a resume "
            f"cannot regenerate its RESTART=.TRUE. deck. Write it beside deck.fds first -- "
            f"`solit2 fds-adopt {run_dir} --design <design.json>` -- then resume again")
    enqueue(run_dir, state_dir)
    _log_action(state_dir, "resume", run_dir, "enqueued")


def adopt_design(run_dir: Path, design: Design) -> Path:
    """Write `design.json` beside an existing run's `deck.fds`, so it can
    resume later even though it was not launched through a writer that sets
    this up itself (the app's CFD step, `fds-grid-study`, `fds-calibrate-e`)
    -- or had its `design.json` lost. `solit2 fds-adopt` is the CLI for this.
    """
    run_dir = Path(run_dir)
    if not (run_dir / "deck.fds").exists():
        raise FileNotFoundError(f"{run_dir} holds no deck.fds; there is no run to adopt a design onto")
    path = run_dir / scheduler_mod.DESIGN_NAME
    # by_alias=True: a field like Fire.fire_class (alias "class") must round-trip
    # through Design.load unambiguously -- writing the field name instead of the
    # alias leaves both spellings in a re-merged preset dict and Design.load
    # rejects it as an unrecognised field. See the same choice in grid.py,
    # calibrate.py and the app's CFD step.
    path.write_text(design.model_dump_json(indent=2, by_alias=True))
    return path

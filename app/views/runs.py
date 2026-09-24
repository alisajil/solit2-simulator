"""The CFD runs manager: every FDS run directory under `SOLIT2_RUN_ROOTS`,
its live progress, and pause/resume/stop/queue controls -- reachable from any
wizard step via the header button (see `streamlit_app.py`), not one of the
five wizard steps itself, because a fleet operator watching runs is a
different task than building one design.

Every number here comes from `solit2.engines.fds.fleet`, which reads it off
the run's own output (never invents a rate or an ETA), and every action goes
through `fleet`'s pause/stop/resume/enqueue/dequeue/move, which is what
writes the IST-stamped audit trail in `actions.jsonl`.

Works with no scheduler process running: pause and stop act on a run's own
process directly, so they still work. Resume and the queue only get acted on
once `solit2 fds-scheduler` is running to read them -- `fleet.summarise`
reports whether one currently is, and this page says so rather than letting
a queued action look like it did something it cannot yet do.
"""
from __future__ import annotations

import re
from pathlib import Path

import streamlit as st

from solit2.engines.fds import fleet
from solit2.engines.fds import runner as runner_mod
from solit2.engines.fds import scheduler as scheduler_mod
from solit2.engines.fds.exec_run import DESIGN_NAME

POLL = "10s"
_STATE_CHIP_CLASS = {"done": "pass", "failed": "fail", "stopped": "fail",
                     "paused": "unset", "running": "unset", "pausing": "unset",
                     "pending": "unset"}
_UNSAFE_KEY_CHARS = re.compile(r"[^A-Za-z0-9]+")
# I5: a confirmation dialog opened from INSIDE a fragment (`_live_panel`,
# `@st.fragment(run_every=POLL)`) is tied to that specific fragment
# invocation. When the fragment's own 10 s timer reruns it, that invocation
# no longer exists -- verified in a browser: the dialog stays visible but
# its buttons stop responding, and the server log says "The fragment with
# id ... does not exist anymore". The fix is this key: the row's Pause/Stop
# button never opens the dialog itself -- it records WHICH action is
# pending here and asks for a full-app rerun; `render()`, which lives
# OUTSIDE the fragment and re-runs on every rerun regardless of what
# triggered it, is what actually opens the dialog, checking this key
# unconditionally. That makes the open dialog's identity belong to the
# stable outer script, not to a fragment tick that will not outlive it.
_PENDING_KEY = "runs_pending_action"


def _key(path: Path) -> str:
    """A run's path, made safe for use inside a Streamlit widget key."""
    return _UNSAFE_KEY_CHARS.sub("_", str(path))


def _speed(info: fleet.RunInfo) -> str:
    return f"{info.rate_s_per_s * 60:.1f} s/min" if info.rate_s_per_s else "—"


def _counts(summary: fleet.FleetSummary) -> None:
    chips = (
        f'<span class="chip unset">{summary.running} running</span>'
        f'<span class="chip unset">{summary.queued} queued</span>'
        f'<span class="chip pass">{summary.done} done</span>'
        f'<span class="chip fail">{summary.failed_or_stopped} failed / stopped</span>'
    )
    st.markdown(chips, unsafe_allow_html=True)
    st.caption(f"{summary.cores_busy} of {summary.cores_total} cores busy")


def _request_confirmation(kind: str, run_dir: Path) -> None:
    """Record which row asked for a Pause/Stop confirmation, and ask for a
    full-app rerun. Never opens the dialog itself -- see `_PENDING_KEY`."""
    st.session_state[_PENDING_KEY] = {"kind": kind, "run": str(run_dir)}
    st.rerun(scope="app")


def _clear_pending() -> None:
    st.session_state.pop(_PENDING_KEY, None)


@st.dialog("Pause this run?")
def _confirm_pause(run_dir: Path, state_dir: Path) -> None:
    st.write(f"Asks FDS to finish its current step, write its restart files and exit "
             f"cleanly for `{run_dir}`. Not a kill: it can be resumed from where it stops "
             f"afterwards. A wedged run may not notice until it is stopped instead.")
    yes, no = st.columns(2)
    if yes.button("Pause it", key="dlg_pause_yes", type="primary"):
        _clear_pending()
        try:
            fleet.pause(run_dir, state_dir)
        except (FileNotFoundError, OSError) as exc:
            st.error(str(exc))
            return
        st.rerun()
    if no.button("Cancel", key="dlg_pause_no"):
        _clear_pending()
        st.rerun()


@st.dialog("Stop this run?")
def _confirm_stop(run_dir: Path, state_dir: Path) -> None:
    st.write(f"Kills every process for `{run_dir}` outright. Whatever restart files it "
             f"already wrote are kept, but the step it was on when this fires is lost. "
             f"For a run that has stopped responding and will not see a pause.")
    yes, no = st.columns(2)
    if yes.button("Stop it now", key="dlg_stop_yes", type="primary"):
        _clear_pending()
        try:
            fleet.stop(run_dir, state_dir)
        except (FileNotFoundError, PermissionError, OSError) as exc:
            st.error(str(exc))
            return
        st.rerun()
    if no.button("Cancel", key="dlg_stop_no"):
        _clear_pending()
        st.rerun()


def _open_pending_dialog(state_dir: Path) -> None:
    """Called from `render()`, outside the fragment, on every rerun -- the
    other half of the I5 fix. Whatever is pending stays open across a
    fragment tick because THIS call does, even though the row that
    originally requested it is redrawn fresh each time."""
    pending = st.session_state.get(_PENDING_KEY)
    if not pending:
        return
    run_dir = Path(pending["run"])
    if pending["kind"] == "pause":
        _confirm_pause(run_dir, state_dir)
    elif pending["kind"] == "stop":
        _confirm_stop(run_dir, state_dir)
    else:
        _clear_pending()


def _actions(info: fleet.RunInfo, state_dir: Path) -> None:
    key = _key(info.path)
    if info.state in runner_mod.RUNNING_STATES:
        col1, col2 = st.columns(2)
        # Pausing an already-pausing run asks nothing new; the process is
        # already on its way out.
        if col1.button("Pause", key=f"pause_{key}", width="stretch",
                       disabled=info.state != "running"):
            _request_confirmation("pause", info.path)
        if col2.button("Stop", key=f"stop_{key}", width="stretch"):
            _request_confirmation("stop", info.path)
        return
    if info.state in ("paused", "stopped"):
        has_restart = runner_mod.has_restart_files(info.path)
        has_design = (info.path / DESIGN_NAME).exists()
        col1, col2 = st.columns(2)
        if col1.button("Resume", key=f"resume_{key}", width="stretch",
                       disabled=not (has_restart and has_design)):
            try:
                fleet.resume(info.path, state_dir)
            except (FileNotFoundError, ValueError) as exc:
                st.error(str(exc))
            else:
                st.rerun(scope="app")
        if col2.button("Stop", key=f"stop_{key}", width="stretch"):
            _request_confirmation("stop", info.path)
        if not has_restart:
            st.caption("no restart files to resume from")
        elif not has_design:
            st.caption(f"needs {DESIGN_NAME} (`solit2 fds-adopt`) before it can resume")
        return
    # done, failed, pending or anything else: nothing to do UNLESS the
    # process is somehow still alive despite the reported state -- I3, the
    # stall-"failed" case Stop exists for (a wedged run that went quiet past
    # STALL_AFTER_S never becomes "failed" by exiting; only Stop ends it).
    if runner_mod._launcher_alive(info.path) is True:
        if st.button("Stop", key=f"stop_{key}"):
            _request_confirmation("stop", info.path)
        st.caption("reported " + info.state + ", but its process is still alive")
        return
    st.caption("—")


def _row(info: fleet.RunInfo, state_dir: Path) -> None:
    name_col, state_col, speed_col, eta_col, cores_col, issue_col, action_col = st.columns(
        [2.6, 1.1, 1.1, 1.5, 0.8, 2.0, 1.6])
    with name_col:
        st.markdown(f"**{info.title or info.chid or info.path.name}**")
        st.caption(str(info.path))
        text = f"{info.progress * 100:.0f}%"
        if info.simulated_s is not None and info.t_end_s:
            text += f" — {info.simulated_s:.0f} s of {info.t_end_s:.0f} s"
        st.progress(min(info.progress, 1.0), text=text)
    with state_col:
        st.markdown(f'<span class="chip {_STATE_CHIP_CLASS.get(info.state, "unset")}">'
                    f'{info.state}</span>', unsafe_allow_html=True)
        if info.detail:
            st.caption(info.detail)
    with speed_col:
        st.write(_speed(info))
    with eta_col:
        st.write(info.eta_ist or "—")
    with cores_col:
        st.write(info.core_block or "—")
    with issue_col:
        st.write(info.last_issue or "—")
    with action_col:
        _actions(info, state_dir)


def _queue_panel(state_dir: Path, infos: list[fleet.RunInfo]) -> None:
    queue = scheduler_mod.load_queue(state_dir)
    if not queue:
        st.caption("Nothing queued.")
        return
    by_path = {str(i.path): i for i in infos}
    for position, entry in enumerate(queue):
        info = by_path.get(entry)
        label = (info.title if info and info.title else None) or Path(entry).name
        pos_col, name_col, up_col, down_col, remove_col = st.columns([0.6, 3.4, 0.6, 0.6, 1.0])
        pos_col.write(str(position + 1))
        name_col.write(f"{label} — `{entry}`")
        key = _key(Path(entry))
        # A queue entry named here can vanish between this read and the
        # click -- the scheduler's own step() dequeues concurrently. A bare
        # ValueError from move/dequeue on a since-popped entry must not take
        # the whole page down; report it and let the next refresh show the
        # queue as it actually is now.
        if up_col.button("↑", key=f"up_{key}", disabled=position == 0):
            try:
                fleet.move(Path(entry), state_dir, position - 1)
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.rerun(scope="app")
        if down_col.button("↓", key=f"down_{key}", disabled=position == len(queue) - 1):
            try:
                fleet.move(Path(entry), state_dir, position + 1)
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.rerun(scope="app")
        if remove_col.button("Remove", key=f"remove_{key}"):
            try:
                fleet.dequeue(Path(entry), state_dir)
            except ValueError as exc:
                st.error(str(exc))
            else:
                st.rerun(scope="app")


@st.fragment(run_every=POLL)
def _live_panel(state_dir: Path, roots: tuple[Path, ...]) -> None:
    infos = fleet.list_runs(roots=roots, state_dir=state_dir)
    summary = fleet.summarise(infos, state_dir=state_dir)
    _counts(summary)
    if not summary.scheduler_running:
        st.warning(
            "No scheduler process detected (`solit2 fds-scheduler` is not running). "
            "Pause and Stop act on a run's own process directly and still work. Resume "
            "and queue changes are saved to the queue file, but nothing launches them "
            "until the scheduler is running.")
    if not infos:
        st.caption("No run directories (holding deck.fds) found under "
                   + ", ".join(str(r) for r in roots) + ".")
        return
    st.subheader("Runs")
    for info in sorted(infos, key=lambda i: (i.state not in runner_mod.RUNNING_STATES,
                                             str(i.path))):
        with st.container(border=True):
            _row(info, state_dir)
    st.subheader("Queue")
    _queue_panel(state_dir, infos)


def render() -> None:
    st.header("CFD runs")
    roots = fleet.resolve_roots()
    if not roots:
        st.info(f"Set {fleet.RUN_ROOTS_ENV} to one or more colon-separated run-directory "
                f"roots (e.g. /opt/solit2/runs:/opt/solit2-app/runs) to see runs here.")
        return
    state_dir = scheduler_mod.resolve_state_dir()
    # Outside the fragment, on purpose -- see _PENDING_KEY.
    _open_pending_dialog(state_dir)
    _live_panel(state_dir, roots)

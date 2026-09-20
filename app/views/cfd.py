"""Step 4: run the design in FDS and watch the CFD field on the same twin canvas.

Deck generation works anywhere; running needs FDS, which the pre-flight reports
honestly. The run directory is `runs/<design sha>` — the CLI's and the deck's
own CHID — so a run launched from the terminal, or one that outlived an app
restart, is picked up rather than relaunched.
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from app import state
from app.components import twin_canvas
from app.views.fire_test import ensure_trace
from app.views.result import ensure_result
from solit2.engines.fds import deck as fds_deck
from solit2.engines.fds import reader as fds_reader
from solit2.engines.fds import runner as fds_runner
from solit2.engines.fds import slices
from solit2.engines.reduced.envelope import _design_sha
from solit2.engines.reduced.state import RunTrace
from solit2.reports import correlation
from solit2.schema.design import Design
from solit2.schema.result import Result

RUNS_DIR = Path("runs")
DURATIONS = {"5 min": 5.0, "10 min": 10.0, "20 min": 20.0, "Full (design duration)": None}
DEFAULT_DURATION = "20 min"
QUANTITIES = (("Temperature", "TEMPERATURE"), ("Smoke", "SOOT DENSITY"), ("Mist", "MPUV"))
POLL = "10s"


def run_dir_for(design: Design) -> Path:
    return RUNS_DIR / _design_sha(design)


def stamp(run_dir: Path) -> tuple:
    """Names, sizes and mtimes of the slice files: the cache key for a re-read."""
    return tuple(sorted((p.name, p.stat().st_size, p.stat().st_mtime_ns)
                        for p in Path(run_dir).glob("*.sf")))


@st.cache_data(show_spinner=False)
def _load_slice(run_dir: str, quantity: str, stamp_key: tuple):
    """`stamp_key` is unused in the body: it exists so the cache re-reads when a file grows."""
    return slices.load_centreline(Path(run_dir), quantity)


def _preflight() -> list[str]:
    problems = fds_runner.preflight()
    chips = ("".join(f'<span class="chip fail">{p}</span>' for p in problems)
             or '<span class="chip pass">FDS ready</span>')
    st.markdown(chips, unsafe_allow_html=True)
    return problems


def _start_controls(design: Design, run_dir: Path, verb: str) -> None:
    st.caption("A Tier 2 run takes hours. It runs in the background; this page keeps up with it.")
    choice = st.radio("Simulated window", list(DURATIONS), horizontal=True, key="fds_minutes",
                      index=list(DURATIONS).index(DEFAULT_DURATION),
                      help="Shortens the run, not the system: the tank and the cost index "
                           "still size on the design's full discharge duration.")
    minutes = DURATIONS[choice]
    if st.button(f"{verb} ({choice})", key="fds_start", type="primary"):
        run_dir.mkdir(parents=True, exist_ok=True)
        deck_path = run_dir / "deck.fds"
        deck_path.write_text(fds_deck.generate(
            design, t_end_s=None if minutes is None else minutes * 60.0))
        fds_runner.run(deck_path, run_dir)
        st.rerun()


@st.fragment(run_every=POLL)
def _live_progress(run_dir: Path) -> None:
    status = fds_runner.status(run_dir)
    st.progress(min(status["progress"], 1.0),
                text=f"FDS running — {status['progress'] * 100:.0f} % of the simulated window. "
                     f"{status['detail']}".strip())
    if status["state"] != "running":
        st.rerun(scope="app")


def _canvas(design: Design, trace: RunTrace, run_dir: Path, running: bool) -> None:
    for tab, (label, quantity) in zip(st.tabs([label for label, _ in QUANTITIES]), QUANTITIES):
        with tab:
            slice_ = _load_slice(str(run_dir), quantity, stamp(run_dir))
            if slice_ is None:
                st.info("FDS has not written this slice yet." if running
                        else f"This run holds no {label.lower()} slice.")
                continue
            st.plotly_chart(twin_canvas.figure(design, trace, cfd=slice_), key=f"cfd_{quantity}")
            last = float(slice_.t_s[-1])
            st.caption(f"Preliminary — last complete frame at t = {last:.0f} s; the run is still going."
                       if running else f"{len(slice_.t_s)} frames to t = {last:.0f} s.")


def _smokeview(run_dir: Path) -> None:
    ready = fds_runner.smokeview_binary() is not None and any(run_dir.glob("*.smv"))
    if st.button("Open in Smokeview", key="open_smv", disabled=not ready):
        fds_runner.open_smokeview(run_dir)
    if not ready:
        st.caption("Smokeview opens on this machine once the run has written its .smv file "
                   f"and a smokeview binary is on PATH (or {fds_runner.SMV_ENV} is set).")


def _tier2(design: Design, run_dir: Path, tier1: Result) -> None:
    tier2 = state.get_tier2_result()
    if tier2 is None:
        try:
            tier2 = fds_reader.read(run_dir, design)
        except (OSError, ValueError, KeyError) as exc:
            st.error(f"The run finished but its result could not be read: {exc}")
            return
        state.set_tier2_result(tier2)
    st.subheader("Tier 1 vs Tier 2")
    for warning in tier2.warnings:
        st.warning(warning)
    st.markdown(correlation.render(tier1, tier2))


def render() -> None:
    st.header("CFD verify — Tier 2")
    design = state.get_design()
    if design is None:
        st.info("Build a design first.")
        return
    result = ensure_result(design)
    trace = ensure_trace(design, result)
    problems = _preflight()
    run_dir = run_dir_for(design)
    status = fds_runner.status(run_dir) if run_dir.exists() else None
    running = status is not None and status["state"] == "running"

    if running:
        _live_progress(run_dir)
    elif not problems:
        _start_controls(design, run_dir, "Re-run FDS" if status else "Start FDS run")
    if status is not None and status["state"] == "failed":
        st.error(f"The last FDS run did not finish: {status['detail']}")
    if status is None:
        st.info("Start a run to see the CFD field here.")
        return
    _canvas(design, trace, run_dir, running)
    _smokeview(run_dir)
    if status["state"] == "done":
        _tier2(design, run_dir, result)

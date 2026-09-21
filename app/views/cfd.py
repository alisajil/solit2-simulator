"""Step 4: run the design in FDS and watch the CFD field on the same twin canvas.

Two scenarios of one design: the fire WITH the mist system, and the same fire
in the same tunnel with no mist at all -- the free-burn reference the mist run
is judged against. Each is its own FDS run in its own directory (`runs/<CHID>`,
the deck's own CHID, so a run launched from the terminal or one that outlived
an app restart is picked up rather than relaunched); with both complete the
step shows their difference field and both HRR curves against Tier 1's.

Deck generation works anywhere; running needs FDS, which the pre-flight
reports honestly.
"""
from __future__ import annotations

from pathlib import Path

import plotly.graph_objects as go
import streamlit as st

from app import palette, state
from app.components import twin_canvas
from app.views.fire_test import ensure_trace
from app.views.result import ensure_result
from solit2.engines.fds import deck as fds_deck
from solit2.engines.fds import reader as fds_reader
from solit2.engines.fds import runner as fds_runner
from solit2.engines.fds import slices
from solit2.engines.reduced.state import RunTrace
from solit2.schema.design import Design
from solit2.schema.result import Result

RUNS_DIR = Path("runs")
DURATIONS = {"5 min": 5.0, "10 min": 10.0, "20 min": 20.0, "Full (design duration)": None}
DEFAULT_DURATION = "20 min"
SCENARIOS = (("With mist", True), ("Free burn", False))
# (label, the quantity string FDS writes into the .smv slice header). FDS names a
# species or particle field after its SPEC_ID / PART_ID: the deck's
# `QUANTITY='DENSITY', SPEC_ID='SOOT'` comes out as 'SOOT DENSITY' and
# `QUANTITY='MPUV', PART_ID='FINE'` as 'FINE MPUV' -- read off a real run's .smv.
QUANTITIES = (("Temperature", "TEMPERATURE"), ("Smoke", "SOOT DENSITY"), ("Mist", "FINE MPUV"))
MIST_ONLY = ("FINE MPUV",)         # no particles in a free burn, so no water-mass field
DIFFERENCE_LABEL = "mist − free burn"
POLL = "10s"
HRR_CHART_HEIGHT = 300


def run_dir_for(design: Design, suppression: bool = True) -> Path:
    return RUNS_DIR / fds_deck.chid(design, suppression)


def _suffix(suppression: bool) -> str:
    return "" if suppression else "_free"


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


def _start_controls(design: Design, run_dir: Path, verb: str, suppression: bool) -> None:
    st.caption("A Tier 2 run takes hours. It runs in the background; this page keeps up with it."
               + ("" if suppression else
                  " The free burn carries no droplets, so it is the cheaper of the two."))
    choice = st.radio("Simulated window", list(DURATIONS), horizontal=True,
                      key=f"fds_minutes{_suffix(suppression)}",
                      index=list(DURATIONS).index(DEFAULT_DURATION),
                      help="Shortens the run, not the system: the tank and the cost index "
                           "still size on the design's full discharge duration.")
    minutes = DURATIONS[choice]
    if st.button(f"{verb} ({choice})", key=f"fds_start{_suffix(suppression)}", type="primary"):
        run_dir.mkdir(parents=True, exist_ok=True)
        deck_path = run_dir / "deck.fds"
        deck_path.write_text(fds_deck.generate(
            design, t_end_s=None if minutes is None else minutes * 60.0,
            suppression=suppression))
        # The previous Tier 2 result describes a pair of runs that no longer exists here.
        state.set_tier2_result(None)
        fds_runner.run(deck_path, run_dir)
        st.rerun()


def _clock(seconds: float | None) -> str:
    """A duration a person can read at a glance."""
    if seconds is None:
        return "—"
    seconds = int(max(seconds, 0))
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60:02d}s"
    return f"{seconds // 3600}h {(seconds % 3600) // 60:02d}m"


def live_metrics(live: dict) -> list[tuple[str, str, str | None]]:
    """(label, value, help) for what the run is doing, from its own output.

    Every one of these is measured. Where a quantity needs something the run
    has not produced yet -- a rate needs two timestamps, an estimate needs a
    rate and a target -- it reads as unknown rather than being guessed at.
    """
    rate = live["rate_s_per_s"]
    fired = [f"detected {live['detect_s']:.0f} s" if live["detect_s"] else None,
             f"discharging from {live['activate_s']:.0f} s" if live["activate_s"] else None]
    return [
        ("Simulated", f"{live['simulated_s']:.0f} s" if live["simulated_s"] is not None else "—",
         f"of the deck's {live['t_end_s']:.0f} s window" if live["t_end_s"] else None),
        ("Running for", _clock(live["elapsed_s"]), "wall clock since the first time step"),
        ("Speed", f"{rate * 60:.1f} s/min" if rate else "—",
         "simulated seconds per minute, over the last 60 time steps rather than "
         "the whole run"),
        ("Left, at this speed", _clock(live["eta_s"]),
         "this run's speed has varied thirtyfold; treat it as the current rate "
         "carried forward, not a forecast"),
        ("Heat release", f"{live['hrr_mw']:.1f} MW" if live["hrr_mw"] is not None else "—",
         "the latest row of the run's own HRR output"),
        ("Time step", f"{live['step_size_s'] * 1000:.0f} ms" if live["step_size_s"] else "—",
         "shrinks as the fire grows, which is why progress is not linear"),
        ("Mist", " · ".join(f for f in fired if f) or "not yet triggered",
         "read from FDS's own control log, not from the design's timetable"),
    ]


@st.fragment(run_every=POLL)
def _live_progress(run_dir: Path) -> None:
    status = fds_runner.status(run_dir)
    live = fds_runner.live(run_dir)
    st.progress(min(status["progress"], 1.0),
                text=f"FDS running — {status['progress'] * 100:.0f} % of the simulated window. "
                     f"{status['detail']}".strip())
    metrics = live_metrics(live)
    for column, (label, value, help_text) in zip(st.columns(len(metrics)), metrics):
        column.metric(label, value, help=help_text)
    st.caption(f"Polled from the run's own output every {POLL}. "
               f"Step {live['time_step'] or 0:,}.")
    if status["state"] != "running":
        st.rerun(scope="app")


def _slice_caption(run_state: str, slice_) -> str:
    """Only a run that actually finished may describe its field as complete."""
    last = float(slice_.t_s[-1])
    if run_state == "running":
        return f"Preliminary — last complete frame at t = {last:.0f} s; the run is still going."
    if run_state == "done":
        return f"{len(slice_.t_s)} frames to t = {last:.0f} s."
    return (f"Incomplete — the run did not finish. Last frame written at t = {last:.0f} s; "
            f"this field is not a completed simulation.")


def _missing_slice_note(run_state: str, label: str) -> str:
    """Absence means different things while running, when finished, and when crashed."""
    if run_state == "running":
        return "FDS has not written this slice yet."
    if run_state == "done":
        return f"This run holds no {label.lower()} slice."
    return f"The run did not finish and never wrote a {label.lower()} slice."


def _read_slice(run_dir: Path, quantity: str, label: str):
    """The slice, or None with the reason already shown."""
    try:
        return _load_slice(str(run_dir), quantity, stamp(run_dir))
    except (OSError, ValueError) as exc:
        # A real run can carry meshes this reader cannot stitch. Say so and leave the
        # other fields selectable rather than taking the whole step down.
        st.warning(f"This run's {label.lower()} slice could not be read: {exc}")
        return None


def _canvas(design: Design, trace: RunTrace, run_dir: Path, run_state: str,
            suppression: bool, other_dir: Path | None) -> None:
    """One field at a time, deliberately.

    `st.tabs` runs every tab's body on every rerun, so three animated figures were
    built each time — measured at 2.6 s and 13.8 MB apiece, and this step reruns
    every few seconds while a run is live. A selector builds only the chosen field.
    """
    options = [name for name, q in QUANTITIES if suppression or q not in MIST_ONLY]
    label = st.segmented_control("Field", options, default=options[0], key="cfd_quantity")
    label = label if label in options else options[0]   # deselected, or Mist on a free burn
    quantity = dict(QUANTITIES)[label]
    slice_ = _read_slice(run_dir, quantity, label)
    if slice_ is None:
        st.info(_missing_slice_note(run_state, label))
        return
    field, key = slice_, f"cfd_{quantity}"
    if other_dir is not None and quantity not in MIST_ONLY:
        other = _read_slice(other_dir, quantity, label)
        if other is not None and st.checkbox(f"Show the difference: {DIFFERENCE_LABEL}",
                                             key="cfd_compare"):
            mist, free = (slice_, other) if suppression else (other, slice_)
            try:
                field, key = slices.difference(mist, free, DIFFERENCE_LABEL), f"cfd_diff_{quantity}"
            except ValueError as exc:
                st.warning(f"The two runs cannot be differenced yet: {exc}")
    # Opened on the newest frame, not on t = 0: at t = 0 a difference field is
    # zero everywhere and the water-mass field holds no droplets, so the two
    # fields this selector exists for both open as an empty picture. The caption
    # below already describes that last frame.
    st.plotly_chart(twin_canvas.figure(design, trace, cfd=field, initial_frame=-1),
                    key=key, theme=None)
    st.caption(_slice_caption(run_state, slice_))


def _smokeview(run_dir: Path) -> None:
    ready = fds_runner.smokeview_binary() is not None and any(run_dir.glob("*.smv"))
    if st.button("Open in Smokeview", key="open_smv", disabled=not ready):
        fds_runner.open_smokeview(run_dir)
    if not ready:
        st.caption("Smokeview opens on this machine once the run has written its .smv file "
                   f"and a smokeview binary is on PATH (or {fds_runner.SMV_ENV} is set).")


def deck_window_s(run_dir: Path) -> float | None:
    """The T_END the deck was actually run to, read back from the deck itself."""
    deck = Path(run_dir) / "deck.fds"
    if not deck.exists():
        return None
    match = fds_runner._T_END.search(deck.read_text())
    return float(match.group(1)) if match else None


def window_caveat(run_dir: Path, design: Design) -> str | None:
    """Named whenever Tier 2 covers less exposure than the design discharges for.

    A shortened FDS window does not shorten the criteria: peak and dose criteria
    (`max_air_temp_c`, `max_fed`, `max_co_ppm`, exposure duration) are evaluated over
    whatever trace exists, so a truncated run is biased toward passing. Comparing that
    column against a full-length Tier 1 without saying so overstates the agreement.
    """
    ran_s = deck_window_s(run_dir)
    full_s = design.zones.duration_min * 60.0
    if ran_s is None or ran_s >= full_s - 1.0:
        return None
    return (f"Tier 2 covers 0–{ran_s:.0f} s of the design's {full_s:.0f} s discharge. "
            f"Peak and dose criteria are evaluated over that shorter exposure, so they "
            f"are not comparable with the full-length Tier 1 column.")


def _hrr_csv(run_dir: Path, design: Design, suppression: bool) -> tuple[list[float], list[float]] | None:
    path = run_dir / f"{fds_deck.chid(design, suppression)}_hrr.csv"
    if not path.exists():
        return None
    try:
        ids, rows = fds_reader._read_csv(path)
        col = ids.index("HRR")
    except (OSError, ValueError, IndexError):
        return None
    return [r[0] for r in rows], [r[col] / 1000.0 for r in rows]


def hrr_comparison(design: Design, trace: RunTrace, mist_dir: Path, free_dir: Path) -> go.Figure | None:
    """Both tiers, both scenarios, one clock: the suppression the mist buys, as
    each engine computes it. Only what exists is drawn -- a scenario that has
    not run has no curve, not a placeholder."""
    series = []
    mist = _hrr_csv(mist_dir, design, True)
    if mist:
        series.append(("Tier 2 · with mist", *mist, palette.PRIMARY, "solid"))
    free = _hrr_csv(free_dir, design, False)
    if free:
        series.append(("Tier 2 · free burn", *free, palette.FAIL, "solid"))
    if not series:
        return None
    t1 = [s.t_s for s in trace.steps]
    series.append(("Tier 1 · with mist", t1, [s.hrr_mw for s in trace.steps], palette.PRIMARY, "dot"))
    series.append(("Tier 1 · free burn", t1, [s.hrr_free_mw for s in trace.steps], palette.FAIL, "dot"))
    fig = go.Figure([go.Scatter(x=t, y=q, mode="lines", name=name,
                                line={"color": colour, "dash": dash})
                     for name, t, q, colour, dash in series])
    fig.update_layout(height=HRR_CHART_HEIGHT, xaxis_title="test clock (s)",
                      yaxis_title="heat release rate (MW)",
                      legend={"orientation": "h", "y": -0.25},
                      margin={"l": 10, "r": 10, "t": 30, "b": 10},
                      title={"text": "Heat release: free burn vs with mist", "x": 0.02,
                             "xanchor": "left", "font": {"size": 13}})
    return fig


def _tier2(design: Design, run_dir: Path, tier1: Result, free_dir: Path | None) -> None:
    tier2 = state.get_tier2_result()
    if tier2 is None:
        try:
            tier2 = fds_reader.read(run_dir, design, free_burn_dir=free_dir)
        except (OSError, ValueError, KeyError) as exc:
            st.error(f"The run finished but its result could not be read: {exc}")
            return
        state.set_tier2_result(tier2)
    st.subheader("Tier 1 vs Tier 2")
    for warning in tier2.warnings:
        st.warning(warning)
    caveat = window_caveat(run_dir, design)
    if caveat:
        st.warning(caveat)
    from solit2.reports import correlation
    st.markdown(correlation.render(tier1, tier2))


def _status(run_dir: Path) -> dict | None:
    return fds_runner.status(run_dir) if run_dir.exists() else None


def render() -> None:
    st.header("CFD verify — Tier 2")
    design = state.get_design()
    if design is None:
        st.info("Build a design first.")
        return
    result = ensure_result(design)
    trace = ensure_trace(design, result)
    problems = _preflight()

    scenario = st.segmented_control("Scenario", [name for name, _ in SCENARIOS],
                                    default=SCENARIOS[0][0], key="cfd_scenario")
    suppression = dict(SCENARIOS).get(scenario, True)
    run_dir, other_dir = run_dir_for(design, suppression), run_dir_for(design, not suppression)
    status, other_status = _status(run_dir), _status(other_dir)
    running = status is not None and status["state"] == "running"

    if running:
        _live_progress(run_dir)
    elif not problems:
        verb = "Re-run FDS" if status else "Start FDS run"
        _start_controls(design, run_dir, verb if suppression else f"{verb} (free burn)", suppression)
    if status is not None and status["state"] == "failed":
        st.error(f"The last FDS run did not finish: {status['detail']}")
    if status is None:
        st.info(f"Start the {(scenario or SCENARIOS[0][0]).lower()} run to see its CFD field here.")
    else:
        _canvas(design, trace, run_dir, status["state"], suppression,
                other_dir if other_status is not None else None)
        _smokeview(run_dir)

    mist_dir, free_dir = run_dir_for(design, True), run_dir_for(design, False)
    mist_status, free_status = (status, other_status) if suppression else (other_status, status)
    if mist_status is not None or free_status is not None:
        chart = hrr_comparison(design, trace, mist_dir, free_dir)
        if chart is not None:
            st.plotly_chart(chart, key="cfd_hrr")
    if mist_status is not None and mist_status["state"] == "done":
        free_done = free_status is not None and free_status["state"] == "done"
        _tier2(design, mist_dir, result, free_dir if free_done else None)

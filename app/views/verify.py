"""The Verify view: Tier 2 (FDS) pre-flight, deck, run and comparison.

Deck generation works on any machine. Running needs an FDS install, which this
page reports on honestly rather than offering a button that cannot work.
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from app import state
from solit2.engines.fds import deck as fds_deck
from solit2.engines.fds import runner as fds_runner
from solit2.engines.reduced.envelope import _design_sha
from solit2.reports import correlation
from solit2.schema.design import Design
from solit2.schema.result import Result

# The deck runs to tens of thousands of characters; st.code is a preview, and
# the download button beside it carries the whole file.
DECK_PREVIEW_CHARS = 4000


def _render_preflight() -> list[str]:
    st.subheader("Pre-flight")
    problems = fds_runner.preflight()
    if problems:
        for problem in problems:
            st.warning(problem)
    else:
        st.success("FDS is available -- a Tier 2 run can be started from here.")
    return problems


def _render_deck(design: Design) -> None:
    st.subheader("Deck")
    if st.button("Generate FDS deck"):
        text = fds_deck.generate(design)
        st.code(text[:DECK_PREVIEW_CHARS], language="text")
        if len(text) > DECK_PREVIEW_CHARS:
            st.caption(f"Preview only: the first {DECK_PREVIEW_CHARS:,} of "
                       f"{len(text):,} characters. The download below is the "
                       f"whole deck.")
        st.download_button("Download deck (.fds)", text,
                           file_name=f"{design.meta.name}.fds")


def _render_run(design: Design, blocked: list[str]) -> None:
    st.subheader("Run")
    if blocked:
        st.info("A Tier 2 run needs the pre-flight above to pass first.")
        return
    st.caption("A Tier 2 run takes hours. It is launched in the background; "
              "come back to this page for progress.")
    # Keyed on the design sha, matching the CLI and the deck's own CHID. Keyed
    # on the name, two edits of one design would share a directory -- and a
    # progress bar reporting the wrong run.
    run_dir = Path("runs") / _design_sha(design)
    if st.button("Start FDS run", type="primary"):
        run_dir.mkdir(parents=True, exist_ok=True)
        deck_path = run_dir / "deck.fds"
        deck_path.write_text(fds_deck.generate(design))
        fds_runner.run(deck_path, run_dir)
        st.success(f"Launched in {run_dir}")
    if run_dir.exists():
        status = fds_runner.status(run_dir)
        st.progress(status["progress"], text=f"{status['state']} -- "
                                            f"{status['progress'] * 100:.0f}%")


def _render_comparison() -> None:
    st.subheader("Tier 1 vs Tier 2")
    tier1 = state.get_result()
    if tier1 is None:
        st.info("Run the design on the Run page to get a Tier 1 result to compare against.")
        return
    uploaded = st.file_uploader("Tier 2 result JSON", type="json", key="verify_tier2")
    if uploaded is None:
        return
    try:
        tier2 = Result.model_validate_json(uploaded.getvalue())
    except ValueError as exc:
        st.error(f"Could not read that result: {exc}")
        return
    # Every Tier 2 stand-in is recorded in the result's warnings. This is the
    # one page where the two tiers are read side by side, so it is the one page
    # that must not present Tier 2's numbers without them.
    for warning in tier2.warnings:
        st.warning(warning)
    st.markdown(correlation.render(tier1, tier2))


def render() -> None:
    st.header("Verify")
    design = state.get_design()
    if design is None:
        st.warning("Build a design on the Design page first to evaluate "
                   "its Tier 2 FDS performance.")
        return
    problems = _render_preflight()
    _render_deck(design)
    _render_run(design, problems)
    st.divider()
    _render_comparison()

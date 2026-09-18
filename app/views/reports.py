"""The Reports view: markdown test-plan and correlation reports."""
from __future__ import annotations

import streamlit as st

from app import state
from solit2.reports import correlation, test_plan
from solit2.schema.result import Result


def _render_test_plan() -> None:
    st.subheader("Test plan")
    design = state.get_design()
    result = state.get_result()
    if design is None or result is None:
        st.warning("Build a design and run it on the Run page first.")
        return
    md = test_plan.render(design, result)
    st.markdown(md)
    st.download_button("Download test plan (.md)", md,
                       file_name=f"{design.meta.name}-test-plan.md")


def _render_correlation() -> None:
    st.subheader("Correlation")
    st.caption(
        "Compare one design's criteria across two runs -- typically the SOLIT2 "
        "test-facility geometry against the real site. Produce each result JSON "
        "with the download button on the Run page."
    )
    test_file = st.file_uploader("Test-facility result JSON", type="json",
                                 key="reports_test_file")
    site_file = st.file_uploader("Site result JSON", type="json",
                                 key="reports_site_file")
    if test_file is None or site_file is None:
        return
    try:
        test_result = Result.model_validate_json(test_file.getvalue())
        site_result = Result.model_validate_json(site_file.getvalue())
    except ValueError as exc:
        st.error(f"Could not read a result file: {exc}")
        return
    md = correlation.render(test_result, site_result)
    st.markdown(md)
    st.download_button("Download correlation report (.md)", md, file_name="correlation.md")


def render() -> None:
    st.header("Reports")
    _render_test_plan()
    st.divider()
    _render_correlation()

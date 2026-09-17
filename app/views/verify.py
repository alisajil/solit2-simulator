"""The Verify view: explicitly not implemented.

Tier 2 (FDS) verification is Plan 2 of this project and has not been built.
This view says so plainly rather than showing a "Verify" button that queues
a job nothing can run.
"""
from __future__ import annotations

import streamlit as st


def render() -> None:
    st.header("Verify")
    st.info(
        "FDS (Tier 2 CFD) verification is not built yet -- it is a separate, "
        "unstarted plan. This tool currently reports the reduced-order "
        "(Tier 1) engine's own results only, shown on the Run and Tunnel pages."
    )

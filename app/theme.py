"""Fonts and the handful of CSS rules Streamlit's theme options cannot express.

Everything colour- and type-related that CAN live in `.streamlit/config.toml`
does; this block covers only the stepper pills, the verdict banner, status
chips and the HMI lamps. Semantic colours are repeated here as literals
because CSS cannot read the TOML tokens.
"""
from __future__ import annotations

import streamlit as st

from app.palette import FAIL, GREY, PASS, PRIMARY, UNSET  # noqa: F401 -- re-exported

FONT_LINK = (
    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2'
    '?family=IBM+Plex+Sans:wght@400;500;600&family=IBM+Plex+Mono:wght@400;500'
    '&display=swap">'
)

CSS = f"""
<style>
[class*="st-key-step_"] button {{ border-radius: 999px; font-weight: 500; }}
[class*="st-key-step_"] button:disabled {{ opacity: 0.45; }}
.verdict {{ display: flex; gap: 1.25rem; align-items: baseline; flex-wrap: wrap;
           padding: 0.9rem 1.2rem; border-radius: 0.5rem; margin-bottom: 1rem;
           border: 1px solid {GREY}55; }}
.verdict.pass {{ border-left: 6px solid {PASS}; }}
.verdict.fail {{ border-left: 6px solid {FAIL}; }}
.verdict-label {{ font-size: 1.8rem; font-weight: 600; letter-spacing: 0.04em; }}
.verdict.pass .verdict-label {{ color: {PASS}; }}
.verdict.fail .verdict-label {{ color: {FAIL}; }}
.verdict-score {{ font-family: "IBM Plex Mono", monospace; font-size: 1.2rem;
                 font-variant-numeric: tabular-nums; }}
.verdict-note {{ opacity: 0.8; }}
.chip {{ display: inline-block; padding: 0.15rem 0.6rem; border-radius: 999px;
        font-size: 0.8rem; margin: 0 0.3rem 0.3rem 0; border: 1px solid transparent; }}
.chip.pass {{ background: {PASS}26; color: {PASS}; border-color: {PASS}; }}
.chip.fail {{ background: {FAIL}26; color: {FAIL}; border-color: {FAIL}; }}
.chip.unset {{ background: {UNSET}26; color: {UNSET}; border-color: {UNSET}; }}
.lamps {{ display: flex; gap: 1.5rem; font-size: 0.9rem; margin: 0.3rem 0 1rem; }}
.lamp {{ display: inline-block; width: 0.8rem; height: 0.8rem; border-radius: 2px;
        margin-right: 0.4rem; vertical-align: middle; background: {GREY}; opacity: 0.4; }}
.lamp.on {{ background: {PASS}; opacity: 1; box-shadow: 0 0 6px {PASS}; }}
</style>
"""


def inject() -> None:
    """Emit the font link and the CSS once per script run."""
    st.markdown(FONT_LINK + CSS, unsafe_allow_html=True)

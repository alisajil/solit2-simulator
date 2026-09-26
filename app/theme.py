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
.chip.neutral {{ background: {GREY}26; color: {GREY}; border-color: {GREY}; }}
.lamps {{ display: flex; gap: 1.5rem; font-size: 0.9rem; margin: 0.3rem 0 1rem; }}
.lamp {{ display: inline-block; width: 0.8rem; height: 0.8rem; border-radius: 2px;
        margin-right: 0.4rem; vertical-align: middle; background: {GREY}; opacity: 0.4; }}
.lamp.on {{ background: {PASS}; opacity: 1; box-shadow: 0 0 6px {PASS}; }}
.sim-head {{ font-family: "IBM Plex Mono", monospace; font-size: 0.85rem; letter-spacing: 0.18em;
            text-transform: uppercase; opacity: 0.9; margin: 0.2rem 0 0.8rem; }}
.sim-label {{ font-family: "IBM Plex Mono", monospace; font-size: 0.72rem; letter-spacing: 0.14em;
             text-transform: uppercase; opacity: 0.75; margin: 0.9rem 0 0.3rem; }}
.tiles {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(10rem, 1fr)); gap: 0.75rem;
         margin-bottom: 0.8rem; }}
.tile {{ border: 1px solid {GREY}55; border-radius: 0.5rem; padding: 0.7rem 0.9rem; }}
.tile-label {{ font-family: "IBM Plex Mono", monospace; font-size: 0.7rem; letter-spacing: 0.12em;
              text-transform: uppercase; opacity: 0.75; }}
.tile-value {{ font-size: 1.7rem; font-weight: 500; font-variant-numeric: tabular-nums; margin-top: 0.2rem; }}
.tile-note {{ font-size: 0.78rem; opacity: 0.7; }}
.diag {{ font-family: "IBM Plex Mono", monospace; font-size: 0.78rem; opacity: 0.85;
        display: flex; gap: 0.8rem; align-items: center; flex-wrap: wrap; margin-bottom: 0.4rem; }}
.pill {{ border: 1px solid {PRIMARY}; color: {PRIMARY}; border-radius: 999px; padding: 0.1rem 0.6rem;
        letter-spacing: 0.12em; white-space: nowrap; }}
.dot {{ display: inline-block; width: 0.5rem; height: 0.5rem; border-radius: 50%; background: {PRIMARY};
       margin-right: 0.4rem; animation: sim-pulse 1.6s ease-in-out infinite; }}
@keyframes sim-pulse {{ 0%, 100% {{ opacity: 1; }} 50% {{ opacity: 0.25; }} }}
@media (prefers-reduced-motion: reduce) {{ .dot {{ animation: none; }} }}
</style>
"""


def inject() -> None:
    """Emit the font link and the CSS once per script run."""
    st.markdown(FONT_LINK + CSS, unsafe_allow_html=True)

"""The Plotly template for figures drawn with `theme=None`.

Those figures opt out of Streamlit's own chart theme (it rewrites near-black
colours, which breaks the temperature scales), so they must be given the app's
colours explicitly. The viewer's theme comes from `st.context.theme.type`, which
Streamlit infers from the page background; it can be unknown on a session's
first run, and the app is dark by default, so unknown means dark.

The colours are read from `.streamlit/config.toml` rather than restated: that
file is where Streamlit takes them from, so the two cannot drift apart.
"""
from __future__ import annotations

import tomllib
from functools import lru_cache
from pathlib import Path

import plotly.graph_objects as go
import plotly.io as pio
import streamlit as st

CONFIG = Path(".streamlit/config.toml")
FONT_FAMILY = "IBM Plex Sans, sans-serif"


@lru_cache(maxsize=1)
def _palettes() -> dict:
    return tomllib.loads(CONFIG.read_text())["theme"]


def template(theme_type: str | None) -> go.layout.Template:
    variant = "light" if theme_type == "light" else "dark"
    colours = _palettes()[variant]
    base = pio.templates["plotly_white" if variant == "light" else "plotly_dark"]
    out = go.layout.Template(base)
    out.layout.paper_bgcolor = colours["backgroundColor"]
    out.layout.plot_bgcolor = colours["backgroundColor"]
    out.layout.font = {"family": FONT_FAMILY, "color": colours["textColor"]}
    return out


def current() -> go.layout.Template:
    return template(getattr(st.context.theme, "type", None))

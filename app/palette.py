"""The semantic colours, in one place.

These were previously restated in three: `app/theme.py`'s CSS literals, and again
in `app/components/twin_canvas.py` — including as hand-expanded `rgba(29,143,138,…)`
strings, where a changed token would not obviously be wrong until someone compared
a chart against a chip. `.streamlit/config.toml` has to restate them too (Streamlit
reads TOML, not Python), so a test pins the two together rather than trusting them
to stay in step.

No Streamlit import here on purpose: the pure canvas layer draws from these, and
must not acquire a dependency on the render layer to do it.
"""
from __future__ import annotations

PASS = "#2E8B57"
FAIL = "#C4452B"
UNSET = "#C98A1E"
PRIMARY = "#1D8F8A"      # the mist, and the app's accent
GREY = "#8A94A6"         # tunnel structure, and anything idle
TRANSPARENT = "rgba(0,0,0,0)"


def rgba(colour: str, alpha: float) -> str:
    """A `#rrggbb` token as `rgba(...)`, so a fill and its outline cannot drift apart."""
    raw = colour.lstrip("#")
    red, green, blue = (int(raw[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({red},{green},{blue},{alpha:g})"

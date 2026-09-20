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
STEAM = "#D8EEEC"        # evaporated water, near the ceiling -- pale, not the mist's own teal
TRANSPARENT = "rgba(0,0,0,0)"


def rgba(colour: str, alpha: float) -> str:
    """A `#rrggbb` token as `rgba(...)`, so a fill and its outline cannot drift apart.

    Fixed-point, not `:g` -- `:g` switches to scientific notation below 1e-4
    (`4.8e-05`), which Plotly's own colour parser rejects outright. A caller scaling
    alpha by a small real quantity (an ignition-progress fraction, a cooling fraction)
    can land there legitimately, so the formatter has to survive it.
    """
    raw = colour.lstrip("#")
    red, green, blue = (int(raw[i:i + 2], 16) for i in (0, 2, 4))
    text = f"{alpha:.6f}".rstrip("0").rstrip(".") or "0"
    return f"rgba({red},{green},{blue},{text})"

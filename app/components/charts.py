"""Plotly and pandas builders shared by the wizard steps."""
from __future__ import annotations

import pandas as pd
import plotly.graph_objects as go

from solit2.reports import labels
from solit2.schema.result import Criterion


def criteria_table(criteria: dict[str, Criterion]) -> pd.DataFrame:
    """One row per criterion, in the shape `st.dataframe` renders directly.

    `value` and `limit` are cast to `str`: `Criterion.value` mixes `bool`
    and `float` and `Criterion.limit` adds `None` and `tuple[float, float]`
    on top, so left as-is the column lands on pandas/Arrow as `object` with
    mixed Python types, which `st.dataframe` cannot serialize cleanly. This
    is a presentation table, so a string column sidesteps that entirely.
    """
    rows = []
    for name, c in criteria.items():
        rows.append({
            "criterion": labels.label(name),
            "unit": labels.unit(name) or "—",
            "value": labels.value(name, c.value),
            "limit": _limit_text(name, c.limit),
            "status": c.status,
            "margin": labels.value("", c.margin),
        })
    return pd.DataFrame(rows)


def _limit_text(name: str, limit: object) -> str:
    """A range limit reads as a range; an unset one stays a dash, never a zero."""
    if limit is None:
        return "—"
    if isinstance(limit, tuple):
        return " – ".join(labels.value(name, v) for v in limit)
    return labels.value(name, limit)


def timeseries_chart(timeseries: dict[str, list[float]], keys: list[str]) -> go.Figure:
    """One line per key in `keys`; `timeseries["t_s"]` is the shared x-axis.

    Every key must be a real key in `timeseries` -- callers read the actual
    key names from a real `Result.timeseries` dict rather than guessing them,
    since this function raises `KeyError` on a name that is not there.
    """
    t = timeseries["t_s"]
    fig = go.Figure()
    for key in keys:
        fig.add_trace(go.Scatter(x=t, y=timeseries[key], mode="lines", name=labels.heading(key)))
    fig.update_layout(xaxis_title="test clock (s)", height=350,
                      margin=dict(l=10, r=10, t=30, b=10))
    return fig

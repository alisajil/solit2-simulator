"""Markdown correlation report: one design's criteria across two runs, side by
side -- typically the SOLIT2 test-facility geometry against the real site.
"""
from __future__ import annotations

from solit2.reports import labels
from solit2.schema.result import Result

# Runs within this fraction of each other cover the same exposure for reporting
# purposes; a sample or two of difference is not a caveat worth printing.
COVERAGE_TOLERANCE = 0.99


def _column(result: Result) -> str:
    """Design name AND engine.

    The comparison this report exists for is one design across two tiers, and
    naming only the design heads both columns with the same string -- a table
    whose two sides cannot be told apart.
    """
    return f"{result.meta['design_name']} ({result.meta.get('engine', 'unknown engine')})"


def _covered_s(result: Result) -> float | None:
    """How far into the fire this run actually got, from its own clock."""
    times = result.timeseries.get("t_s") or []
    return float(times[-1]) if times else None


def coverage_note(test_result: Result, site_result: Result) -> str | None:
    """Named whenever the two columns do not cover the same exposure.

    Every criterion in the table is a peak or a dose, so each is evaluated over
    whatever trace exists. A column from a shorter run is therefore biased
    toward passing, and setting the two side by side without saying so reads as
    agreement between the tiers when it is partly a difference in how long they
    ran. Both results carry their own clock, so this holds for any caller --
    the CLI's `report correlation` had no such caveat at all.
    """
    covered = {_column(r): _covered_s(r) for r in (test_result, site_result)}
    if any(v is None for v in covered.values()) or len(covered) < 2:
        return None
    (short_name, short_s), (long_name, long_s) = sorted(covered.items(), key=lambda kv: kv[1])
    if short_s >= long_s * COVERAGE_TOLERANCE:
        return None
    return (f"**{short_name} covers 0-{short_s:.0f} s against {long_name}'s {long_s:.0f} s.** "
            f"Every criterion above is a peak or a dose, evaluated over whatever trace "
            f"exists, so the shorter column is biased toward passing and the two are not "
            f"like for like.")


def render(test_result: Result, site_result: Result) -> str:
    test_name = _column(test_result)
    site_name = _column(site_result)
    lines = [
        f"# Correlation — {test_name} vs {site_name}",
        "",
        f"| criterion | {test_name} | status | {site_name} | status |",
        "|---|---|---|---|---|",
    ]
    for name in sorted(set(test_result.criteria) | set(site_result.criteria)):
        t = test_result.criteria.get(name)
        s = site_result.criteria.get(name)
        lines.append(
            f"| {labels.heading(name)} "
            f"| {labels.value(name, t.value) if t else '—'} | {t.status if t else '—'} "
            f"| {labels.value(name, s.value) if s else '—'} | {s.status if s else '—'} |"
        )
    note = coverage_note(test_result, site_result)
    if note:
        lines += ["", f"> {note}"]
    return "\n".join(lines)

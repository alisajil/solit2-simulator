"""Markdown correlation report: one design's criteria across two runs, side by
side -- typically the SOLIT2 test-facility geometry against the real site.
"""
from __future__ import annotations

from solit2.schema.result import Result


def _column(result: Result) -> str:
    """Design name AND engine.

    The comparison this report exists for is one design across two tiers, and
    naming only the design prints "og-dbr-rev0 vs og-dbr-rev0" -- a table whose
    two columns cannot be told apart.
    """
    return f"{result.meta['design_name']} ({result.meta.get('engine', 'unknown engine')})"


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
            f"| {name} | {t.value if t else '—'} | {t.status if t else '—'} | "
            f"{s.value if s else '—'} | {s.status if s else '—'} |"
        )
    return "\n".join(lines)

"""Markdown correlation report: one design's criteria across two runs, side by
side -- typically the SOLIT2 test-facility geometry against the real site.
"""
from __future__ import annotations

from solit2.schema.result import Result


def render(test_result: Result, site_result: Result) -> str:
    test_name = test_result.meta["design_name"]
    site_name = site_result.meta["design_name"]
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

"""Markdown test-plan report: a design's test inputs and its predicted outcomes.

SOLIT2 Annex 7 defines the acceptance criteria
(`solit2.engines.reduced.criteria`) but not a test-plan document format, so
this report's shape is read off the Design and Result contracts directly,
not transcribed from a spec section.
"""
from __future__ import annotations

from solit2.schema.design import Design
from solit2.schema.result import Criterion, Result


def _criteria_table(criteria: dict[str, Criterion]) -> str:
    lines = ["| criterion | value | limit | status | margin |", "|---|---|---|---|---|"]
    for name, c in criteria.items():
        limit = str(c.limit) if c.limit is not None else "—"
        lines.append(f"| {name} | {c.value} | {limit} | {c.status} | {c.margin:.3f} |")
    return "\n".join(lines)


def render(design: Design, result: Result) -> str:
    t, f, n, z, v, d = (design.tunnel, design.fire, design.nozzles,
                        design.zones, design.ventilation, design.detection)
    velocity = v.velocity_ms if v.velocity_ms is not None else v.velocity_range_ms
    score = result.score
    # "All gates passed" alone would overstate a design most of whose criteria nobody
    # has ruled on: CLAUDE.md forbids presenting `gates_passed` as approval while
    # `criteria_unset` is non-empty, and this line is read on its own in the report.
    unset = score["criteria_unset"]
    outcome = ("all gates passed" if score["gates_passed"]
              else "gates failed: " + ", ".join(score["gates_failed"]))
    if unset:
        outcome += (f" — but {len(unset)} of {len(result.criteria)} criteria were not judged, "
                    f"no limit having been set for them: " + ", ".join(unset))
    lines = [
        f"# Test Plan — {design.meta.name}",
        "",
        "## Test inputs",
        "",
        f"- **Tunnel**: {t.preset} ({t.section}, {t.shape}), length {t.length_m:.0f} m",
        f"- **Fire**: {f.preset}, Class {f.fire_class}, {f.design_hrr_mw:.0f} MW, "
        f"{f.growth} growth",
        f"- **Nozzles**: {n.preset}, {n.pressure_bar:.1f} bar",
        f"- **Zones**: {z.sections_simultaneous} section(s) x {z.section_length_m:.0f} m, "
        f"activation delay {z.activation_delay_s:.0f} s",
        f"- **Ventilation**: {velocity} m/s",
        f"- **Detection**: {d.type}, threshold {d.threshold_c:.0f} C, "
        f"spacing {d.sensor_spacing_m:.0f} m",
        "",
        "## Predicted outcomes",
        "",
        _criteria_table(result.criteria),
        "",
        f"**Score**: {score['total']:.2f} ({outcome})",
    ]
    return "\n".join(lines)

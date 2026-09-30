"""Markdown activation-timing comparison: one design started as declared and
started at a time the user supplies, side by side.

The report states consequences and never a preference. Which start suits a
tunnel is the authority's judgement; the late time itself is an input the tool
does not choose, because Annex 7 leaves activation conditions to the authority.
"""
from __future__ import annotations

from solit2.reports import labels
from solit2.schema.design import Design
from solit2.schema.result import Criterion, Result

AS_DESIGNED, LATE = "as_designed", "late"
LPM_TIMES_S_TO_M3 = 1.0 / 60.0 / 1000.0
STATUS_TEXT = {"pass": "met", "fail": "not met", "unset": "limit not set"}
STATUS_MARK = {"pass": "✓ met", "fail": "✗ not met", "unset": "limit not set"}
NOT_REACHED = "not reached"


def strategies(design: Design, late_s: float) -> dict[str, Design]:
    """The design as declared, and the same design with activation pinned at `late_s`."""
    run_s = design.zones.duration_min * 60.0
    if late_s <= 0:
        raise ValueError(f"the late activation time must be positive, got {late_s:g} s")
    if late_s > run_s:
        raise ValueError(f"the late activation time {late_s:g} s is after the end of the "
                         f"run ({run_s:.0f} s); the design runs {design.zones.duration_min:g} min")
    zones = design.zones.model_copy(update={"manual_activation_s": late_s})
    return {AS_DESIGNED: design, LATE: design.model_copy(update={"zones": zones})}


def water_volume_m3(result: Result) -> float:
    """Water discharged over the reported worst case, integrating its sampled flow."""
    t, q = result.timeseries["t_s"], result.timeseries["water_lpm"]
    return sum((t[i + 1] - t[i]) * (q[i] + q[i + 1]) / 2.0
               for i in range(len(t) - 1)) * LPM_TIMES_S_TO_M3


def _set_by(design: Design) -> str:
    pinned = design.zones.manual_activation_s
    if pinned is not None:
        return f"pinned at {pinned:.0f} s"
    return f"detection + {design.zones.activation_delay_s:.0f} s delay"


def _time(events: dict, key: str) -> str:
    t = events.get(key)
    return NOT_REACHED if t is None else f"{float(t):.0f} s"


def _delta(a: float | None, b: float | None, unit: str, places: int = 1) -> str:
    if a is None or b is None:
        return "—"
    return f"{b - a:+.{places}f} {unit}".rstrip()


def _limit_text(key: str, criterion: Criterion) -> str:
    limit = criterion.limit
    if limit is None:
        return "—"
    if isinstance(limit, tuple):
        return " – ".join(labels.value(key, v) for v in limit)
    return labels.value(key, limit)


def _timetable(designs: dict[str, Design], results: dict[str, Result]) -> list[str]:
    a, b = results[AS_DESIGNED].events, results[LATE].events
    rows = [("Activation set by", _set_by(designs[AS_DESIGNED]), _set_by(designs[LATE])),
            ("Detection", _time(a, "t_detect_s"), _time(b, "t_detect_s")),
            ("Activation", _time(a, "t_activate_s"), _time(b, "t_activate_s")),
            ("Full pressure", _time(a, "t_full_pressure_s"), _time(b, "t_full_pressure_s"))]
    return ["| | as designed | late |", "|---|---|---|"] + [
        f"| {name} | {x} | {y} |" for name, x, y in rows]


def _comparison(results: dict[str, Result]) -> list[str]:
    a, b = results[AS_DESIGNED], results[LATE]
    lines = ["| quantity | as designed | late | late − as designed |", "|---|---|---|---|"]
    for key in ("hrr_mw", "hrr_free_burn_mw", "ceiling_temp_c", "lining_temp_c"):
        lines.append(f"| {labels.label(key)} ({labels.unit(key)}) | "
                     f"{labels.value(key, a.peaks[key])} | {labels.value(key, b.peaks[key])} | "
                     f"{_delta(a.peaks[key], b.peaks[key], labels.unit(key))} |")
    back_a = a.events["backlayering"]["max_length_m"]
    back_b = b.events["backlayering"]["max_length_m"]
    lines.append(f"| Longest backlayering (m) | {back_a:.1f} | {back_b:.1f} | "
                 f"{_delta(back_a, back_b, 'm')} |")
    vol_a, vol_b = water_volume_m3(a), water_volume_m3(b)
    lines.append(f"| Water discharged, worst case (m³) | {vol_a:.1f} | {vol_b:.1f} | "
                 f"{_delta(vol_a, vol_b, 'm³')} |")
    return lines


def _criteria(results: dict[str, Result]) -> list[str]:
    a, b = results[AS_DESIGNED].criteria, results[LATE].criteria
    lines = ["| criterion | limit (from the design's own AHJ block) | as designed | result "
             "| late | result |", "|---|---|---|---|---|---|"]
    for key in sorted(a):
        ca, cb = a[key], b[key]
        lines.append(f"| {labels.label(key)} | {_limit_text(key, ca)} | "
                     f"{labels.with_unit(key, ca.value)} | {STATUS_MARK[ca.status]} | "
                     f"{labels.with_unit(key, cb.value)} | {STATUS_MARK[cb.status]} |")
    return lines


def _changes(results: dict[str, Result]) -> list[str]:
    a, b = results[AS_DESIGNED].criteria, results[LATE].criteria
    changed = [f"- {labels.label(key)}: {STATUS_TEXT[a[key].status]} as designed, "
               f"{STATUS_TEXT[b[key].status]} when started late"
               for key in sorted(a) if a[key].status != b[key].status]
    return changed or ["No criterion changes status."]


def render(late_s: float, designs: dict[str, Design], results: dict[str, Result]) -> str:
    base = results[AS_DESIGNED]
    lines = [f"# Activation timing — {base.meta['design_name']}", "",
             f"Design SHA: `{base.meta['design_sha']}`", "",
             f"Late activation time: {late_s:.0f} s, supplied by the user. "
             "The tool does not choose it."]
    t_activate = base.events.get("t_activate_s")
    if t_activate is not None and late_s <= t_activate:
        lines += ["", f"The supplied time is not later than the as-designed activation "
                      f"({t_activate:.0f} s); the two runs are the same or reversed."]
    lines += ["", "## Timetable", "", *_timetable(designs, results),
              "", "## Comparison", "",
              "Read from each run's reported worst case.", "", *_comparison(results),
              "", "## Criteria", "",
              "Each criterion takes its worst value across the whole velocity envelope, so a "
              "value here can come from a different case than the table above.", "",
              *_criteria(results),
              "", "## What changes", "", *_changes(results)]
    warnings = sorted({w for r in results.values() for w in r.warnings})
    lines += ["", "## Warnings", ""] + ([f"- {w}" for w in warnings] or ["None."])
    lines += ["", "---", "",
              "Prediction, not a measurement. "
              + str(base.meta.get("calibration_note", "")).strip()]
    return "\n".join(lines) + "\n"

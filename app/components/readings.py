"""What the simulator's gauges and tiles read -- every value the engine's own.

Four gauges are the quantities Annex 7 section 7.2 judges, read exactly the way
`solit2.engines.reduced.criteria` reads them: the worst value, at one instant,
over the Table 5 stations that carry that instrument and no others. That is what
lets a gauge's red band be the criterion's own limit and nothing else. The other
two gauges (air velocity, water flow) have no Annex 7 limit, so they never get one.

No Streamlit import: the figure builders and their tests use this directly.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass

from solit2.engines.reduced.criteria import (
    HEAT_FLUX_STATIONS, THERMOCOUPLE_STATIONS, VISIBILITY_STATIONS,
)
from solit2.engines.reduced.state import RunTrace, StepRecord
from solit2.schema.presets import calibration_hash
from solit2.schema.result import Result

# The dial ends 10 % above the larger of the run's own peak and the limit, so the
# needle never pins and a limit is never drawn off the dial.
RANGE_HEADROOM = 1.1


@dataclass(frozen=True)
class Gauge:
    key: str
    label: str
    unit: str
    criterion: str | None         # the criterion whose `ahj` limit bands this gauge


GAUGES: tuple[Gauge, ...] = (
    Gauge("hrr_mw", "Heat release", "MW", "hrr_below_tvs_design_mw"),
    Gauge("air_temp_c", "Air temperature", "°C", "max_air_temp_c"),
    Gauge("heat_flux_kwm2", "Heat flux", "kW/m²", "max_heat_flux_kwm2"),
    Gauge("visibility_m", "Visibility", "m", "min_visibility_m"),
    Gauge("air_velocity_ms", "Air velocity", "m/s", None),
    Gauge("water_lpm", "Water flow", "L/min", None),
)


@dataclass(frozen=True)
class Band:
    """A gauge's limit, exactly as its criterion declared it -- the comparison
    together with the value, never just the value alone. `live_figure._gauge`
    reads `op` to decide which side of `limit` is the red zone; a hard-coded
    per-gauge direction (the old `lower_is_worse` flag) would draw the wrong
    side the moment a design overrides a criterion's `op` (`design.criteria`
    lets it, e.g. to `"in"`, a two-sided `(lo, hi)` limit)."""
    op: str
    limit: float | tuple[float, float]

    @property
    def edge(self) -> float:
        """The furthest value a gauge's axis must reach to keep this band on-dial."""
        return max(self.limit) if isinstance(self.limit, tuple) else float(self.limit)


_READERS: dict[str, Callable[[StepRecord], float]] = {
    "hrr_mw": lambda s: s.hrr_mw,
    "air_temp_c": lambda s: max(s.stations[n].temp_c for n in THERMOCOUPLE_STATIONS),
    "heat_flux_kwm2": lambda s: max(s.stations[n].flux_kwm2 for n in HEAT_FLUX_STATIONS),
    "visibility_m": lambda s: min(s.stations[n].visibility_m for n in VISIBILITY_STATIONS),
    "air_velocity_ms": lambda s: s.u_eff_ms,
    "water_lpm": lambda s: s.water_lpm,
}


def reading(step: StepRecord, key: str) -> float:
    """One gauge's value at one instant."""
    reader = _READERS.get(key)
    if reader is None:
        raise ValueError(f"unknown gauge {key!r}; expected one of {', '.join(_READERS)}")
    return float(reader(step))


def limit(result: Result, gauge: Gauge) -> Band | None:
    """This gauge's criterion, as a `Band` (its own comparison and limit), or
    `None` where nobody set a limit -- never a bare number: a bare `float()` on a
    two-sided `(lo, hi)` limit raises, and dropping `op` is what let the gauge
    band assume every criterion reads the same way `<=` does."""
    if gauge.criterion is None:
        return None
    criterion = result.criteria.get(gauge.criterion)
    if criterion is None or criterion.limit is None:
        return None
    return Band(criterion.op, criterion.limit)


def axis_max(trace: RunTrace, gauge: Gauge, limit_value: Band | float | None) -> float:
    peak = max(reading(s, gauge.key) for s in trace.steps)
    edge = limit_value.edge if isinstance(limit_value, Band) else limit_value
    top = max(peak, edge if edge is not None else 0.0) * RANGE_HEADROOM
    return top if top > 0 else 1.0


@dataclass(frozen=True)
class Tile:
    label: str
    value: str
    note: str


def criteria_set(result: Result) -> tuple[int, int]:
    """How many of the Annex 7 criteria have a limit to be judged against, of how many."""
    total = len(result.criteria)
    return total - len(result.score.get("criteria_unset", [])), total


def tiles(result: Result) -> tuple[Tile, ...]:
    peaks, events, score = result.peaks, result.events, result.score
    n_set, total = criteria_set(result)
    full = events.get("t_full_pressure_s")
    ignited = bool(result.criteria["target_ignited"].value)
    failed = list(score.get("gates_failed") or [])
    # The count is never dropped in favour of the gate failure: a design can fail
    # a gate for reasons that have nothing to do with how many criteria are set
    # (`target_ignited` needs no AHJ limit at all), so hiding the count exactly
    # when a gate fails is the one time a reader most needs to see it (M-1).
    note = f"{n_set} of {total} criteria set"
    if failed:
        note += " · gates failed: " + ", ".join(failed)
    return (
        Tile("Peak heat release", f"{peaks['hrr_mw']:.1f} MW",
             f"free burn {peaks['hrr_free_burn_mw']:.1f} MW"),
        Tile("Peak ceiling gas", f"{peaks['ceiling_temp_c']:.0f} °C", "under the ceiling"),
        Tile("Target", "ignited" if ignited else "not ignited", "Annex 7 §7.2.1"),
        Tile("Full pressure", f"{full:.0f} s" if full is not None else "never reached",
             "after ignition"),
        Tile("Score", f"{score['total']:.1f}", note),
    )


_EVENT_LABELS = (("t_detect_s", "detect"), ("t_activate_s", "activate"),
                 ("t_full_pressure_s", "full pressure"), ("t_peak_hrr_s", "peak HRR"))


def diagnostics(result: Result) -> str:
    """The run's events, what is judged, which case plays, and the calibration."""
    events = result.events
    parts = [f"{label} {events[key]:.0f} s" if events.get(key) is not None else f"{label} —"
             for key, label in _EVENT_LABELS]
    back = events.get("backlayering") or {}
    if back.get("occurred"):
        cleared = back.get("cleared_at_s")
        parts.append(f"backlayering {back['max_length_m']:.0f} m"
                     + (f", cleared {cleared:.0f} s" if cleared is not None else ", not cleared"))
    n_set, total = criteria_set(result)
    parts.append(f"criteria set {n_set}/{total}")
    case = result.worst_case
    parts.append(f"playback: worst case, {case['section']} section at "
                 f"{case['velocity_ms']:.2f} m/s")
    parts.append(f"calibration {calibration_hash()}")
    return " · ".join(parts)


def _limit_text(band: Band, unit: str) -> str:
    if isinstance(band.limit, tuple):
        lo, hi = band.limit
        return f"limit {lo:.1f}-{hi:.1f} {unit}"
    return f"limit {band.limit:.1f} {unit}"


def judged_elsewhere(result: Result) -> tuple[str, ...]:
    """One line per gauge whose criterion was judged on a case other than the one
    the figure replays (`result.worst_case`) -- empty when every gauge's criterion
    was judged on the replayed case.

    I-1: the envelope takes each criterion from its own worst case across every
    section/velocity combination (`envelope._worst_per_id`), but the figure only
    ever replays `result.worst_case`, the run with the thinnest hard margin. A
    gauge can sit comfortably inside its band for the whole animation while the
    criterion it stands for actually failed on a case nobody sees play out.
    """
    worst = result.worst_case
    lines = []
    for gauge in GAUGES:
        if gauge.criterion is None:
            continue
        case = result.criteria_cases.get(gauge.criterion)
        if case is None or case == worst:
            continue
        criterion = result.criteria[gauge.criterion]
        limit_text = "limit not set" if criterion.limit is None else _limit_text(
            Band(criterion.op, criterion.limit), gauge.unit)
        lines.append(
            f"{gauge.label} was judged on the {case['section']} section at "
            f"{case['velocity_ms']:.2f} m/s: {criterion.value:.1f} {gauge.unit} "
            f"({limit_text}, {criterion.status}). The figure replays the worst "
            f"case ({worst['section']} section at {worst['velocity_ms']:.2f} m/s).")
    return tuple(lines)

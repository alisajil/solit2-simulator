"""Everything a rule may read, and the few quantities several rules share."""
from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from solit2.compliance.spec import Facts
from solit2.engines.reduced.criteria import FLAME_CONTACT_FLUX_KWM2, IGNITION_EXPOSURE_S
from solit2.schema.design import Design
from solit2.schema.result import Result


@dataclass(frozen=True)
class Context:
    tests: Mapping[str, Design]            # by fire class, "A" always present
    test_results: Mapping[str, Result]
    installation: Design
    installation_result: Result
    facts: Facts
    protocol_text: Mapping[str, str]       # the rendered Annex 7 §8.2 protocol, by class


def hrr_at_mw(result: Result, t_s: float) -> float:
    """HRR at `t_s`, linearly interpolated on the result's sampled series."""
    ts, hrr = result.timeseries["t_s"], result.timeseries["hrr_mw"]
    if t_s <= ts[0]:
        return hrr[0]
    for (t0, h0), (t1, h1) in zip(zip(ts, hrr), zip(ts[1:], hrr[1:])):
        if t0 <= t_s <= t1:
            return h0 + (h1 - h0) * (t_s - t0) / (t1 - t0)
    return hrr[-1]


def time_to_full_operation_s(result: Result) -> float:
    """Detection to full pressure: Annex 3 §3.3's 'time to full operation'."""
    return result.events["t_full_pressure_s"] - result.events["t_detect_s"]


def standoff_m(design: Design) -> float:
    """Nozzle to top of the fire load, the distance main document §3.6.2 bounds."""
    return design.nozzles.mounting.height_above_carriageway_m - design.fire.footprint.top_height_m


def target_ignited(result: Result) -> bool:
    peaks = result.peaks
    return bool(peaks["target_peak_flux_kwm2"] >= FLAME_CONTACT_FLUX_KWM2
                or peaks["target_max_exposure_s"] >= IGNITION_EXPOSURE_S)


def tested_velocities_ms(ctx: Context, fire_class: str) -> tuple[list[float], str]:
    """The velocities the test programme runs this class at, and where that came from.

    A design's `velocity_range_ms` defaults to (3.88, 5.08) -- an installation
    figure, not a test condition -- when the field is left unset, so that
    default may never stand in as "what this test ran at". Only a design that
    DECLARES the field, or a `planned_tests` fact, counts as evidence of the
    velocities actually tested.
    """
    planned = ctx.facts.planned_tests
    if planned is not None:
        values = [t.velocity_ms for t in planned.value if t.fire_class == fire_class]
        if values:
            return values, f"planned tests ({planned.evidence.cite()})"
    design = ctx.tests.get(fire_class)
    if design is not None and "velocity_range_ms" in design.ventilation.model_fields_set:
        return list(design.ventilation.velocity_range_ms), "the test design's velocity range"
    return [], "no tested velocity declared"

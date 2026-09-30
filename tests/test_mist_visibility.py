"""Droplet extinction for visibility: derived from the water in the zone, not from
the radiant transmissivity of a curtain built for a different path."""
import dataclasses
import functools
import math

import pytest

from solit2.engines.reduced import envelope, sim, tenability
from solit2.engines.reduced.criteria import STATIONS
from solit2.engines.reduced.state import MistEffect, RunTrace
from solit2.schema.design import Design

BASELINE = "examples/designs/road-tunnel-twin-bore.json"
# Radiant extinction uses prefactor 1.5 (Q = 1); visible light through drops much larger
# than its wavelength has Q_ext = 2, i.e. prefactor 3.0.
VISIBLE_TO_RADIANT = 2.0
CURTAIN_PATH_FRACTION = 0.5


@functools.lru_cache(maxsize=1)
def _run():
    design = Design.load(BASELINE)
    result = envelope.run(design)
    trace = sim.run_once(design, result.worst_case["section"], result.worst_case["velocity_ms"])
    return design, result, trace


def _active(trace):
    return [s for s in trace.steps if s.mist.tau_mist < 1.0]


def test_no_mist_means_no_visible_extinction():
    assert MistEffect.none().kappa_visible_per_m == 0.0


def test_before_the_system_discharges_there_is_no_extinction():
    _, _, trace = _run()
    idle = [s for s in trace.steps if s.mist.tau_mist == 1.0]
    assert idle
    assert all(s.mist.kappa_visible_per_m == 0.0 for s in idle)


def test_visible_extinction_is_twice_the_radiant_extinction_of_the_same_water():
    design, _, trace = _run()
    steps = _active(trace)
    assert steps
    path_m = design.active_length_m * CURTAIN_PATH_FRACTION
    for step in steps:
        kappa_radiant = -math.log(step.mist.tau_mist) / path_m
        assert step.mist.kappa_visible_per_m == pytest.approx(
            VISIBLE_TO_RADIANT * kappa_radiant, rel=1e-9)


def test_the_old_linear_derivation_is_gone():
    design, _, trace = _run()
    step = min(_active(trace), key=lambda s: s.mist.tau_mist)   # the thickest curtain
    old = (1.0 - step.mist.tau_mist) / (design.active_length_m / 2.0)
    assert step.mist.kappa_visible_per_m > old


def test_a_thicker_curtain_never_has_less_extinction():
    _, _, trace = _run()
    pairs = sorted((s.mist.tau_mist, s.mist.kappa_visible_per_m) for s in _active(trace))
    kappas = [k for _, k in reversed(pairs)]      # tau falling -> thicker
    assert all(b >= a - 1e-12 for a, b in zip(kappas, kappas[1:]))


def test_droplets_alone_bound_the_visibility_inside_the_spray_zone():
    design, _, trace = _run()
    half = design.active_length_m / 2.0
    checked = 0
    for step in _active(trace):
        for name, sample in step.stations.items():
            if sample.visibility_m is None or step.mist.kappa_visible_per_m <= 0:
                continue
            if abs(STATIONS[name]) > half:
                continue
            ceiling = tenability.JIN_LIGHT_EMITTING / step.mist.kappa_visible_per_m
            assert sample.visibility_m <= min(ceiling, tenability.MAX_REPORTED_VISIBILITY_M) + 1e-9
            checked += 1
    assert checked > 0


def _with_spray(step, kappa, strat):
    return dataclasses.replace(
        step, strat_factor=strat,
        mist=dataclasses.replace(step.mist, kappa_visible_per_m=kappa))


def _trace_of(steps):
    return RunTrace(tuple(steps), {}, "test", 1.0)


WHOLE_TUNNEL_HALF_M = 10_000.0   # every station is inside a zone this long
NO_STATION_HALF_M = 1.0          # no Annex 7 station is within a metre of the fire


def test_a_stratified_run_with_a_station_in_the_spray_zone_warns():
    _, _, trace = _run()
    trace1 = _trace_of([_with_spray(trace.steps[0], 0.05, 0.1)])
    warnings = envelope._destratification_warnings(trace1, WHOLE_TUNNEL_HALF_M)
    assert len(warnings) == 1
    assert "de-stratification is not modelled" in warnings[0]
    assert "worse than reported" in warnings[0]


def test_no_warning_when_no_reported_station_is_inside_the_zone():
    _, _, trace = _run()
    trace1 = _trace_of([_with_spray(trace.steps[0], 0.05, 0.1)])
    assert envelope._destratification_warnings(trace1, NO_STATION_HALF_M) == []


def test_no_warning_when_the_spray_never_discharges_or_the_layer_is_mixed():
    _, _, trace = _run()
    step = trace.steps[0]
    idle = _trace_of([_with_spray(step, 0.0, 0.1)])
    mixed = _trace_of([_with_spray(step, 0.05, 1.0)])
    assert envelope._destratification_warnings(idle, WHOLE_TUNNEL_HALF_M) == []
    assert envelope._destratification_warnings(mixed, WHOLE_TUNNEL_HALF_M) == []


def test_the_warning_reaches_the_result_only_when_a_station_is_in_the_zone():
    design, result, trace = _run()
    half = design.active_length_m / 2.0
    expected = bool(envelope._destratification_warnings(trace, half))
    matching = [w for w in result.warnings if "de-stratification is not modelled" in w]
    assert len(matching) == (1 if expected else 0)


def test_a_zone_long_enough_to_reach_a_visibility_station_is_dimmed_by_the_droplets():
    """The change bites only where the zone reaches an instrumented station."""
    design, _, _ = _run()
    long_zone = design.model_copy(update={"zones": design.zones.model_copy(
        update={"section_length_m": 100.0})})
    result = envelope.run(long_zone)
    trace = sim.run_once(long_zone, result.worst_case["section"],
                         result.worst_case["velocity_ms"])
    half = long_zone.active_length_m / 2.0
    dimmed = [
        (s.stations[n].visibility_m, tenability.JIN_LIGHT_EMITTING / s.mist.kappa_visible_per_m)
        for s in _active(trace) if s.mist.kappa_visible_per_m > 0
        for n in s.stations if s.stations[n].visibility_m is not None
        and abs(STATIONS[n]) <= half]
    assert dimmed, "a 100 m section should put a visibility station inside the zone"
    assert all(vis <= ceiling + 1e-9 for vis, ceiling in dimmed)

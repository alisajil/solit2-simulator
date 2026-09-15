import copy

import pytest
from solit2.schema.design import Design
from solit2.schema.presets import load_calibration
from solit2.engines.reduced.geometry import section_geometry, nozzle_positions
from solit2.engines.reduced import mist

BASELINE = "examples/designs/road-tunnel-twin-bore.json"
FIRE_TOP_M = 4.0
Q_CONV_KW = 50_000 * 0.65

# What the previous top-face-only delivery model reported for the SOLIT2
# reference geometry (c4: nozzles 0.9 m above a 4.0 m fuel top, 2.25 m/s, cold
# gas so evaporation plays no part). Measured on the model as it stood at commit
# 7ec4066, before the interception envelope replaced the single-plane halo.
# Pinned here so the structural change has something concrete to be judged
# against rather than an assertion that only says "bigger than zero".
OLD_TOP_PLANE_W_FUEL_MM_MIN = 1.639

# The brief's starting estimates for the two new constants. The envelope tests
# pin them rather than reading the live calibration, because they are about the
# SHAPE of the delivery model and must keep their meaning after a fit has moved
# the values.
REFERENCE_FLANK_REACH_FACTOR = 0.5
REFERENCE_FLANK_EFFICIENCY = 0.4


def _pin_mist_calibration(monkeypatch, **overrides):
    """Fix named `mist` constants for one test, leaving the real file alone."""
    cal = copy.deepcopy(load_calibration())
    for key, value in overrides.items():
        cal["mist"][key]["value"] = value
    monkeypatch.setattr(mist, "load_calibration", lambda: cal)


def _envelope(design, geom, reach_m=None):
    fire_y = design.fire.lane_centre_offset_from_wall_m - geom.road_width_m / 2.0
    if reach_m is None:
        reach_m = mist.flank_reach_m(design.fire.footprint.top_height_m)
    return mist.fuel_envelope(0.0, fire_y, design.fire.footprint.length_m,
                              design.fire.footprint.width_m, reach_m)


def _setup(design=None, u_ms=5.0, gas_excess_k=0.0, flow_fraction=1.0, reach_m=None,
           fire_top_m=FIRE_TOP_M):
    d = design or Design.load(BASELINE)
    geom = section_geometry(d)
    pos = nozzle_positions(d, geom, fire_x_m=0.0)
    env = _envelope(d, geom, reach_m)
    effect = mist.evaluate(d, geom, pos, env, fire_top_m, u_ms, gas_excess_k,
                           Q_CONV_KW, flow_fraction)
    return d, geom, pos, env, effect


def _solit2_reference_design():
    """The c4 anchor's design: the short-throw, tall-fuel geometry that exposed
    the flat-plate defect. Read from the anchor so the test cannot drift from
    the reference case it is named for."""
    from validation import compare

    return compare.load_anchors(("c4",))[0].design


# --- the interception envelope ----------------------------------------------

def test_the_envelope_is_the_footprint_plus_a_height_scaled_flank_band():
    d = Design.load(BASELINE)
    geom = section_geometry(d)
    env = _envelope(d, geom, reach_m=2.0)

    assert env.top.x1_m - env.top.x0_m == pytest.approx(8.4)
    assert env.top.y1_m - env.top.y0_m == pytest.approx(2.4)
    assert env.top.area_m2 == pytest.approx(20.16, rel=0.01)

    assert env.outer.x1_m - env.outer.x0_m == pytest.approx(12.4)
    assert env.outer.y1_m - env.outer.y0_m == pytest.approx(6.4)
    assert env.flank_area_m2 == pytest.approx(79.36 - 20.16, rel=0.01)


def test_the_flank_reach_scales_with_the_fuel_height():
    factor = load_calibration()["mist"]["flank_reach_factor"]["value"]
    assert mist.flank_reach_m(4.0) == pytest.approx(4.0 * factor)
    assert mist.flank_reach_m(8.0) == pytest.approx(2.0 * mist.flank_reach_m(4.0))


def test_a_tall_fuel_at_a_short_throw_intercepts_far_more_than_the_top_face_alone(monkeypatch):
    """Test 1. The SOLIT2 geometry: a 4.0 m stack with the nozzles 0.9 m above
    it. Projecting the cones onto the fuel's top plane saw almost nothing; the
    real stack stands in the spray and takes it on its flanks as well."""
    _pin_mist_calibration(monkeypatch,
                          flank_reach_factor=REFERENCE_FLANK_REACH_FACTOR,
                          flank_efficiency=REFERENCE_FLANK_EFFICIENCY)
    d = _solit2_reference_design()
    _, _, _, _, effect = _setup(d, u_ms=2.25, gas_excess_k=0.0)

    assert effect.w_fuel_mm_min > 0.0
    assert effect.w_fuel_mm_min > 2.0 * OLD_TOP_PLANE_W_FUEL_MM_MIN


def test_zero_flank_efficiency_reduces_to_top_face_only_delivery(monkeypatch):
    """Test 2. The old behaviour is the new model's flank_efficiency -> 0 limit."""
    d = _solit2_reference_design()

    _pin_mist_calibration(monkeypatch, flank_efficiency=0.0)
    _, _, pos, env, none_credited = _setup(d, u_ms=2.25)

    deliveries = mist.mode_deliveries(d, pos, env, FIRE_TOP_M, 2.25, 0.0, 1.0)
    top_only = sum(m.flow_to_top_lpm for m in deliveries) / env.top.area_m2

    assert none_credited.w_fuel_mm_min == pytest.approx(top_only)
    assert any(m.flow_to_flank_lpm > 0.0 for m in deliveries), (
        "the flank band must still be measured, only credited at zero")


def test_a_wider_flank_band_delivers_monotonically_more(monkeypatch):
    """Test 3. A taller stack reaches further into the falling spray."""
    _pin_mist_calibration(monkeypatch, flank_efficiency=REFERENCE_FLANK_EFFICIENCY)
    d = _solit2_reference_design()
    fluxes = [_setup(d, u_ms=2.25, reach_m=reach)[4].w_fuel_mm_min
              for reach in (0.5, 1.0, 2.0, 3.0)]
    assert fluxes == sorted(fluxes)
    assert fluxes[0] < fluxes[-1]


def test_a_tall_fuel_intercepts_more_water_than_a_short_one(monkeypatch):
    """Test 4. Same nozzles, same flow, same application density: the taller
    stack presents a bigger interception envelope and catches more of it."""
    _pin_mist_calibration(monkeypatch,
                          flank_reach_factor=REFERENCE_FLANK_REACH_FACTOR,
                          flank_efficiency=REFERENCE_FLANK_EFFICIENCY)
    d = _solit2_reference_design()
    geom = section_geometry(d)
    pos = nozzle_positions(d, geom, fire_x_m=0.0)
    efficiency = REFERENCE_FLANK_EFFICIENCY

    def intercepted_lpm(top_height_m):
        env = _envelope(d, geom, mist.flank_reach_m(top_height_m))
        got = mist.mode_deliveries(d, pos, env, top_height_m, 2.25, 0.0, 1.0)
        return sum(m.flow_to_top_lpm + efficiency * m.flow_to_flank_lpm for m in got)

    assert intercepted_lpm(4.0) > intercepted_lpm(1.5)


# --- ruling R4: the geometry cache ------------------------------------------

def test_the_geometry_cache_serves_repeats_and_still_separates_two_designs():
    """Test 5. The expensive half is computed once per distinct flight condition
    and keyed on the design's own spray geometry, so raising the mounting height
    must miss the entry the lower design put there."""
    d, geom, pos, env, _ = _setup()

    first = mist._geometry(d, pos, env, FIRE_TOP_M, 5.0, 0.0)
    again = mist._geometry(d, pos, env, FIRE_TOP_M, 5.0, 0.0)
    assert again is first, "an identical flight condition must be served from the cache"

    mount = d.nozzles.mounting
    raised = d.model_copy(update={"nozzles": d.nozzles.model_copy(update={
        "mounting": mount.model_copy(update={
            "height_above_carriageway_m": mount.height_above_carriageway_m + 0.5})})})
    raised_pos = nozzle_positions(raised, geom, fire_x_m=0.0)
    other = mist._geometry(raised, raised_pos, env, FIRE_TOP_M, 5.0, 0.0)

    assert other is not first
    assert other[0].footprint_radius_m > first[0].footprint_radius_m


# --- behaviour carried over from the top-plane model ------------------------

def test_no_flow_means_no_effect():
    _, _, _, _, effect = _setup(flow_fraction=0.0)
    assert effect.eta == 0.0
    assert effect.w_fuel_mm_min == 0.0
    assert effect.tau_mist == 1.0


def test_baseline_delivers_useful_flux_to_the_fuel(monkeypatch):
    _pin_mist_calibration(monkeypatch,
                          flank_reach_factor=REFERENCE_FLANK_REACH_FACTOR,
                          flank_efficiency=REFERENCE_FLANK_EFFICIENCY)
    _, _, _, _, effect = _setup()
    eta_ceiling = load_calibration()["mist"]["eta_max"]["value"]
    assert 1.5 < effect.w_fuel_mm_min < 20.0
    assert 0.0 < effect.f_cov <= 1.0
    # eta's own bounds are fitted constants, so assert the shape, not a value.
    assert 0.0 < effect.eta < eta_ceiling


def test_fine_mode_is_carried_onto_the_fire_from_upstream_heads():
    # the fine mode's whole point: released far upstream, it arrives over the fire
    d, _, pos, env, _ = _setup()
    deliveries = {m.mode_id: m for m in mist.mode_deliveries(
        d, pos, env, FIRE_TOP_M, 5.0, 0.0, 1.0)}
    assert deliveries["fine"].drift_m > 10.0
    assert deliveries["coarse"].drift_m < 3.0
    assert deliveries["fine"].flow_to_fuel_lpm > 0.0


def test_coarse_mode_carries_the_suppression_when_the_fine_mode_evaporates():
    _, _, _, _, cool = _setup(gas_excess_k=0.0)
    _, _, _, _, hot = _setup(gas_excess_k=700.0)
    assert hot.w_fuel_mm_min < cool.w_fuel_mm_min
    assert hot.w_fuel_mm_min > 0.0      # the coarse core still gets through
    assert hot.chi_cool > cool.chi_cool  # evaporation is what cools the gas


def test_mist_curtain_attenuates_radiation():
    _, _, _, _, effect = _setup()
    assert 0.0 < effect.tau_mist < 1.0


def test_tighter_pitch_raises_the_flux_on_the_fuel():
    d = Design.load(BASELINE)
    tight = d.model_copy(update={"nozzles": d.nozzles.model_copy(
        update={"mounting": d.nozzles.mounting.model_copy(update={"pitch_m": 1.6})})})
    _, _, _, _, base = _setup()
    _, _, _, _, dense = _setup(tight)
    assert dense.w_fuel_mm_min > base.w_fuel_mm_min


def test_all_fine_split_loses_fuel_wetting_at_tunnel_velocity():
    d = Design.load(BASELINE)
    fine_only = d.model_copy(update={"nozzles": d.nozzles.model_copy(update={
        "modes": (d.nozzles.modes[0].model_copy(update={"fraction": 1.0}),)})})
    _, _, _, _, base = _setup()
    _, _, _, _, fine = _setup(fine_only, gas_excess_k=700.0)
    assert fine.w_fuel_mm_min < base.w_fuel_mm_min


def test_cooling_fraction_is_capped():
    cap = load_calibration()["mist"]["chi_cool_max"]["value"]
    _, _, _, _, effect = _setup(gas_excess_k=900.0)
    assert effect.chi_cool <= cap + 1e-9

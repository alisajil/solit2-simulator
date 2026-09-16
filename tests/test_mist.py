import copy
import json

import pytest
from solit2.schema.design import Design
from solit2.schema.presets import PRESET_DIR, load_calibration, reload_calibration
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

# The geometry cache's hit rate over one full three-anchor `compare.residuals`
# call, measured in Task 16 before spray-core shielding was added. Ruling R4's
# 177x speed-up rests on this staying where it is.
TASK_16_CACHE_HIT_RATE_PCT = 98.54


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

    # the Annex 7 section 5.2.2 mock-up: 10,0 m long by 2,4 m wide
    assert env.top.x1_m - env.top.x0_m == pytest.approx(10.0)
    assert env.top.y1_m - env.top.y0_m == pytest.approx(2.4)
    assert env.top.area_m2 == pytest.approx(24.0, rel=0.01)

    # and the band, 2.0 m of reach added on all four sides
    assert env.outer.x1_m - env.outer.x0_m == pytest.approx(14.0)
    assert env.outer.y1_m - env.outer.y0_m == pytest.approx(6.4)
    assert env.flank_area_m2 == pytest.approx(89.6 - 24.0, rel=0.01)


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


# --- task 17b: the geometry cache's two blind spots -------------------------
#
# `_compute_geometry` calls `spray_shielding_factor`, which reads
# `shielding_reference_loading_kgm3` from calibration INTERNALLY -- a value
# `_geometry_key` never sees, because it never passes through its own
# arguments. These tests mutate the real calibration.json and call the real
# `reload_calibration()`, because the bug is specifically about whether that
# one chokepoint actually busts `_GEOMETRY_CACHE`: monkeypatching
# `load_calibration` in memory, as `_pin_mist_calibration` does elsewhere in
# this file, would bypass the exact code path being tested.

CALIBRATION_PATH = PRESET_DIR / "calibration.json"

# Bucket-aligned (a multiple of `GAS_EXCESS_BUCKET_K`) so `_geometry`'s own R4
# quantisation cannot silently move it. The COARSE mode (index 1 of a design
# loaded from BASELINE) is used throughout: it is evaporation-resistant enough
# -- see `test_coarse_core_survives_the_same_hot_gas` in test_droplet.py --
# that the whole shielding sweep below stays in a smooth, monotonic regime
# instead of every point collapsing onto the FULLY_EVAPORATED_UM floor, which
# would hide a stale cache behind discretisation noise instead of a clean
# signal.
SHIELDING_CACHE_GAS_EXCESS_K = 900.0
COARSE_MODE_INDEX = 1

# Spans the shield factor from ~0.11 to ~0.93 at the coarse mode's own flow
# (measured directly against droplet.spray_shielding_factor before writing
# this sweep), giving surviving_fraction values that are cleanly separated
# rather than merely different in the last decimal place.
SHIELDING_SWEEP_KGM3 = (0.005, 0.02, 0.05, 0.2, 1.0)
# flank_efficiency never reaches `_compute_geometry` at all -- it only scales
# the cheap per-call flank credit in `_effective_flux_mm_min` -- so moving it
# between shielding points is a pure probe of whether reloading calibration
# for ANY reason still busts the geometry cache, exactly as a fit's
# finite-difference Jacobian does when it steps through the other eleven
# fitted constants between shielding steps.
SHIELDING_SWEEP_SECOND_CONSTANT = (0.10, 0.40, 0.70)


@pytest.fixture
def real_calibration_file():
    """Restore calibration.json and both process-wide caches afterward, so a
    test that writes the real file cannot leak into any other test."""
    original = CALIBRATION_PATH.read_text()
    try:
        yield
    finally:
        CALIBRATION_PATH.write_text(original)
        reload_calibration()
        mist._GEOMETRY_CACHE.clear()


def _write_mist_constants(**overrides) -> None:
    """Write named `mist` calibration constants to the real file and reload --
    the same write-then-reload sequence `validation.fit.apply_vector` uses."""
    cal = json.loads(CALIBRATION_PATH.read_text())
    for name, value in overrides.items():
        cal["mist"][name]["value"] = value
    CALIBRATION_PATH.write_text(json.dumps(cal))
    reload_calibration()


def _coarse_survival(design, positions, envelope) -> float:
    geometry = mist._geometry(design, positions, envelope, FIRE_TOP_M, 5.0,
                              SHIELDING_CACHE_GAS_EXCESS_K)
    return geometry[COARSE_MODE_INDEX].surviving_fraction


def test_reloading_calibration_busts_the_geometry_cache_too(real_calibration_file):
    """Task 17b bug 1, direct proof. Two calls for the same design and flight
    condition, with only `shielding_reference_loading_kgm3` changed between
    them via a real write plus `reload_calibration()`, must give different
    results -- proving the second call is not silently served a trajectory
    computed under the first value."""
    d, geom, pos, env, _ = _setup()
    mist._GEOMETRY_CACHE.clear()

    _write_mist_constants(shielding_reference_loading_kgm3=0.005)
    low_ref = _coarse_survival(d, pos, env)

    _write_mist_constants(shielding_reference_loading_kgm3=1.0)
    high_ref = _coarse_survival(d, pos, env)

    assert low_ref != high_ref, (
        "the second call was served a trajectory computed under the FIRST "
        "shielding_reference_loading_kgm3, not the value just reloaded"
    )


def test_a_shielding_sweep_agrees_with_a_grid_that_also_moves_another_constant(
        real_calibration_file):
    """Task 17b bug 1, second angle -- the test that would have caught the
    discarded fit's problem directly. A one-dimensional sweep of
    `shielding_reference_loading_kgm3` alone, and a two-dimensional grid that
    also moves `flank_efficiency` and visits the same shielding values in a
    different order, must agree at every shielding value they share: the
    geometry has to depend on the shielding value currently in the file, never
    on what else was set in between or on which sweep got there first."""
    d, geom, pos, env, _ = _setup()

    mist._GEOMETRY_CACHE.clear()
    sweep = {}
    for ref in SHIELDING_SWEEP_KGM3:
        _write_mist_constants(shielding_reference_loading_kgm3=ref)
        sweep[ref] = _coarse_survival(d, pos, env)

    mist._GEOMETRY_CACHE.clear()
    grid = {}
    for efficiency in SHIELDING_SWEEP_SECOND_CONSTANT:
        for ref in reversed(SHIELDING_SWEEP_KGM3):
            _write_mist_constants(shielding_reference_loading_kgm3=ref,
                                  flank_efficiency=efficiency)
            grid[(efficiency, ref)] = _coarse_survival(d, pos, env)

    for (efficiency, ref), grid_value in grid.items():
        assert grid_value == pytest.approx(sweep[ref]), (
            f"shielding_reference_loading_kgm3={ref}: the 1D sweep saw "
            f"{sweep[ref]:.6f}, the grid (flank_efficiency={efficiency} also "
            f"moving) saw {grid_value:.6f} for the same shielding value -- the "
            f"geometry cache served a trajectory computed under a different one"
        )


def test_two_designs_that_differ_only_in_flow_get_different_cached_geometry():
    """Task 17b bug 2. `_geometry_key`'s `modes` tuple carried droplet size,
    cone angle and launch velocity but not `mode_flow_lpm`, so two designs
    sharing every other spray-geometry input -- differing only in K-factor or
    pressure -- could silently share one cache entry and read back a shield
    factor computed for the wrong flow rate. This test does not touch
    calibration at all; it fits entirely within the default `real` file."""
    mist._GEOMETRY_CACHE.clear()
    d = Design.load(BASELINE)
    geom = section_geometry(d)
    pos = nozzle_positions(d, geom, fire_x_m=0.0)
    env = _envelope(d, geom)

    doubled_flow = d.model_copy(update={"nozzles": d.nozzles.model_copy(
        update={"k_factor_lpm_bar05": d.nozzles.k_factor_lpm_bar05 * 2.0})})
    doubled_pos = nozzle_positions(doubled_flow, geom, fire_x_m=0.0)

    # Every OTHER spray-geometry input is unchanged: pressure (hence smd_um),
    # cone angle, launch velocity, mounting and nozzle positions all agree --
    # only the flow K-factor was touched.
    assert doubled_flow.nozzles.modes == d.nozzles.modes
    assert doubled_flow.nozzles.mounting == d.nozzles.mounting
    assert doubled_pos == pos
    assert doubled_flow.nozzles.mode_flow_lpm("coarse") != d.nozzles.mode_flow_lpm("coarse")

    base = _coarse_survival(d, pos, env)
    other = _coarse_survival(doubled_flow, doubled_pos, env)

    assert other != base, (
        "two designs differing only in K-factor (hence mode_flow_lpm) got "
        "identical cached geometry -- mode_flow_lpm is missing from _geometry_key"
    )


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


def test_shielding_does_not_widen_the_geometry_cache_key():
    """Task 17 test 5. Everything `spray_shielding_factor` reads -- mode flow,
    cone angle, launch velocity, droplet size, drop height -- is already fixed by
    the design, and the gas temperature it scales is already bucketed, so
    shielding composes with the existing cache without adding a dimension to the
    key. Measured over one full three-anchor `compare.residuals` call and judged
    against the 98.54% Task 16 measured on the same call.
    """
    from validation import compare

    mist._GEOMETRY_CACHE.clear()
    counts = {"lookups": 0, "misses": 0}
    real_geometry, real_compute = mist._geometry, mist._compute_geometry

    def counting_geometry(*args, **kwargs):
        counts["lookups"] += 1
        return real_geometry(*args, **kwargs)

    def counting_compute(*args, **kwargs):
        counts["misses"] += 1
        return real_compute(*args, **kwargs)

    mist._geometry, mist._compute_geometry = counting_geometry, counting_compute
    try:
        compare.residuals(compare.load_anchors())
    finally:
        mist._geometry, mist._compute_geometry = real_geometry, real_compute

    hit_rate = 100.0 * (counts["lookups"] - counts["misses"]) / counts["lookups"]
    assert counts["lookups"] > 1000, "the call must exercise the cache properly"
    assert abs(hit_rate - TASK_16_CACHE_HIT_RATE_PCT) <= 1.0, (
        f"hit rate {hit_rate:.2f}% against Task 16's "
        f"{TASK_16_CACHE_HIT_RATE_PCT}%: shielding widened the cache key")

import math
import copy
import json

import pytest
from solit2.schema.design import Design
from solit2.schema.presets import PRESET_DIR, load_calibration, reload_calibration
from solit2.engines.reduced.geometry import section_geometry, nozzle_positions
from solit2.engines.reduced import droplet, mist

BASELINE = "examples/designs/road-tunnel-twin-bore.json"
FIRE_TOP_M = 4.0
Q_CONV_KW = 50_000 * 0.65
HRR_MW = 50.0

# What the previous top-face-only delivery model reported for the SOLIT2
# reference geometry (c4: nozzles 0.9 m above a 4.0 m fuel top, 2.25 m/s, cold
# gas so evaporation plays no part). Measured on the model as it stood at commit
# 7ec4066, before the interception envelope replaced the single-plane halo.
# Pinned here so the structural change has something concrete to be judged
# against rather than an assertion that only says "bigger than zero".
OLD_TOP_PLANE_W_FUEL_MM_MIN = 1.639

# Task 25 moved this ratio. The envelope model's margin over twice the old
# top-plane figure was never large -- 3.362 mm/min against 3.278, i.e. 2.5% --
# and expanding each mode into a droplet SPECTRUM takes a further 9% off, because
# the finest bin of a 90 um spray drifts 53 m in 2.25 m/s of tunnel air and is
# carried clean out of the 60 m zone before it has fallen the 0.9 m to the fuel.
# That water genuinely does not wet this fuel. The ratio is now 1.86, measured
# stable across 12 to 48 size bins (1.86, 1.86, 1.88), so the bound is set below
# it with room rather than re-pinned on the nose. The claim the test is named for
# is untouched and is asserted directly below: whole envelope over top face alone
# was 1.74 before the spectrum and is 1.72 after.
ENVELOPE_OVER_OLD_TOP_PLANE = 1.75
ENVELOPE_OVER_ITS_OWN_TOP_FACE = 1.5

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
           fire_top_m=FIRE_TOP_M, hrr_mw=HRR_MW, hrr_free_mw=HRR_MW):
    """Delivery against a fully involved fire unless a test says otherwise.

    `hrr_mw == hrr_free_mw` is a fire the spray has taken nothing off yet, which
    makes `mist.burning_fraction` 1 and the hardening term 1. Every delivery
    test here is about what reaches the fuel, not about how far the fire has
    already been driven down, so that is the condition they all want.
    """
    d = design or Design.load(BASELINE)
    geom = section_geometry(d)
    pos = nozzle_positions(d, geom, fire_x_m=0.0)
    env = _envelope(d, geom, reach_m)
    effect = mist.evaluate(d, geom, pos, env, fire_top_m, u_ms, gas_excess_k,
                           Q_CONV_KW, flow_fraction,
                           hrr_mw=hrr_mw, hrr_free_mw=hrr_free_mw)
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
    _, _, pos, env, effect = _setup(d, u_ms=2.25, gas_excess_k=0.0)

    assert effect.w_fuel_mm_min > 0.0
    assert effect.w_fuel_mm_min > ENVELOPE_OVER_OLD_TOP_PLANE * OLD_TOP_PLANE_W_FUEL_MM_MIN

    # The structural claim, against this same run rather than a historical
    # number: the stack's flanks are most of what it intercepts, so counting
    # only its top face reports a small fraction of the real delivery.
    deliveries = mist.mode_deliveries(d, pos, env, FIRE_TOP_M, 2.25, 0.0, 1.0)
    top_only = sum(m.flow_to_top_lpm for m in deliveries) / env.top.area_m2
    assert effect.w_fuel_mm_min > ENVELOPE_OVER_ITS_OWN_TOP_FACE * top_only


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
    # One-sided on purpose. The claim is that the key did not get WIDER, so the
    # hit rate must not FALL below what Task 16 measured. A higher rate means
    # more sharing, which is the good direction -- the size distribution pushed
    # it to ~99.6% by flying several bins through one cached geometry, and a
    # two-sided band rejected that improvement as if it were a regression.
    assert hit_rate >= TASK_16_CACHE_HIT_RATE_PCT - 1.0, (
        f"hit rate {hit_rate:.2f}% fell below Task 16's "
        f"{TASK_16_CACHE_HIT_RATE_PCT}% floor: something widened the cache key")


# --- task 24: the suppression law's dependence on the fire it is fighting -----
#
# The equilibrium these tests describe is real but is NOT reachable in the
# shipped engine: `suppression_hardening_exponent` is 0.0 because every value
# large enough to matter lifts c4 over the delivery model's evaporation cliff
# (w_fuel falls 109x between 275 K and 350 K of ceiling excess) and the fire
# escapes to free burn. See the constant's note in calibration.json. These pin
# the LAW, on a delivery held fixed, so that the day the delivery stops being
# near-binary in gas temperature the term can be raised and verified.

# Pinned for the same reason the envelope tests pin the flank constants: these
# are about the SHAPE of the suppression law and must keep their meaning after a
# fit has moved the values. Both sit near their current fitted values, so the
# levels below stay comparable with the task-24 measurements.
LAW_SHAPE_ETA_MAX = 0.97
LAW_SHAPE_W_REF_MM_MIN = 0.31
# The delivery c4 actually runs at once the mist is established, from the trace
# in the task-24 report: 4.18 mm/min over 19.8% of the interception envelope.
C4_W_FUEL_MM_MIN = 4.18
C4_F_COV = 0.198


def _law_cal(exponent):
    """The mist constants with the law's shape pinned and one exponent set."""
    cal = copy.deepcopy(load_calibration())["mist"]
    cal["eta_max"]["value"] = LAW_SHAPE_ETA_MAX
    cal["w_ref_mm_min"]["value"] = LAW_SHAPE_W_REF_MM_MIN
    cal["suppression_hardening_exponent"]["value"] = exponent
    return cal


def _settled(cal, w_fuel, f_cov=C4_F_COV, start=1.0, steps=400):
    """Iterate `S -> 1 - eta(S)` to where the suppressed fire comes to rest.

    `fire.step` relaxes the suppression fraction toward `1 - eta` and the fire is
    `hrr_free * suppression`, so a fixed point of this map IS the plateau the
    time loop walks to -- without paying for a 42-minute run to find it.
    """
    s = start
    for _ in range(steps):
        s = 1.0 - mist._suppression_efficiency(cal, w_fuel, f_cov, s)
    return s


def _step_ratios(levels):
    """How evenly a ladder of settled levels is spaced, as successive ratios."""
    return [a / b for a, b in zip(levels, levels[1:])]


def test_burning_fraction_is_the_share_of_free_burn_still_alive():
    assert mist.burning_fraction(30.0, 150.0) == pytest.approx(0.2)
    # a fire the spray has taken nothing off yet
    assert mist.burning_fraction(150.0, 150.0) == pytest.approx(1.0)
    # before the fire exists there is nothing to be a fraction of
    assert mist.burning_fraction(0.0, 0.0) == 1.0
    assert mist.burning_fraction(5.0, 0.0) == 1.0
    # and the ratio can never leave 0..1, whatever rounding hands it
    assert mist.burning_fraction(151.0, 150.0) == 1.0
    assert mist.burning_fraction(-1.0, 150.0) == 0.0


def test_a_zero_exponent_reproduces_the_unhardened_law_exactly():
    """The shipped default must be the previous model to the last bit.

    `suppression_hardening_exponent` is 0.0 in calibration.json, so this is what
    guarantees the structural change moved no anchor. Asserted against the closed
    form the module used before, at the live constants, not a recorded number.
    """
    cal = copy.deepcopy(load_calibration())["mist"]
    cal["suppression_hardening_exponent"]["value"] = 0.0
    eta_max, w_ref = cal["eta_max"]["value"], cal["w_ref_mm_min"]["value"]
    for w_fuel, f_cov, f_burn in ((4.18, 0.198, 0.26), (8.23, 0.191, 0.03),
                                  (0.013, 0.19, 1.0)):
        unhardened = eta_max * (1.0 - math.exp(-w_fuel * f_cov / w_ref))
        assert mist._suppression_efficiency(cal, w_fuel, f_cov, f_burn) == unhardened


def test_hardening_makes_an_already_knocked_down_fire_cost_more_water():
    """The law's defining behaviour: what is left is the part the spray reaches
    least, so the same delivery buys a smaller fractional reduction."""
    cal = _law_cal(0.5)
    etas = [mist._suppression_efficiency(cal, C4_W_FUEL_MM_MIN, C4_F_COV, f)
            for f in (0.05, 0.2, 0.5, 1.0)]
    assert etas == sorted(etas), "eta must rise with the fire still left to fight"
    assert etas[0] < etas[-1]


def test_the_hardened_law_settles_at_a_stable_interior_level():
    """The point of the change: a plateau, not a transient on the way to nothing."""
    cal = _law_cal(0.5)
    floor = 1.0 - LAW_SHAPE_ETA_MAX

    level = _settled(cal, C4_W_FUEL_MM_MIN)
    assert 3.0 * floor < level < 1.0, "must settle well above near-extinction"

    # stable, not merely stationary: pushed either way it comes back
    for nudge in (0.4, 2.0):
        assert _settled(cal, C4_W_FUEL_MM_MIN,
                        start=min(level * nudge, 1.0)) == pytest.approx(level, rel=1e-6)


def test_hardening_is_what_stops_the_law_collapsing_into_a_switch():
    """Consequence 2 of the task-24 brief, pinned.

    Unhardened, the settled level has no `S` in it at all -- it is just
    `1 - eta(delivery)` -- and over a 16x ladder in water it runs onto the
    `1 - eta_max` floor and stops responding. That saturation is why the design
    sweep is bimodal. Hardened, the same ladder stays off the floor and its
    steps stay near-even, which is what a design tool can interpolate between.
    """
    water = (1.0, 2.0, C4_W_FUEL_MM_MIN, 8.0, 16.0)
    floor = 1.0 - LAW_SHAPE_ETA_MAX

    plain = [_settled(_law_cal(0.0), w) for w in water]
    hardened = [_settled(_law_cal(0.5), w) for w in water]

    assert plain[-1] == pytest.approx(floor, abs=0.005), (
        f"the unhardened law must saturate onto its floor: {plain}")
    assert hardened[-1] > 2.5 * floor, (
        f"the hardened law must stay off the floor: {hardened}")

    assert hardened == sorted(hardened, reverse=True), f"not monotone: {hardened}"
    plain_spread = max(_step_ratios(plain)) / min(_step_ratios(plain))
    hardened_spread = max(_step_ratios(hardened)) / min(_step_ratios(hardened))
    assert hardened_spread < plain_spread / 1.5, (
        f"hardened steps {_step_ratios(hardened)} are no more even than "
        f"unhardened {_step_ratios(plain)}")


# --- task 25: the spray is a size distribution, not one representative drop ---
#
# `droplet.integrate` flies ONE diameter, and a mode's `smd_um` is a Sauter MEAN,
# so the engine was modelling a 90 um spray as a population all at exactly 90 um.
# That made the delivery effectively binary in gas temperature: one diameter
# either survives the fall or it does not. `_mode_geometry` now flies the whole
# spectrum and sums it. The trajectory, drag, evaporation and shielding physics
# are untouched; only the population they are applied to changed.

# c4's delivery on the model as it stood at commit cd80021, immediately before
# this change: the single 90 um drop, at the real calibration, over the gas
# excess band where it collapsed. 275 -> 350 K is a 108x fall and everything
# above it sits on the FULLY_EVAPORATED_UM floor of 0.013 mm/min.
# Recorded on the engine as it stood BEFORE the size distribution, at the
# calibration of that moment. Every one of these depends on constants the fit
# moves -- `evaporation_k_ref_m2s` alone went 1.02e-8 -> 4.21e-8 at the refit
# that followed -- so the table is a record of the OLD MODEL'S SHAPE, not of the
# current engine's numbers, and the equivalence test below pins the calibration
# it was taken at rather than comparing against whatever is live.
SINGLE_DROP_W_FUEL_MM_MIN = {0.0: 9.56115, 275.0: 1.41918, 300.0: 0.13941,
                             325.0: 0.01274, 350.0: 0.01312}
SINGLE_DROP_CALIBRATION = {"evaporation_k_ref_m2s": 1.0232541092292674e-08,
                           "w_ref_mm_min": 0.3088315203989264,
                           "eta_max": 0.971705608998945,
                           "flank_efficiency": 0.9962348912482406,
                           "flank_reach_factor": 0.8564404195793335,
                           "shielding_reference_loading_kgm3": 0.009708329485589995}
# No 25 K step of ceiling gas temperature may take more than this share of the
# delivery with it. The single drop took 90% in one step twice over; a spray
# whose coarse tail is still arriving after its fines have gone cannot.
MAX_DELIVERY_LOSS_PER_25K_STEP = 0.10
C4_GAS_BAND_K = (275.0, 300.0, 325.0, 350.0)


def _c4_delivery(gas_excess_k, bin_count=None):
    """c4's spray delivery at one ceiling gas excess, at a chosen bin count."""
    real = droplet.SIZE_DISTRIBUTION_BINS
    if bin_count is not None:
        droplet.SIZE_DISTRIBUTION_BINS = bin_count
    mist._GEOMETRY_CACHE.clear()
    try:
        _, _, _, _, effect = _setup(_solit2_reference_design(), u_ms=2.25,
                                    gas_excess_k=gas_excess_k)
        return effect
    finally:
        droplet.SIZE_DISTRIBUTION_BINS = real
        mist._GEOMETRY_CACHE.clear()


def test_one_size_bin_is_the_previous_single_drop_model_exactly(monkeypatch):
    """The change has to be a strict generalisation, so that any difference in
    an anchor is attributable to the SPECTRUM and to nothing else. Pinned
    against `w_fuel` measured on the engine as it stood before this task, not
    against a value this code produced."""
    import copy as _copy
    from solit2.schema.presets import load_calibration as _load
    from solit2.engines.reduced import mist as _mist
    cal = _copy.deepcopy(_load())
    cal["mist"].update({k: {**cal["mist"][k], "value": v}
                        for k, v in SINGLE_DROP_CALIBRATION.items()})
    monkeypatch.setattr(_mist, "load_calibration", lambda: cal)
    monkeypatch.setattr(droplet, "load_calibration", lambda: cal)
    _mist._GEOMETRY_CACHE.clear()

    for gas_excess_k, expected in SINGLE_DROP_W_FUEL_MM_MIN.items():
        got = _c4_delivery(gas_excess_k, bin_count=1).w_fuel_mm_min
        # The recorded values carry five decimal places, so that is the tightest
        # the comparison can honestly be.
        assert got == pytest.approx(expected, rel=1e-4), (
            f"at {gas_excess_k} K of gas excess one bin gave {got:.5f} mm/min "
            f"against the single drop's {expected}")


def test_the_delivery_cliff_becomes_a_slope():
    """The defect this task exists for. Across 275-350 K of ceiling gas excess
    the single-drop delivery fell by 108x and then sat on the fully-evaporated
    floor. A spectrum must degrade, not collapse: still monotone, but no step
    may cost more than a tenth of what is arriving."""
    got = [_c4_delivery(g).w_fuel_mm_min for g in C4_GAS_BAND_K]

    assert got == sorted(got, reverse=True), f"delivery must still fall: {got}"
    for before, after, gas in zip(got, got[1:], C4_GAS_BAND_K[1:]):
        assert after > (1.0 - MAX_DELIVERY_LOSS_PER_25K_STEP) * before, (
            f"the 25 K step up to {gas} K took {100*(1-after/before):.0f}% of the "
            f"delivery: {before:.4f} -> {after:.4f} mm/min")
    assert got[-1] > 0.5 * got[0], f"the whole 75 K band must not halve it: {got}"


def test_it_is_the_spectrum_and_not_something_else_that_does_it():
    """Same code, same constants, same physics: only the bin count differs."""
    single = _c4_delivery(350.0, bin_count=1).w_fuel_mm_min
    spread = _c4_delivery(350.0).w_fuel_mm_min
    assert single < 0.02, "the single drop is on the fully-evaporated floor"
    assert spread > 100.0 * single


def test_a_mode_survives_by_volume_share_and_not_by_droplet_count():
    """The weighting, verified against an independent recomputation.

    The bin weights have to be shares of the spray's VOLUME, because everything
    downstream is a volume flow. A spray's droplets are overwhelmingly fines --
    they carry cubically less water each -- so weighting by count instead would
    put most of the delivered water on the bins that evaporate first and would
    quietly restore most of the cliff. Both are computed here from the same
    trajectories; only the weights differ, and the model must match the first.
    """
    gas_excess_k = 350.0
    d = _solit2_reference_design()
    mode = d.nozzles.modes[0]
    smd = d.nozzles.smd_um(mode.id)
    drop_height_m = d.nozzles.mounting.height_above_carriageway_m - FIRE_TOP_M
    shield = droplet.spray_shielding_factor(
        mode_flow_lpm=d.nozzles.mode_flow_lpm(mode.id),
        cone_half_angle_deg=mode.cone_half_angle_deg,
        launch_velocity_ms=mode.launch_velocity_ms,
        diameter_um=smd, drop_height_m=drop_height_m)

    bins = droplet.size_distribution(smd)
    survival = [droplet.integrate(b.diameter_um, mode.launch_velocity_ms, 0.0,
                                  drop_height_m, 2.25,
                                  gas_excess_k=gas_excess_k * shield).surviving_fraction
                for b in bins]
    by_volume = sum(b.volume_fraction * s for b, s in zip(bins, survival))
    counts = [b.volume_fraction / b.diameter_um ** 3 for b in bins]
    by_number = sum(c * s for c, s in zip(counts, survival)) / sum(counts)

    mist._GEOMETRY_CACHE.clear()
    geom = section_geometry(d)
    pos = nozzle_positions(d, geom, fire_x_m=0.0)
    got = mist._geometry(d, pos, _envelope(d, geom), FIRE_TOP_M, 2.25, gas_excess_k)

    assert got[0].surviving_fraction == pytest.approx(by_volume, rel=1e-9)
    assert by_number < 0.5 * by_volume, (
        f"number weighting {by_number:.4f} must be far below volume weighting "
        f"{by_volume:.4f}, or this test cannot tell them apart")


def test_the_delivery_never_exceeds_the_water_the_heads_are_flowing():
    """A spectrum sums twelve sweeps where there was one, so the cap that stops
    a head delivering more than it is given has twelve chances to be wrong."""
    d, _, pos, env, _ = _setup(_solit2_reference_design(), u_ms=2.25)
    delivered = sum(m.flow_to_fuel_lpm for m in
                    mist.mode_deliveries(d, pos, env, FIRE_TOP_M, 2.25, 0.0, 1.0))
    assert 0.0 < delivered <= d.nozzles.flow_per_head_lpm * len(pos)


def test_reloading_calibration_busts_the_geometry_cache_for_the_spectrum_too(
        real_calibration_file):
    """`droplet_size_spread` is the second constant to reach `_compute_geometry`
    without passing through `_geometry_key` -- `size_distribution` reads it
    internally, exactly as `spray_shielding_factor` reads its own. The
    unconditional invalidation hook is what covers it; this proves it does."""
    d, _, pos, env, _ = _setup()
    mist._GEOMETRY_CACHE.clear()

    _write_mist_constants(droplet_size_spread=1.5)
    wide = _coarse_survival(d, pos, env)

    _write_mist_constants(droplet_size_spread=4.0)
    narrow = _coarse_survival(d, pos, env)

    assert wide != narrow, (
        "the second call was served trajectories computed under the FIRST "
        "droplet_size_spread, not the value just reloaded")


def test_spray_delivery_is_continuous_in_gas_temperature():
    """The cache is quantised because trajectories are expensive. Snapping the
    PHYSICS to a bucket centre is a different thing, and it put the engine in a
    period-2 limit cycle: gas temperature drives evaporation, evaporation
    drives how much water lands, and that drives gas temperature back -- so a
    step in delivery across a bucket edge is a feedback loop with a
    discontinuity in it."""
    from solit2.engines.reduced import mist as mist_mod
    from solit2.engines.reduced.geometry import nozzle_positions, section_geometry
    from solit2.schema.design import Design

    design = Design.load("examples/designs/road-tunnel-twin-bore.json")
    geom = section_geometry(design)
    positions = nozzle_positions(design, geom, 0.0)
    fp = design.fire.footprint
    envelope = mist_mod.fuel_envelope(0.0, 0.0, fp.length_m, fp.width_m,
                                      mist_mod.flank_reach_m(fp.top_height_m))
    width = mist_mod.GAS_EXCESS_BUCKET_K

    def surviving(excess_k):
        g = mist_mod._geometry(design, positions, envelope, fp.top_height_m, 4.0, excess_k)
        return sum(m.surviving_fraction for m in g) / len(g)

    # straddle a bucket edge by a tenth of a kelvin
    edge = 2 * width
    below, above = surviving(edge - 0.05), surviving(edge + 0.05)
    assert abs(above - below) < 0.01, (
        f"delivery jumps {abs(above - below):.3f} across a bucket edge at {edge} K")
    # and the response is monotone and smooth across a whole bucket
    samples = [surviving(edge - width / 2 + i * width / 20) for i in range(21)]
    steps = [abs(b - a) for a, b in zip(samples, samples[1:])]
    assert max(steps) < 0.02, f"largest step within a bucket {max(steps):.3f}"


def test_the_engine_does_not_oscillate_step_to_step():
    """The symptom this was found by: the ceiling at D03 alternated 41.6 C and
    55.8 C every second for two thirds of the run, which is what a 25 K
    quantisation looks like inside a feedback loop."""
    from solit2.engines.reduced import envelope as env
    from solit2.engines.reduced.sim import run_once
    from solit2.schema.design import Design

    design = Design.load("examples/designs/road-tunnel-twin-bore.json")
    result = env.run(design)
    trace = run_once(design, result.worst_case["section"], result.worst_case["velocity_ms"])
    tops = [s.stations["D03"].temps_c[-1] for s in trace.steps]
    jumps = [abs(b - a) for a, b in zip(tops, tops[1:])]
    assert max(jumps) < 2.0, f"largest one-second change {max(jumps):.1f} C"
    # and the cooling fraction that drives it, once the pumps are at full
    # pressure. Before that the valves opening and the pumps ramping are real
    # step changes in the system, not artefacts of the model.
    settled = trace.events["t_full_pressure_s"]
    chis = [s.mist.chi_cool for s in trace.steps if s.t_s >= settled]
    chi_jumps = [abs(b - a) for a, b in zip(chis, chis[1:])]
    assert max(chi_jumps) < 0.02, (
        f"cooling fraction jumps {max(chi_jumps):.3f} in one second after full pressure")

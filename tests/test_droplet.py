import copy

import pytest
from solit2.engines.reduced import droplet
from solit2.schema.presets import load_calibration


def _shielding_floor() -> float:
    """The floor is a calibration constant, not a module constant, and it is
    deliberately NOT fitted -- read it rather than restating it here."""
    return load_calibration()["mist"]["shielding_floor"]["value"]


def test_drag_coefficient_switches_from_stokes_to_newton():
    # Schiller-Naumann at Re=0.5: 24/Re * (1 + 0.15*Re**0.687) = 52.4722.
    # Pure Stokes (24/Re) would give 48.0, so this value discriminates between
    # the two rather than merely recording whatever the code currently outputs.
    assert droplet.drag_coefficient(0.5) == pytest.approx(52.4722, rel=0.001)
    assert droplet.drag_coefficient(2000.0) == pytest.approx(0.44)


def test_terminal_velocities_are_physical():
    assert droplet.terminal_velocity_ms(100) == pytest.approx(0.25, rel=0.25)
    assert droplet.terminal_velocity_ms(450) == pytest.approx(1.9, rel=0.25)
    assert droplet.terminal_velocity_ms(450) > 5 * droplet.terminal_velocity_ms(100)


def test_fine_mist_is_blown_far_downstream_before_reaching_the_carriageway():
    t = droplet.integrate(diameter_um=100, launch_velocity_ms=15.0, launch_angle_deg=0.0,
                          drop_height_m=5.75, air_velocity_ms=5.0, gas_excess_k=0.0)
    assert 60.0 < t.drift_m < 180.0
    assert t.reached_target


def test_coarse_core_lands_almost_under_the_nozzle():
    t = droplet.integrate(diameter_um=450, launch_velocity_ms=100.0, launch_angle_deg=0.0,
                          drop_height_m=5.75, air_velocity_ms=5.0, gas_excess_k=0.0)
    assert t.drift_m < 20.0


def test_the_bimodal_argument_in_numbers():
    fine = droplet.integrate(100, 15.0, 0.0, 1.75, 5.0, 0.0)
    coarse = droplet.integrate(450, 100.0, 0.0, 1.75, 5.0, 0.0)
    assert coarse.drift_m * 10 < fine.drift_m


def test_more_wind_means_more_drift():
    slow = droplet.integrate(100, 15.0, 0.0, 5.75, 3.88, 0.0)
    fast = droplet.integrate(100, 15.0, 0.0, 5.75, 5.08, 0.0)
    assert fast.drift_m > slow.drift_m


def test_fine_mist_evaporates_in_hot_gas_and_survives_in_cool_air():
    cool = droplet.integrate(100, 15.0, 0.0, 1.75, 5.0, gas_excess_k=0.0)
    hot = droplet.integrate(100, 15.0, 0.0, 1.75, 5.0, gas_excess_k=600.0)
    assert cool.surviving_fraction > 0.95
    assert hot.surviving_fraction < 0.2
    assert not hot.reached_target


def test_coarse_core_survives_the_same_hot_gas():
    hot = droplet.integrate(450, 100.0, 0.0, 1.75, 5.0, gas_excess_k=600.0)
    assert hot.surviving_fraction > 0.9
    assert hot.reached_target


def test_tilting_the_spray_off_vertical_increases_drift():
    # launch_angle_deg is measured from vertical, so 0 deg is already straight down:
    # any tilt both cuts the downward velocity component and adds a downstream one.
    flat = droplet.integrate(100, 15.0, 0.0, 5.75, 5.0, 0.0)
    tilted = droplet.integrate(100, 15.0, 45.0, 5.75, 5.0, 0.0)
    assert tilted.drift_m > flat.drift_m


# --- task 17: spray-core shielding -------------------------------------------
#
# A droplet does not fall alone; it falls inside a cloud of other droplets from
# the same spray, which locally cools and humidifies the gas around it. These
# tests pin the SHAPE of that correction, not the fitted constant's value, so
# they keep their meaning after a fit has moved `shielding_reference_loading_kgm3`.

# The SOLIT2 reference head at the c4 geometry: 28 lpm through one 50-degree
# fine mode at 25 m/s, 90 um drops, 0.9 m from the nozzle to the fuel top.
C4_FLOW_LPM = 28.0
C4_CONE_HALF_ANGLE_DEG = 50.0
C4_LAUNCH_MS = 25.0
C4_SMD_UM = 90.0
C4_DROP_HEIGHT_M = 0.9

# The bimodal illustration preset at 50 bar, 28.99 lpm per head: a wide fine
# mode and a narrow, fast coarse mode. Used for the cone-angle consistency check.
BIMODAL_FINE = dict(mode_flow_lpm=17.39, cone_half_angle_deg=45.0,
                    launch_velocity_ms=15.0, diameter_um=102.0, drop_height_m=1.75)
BIMODAL_COARSE = dict(mode_flow_lpm=11.60, cone_half_angle_deg=8.0,
                      launch_velocity_ms=100.0, diameter_um=450.0, drop_height_m=1.75)


def test_a_sparse_spray_reduces_to_the_unshielded_single_droplet():
    """Test 1. At zero water loading the droplet's local environment IS the
    ambient plume, so the shield factor must be exactly 1.0 -- today's behaviour
    recovered exactly as a limiting case, not approximately."""
    assert droplet.spray_shielding_factor(
        mode_flow_lpm=0.0, cone_half_angle_deg=C4_CONE_HALF_ANGLE_DEG,
        launch_velocity_ms=C4_LAUNCH_MS, diameter_um=C4_SMD_UM,
        drop_height_m=C4_DROP_HEIGHT_M) == 1.0

    trickle = droplet.spray_shielding_factor(
        mode_flow_lpm=1e-9, cone_half_angle_deg=C4_CONE_HALF_ANGLE_DEG,
        launch_velocity_ms=C4_LAUNCH_MS, diameter_um=C4_SMD_UM,
        drop_height_m=C4_DROP_HEIGHT_M)
    assert trickle == pytest.approx(1.0)
    assert trickle < 1.0, "any water at all must shield a little"


def test_more_flow_shields_monotonically_more_and_never_passes_the_floor():
    """Test 2. Denser spray core, colder and wetter local gas, lower shield
    factor -- but never below the floor, because the spray entrains hot ambient
    gas and full insulation from it is not physical."""
    flows = [0.1, 1.0, 5.0, 28.0, 100.0, 1_000.0, 1e6]
    shields = [droplet.spray_shielding_factor(
        mode_flow_lpm=q, cone_half_angle_deg=C4_CONE_HALF_ANGLE_DEG,
        launch_velocity_ms=C4_LAUNCH_MS, diameter_um=C4_SMD_UM,
        drop_height_m=C4_DROP_HEIGHT_M) for q in flows]

    assert shields == sorted(shields, reverse=True)
    assert all(a > b for a, b in zip(shields, shields[1:])), "strictly decreasing"
    floor = _shielding_floor()
    assert all(s >= floor for s in shields)
    assert shields[-1] == pytest.approx(floor, abs=1e-4)


def test_a_narrower_cone_concentrates_the_same_flow_and_shields_more():
    """Test 3. The consistency check the brief asks for by name: the same flow
    through a narrower cone occupies less volume at the same distance, so its
    loading is higher and its shield factor lower."""
    wide = droplet.spray_shielding_factor(
        mode_flow_lpm=20.0, cone_half_angle_deg=45.0, launch_velocity_ms=20.0,
        diameter_um=100.0, drop_height_m=1.75)
    narrow = droplet.spray_shielding_factor(
        mode_flow_lpm=20.0, cone_half_angle_deg=8.0, launch_velocity_ms=20.0,
        diameter_um=100.0, drop_height_m=1.75)
    assert narrow < wide


def test_the_bimodal_coarse_mode_self_shields_more_than_the_fine_mode():
    """Test 3, on a design that really has both modes. The coarse mode is
    launched 6.7x faster and carries less of the flow, both of which REDUCE its
    loading; the 8-degree cone concentrates it into a ~50x smaller area, which
    wins. If this ever inverts, the brief's argument for why a ballistic core
    survives the plume no longer follows from the loading formula."""
    fine = droplet.spray_shielding_factor(**BIMODAL_FINE)
    coarse = droplet.spray_shielding_factor(**BIMODAL_COARSE)
    assert coarse < fine


def test_shielding_keeps_a_droplet_alive_through_hot_gas():
    """Test 4. The coupling is real and must not be fought: less evaporation
    means the droplet stays larger for longer, which changes its drag and so its
    drift. `integrate` is unchanged -- shielding only scales the gas temperature
    rise it is handed."""
    hot_k = 600.0
    unshielded = droplet.integrate(C4_SMD_UM, C4_LAUNCH_MS, 0.0, C4_DROP_HEIGHT_M,
                                   2.25, gas_excess_k=hot_k * 1.0)
    shielded = droplet.integrate(C4_SMD_UM, C4_LAUNCH_MS, 0.0, C4_DROP_HEIGHT_M,
                                 2.25, gas_excess_k=hot_k * _shielding_floor())

    assert shielded.surviving_fraction > unshielded.surviving_fraction
    assert shielded.final_diameter_um > unshielded.final_diameter_um
    assert shielded.flight_s > unshielded.flight_s, "it survives further into the fall"
    assert not unshielded.reached_target, (
        "the unshielded 90 um drop must not arrive -- this is the defect Task 16 found")


def test_shielding_only_lands_the_reference_droplet_at_a_low_evaporation_constant(
        monkeypatch):
    """Test 4, continued -- the claim that matters for whether shielding can
    close Task 16's gap at all.

    Floor-shielding the 90 um reference drop to 30 K (600 K * the shielding
    floor) is not sufficient on its own: whether it lands also depends on
    where `evaporation_k_ref_m2s` sits in its fitted range (validation/fit.py
    FITTED_KEYS: [1e-8, 1e-6]). Comparing the two ends of that fitted range
    directly -- rather than "today's calibrated value" against one hardcoded
    bound -- is what keeps this test meaningful after a fit moves the constant
    anywhere inside the range, including onto the lower bound itself, which is
    where the current fit already sits (see calibration.json's provenance
    note: this constant "did not move at all"). Both constants are needed, so
    a fit has a gradient in both; that is the whole point of the new
    structure, and if this ever passes at an order of magnitude above the
    lower bound the claim no longer holds.
    """
    hot_k = 600.0
    floor_shielded = hot_k * _shielding_floor()

    def _at(k_ref):
        cal = copy.deepcopy(load_calibration())
        cal["mist"]["evaporation_k_ref_m2s"]["value"] = k_ref
        monkeypatch.setattr(droplet, "load_calibration", lambda: cal)
        return droplet.integrate(C4_SMD_UM, C4_LAUNCH_MS, 0.0, C4_DROP_HEIGHT_M,
                                 2.25, gas_excess_k=floor_shielded)

    at_lower_bound = _at(1.0e-8)     # the fitted lower bound
    at_ten_x_higher = _at(1.0e-7)    # one order of magnitude up, still inside the range

    assert at_lower_bound.reached_target
    assert at_lower_bound.surviving_fraction > 0.5
    assert not at_ten_x_higher.reached_target


# --- task 25: the spray is a population, not one representative drop ---------
#
# `integrate` flies one diameter. A mode's `smd_um` is a Sauter MEAN, so a real
# spray carries droplets spread around it, and it is that spread -- not the mean
# -- that decides how the delivery decays with gas temperature. These tests pin
# the SHAPE of the spectrum and the volume bookkeeping, never the fitted spread
# value, which lives in calibration.json as `droplet_size_spread`.

REFERENCE_SMD_UM = 90.0


def _spread() -> float:
    return load_calibration()["mist"]["droplet_size_spread"]["value"]


def _number_fractions(bins) -> list[float]:
    """Convert volume shares to number shares: n_i is proportional to v_i / d_i**3."""
    raw = [b.volume_fraction / b.diameter_um ** 3 for b in bins]
    total = sum(raw)
    return [r / total for r in raw]


def test_the_bins_carry_the_whole_spray_and_nothing_more():
    """Test 1. Delivery is a volume flow, so the weights are volume shares and
    they must sum to exactly one -- no water invented, none lost."""
    bins = droplet.size_distribution(REFERENCE_SMD_UM)
    assert len(bins) == droplet.SIZE_DISTRIBUTION_BINS
    assert sum(b.volume_fraction for b in bins) == pytest.approx(1.0)
    assert all(b.diameter_um > 0 for b in bins)
    assert [b.diameter_um for b in bins] == sorted(b.diameter_um for b in bins)


def test_the_bin_set_reproduces_the_modes_sauter_mean_diameter():
    """Test 2. The Sauter mean is volume over surface, so for a volume-weighted
    bin set it is `1 / sum(v_i / d_i)`. `size_distribution` scales the whole
    spectrum so this is the declared SMD exactly, at any bin count and any
    spread. That is what keeps the spray's total surface area -- and so its
    evaporation rate and its radiation extinction -- the same as the single
    representative drop the model used before.
    """
    for bin_count in (1, 2, 5, 12, 40):
        bins = droplet.size_distribution(REFERENCE_SMD_UM, bin_count)
        sauter = 1.0 / sum(b.volume_fraction / b.diameter_um for b in bins)
        assert sauter == pytest.approx(REFERENCE_SMD_UM, rel=1e-9)


def test_one_bin_is_the_single_representative_drop_exactly():
    """Test 3. The change must be a strict generalisation: at one bin the model
    is the previous one, to the last bit, not merely close to it."""
    bins = droplet.size_distribution(REFERENCE_SMD_UM, 1)
    assert bins == (droplet.SizeBin(REFERENCE_SMD_UM, 1.0),)


def test_volume_shares_are_not_number_shares():
    """Test 4. The classic error here is weighting the bins by droplet COUNT.
    A spray's number distribution is overwhelmingly fines -- they are cheap by
    volume and there are cubically more of them -- so using number shares as
    volume shares would put most of the delivered water in droplets that carry
    almost none of it. The two must be far apart, and in this direction.
    """
    bins = droplet.size_distribution(REFERENCE_SMD_UM)
    number = _number_fractions(bins)

    assert number[0] > 0.4, "the finest bin must dominate by count"
    assert bins[0].volume_fraction < 0.15, "and carry little of the volume"
    assert number[0] > 5.0 * bins[0].volume_fraction

    volume_mean = sum(b.volume_fraction * b.diameter_um for b in bins)
    number_mean = sum(n * b.diameter_um for n, b in zip(number, bins))
    assert number_mean < 0.8 * volume_mean
    # Over half the spray's VOLUME sits in droplets coarser than its SMD, even
    # though the great majority of its droplets are finer. Both at once is the
    # signature of a correctly volume-weighted spectrum.
    coarser = sum(b.volume_fraction for b in bins if b.diameter_um > REFERENCE_SMD_UM)
    assert coarser > 0.5
    assert sum(n for n, b in zip(number, bins) if b.diameter_um > REFERENCE_SMD_UM) < 0.2


def test_a_wider_spectrum_keeps_more_water_alive_through_hot_gas(monkeypatch):
    """Test 5. Why this task exists. One diameter either survives the fall or it
    does not; a population degrades smoothly, because its coarse tail is still
    arriving after its fines have gone. A lower Rosin-Rammler n is a wider
    spectrum, so it must leave more water on the fuel in gas hot enough to kill
    the mean drop -- and every spectrum must beat the single drop outright.
    """
    hot_k = 400.0

    def surviving(bin_count, spread):
        cal = copy.deepcopy(load_calibration())
        cal["mist"]["droplet_size_spread"]["value"] = spread
        monkeypatch.setattr(droplet, "load_calibration", lambda: cal)
        bins = droplet.size_distribution(REFERENCE_SMD_UM, bin_count)
        return sum(b.volume_fraction * droplet.integrate(
            b.diameter_um, C4_LAUNCH_MS, 0.0, C4_DROP_HEIGHT_M, 2.25,
            gas_excess_k=hot_k).surviving_fraction for b in bins)

    single = surviving(1, _spread())
    assert single < 0.01, "the single 90 um drop is on the fully-evaporated floor"

    wide, mid, narrow = (surviving(droplet.SIZE_DISTRIBUTION_BINS, n)
                         for n in (1.8, 2.5, 4.0))
    # Ordering is the claim and it holds at any calibration: a wider spectrum has
    # a longer coarse tail, so it lands more water. The MARGIN over the single
    # drop is not a constant -- it scales with how hard the gas is evaporating,
    # so it moves with `evaporation_k_ref_m2s`, which the fit moves. A fixed 20x
    # went stale the first time that constant was refit. Asserted as a strict
    # ordering plus a margin that only has to be decisive.
    assert wide > mid > narrow, (
        f"a wider spectrum must land more water: {wide:.5f} / {mid:.5f} / {narrow:.5f}")
    assert narrow > 1.5 * single, (
        f"even the narrowest spectrum must beat the single drop outright: "
        f"{narrow:.5f} against {single:.5f}")


def test_the_spectrum_is_rejected_when_it_cannot_be_a_spray():
    with pytest.raises(ValueError, match="Sauter mean"):
        droplet.size_distribution(0.0)
    with pytest.raises(ValueError, match="at least one"):
        droplet.size_distribution(REFERENCE_SMD_UM, 0)


def test_a_spread_at_or_below_one_has_no_sauter_mean(monkeypatch):
    """The Rosin-Rammler Sauter mean is `X * gamma(1 - 1/n)`, which diverges at
    n = 1 and is negative below it: such a spectrum has infinite surface area
    per unit volume and is not a spray. Rejected rather than silently rescaled.
    """
    cal = copy.deepcopy(load_calibration())
    cal["mist"]["droplet_size_spread"]["value"] = 1.0
    monkeypatch.setattr(droplet, "load_calibration", lambda: cal)
    with pytest.raises(ValueError, match="droplet_size_spread"):
        droplet.size_distribution(REFERENCE_SMD_UM)

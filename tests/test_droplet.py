import pytest
from solit2.engines.reduced import droplet


def test_drag_coefficient_switches_from_stokes_to_newton():
    assert droplet.drag_coefficient(0.5) == pytest.approx(48.0, rel=0.1)
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

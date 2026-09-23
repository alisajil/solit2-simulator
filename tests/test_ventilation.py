import pytest
from solit2.engines.reduced.geometry import SectionGeometry
from solit2.engines.reduced import ventilation as vent

# An 11 m bored section, a cut & cover box, and the SOLIT2 test tunnel
BORE = SectionGeometry("bored", 10.146, 7.625, 70.29, "circle", 5.5, 2.125)
BOX = SectionGeometry("cut_cover", 9.0, 6.5, 58.5, "box")
SPDA = SectionGeometry("test", 9.5, 5.17, 48.0, "box")

CONV_150MW_KW = 150_000 * 0.65
CONV_100MW_KW = 100_000 * 0.65


def test_critical_velocity_bored_section_150mw():
    # Li, Lei & Ingason 2010: Q* > 0.15 so u_c* = 0.43, u_c = 0.43 sqrt(g H)
    assert vent.critical_velocity_ms(CONV_150MW_KW, BORE.crown_height_m) == pytest.approx(3.72, abs=0.05)


def test_critical_velocity_cut_and_cover_and_test_tunnel():
    assert vent.critical_velocity_ms(CONV_150MW_KW, BOX.crown_height_m) == pytest.approx(3.43, abs=0.05)
    assert vent.critical_velocity_ms(CONV_100MW_KW, SPDA.crown_height_m) == pytest.approx(3.06, abs=0.05)


def test_small_fire_falls_in_the_cube_root_regime():
    # 5 MW in the bore: Q* < 0.15, so u_c* = 0.81 Q*^(1/3) and u_c is well below 3 m/s
    u_c = vent.critical_velocity_ms(5_000 * 0.65, BORE.crown_height_m)
    assert 0.5 < u_c < 2.5
    assert vent.dimensionless_hrr(5_000 * 0.65, BORE.crown_height_m) < 0.15


def test_no_backlayering_above_the_critical_velocity():
    assert vent.backlayering_length_m(CONV_150MW_KW, BORE.crown_height_m, 5.08) == 0.0


def test_backlayering_grows_as_velocity_falls():
    at_3 = vent.backlayering_length_m(CONV_150MW_KW, BORE.crown_height_m, 3.0)
    at_2 = vent.backlayering_length_m(CONV_150MW_KW, BORE.crown_height_m, 2.0)
    assert 0.0 < at_3 < at_2
    assert at_2 < 200.0


def test_the_example_floor_velocity_clears_the_bore_by_a_thin_margin():
    u_c = vent.critical_velocity_ms(CONV_150MW_KW, BORE.crown_height_m)
    assert 3.88 > u_c
    assert (3.88 - u_c) / u_c < 0.10   # under 10 % margin - the engine must warn


def test_fire_throttles_the_airflow():
    state = vent.evaluate(BORE, fan_velocity_ms=5.08, q_conv_kw=CONV_150MW_KW)
    assert state.u_eff_ms < state.u_fan_ms
    assert state.u_eff_ms > 0.0
    cold = vent.evaluate(BORE, fan_velocity_ms=5.08, q_conv_kw=0.0)
    assert cold.u_eff_ms == pytest.approx(5.08)


def test_throttling_never_reverses_the_flow():
    state = vent.evaluate(BORE, fan_velocity_ms=1.0, q_conv_kw=CONV_150MW_KW)
    assert state.u_eff_ms > 0.0


def test_fans_off_during_a_fire_gives_a_long_backlayer_not_a_crash():
    state = vent.evaluate(BORE, fan_velocity_ms=0.0, q_conv_kw=CONV_150MW_KW)
    assert isinstance(state, vent.VentilationState)
    assert state.u_eff_ms > 0.0
    assert state.backlayer_m > 400.0


def test_throttled_velocity_floors_when_fans_are_off():
    # Fans off is a modelled state, so the floor is the right answer for it.
    assert vent.throttled_velocity_ms(0.0, CONV_150MW_KW, BORE.free_area_m2) == vent.MIN_EFFECTIVE_VELOCITY_MS


def test_throttled_velocity_rejects_a_reversed_fan_velocity():
    # Reversed flow is not modelled at all; answering with a small forward
    # velocity would be a silent wrong answer, so it must refuse instead.
    with pytest.raises(ValueError, match="-2.0"):
        vent.throttled_velocity_ms(-2.0, CONV_150MW_KW, BORE.free_area_m2)


def test_the_backlayer_heat_sets_the_backlayer_and_the_plume_heat_throttles_the_fans():
    """Under a spray the smoke that turns upstream carries less heat than the
    plume (mist.backlayer_heat_kw). Only the backlayer and the critical velocity
    read it; the fans are still throttled by the plume."""
    plume, backlayer = 20_000.0, 2_000.0
    both = vent.evaluate(SPDA, 1.5, plume, backlayer)
    plume_only = vent.evaluate(SPDA, 1.5, plume)
    assert both.u_eff_ms == plume_only.u_eff_ms
    assert both.u_critical_ms == pytest.approx(vent.critical_velocity_ms(backlayer, SPDA.crown_height_m))
    assert both.backlayer_m == pytest.approx(
        vent.backlayering_length_m(backlayer, SPDA.crown_height_m, both.u_eff_ms))
    assert both.backlayer_m < plume_only.backlayer_m


def test_a_negative_backlayer_heat_is_refused():
    with pytest.raises(ValueError, match="backlayer heat"):
        vent.evaluate(SPDA, 1.5, 20_000.0, -1.0)

import pytest
from solit2.schema.design import Design
from solit2.engines.reduced import fire, tenability

BASELINE = "examples/designs/road-tunnel-twin-bore.json"
# The example bored section at 5 m/s: 70.29 m2 x 5 m/s
AIR_M3S = 70.29 * 5.0


def _model():
    return fire.build_model(Design.load(BASELINE))


def test_species_concentrations_for_a_suppressed_fifty_megawatt_wood_fire():
    sp = tenability.species_at(_model(), hrr_mw=50.0, air_volumetric_m3s=AIR_M3S,
                               strat_factor=1.0)
    assert sp.co_ppm == pytest.approx(44.0, rel=0.25)
    assert 0.3 < sp.co2_pct < 1.5
    assert sp.soot_gm3 == pytest.approx(0.152, rel=0.25)
    assert 19.5 < sp.o2_pct < 21.0


def test_stratification_keeps_the_breathing_layer_clear():
    stratified = tenability.species_at(_model(), 50.0, AIR_M3S, strat_factor=0.1)
    mixed = tenability.species_at(_model(), 50.0, AIR_M3S, strat_factor=1.0)
    assert stratified.co_ppm == pytest.approx(0.1 * mixed.co_ppm, rel=0.01)


def test_fed_over_an_hour_at_the_stratified_concentration_passes_the_limit():
    sp = tenability.species_at(_model(), 50.0, AIR_M3S, strat_factor=0.1)
    fed = sum(tenability.fed_tox_increment(sp, 1.0) for _ in range(3600))
    assert fed < 0.3


def test_fed_at_fully_mixed_concentration_is_much_worse():
    mixed = tenability.species_at(_model(), 50.0, AIR_M3S, strat_factor=1.0)
    strat = tenability.species_at(_model(), 50.0, AIR_M3S, strat_factor=0.1)
    fed_mixed = sum(tenability.fed_tox_increment(mixed, 1.0) for _ in range(3600))
    fed_strat = sum(tenability.fed_tox_increment(strat, 1.0) for _ in range(3600))
    assert fed_mixed > 10 * fed_strat


def test_fed_heat_ignores_flux_below_the_pain_threshold():
    # 30 C is not above the convective threshold and 1.0 kW/m2 is below the
    # 2.5 kW/m2 radiant threshold, so neither term contributes: exactly zero.
    assert tenability.fed_heat_increment(temp_c=30.0, flux_kwm2=1.0, dt_s=60.0) == 0.0


def test_fed_heat_accumulates_fast_under_severe_exposure():
    one_minute = tenability.fed_heat_increment(temp_c=200.0, flux_kwm2=10.0, dt_s=60.0)
    # ISO 13571 over one minute, convective + radiant:
    #   1 / (5.0e7 * 200**-3.4)  = 1.332  (convected heat at 200 C)
    # + 1 / (6.9  *  10**-1.56)  = 5.262  (radiant heat at 10 kW/m2)
    # = 6.594
    assert one_minute == pytest.approx(6.594, rel=0.01)


def test_visibility_at_the_stratified_soot_load():
    sp = tenability.species_at(_model(), 50.0, AIR_M3S, strat_factor=0.1)
    assert tenability.visibility_m(sp.soot_gm3, kappa_mist_per_m=0.0) == pytest.approx(60.0, rel=0.25)


def test_mist_in_the_path_reduces_visibility():
    sp = tenability.species_at(_model(), 50.0, AIR_M3S, strat_factor=0.1)
    clear = tenability.visibility_m(sp.soot_gm3, 0.0)
    misty = tenability.visibility_m(sp.soot_gm3, 0.5)
    assert misty < clear


def test_diesel_makes_more_soot_per_megawatt_than_wood():
    pool_model = fire.build_model(Design.load("tests/fixtures/pool_design.json"))
    wood = tenability.species_at(_model(), 30.0, AIR_M3S, 1.0)
    diesel = tenability.species_at(pool_model, 30.0, AIR_M3S, 1.0)
    ratio = diesel.soot_gm3 / wood.soot_gm3
    # Yields give diesel 4x wood's soot per kg of fuel burnt (0.060 / 0.015 = 4.0), but
    # diesel's higher heat of combustion means less fuel mass is needed per MW, diluting
    # that by the heat-of-combustion ratio (44.8 / 17.5 = 2.56): 4.0 / 2.56 = 1.5625.
    assert ratio == pytest.approx(1.5625, rel=0.01)
    assert ratio > 1.0

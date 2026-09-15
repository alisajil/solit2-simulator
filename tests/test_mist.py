import pytest
from solit2.schema.design import Design
from solit2.engines.reduced.geometry import section_geometry, nozzle_positions
from solit2.engines.reduced import mist

BASELINE = "examples/designs/road-tunnel-twin-bore.json"
FIRE_TOP_M = 4.0
Q_CONV_KW = 50_000 * 0.65


def _setup(design=None, u_ms=5.0, gas_excess_k=0.0, flow_fraction=1.0):
    d = design or Design.load(BASELINE)
    geom = section_geometry(d)
    pos = nozzle_positions(d, geom, fire_x_m=0.0)
    fire_y = d.fire.lane_centre_offset_from_wall_m - geom.road_width_m / 2.0
    halo = mist.halo_around(0.0, fire_y, d.fire.footprint.length_m, d.fire.footprint.width_m)
    effect = mist.evaluate(d, geom, pos, halo, FIRE_TOP_M, u_ms, gas_excess_k,
                           Q_CONV_KW, flow_fraction)
    return d, geom, pos, halo, effect


def test_halo_is_the_fuel_footprint_plus_one_metre():
    _, geom, _, halo, _ = _setup()
    assert halo.x1_m - halo.x0_m == pytest.approx(10.4)
    assert halo.y1_m - halo.y0_m == pytest.approx(4.4)
    assert halo.area_m2 == pytest.approx(45.76, rel=0.01)


def test_no_flow_means_no_effect():
    _, _, _, _, effect = _setup(flow_fraction=0.0)
    assert effect.eta == 0.0
    assert effect.w_fuel_mm_min == 0.0
    assert effect.tau_mist == 1.0


def test_baseline_delivers_useful_flux_to_the_fuel():
    _, _, _, _, effect = _setup()
    assert 1.5 < effect.w_fuel_mm_min < 6.0
    assert effect.f_cov > 0.5
    assert 0.5 < effect.eta < 0.9


def test_fine_mode_is_carried_onto_the_fire_from_upstream_heads():
    # the fine mode's whole point: released far upstream, it arrives over the fire
    d, _, pos, halo, _ = _setup()
    deliveries = {m.mode_id: m for m in mist.mode_deliveries(
        d, pos, halo, FIRE_TOP_M, 5.0, 0.0, 1.0)}
    assert deliveries["fine"].drift_m > 10.0
    assert deliveries["coarse"].drift_m < 3.0
    assert deliveries["fine"].flow_to_halo_lpm > 0.0


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
    _, _, _, _, effect = _setup(gas_excess_k=900.0)
    assert effect.chi_cool <= 0.45 + 1e-9

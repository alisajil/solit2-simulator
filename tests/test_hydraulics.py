import pytest
from solit2.schema.design import Design
from solit2.engines.reduced.geometry import section_geometry
from solit2.engines.reduced.hydraulics import darcy_weisbach_bar, size_system

BASELINE = "examples/designs/road-tunnel-twin-bore.json"


def test_darcy_weisbach_against_a_hand_calculation():
    # 143.6 m3/h through 154.1 mm bore, 1000 m of it:
    # A = 0.018653 m2, v = 2.139 m/s, Re = 1.83e5, f ~ 0.0165 (Colebrook, eps 0.045 mm)
    # dp = f (L/D) rho v^2 / 2 = 0.0165 * 6489 * 1000 * 2.139^2 / 2 = 2.45e5 Pa = 2.45 bar
    dp = darcy_weisbach_bar(flow_m3s=143.6 / 3600, diameter_m=0.1541,
                            length_m=1000.0, roughness_mm=0.045)
    assert dp == pytest.approx(2.45, rel=0.10)


def test_example_flow_chain():
    hyd = size_system(Design.load(BASELINE), section_geometry(Design.load(BASELINE)))
    assert hyd.active_heads == 75
    assert hyd.flow_lpm == pytest.approx(2174.3, abs=2.0)        # stated: 2175
    assert hyd.flow_design_lpm == pytest.approx(2391.7, abs=3.0)  # stated: 2393


def test_example_pump_pressure_and_power():
    hyd = size_system(Design.load(BASELINE), section_geometry(Design.load(BASELINE)))
    assert hyd.required_pump_bar == pytest.approx(59.4, abs=2.5)  # stated: 59.4
    assert hyd.rated_pump_bar == pytest.approx(hyd.required_pump_bar * 1.10, rel=1e-6)
    assert hyd.power_kw == pytest.approx(375.0, rel=0.08)          # stated: ~375 kW
    assert hyd.power_kw < 650.0


def test_example_tank_volume_is_sixty_minutes_of_design_flow():
    hyd = size_system(Design.load(BASELINE), section_geometry(Design.load(BASELINE)))
    assert hyd.tank_m3 == pytest.approx(143.5, abs=1.0)            # stated: ~145


def test_density_uses_the_road_width_not_the_bore_diameter():
    d = Design.load(BASELINE)
    hyd = size_system(d, section_geometry(d))
    # 2175 lpm over 90 m x 10.146 m
    assert hyd.density_mm_min == pytest.approx(2.38, abs=0.05)


def test_higher_pressure_raises_flow_and_power():
    d = Design.load(BASELINE)
    geom = section_geometry(d)
    base = size_system(d, geom)
    hotter = size_system(d.model_copy(update={"nozzles": d.nozzles.model_copy(
        update={"pressure_bar": 60.0})}), geom)
    assert hotter.flow_lpm > base.flow_lpm
    assert hotter.power_kw > base.power_kw

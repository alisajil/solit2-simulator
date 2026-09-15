import math
import pytest
from solit2.engines.reduced.geometry import SectionGeometry
from solit2.engines.reduced import thermal

BORE = SectionGeometry("bored", 10.146, 7.625, 70.29, "circle", 5.5, 2.125)
# HGV load 8.4 x 2.4 m, top 4.0 m above the carriageway
B_FO = thermal.equivalent_radius_m(8.4, 2.4)
H_EF = 7.625 - 4.0


def test_equivalent_radius_of_the_hgv_footprint():
    assert B_FO == pytest.approx(2.533, abs=0.01)


def test_forced_regime_ceiling_excess_for_a_suppressed_fifty_megawatt_fire():
    # V' = u / w* > 0.19, so Li & Ingason region II applies
    dt = thermal.max_ceiling_excess_k(hrr_kw=50_000, q_conv_kw=32_500,
                                      u_ms=4.5, b_fo_m=B_FO, h_ef_m=H_EF)
    assert dt == pytest.approx(953.0, rel=0.05)


def test_free_burning_one_fifty_megawatt_fire_hits_the_cap():
    dt = thermal.max_ceiling_excess_k(hrr_kw=150_000, q_conv_kw=97_500,
                                      u_ms=4.5, b_fo_m=B_FO, h_ef_m=H_EF)
    assert dt == pytest.approx(1350.0)


def test_low_velocity_falls_into_the_plume_regime():
    # 5 MW at 0.3 m/s: V' < 0.19, region I formula, not capped
    dt = thermal.max_ceiling_excess_k(hrr_kw=5_000, q_conv_kw=3_250,
                                      u_ms=0.3, b_fo_m=B_FO, h_ef_m=H_EF)
    assert dt == pytest.approx(598.0, rel=0.05)


def test_longitudinal_decay_matches_the_two_term_correlation():
    assert thermal.longitudinal_decay(0.0, 7.625) == pytest.approx(1.0)
    assert thermal.longitudinal_decay(15.0, 7.625) == pytest.approx(0.854, abs=0.01)
    assert thermal.longitudinal_decay(100.0, 7.625) == pytest.approx(0.430, abs=0.01)


def test_strong_stratification_at_tunnel_design_velocity():
    # Fr well below 0.9 -> breathing height stays near ambient
    f = thermal.stratification_factor(u_ms=4.5, height_m=7.625, ceiling_excess_k=950.0)
    assert f == pytest.approx(0.1, abs=0.001)


def test_mixed_regime_when_the_layer_is_cool_and_the_wind_is_strong():
    f = thermal.stratification_factor(u_ms=5.0, height_m=7.625, ceiling_excess_k=5.0)
    assert f == pytest.approx(1.0)


def test_alpert_ceiling_jet_gives_the_detection_threshold():
    # 30 K rise above a 30 C ambient trips a 60 C linear heat detector
    dt = thermal.alpert_ceiling_excess_k(hrr_kw=59.3, radius_m=0.0, height_m=H_EF)
    assert dt == pytest.approx(30.0, rel=0.05)


def test_heskestad_flame_length():
    assert thermal.heskestad_flame_length_m(50_000, 5.066) == pytest.approx(12.65, rel=0.05)


def test_bare_radiation_at_fifteen_metres_would_fail_the_gate():
    # the point-source flux alone exceeds the 5 kW/m2 upstream limit ...
    bare = thermal.point_source_flux_kwm2(50_000, 0.35, 15.0, transmissivity=1.0)
    assert bare > 5.0
    # ... and the mist curtain is what brings it under
    with_mist = thermal.point_source_flux_kwm2(50_000, 0.35, 15.0, transmissivity=0.55)
    assert with_mist < 5.0


def test_field_reports_breathing_height_temperatures_in_the_annex2_range():
    from solit2.engines.reduced.state import MistEffect
    from solit2.engines.reduced.ventilation import evaluate
    from solit2.engines.reduced import fire
    from solit2.schema.design import Design

    d = Design.load("designs/og-dbr-rev0.json")
    model = fire.build_model(d)
    st = fire.FireState(t_s=900.0, hrr_mw=50.0, hrr_free_mw=150.0,
                        energy_released_mj=30_000.0, suppression=0.33,
                        pools_remaining=0, wet_time_s=0.0)
    vent = evaluate(BORE, 4.5, fire.convective_kw(model, 50.0))
    f = thermal.field(BORE, model, st, vent, MistEffect.none(),
                      fire_top_m=4.0, fire_length_m=8.4, fire_width_m=2.4, ambient_c=30.0)
    # SOLIT2 Annex 2 suppressed Class A: D15 50-100 C, D100 50-65 C
    assert 50.0 < f.gas_temp_c(15.0, 1.8) < 130.0
    assert 40.0 < f.gas_temp_c(100.0, 1.8) < 90.0
    assert f.ceiling_temp_c(0.0) > 500.0


def test_stratification_blend_is_anchored_at_breathing_height():
    from solit2.engines.reduced.state import MistEffect
    from solit2.engines.reduced.ventilation import evaluate
    from solit2.engines.reduced import fire
    from solit2.schema.design import Design

    d = Design.load("designs/og-dbr-rev0.json")
    model = fire.build_model(d)
    st = fire.FireState(t_s=900.0, hrr_mw=50.0, hrr_free_mw=150.0,
                        energy_released_mj=30_000.0, suppression=0.33,
                        pools_remaining=0, wet_time_s=0.0)
    vent = evaluate(BORE, 4.5, fire.convective_kw(model, 50.0))
    f = thermal.field(BORE, model, st, vent, MistEffect.none(),
                      fire_top_m=4.0, fire_length_m=8.4, fire_width_m=2.4, ambient_c=30.0)

    x = 15.0
    excess = f.ceiling_temp_c(x) - f.ambient_c
    # Anchored at breathing height: the blend must equal strat_factor exactly there.
    assert f.gas_temp_c(x, 1.8) == pytest.approx(f.ambient_c + f.strat_factor * excess)
    # Anchored at the crown: the full excess arrives, matching the ceiling value.
    assert f.gas_temp_c(x, f.height_m) == pytest.approx(f.ceiling_temp_c(x))


def test_structure_exposure_length_is_zero_below_the_threshold_and_finite_above_it():
    """Annex 7 7.2.4 asks how much tunnel got hot, not how hot the hottest point got."""
    from solit2.engines.reduced.state import FireState, MistEffect
    from solit2.engines.reduced.ventilation import evaluate
    from solit2.engines.reduced import fire
    from solit2.schema.design import Design

    d = Design.load("designs/og-dbr-rev0.json")
    model = fire.build_model(d)

    def _field(hrr_mw):
        st = fire.FireState(t_s=900.0, hrr_mw=hrr_mw, hrr_free_mw=hrr_mw,
                            energy_released_mj=30_000.0, suppression=0.0,
                            pools_remaining=0, wet_time_s=0.0)
        vent = evaluate(BORE, 4.5, fire.convective_kw(model, hrr_mw))
        return thermal.field(BORE, model, st, vent, MistEffect.none(), fire_top_m=4.0,
                             fire_length_m=8.4, fire_width_m=2.4, ambient_c=30.0)

    threshold = 500.0
    span_m = 100.0 - -35.0 + thermal.STRUCTURE_SCAN_STEP_M
    cool, hot = _field(2.0), _field(30.0)
    assert cool.ceiling_temp_c(0.0) < threshold < hot.ceiling_temp_c(0.0)

    assert thermal.exposure_length_m(cool, threshold, -35.0, 100.0) == 0.0
    length = thermal.exposure_length_m(hot, threshold, -35.0, 100.0)
    assert 0.0 < length < span_m
    assert math.isfinite(length)


def test_structure_exposure_length_grows_with_the_fire():
    """A bigger fire holds more tunnel above the threshold, never less."""
    from solit2.engines.reduced.state import MistEffect
    from solit2.engines.reduced.ventilation import evaluate
    from solit2.engines.reduced import fire
    from solit2.schema.design import Design

    d = Design.load("designs/og-dbr-rev0.json")
    model = fire.build_model(d)
    lengths = []
    for hrr_mw in (30.0, 40.0, 50.0):
        st = fire.FireState(t_s=900.0, hrr_mw=hrr_mw, hrr_free_mw=hrr_mw,
                            energy_released_mj=30_000.0, suppression=0.0,
                            pools_remaining=0, wet_time_s=0.0)
        vent = evaluate(BORE, 4.5, fire.convective_kw(model, hrr_mw))
        f = thermal.field(BORE, model, st, vent, MistEffect.none(), fire_top_m=4.0,
                          fire_length_m=8.4, fire_width_m=2.4, ambient_c=30.0)
        lengths.append(thermal.exposure_length_m(f, 500.0, -35.0, 100.0))
    assert lengths == sorted(lengths)
    assert lengths[0] < lengths[-1]


def test_exposure_length_saturates_at_the_instrumented_span():
    """A known limit of the measure: the scan only walks between the outermost
    stations, so a big enough fire reads as the whole window rather than its
    true physical extent. The reported figure is a measurement, not a horizon."""
    from solit2.engines.reduced.state import MistEffect
    from solit2.engines.reduced.ventilation import evaluate
    from solit2.engines.reduced import fire
    from solit2.schema.design import Design

    d = Design.load("designs/og-dbr-rev0.json")
    model = fire.build_model(d)
    st = fire.FireState(t_s=900.0, hrr_mw=150.0, hrr_free_mw=150.0,
                        energy_released_mj=30_000.0, suppression=0.0,
                        pools_remaining=0, wet_time_s=0.0)
    vent = evaluate(BORE, 4.5, fire.convective_kw(model, 150.0))
    f = thermal.field(BORE, model, st, vent, MistEffect.none(), fire_top_m=4.0,
                      fire_length_m=8.4, fire_width_m=2.4, ambient_c=30.0)
    span_m = 100.0 - -35.0 + thermal.STRUCTURE_SCAN_STEP_M
    assert thermal.exposure_length_m(f, 500.0, -35.0, 100.0) == pytest.approx(span_m)


def test_exposure_length_rejects_a_non_positive_scan_step():
    with pytest.raises(ValueError) as exc:
        thermal.exposure_length_m(_ZERO_FIELD, 500.0, -35.0, 100.0, step_m=0.0)
    assert "0.0" in str(exc.value)


_ZERO_FIELD = thermal.ThermalField(
    ceiling_excess_k=0.0, strat_factor=0.1, ambient_c=30.0, height_m=7.625,
    hrr_kw=0.0, radiative_fraction=0.3, flame_centroid_z_m=4.0, flame_tip_x_m=0.0)

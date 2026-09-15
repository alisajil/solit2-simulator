import pytest
from solit2.schema.design import Design
from solit2.engines.reduced import fire
from solit2.engines.reduced.state import MistEffect

BASELINE = "examples/designs/road-tunnel-twin-bore.json"
POOL = "tests/fixtures/pool_design.json"


def _march(design, seconds, mist=None, dt=1.0):
    model = fire.build_model(design)
    st = fire.initial_state(model)
    effect = mist or MistEffect.none()
    out = [st]
    for _ in range(int(seconds / dt)):
        st = fire.step(model, st, dt, effect)
        out.append(st)
    return out


def test_class_a_free_burn_reaches_the_design_hrr():
    # ultrafast t-squared after 60 s incubation: 150 MW at ~60 + sqrt(150000/0.1876) = 954 s
    hist = _march(Design.load(BASELINE), 1200)
    at_954 = hist[954]
    assert at_954.hrr_free_mw == pytest.approx(150.0, rel=0.05)
    assert hist[100].hrr_free_mw < 1.0


def test_class_a_is_fuel_limited_and_decays():
    hist = _march(Design.load(BASELINE), 3600)
    peak = max(h.hrr_free_mw for h in hist)
    assert peak == pytest.approx(150.0, rel=0.02)
    assert hist[-1].hrr_free_mw < 5.0
    total_mj = hist[-1].energy_released_mj
    assert total_mj == pytest.approx(408 * 343, rel=0.05)


def test_suppression_pulls_the_peak_below_the_free_burn():
    mist = MistEffect(eta=0.72, w_fuel_mm_min=3.0, f_cov=0.9, chi_cool=0.35, tau_mist=0.6)
    hist = _march(Design.load(BASELINE), 3600, mist)
    assert max(h.hrr_mw for h in hist) < 0.45 * 150.0
    assert max(h.hrr_free_mw for h in hist) == pytest.approx(150.0, rel=0.02)


def test_covered_load_delays_suppression():
    mist = MistEffect(eta=0.72, w_fuel_mm_min=3.0, f_cov=0.9, chi_cool=0.35, tau_mist=0.6)
    d = Design.load(BASELINE)
    covered = d.model_copy(update={"fire": d.fire.model_copy(update={"covered": True})})
    bare_peak = max(h.hrr_mw for h in _march(d, 3600, mist))
    covered_peak = max(h.hrr_mw for h in _march(covered, 3600, mist))
    assert covered_peak > bare_peak


def test_class_b_pool_hrr_matches_the_nominal_sixty_megawatts():
    # 7 pools of 2.5 x 1.6 m diesel, Babrauskas with the fitted ventilation factor
    hist = _march(Design.load(POOL), 600)
    assert max(h.hrr_free_mw for h in hist) == pytest.approx(60.0, rel=0.15)


def test_class_b_pools_extinguish_one_by_one_under_mist():
    mist = MistEffect(eta=0.0, w_fuel_mm_min=3.0, f_cov=1.0, chi_cool=0.3, tau_mist=0.6)
    hist = _march(Design.load(POOL), 1200, mist)
    remaining = [h.pools_remaining for h in hist]
    assert remaining[0] == 7
    assert remaining[-1] == 0
    # strictly non-increasing, one at a time
    assert all(b - a in (0, -1) for a, b in zip(remaining, remaining[1:]))


def test_class_b_below_the_extinction_flux_never_goes_out():
    mist = MistEffect(eta=0.0, w_fuel_mm_min=0.5, f_cov=1.0, chi_cool=0.1, tau_mist=0.9)
    hist = _march(Design.load(POOL), 1200, mist)
    assert hist[-1].pools_remaining == 7


def test_mass_loss_and_convective_split():
    model = fire.build_model(Design.load(BASELINE))
    assert fire.radiative_fraction(model) == pytest.approx(0.35)
    assert fire.convective_kw(model, 100.0) == pytest.approx(65_000.0)
    # 100 MW of wood at 17.5 MJ/kg and 80 % combustion efficiency
    assert fire.mass_loss_rate_kgs(model, 100.0) == pytest.approx(7.14, rel=0.02)


def test_suppression_relaxes_symmetrically_when_eta_drops_to_zero():
    # Regression: suppression must relax toward its target in both directions.
    # Previously, `mist.eta == 0.0` forced suppression straight to 1.0 instead
    # of continuing the tau-based lag, discarding whatever level it had decayed
    # to the step before.
    model = fire.build_model(Design.load(BASELINE))
    st = fire.initial_state(model)
    suppressing = MistEffect(eta=0.72, w_fuel_mm_min=3.0, f_cov=0.9, chi_cool=0.35, tau_mist=0.6)
    for _ in range(600):
        st = fire.step(model, st, 1.0, suppressing)
    assert st.suppression < 0.5  # well decayed toward 1 - eta = 0.28 before mist stops
    before = st.suppression

    st = fire.step(model, st, 1.0, MistEffect.none())

    # a single 1 s step at tau=90 s moves it only slightly toward 1.0, not a jump
    assert st.suppression == pytest.approx(before, abs=0.02)
    assert st.suppression < 0.5

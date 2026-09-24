import math

import pytest

from solit2.engines.fds import calibrate
from validation.compare import Anchor, load_anchors

ANCHOR_IDS = ("c4", "c5")


@pytest.fixture(scope="module")
def anchors():
    return load_anchors(ANCHOR_IDS)


def test_run_dir_for_lays_out_anchor_e_and_dx(tmp_path):
    d = calibrate.run_dir_for(tmp_path, "c4", 0.25, 0.6)
    assert d == tmp_path / "c4" / "e_0.250_dx_0.60"


def test_write_decks_writes_one_deck_per_anchor_per_e(tmp_path, anchors):
    written = calibrate.write_decks(anchors, (0.2, 0.4), 0.6, tmp_path)
    assert len(written) == 4
    for path in written:
        assert path.exists()
        assert path.name == "deck.fds"


def test_write_decks_writes_design_json_beside_every_deck(tmp_path, anchors):
    from solit2.engines.fds.exec_run import DESIGN_NAME
    from solit2.schema.design import Design

    calibrate.write_decks(anchors, (0.2,), 0.6, tmp_path)
    for anchor in anchors:
        design_path = calibrate.run_dir_for(tmp_path, anchor.id, 0.2, 0.6) / DESIGN_NAME
        assert design_path.exists()
        assert Design.load(design_path) == anchor.design


def test_write_decks_carries_the_swept_e_into_the_deck(tmp_path, anchors):
    calibrate.write_decks(anchors, (0.2,), 0.6, tmp_path)
    for anchor in anchors:
        text = (calibrate.run_dir_for(tmp_path, anchor.id, 0.2, 0.6) / "deck.fds").read_text()
        assert "E_COEFFICIENT=0.2" in text


def test_write_decks_surfaces_a_bad_dx_as_the_generators_own_error(tmp_path, anchors):
    with pytest.raises(ValueError, match="does not tile"):
        calibrate.write_decks(anchors, (0.4,), 0.37, tmp_path)


def test_launch_and_wait_skips_a_point_already_done(tmp_path, anchors, monkeypatch):
    from solit2.engines.fds import runner as runner_mod
    calibrate.write_decks(anchors, (0.2, 0.4), 0.6, tmp_path)
    launched = []
    monkeypatch.setattr(runner_mod, "status", lambda d: {"state": "done"})
    monkeypatch.setattr(runner_mod, "run", lambda deck, out: launched.append(out))
    calibrate.launch_and_wait(anchors, (0.2, 0.4), 0.6, tmp_path, poll_s=0.0)
    assert launched == []


def test_launch_and_wait_launches_and_waits_for_each_point(tmp_path, anchors, monkeypatch):
    from solit2.engines.fds import runner as runner_mod
    calibrate.write_decks(anchors, (0.2,), 0.6, tmp_path)
    launched = []
    # every point is "running" once, then "done": proves the wait loop polls
    calls = {"n": 0}

    def fake_status(run_dir):
        calls["n"] += 1
        return {"state": "done"} if calls["n"] % 2 == 0 else {"state": "running"}
    monkeypatch.setattr(runner_mod, "status", fake_status)
    monkeypatch.setattr(runner_mod, "run", lambda deck, out: launched.append(out))
    calibrate.launch_and_wait(anchors, (0.2,), 0.6, tmp_path, poll_s=0.0)
    assert len(launched) == len(anchors)


def test_read_points_excludes_a_run_that_has_not_completed(tmp_path, anchors, monkeypatch):
    from solit2.engines.fds import runner as runner_mod
    calibrate.write_decks(anchors, (0.2,), 0.6, tmp_path)
    monkeypatch.setattr(runner_mod, "status",
                        lambda d: {"state": "running", "detail": "40%"})
    points = calibrate.read_points(anchors, (0.2,), 0.6, tmp_path)
    assert all(not p.included for p in points)
    assert all("not completed: running" in p.excluded_reason for p in points)


def test_read_points_excludes_a_run_whose_peak_did_not_pass(tmp_path, anchors, monkeypatch):
    from solit2.engines.fds import reader as reader_mod
    from solit2.engines.fds import runner as runner_mod
    calibrate.write_decks(anchors, (0.2,), 0.6, tmp_path)
    monkeypatch.setattr(runner_mod, "status", lambda d: {"state": "done"})

    class _Fake:
        peaks = {"hrr_mw": 12.0, "hrr_peak_passed": False}
    monkeypatch.setattr(reader_mod, "read", lambda run_dir, design, **kw: _Fake())
    points = calibrate.read_points(anchors, (0.2,), 0.6, tmp_path)
    assert all(not p.included for p in points)
    assert all("peak was not passed" in p.excluded_reason for p in points)


def test_read_points_includes_a_completed_passed_run(tmp_path, anchors, monkeypatch):
    from solit2.engines.fds import reader as reader_mod
    from solit2.engines.fds import runner as runner_mod
    calibrate.write_decks(anchors, (0.2,), 0.6, tmp_path)
    monkeypatch.setattr(runner_mod, "status", lambda d: {"state": "done"})

    class _Fake:
        peaks = {"hrr_mw": 25.0, "hrr_peak_passed": True}
    monkeypatch.setattr(reader_mod, "read", lambda run_dir, design, **kw: _Fake())
    points = calibrate.read_points(anchors, (0.2,), 0.6, tmp_path)
    assert all(p.included and p.modelled_peak_hrr_mw == 25.0 for p in points)


def test_read_points_excludes_a_run_the_reader_cannot_parse(tmp_path, anchors, monkeypatch):
    from solit2.engines.fds import reader as reader_mod
    from solit2.engines.fds import runner as runner_mod
    calibrate.write_decks(anchors, (0.2,), 0.6, tmp_path)
    monkeypatch.setattr(runner_mod, "status", lambda d: {"state": "done"})

    def raising(run_dir, design, **kw):
        raise ValueError("the FDS run's heat detectors never tripped")
    monkeypatch.setattr(reader_mod, "read", raising)
    points = calibrate.read_points(anchors, (0.2,), 0.6, tmp_path)
    assert all("could not be read" in p.excluded_reason for p in points)


def test_weighted_error_by_e_averages_across_anchors_by_weight():
    a1 = Anchor("a1", 1.0, "test", None, {"peak_hrr_mw": 10.0}, {})
    a2 = Anchor("a2", 3.0, "test", None, {"peak_hrr_mw": 20.0}, {})
    points = [calibrate.SweepPoint("a1", 0.4, 0.6, None, modelled_peak_hrr_mw=11.0),   # +10%
             calibrate.SweepPoint("a2", 0.4, 0.6, None, modelled_peak_hrr_mw=22.0)]   # +10%
    errors = calibrate.weighted_error_by_e((a1, a2), points)
    assert errors[0.4] == pytest.approx(0.01)   # both anchors read the same 10% error


def test_weighted_error_by_e_skips_e_values_with_no_included_point():
    a1 = Anchor("a1", 1.0, "test", None, {"peak_hrr_mw": 10.0}, {})
    points = [calibrate.SweepPoint("a1", 0.2, 0.6, None, excluded_reason="not completed")]
    assert calibrate.weighted_error_by_e((a1,), points) == {}


def test_best_e_recovers_the_exact_minimum_of_a_quadratic_error_curve():
    # error(E) = (ln E - ln E0)^2 is exactly quadratic in ln(E): the two
    # secant slopes bracketing its minimum are exact samples of its (linear)
    # derivative, so the linear interpolation between them recovers E0 exactly
    e0 = 0.3
    es = (0.1, 0.2, 0.4, 0.8)
    errors = {e: (math.log(e) - math.log(e0)) ** 2 for e in es}
    fit = calibrate.best_e(errors)
    assert fit.best_e == pytest.approx(e0, rel=1e-9)
    assert fit.reason is None


def test_best_e_refuses_to_extrapolate_past_a_sampled_end():
    # monotonically decreasing error: the minimum sits at the LAST sampled E
    errors = {0.1: 5.0, 0.2: 3.0, 0.4: 1.0, 0.8: 0.2}
    fit = calibrate.best_e(errors)
    assert fit.best_e is None
    assert "sampled end" in fit.reason


def test_best_e_with_no_data_names_the_reason():
    fit = calibrate.best_e({})
    assert fit.best_e is None and "no sampled E" in fit.reason


def test_render_lists_excluded_points_with_their_reasons():
    a1 = Anchor("a1", 1.0, "test source", None, {"peak_hrr_mw": 10.0}, {})
    points = [calibrate.SweepPoint("a1", 0.2, 0.6, None,
                                   excluded_reason="not completed: running (40%)"),
             calibrate.SweepPoint("a1", 0.4, 0.6, None, modelled_peak_hrr_mw=10.5)]
    errors = calibrate.weighted_error_by_e((a1,), points)
    fit = calibrate.best_e(errors)
    text = calibrate.render((a1,), points, errors, fit, 0.6)
    assert "not completed: running (40%)" in text
    assert "test source" in text
    assert "dx = 0.60 m" in text
    assert "applies at this dx only" in text


def test_render_says_no_best_e_when_unbracketed():
    a1 = Anchor("a1", 1.0, "test", None, {"peak_hrr_mw": 10.0}, {})
    points = [calibrate.SweepPoint("a1", e, 0.6, None, modelled_peak_hrr_mw=10.0 + e)
             for e in (0.2, 0.4, 0.8)]
    errors = calibrate.weighted_error_by_e((a1,), points)
    fit = calibrate.best_e(errors)
    text = calibrate.render((a1,), points, errors, fit, 0.6)
    assert "No best E is reported" in text
    assert "does not adopt it" not in text  # only printed when a fit exists


def test_to_json_never_writes_a_fitted_e_anywhere_but_the_fit_block():
    a1 = Anchor("a1", 1.0, "test", None, {"peak_hrr_mw": 10.0}, {})
    points = [calibrate.SweepPoint("a1", e, 0.6, None, modelled_peak_hrr_mw=10.0 * (1 + 0.01 * i))
             for i, e in enumerate((0.1, 0.2, 0.4, 0.8))]
    errors = calibrate.weighted_error_by_e((a1,), points)
    fit = calibrate.best_e(errors)
    payload = calibrate.to_json((a1,), points, errors, fit, 0.6)
    assert payload["dx_m"] == 0.6
    assert payload["fit"]["best_e"] == fit.best_e
    assert len(payload["points"]) == 4

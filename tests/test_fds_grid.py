import pytest

from solit2.engines.fds import grid
from solit2.schema.design import Design

BASELINE = "designs/og-dbr-rev0.json"


def _quadratic(h: float, phi0: float = 100.0, c: float = 5.0) -> float:
    """phi = phi0 + C h^2 -- a synthetic curve whose true apparent order is
    exactly 2 and whose Richardson extrapolation is exactly phi0, so the GCI
    math can be checked against a known answer rather than a citation."""
    return phi0 + c * h ** 2


def test_gci_recovers_the_known_order_and_extrapolation_of_a_quadratic_curve():
    h1, h2, h3 = 0.5, 0.8, 1.3       # non-uniform refinement: r21 != r32
    result = grid.gci("phi", h1, h2, h3,
                      _quadratic(h1), _quadratic(h2), _quadratic(h3))
    assert result.status == "ok"
    assert result.p == pytest.approx(2.0, abs=1e-5)
    assert result.phi_ext21 == pytest.approx(100.0, abs=1e-5)
    assert result.gci_fine21 > 0.0


def test_gci_matches_on_a_uniform_refinement_too():
    h1, h2, h3 = 0.6, 1.2, 2.4       # r21 == r32 == 2
    result = grid.gci("phi", h1, h2, h3,
                      _quadratic(h1), _quadratic(h2), _quadratic(h3))
    assert result.p == pytest.approx(2.0, abs=1e-6)
    assert result.phi_ext21 == pytest.approx(100.0, abs=1e-6)


def test_gci_reports_oscillatory_convergence_instead_of_a_number():
    # the change reverses sign between grid pairs: e21 = +2, e32 = -1
    result = grid.gci("phi", 0.5, 0.8, 1.3, 10.0, 12.0, 11.0)
    assert result.status == "oscillatory"
    assert result.p is None and result.gci_fine21 is None and result.phi_ext21 is None
    assert "reverses sign" in result.detail


def test_gci_reports_non_convergence_rather_than_a_number():
    # both grid pairs read EXACTLY the same value: no change to estimate an
    # order from
    result = grid.gci("phi", 0.5, 0.8, 1.3, 10.0, 10.0, 10.0)
    assert result.status == "non_convergent"
    assert result.p is None
    assert "zero" in result.detail.lower()


def test_gci_refuses_grids_out_of_order():
    with pytest.raises(ValueError, match="h1 < h2 < h3"):
        grid.gci("phi", 1.3, 0.8, 0.5, 1.0, 1.0, 1.0)


def test_compute_all_needs_exactly_three_usable_grids():
    points = [grid.GridPoint(0.6, None, peaks={"hrr_mw": 10.0}),
             grid.GridPoint(0.75, None, excluded_reason="not completed: running")]
    with pytest.raises(ValueError, match="needs exactly 3"):
        grid.compute_all(points)


def test_compute_all_only_uses_quantities_every_grid_carries():
    points = [
        grid.GridPoint(0.5, None, peaks={"hrr_mw": _quadratic(0.5), "ceiling_temp_c": 1.0}),
        grid.GridPoint(0.8, None, peaks={"hrr_mw": _quadratic(0.8)}),   # no ceiling_temp_c
        grid.GridPoint(1.3, None, peaks={"hrr_mw": _quadratic(1.3), "ceiling_temp_c": 3.0}),
    ]
    results = grid.compute_all(points)
    assert [r.quantity for r in results] == ["hrr_mw"]
    assert results[0].p == pytest.approx(2.0, abs=1e-5)


def test_write_decks_lays_out_one_deck_per_dx_under_the_designs_chid(tmp_path):
    from solit2.engines.fds import deck as deck_mod
    design = Design.load(BASELINE)
    written = grid.write_decks(design, (1.2, 0.75, 0.6), 300.0, tmp_path)
    chid = deck_mod.chid(design)
    for dx in (1.2, 0.75, 0.6):
        expected = tmp_path / chid / f"dx_{dx:.2f}" / "deck.fds"
        assert expected in written
        assert expected.exists()
        assert "T_END=300.0" in expected.read_text()


def test_write_decks_surfaces_a_bad_dx_as_the_generators_own_error(tmp_path):
    design = Design.load(BASELINE)
    with pytest.raises(ValueError, match="does not tile"):
        grid.write_decks(design, (0.37,), 300.0, tmp_path)


def test_read_grids_excludes_unfinished_and_unreadable_runs(tmp_path, monkeypatch):
    from solit2.engines.fds import deck as deck_mod
    from solit2.engines.fds import runner as runner_mod
    design = Design.load(BASELINE)
    grid.write_decks(design, (1.2, 0.6), 300.0, tmp_path)

    def fake_status(run_dir):
        return {"state": "done"} if "dx_0.60" in str(run_dir) else {"state": "running",
                                                                     "detail": "42%"}
    monkeypatch.setattr(runner_mod, "status", fake_status)

    def fake_read(run_dir, d):
        raise ValueError("the FDS run's heat detectors never tripped")
    monkeypatch.setattr("solit2.engines.fds.reader.read", fake_read)

    points = grid.read_grids(design, (1.2, 0.6), tmp_path)
    by_dx = {p.dx_m: p for p in points}
    assert by_dx[1.2].peaks is None and "running" in by_dx[1.2].excluded_reason
    assert by_dx[0.6].peaks is None and "never tripped" in by_dx[0.6].excluded_reason


def test_render_reports_no_gci_when_grids_are_missing():
    points = [grid.GridPoint(0.6, None, peaks={"hrr_mw": 10.0}),
             grid.GridPoint(0.75, None, excluded_reason="not completed: running")]
    text = grid.render(points, 300.0)
    assert "No discretisation uncertainty could be computed" in text
    assert "needs exactly 3" in text


def test_render_and_json_agree_on_a_clean_three_grid_study():
    points = [grid.GridPoint(h, None, peaks={"hrr_mw": _quadratic(h)})
             for h in (0.5, 0.8, 1.3)]
    text = grid.render(points, 300.0)
    assert "hrr_mw" in text and "2" in text
    payload = grid.to_json(points, 300.0)
    assert payload["results"][0]["quantity"] == "hrr_mw"
    assert payload["results"][0]["p"] == pytest.approx(2.0, abs=1e-5)
    assert payload["t_end_s"] == 300.0

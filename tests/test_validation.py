from validation import compare


def test_the_anchor_set_is_exactly_the_solit2_guidance_tests():
    """The APPLUS+TST cases (c1-c3) are a different vendor's campaign on a
    different nozzle; the validation basis is the SOLIT2 guidance tests only."""
    anchors = compare.load_anchors()
    assert {a.id for a in anchors} == {"c4", "c5", "c6"}
    assert all(a.source for a in anchors)


def test_every_solit2_anchor_carries_full_weight():
    by_id = {a.id: a for a in compare.load_anchors()}
    assert [by_id[i].weight for i in ("c4", "c5", "c6")] == [1.0, 1.0, 1.0]


def test_anchor_designs_all_build_and_run():
    for anchor in compare.load_anchors():
        report = compare.check(anchor)
        assert report.rows, f"{anchor.id} produced no comparison rows"


def test_report_rows_carry_modelled_and_measured_values():
    report = compare.check(next(a for a in compare.load_anchors() if a.id == "c4"))
    quantities = {r[0] for r in report.rows}
    assert "peak_ceiling_temp_c" in quantities
    assert "peak_hrr_mw" in quantities
    for _, modelled, measured, _, ok in report.rows:
        assert isinstance(modelled, (int, float, bool))
        assert isinstance(measured, (int, float, bool))
        assert isinstance(ok, bool)


def test_every_anchor_quantity_has_a_live_extractor():
    """A quantity whose extractor was pinned to a deleted criterion would only
    blow up at `check` time, so assert the wiring directly."""
    for anchor in compare.load_anchors():
        for quantity in anchor.measured:
            assert quantity in compare.EXTRACTORS, f"{anchor.id} wants {quantity!r}"


def test_residuals_are_finite_and_weighted():
    residuals = compare.residuals(compare.load_anchors())
    assert residuals
    assert all(abs(r) < 1e6 for r in residuals)


def test_tolerance_kinds():
    assert compare.within(10.0, 10.4, {"kind": "relative", "value": 0.05})
    assert not compare.within(10.0, 12.0, {"kind": "relative", "value": 0.05})
    assert compare.within(10.0, 20.0, {"kind": "factor", "value": 2.0})
    assert not compare.within(10.0, 25.0, {"kind": "factor", "value": 2.0})
    assert compare.within(10.0, 14.0, {"kind": "absolute", "value": 5.0})
    assert compare.within(True, True, {"kind": "exact"})
    assert not compare.within(True, False, {"kind": "exact"})

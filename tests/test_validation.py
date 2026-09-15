from validation import compare


def test_every_anchor_file_loads_and_declares_a_source():
    anchors = compare.load_anchors()
    assert len(anchors) >= 4
    ids = {a.id for a in anchors}
    assert {"c3", "c4", "c5", "c6"} <= ids
    assert all(a.source for a in anchors)
    assert all(0.0 < a.weight <= 1.0 for a in anchors)


def test_solit2_anchors_are_down_weighted():
    by_id = {a.id: a for a in compare.load_anchors()}
    assert by_id["c3"].weight == 1.0
    assert by_id["c4"].weight == 0.5
    assert by_id["c6"].weight == 0.5


def test_anchor_designs_all_build_and_run():
    for anchor in compare.load_anchors():
        report = compare.check(anchor)
        assert report.rows, f"{anchor.id} produced no comparison rows"


def test_report_rows_carry_modelled_and_measured_values():
    report = compare.check(next(a for a in compare.load_anchors() if a.id == "c3"))
    quantities = {r[0] for r in report.rows}
    assert "peak_ceiling_temp_c" in quantities
    assert "u35_temp_c" in quantities
    for _, modelled, measured, _, ok in report.rows:
        assert isinstance(modelled, (int, float, bool))
        assert isinstance(measured, (int, float, bool))
        assert isinstance(ok, bool)


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

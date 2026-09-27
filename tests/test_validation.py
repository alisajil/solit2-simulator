from dataclasses import dataclass

import pytest

from solit2.engines.reduced import envelope
from validation import compare


@dataclass(frozen=True)
class _FakeResult:
    """Just enough of a `Result` for the extractors to read."""
    timeseries: dict
    peaks: dict


def _trace_with_distinct_stations() -> _FakeResult:
    """Every station carries a different value, and the peaks block carries
    values that disagree with all of them, so an extractor reading the wrong
    series cannot accidentally return the right number."""
    return _FakeResult(
        timeseries={
            "u45_temp_c": [10.0, 45.0],
            "u15_temp_c": [10.0, 15.0],
            "d15_temp_c": [10.0, 75.0],
            "d100_temp_c": [10.0, 100.0],
            "hf_u15_kwm2": [0.1, 0.5],
            "hf_d15_kwm2": [0.2, 2.5],
        },
        peaks={"smoke_layer_temp_d15_c": 999.0, "smoke_layer_temp_d100_c": 888.0},
    )


def test_each_temperature_extractor_reads_its_own_station():
    """Test 6. `u15_temp_c` read the 35 m series and `d100_temp_c` read the
    peaks block rather than the station's own series; both now read the series
    named for the station they report."""
    fake = _trace_with_distinct_stations()
    assert compare.EXTRACTORS["u15_temp_c"](fake) == 15.0
    assert compare.EXTRACTORS["d15_temp_c"](fake) == 75.0
    assert compare.EXTRACTORS["d100_temp_c"](fake) == 100.0


def test_the_heat_flux_extractor_reads_the_downstream_station():
    """Task 17 test 6. `hf_d15_kwm2` read `max(timeseries["hf_u15_kwm2"])` --
    the UPSTREAM station's flux reported as a downstream quantity, the wrong
    side of the fire entirely. The two series are given different values here so
    an extractor reading the upstream one cannot return the right number by
    luck. `hf_u15_kwm2` has no extractor of its own because no anchor measures
    upstream flux; what is asserted is that the downstream extractor reads the
    downstream series and not the other one.
    """
    fake = _trace_with_distinct_stations()
    assert fake.timeseries["hf_u15_kwm2"] != fake.timeseries["hf_d15_kwm2"]
    assert compare.EXTRACTORS["hf_d15_kwm2"](fake) == 2.5
    assert compare.EXTRACTORS["hf_d15_kwm2"](fake) != max(fake.timeseries["hf_u15_kwm2"])


def test_the_result_timeseries_carries_every_station_an_extractor_needs():
    """The extractors above are only correct if the series actually exist and
    are drawn from the stations they are named for.

    Run on c6 because its pre-activation backlayer reaches U15 and stops short
    of U45 (Annex 2 Figure 29), so the two upstream series genuinely differ.
    c4 no longer serves: with the fire it was tested with, its layer never
    reaches U15, and both stations read ambient throughout -- as Figure 11 says
    the test's did.
    """
    from solit2.engines.reduced import sim

    design = compare.load_anchors(("c6",))[0].design
    trace = sim.run_once(design, "test", design.ventilation.velocity_ms)
    sampled = trace.steps[::envelope.TIMESERIES_STRIDE_S]
    series = envelope._timeseries(sampled)

    assert series["u15_temp_c"] == [s.stations["U15"].temp_c for s in sampled]
    assert series["d100_temp_c"] == [s.stations["D100"].temp_c for s in sampled]
    assert series["hf_u15_kwm2"] == [s.stations["U15"].flux_kwm2 for s in sampled]
    assert series["hf_d15_kwm2"] == [s.stations["D15"].flux_kwm2 for s in sampled]
    assert series["u15_temp_c"] != series["u45_temp_c"], (
        "the 15 m and 45 m upstream stations must not report the same series")


def test_the_anchor_set_is_exactly_the_solit2_guidance_tests():
    """The retired cases c1-c3 were a different manufacturer's campaign on a
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


# --- Annex 7 section 7.2.1: the target outcome as an anchored quantity -------

def test_the_target_ignited_extractor_reads_the_trace_not_a_criterion():
    """Every extractor reads the trace or the peaks, never a criterion -- an
    authority can switch a criterion off, and an anchor must not stop working
    when it does. `target_ignited` is reconstructed from the two peaks the run
    already records, against the same two thresholds `criteria` uses."""
    from solit2.engines.reduced.criteria import (FLAME_CONTACT_FLUX_KWM2,
                                                 IGNITION_EXPOSURE_S)

    quiet = _FakeResult(timeseries={}, peaks={
        "target_peak_flux_kwm2": FLAME_CONTACT_FLUX_KWM2 - 1.0,
        "target_max_exposure_s": IGNITION_EXPOSURE_S - 1.0})
    contact = _FakeResult(timeseries={}, peaks={
        "target_peak_flux_kwm2": FLAME_CONTACT_FLUX_KWM2,
        "target_max_exposure_s": 0.0})
    sustained = _FakeResult(timeseries={}, peaks={
        "target_peak_flux_kwm2": 13.0,
        "target_max_exposure_s": IGNITION_EXPOSURE_S})

    assert compare.EXTRACTORS["target_ignited"](quiet) is False
    assert compare.EXTRACTORS["target_ignited"](contact) is True
    assert compare.EXTRACTORS["target_ignited"](sustained) is True


def test_a_boolean_target_ignited_compares_and_scores_both_ways():
    """A measured `false` matches a modelled `false` and fails against a modelled
    `true`, and the residual is 0 or the anchor weight accordingly -- the same
    path `backlayering` already takes."""
    exact = {"kind": "exact"}
    assert compare.within(False, False, exact)
    assert not compare.within(False, True, exact)
    assert compare.within(True, True, exact)
    assert not compare.within(True, False, exact)


def test_the_class_a_anchors_carry_a_target_outcome_and_the_class_b_one_does_not():
    """Annex 7 section 5.2.6: "Fire target shall be used with Class A fires."
    There is no target in a Class B pool-fire test, so c6 must not claim one.
    c4 and c5 are the Class A tests and carry the section 7.2.1 pass condition.
    """
    by_id = {a.id: a for a in compare.load_anchors()}
    for anchor_id in ("c4", "c5"):
        assert by_id[anchor_id].measured["target_ignited"] is False
        assert by_id[anchor_id].tolerances["target_ignited"] == {"kind": "exact"}
    assert "target_ignited" not in by_id["c6"].measured
    assert by_id["c6"].design.fire.fire_class == "B"


def test_backlayering_is_judged_where_the_tests_judged_it():
    """Annex 2 reads backlayering off the U15 thermocouple tree (Figures 11, 20
    and 29). A 3 m layer that never leaves the mock-up is not what those tests
    could have seen; one that reaches 15 m is."""
    from types import SimpleNamespace

    def result(length_m):
        return SimpleNamespace(events={"backlayering": {"occurred": length_m > 0,
                                                         "max_length_m": length_m}})

    judge = compare.EXTRACTORS["backlayering"]
    assert judge(result(3.0)) is False
    assert judge(result(15.0)) is True
    assert judge(result(0.0)) is False


def test_no_reference_nozzle_ships_with_the_tool():
    from solit2.schema.presets import list_presets
    assert "solit2_reference" not in list_presets("nozzle")


def test_anchors_refuse_without_a_tester_supplied_reference_nozzle(monkeypatch, tmp_path):
    monkeypatch.setenv("SOLIT2_REFERENCE_NOZZLE", str(tmp_path / "absent.json"))
    with pytest.raises(compare.ReferenceNozzleMissing, match="SOLIT2 reference test nozzle"):
        compare.load_anchors()


def test_anchor_designs_carry_the_testers_reference_nozzle():
    nozzle = compare.load_reference_nozzle()
    for anchor in compare.load_anchors():
        assert anchor.design.nozzles.k_factor_lpm_bar05 == nozzle["k_factor_lpm_bar05"]
        assert anchor.design.nozzles.spread_n("fine") == pytest.approx(2.5, abs=1e-6)


def test_a_reference_nozzle_without_a_spectrum_is_refused(monkeypatch, tmp_path):
    import json
    import os
    from pathlib import Path

    from solit2.schema.design import MissingNozzleData
    # the autouse conftest fixture points this at the labelled test fixture
    raw = json.loads(Path(os.environ["SOLIT2_REFERENCE_NOZZLE"]).read_text())
    for mode in raw["modes"]:
        mode.pop("dv50_um"), mode.pop("dv90_um")
    path = tmp_path / "no-spectrum.json"
    path.write_text(json.dumps(raw))
    monkeypatch.setenv("SOLIT2_REFERENCE_NOZZLE", str(path))
    with pytest.raises(MissingNozzleData, match="Dv50 and Dv90"):
        compare.load_anchors()

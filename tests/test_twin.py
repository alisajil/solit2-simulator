"""The twin keeps the system under test and takes everything else from Annex 7."""
import json

import pytest

from solit2.engines.reduced import envelope
from solit2.reports import twin
from solit2.schema.design import Design

EXAMPLE = "examples/designs/road-tunnel-twin-bore.json"
# Test values for the conditions Annex 7 leaves to the AHJ or the test day.
INPUTS = twin.Annex7Inputs("A", activation_s=150.0, ambient_c=20.0, ambient_rh_pct=60.0,
                           growth_alpha_kw_s2=0.1876, incubation_s=243.0)


def _inputs(fire_class: str = "A", activation_s: float = 150.0) -> twin.Annex7Inputs:
    return twin.Annex7Inputs(fire_class, activation_s, 20.0, 60.0, 0.1876, 243.0)


def _design_with_mount(height_m: float) -> Design:
    raw = json.loads(open(EXAMPLE).read())
    raw["nozzles"]["mounting"] = {**raw["nozzles"].get("mounting", {}),
                                  "height_above_carriageway_m": height_m}
    return Design.from_dict(raw)


def _without_mount(block: dict) -> dict:
    return {k: v for k, v in block.items() if k != "mounting"}


def test_twin_keeps_the_testers_system_and_carries_it_into_the_gallery():
    site = _design_with_mount(4.5)
    t = twin.test_facility_twin(site, INPUTS)
    assert t.tunnel.preset == twin.GALLERY_TUNNEL and t.tunnel.section == "test"
    assert _without_mount(t.nozzles.model_dump(mode="json", by_alias=True)) == \
        _without_mount(site.nozzles.model_dump(mode="json", by_alias=True))
    assert t.hydraulics.model_dump(mode="json") == site.hydraulics.model_dump(mode="json")
    assert t.detection.model_dump(mode="json") == site.detection.model_dump(mode="json")
    assert (t.zones.section_length_m, t.zones.sections_simultaneous, t.zones.pump_ramp_s) == \
        (site.zones.section_length_m, site.zones.sections_simultaneous, site.zones.pump_ramp_s)
    assert t.ahj.model_dump(mode="json") == site.ahj.model_dump(mode="json")
    assert t.meta.name == f"{site.meta.name}-annex7-class-a"


def test_twin_takes_the_annex7_mockup_not_the_sites_fire():
    t = twin.test_facility_twin(_design_with_mount(4.5), INPUTS)
    assert t.fire.preset == "hgv_150mw" and t.fire.design_hrr_mw == 150.0
    assert t.fire.covered is True
    assert tuple(t.ventilation.velocity_range_ms) == (1.5, 3.0)
    assert t.zones.manual_activation_s == 150.0 and t.zones.activation_delay_s == 0.0
    assert t.zones.duration_min >= (150.0 + 30 * 60) / 60
    assert (t.tunnel.ambient_temp_c, t.tunnel.ambient_rh_pct) == (20.0, 60.0)
    assert t.fire.alpha == 0.1876 and t.fire.incubation_s == 243.0


def test_class_b_takes_the_annex7_pool_mockup():
    t = twin.test_facility_twin(_design_with_mount(4.5), _inputs("B", 100.0))
    assert t.fire.preset == "pool_60mw" and t.fire.covered is False
    assert t.zones.manual_activation_s == 100.0


def test_class_a_activation_before_one_minute_is_refused():
    with pytest.raises(ValueError, match="5.2.8"):
        twin.test_facility_twin(_design_with_mount(4.5), _inputs("A", 45.0))


def test_class_b_activation_after_two_minutes_is_refused():
    with pytest.raises(ValueError, match="5.3.7"):
        twin.test_facility_twin(_design_with_mount(4.5), _inputs("B", 150.0))


def test_activation_area_shorter_than_three_mockups_is_refused():
    site = _design_with_mount(4.5)
    short = site.model_copy(update={"zones": site.zones.model_copy(
        update={"section_length_m": 8.0, "sections_simultaneous": 1})})
    with pytest.raises(ValueError, match="3 times the length"):
        twin.test_facility_twin(short, INPUTS)


def test_a_site_height_that_fits_the_gallery_is_kept():
    height, reason = twin.gallery_mount_height_m(_design_with_mount(4.5), 4.0)
    assert height == 4.5 and "own" in reason


def test_a_site_height_above_the_gallery_ceiling_is_refused_not_substituted():
    """SOLIT2 publishes no mounting height for its reference system, so there is
    no standard value to put the heads at instead; the tester must enter one."""
    with pytest.raises(ValueError, match="enter the height the heads will be tested at"):
        twin.gallery_mount_height_m(_design_with_mount(6.5), 4.0)


def test_the_twin_validates_and_runs_in_tier_one():
    result = envelope.run(twin.test_facility_twin(_design_with_mount(4.5), INPUTS))
    assert result.meta["design_name"].endswith("-annex7-class-a")
    assert result.worst_case["velocity_ms"] in (1.5, 3.0)


@pytest.mark.xfail(strict=True, raises=AssertionError, reason=(
    "Since located cooling (#9) the mist cannot put this pool out: water on the fuel is "
    "1.13 mm/min against the 1.38 extinction flux, and the flame loses 7 % of its heat "
    "against the 29 % extinction fraction. A Class B pool carries no fuel inventory "
    "(fire_pool_60mw.json declares none), so an unextinguished pool burns at its full "
    "57 MW for the whole horizon. This is the same miss `solit2 validate` reports for c6 "
    "(pools_extinguished). Remove the mark when pool extinction or a pool fuel inventory "
    "is modelled -- never by lowering either threshold to pass it."))
def test_class_b_horizon_covers_the_whole_fire():
    """5.3.7 runs Class B until the fire is out or the fuel is gone; the run
    horizon is only how long the engine runs, so it must reach that point."""
    from solit2.engines.reduced.sim import run_once
    t = twin.test_facility_twin(_design_with_mount(4.5), _inputs("B", 100.0))
    trace = run_once(t, "test", 3.0)
    assert trace.steps[-1].hrr_mw < 0.01 * max(s.hrr_mw for s in trace.steps)

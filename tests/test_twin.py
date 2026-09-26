"""The twin keeps the system under test and swaps everything else for the Annex 7 gallery."""
import json

import pytest

from solit2.engines.reduced import envelope
from solit2.reports import twin
from solit2.schema.design import Design

EXAMPLE = "examples/designs/road-tunnel-twin-bore.json"


def _design_with_mount(height_m: float) -> Design:
    raw = json.loads(open(EXAMPLE).read())
    raw["nozzles"]["mounting"] = {**raw["nozzles"].get("mounting", {}),
                                  "height_above_carriageway_m": height_m}
    return Design.from_dict(raw)


def _without_mount(block: dict) -> dict:
    return {k: v for k, v in block.items() if k != "mounting"}


def test_twin_keeps_nozzles_and_hydraulics_and_swaps_in_the_gallery_protocol():
    site = _design_with_mount(4.5)
    t = twin.test_facility_twin(site)
    assert t.tunnel.preset == twin.GALLERY_TUNNEL and t.tunnel.section == "test"
    assert t.fire.covered is True and t.fire.preset == site.fire.preset
    assert t.ventilation.velocity_range_ms == (1.5, 3.0) or list(t.ventilation.velocity_range_ms) == [1.5, 3.0]
    assert (t.zones.section_length_m, t.zones.sections_simultaneous, t.zones.duration_min) == (20.0, 3, 35.0)
    assert t.detection.sensor_spacing_m == 12.0
    assert _without_mount(t.nozzles.model_dump(mode="json", by_alias=True)) == \
        _without_mount(site.nozzles.model_dump(mode="json", by_alias=True))
    assert t.hydraulics.model_dump(mode="json") == site.hydraulics.model_dump(mode="json")
    assert t.ahj.model_dump(mode="json") == site.ahj.model_dump(mode="json")
    assert t.meta.name == f"{site.meta.name}-test-facility"


def test_a_site_height_that_fits_the_gallery_is_kept():
    height, reason = twin.gallery_mount_height_m(_design_with_mount(4.5))
    assert height == 4.5 and "site's own" in reason


def test_a_site_height_above_the_gallery_ceiling_falls_back_to_the_reference_tests():
    site = _design_with_mount(6.5)
    height, reason = twin.gallery_mount_height_m(site)
    assert height == 4.9 and "reference" in reason
    t = twin.test_facility_twin(site)
    assert t.nozzles.mounting.height_above_carriageway_m == 4.9
    assert "4.90 m" in t.meta.notes and "6.50 m" in t.meta.notes


def test_the_twin_validates_and_runs_in_tier_one():
    result = envelope.run(twin.test_facility_twin(_design_with_mount(6.5)))
    assert result.meta["design_name"].endswith("-test-facility")
    assert result.worst_case["velocity_ms"] in (1.5, 3.0)


def test_an_impossible_gallery_raises_instead_of_clamping(monkeypatch):
    # a fuel taller than the reference mounting height leaves no valid height
    site = _design_with_mount(6.5)
    monkeypatch.setattr(twin, "load_preset", lambda kind, name: (
        {"height_m": 5.2} if kind == "tunnel" else {"mounting": {"height_above_carriageway_m": 3.5}}))
    with pytest.raises(ValueError, match="gallery"):
        twin.gallery_mount_height_m(site)

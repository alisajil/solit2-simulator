"""The test-facility twin: one design's nozzle system, as Annex 7 would test it.

Annex 7 tests the fixed fire-fighting system in the SOLIT2 gallery, then §3.3
governs transferring the result to the site. The twin is therefore the SITE's
`nozzles` and `hydraulics` blocks — the thing being assessed — dropped into
the gallery's tunnel, fire, ventilation, zoning and detection as the protocol
prescribes. `ahj` travels unchanged: acceptance limits belong to the project,
not to the tunnel they are measured in. Site constraints do not apply in the
gallery and are dropped.
"""
from __future__ import annotations

from solit2.schema.design import Design
from solit2.schema.presets import load_preset

GALLERY_TUNNEL = "solit2_test"
REFERENCE_NOZZLE = "solit2_reference"
# Annex 7 test protocol, as examples/designs/solit2-test-protocol.json encodes it.
PROTOCOL_ZONES = {"section_length_m": 20.0, "sections_simultaneous": 3,
                  "activation_delay_s": 60.0, "pump_ramp_s": 30.0, "duration_min": 35.0}
PROTOCOL_VENTILATION = {"mode": "longitudinal", "velocity_range_ms": [1.5, 3.0]}  # §5.2.7
PROTOCOL_DETECTION = {"type": "linear_heat", "threshold_c": 60.0, "sensor_spacing_m": 12.0}


def gallery_mount_height_m(design: Design) -> tuple[float, str]:
    """Where the heads go in the gallery, and the one-sentence reason why.

    The site's own height when it fits between the fuel top and the gallery
    ceiling — the system is tested as it will be installed. Otherwise the
    height the SOLIT2 reference tests used in this same gallery, which is a
    fact about the standard's facility, not a vendor figure.
    """
    gallery_m = float(load_preset("tunnel", GALLERY_TUNNEL)["height_m"])
    site_m = design.nozzles.mounting.height_above_carriageway_m
    fuel_top_m = design.fire.footprint.top_height_m
    if fuel_top_m < site_m < gallery_m:
        return site_m, (f"heads at the site's own {site_m:.2f} m, which fits under the "
                        f"{gallery_m:.2f} m gallery ceiling")
    ref_m = float(load_preset("nozzle", REFERENCE_NOZZLE)["mounting"]["height_above_carriageway_m"])
    if not fuel_top_m < ref_m < gallery_m:
        raise ValueError(
            f"nozzle mounting cannot be reproduced in the {gallery_m:.2f} m test gallery: "
            f"the site's {site_m:.2f} m and the reference tests' {ref_m:.2f} m both fall "
            f"outside the {fuel_top_m:.2f} m fuel top to ceiling range")
    return ref_m, (f"heads at {ref_m:.2f} m, where the SOLIT2 reference tests mounted theirs: "
                   f"the site's {site_m:.2f} m does not fit between the {fuel_top_m:.2f} m "
                   f"fuel top and the {gallery_m:.2f} m gallery ceiling")


def test_facility_twin(design: Design) -> Design:
    height_m, reason = gallery_mount_height_m(design)
    nozzles = design.nozzles.model_dump(mode="json", by_alias=True)
    nozzles = {**nozzles, "mounting": {**nozzles["mounting"],
                                       "height_above_carriageway_m": height_m}}
    raw = {
        "meta": {"name": f"{design.meta.name}-test-facility",
                 "notes": (f"Test-facility twin of {design.meta.name}: the site's nozzle and "
                           f"hydraulics blocks in the SOLIT2 Annex 7 gallery. Heads {reason}.")},
        "tunnel": {"preset": GALLERY_TUNNEL, "section": "test"},
        "fire": {**design.fire.model_dump(mode="json", by_alias=True), "covered": True},
        "nozzles": nozzles,
        "hydraulics": design.hydraulics.model_dump(mode="json", by_alias=True),
        "zones": dict(PROTOCOL_ZONES),
        "ventilation": dict(PROTOCOL_VENTILATION),
        "detection": dict(PROTOCOL_DETECTION),
        "ahj": design.ahj.model_dump(mode="json", by_alias=True),
        "constraints": {},
    }
    return Design.from_dict(raw)

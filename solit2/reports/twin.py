"""The test-facility twin: the tester's nozzle system in the SOLIT2 Annex 7 test.

Annex 7 tests the fixed fire-fighting system in the SOLIT2 gallery, then §3.3
governs transferring the result to the site. The twin is therefore the tester's
`nozzles`, `hydraulics`, zoning and detection blocks — the system being assessed
— run in the Annex 7 test: the gallery, the Annex 7 mock-up (not the site's
fire), the Annex 7 velocities, and Annex 7's manual activation and discharge
rules. `ahj` travels unchanged: acceptance limits belong to the project, not to
the tunnel they are measured in. Site constraints do not apply in the gallery.

EVERY VALUE BELOW IS AN ANNEX 7 CLAUSE OR A TESTER INPUT. Where Annex 7 leaves a
condition to the authority having jurisdiction or to the test day — the
activation trigger, the ambient conditions, the mock-up's free-burn growth — it
is an `Annex7Inputs` field with no default, and nothing here fills it in.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

from solit2.schema.design import Design
from solit2.schema.presets import load_preset

GALLERY_TUNNEL = "solit2_test"                      # Annex 2 §2, the gallery as tested
ANNEX7_VELOCITIES_MS = (1.5, 3.0)                  # 5.2.7 (Class A), 5.3.6 (Class B)
ANNEX7_FIRE = {"A": "hgv_150mw", "B": "pool_60mw"}  # 5.2.1-5.2.2, 5.3.1-5.3.2; Table 4
CLASS_A_MIN_ACTIVATION_S = 60.0                    # 5.2.8 A: "Minimum 1 minutes after ignition"
CLASS_B_MAX_ACTIVATION_S = 120.0                   # 5.3.7: "within 2 minutes after ignition"
CLASS_A_MIN_DISCHARGE_S = 30 * 60.0                # 5.2.8: "minimum of 30 minutes after activation"
# 5.2.8 / 5.3.7: "it shall be minimum 3 times the length of the mock-up".
ACTIVATION_AREA_MOCKUP_MULTIPLE = 3.0
# 5.3.7 runs Class B "until the fire is extinguished or the fuel is consumed
# completely". This is only how long the engine is run, not a test condition,
# and tests/test_twin.py asserts it reaches the end of the fire.
CLASS_B_RUN_HORIZON_MIN = 60.0


@dataclass(frozen=True)
class Annex7Inputs:
    """The Annex 7 test conditions that SOLIT2 leaves to the AHJ or the test day."""
    fire_class: Literal["A", "B"]
    activation_s: float        # AHJ trigger, from ignition: A >= 60 s (5.2.8), B <= 120 s (5.3.7)
    ambient_c: float           # test-day gallery air temperature
    ambient_rh_pct: float      # test-day relative humidity
    growth_alpha_kw_s2: float  # mock-up free-burn t^2 growth: AHJ design fire / lab calibration
    incubation_s: float        # ignition to the start of t^2 growth: AHJ design fire / lab


def _check_activation(inputs: Annex7Inputs) -> None:
    if inputs.fire_class == "A" and inputs.activation_s < CLASS_A_MIN_ACTIVATION_S:
        raise ValueError(f"Annex 7 5.2.8: Class A activation must be at least 60 s after "
                         f"ignition, got {inputs.activation_s:g} s")
    if inputs.fire_class == "B" and inputs.activation_s > CLASS_B_MAX_ACTIVATION_S:
        raise ValueError(f"Annex 7 5.3.7: Class B activation must be within 120 s of "
                         f"ignition, got {inputs.activation_s:g} s")


def gallery_mount_height_m(design: Design, fuel_top_m: float) -> tuple[float, str]:
    """Where the heads go in the gallery, and the one-sentence reason why.

    The tester's own height when it fits between the mock-up's fuel top and the
    gallery ceiling — the system is tested as it will be installed. Otherwise
    refused: SOLIT2 publishes no mounting height for its reference system, so
    there is no standard value to fall back on.
    """
    gallery_m = float(load_preset("tunnel", GALLERY_TUNNEL)["height_m"])
    site_m = design.nozzles.mounting.height_above_carriageway_m
    if fuel_top_m < site_m < gallery_m:
        return site_m, (f"heads at the tester's own {site_m:.2f} m, which fits under the "
                        f"{gallery_m:.2f} m gallery ceiling")
    raise ValueError(
        f"nozzle mounting cannot be reproduced in the {gallery_m:.2f} m SOLIT2 gallery: the "
        f"tester's {site_m:.2f} m head height does not fit between the {fuel_top_m:.2f} m fuel "
        f"top and the ceiling; enter the height the heads will be tested at")


def _check_activation_area(design: Design, mockup_m: float) -> None:
    area_m = design.zones.section_length_m * design.zones.sections_simultaneous
    minimum_m = ACTIVATION_AREA_MOCKUP_MULTIPLE * mockup_m
    if area_m < minimum_m:
        raise ValueError(f"Annex 7 5.2.8/5.3.7: the activation area must be at least 3 times "
                         f"the length of the mock-up ({minimum_m:g} m); this system activates "
                         f"{area_m:g} m")


def test_facility_twin(design: Design, inputs: Annex7Inputs) -> Design:
    _check_activation(inputs)
    fire_preset = ANNEX7_FIRE[inputs.fire_class]
    footprint = load_preset("fire", fire_preset)["footprint"]
    _check_activation_area(design, float(footprint["length_m"]))
    height_m, reason = gallery_mount_height_m(design, float(footprint["top_height_m"]))
    nozzles = design.nozzles.model_dump(mode="json", by_alias=True)
    nozzles = {**nozzles, "mounting": {**nozzles["mounting"],
                                       "height_above_carriageway_m": height_m}}
    duration_min = (math.ceil((inputs.activation_s + CLASS_A_MIN_DISCHARGE_S) / 60.0)
                    if inputs.fire_class == "A" else CLASS_B_RUN_HORIZON_MIN)
    raw = {
        "meta": {"name": f"{design.meta.name}-annex7-class-{inputs.fire_class.lower()}",
                 "notes": (f"SOLIT2 Annex 7 Class {inputs.fire_class} test of "
                           f"{design.meta.name}'s nozzle system in the SOLIT2 gallery. Heads "
                           f"{reason}. Every other value is an Annex 7 clause or a test-day "
                           f"input (solit2/reports/twin.py).")},
        "tunnel": {"preset": GALLERY_TUNNEL, "section": "test",
                   "ambient_temp_c": inputs.ambient_c, "ambient_rh_pct": inputs.ambient_rh_pct},
        "fire": {"preset": fire_preset, "alpha_kw_s2": inputs.growth_alpha_kw_s2,
                 "incubation_s": inputs.incubation_s,
                 # Table 4 rows 1-2, the mandatory Class A pair, are "With tarpaulin cover".
                 "covered": inputs.fire_class == "A"},
        "nozzles": nozzles,
        "hydraulics": design.hydraulics.model_dump(mode="json", by_alias=True),
        "zones": {"section_length_m": design.zones.section_length_m,
                  "sections_simultaneous": design.zones.sections_simultaneous,
                  # 5.2.8 / 5.3.7: "The activation of FFFS shall happen manually".
                  "manual_activation_s": inputs.activation_s, "activation_delay_s": 0.0,
                  "pump_ramp_s": design.zones.pump_ramp_s, "duration_min": duration_min},
        "ventilation": {"mode": "longitudinal", "velocity_range_ms": list(ANNEX7_VELOCITIES_MS)},
        "detection": design.detection.model_dump(mode="json", by_alias=True),
        "ahj": design.ahj.model_dump(mode="json", by_alias=True),
        "constraints": {},
    }
    return Design.from_dict(raw)

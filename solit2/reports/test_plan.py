"""The fire test protocol: what will be burned, measured and judged.

Annex 7 §8.2 lists, as a minimum, what a fire test protocol shall cover, and
§8.2's closing line is the reason this document exists at all: it "has to be
approved well prior to the tests by the authorities having jurisdiction".
This report is built to that list, section by section, so a reviewer can check
it against the standard without holding both open.

Two things it will not do. It does not invent an acceptance limit -- Annex 7
§7.1 puts those with the authority having jurisdiction and says in terms that
the chapter "do[es] not specify in detaild absolute values" -- and it does not
present the engine's predictions as results. The predictions are here so the
test has something to falsify.

Every requirement below carries its Annex 7 clause. Where the standard is
silent, or as at §5.2.8 option B where the published text is blank, this says
so rather than filling the gap.
"""
from __future__ import annotations

from solit2.engines.reduced.criteria import INSTRUMENTS, STATIONS
from solit2.engines.reduced.geometry import section_geometry
from solit2.schema.design import Design
from solit2.reports.guidance import (
    ACTIVATION_AREA_MIN_MULTIPLE,
    ACTIVATION_MIN_AFTER_IGNITION_S,
    CALIBRATION_POOL_MW,
    CLASS_A_ENERGY_GJ,
    CLASS_A_MIN_PALLETS,
    CLASS_A_MIN_UNSUPPRESSED_MW,
    CLASS_B_IGNITION_WITHIN_S,
    CLASS_B_MIN_BURN_MIN,
    CLASS_B_MIN_MW,
    CLASS_B_POOL_MIN_M,
    CLASS_B_SINGLE_POOL_MIN_M2,
    CLASS_B_TRIGGER_WITHIN_S,
    FLOW_TOLERANCE_PCT,
    FRAME_COVERAGE_MAX_PCT,
    HRR_MAX_DELAY_S,
    IGNITION_PANS,
    IGNITION_PAN_MM,
    IGNITION_PETROL_L,
    INSTRUMENT_SPEC,
    MAX_PALLET_MOISTURE_PCT,
    MAX_WALL_CLEARANCE_M,
    MINIMUM_TESTS,
    MIN_DISCHARGE_MIN,
    MIN_TEST_TUNNEL,
    MOCKUP_MIN_M,
    NOZZLE_SPREAD_MAX_PCT,
    PALLET_MASS_KG,
    PALLET_MM,
    TARGET_STANDOFF_M,
    TEST_VELOCITIES_MS,
    VELOCITY_STATION_M,
)
from solit2.reports import guidance
from solit2.schema.result import Criterion, Result

def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    if not rows:
        return ["_None._", ""]
    return ["| " + " | ".join(header) + " |",
            "|" + "|".join("---" for _ in header) + "|",
            *["| " + " | ".join(r) + " |" for r in rows], ""]


def _check(ok: bool | None) -> str:
    """Conformance against an Annex 7 minimum. `None` is "the design does not
    say", which is a gap in the protocol, not a pass."""
    return {True: "meets", False: "**BELOW MINIMUM**", None: "not stated"}[ok]


def _criteria_table(criteria: dict[str, Criterion]) -> str:
    lines = ["| criterion | value | limit | status | margin |", "|---|---|---|---|---|"]
    for name, c in criteria.items():
        limit = str(c.limit) if c.limit is not None else "—"
        lines.append(f"| {name} | {c.value} | {limit} | {c.status} | {c.margin:.3f} |")
    return "\n".join(lines)


def _standards() -> list[str]:
    return [
        "## 1. Standards referred to, and variations",
        "",
        "SOLIT² Engineering Guidance v2.1. Three parts of it bind a full-scale test, "
        "and they do not say the same thing:",
        "",
        "- **Annex 7**, *Fire Tests and Fire Scenarios for Evaluation of FFFS* — the "
        "detailed protocol. Bare clause numbers below are Annex 7's.",
        "- **Main document §3.6.2**, *Evidence of effectiveness* — its own test "
        "requirements, which Annex 7 does not repeat. A protocol built from Annex 7 "
        "alone misses the sampling rate, the number of test series and the standoff "
        "tolerance entirely.",
        "- **Annex 3 §3.3** — the design parameters that shall be *derived* from "
        "full-scale testing, which is what fixes the envelope a later tunnel must sit "
        "inside.",
        "",
        "Annex 7 §3.4 is the reason this test is being run rather than argued: CFD "
        "\"is only suitable for a limited interpolation or extrapolation of test data\" "
        "and \"shall not however replace full scale fire testing\". Any modelling "
        "supplied alongside this protocol is supporting evidence, not a substitute for it.",
        "",
        "**Variations from any of the three must be listed in this section and "
        "approved with the rest of the protocol.**",
        "",
    ]


def _risk_basis() -> list[str]:
    """Annex 7 §3.1 puts the risk analysis upstream of the whole protocol."""
    ex = guidance.RISK_ANALYSIS_EXAMPLE
    return [
        "## 2. Basis in the tunnel's risk analysis",
        "",
        "Annex 7 §3.1 does not let a test choose its own fire: \"Fire testing should be "
        "based on the results of risk analysis for every tunnel. The risk analysis "
        "defines the vehicle types and related design fire sizes that shall be "
        "considered for the tunnel.\" The same clause gives the authority having "
        "jurisdiction two separate approvals to make — the **suitability of the design "
        "fire scenarios**, and **what the minimum acceptance criteria are**.",
        "",
        "**Nothing below can be settled by this document.** The design fire, the "
        "scenarios and the criteria come from the tunnel's own risk analysis and its "
        "authority. What follows is the worked example the Guidance itself supplies in "
        "Annex 4, given as the method to follow, not as figures to copy.",
        "",
        *_table(["Element of the worked example", "Annex 4's value"],
                [[k[0].upper() + k[1:], v] for k, v in ex.items()]),
        "Two things in that example bear directly on this protocol.",
        "",
        f"**The activation timeline.** Annex 4 credits the system from "
        f"{ex['activation']}. Annex 7 §5.2.8 separately requires test activation to be "
        f"no earlier than {ACTIVATION_MIN_AFTER_IGNITION_S:.0f} s after ignition. If the "
        f"risk analysis for this tunnel assumes the system takes effect later than the "
        f"test activates it, the test is the easier case and the risk analysis is not "
        f"supported by it. **State the tunnel's own assumed activation time here and "
        f"check it against the test.**",
        "",
        f"**The ranking noise floor.** Annex 4 §5.2 reports its two cases at 30.04 and "
        f"30.71 expected-damage units and then says plainly that differences up to about "
        f"{guidance.RISK_RANKING_NOISE_PCT:.0f} % support no binding statement of rank, "
        f"scatter that size being usual given uncertainty in the inputs and assumptions. "
        f"A margin thinner than that is not evidence of an improvement.",
        "",
        "One methodological caveat, because it decides whether a Class A test can be "
        "dropped. German practice (Heft 66) runs quantitative risk analysis on "
        "fast-developing pool fires alone, on the reasoning that the measures being "
        "compared — escape routes, ventilation, detection — improve escape conditions "
        "without changing how the fire itself develops, so a slower solid fire ranks "
        "them the same way. **A fire fighting system is the exception**: it acts on the "
        "fire. That reasoning therefore does not carry over, which is consistent with "
        "Annex 7 §5.4 requiring both classes rather than either.",
        "",
    ]


def _tunnel(design: Design) -> list[str]:
    t = design.tunnel
    geom = section_geometry(design)
    rows = [
        ["Free cross-section", f"{geom.free_area_m2:.1f} m²",
         f"≥ {MIN_TEST_TUNNEL['free area (m2)']:.0f} m²",
         _check(geom.free_area_m2 >= MIN_TEST_TUNNEL["free area (m2)"])],
        ["Height to crown", f"{geom.crown_height_m:.2f} m",
         f"≥ {MIN_TEST_TUNNEL['height (m)']:.1f} m",
         _check(geom.crown_height_m >= MIN_TEST_TUNNEL["height (m)"])],
        ["Length", f"{t.length_m:.0f} m", f"≥ {MIN_TEST_TUNNEL['length (m)']:.0f} m",
         _check(t.length_m >= MIN_TEST_TUNNEL["length (m)"])],
        ["Carriageway width", f"{geom.road_width_m:.2f} m", "—", "—"],
        ["Gradient", f"{t.gradient_pct:.1f} %", "—", "—"],
        ["Ambient", f"{t.ambient_temp_c:.1f} °C, {t.ambient_rh_pct:.0f} % RH", "—", "—"],
    ]
    return [
        "## 3. Test tunnel — description and geometry",
        "",
        f"Section `{t.section}` ({t.shape}), preset `{t.preset}`, {t.tubes} bore(s).",
        "",
        "Annex 7 §3.6 sets geometric minimums for a test tunnel and allows the "
        "authority having jurisdiction to accept different values where the test or "
        "the real tunnel is smaller.",
        "",
        *_table(["Property", "This tunnel", "Annex 7 §3.6 minimum", "Conformance"], rows),
        "### Two floors, not one",
        "",
        "Annex 7 §3.6 and main document §3.6.2 both set minimum test-tunnel dimensions "
        "and they disagree. Both are minimums, so a test tunnel has to clear the higher "
        "of each pair. Annex 7 lets the authority accept smaller values; §3.6.2 does "
        "not say so, which is a reason to raise any shortfall with them explicitly "
        "rather than assume the weaker figure governs.",
        "",
        *_table(["Property", "Annex 7 §3.6", "Main §3.6.2", "Governs"],
                [[name, f"{a:g} {unit}" if a else "—", f"{b:g} {unit}",
                  f"**{max(a, b):g} {unit}**"]
                 for name, a, b, unit, _ in guidance.STRICTER_OF]),
        f"Main §3.6.2 additionally requires a test tunnel at least "
        f"{guidance.MAIN_MIN_TEST_TUNNEL['width (m)']:g} m wide with the cross-section "
        f"of a typical tunnel. Annex 7 states its own floor as a free area of "
        f"{MIN_TEST_TUNNEL['free area (m2)']:.0f} m² instead of a width.",
        "",
        "**The figures above describe the tunnel this design is assessed for.** If the "
        "fire test is run in a different tunnel, §3.3 applies: results transfer only "
        "while the protected tunnel's major design parameters sit inside those of the "
        "tunnel tested in. State the test tunnel's own geometry here before approval.",
        "",
    ]


def _system(design: Design) -> list[str]:
    n, z = design.nozzles, design.zones
    mount = n.mounting
    mockup_length = design.fire.footprint.length_m
    activation_length = z.sections_simultaneous * z.section_length_m
    required = ACTIVATION_AREA_MIN_MULTIPLE * mockup_length
    rows = [
        ["Nozzle K-factor", f"{n.k_factor_lpm_bar05:g} L/min·bar⁰·⁵", "recorded", "—"],
        ["Working pressure", f"{n.pressure_bar:.1f} bar", "recorded", "—"],
        ["Flow per head", f"{n.flow_per_head_lpm:.1f} L/min", "recorded", "—"],
        ["Droplet size (Sauter mean)", f"{n.smd_um(n.modes[0].id):.0f} µm", "recorded", "—"],
        ["Head pitch", f"{mount.pitch_m:g} m", "recorded", "—"],
        ["Rows and offsets",
         f"{mount.rows} at y {', '.join(f'{o:+.2f}' for o in mount.row_lateral_offsets_m)} m",
         "recorded", "—"],
        ["Mounting height above carriageway",
         f"{mount.height_above_carriageway_m:g} m", "recorded", "—"],
        ["Heads discharging", f"{design.active_heads}", "—", "—"],
        ["Activation length", f"{activation_length:.0f} m",
         f"≥ {required:.0f} m (3 × mock-up)",
         _check(activation_length >= required)],
        ["Discharge duration", f"{z.duration_min:.0f} min",
         f"≥ {MIN_DISCHARGE_MIN:.0f} min", _check(z.duration_min >= MIN_DISCHARGE_MIN)],
    ]
    return [
        "## 4. FFFS categorisation and intended system parameters",
        "",
        "Annex 7 §4 requires the tested system to carry the same design parameters as "
        "the one to be installed, and the nozzle type, K-factor, pressure and spacing "
        "to be recorded as part of testing.",
        "",
        *_table(["Parameter", "Value", "Annex 7 requirement", "Conformance"], rows),
        "Three §4 conditions bind the test rig rather than the design, and are "
        "verified on site rather than here:",
        "",
        f"- The system is tested at its **minimum** pressure and **minimum** "
        f"application rate, not a favourable one.",
        f"- Pressure and application rate vary by no more than "
        f"**{NOZZLE_SPREAD_MAX_PCT:.0f} %** between the hydraulically first and last "
        f"nozzle of the whole test installation.",
        "- The layout represents the **most unfavourable** conditions that would occur "
        "in the real tunnel. The activation length may be shorter in test than in "
        "service; nothing else may be more favourable.",
        "",
        f"Main §3.6.2 adds two conditions Annex 7 does not state. The exact nozzle or "
        f"deluge head must be used, with its droplet distribution and K-factor "
        f"documented; and the **nozzle-to-fire-load distance in the real tunnel may "
        f"exceed the tested distance by no more than "
        f"{guidance.MAIN_MAX_STANDOFF_EXCESS_PCT:.0f} %**. The spray deviation must be "
        f"characterised at least at "
        f"{', '.join(f'{v:g}' for v in guidance.MAIN_SPRAY_DEVIATION_MS)} m/s — a wider "
        f"set than the {' and '.join(f'{v:g}' for v in TEST_VELOCITIES_MS)} m/s at which "
        f"Annex 7 §5.2.7 requires the fires themselves to be run.",
        "",
        "### Parameters this test has to establish (Annex 3 §3.3)",
        "",
        "\"All major design parameters of any FFFS shall be derived from full scale fire "
        "testing.\" The list below is what the test must pin down, and it is also the "
        "envelope §3.3 then confines a protected tunnel to: a later tunnel needs no "
        "retest only while its major design parameters sit inside what was tested here.",
        "",
        *["- " + item for item in guidance.TEST_DERIVED_PARAMETERS],
        "",
        f"Measured flow shall sit within **{FLOW_TOLERANCE_PCT:.0f} %** of the flow "
        f"calculated from K-factor, nozzle count and minimum nozzle pressure (§6.4.7). "
        f"A wider gap means the water is unevenly distributed across the activated area.",
        "",
    ]


def _fire_load(design: Design) -> list[str]:
    f = design.fire
    fp = f.footprint
    geom = section_geometry(design)
    clearance = f.lane_centre_offset_from_wall_m - fp.width_m / 2.0
    rows = [
        ["Unsuppressed design fire", f"{f.design_hrr_mw:.0f} MW",
         f"≥ {CLASS_A_MIN_UNSUPPRESSED_MW:.0f} MW",
         _check(f.design_hrr_mw >= CLASS_A_MIN_UNSUPPRESSED_MW)],
        ["Mock-up length", f"{fp.length_m:g} m", f"{MOCKUP_MIN_M['length']:g} m",
         _check(fp.length_m >= MOCKUP_MIN_M["length"])],
        ["Mock-up width", f"{fp.width_m:g} m", f"{MOCKUP_MIN_M['width']:g} m",
         _check(fp.width_m >= MOCKUP_MIN_M["width"])],
        ["Mock-up top height", f"{fp.top_height_m:g} m",
         f"≥ {MOCKUP_MIN_M['height']:g} m",
         _check(fp.top_height_m >= MOCKUP_MIN_M["height"])],
        ["Fuel stack height", f"{fp.top_height_m - fp.base_height_m:g} m",
         f"≥ {MOCKUP_MIN_M['fuel height']:g} m",
         _check((fp.top_height_m - fp.base_height_m) >= MOCKUP_MIN_M["fuel height"])],
        ["Clearance, load edge to side wall", f"{clearance:.2f} m",
         f"< {MAX_WALL_CLEARANCE_M:g} m", _check(clearance < MAX_WALL_CLEARANCE_M)],
        ["Target standoff behind mock-up", f"{f.target_distance_m:.1f} m",
         f"{TARGET_STANDOFF_M:.0f} m (station D10)",
         _check(abs(f.target_distance_m - TARGET_STANDOFF_M) < 0.05)],
    ]
    return [
        "## 5. Fire load and target",
        "",
        f"Class {f.fire_class} solid fire, preset `{f.preset}`, {f.growth} growth "
        f"(α = {f.alpha:g} kW/s²), incubation {f.incubation_s:.0f} s.",
        "",
        *_table(["Property", "This design", "Annex 7 §5.2", "Conformance"], rows),
        "### Fuel, as §5.2.2 and §5.2.4 specify it",
        "",
        f"- **Euro wood pallets**, minimum **{CLASS_A_MIN_PALLETS}**, corresponding to "
        f"roughly {CLASS_A_ENERGY_GJ[0]:.0f}–{CLASS_A_ENERGY_GJ[1]:.0f} GJ. Pallet "
        f"{PALLET_MM[0]} × {PALLET_MM[1]} × {PALLET_MM[2]} mm, "
        f"{PALLET_MASS_KG[0]:.0f}–{PALLET_MASS_KG[1]:.0f} kg each.",
        f"- **Moisture content {MAX_PALLET_MOISTURE_PCT:.0f} % or less.** Random probes "
        f"measured from the pallets in the set-up **before each test**, and the "
        f"measurements included in the test report. This is a per-test record, not a "
        f"one-off qualification of the batch.",
        "- **Plastic pallets shall not be used.** They vary more, lose structural "
        "integrity at low temperature and collapse the load early.",
        f"- **Steel frames** hold the stacks up so they cannot fall, and cover no more "
        f"than {FRAME_COVERAGE_MAX_PCT:.0f} % of the sides or top of the fuel. The "
        f"frames survive the test without collapsing. Keeping the load together is the "
        f"harder case for the system: a collapsed stack exposes more surface to water.",
        "- **Steel plates** close the front and back, representing trailer doors and "
        "blocking air straight into the load.",
        "- **PVC tarpaulin**, not fire retardant, fixed so the forced ventilation "
        "cannot remove or open it. Without a cover water reaches the seat of the fire "
        "immediately, which §5.2.2 calls unrealistic for most real HGVs.",
        "",
        "### Position (§5.2.3)",
        "",
        f"Eccentric to the tunnel centre line, load edge less than "
        f"{MAX_WALL_CLEARANCE_M:g} m from the side wall. This design places the load "
        f"centre {f.lane_centre_offset_from_wall_m:.2f} m from the wall, in a "
        f"{geom.road_width_m:.2f} m carriageway. A centred load is the easier case, "
        f"because the system reaches it from both sides.",
        "",
        "### Target (§5.2.6)",
        "",
        f"A second fuel package **{TARGET_STANDOFF_M:.0f} m downstream** of the mock-up, "
        f"at station **D10**, of the same width, height and combustibility as the "
        f"mock-up, built from Euro wood pallets. Water-filled barrels and other "
        f"non-combustible targets are **not permitted**: they do not demonstrate fire "
        f"spread. The target is inspected after extinguishment for damage indicating "
        f"ignition.",
        "",
    ]


def _ignition_and_ventilation(design: Design) -> list[str]:
    v = design.ventilation
    declared = (f"{v.velocity_ms:.2f} m/s" if v.velocity_ms is not None
                else f"{v.velocity_range_ms[0]:.2f}–{v.velocity_range_ms[1]:.2f} m/s")
    return [
        "## 6. Ignition (§5.2.5)",
        "",
        f"At least **{IGNITION_PANS} pans**, each {IGNITION_PAN_MM[0]} × "
        f"{IGNITION_PAN_MM[1]} × {IGNITION_PAN_MM[2]} mm, each holding "
        f"**{IGNITION_PETROL_L:.0f} litres of gasoline**. Placed inside the first "
        f"pallets on the side of the mock-up, in the second stack at the upstream front.",
        "",
        "## 7. Ventilation conditions (§5.2.7)",
        "",
        f"Both **{TEST_VELOCITIES_MS[0]:g} m/s and {TEST_VELOCITIES_MS[1]:g} m/s** "
        f"longitudinal velocity shall be tested; see the matrix in section 8. Air "
        f"velocity is measured **{VELOCITY_STATION_M['A']:.0f} m upstream** of the fuel "
        f"for Class A ({VELOCITY_STATION_M['B']:.0f} m for Class B, §5.3.6) and checked "
        f"for plausibility before the start of each test.",
        "",
        f"This design is assessed at {declared}, ventilation mode `{v.mode}`.",
        "",
        "Annex 7 §3.2 ties the test to the real installation in two ways that must be "
        "checked before the results can be relied on:",
        "",
        "- The real tunnel's ventilation shall have **at least the same capacity** as "
        "used in the tests.",
        "- The real fire detection and localisation system shall detect a fire **at "
        "least as fast** as the FFFS was activated in the tests.",
        "",
    ]


def _activation(design: Design) -> list[str]:
    z, d = design.zones, design.detection
    return [
        "## 8. Activation times (§5.2.8)",
        "",
        "Activation is **manual** and deliberately delayed relative to the detection "
        "system, so the test does not credit a detection time it has not demonstrated.",
        "",
        *_table(["Requirement", "Annex 7", "This design"], [
            ["Earliest activation after ignition",
             f"≥ {ACTIVATION_MIN_AFTER_IGNITION_S:.0f} s (option A)",
             f"activation delay {z.activation_delay_s:.0f} s after detection"],
            ["Continuous discharge", f"≥ {MIN_DISCHARGE_MIN:.0f} min",
             f"{z.duration_min:.0f} min"],
            ["Deactivation", "manual", "manual"],
            ["Pump ramp to full pressure", "not specified", f"{z.pump_ramp_s:.0f} s"],
            ["Detection", "shall be at least as fast in service as in test",
             f"{d.type}, {d.threshold_c:.0f} °C, {d.sensor_spacing_m:g} m spacing"],
        ]),
        "> **Open item — a gap in the published standard.** §5.2.8 offers the trigger "
        "as \"A. Minimum 1 minutes after ignition **or** B.\" — and option B is blank "
        "in Annex 7 v2.1 as published. §6.5 makes the intent clear, stating that the "
        "heat release rate \"is used as the triggering point for activation of FFFS\" "
        f"and that its measurement delay should not exceed {HRR_MAX_DELAY_S:.0f} s. "
        "The HRR value itself is not printed anywhere in the clause. **The authority "
        "having jurisdiction must set the option B trigger, in MW, before the protocol "
        "is approved.** It is not inferred here.",
        "",
        f"Class B differs: triggering shall happen **within "
        f"{CLASS_B_TRIGGER_WITHIN_S / 60:.0f} minutes** of ignition, and discharge "
        f"continues until the fire is extinguished or the fuel is fully consumed "
        f"(§5.3.7).",
        "",
    ]


def _programme(design: Design) -> list[str]:
    f = design.fire
    return [
        "## 9. Fire test programme (§5.4, Table 4)",
        "",
        *_table(["No.", "Class", "Configuration", "Ventilation", "Status"],
                [list(r) for r in MINIMUM_TESTS]),
        f"**Class B, tests 3 and 4.** A pool fire of at least "
        f"{CLASS_B_MIN_MW:.0f} MW, minimum {CLASS_B_POOL_MIN_M['width']:g} m wide by "
        f"{CLASS_B_POOL_MIN_M['length']:g} m long, no more than "
        f"{CLASS_B_POOL_MIN_M['height above road']:g} m above road level, as one pool "
        f"or several of at least {CLASS_B_SINGLE_POOL_MIN_M2:g} m² each. Light diesel "
        f"oil, volume equal to at least {CLASS_B_MIN_BURN_MIN:.0f} minutes of "
        f"unsuppressed burning. All pools ignited within "
        f"{CLASS_B_IGNITION_WITHIN_S:.0f} seconds (§5.3.1–§5.3.5).",
        "",
        f"This design declares a Class {f.fire_class} fire. **Annex 7 requires both "
        f"classes**: tests 1–4 are the minimum set, and a Class A result does not "
        f"discharge the Class B requirement. If the authority having jurisdiction has "
        f"waived either class on the basis of the tunnel's risk analysis, record that "
        f"waiver in section 1 as a variation.",
        "",
        f"### Repeat series (main §3.6.2)",
        "",
        f"Annex 7's Table 4 is a matrix of configurations, not a count of repetitions, "
        f"and Annex 7 nowhere requires a test to be repeated. Main §3.6.2 does: **\"At "
        f"least {guidance.MAIN_MIN_TEST_SERIES} series of tests must be carried out for "
        f"FFFSs in tunnels.\"** Read together, the matrix above is one series.",
        "",
        "This is worth stating plainly because it is the only requirement in the whole "
        "Guidance that bears on repeatability, and it does not deliver much. Neither "
        "Annex 1 nor Annex 2 reports duplicate tests, run-to-run scatter or measurement "
        "uncertainty for the full-scale fire tests, so there is no published figure for "
        "how much two nominally identical tunnel fire tests differ. **Run the repeat "
        "series as nominally identical tests wherever the programme allows, and report "
        "the spread.** Without it, a later disagreement between test and model cannot "
        "be told apart from ordinary scatter.",
        "",
        "### Calibration series, before the official tests (§5.4, §6.2)",
        "",
        f"Annex 7 strongly recommends a separate fire series to calibrate the "
        f"measurement system first, using smaller Class B pool fires — about "
        f"**{CALIBRATION_POOL_MW[0]:.0f} MW and {CALIBRATION_POOL_MW[1]:.0f} MW** — "
        f"and free-burning Class B tests. A pool fire gives a constant heat release "
        f"rate, which is what makes it usable as a reference for the measurement and "
        f"calculation method.",
        "",
    ]


def _instrumentation() -> list[str]:
    rows = []
    for name, x in sorted(STATIONS.items(), key=lambda kv: kv[1]):
        kit = INSTRUMENTS[name]
        carried = [f"{kit.thermocouples} thermocouple(s)"]
        for count, what in ((kit.bidirectional, "bidirectional probe"),
                            (kit.ultrasonic, "ultrasonic air velocity"),
                            (kit.oxygen, "oxygen"), (kit.carbon_dioxide, "carbon dioxide"),
                            (kit.carbon_monoxide, "carbon monoxide"),
                            (kit.relative_humidity, "relative humidity")):
            if count:
                carried.append(f"{count} {what}")
        if kit.heat_flux:
            carried.append("1 heat flux")
        if kit.visibility:
            carried.append("visibility")
        if kit.reference_thermocouple:
            carried.append("1 reference thermocouple")
        rows.append([name, f"{x:+.0f}", ", ".join(carried)])
    return [
        "## 10. Test set-up — instruments, methodology and measurement grid",
        "",
        "### Naming (§6.3)",
        "",
        "The virtual zero point **00** is longitudinally at the middle of the mock-up. "
        "Upstream positions are **U**xx and downstream **D**xx, xx being the distance "
        "from zero in metres. The mock-up ends therefore fall at U05 and D05, and the "
        "fire target at D10. Instrument types are abbreviated TC (thermocouple), "
        "HF (heat flux), IR (infrared camera), CM (video), AN (anemometer), "
        "GA (gas sampling), VI (visibility).",
        "",
        "Within a cross-section carrying five or more thermocouples, sensors are "
        "arranged as Annex 7 Figure 16 draws them: two on each side wall bracketing "
        "the load, one at the ceiling, and — where the plane cuts the mock-up — one "
        "beside the load and one above it.",
        "",
        "### Longitudinal schedule (§6.4.10, Table 5)",
        "",
        "Annex 7 calls this a **minimum**. The authority having jurisdiction may add "
        "to it, or reduce it, particularly where the protected tunnel carries a "
        "special risk.",
        "",
        *_table(["Station", "x (m)", "Sensors"], rows),
        "### Instrument specification (§6.4)",
        "",
        *_table(["Measurement", "Abbr.", "Type", "Range", "Accuracy", "Clause"],
                [list(r) for r in INSTRUMENT_SPEC]),
        "Two further requirements that are easy to miss:",
        "",
        "- **Thermo plates shall not be used for heat flux** (§6.4.2). They react too "
        "slowly for a test with a fire fighting system, and droplets landing on the "
        "large sensing surface cause failures.",
        "- **Gas sampling uses at least 3 sensors with 2 suction points each** per "
        "cross-section, on **both sides** of the fire, at U45 and D45 (§6.4.3). Under "
        "semi-transverse or transverse ventilation, gas must additionally be measured "
        "in a cross-section beyond the last extraction damper downstream.",
        "",
        "### The main document's own schedule (§3.6.2)",
        "",
        "Main §3.6.2 lists measurements separately from Annex 7's Table 5, and calls its "
        "list \"not exclusive\". The two overlap but are not the same: §3.6.2 wants "
        "temperatures at 10 m and 20 m, which Table 5 does not carry, and radiant heat "
        "at 5 m and 10 m rather than Table 5's U15 and D15. Satisfy both.",
        "",
        *_table(["Quantity", "Positions required by main §3.6.2"],
                [list(r) for r in guidance.MAIN_MEASUREMENT_SCHEDULE]),
        f"**Sampling rate.** All values \"must be measured and collated at least every "
        f"{guidance.MAIN_MAX_SAMPLE_INTERVAL_S:g} s\" throughout the test (§3.6.2). "
        f"Annex 7 sets no sampling rate at all; it constrains only the heat release "
        f"rate, whose measurement delay must not exceed {HRR_MAX_DELAY_S:.0f} s (§6.5).",
        "",
        "### Video (§6.4.8)",
        "",
        "At least one normal camera upstream at U10 and one downstream at D25, plus a "
        "**thermal** camera downstream at D25. Downstream cameras are mounted below "
        "1.5 m and thermally insulated. All cameras point at the mock-up and cover the "
        "full cross-section.",
        "",
    ]


def _calibration_and_hrr() -> list[str]:
    return [
        "## 11. System calibration and heat release rate",
        "",
        "### Calibration (§6.2)",
        "",
        "Measurements shall be made by a body holding **ISO/IEC 17025:2005** "
        "accreditation, or one whose competence in planning, executing and evaluating "
        "complex full-scale tunnel fire measurements is otherwise demonstrated — by "
        "prior experience of this specific kind of test. §3.5 makes the same point "
        "about the test institute and is explicit that experience weighs more heavily "
        "than the accreditation alone.",
        "",
        "**All measurement equipment is calibrated before the fire tests.** The "
        "calibration data is attached to the protocol, and the calibration reports or "
        "certificates form part of the test reporting.",
        "",
        "### Heat release rate (§6.5)",
        "",
        "HRR shall be determined by **oxygen consumption**. Mass loss is not usable "
        "for suppressed tests, because the fire fighting medium lands on the fire load "
        "and corrupts the weight. Mass loss remains valid for free-burning fires, "
        "particularly Class B, and is used to calibrate the oxygen-consumption method "
        "and to verify Class A heat release over the whole test.",
        "",
        f"The measurement delay shall not exceed **{HRR_MAX_DELAY_S:.0f} seconds**, "
        f"both so activation is timely and for the safety of the people running the "
        f"test.",
        "",
        "The oxygen-consumption method shall be **documented in detail** in the "
        "protocol and the report, its accuracy demonstrated by Class B reference tests "
        "with and without the system running, and **the method itself approved by the "
        "authority having jurisdiction**.",
        "",
    ]


def _acceptance(result: Result) -> list[str]:
    unset = result.score["criteria_unset"]
    lines = [
        "## 12. Acceptance criteria (§7)",
        "",
        "Annex 7 §7.1 is unambiguous about who owns this section: \"The detailed "
        "acceptance criteria shall be defined by authorities having jurisdiction based "
        "on the risk analysis of every individual tunnel\", and the chapter gives "
        "guidance for selecting minimum requirements but does \"not specify in detaild "
        "absolute values\". Nothing in this document sets a limit. The four categories "
        "the standard requires them under are:",
        "",
        "1. **Fire development and suppression.** The system shall slow fire "
        "development in terms of measured HRR, and the HRR limit shall be consistent "
        "with the capacity of the ventilation system and other fire-size dependent "
        "systems.",
        "2. **Personal (life) safety.** Tenable conditions upstream, covering "
        "temperature, heat radiation, visibility and gas concentrations; corresponding "
        "limits downstream, where conditions are more critical and where §7.2.2 "
        "singles out CO and CO₂ for special attention.",
        "3. **Fire services.** Normally the life-safety criteria suffice, since "
        "firefighters have protective clothing and breathing apparatus, but the "
        "authority may add requirements for a tunnel with special features.",
        "4. **Tunnel structure.** High-temperature exposure shall be limited to a "
        "small area directly above the load or slightly downstream. §7.2.4 is explicit "
        "that **duration matters more than peak**: temperatures above 500 °C are "
        "acceptable if the exposure is short and the area small, and what a structure "
        "tolerates depends on its construction — the clause contrasts concrete with "
        "60 mm cover against a cast iron lining.",
        "",
        "### The one absolute rule",
        "",
        "§7.2.1 states a pass/fail condition that carries no adjustable limit and is "
        "not the authority's to relax: **the fire target shall not ignite.** \"FFFS "
        "has failed if fire spread has spread to the target 5 m downstream behind the "
        "mock-up (D10).\" The target is examined after extinguishment for damage "
        "indicating ignition of the target material.",
        "",
        "### Timing of the criteria (§7.4)",
        "",
        "A system needs time after its trigger before pumps run and pressure reaches "
        "the design level, so measured conditions lag activation. **The authority "
        "having jurisdiction shall state the time limit by which each acceptance "
        "criterion must be satisfied.** Without it, a criterion has no meaning: any "
        "system passes eventually, and any system fails at t=0.",
        "",
        "### Criteria carried by this assessment",
        "",
        _criteria_table(result.criteria),
        "",
    ]
    if unset:
        lines += [
            f"**{len(unset)} of {len(result.criteria)} criteria carry no limit.** They "
            f"are reported as `unset` and excluded from the margin score rather than "
            f"counted as passes. Each must be given a value by the authority having "
            f"jurisdiction before this protocol is approved.",
            "",
        ]
    return lines


def _predictions(design: Design, result: Result) -> list[str]:
    score = result.score
    # "All gates passed" alone would overstate a design most of whose criteria nobody
    # has ruled on: CLAUDE.md forbids presenting `gates_passed` as approval while
    # `criteria_unset` is non-empty, and this line is read on its own in the report.
    unset = score["criteria_unset"]
    outcome = ("all gates passed" if score["gates_passed"]
               else "gates failed: " + ", ".join(score["gates_failed"]))
    if unset:
        outcome += (f" — but {len(unset)} of {len(result.criteria)} criteria were not judged, "
                    f"no limit having been set for them: " + ", ".join(unset))
    note = result.meta.get("calibration_note")
    lines = [
        "## 13. Predicted outcomes — what the test will check",
        "",
        "These are model outputs, stated in advance so the test can contradict them. "
        "They are not results and carry no standing under Annex 7.",
        "",
        *_table(["Quantity", "Predicted"],
                [[k, str(v)] for k, v in sorted(result.peaks.items())]),
    ]
    events = {k: v for k, v in result.events.items() if isinstance(v, (int, float))}
    if events:
        lines += [*_table(["Predicted event", "Test clock (s)"],
                          [[k.replace("_", " ").replace("t ", "").strip().capitalize(),
                            f"{v:.0f}"] for k, v in sorted(events.items(), key=lambda kv: kv[1])])]
    lines += [f"**Score**: {score['total']:.2f} ({outcome})", ""]
    if note:
        lines += ["The engine's own calibration note, verbatim:", "", f"> {note}", ""]
    if result.warnings:
        lines += ["Reported by the engine for this run:", ""]
        lines += [f"- {w}" for w in result.warnings] + [""]
    return lines


def _reporting() -> list[str]:
    return [
        "## 14. Reporting (§8)",
        "",
        "Two documents cover the tests. **This protocol**, which must be approved by "
        "the authority having jurisdiction well before testing, and the **fire test "
        "report** afterwards. §8.4 gives the authority a role at all three stages: "
        "approving the protocol, witnessing the tests, and approving the report.",
        "",
        "The report shall carry, at minimum:",
        "",
        "- Tested design parameters in detail — layout, design nozzle pressure, design "
        "nozzle flow rate (§8.3.1).",
        "- **One sample nozzle**, delivered with the report for the authority's records "
        "(§8.3.1).",
        "- A summary of all measurements; data files may be supplied electronically by "
        "agreement (§8.3.2).",
        "- Every acceptance criterion, whether it passed, and a reference to the "
        "measurement that decides it (§8.3.3).",
        "- Other recordings, their content agreed with the authority (§8.3.4).",
        "- Empirical observations, for example firefighters' experience of conditions "
        "and of the difficulty of manual firefighting (§8.3.5, §6.4.9).",
        "- **Copies of the original log files**, signed by the authority's witness "
        "(§8.3.6).",
        "",
        "## 15. Safety during testing (§3.8)",
        "",
        "A suppressed HGV fire that loses its suppression develops within about a "
        "minute into a blaze the fire service cannot fight; Annex 7 §3.8 illustrates "
        "exactly this. Accordingly: only trained personnel take part, the test "
        "institute gives a safety induction to every external visitor and witness "
        "including the test tunnel's evacuation plan, and **all major tests are "
        "secured by professional firefighters**.",
        "",
    ]


def render(design: Design, result: Result) -> str:
    """The protocol, in the order Annex 7 §8.2 lists its minimum contents."""
    lines = [
        f"# Fire test protocol — {design.meta.name}",
        "",
        "Full-scale fire test of a fixed fire fighting system in a road tunnel, to "
        "SOLIT² Engineering Guidance Annex 7 v2.1.",
        "",
        "> **Status: draft for approval.** Annex 7 §8.2 requires this protocol to be "
        "approved by the authority having jurisdiction well before testing begins. "
        "Sections marked as open items must be settled first.",
        "",
        *_standards(),
        *_risk_basis(),
        *_tunnel(design),
        *_system(design),
        *_fire_load(design),
        *_ignition_and_ventilation(design),
        *_activation(design),
        *_programme(design),
        *_instrumentation(),
        *_calibration_and_hrr(),
        *_acceptance(result),
        *_predictions(design, result),
        *_reporting(),
    ]
    return "\n".join(lines)

"""The full assessment report: one document a reviewer can read on its own.

`test_plan.py` states the inputs and the predictions for a test that is about
to be run. This is the other document -- what was assessed, how, what came
out, and what the result does not establish. It is written to be handed to
someone who has not seen the tool.

Two rules shape it, both from INDEPENDENCE.md. It never presents passed gates
as approval while criteria are unjudged, and it never omits the standing of
the engine that produced the numbers: a fitted calibration is not a validated
one, and a reader who is not told that will assume otherwise.
"""
from __future__ import annotations

from datetime import datetime, timezone

from solit2.engines.reduced.criteria import INSTRUMENTS, STATIONS
from solit2.engines.reduced.geometry import section_geometry
from solit2.reports import labels
from solit2.schema.design import Design
from solit2.schema.result import Criterion, Result

SECTION_RULE = ""


def _table(header: list[str], rows: list[list[str]]) -> list[str]:
    if not rows:
        return ["_None._", ""]
    return ["| " + " | ".join(header) + " |",
            "|" + "|".join("---" for _ in header) + "|",
            *["| " + " | ".join(r) + " |" for r in rows], ""]


def _criteria_rows(criteria: dict[str, Criterion]) -> list[list[str]]:
    rows = []
    for name, c in criteria.items():
        limit = labels.value(name, c.limit) if c.limit is not None else "not set"
        verdict = {"pass": "pass", "fail": "FAIL",
                   "unset": "not judged"}.get(c.status, c.status)
        rows.append([labels.heading(name), labels.value(name, c.value), limit,
                     verdict, f"{c.margin:.2f}" if c.status != "unset" else "—"])
    return rows


def _quantities(block: dict) -> list[list[str]]:
    return [[labels.heading(k), labels.value(k, v)] for k, v in sorted(block.items())]


def _identity(design: Design, result: Result) -> list[str]:
    meta = result.meta
    return [
        f"# Fire suppression assessment — {design.meta.name}",
        "",
        *_table(["", ""], [
            ["Generated", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")],
            ["Engine", f"{meta.get('engine', 'reduced')} "
                       f"{meta.get('engine_version', '')}".strip()],
            ["Design identifier", str(meta.get("design_sha", "—"))],
            ["Assessed against", "SOLIT² Engineering Guidance Annex 7"],
        ]),
    ]


def _standing(result: Result) -> list[str]:
    """What the reader must know before reading a single number."""
    note = result.meta.get("calibration_note")
    lines = ["## 1. Standing of this assessment", "",
             "This is a **predictive assessment**, not a test report. No physical "
             "fire test was performed. Every figure below is a model output.", ""]
    if note:
        lines += ["The engine's own calibration note, verbatim:", "",
                  f"> {note}", ""]
    lines += [
        "The tool is an independent evaluator. It does not select, endorse or "
        "certify a product, and it holds acceptance limits only where an authority "
        "has set them.", "",
    ]
    return lines


def _system(design: Design, result: Result) -> list[str]:
    t, f, n, z, v, d = (design.tunnel, design.fire, design.nozzles,
                        design.zones, design.ventilation, design.detection)
    mount, fp = n.mounting, f.footprint
    geom = section_geometry(design)
    velocity = (f"{v.velocity_ms:.2f} m/s" if v.velocity_ms is not None
                else f"{v.velocity_range_ms[0]:.2f}–{v.velocity_range_ms[1]:.2f} m/s")
    return [
        "## 2. The system as assessed", "",
        "### Tunnel", "",
        *_table(["Property", "Value"], [
            ["Section", f"{t.section} ({t.shape})"],
            ["Carriageway width", f"{geom.road_width_m:.2f} m"],
            ["Height to crown", f"{geom.crown_height_m:.2f} m"],
            ["Free cross-section", f"{geom.free_area_m2:.1f} m²"],
            ["Length", f"{t.length_m:.0f} m"],
            ["Bores covered", str(t.tubes)],
            ["Gradient", f"{t.gradient_pct:.1f} %"],
            ["Ambient", f"{t.ambient_temp_c:.1f} °C, {t.ambient_rh_pct:.0f} % RH"],
        ]),
        "### Fire load", "",
        *_table(["Property", "Value"], [
            ["Class", f"{f.fire_class} ({'solid' if f.fire_class == 'A' else 'pool'})"],
            ["Design heat release", f"{f.design_hrr_mw:.0f} MW"],
            ["Growth", f"{f.growth} (alpha {f.alpha:g} kW/s²)"],
            ["Incubation", f"{f.incubation_s:.0f} s"],
            ["Footprint", f"{fp.length_m:g} × {fp.width_m:g} m, "
                          f"{fp.base_height_m:g}–{fp.top_height_m:g} m high"],
            ["Offset to load centre from wall", f"{f.lane_centre_offset_from_wall_m:.2f} m"],
            ["Target standoff behind mock-up", f"{f.target_distance_m:.1f} m"],
        ]),
        "### Water mist system", "",
        *_table(["Property", "Value"], [
            ["K-factor", f"{n.k_factor_lpm_bar05:g} L/min·bar⁰·⁵"],
            ["Working pressure", f"{n.pressure_bar:g} bar"],
            ["Flow per head", f"{n.flow_per_head_lpm:.1f} L/min"],
            ["Droplet size (Sauter mean)",
             f"{n.smd_um(n.modes[0].id):.0f} µm"],
            ["Spray half-angle", f"{n.modes[0].cone_half_angle_deg:g}°"],
            ["Mounting", f"{mount.rows} row(s) at y {', '.join(f'{o:+.2f}' for o in mount.row_lateral_offsets_m)} m, "
                         f"{mount.height_above_carriageway_m:g} m above the carriageway"],
            ["Head pitch", f"{mount.pitch_m:g} m"],
            ["Zoning", f"{z.sections_simultaneous} × {z.section_length_m:g} m sections, "
                       f"{design.active_heads} heads discharging"],
            ["Activation delay after detection", f"{z.activation_delay_s:.0f} s"],
            ["Pump ramp", f"{z.pump_ramp_s:.0f} s"],
            ["Discharge duration", f"{z.duration_min:.0f} min"],
        ]),
        "### Ventilation and detection", "",
        *_table(["Property", "Value"], [
            ["Mode", v.mode],
            ["Velocity assessed", velocity],
            ["Detection", f"{d.type}, {d.threshold_c:.0f} °C, {d.sensor_spacing_m:g} m spacing"],
        ]),
        "### Hydraulics as sized", "",
        *_table(["Quantity", "Value"], _quantities(result.hydraulics)),
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
        "## 3. Instrumentation", "",
        "Annex 7 Table 5, station by station. Distances are from the mock-up centre.",
        "",
        *_table(["Station", "x (m)", "Sensors"], rows),
        "Within a cross-section carrying five or more thermocouples, the sensors are "
        "arranged as Annex 7 Figure 16 draws them: two on each side wall bracketing the "
        "load, one at the ceiling, and — where the plane cuts the mock-up — one beside "
        "the load and one above it.", "",
    ]


def _results(result: Result) -> list[str]:
    score = result.score
    unset = score["criteria_unset"]
    lines = [
        "## 4. Results", "",
        "### Acceptance criteria", "",
        *_table(["Criterion", "Value", "Limit", "Verdict", "Margin"],
                _criteria_rows(result.criteria)),
    ]
    if unset:
        lines += [
            f"**{len(unset)} of {len(result.criteria)} criteria carry no limit and were "
            f"not judged.** An unjudged criterion is not a passed one. Annex 7 §7.1 "
            f"leaves these values to the PMC / Authority's Engineer, and none has "
            f"been set here.", "",
        ]
    if result.constraints:
        lines += ["### The project's own engineering limits", "",
                  "Site and procurement limits, not acceptance criteria. A breach is a "
                  "penalty and a warning, never a failed gate.", "",
                  *_table(["Limit", "Value", "Limit", "Verdict", "Margin"],
                          _criteria_rows(result.constraints))]
    lines += ["### Peak values reached", "",
              *_table(["Quantity", "Value"], _quantities(result.peaks))]
    events = {k: v for k, v in result.events.items() if isinstance(v, (int, float))}
    if events:
        lines += ["### Event times", "",
                  *_table(["Event", "Test clock (s)"],
                          [[k.replace("_", " ").replace("t ", "").strip().capitalize(),
                            f"{v:.0f}"] for k, v in sorted(events.items(), key=lambda kv: kv[1])])]
    worst = result.worst_case
    lines += [
        "### Score", "",
        *_table(["Component", "Value"], [
            ["Total", f"{score['total']:.2f} / 10"],
            ["Gates passed", "yes" if score["gates_passed"] else "NO"],
            ["Gates failed", ", ".join(score["gates_failed"]) or "none"],
            *[[k, f"{v:.3f}"] for k, v in sorted(score["components"].items())],
            ["Penalties", ", ".join(score["penalties"]) or "none"],
        ]),
        f"Worst case across the assessed envelope: {worst.get('section', '—')} section at "
        f"{worst.get('velocity_ms', 0):.2f} m/s.", "",
    ]
    return lines


def _findings(result: Result) -> list[str]:
    lines = ["## 5. What this result does not establish", ""]
    if result.warnings:
        lines += ["Reported by the engine for this run:", ""]
        lines += [f"- {w}" for w in result.warnings] + [""]
    lines += [
        "- No physical fire test with this equipment has been performed. Every value "
        "is an extrapolation from the engine's reference cases.",
        "- A passed gate is not an approval. It means the criteria that carry a limit "
        "were met by the model.",
        "",
    ]
    return lines


def render(design: Design, result: Result, tier2: Result | None = None,
           validation: str | None = None) -> str:
    """The whole document. `tier2` and `validation` are included when supplied."""
    lines = (_identity(design, result) + _standing(result) + _system(design, result)
             + _instrumentation() + _results(result))
    if tier2 is not None:
        from solit2.reports import correlation
        lines += ["## 6. Tier 1 against Tier 2 (CFD)", "",
                  correlation.render(result, tier2), ""]
        if tier2.warnings:
            lines += ["What the CFD run reports about itself:", ""]
            lines += [f"- {w}" for w in tier2.warnings] + [""]
    if validation:
        lines += ["## 7. Engine standing against the reference tests", "",
                  "`solit2 validate`, verbatim. A miss here is a disagreement with a "
                  "measured full-scale test and is a property of the engine, not of "
                  "this design.", "", "```", validation.rstrip(), "```", ""]
    lines += _findings(result)
    if design.meta.notes:
        lines += ["## Appendix — the design's own notes", "", design.meta.notes, ""]
    return "\n".join(lines)

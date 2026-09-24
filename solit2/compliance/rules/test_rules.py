"""SOLIT2 clauses judged from the test designs and their Tier 1 runs."""
from __future__ import annotations

from collections.abc import Callable

from solit2.compliance.context import Context, target_ignited
from solit2.compliance.rules.base import Outcome, Rule, judge, needs
from solit2.engines.reduced.geometry import section_geometry
from solit2.reports import guidance as g
from solit2.reports.guidance import CONTENT_MARKERS
from solit2.schema.design import Design

TUNNEL = "Test tunnel"
CLASS_A = "Class A fire load"
CLASS_B = "Class B fire load"
ACTIVATION = "Activation"
SYSTEM = "System"
PROTOCOL = "Protocol"
ACCEPTANCE = "Acceptance"


def _every_test(value: Callable[[Design], float], ok: Callable[[float], bool],
                required: str, basis: str) -> Callable[[Context], Outcome]:
    """Judge one quantity on every test design; all must pass.

    Every use of this helper reads a plain design field, never a Tier 1
    result, so its basis kind is "planned" throughout.
    """
    def check(ctx: Context) -> Outcome:
        values = {cls: value(d) for cls, d in sorted(ctx.tests.items())}
        found = "; ".join(f"{cls}: {v:g}" for cls, v in values.items())
        return judge(all(ok(v) for v in values.values()), found, required, basis, "planned")
    return check


def _on_class(fire_class: str, value: Callable[[Design], float], ok: Callable[[float], bool],
              required: str, basis: str) -> Callable[[Context], Outcome]:
    """Judge one quantity on the test design of one fire class.

    Every use of this helper reads a plain design field, never a Tier 1
    result, so its basis kind is "planned" throughout.
    """
    def check(ctx: Context) -> Outcome:
        design = ctx.tests.get(fire_class)
        if design is None:
            return needs(f"test_designs.{fire_class}", required, "planned",
                         f"no Class {fire_class} test design in the spec")
        return judge(ok(value(design)), f"{value(design):g}", required, basis, "planned")
    return check


def _area(d: Design) -> float:
    return section_geometry(d).free_area_m2


def _height(d: Design) -> float:
    return section_geometry(d).crown_height_m


def _width(d: Design) -> float:
    return section_geometry(d).road_width_m


def _energy_gj(d: Design) -> float:
    return (d.fire.pallets or 0) * d.fire.energy_mj_per_pallet / 1000.0


def _wall_clearance(d: Design) -> float:
    return d.fire.lane_centre_offset_from_wall_m - d.fire.footprint.width_m / 2.0


def _pool_area(d: Design) -> float:
    pools = d.fire.pools
    return pools.length_m * pools.width_m if pools else 0.0


def _stricter(label: str) -> float:
    """The governing minimum where Annex 7 and the main document both set one."""
    for name, annex7, main, _unit, _ref in g.STRICTER_OF:
        if name == label:
            return max(annex7, main)
    raise KeyError(f"guidance.STRICTER_OF has no row {label!r}")


# Annex 7 Table 4: whether its REQUIRED Class A tests use the tarpaulin cover.
CLASS_A_REQUIRED_COVERED = any(row[4] == "required" and row[1].startswith("Class A")
                               and "with tarpaulin" in row[2] for row in g.MINIMUM_TESTS)


def _activation(event: str) -> Callable[[Context], Outcome]:
    """Annex 7 §5.2.8 option A timing, judged on the Class A test's Tier 1 timetable.

    §5.2.8 sits inside §5.2, Class A fire load -- Class B's own trigger timing
    is §5.3.7, a different rule with a different (and looser) bound, judged by
    `_class_b_trigger_planned` below. Applying THIS rule's bounds to the Class
    B test as well (as a prior version did, by looping over every test class)
    judged Class B against a requirement that is not its own.
    """
    required = {"after_ignition": f">= {g.ACTIVATION_MIN_AFTER_IGNITION_S:g} s after ignition",
                "after_detection": "after detection",
                "discharge": f">= {g.MIN_DISCHARGE_MIN:g} min after activation"}[event]

    def check(ctx: Context) -> Outcome:
        design, res = ctx.tests.get("A"), ctx.test_results.get("A")
        # Defensive: the spec model requires a Class A test design, so this
        # branch should be unreachable in practice.
        if design is None or res is None:
            return needs("test_designs.A", required, "predicted",
                         "no Class A test design in the spec")
        t_act, t_det = res.events["t_activate_s"], res.events["t_detect_s"]
        if event == "after_ignition":
            ok, found = t_act >= g.ACTIVATION_MIN_AFTER_IGNITION_S, f"{t_act:.0f} s after ignition"
        elif event == "after_detection":
            ok = t_act > t_det
            found = f"detection {t_det:.0f} s, activation {t_act:.0f} s"
        else:  # discharge
            discharge_min = (design.zones.duration_min * 60.0 - t_act) / 60.0
            ok, found = discharge_min >= g.MIN_DISCHARGE_MIN, f"{discharge_min:.1f} min after activation"
        return judge(ok, found, required, "Tier 1 activation timetable (Class A)", "predicted")
    return check


def _class_b_trigger_planned(ctx: Context) -> Outcome:
    """Annex 7 §5.3.7 trigger timing, judged on the Class B test's Tier 1 timetable.

    The lab-evidenced counterpart is `annex7.5_3_7.trigger` (lab_rules.py),
    which judges the MEASURED trigger time once the test has run. Before that,
    this is the Tier 1 prediction the same clause reduces to.
    """
    required = f"<= {g.CLASS_B_TRIGGER_WITHIN_S:g} s after ignition"
    design, res = ctx.tests.get("B"), ctx.test_results.get("B")
    if design is None or res is None:
        return needs("test_designs.B", required, "predicted", "no Class B test design in the spec")
    t_act = res.events["t_activate_s"]
    return judge(t_act <= g.CLASS_B_TRIGGER_WITHIN_S, f"{t_act:.0f} s", required,
                 "Tier 1 activation timetable (Class B)", "predicted")


def _pressure_spread(ctx: Context) -> Outcome:
    rows, ok = [], True
    for cls, res in sorted(ctx.test_results.items()):
        spread = 100.0 * res.hydraulics["zone_loss_bar"] / ctx.tests[cls].nozzles.pressure_bar
        ok &= spread <= g.NOZZLE_SPREAD_MAX_PCT
        rows.append(f"{cls}: {spread:.1f} %")
    return judge(ok, "; ".join(rows), f"<= {g.NOZZLE_SPREAD_MAX_PCT:g} % first to last nozzle",
                 "Tier 1 hydraulics: zone pipe loss against the design pressure", "predicted")


def _protocol(ctx: Context) -> Outcome:
    missing = sorted({key for text in ctx.protocol_text.values()
                      for key, marker in CONTENT_MARKERS.items() if marker not in text})
    return judge(not missing and bool(ctx.protocol_text),
                 "all present" if not missing else "missing: " + ", ".join(missing),
                 f"all {len(g.PROTOCOL_CONTENTS)} Annex 7 §8.2 contents",
                 "the generated fire test protocol", "planned")


def _target(ctx: Context) -> Outcome:
    ignited = {cls: target_ignited(res) for cls, res in sorted(ctx.test_results.items())}
    found = "; ".join(f"{cls}: {'ignited' if v else 'not ignited'}" for cls, v in ignited.items())
    return judge(not any(ignited.values()), found, "target not ignited",
                 "Tier 1 prediction (replaced by the measurement after the test)", "predicted")


RULES: tuple[Rule, ...] = (
    # --- Test tunnel: Annex 7 §3.6 and main document §3.6.2, both bind (STRICTER_OF).
    Rule("annex7.3_6.free_area", TUNNEL, "Annex 7 §3.6",
         "Test tunnel free cross-section of at least the Annex 7 minimum.", "design",
         _every_test(_area, lambda v: v >= g.MIN_TEST_TUNNEL["free area (m2)"],
                     f">= {g.MIN_TEST_TUNNEL['free area (m2)']:g} m²", "test design geometry"),
         waivable=True, constants=("MIN_TEST_TUNNEL",)),
    Rule("annex7.3_6.height", TUNNEL, "Annex 7 §3.6",
         "Test tunnel height of at least the Annex 7 minimum.", "design",
         _every_test(_height, lambda v: v >= g.MIN_TEST_TUNNEL["height (m)"],
                     f">= {g.MIN_TEST_TUNNEL['height (m)']:g} m", "test design geometry"),
         waivable=True, constants=("MIN_TEST_TUNNEL",)),
    Rule("annex7.3_6.length", TUNNEL, "Annex 7 §3.6",
         "Test tunnel length of at least the Annex 7 minimum.", "design",
         _every_test(lambda d: d.tunnel.length_m, lambda v: v >= g.MIN_TEST_TUNNEL["length (m)"],
                     f">= {g.MIN_TEST_TUNNEL['length (m)']:g} m", "test design tunnel"),
         waivable=True, constants=("MIN_TEST_TUNNEL",)),
    Rule("main.3_6_2.height", TUNNEL, "Main document §3.6.2",
         "Test tunnel height of at least the main document's minimum, which is the stricter.",
         "design",
         _every_test(_height, lambda v: v >= _stricter("Test tunnel height"),
                     f">= {_stricter('Test tunnel height'):g} m", "test design geometry"),
         constants=("STRICTER_OF",)),
    Rule("main.3_6_2.width", TUNNEL, "Main document §3.6.2",
         "Test tunnel width of at least the main document's minimum.", "design",
         _every_test(_width, lambda v: v >= g.MAIN_MIN_TEST_TUNNEL["width (m)"],
                     f">= {g.MAIN_MIN_TEST_TUNNEL['width (m)']:g} m", "test design geometry"),
         constants=("MAIN_MIN_TEST_TUNNEL",)),
    Rule("main.3_6_2.length", TUNNEL, "Main document §3.6.2",
         "Test tunnel length of at least the main document's minimum.", "design",
         _every_test(lambda d: d.tunnel.length_m,
                     lambda v: v >= _stricter("Test tunnel length"),
                     f">= {_stricter('Test tunnel length'):g} m", "test design tunnel"),
         constants=("STRICTER_OF",)),
    # --- Class A fire load, Annex 7 §5.2.
    Rule("annex7.5_2_1.potential", CLASS_A, "Annex 7 §5.2.1",
         "Class A design fire of at least the minimum unsuppressed potential.", "design",
         _on_class("A", lambda d: d.fire.design_hrr_mw,
                   lambda v: v >= g.CLASS_A_MIN_UNSUPPRESSED_MW,
                   f">= {g.CLASS_A_MIN_UNSUPPRESSED_MW:g} MW", "test design fire"),
         constants=("CLASS_A_MIN_UNSUPPRESSED_MW",)),
    Rule("annex7.5_2_2.pallets", CLASS_A, "Annex 7 §5.2.2",
         "At least the minimum number of pallets in the mock-up.", "design",
         _on_class("A", lambda d: float(d.fire.pallets or 0),
                   lambda v: v >= g.CLASS_A_MIN_PALLETS,
                   f">= {g.CLASS_A_MIN_PALLETS}", "test design fire"),
         constants=("CLASS_A_MIN_PALLETS",)),
    Rule("annex7.5_2_2.energy", CLASS_A, "Annex 7 §5.2.2",
         "Mock-up fuel energy within the stated range.", "design",
         _on_class("A", _energy_gj,
                   lambda v: g.CLASS_A_ENERGY_GJ[0] <= v <= g.CLASS_A_ENERGY_GJ[1],
                   f"{g.CLASS_A_ENERGY_GJ[0]:g}–{g.CLASS_A_ENERGY_GJ[1]:g} GJ",
                   "pallets × energy per pallet"),
         constants=("CLASS_A_ENERGY_GJ",)),
    Rule("annex7.5_2_2.height", CLASS_A, "Annex 7 §5.2.2", "Mock-up height of at least the minimum.",
         "design",
         _on_class("A", lambda d: d.fire.footprint.top_height_m,
                   lambda v: v >= g.MOCKUP_MIN_M["height"],
                   f">= {g.MOCKUP_MIN_M['height']:g} m", "test design footprint"),
         constants=("MOCKUP_MIN_M",)),
    Rule("annex7.5_2_2.fuel_height", CLASS_A, "Annex 7 §5.2.2",
         "Fuel part of the mock-up of at least the minimum height.", "design",
         _on_class("A", lambda d: d.fire.footprint.top_height_m - d.fire.footprint.base_height_m,
                   lambda v: v >= g.MOCKUP_MIN_M["fuel height"],
                   f">= {g.MOCKUP_MIN_M['fuel height']:g} m", "test design footprint"),
         constants=("MOCKUP_MIN_M",)),
    Rule("annex7.5_2_2.width", CLASS_A, "Annex 7 §5.2.2", "Mock-up width of at least the minimum.",
         "design",
         _on_class("A", lambda d: d.fire.footprint.width_m,
                   lambda v: v >= g.MOCKUP_MIN_M["width"],
                   f">= {g.MOCKUP_MIN_M['width']:g} m", "test design footprint"),
         constants=("MOCKUP_MIN_M",)),
    Rule("annex7.5_2_2.length", CLASS_A, "Annex 7 §5.2.2", "Mock-up length of at least the minimum.",
         "design",
         _on_class("A", lambda d: d.fire.footprint.length_m,
                   lambda v: v >= g.MOCKUP_MIN_M["length"],
                   f">= {g.MOCKUP_MIN_M['length']:g} m", "test design footprint"),
         constants=("MOCKUP_MIN_M",)),
    Rule("annex7.5_2_3.wall_clearance", CLASS_A, "Annex 7 §5.2.3",
         "Mock-up placed eccentrically, no further than the maximum from the side wall.", "design",
         _on_class("A", _wall_clearance, lambda v: 0.0 <= v <= g.MAX_WALL_CLEARANCE_M,
                   f"0–{g.MAX_WALL_CLEARANCE_M:g} m", "lane offset minus half the mock-up width"),
         constants=("MAX_WALL_CLEARANCE_M",)),
    Rule("annex7.5_2_6.target", CLASS_A, "Annex 7 §5.2.6",
         "Fire target the stated distance downstream of the mock-up.", "design",
         _on_class("A", lambda d: d.fire.target_distance_m,
                   lambda v: abs(v - g.TARGET_STANDOFF_M) < 1e-9,
                   f"{g.TARGET_STANDOFF_M:g} m", "test design fire"),
         constants=("TARGET_STANDOFF_M",)),
    Rule("annex7.5_4.covered", CLASS_A, "Annex 7 §5.4 Table 4",
         "The required Class A tests use the tarpaulin-covered mock-up.", "design",
         _on_class("A", lambda d: float(d.fire.covered), lambda v: v == CLASS_A_REQUIRED_COVERED,
                   "covered" if CLASS_A_REQUIRED_COVERED else "either", "test design fire"),
         constants=("MINIMUM_TESTS",)),
    # --- Class B fire load, Annex 7 §5.3.
    Rule("annex7.5_3_1.hrr", CLASS_B, "Annex 7 §5.3.1", "Class B pool fire of at least the minimum.",
         "design",
         _on_class("B", lambda d: d.fire.design_hrr_mw, lambda v: v >= g.CLASS_B_MIN_MW,
                   f">= {g.CLASS_B_MIN_MW:g} MW", "test design fire"),
         constants=("CLASS_B_MIN_MW",)),
    Rule("annex7.5_3_2.width", CLASS_B, "Annex 7 §5.3.2", "Pool mock-up of at least the minimum width.",
         "design",
         _on_class("B", lambda d: d.fire.footprint.width_m,
                   lambda v: v >= g.CLASS_B_POOL_MIN_M["width"],
                   f">= {g.CLASS_B_POOL_MIN_M['width']:g} m", "test design footprint"),
         constants=("CLASS_B_POOL_MIN_M",)),
    Rule("annex7.5_3_2.length", CLASS_B, "Annex 7 §5.3.2",
         "Pool mock-up of at least the minimum length.", "design",
         _on_class("B", lambda d: d.fire.footprint.length_m,
                   lambda v: v >= g.CLASS_B_POOL_MIN_M["length"],
                   f">= {g.CLASS_B_POOL_MIN_M['length']:g} m", "test design footprint"),
         constants=("CLASS_B_POOL_MIN_M",)),
    Rule("annex7.5_3_2.height", CLASS_B, "Annex 7 §5.3.2",
         "Pool no higher than the maximum above the road.", "design",
         _on_class("B", lambda d: d.fire.footprint.top_height_m,
                   lambda v: v <= g.CLASS_B_POOL_MIN_M["height above road"],
                   f"<= {g.CLASS_B_POOL_MIN_M['height above road']:g} m", "test design footprint"),
         constants=("CLASS_B_POOL_MIN_M",)),
    Rule("annex7.5_3_2.pool_area", CLASS_B, "Annex 7 §5.3.2",
         "Each pool at least the minimum area.", "design",
         _on_class("B", _pool_area, lambda v: v >= g.CLASS_B_SINGLE_POOL_MIN_M2,
                   f">= {g.CLASS_B_SINGLE_POOL_MIN_M2:g} m²", "test design pools"),
         constants=("CLASS_B_SINGLE_POOL_MIN_M2",)),
    Rule("annex7.5_3_7.trigger_planned", CLASS_B, "Annex 7 §5.3.7",
         "The system triggers within the maximum after ignition (Tier 1 prediction, "
         "ahead of the lab's measured trigger time).", "design", _class_b_trigger_planned,
         constants=("CLASS_B_TRIGGER_WITHIN_S",)),
    # --- Activation, Annex 7 §5.2.8 option A.
    Rule("annex7.5_2_8.after_ignition", ACTIVATION, "Annex 7 §5.2.8",
         "Option A: the system is activated no earlier than the minimum after ignition.",
         "design", _activation("after_ignition"), constants=("ACTIVATION_MIN_AFTER_IGNITION_S",)),
    Rule("annex7.5_2_8.after_detection", ACTIVATION, "Annex 7 §5.2.8",
         "Activation is delayed relative to detection.", "design", _activation("after_detection")),
    Rule("annex7.5_2_8.discharge", ACTIVATION, "Annex 7 §5.2.8",
         "The system discharges for at least the minimum after activation.", "design",
         _activation("discharge"), constants=("MIN_DISCHARGE_MIN",)),
    Rule("annex7.5_2_8.area", ACTIVATION, "Annex 7 §5.2.8",
         "The activated length is at least the stated multiple of the mock-up length.", "design",
         _every_test(lambda d: d.active_length_m / d.fire.footprint.length_m,
                     lambda v: v >= g.ACTIVATION_AREA_MIN_MULTIPLE,
                     f">= {g.ACTIVATION_AREA_MIN_MULTIPLE:g} × mock-up length",
                     "active length over mock-up length"),
         constants=("ACTIVATION_AREA_MIN_MULTIPLE",)),
    # --- System, protocol and acceptance.
    Rule("annex7.4.pressure_spread", SYSTEM, "Annex 7 §4",
         "Pressure difference from the first to the last nozzle within the maximum.", "design",
         _pressure_spread, constants=("NOZZLE_SPREAD_MAX_PCT",)),
    Rule("annex7.8_2.contents", PROTOCOL, "Annex 7 §8.2",
         "The fire test protocol covers every minimum content.", "design", _protocol,
         constants=("PROTOCOL_CONTENTS", "CONTENT_MARKERS")),
    Rule("annex7.7_2_1.target", ACCEPTANCE, "Annex 7 §7.2.1",
         "The fire does not spread to the target.", "design", _target),
)

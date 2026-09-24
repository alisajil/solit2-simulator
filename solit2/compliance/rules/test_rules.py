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
    """Judge one quantity on every test design; all must pass."""
    def check(ctx: Context) -> Outcome:
        values = {cls: value(d) for cls, d in sorted(ctx.tests.items())}
        found = "; ".join(f"{cls}: {v:g}" for cls, v in values.items())
        return judge(all(ok(v) for v in values.values()), found, required, basis)
    return check


def _on_class(fire_class: str, value: Callable[[Design], float], ok: Callable[[float], bool],
              required: str, basis: str) -> Callable[[Context], Outcome]:
    """Judge one quantity on the test design of one fire class."""
    def check(ctx: Context) -> Outcome:
        design = ctx.tests.get(fire_class)
        if design is None:
            return needs(f"test_designs.{fire_class}", required,
                         f"no Class {fire_class} test design in the spec")
        return judge(ok(value(design)), f"{value(design):g}", required, basis)
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


def _activation(event: str) -> Callable[[Context], Outcome]:
    """Annex 7 §5.2.8 option A timing, judged on every test's Tier 1 timetable."""
    def check(ctx: Context) -> Outcome:
        rows = []
        ok = True
        for cls, res in sorted(ctx.test_results.items()):
            t_act, t_det = res.events["t_activate_s"], res.events["t_detect_s"]
            if event == "after_ignition":
                ok &= t_act >= g.ACTIVATION_MIN_AFTER_IGNITION_S
                rows.append(f"{cls}: {t_act:.0f} s after ignition")
            elif event == "after_detection":
                ok &= t_act > t_det
                rows.append(f"{cls}: detection {t_det:.0f} s, activation {t_act:.0f} s")
            else:  # discharge
                design = ctx.tests[cls]
                discharge_min = (design.zones.duration_min * 60.0 - t_act) / 60.0
                ok &= discharge_min >= g.MIN_DISCHARGE_MIN
                rows.append(f"{cls}: {discharge_min:.1f} min after activation")
        required = {"after_ignition": f">= {g.ACTIVATION_MIN_AFTER_IGNITION_S:g} s after ignition",
                    "after_detection": "after detection",
                    "discharge": f">= {g.MIN_DISCHARGE_MIN:g} min after activation"}[event]
        return judge(ok, "; ".join(rows), required, "Tier 1 activation timetable")
    return check


def _pressure_spread(ctx: Context) -> Outcome:
    rows, ok = [], True
    for cls, res in sorted(ctx.test_results.items()):
        spread = 100.0 * res.hydraulics["zone_loss_bar"] / ctx.tests[cls].nozzles.pressure_bar
        ok &= spread <= g.NOZZLE_SPREAD_MAX_PCT
        rows.append(f"{cls}: {spread:.1f} %")
    return judge(ok, "; ".join(rows), f"<= {g.NOZZLE_SPREAD_MAX_PCT:g} % first to last nozzle",
                 "Tier 1 hydraulics: zone pipe loss against the design pressure")


def _protocol(ctx: Context) -> Outcome:
    missing = sorted({key for text in ctx.protocol_text.values()
                      for key, marker in CONTENT_MARKERS.items() if marker not in text})
    return judge(not missing and bool(ctx.protocol_text),
                 "all present" if not missing else "missing: " + ", ".join(missing),
                 f"all {len(g.PROTOCOL_CONTENTS)} Annex 7 §8.2 contents",
                 "the generated fire test protocol")


def _target(ctx: Context) -> Outcome:
    ignited = {cls: target_ignited(res) for cls, res in sorted(ctx.test_results.items())}
    found = "; ".join(f"{cls}: {'ignited' if v else 'not ignited'}" for cls, v in ignited.items())
    return judge(not any(ignited.values()), found, "target not ignited",
                 "Tier 1 prediction (replaced by the measurement after the test)")


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
         _every_test(_height, lambda v: v >= g.MAIN_MIN_TEST_TUNNEL["height (m)"],
                     f">= {g.MAIN_MIN_TEST_TUNNEL['height (m)']:g} m", "test design geometry"),
         constants=("MAIN_MIN_TEST_TUNNEL", "STRICTER_OF")),
    Rule("main.3_6_2.width", TUNNEL, "Main document §3.6.2",
         "Test tunnel width of at least the main document's minimum.", "design",
         _every_test(_width, lambda v: v >= g.MAIN_MIN_TEST_TUNNEL["width (m)"],
                     f">= {g.MAIN_MIN_TEST_TUNNEL['width (m)']:g} m", "test design geometry"),
         constants=("MAIN_MIN_TEST_TUNNEL",)),
    Rule("main.3_6_2.length", TUNNEL, "Main document §3.6.2",
         "Test tunnel length of at least the main document's minimum.", "design",
         _every_test(lambda d: d.tunnel.length_m,
                     lambda v: v >= g.MAIN_MIN_TEST_TUNNEL["length (m)"],
                     f">= {g.MAIN_MIN_TEST_TUNNEL['length (m)']:g} m", "test design tunnel"),
         constants=("MAIN_MIN_TEST_TUNNEL", "STRICTER_OF")),
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
         _on_class("A", lambda d: float(d.fire.covered), lambda v: v == 1.0,
                   "covered (1)", "test design fire"),
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

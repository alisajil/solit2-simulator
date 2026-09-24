"""Does the test's result transfer to the installation?

Annex 7 §3.3 lets a result transfer only while the protected tunnel sits inside
the tested parameters, Annex 3 §3.3 lists the parameters, and §3.4 does not let
CFD stand in for a test outside them. A single tested value is a range of one:
the installation must equal it. The main document relaxes one parameter, the
nozzle-to-load distance, to at most 20 % more than tested.
"""
from __future__ import annotations

from collections.abc import Callable

from solit2.compliance.context import (Context, hrr_at_mw, standoff_m,
                                       time_to_full_operation_s, tested_velocities_ms)
from solit2.compliance.rules.base import Outcome, Rule, judge, needs
from solit2.reports import guidance as g
from solit2.schema.design import Design

GROUP = "Transfer to the installation"
REL_TOL = 1e-9


def _pair(ctx: Context) -> tuple[Design, str] | None:
    cls = ctx.installation.fire.fire_class
    return (ctx.tests[cls], cls) if cls in ctx.tests else None


def _transfer(body: Callable[[Context, Design, str], Outcome], required: str) -> Callable[[Context], Outcome]:
    def check(ctx: Context) -> Outcome:
        pair = _pair(ctx)
        if pair is None:
            cls = ctx.installation.fire.fire_class
            return needs(f"test_designs.{cls}", required,
                         f"no Class {cls} test design to transfer from")
        return body(ctx, *pair)
    return check


def _equal(a: float, b: float) -> bool:
    return abs(a - b) <= REL_TOL * max(abs(a), abs(b), 1.0)


def _response(ctx: Context, test: Design, cls: str) -> Outcome:
    inst_s = time_to_full_operation_s(ctx.installation_result)
    test_s = time_to_full_operation_s(ctx.test_results[cls])
    return judge(inst_s <= test_s, f"installation {inst_s:.0f} s", f"<= tested {test_s:.0f} s",
                 "Tier 1 detection-to-full-pressure, both designs (predicted)")


def _k_factor(ctx: Context, test: Design, cls: str) -> Outcome:
    i, t = ctx.installation.nozzles, test.nozzles
    ok = i.preset == t.preset and _equal(i.k_factor_lpm_bar05, t.k_factor_lpm_bar05)
    return judge(ok, f"{i.preset}, K {i.k_factor_lpm_bar05:g}", f"{t.preset}, K {t.k_factor_lpm_bar05:g}",
                 "nozzle blocks of both designs")


def _pressure(ctx: Context, test: Design, cls: str) -> Outcome:
    fact = ctx.facts.tested_pressure_bar
    lo, hi = fact.value if fact else (test.nozzles.pressure_bar, test.nozzles.pressure_bar)
    p = ctx.installation.nozzles.pressure_bar
    basis = f"tested range ({fact.evidence.cite()})" if fact else "the test design's single pressure"
    return judge(lo - REL_TOL <= p <= hi + REL_TOL, f"{p:g} bar", f"{lo:g}–{hi:g} bar", basis)


def _positions(ctx: Context, test: Design, cls: str) -> Outcome:
    i, t = ctx.installation.nozzles.mounting, test.nozzles.mounting
    ok = (i.rows == t.rows and i.tilt_deg == t.tilt_deg
          and all(_equal(a, b) for a, b in zip(i.row_lateral_offsets_m, t.row_lateral_offsets_m)))
    return judge(ok, f"{i.rows} rows at {list(i.row_lateral_offsets_m)}, tilt {i.tilt_deg:g}°",
                 f"{t.rows} rows at {list(t.row_lateral_offsets_m)}, tilt {t.tilt_deg:g}°",
                 "mounting blocks of both designs")


def _spacing(ctx: Context, test: Design, cls: str) -> Outcome:
    i, t = ctx.installation.nozzles.mounting.pitch_m, test.nozzles.mounting.pitch_m
    return judge(_equal(i, t), f"{i:g} m", f"{t:g} m", "mounting pitch of both designs")


def _standoff(ctx: Context, test: Design, cls: str) -> Outcome:
    inst, tested = standoff_m(ctx.installation), standoff_m(test)
    most = tested * (1.0 + g.MAIN_MAX_STANDOFF_EXCESS_PCT / 100.0)
    ok = tested - REL_TOL <= inst <= most + REL_TOL
    return judge(ok, f"{inst:.2f} m", f"{tested:.2f}–{most:.2f} m",
                 "nozzle height minus fire-load top, both designs")


def _ventilation(ctx: Context, test: Design, cls: str) -> Outcome:
    tested, basis = tested_velocities_ms(ctx, cls)
    lo, hi = ctx.installation.ventilation.velocity_range_ms
    ok = bool(tested) and min(tested) <= lo and hi <= max(tested)
    return judge(ok, f"{lo:g}–{hi:g} m/s",
                 f"inside {min(tested):g}–{max(tested):g} m/s" if tested else "a tested velocity",
                 basis)


def _fire_at_activation(ctx: Context, test: Design, cls: str) -> Outcome:
    inst_r, test_r = ctx.installation_result, ctx.test_results[cls]
    inst_mw = hrr_at_mw(inst_r, inst_r.events["t_activate_s"])
    test_mw = hrr_at_mw(test_r, test_r.events["t_activate_s"])
    return judge(inst_mw <= test_mw + REL_TOL, f"{inst_mw:.1f} MW", f"<= tested {test_mw:.1f} MW",
                 "Tier 1 HRR at activation, both designs (predicted)")


def _zones(field: str) -> Callable[[Context, Design, str], Outcome]:
    def body(ctx: Context, test: Design, cls: str) -> Outcome:
        i, t = getattr(ctx.installation.zones, field), getattr(test.zones, field)
        return judge(_equal(float(i), float(t)), f"{i:g}", f"{t:g}", f"zones.{field}, both designs")
    return body


def _no_extrapolation(ctx: Context, test: Design, cls: str) -> Outcome:
    outside = [name for name, body in (("ventilation", _ventilation), ("pressure", _pressure),
                                       ("standoff", _standoff))
               if body(ctx, test, cls).verdict.value != "complies"]
    return judge(not outside, "outside the tested envelope: " + ", ".join(outside) if outside
                 else "inside the tested envelope", "no parameter outside the tested envelope",
                 "the ventilation, pressure and standoff transfer checks")


def _t(rule_id: str, clause: str, requirement: str, parameter: str | None,
       body: Callable[[Context, Design, str], Outcome], required: str, *constants: str) -> Rule:
    if parameter is not None and parameter not in g.TEST_DERIVED_PARAMETERS:
        raise ValueError(f"{parameter!r} is not an Annex 3 §3.3 test-derived parameter")
    text = requirement if parameter is None else f"{requirement} (Annex 3 §3.3: {parameter})"
    return Rule(rule_id, GROUP, clause, text, "transfer", _transfer(body, required),
                constants=constants)


RULES: tuple[Rule, ...] = (
    _t("annex7.3_2.response", "Annex 7 §3.2, Annex 3 §3.3",
       "The installation detects and reaches full operation at least as fast as the test.",
       "Time to full operation",
       _response, "no slower than tested", "TEST_DERIVED_PARAMETERS"),
    _t("annex3.3_3.k_factor", "Annex 3 §3.3", "Same nozzle type and K-factor as tested.",
       "Nozzle types and K-factors",
       _k_factor, "the tested nozzle", "TEST_DERIVED_PARAMETERS"),
    _t("annex3.3_3.pressure", "Annex 3 §3.3", "Working pressure inside the tested range.",
       "Minimum and maximum working pressure",
       _pressure, "inside the tested range", "TEST_DERIVED_PARAMETERS"),
    _t("annex3.3_3.positions", "Annex 3 §3.3", "Nozzle positions as tested.",
       "Nozzle positions",
       _positions, "the tested positions", "TEST_DERIVED_PARAMETERS"),
    _t("annex3.3_3.spacing", "Annex 3 §3.3", "Nozzle spacing as tested.",
       "Nozzle spacing, longitudinal and transversal",
       _spacing, "the tested spacing", "TEST_DERIVED_PARAMETERS"),
    _t("main.3_6_2.standoff", "Main document §3.6.2, Annex 3 §3.3",
       "Nozzle-to-load distance no less than tested and at most the stated excess over it.",
       "Minimum and maximum installation height",
       _standoff, "tested to tested + 20 %", "MAIN_MAX_STANDOFF_EXCESS_PCT",
       "TEST_DERIVED_PARAMETERS"),
    _t("annex3.3_3.ventilation", "Annex 3 §3.3, Annex 7 §3.3",
       "Installation ventilation inside the tested velocities.",
       "Minimum and maximum ventilation conditions",
       _ventilation,
       "inside the tested velocities", "TEST_DERIVED_PARAMETERS"),
    _t("annex3.3_3.fire_at_activation", "Annex 3 §3.3",
       "Fire at activation no larger than tested.",
       "Maximum fire size at activation",
       _fire_at_activation,
       "no larger than tested", "TEST_DERIVED_PARAMETERS"),
    _t("annex3.3_3.section_length", "Annex 3 §3.3", "Section length as tested.",
       "Minimum and maximum section lengths",
       _zones("section_length_m"), "the tested section length", "TEST_DERIVED_PARAMETERS"),
    _t("annex3.3_3.sections_simultaneous", "Annex 3 §3.3",
       "Number of sections activated together as tested.",
       "Minimum and maximum number of sections activated simultaneously",
       _zones("sections_simultaneous"), "the tested number", "TEST_DERIVED_PARAMETERS"),
    _t("annex7.3_4.no_extrapolation", "Annex 7 §3.4",
       "No parameter outside the tested envelope, which CFD may not supply.",
       None,
       _no_extrapolation, "inside the tested envelope"),
)

"""SOLIT2 clauses only the laboratory can evidence.

Every rule here reads one `Facts` field. No fact, no verdict beyond Needs
evidence: the checker never assumes a laboratory did what the standard asks.
"""
from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any

from solit2.compliance.context import Context
from solit2.compliance.rules.base import Outcome, Rule, judge, needs
from solit2.reports import guidance as g

CLASS_A = "Class A fire load"
CLASS_B = "Class B fire load"
VENTILATION = "Ventilation"
ACTIVATION = "Activation"
SYSTEM = "System"
INSTRUMENTS = "Instruments"
PROGRAMME = "Test programme"
NOZZLE = "Nozzle"
ACCEPTANCE = "Acceptance"


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", text.lower()).strip("_")


def _fact(name: str, ok: Callable[[Any], bool], required: str,
          show: Callable[[Any], str] = str) -> Callable[[Context], Outcome]:
    """Every rule in this module reads one `Facts` field, so its basis kind is
    "evidenced" throughout -- there is nothing else it could be judged on."""
    def check(ctx: Context) -> Outcome:
        fact = getattr(ctx.facts, name)
        if fact is None:
            return needs(name, required, "evidenced")
        return judge(ok(fact.value), show(fact.value), required, "spec fact", "evidenced",
                     fact.evidence.cite())
    return check


def _contains(name: str, item: str, required: str) -> Callable[[Context], Outcome]:
    return _fact(name, lambda values: item in values, required, lambda v: ", ".join(map(str, v)))


def _option(ctx: Context) -> Outcome:
    fact = ctx.facts.activation_option
    required = "option A, whose timing Annex 7 states"
    if fact is None:
        return needs("activation_option", required, "evidenced")
    if fact.value == "B":
        return needs("activation_option", required, "evidenced",
                     "option B declared; Annex 7 leaves its content blank, so it cannot be judged")
    return judge(True, "option A", required, "spec fact", "evidenced", fact.evidence.cite())


def _required_test(row: tuple[str, ...]) -> Callable[[Context], Outcome]:
    fire_class = "A" if row[1].startswith("Class A") else "B"
    covered = "with tarpaulin" in row[2]
    velocity = float(row[3].split()[0])
    if velocity not in g.TEST_VELOCITIES_MS:
        raise ValueError(f"Annex 7 Table 4 row {row[0]} names {velocity:g} m/s, which is not "
                         f"one of the §5.2.7 test velocities {g.TEST_VELOCITIES_MS}")
    required = f"{row[1]}, {row[2]}, {row[3]}"

    def check(ctx: Context) -> Outcome:
        fact = ctx.facts.planned_tests
        if fact is None:
            return needs("planned_tests", required, "evidenced")
        found = any(t.fire_class == fire_class and t.velocity_ms == velocity
                    and (fire_class == "B" or t.covered == covered) for t in fact.value)
        return judge(found, "planned" if found else "not in the planned tests", required,
                     "spec fact", "evidenced", fact.evidence.cite())
    return check


def _authority_limits(ctx: Context) -> Outcome:
    required = "every Annex 7 §7 limit set by a cited authority"
    fact = ctx.facts.authority_limits
    if fact is None:
        return needs("authority_limits", required, "evidenced")
    unset = [k for k, v in ctx.installation.ahj.model_dump().items()
             if k not in ("note", "structure_temp_threshold_c") and v is None]
    if unset:
        return needs("authority_limits", required, "evidenced",
                     "limits still unset: " + ", ".join(unset))
    return judge(True, "all set", required, "installation design ahj block", "evidenced",
                 fact.evidence.cite())


def _velocity_station(ctx: Context) -> Outcome:
    required = "; ".join(f"{k}: U{v:g}" for k, v in sorted(g.VELOCITY_STATION_M.items()))
    fact = ctx.facts.velocity_measured_at_m
    if fact is None:
        return needs("velocity_measured_at_m", required, "evidenced")
    ok = all(fact.value.get(cls) == g.VELOCITY_STATION_M[cls] for cls in ctx.tests)
    return judge(ok, "; ".join(f"{k}: U{v:g}" for k, v in sorted(fact.value.items())),
                 required, "spec fact", "evidenced", fact.evidence.cite())


def _lab(rule_id: str, group: str, clause: str, requirement: str,
         check: Callable[[Context], Outcome], *constants: str) -> Rule:
    return Rule(rule_id, group, clause, requirement, "lab", check, constants=constants)


_INSTRUMENT_RULES = tuple(
    _lab(f"annex7.{clause.lstrip('§').replace('.', '_')}.{_slug(name)}", INSTRUMENTS,
         f"Annex 7 {clause}",
         f"{name} measured with the stated range ({rng}) and accuracy ({acc}).",
         _contains("instruments_compliant", name, f"{name}: {rng}, {acc}"), "INSTRUMENT_SPEC")
    for name, _code, _kind, rng, acc, clause in g.INSTRUMENT_SPEC
)

_SCHEDULE_RULES = tuple(
    _lab(f"main.3_6_2.schedule.{_slug(item)}", INSTRUMENTS, "Main document §3.6.2",
         f"Measurement schedule: {item} — {where}.",
         _contains("measurement_schedule", item, where), "MAIN_MEASUREMENT_SCHEDULE")
    for item, where in g.MAIN_MEASUREMENT_SCHEDULE
)

_PROGRAMME_RULES = tuple(
    _lab(f"annex7.5_4.test_{row[0]}", PROGRAMME, "Annex 7 §5.4 Table 4",
         f"Required test {row[0]} is in the programme.", _required_test(row),
         "MINIMUM_TESTS", "TEST_VELOCITIES_MS")
    for row in g.MINIMUM_TESTS if row[4] == "required"
)

RULES: tuple[Rule, ...] = (
    _lab("annex7.5_2_4.pallet_size", CLASS_A, "Annex 7 §5.2.4", "Pallets of the stated size.",
         _fact("pallet_dims_mm", lambda v: tuple(v) == tuple(map(float, g.PALLET_MM)),
               "×".join(map(str, g.PALLET_MM)) + " mm"), "PALLET_MM"),
    _lab("annex7.5_2_4.pallet_mass", CLASS_A, "Annex 7 §5.2.4", "Pallet mass within the stated range.",
         _fact("pallet_mass_kg",
               lambda v: g.PALLET_MASS_KG[0] <= v[0] and v[1] <= g.PALLET_MASS_KG[1],
               f"{g.PALLET_MASS_KG[0]:g}–{g.PALLET_MASS_KG[1]:g} kg"), "PALLET_MASS_KG"),
    _lab("annex7.5_2_4.moisture", CLASS_A, "Annex 7 §5.2.4", "Pallet moisture within the maximum.",
         _fact("pallet_moisture_pct", lambda v: v <= g.MAX_PALLET_MOISTURE_PCT,
               f"<= {g.MAX_PALLET_MOISTURE_PCT:g} %"), "MAX_PALLET_MOISTURE_PCT"),
    _lab("annex7.5_2_2.frames", CLASS_A, "Annex 7 §5.2.2",
         "Steel frames cover no more than the maximum of the fuel faces.",
         _fact("frame_coverage_pct", lambda v: v <= g.FRAME_COVERAGE_MAX_PCT,
               f"<= {g.FRAME_COVERAGE_MAX_PCT:g} %"), "FRAME_COVERAGE_MAX_PCT"),
    _lab("annex7.5_2_2.tarpaulin", CLASS_A, "Annex 7 §5.2.2", "The tarpaulin cover is fitted.",
         _fact("tarpaulin_fitted", lambda v: v is True, "fitted")),
    _lab("annex7.5_2_5.pans", CLASS_A, "Annex 7 §5.2.5", "At least the stated number of ignition pans.",
         _fact("ignition_pans", lambda v: v >= g.IGNITION_PANS, f">= {g.IGNITION_PANS}"),
         "IGNITION_PANS"),
    _lab("annex7.5_2_5.pan_size", CLASS_A, "Annex 7 §5.2.5", "Ignition pans of the stated size.",
         _fact("ignition_pan_mm", lambda v: tuple(v) == tuple(map(float, g.IGNITION_PAN_MM)),
               "×".join(map(str, g.IGNITION_PAN_MM)) + " mm"), "IGNITION_PAN_MM"),
    _lab("annex7.5_2_5.petrol", CLASS_A, "Annex 7 §5.2.5", "The stated volume of petrol in each pan.",
         _fact("ignition_petrol_l", lambda v: v == g.IGNITION_PETROL_L,
               f"{g.IGNITION_PETROL_L:g} L per pan"), "IGNITION_PETROL_L"),
    _lab("annex7.5_3_4.free_burn", CLASS_B, "Annex 7 §5.3.4",
         "Enough fuel to burn unsuppressed for at least the minimum.",
         _fact("class_b_free_burn_min", lambda v: v >= g.CLASS_B_MIN_BURN_MIN,
               f">= {g.CLASS_B_MIN_BURN_MIN:g} min"), "CLASS_B_MIN_BURN_MIN"),
    _lab("annex7.5_3_5.ignition", CLASS_B, "Annex 7 §5.3.5", "All pools ignited within the maximum.",
         _fact("class_b_ignition_s", lambda v: v <= g.CLASS_B_IGNITION_WITHIN_S,
               f"<= {g.CLASS_B_IGNITION_WITHIN_S:g} s"), "CLASS_B_IGNITION_WITHIN_S"),
    _lab("annex7.5_3_7.trigger", CLASS_B, "Annex 7 §5.3.7", "The system triggered within the maximum.",
         _fact("class_b_trigger_s", lambda v: v <= g.CLASS_B_TRIGGER_WITHIN_S,
               f"<= {g.CLASS_B_TRIGGER_WITHIN_S:g} s"), "CLASS_B_TRIGGER_WITHIN_S"),
    _lab("annex7.5_2_7.velocity_station", VENTILATION, "Annex 7 §5.2.7, §5.3.6",
         "Ventilation velocity measured at the stated upstream station.", _velocity_station,
         "VELOCITY_STATION_M"),
    _lab("annex7.5_2_8.option", ACTIVATION, "Annex 7 §5.2.8",
         "The activation option used is declared.", _option),
    _lab("annex7.6_4_7.flow", SYSTEM, "Annex 7 §6.4.7", "Measured flow within the tolerance.",
         _fact("flow_deviation_pct", lambda v: abs(v) <= g.FLOW_TOLERANCE_PCT,
               f"± {g.FLOW_TOLERANCE_PCT:g} %"), "FLOW_TOLERANCE_PCT"),
    _lab("annex7.6_4_6.last_nozzle", SYSTEM, "Annex 7 §6.4.6",
         "Pressure measured at the hydraulically last nozzle.",
         _fact("last_nozzle_pressure_measured", lambda v: v is True, "measured")),
    *_INSTRUMENT_RULES,
    _lab("annex7.table5.layout", INSTRUMENTS, "Annex 7 §6.3 Table 5",
         "Instruments at every Table 5 station.",
         _fact("table5_layout", lambda v: v is True, "every Table 5 station instrumented")),
    _lab("main.3_6_2.sampling", INSTRUMENTS, "Main document §3.6.2",
         "Data measured and collated at least as often as stated.",
         _fact("sampling_interval_s", lambda v: v <= g.MAIN_MAX_SAMPLE_INTERVAL_S,
               f"<= {g.MAIN_MAX_SAMPLE_INTERVAL_S:g} s"), "MAIN_MAX_SAMPLE_INTERVAL_S"),
    *_SCHEDULE_RULES,
    _lab("annex7.6_5.hrr_method", INSTRUMENTS, "Annex 7 §6.5",
         "Heat release rate by oxygen consumption.",
         _fact("hrr_method", lambda v: v.strip().lower() == "oxygen consumption",
               "oxygen consumption")),
    _lab("annex7.6_5.hrr_delay", INSTRUMENTS, "Annex 7 §6.5",
         "Heat release rate measurement delay within the maximum.",
         _fact("hrr_delay_s", lambda v: v <= g.HRR_MAX_DELAY_S, f"<= {g.HRR_MAX_DELAY_S:g} s"),
         "HRR_MAX_DELAY_S"),
    _lab("annex7.6_2.calibration", INSTRUMENTS, "Annex 7 §6.2",
         "Calibration fires of each stated size.",
         _fact("calibration_fires_mw", lambda v: all(mw in v for mw in g.CALIBRATION_POOL_MW),
               " and ".join(f"{mw:g} MW" for mw in g.CALIBRATION_POOL_MW),
               lambda v: ", ".join(f"{mw:g} MW" for mw in v)), "CALIBRATION_POOL_MW"),
    *_PROGRAMME_RULES,
    _lab("main.3_6_2.series", PROGRAMME, "Main document §3.6.2",
         "At least the stated number of test series.",
         _fact("test_series", lambda v: v >= g.MAIN_MIN_TEST_SERIES,
               f">= {g.MAIN_MIN_TEST_SERIES}"), "MAIN_MIN_TEST_SERIES"),
    _lab("main.3_6_2.droplet_distribution", NOZZLE, "Main document §3.6.2",
         "The exact nozzle is tested, with its droplet distribution documented.",
         _fact("droplet_distribution_report", lambda v: bool(v.strip()), "a measured report")),
    _lab("main.3_6_2.spray_deviation", NOZZLE, "Main document §3.6.2",
         "The spray's deviation in the airflow defined at least at the stated velocities.",
         _fact("spray_deviation_tested_ms",
               lambda v: all(ms in v for ms in g.MAIN_SPRAY_DEVIATION_MS),
               ", ".join(f"{ms:g}" for ms in g.MAIN_SPRAY_DEVIATION_MS) + " m/s",
               lambda v: ", ".join(f"{ms:g}" for ms in v) + " m/s"), "MAIN_SPRAY_DEVIATION_MS"),
    _lab("annex7.7_1.authority_limits", ACCEPTANCE, "Annex 7 §7.1",
         "Every acceptance limit other than the target is set by the authority.",
         _authority_limits),
)

# solit2/reports/virtual_test.py
"""The virtual fire test report: a full-scale-test-shaped HTML document
predicting the outcome of the SOLIT2 tests a compliance spec names, entirely
from this tool's own Tier 1 output. Every section builder here is a pure
function over already-computed Design/Result/RunTrace/ComplianceReport
objects; solit2/cli.py does the loading and running.
"""
from __future__ import annotations

from solit2.compliance.spec import LoadedSpec
from solit2.reports import html
from solit2.schema.result import Result
from solit2.engines.reduced.geometry import section_geometry


def _introduction() -> str:
    return (
        "<p>This report predicts the outcome of the planned SOLIT² Annex 7 "
        "tests, laid out in the shape a full-scale fire test report uses, so the "
        "real test report can later be placed beside it section by section. "
        "It is not a measurement: every figure in it comes from this tool's own "
        "Tier 1 (and, once run, Tier 2 CFD) engine, never from an instrument.</p>")


def _requested_tests(loaded: LoadedSpec) -> str:
    rows = [[cls, design.meta.name, design.fire.preset,
            f"{design.fire.design_hrr_mw:.0f} MW",
            f"{design.ventilation.velocity_range_ms[0]:.2f}–"
            f"{design.ventilation.velocity_range_ms[1]:.2f} m/s",
            f"{design.zones.duration_min:.0f} min"]
            for cls, design in sorted(loaded.tests.items())]
    return html.table(["Test", "Design", "Fire class", "Design HRR",
                       "Ventilation", "Duration"], rows)


def _facility(loaded: LoadedSpec) -> str:
    rows = [[cls, design.meta.name, design.tunnel.preset, design.tunnel.section,
            f"{section_geometry(design).road_width_m:.2f} m",
            f"{section_geometry(design).crown_height_m:.2f} m",
            f"{design.ventilation.velocity_range_ms[0]:.2f}–"
            f"{design.ventilation.velocity_range_ms[1]:.2f} m/s"]
            for cls, design in sorted(loaded.tests.items())]
    return html.table(["Test", "Design", "Tunnel preset", "Section",
                       "Road width", "Crown height", "Ventilation band"], rows)


def _water_mist_system(loaded: LoadedSpec) -> str:
    rows = []
    for cls, design in sorted(loaded.tests.items()):
        n = design.nozzles
        rows.append([cls, n.preset, f"{n.k_factor_lpm_bar05:.2f}", f"{n.pressure_bar:.1f} bar",
                    f"{n.flow_per_head_lpm:.1f} L/min", f"{design.zones.section_length_m:.0f} m",
                    str(design.active_heads),
                    f"{n.k_factor_lpm_bar05 * design.active_heads:.1f}"])
    return html.table(["Test", "Nozzle preset", "K-factor", "Pressure", "Flow per head",
                       "Zone length", "Active heads", "Total K"], rows)


def _fire_load(loaded: LoadedSpec) -> str:
    rows = [[cls, design.fire.preset, "covered" if design.fire.covered else "uncovered",
            f"{design.fire.design_hrr_mw:.0f} MW"]
            for cls, design in sorted(loaded.tests.items())]
    return html.table(["Test", "Fire preset", "Cover", "Design HRR"], rows)


def render(loaded: LoadedSpec, results: dict[str, Result]) -> str:
    sections = [
        ("Introduction", _introduction()),
        ("Requested tests", _requested_tests(loaded)),
        ("Test facility", _facility(loaded)),
        ("Water mist system", _water_mist_system(loaded)),
        ("Fire load and target", _fire_load(loaded)),
    ]
    return html.document(f"Virtual fire test report — {loaded.spec.name}", sections)

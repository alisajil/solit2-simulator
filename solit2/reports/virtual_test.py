"""The virtual fire test report: a full-scale-test-shaped HTML document
predicting the outcome of the SOLIT2 tests a compliance spec names, entirely
from this tool's own Tier 1 output. Every section builder here is a pure
function over already-computed Design/Result/RunTrace/ComplianceReport
objects; solit2/cli.py does the loading and running.
"""
from __future__ import annotations

import plotly.graph_objects as go

from solit2.compliance.spec import LoadedSpec
from solit2.engines.reduced.criteria import STATIONS
from solit2.engines.reduced.geometry import section_geometry
from solit2.reports import html, labels
from solit2.schema.result import Result


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


def _instruments() -> str:
    rows = [[station, "temperature, heat flux, visibility, FED, CO, air velocity "
            "(where Annex 7 Table 5 places a sensor at this station)"]
            for station in STATIONS]
    return (
        "<p>Every station below is a modelled point, not a physical sensor: this is a "
        "prediction, and no instrument has been installed yet.</p>"
        + html.table(["Station", "What is modelled there"], rows))


def _procedure(loaded: LoadedSpec, results: dict[str, Result]) -> str:
    parts = [
        "<p>Ignition follows each design's own fire preset; detection is "
        "<code>linear_heat</code> at the threshold and spacing each design declares; "
        "activation follows detection by the design's own delay, or fires at a fixed "
        "time where the design pins it manually; the system then runs for the "
        "design's own declared duration. The performance criteria below are judged "
        "against each design's own <code>ahj</code> block.</p>"]
    for cls, design in sorted(loaded.tests.items()):
        result = results[cls]
        rows = []
        for key, criterion in sorted(result.criteria.items()):
            limit_text = ("limit not set" if criterion.status == "unset"
                         else labels.with_unit(key, criterion.limit))
            rows.append([labels.label(key), limit_text])
        parts.append(f"<h3>Test {cls}: {html.escape(design.meta.name)}</h3>")
        parts.append(html.table(["Criterion", "Limit"], rows))
    return "\n".join(parts)


# t² growth, Q = alpha * t² (Q in kW, t in s). Slow, medium, fast and ultra-fast
# growth as tabulated in NFPA 72 Annex B and the SFPE Handbook of Fire Protection
# Engineering. Reference shapes only -- see _results_overview's note.
GROWTH_CURVES = (("slow", 0.00293, "#c8c8c8"), ("medium", 0.01172, "#a0a0a0"),
                 ("fast", 0.0469, "#787878"), ("ultra-fast", 0.1876, "#505050"))
GROWTH_CURVE_POINTS = 200
HRR_AXIS_HEADROOM = 1.15   # the HRR axis stops 15 % above the highest engine curve
CHART_HEIGHT_PX = 420
CHART_MARGIN = {"l": 10, "r": 10, "t": 30, "b": 10}


class _Figures:
    """Hands the Plotly bundle to the first chart embedded and to no other.

    ponytail: one mutable flag. The bundle must exist exactly once per document
    and document order is build order; if sections are ever built out of order,
    move the bundle into html.document's <head> instead.
    """

    def __init__(self) -> None:
        self._bundle_written = False

    def embed(self, fig: go.Figure) -> str:
        first = not self._bundle_written
        self._bundle_written = True
        return html.figure_html(fig, first=first)


def _criteria_counts(result: Result) -> tuple[int, int, int]:
    statuses = [c.status for c in result.criteria.values()]
    return statuses.count("pass"), statuses.count("fail"), statuses.count("unset")


def _hrr_figure(results: dict[str, Result]) -> go.Figure:
    fig = go.Figure()
    top = 0.0
    for cls, result in sorted(results.items()):
        ts = result.timeseries
        fig.add_trace(go.Scatter(x=ts["t_s"], y=ts["hrr_mw"], mode="lines",
                                 name=f"Test {cls} — suppressed"))
        fig.add_trace(go.Scatter(x=ts["t_s"], y=ts["hrr_free_burn_mw"], mode="lines",
                                 line={"dash": "dash"}, name=f"Test {cls} — free burn"))
        top = max(top, max(ts["hrr_free_burn_mw"]))
    t_end = max(result.timeseries["t_s"][-1] for result in results.values())
    grid = [t_end * i / GROWTH_CURVE_POINTS for i in range(GROWTH_CURVE_POINTS + 1)]
    for name, alpha, colour in GROWTH_CURVES:
        fig.add_trace(go.Scatter(x=grid, y=[alpha * t * t / 1000.0 for t in grid],
                                 mode="lines", line={"dash": "dot", "color": colour},
                                 name=f"t² {name} (α = {alpha} kW/s²)"))
    fig.update_layout(xaxis_title="test clock (s)", yaxis_title=labels.heading("hrr_mw"),
                      yaxis_range=[0, (top or 1.0) * HRR_AXIS_HEADROOM],
                      height=CHART_HEIGHT_PX, margin=CHART_MARGIN)
    return fig


def _ceiling_figure(results: dict[str, Result]) -> go.Figure:
    fig = go.Figure()
    for cls, result in sorted(results.items()):
        fig.add_trace(go.Scatter(x=result.timeseries["t_s"],
                                 y=result.timeseries["ceiling_temp_c"], mode="lines",
                                 name=f"Test {cls}"))
    fig.update_layout(xaxis_title="test clock (s)",
                      yaxis_title=labels.heading("ceiling_temp_c"),
                      height=CHART_HEIGHT_PX, margin=CHART_MARGIN)
    return fig


def _results_overview(loaded: LoadedSpec, results: dict[str, Result],
                      figs: _Figures) -> str:
    rows = []
    for cls, design in sorted(loaded.tests.items()):
        result = results[cls]
        met, not_met, unset = _criteria_counts(result)
        rows.append([cls, design.meta.name,
                     f"{result.worst_case['section']} at {result.worst_case['velocity_ms']:.2f} m/s",
                     labels.with_unit("hrr_mw", result.peaks["hrr_mw"]),
                     labels.with_unit("hrr_free_burn_mw", result.peaks["hrr_free_burn_mw"]),
                     labels.with_unit("ceiling_temp_c", result.peaks["ceiling_temp_c"]),
                     f"{met} met · {not_met} not met · {unset} limit not set"])
    curves = ", ".join(f"{name} α = {alpha} kW/s²" for name, alpha, _ in GROWTH_CURVES)
    return "\n".join([
        html.table(["Test", "Design", "Worst case", "Peak HRR (suppressed)",
                    "Peak HRR (free burn)", "Peak ceiling temperature", "Criteria"], rows),
        "<h3>Heat release rate</h3>",
        "<p>Solid lines are the engine's suppressed heat release rate; dashed lines are "
        "the same fire burning freely, also the engine's own output. The dotted grey "
        f"lines are conventional t² growth curves, Q = α·t² ({curves}), from NFPA 72 "
        "Annex B and the SFPE Handbook of Fire Protection Engineering. They are "
        "reference shapes, not engine output.</p>",
        figs.embed(_hrr_figure(results)),
        "<h3>Ceiling temperature</h3>",
        figs.embed(_ceiling_figure(results)),
    ])


def render(loaded: LoadedSpec, results: dict[str, Result]) -> str:
    figs = _Figures()
    sections = [
        ("Introduction", _introduction()),
        ("Requested tests", _requested_tests(loaded)),
        ("Test facility", _facility(loaded)),
        ("Water mist system", _water_mist_system(loaded)),
        ("Fire load and target", _fire_load(loaded)),
        ("Virtual instruments", _instruments()),
        ("Procedure", _procedure(loaded, results)),
        ("Results", _results_overview(loaded, results, figs)),
    ]
    return html.document(f"Virtual fire test report — {loaded.spec.name}", sections)

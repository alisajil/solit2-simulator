"""The virtual fire test report: a full-scale-test-shaped HTML document
predicting the outcome of the SOLIT2 tests a compliance spec names, entirely
from this tool's own Tier 1 output. Every section builder here is a pure
function over already-computed Design/Result/RunTrace/ComplianceReport
objects; solit2/cli.py does the loading and running.
"""
from __future__ import annotations

import plotly.graph_objects as go

# ponytail: the chart and 3D builders live in app/ and are pure Plotly. Importing
# them keeps the report identical to the live simulator; promote them into solit2/
# if the CLI is ever shipped without the app package.
from app.components import charts, tunnel3d, twin_canvas
from solit2.compliance.check import ComplianceReport
from solit2.compliance.spec import LoadedSpec
from solit2.engines.reduced.criteria import STATIONS
from solit2.engines.reduced.envelope import ENGINE_VERSION
from solit2.engines.reduced.geometry import section_geometry
from solit2.engines.reduced.state import RunTrace
from solit2.reports import html, labels
from solit2.reports.cfd_runs import CfdRun
from solit2.schema.design import Design
from solit2.schema.result import Criterion, Result


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


FACILITY_HEADERS = ["Test", "Design", "Tunnel preset", "Section",
                    "Road width", "Crown height", "Ventilation band"]
WATER_MIST_HEADERS = ["Test", "Nozzle preset", "K-factor", "Pressure", "Flow per head",
                      "Zone length", "Active heads", "Total K"]


def _facility_row(cls: str, design: Design) -> list[str]:
    geom = section_geometry(design)
    return [cls, design.meta.name, design.tunnel.preset, design.tunnel.section,
            f"{geom.road_width_m:.2f} m", f"{geom.crown_height_m:.2f} m",
            f"{design.ventilation.velocity_range_ms[0]:.2f}–"
            f"{design.ventilation.velocity_range_ms[1]:.2f} m/s"]


def _water_mist_row(cls: str, design: Design) -> list[str]:
    n = design.nozzles
    return [cls, n.preset, f"{n.k_factor_lpm_bar05:.2f}", f"{n.pressure_bar:.1f} bar",
            f"{n.flow_per_head_lpm:.1f} L/min", f"{design.zones.section_length_m:.0f} m",
            str(design.active_heads), f"{n.k_factor_lpm_bar05 * design.active_heads:.1f}"]


def _facility(loaded: LoadedSpec) -> str:
    return html.table(FACILITY_HEADERS,
                      [_facility_row(cls, d) for cls, d in sorted(loaded.tests.items())])


def _water_mist_system(loaded: LoadedSpec) -> str:
    return html.table(WATER_MIST_HEADERS,
                      [_water_mist_row(cls, d) for cls, d in sorted(loaded.tests.items())])


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


# The six per-test charts. Every key is a real key of Result.timeseries. The engine
# samples four gas-temperature stations (U45, U15, D15, D100) plus the ceiling, so
# "every station" means every station the timeseries carries.
CHART_SPECS = (
    ("Heat release rate", ("hrr_mw", "hrr_free_burn_mw")),
    ("Air velocity", ("velocity_ms",)),
    ("Heat flux at U15", ("hf_u15_kwm2",)),
    ("Gas temperature at U15", ("u15_temp_c",)),
    ("Gas temperature at every sampled station",
     ("ceiling_temp_c", "u45_temp_c", "u15_temp_c", "d15_temp_c", "d100_temp_c")),
    ("Water flow", ("water_lpm",)),
)
TUNNEL_HEIGHT_PX = 520
NOT_REACHED = "not reached"


def _clock(t_s: float) -> str:
    return f"{t_s:.0f} s ({twin_canvas.mmss(t_s)})"


def _timeline_rows(events: dict, t_end_s: float) -> list[list[str]]:
    def at(key: str) -> str:
        t = events.get(key)
        return NOT_REACHED if t is None else _clock(float(t))

    back = events.get("backlayering") or {}
    if not back.get("occurred"):
        backlayering = "did not occur"
    elif back.get("cleared_at_s") is None:
        backlayering = f"reached {back['max_length_m']:.0f} m, not cleared"
    else:
        backlayering = (f"reached {back['max_length_m']:.0f} m, cleared at "
                        f"{_clock(float(back['cleared_at_s']))}")
    return [["Ignition", _clock(0.0)],
            ["Detection", at("t_detect_s")],
            ["Activation", at("t_activate_s")],
            ["Full pressure", at("t_full_pressure_s")],
            ["Peak heat release", at("t_peak_hrr_s")],
            ["Backlayering", backlayering],
            ["End of test", _clock(t_end_s)]]


def _criterion_row(key: str, criterion: Criterion) -> list[str]:
    predicted = labels.with_unit(key, criterion.value)
    if criterion.status == "unset":
        return [labels.label(key), predicted, "—", "limit not set"]
    limit = criterion.limit
    limit_text = (" – ".join(labels.with_unit(key, v) for v in limit)
                  if isinstance(limit, tuple) else labels.with_unit(key, limit))
    mark = "✓ met" if criterion.status == "pass" else "✗ not met"
    return [labels.label(key), predicted, limit_text if limit is not None else "—", mark]


def _criteria_checklist(criteria: dict[str, Criterion]) -> str:
    return html.table(["Criterion", "Predicted", "Limit (set by the PMC / Authority's Engineer)",
                       "Result"],
                      [_criterion_row(k, c) for k, c in sorted(criteria.items())])


def _overview(cls: str, design: Design, result: Result) -> str:
    met, not_met, unset = _criteria_counts(result)
    p = result.peaks
    return (
        f"Test {cls} ({design.meta.name}): the engine's worst case is "
        f"{result.worst_case['section']} at {result.worst_case['velocity_ms']:.2f} m/s "
        f"ventilation. Suppressed heat release peaks at "
        f"{labels.with_unit('hrr_mw', p['hrr_mw'])} against a free-burn peak of "
        f"{labels.with_unit('hrr_free_burn_mw', p['hrr_free_burn_mw'])}, and the ceiling "
        f"reaches {labels.with_unit('ceiling_temp_c', p['ceiling_temp_c'])}. "
        f"{met} criteria are met, {not_met} are not met and {unset} have no limit set.")


def _tunnel_at_peak(design: Design, trace: RunTrace) -> go.Figure:
    geom = section_geometry(design)
    window = twin_canvas.core_window_m(design)
    step = max(trace.steps, key=lambda s: s.hrr_mw)
    fig = go.Figure()
    for static in tunnel3d.static_traces(design, geom, window):
        fig.add_trace(static)
    for dynamic in tunnel3d.dynamic_traces(design, geom, step, window,
                                           hrr_peak_mw=step.hrr_mw,
                                           cmax_c=twin_canvas.temp_max_c(trace)):
        fig.add_trace(dynamic)
    fig.update_layout(
        scene=tunnel3d.scene_layout(geom, window), height=TUNNEL_HEIGHT_PX,
        margin=CHART_MARGIN,
        title=f"Predicted state at peak HRR, t = {step.t_s:.0f} s")
    return fig


def _test_results(cls: str, design: Design, result: Result, trace: RunTrace,
                  figs: _Figures) -> str:
    parts = [f"<h3>Test {cls}: {html.escape(design.meta.name)}</h3>",
             f"<p>{html.escape(_overview(cls, design, result))}</p>",
             "<h4>Configuration</h4>",
             html.table(FACILITY_HEADERS, [_facility_row(cls, design)]),
             html.table(WATER_MIST_HEADERS, [_water_mist_row(cls, design)]),
             "<h4>Timeline</h4>",
             html.table(["Event", "Test clock"],
                        _timeline_rows(result.events, result.timeseries["t_s"][-1])),
             "<h4>Criteria</h4>",
             _criteria_checklist(result.criteria),
             "<h4>Results</h4>"]
    for title, keys in CHART_SPECS:
        fig = charts.timeseries_chart(result.timeseries, list(keys))
        fig.update_layout(title=title)
        fig.update_yaxes(title_text=labels.unit(keys[0]))
        parts.append(figs.embed(fig))
    parts += ["<h4>Tunnel at peak heat release</h4>",
              figs.embed(_tunnel_at_peak(design, trace))]
    return "\n".join(parts)


def _results(loaded: LoadedSpec, results: dict[str, Result],
             traces: dict[str, RunTrace], figs: _Figures) -> str:
    return "\n".join(
        [_results_overview(loaded, results, figs)]
        + [_test_results(cls, design, results[cls], traces[cls], figs)
           for cls, design in sorted(loaded.tests.items())])


# The only series an FDS Result carries (fds/reader.py builds its timeseries from
# these four), so the only ones that can be laid over a Tier 1 chart.
CFD_SERIES = (("hrr_mw", "Heat release rate"), ("ceiling_temp_c", "Ceiling temperature"))
CFD_PEAK_KEYS = ("hrr_mw", "ceiling_temp_c")


def _cfd_status_line(run: CfdRun) -> str:
    if run.state in ("not_run", "running", "pausing"):
        return run.detail
    return f"CFD {run.state}: {run.detail}"


def _cfd_figures(cls: str, tier1: Result, cfd: Result) -> list[go.Figure]:
    figures = []
    for key, title in CFD_SERIES:
        fig = go.Figure()
        fig.add_trace(go.Scatter(x=tier1.timeseries["t_s"], y=tier1.timeseries[key],
                                 mode="lines", name="Tier 1 (reduced)"))
        fig.add_trace(go.Scatter(x=cfd.timeseries["t_s"], y=cfd.timeseries[key],
                                 mode="lines", name="CFD (FDS)"))
        fig.update_layout(title=f"Test {cls} — {title}", xaxis_title="test clock (s)",
                          yaxis_title=labels.unit(key), height=350, margin=CHART_MARGIN)
        figures.append(fig)
    return figures


def _cfd_peaks_table(tier1: Result, cfd: Result) -> str:
    rows = []
    for key in CFD_PEAK_KEYS:
        a, b = float(tier1.peaks[key]), float(cfd.peaks[key])
        rows.append([labels.label(key), labels.with_unit(key, a), labels.with_unit(key, b),
                     f"{b - a:+.1f} {labels.unit(key)}"])
    return html.table(["Peak", "Tier 1", "CFD", "CFD minus Tier 1"], rows)


def _cfd_comparison(loaded: LoadedSpec, results: dict[str, Result],
                    cfd: dict[str, CfdRun], figs: _Figures) -> str:
    parts = [
        "<p>Each finished FDS run of a test design (its CHID is the design's SHA) is laid "
        "over that test's Tier 1 prediction. The CFD reader exports heat release rate and "
        "ceiling temperature only, so the other four charts on each results page have no "
        "CFD counterpart. Differences are reported, not judged: where the two tiers "
        "disagree, the disagreement is the finding.</p>"]
    for cls, design in sorted(loaded.tests.items()):
        run = cfd[cls]
        parts.append(f"<h3>Test {cls}: {html.escape(design.meta.name)}</h3>")
        parts.append(f"<p>{html.escape(_cfd_status_line(run))}</p>")
        if run.result is None:
            continue
        parts.append(_cfd_peaks_table(results[cls], run.result))
        parts += [figs.embed(fig) for fig in _cfd_figures(cls, results[cls], run.result)]
        if run.result.warnings:
            parts.append("<h4>Warnings from the CFD run</h4><ul>"
                         + "".join(f"<li>{html.escape(w)}</li>" for w in run.result.warnings)
                         + "</ul>")
    return "\n".join(parts)


def _compliance_summary(report: ComplianceReport) -> str:
    h = report.headline
    parts = [
        f"<p>Spec: {html.escape(report.spec_name)}. {h.applicable} clauses apply: "
        f"{h.complying} comply ({h.by_deviation} through an accepted deviation), "
        f"{h.fails} fail and {h.needs_evidence} need evidence. Of those that comply, "
        f"{h.evidenced} rest on a full-scale measurement, {h.planned} on a planned "
        f"design value and {h.predicted} on a Tier 1 prediction.</p>"]
    blockers = report.blockers
    if not blockers:
        parts.append("<p>No clause fails or lacks evidence.</p>")
        return "\n".join(parts)
    parts.append(html.table(
        ["Clause", "Requirement", "Verdict", "Found", "Required"],
        [[f.clause, f.requirement, f.verdict.value.replace("_", " "), f.found, f.required]
         for f in blockers]))
    return "\n".join(parts)


def _unset_criteria(results: dict[str, Result]) -> list[str]:
    """Labels of every criterion no test design's AHJ block set, across all tests."""
    return sorted({labels.label(key) for result in results.values()
                   for key, c in result.criteria.items() if c.status == "unset"})


def _conclusion(loaded: LoadedSpec, results: dict[str, Result],
                report: ComplianceReport) -> str:
    lines = []
    for cls, design in sorted(loaded.tests.items()):
        met, not_met, unset = _criteria_counts(results[cls])
        failed = sorted(labels.label(k) for k, c in results[cls].criteria.items()
                        if c.status == "fail")
        tail = f" Not met: {', '.join(failed)}." if failed else ""
        lines.append(f"<li>Test {cls} ({html.escape(design.meta.name)}): {met} criteria met, "
                     f"{not_met} not met, {unset} with no limit set.{html.escape(tail)}</li>")
    unset_names = _unset_criteria(results)
    unset_text = (f"<p>In at least one test design no authority has set a limit for: "
                  f"{html.escape(', '.join(unset_names))}. They are predicted and shown, and "
                  "not judged.</p>" if unset_names
                  else "<p>Every criterion in every test design has a limit set by its "
                       "authority.</p>")
    h = report.headline
    return "\n".join([
        "<p>This is a prediction from the engine, not a test result.</p>",
        f"<ul>{''.join(lines)}</ul>", unset_text,
        f"<p>The compliance checker finds {h.fails} failing and {h.needs_evidence} "
        f"unevidenced clause(s) of {h.applicable} that apply.</p>"])


def _limitations(results: dict[str, Result], report: ComplianceReport, commit: str) -> str:
    any_result = next(iter(results.values()))
    provenance = [[key.replace("design_sha.", "design SHA, "), value]
                  for key, value in sorted(report.provenance.items())
                  if key != "calibration"]
    provenance += [["calibration hash", report.provenance["calibration"]],
                   ["engine version", ENGINE_VERSION],
                   ["tool commit", commit]]
    warnings = sorted({w for r in results.values() for w in r.warnings})
    return "\n".join([
        f"<p>{html.escape(str(any_result.meta.get('calibration_note', '')))}</p>",
        "<p>Every number in this report is an extrapolation until a full-scale test of the "
        "assessed system exists.</p>",
        "<h3>Provenance</h3>", html.table(["Item", "Value"], provenance),
        "<h3>Warnings the engine raised</h3>",
        ("<ul>" + "".join(f"<li>{html.escape(w)}</li>" for w in warnings) + "</ul>"
         if warnings else "<p>The engine raised no warnings.</p>")])


SECTION_TITLES = (
    "Introduction", "Requested tests", "Test facility", "Water mist system",
    "Fire load and target", "Virtual instruments", "Procedure", "Results",
    "CFD comparison", "Compliance summary", "Conclusion", "Limitations and provenance",
)


def render(loaded: LoadedSpec, results: dict[str, Result], *,
           traces: dict[str, RunTrace], cfd: dict[str, CfdRun],
           compliance: ComplianceReport, commit: str) -> str:
    figs = _Figures()
    bodies = (
        _introduction(),
        _requested_tests(loaded),
        _facility(loaded),
        _water_mist_system(loaded),
        _fire_load(loaded),
        _instruments(),
        _procedure(loaded, results),
        _results(loaded, results, traces, figs),
        _cfd_comparison(loaded, results, cfd, figs),
        _compliance_summary(compliance),
        _conclusion(loaded, results, compliance),
        _limitations(results, compliance, commit),
    )
    assert len(bodies) == len(SECTION_TITLES)   # a builder added without a title is a bug
    out = html.document(f"Virtual fire test report — {loaded.spec.name}",
                        list(zip(SECTION_TITLES, bodies)))
    refs = html.external_references(out)
    if refs:
        raise ValueError(f"the report would fetch something when opened: {refs[:3]}")
    return out

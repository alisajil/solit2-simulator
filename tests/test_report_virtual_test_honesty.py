# tests/test_report_virtual_test_honesty.py
"""The virtual test report's honesty rules, one test per rule in the design spec."""
import dataclasses
import functools
import re


from solit2.compliance import check as compliance_check
from solit2.compliance.spec import load_spec
from solit2.engines.reduced import envelope, sim
from solit2.reports import cfd_runs, html, labels, virtual_test

SPEC = "examples/compliance/solit2-example.spec.json"
COMMIT = "0123abc"
SPEC_SECTIONS = (
    "Introduction", "Requested tests", "Test facility", "Water mist system",
    "Fire load and target", "Virtual instruments", "Procedure", "Results",
    "CFD comparison", "Compliance summary", "Conclusion", "Limitations and provenance",
)


@functools.lru_cache(maxsize=1)
def _world():
    loaded = load_spec(SPEC)
    results = {cls: envelope.run(d) for cls, d in loaded.tests.items()}
    traces = {cls: sim.run_once(loaded.tests[cls], r.worst_case["section"],
                                r.worst_case["velocity_ms"]) for cls, r in results.items()}
    return loaded, results, traces, compliance_check.run(SPEC)


def _render(cfd=None):
    loaded, results, traces, compliance = _world()
    cfd = cfd or {cls: cfd_runs.NOT_RUN for cls in loaded.tests}
    return virtual_test.render(loaded, results, traces=traces, cfd=cfd,
                               compliance=compliance, commit=COMMIT)


def test_every_section_of_the_design_spec_is_present_in_its_order():
    assert virtual_test.SECTION_TITLES == SPEC_SECTIONS
    headings = re.findall(r"<h2>(\d+)\. (.*?)</h2>", _render())
    assert [(int(n), title) for n, title in headings] == list(enumerate(SPEC_SECTIONS, 1))


def test_the_prediction_band_is_on_every_section_and_in_the_repeating_header():
    out = _render()
    assert out.count(html.BAND_TEXT) == len(SPEC_SECTIONS) + 1


def test_nothing_reads_as_a_real_test():
    visible = html.without_scripts(_render()).lower()
    for word in ("witness", "signature", "signed by", "laboratory", "accredited",
                 "certificate", "logo"):
        assert word not in visible
    assert "<img" not in visible


def test_a_limit_only_ever_comes_from_the_designs_own_ahj_block():
    loaded, _, _, _ = _world()
    designs = {cls: d.model_copy(update={"ahj": d.ahj.model_copy(update={"max_air_temp_c": 123.0})})
               for cls, d in loaded.tests.items()}
    loaded2 = dataclasses.replace(loaded, tests=designs)
    results2 = {cls: envelope.run(d) for cls, d in designs.items()}
    procedure = virtual_test._procedure(loaded2, results2)
    assert "123" in procedure                       # the limit the design's ahj set
    total = sum(len(r.criteria) for r in results2.values())
    unset = sum(1 for r in results2.values() for c in r.criteria.values()
                if c.status == "unset")
    assert procedure.count("<tr>") - len(results2) == total    # one row per criterion
    assert procedure.count("limit not set") == unset           # every unset one says so
    assert 0 < unset < total


def test_the_example_specs_unset_criteria_read_limit_not_set_beside_their_value():
    loaded, results, _, _ = _world()
    out = _render()
    assert "limit not set" in out
    for result in results.values():
        for key, criterion in result.criteria.items():
            if criterion.status == "unset":
                assert labels.with_unit(key, criterion.value) in out


def test_every_free_burn_and_peak_number_is_the_engines_own():
    _, results, _, _ = _world()
    fig = virtual_test._hrr_figure(results)
    by_name = {t.name: t for t in fig.data}
    for cls, result in results.items():
        assert tuple(by_name[f"Test {cls} — free burn"].y) == tuple(
            result.timeseries["hrr_free_burn_mw"])
        assert result.peaks["hrr_free_burn_mw"] == max(result.timeseries["hrr_free_burn_mw"])


def test_the_cfd_placeholder_appears_without_a_run():
    loaded, _, _, _ = _world()
    assert _render().count("CFD not yet run") == len(loaded.tests)


def test_a_finished_run_is_overlaid_and_a_missing_one_still_says_so():
    loaded, results, _, _ = _world()
    ts = results["A"].timeseries
    finished = cfd_runs.CfdRun("done", "", results["A"].model_copy(update={
        "timeseries": {"t_s": ts["t_s"], "hrr_mw": ts["hrr_mw"],
                       "hrr_free_mw": ts["hrr_free_burn_mw"],
                       "ceiling_temp_c": ts["ceiling_temp_c"]}}))
    out = _render({"A": finished, "B": cfd_runs.NOT_RUN})
    assert "CFD (FDS)" in out
    assert out.count("CFD not yet run") == 1


def test_the_document_makes_no_network_request_and_embeds_plotly_once():
    out = _render()
    assert html.external_references(out) == []
    assert out.count(html.BUNDLE_MARK) == 1


def test_a_design_name_cannot_inject_markup_anywhere_in_the_document():
    loaded, results, traces, compliance = _world()
    hostile = "<script>alert(1)</script>"
    designs = {cls: d.model_copy(update={"meta": d.meta.model_copy(update={"name": hostile})})
               for cls, d in loaded.tests.items()}
    out = virtual_test.render(dataclasses.replace(loaded, tests=designs), results,
                              traces=traces,
                              cfd={cls: cfd_runs.NOT_RUN for cls in designs},
                              compliance=compliance, commit=COMMIT)
    assert hostile not in out
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in out


def test_the_cli_writes_a_file_that_passes_every_check_above(tmp_path):
    import subprocess
    out = tmp_path / "virtual-test.html"
    done = subprocess.run(
        ["uv", "run", "solit2", "report", "virtual-test", SPEC, "--out", str(out)],
        capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    text = out.read_text()
    assert html.external_references(text) == []
    assert text.count(html.BAND_TEXT) == len(SPEC_SECTIONS) + 1
    assert text.count(html.BUNDLE_MARK) == 1

"""The tool ships the standard; the user supplies the product and the project.

These are the tests that keep the evaluator independent: that nothing shipped
inside the package names a manufacturer or a commissioning project, that the
acceptance criteria are the standard's and nothing else, that a user's own
engineering limits are judged separately from the standard's, and that the
engine states in its own output what its constants rest on.
"""
import json
import re
from pathlib import Path

import pytest

from solit2.engines.reduced import constraints as constraints_mod
from solit2.engines.reduced import criteria as criteria_mod
from solit2.engines.reduced import envelope
from solit2.schema.design import Constraints, Design
from solit2.schema.presets import EXAMPLE_PRESET_DIR, PRESET_DIR, load_preset

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DIR = REPO_ROOT / "solit2"
APP_DIR = REPO_ROOT / "app"
EXAMPLES_DIR = REPO_ROOT / "examples"
EXAMPLE_DESIGN = "examples/designs/road-tunnel-twin-bore.json"


# --- test 1: presets resolve in both locations -------------------------------

def test_load_preset_finds_a_shipped_preset_and_an_example_preset():
    shipped = load_preset("nozzle", "template")
    example = load_preset("nozzle", "bimodal_example")
    assert shipped["preset"] == "template"
    assert example["preset"] == "bimodal_example"


def test_a_missing_preset_lists_candidates_from_both_locations():
    with pytest.raises(FileNotFoundError) as exc:
        load_preset("nozzle", "no_such_nozzle")
    message = str(exc.value)
    assert "no_such_nozzle" in message
    assert "template" in message, "the shipped presets must be offered"
    assert "bimodal_example" in message, "the example presets must be offered too"


def test_the_two_preset_locations_are_distinct_and_both_exist():
    assert PRESET_DIR != EXAMPLE_PRESET_DIR
    assert PRESET_DIR.is_dir() and EXAMPLE_PRESET_DIR.is_dir()


# --- test 2: nothing under solit2/ names a vendor or a project ---------------

# The commissioning project, the manufacturers whose products were evaluated,
# and the tender/vendor document references they were read off.
#
# Deliberately NOT banned: the name of the test gallery where the SOLIT2
# full-scale tests were run. That is published-research provenance, and citing
# it is what makes the reference cases checkable (see INDEPENDENCE.md rule 3).
BANNED_TERMS = (
    "orange gate", "orange_gate", "orangegate",
    "mistelix", "msx-t100", "msx_t100", "ultrafog", "fogtec",
    "mstx", "dbr", "ewcr", "hpwm", "applus",
)
SKIP_DIRS = {"__pycache__", ".pytest_cache", ".ruff_cache"}


def _package_files() -> list[Path]:
    # `app/` is scanned too: it is now the primary surface, and a vendor name reaching
    # a screen is exactly what this rule exists to prevent.
    return sorted(p for root in (PACKAGE_DIR, APP_DIR) for p in root.rglob("*")
                  if p.is_file() and not SKIP_DIRS & set(p.parts))


def _wrapped_offences(relative: Path, text: str) -> list[str]:
    """Banned terms that appear only once line breaks are flattened away."""
    flat, source_index = [], []
    for i, char in enumerate(text):
        if char.isspace():
            if flat and flat[-1] == " ":
                continue
            flat.append(" ")
        else:
            flat.append(char.lower())
        source_index.append(i)
    flattened = "".join(flat)
    offences = []
    for term in BANNED_TERMS:
        start = flattened.find(term)
        while start != -1:
            first = source_index[start]
            last = source_index[min(start + len(term) - 1, len(source_index) - 1)]
            if "\n" in text[first:last + 1]:      # the line-by-line scan already has the rest
                offences.append(f"{relative}:{text.count(chr(10), 0, first) + 1}: "
                                f"{term!r} wrapped across a line break")
            start = flattened.find(term, start + 1)
    return offences


def test_no_file_in_the_package_names_a_vendor_or_a_project():
    """Code, presets, docstrings and comments alike.

    This is the test that keeps the tool neutral as it grows: a new preset, a
    new comment or a new default that carries a manufacturer's or a project's
    name fails here, naming the file and the line.
    """
    offences = []
    for path in _package_files():
        relative = path.relative_to(REPO_ROOT)
        for term in BANNED_TERMS:
            if term in str(relative).lower():
                offences.append(f"{relative}: {term!r} in the file name")
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue  # not text; nothing to read a name out of
        for number, line in enumerate(lines, start=1):
            lowered = line.lower()
            for term in BANNED_TERMS:
                if term in lowered:
                    offences.append(
                        f"{relative}:{number}: {term!r} in {line.strip()!r}")
        # A name wrapped across a line break reads as the name to any human and
        # was invisible to the line-by-line scan above: a project name sat in
        # the FDS deck module for weeks, split as "the Orange" / "Gate baseline",
        # while this test passed. Flattening runs of whitespace catches it.
        offences += _wrapped_offences(relative, "\n".join(lines))
    assert not offences, (
        "vendor or project names must not ship inside the package; move the "
        "data to examples/ and neutralise the wording:\n  " + "\n  ".join(offences))


def test_the_grep_actually_greps_something():
    """A guard on the guard: an empty file list would make the test above vacuous."""
    assert len(_package_files()) > 20


# --- test 3: the shipped templates announce themselves as placeholders -------

def _template_design(tmp_path: Path) -> Design:
    raw = json.loads((REPO_ROOT / EXAMPLE_DESIGN).read_text())
    raw["nozzles"] = {"preset": "template"}
    path = tmp_path / "template_design.json"
    path.write_text(json.dumps(raw))
    return Design.load(path)


def test_the_nozzle_template_loads_and_runs(tmp_path):
    design = _template_design(tmp_path)
    assert design.nozzles.k_factor_lpm_bar05 == pytest.approx(1.0)
    result = envelope.run(design)
    assert result.criteria, "a template design must still produce a full result"


def test_a_result_built_on_the_nozzle_template_warns_that_it_is_a_placeholder(tmp_path):
    result = envelope.run(_template_design(tmp_path))
    placeholder = [w for w in result.warnings
                   if "placeholder" in w.lower() and "nozzle" in w.lower()]
    assert placeholder, (
        "a result computed from placeholder nozzle data must say so in its own "
        f"output; warnings were {result.warnings}")


# --- test 4: the criteria are the standard's, and only the standard's --------

# Exactly the SOLIT2 Annex 7 section 7 criteria: the one absolute rule (7.2.1),
# the ventilation design fire size (7.3.1), life safety (7.2.2) and structure
# (7.2.4). Nothing here traces to a project's supply or a vendor's margin.
SOLIT2_CRITERION_IDS = {
    "target_ignited",
    "hrr_below_tvs_design_mw",
    "max_air_temp_c", "max_heat_flux_kwm2", "min_visibility_m",
    "max_fed", "max_co_ppm",
    "structure_exposure_length_m", "structure_exposure_duration_s",
}


def test_default_criteria_are_exactly_the_solit2_derived_set():
    ids = {spec.id for spec in criteria_mod.DEFAULT_CRITERIA}
    assert ids == SOLIT2_CRITERION_IDS


def test_the_project_and_vendor_criteria_are_gone():
    """`power_kw` was one tunnel's feeder capacity; `density_mm_min` was one
    vendor's power-headroom calculation. Both are now user-declared constraints."""
    ids = {spec.id for spec in criteria_mod.DEFAULT_CRITERIA}
    assert ids.isdisjoint({"power_kw", "density_mm_min"})


# --- test 5: an undeclared constraints block asks nothing --------------------

def test_an_unset_constraints_block_reports_every_constraint_as_unset():
    design = Design.load(REPO_ROOT / EXAMPLE_DESIGN).model_copy(
        update={"constraints": Constraints()})
    result = envelope.run(design)
    assert set(result.constraints) == {spec.id for spec in constraints_mod.CONSTRAINT_SPECS}
    for cid, reported in result.constraints.items():
        assert reported.status == "unset", f"{cid} should be unset"
        assert reported.limit is None
        assert reported.passed, "a limit nobody declared must not reject a design"


def test_unset_constraints_never_reach_gates_failed():
    design = Design.load(REPO_ROOT / EXAMPLE_DESIGN).model_copy(
        update={"constraints": Constraints()})
    result = envelope.run(design)
    assert set(result.constraints).isdisjoint(result.score["gates_failed"])


# --- test 6: a breached constraint is not a SOLIT2 failure -------------------

def test_a_breached_constraint_is_reported_apart_from_the_criteria():
    """A local circumstance and a standard are two different verdicts, and the
    result must keep them visibly apart."""
    design = Design.load(REPO_ROOT / EXAMPLE_DESIGN)
    breaching = design.model_copy(update={"constraints": Constraints(
        note="an impossibly tight local limit, so the breach is certain",
        max_pump_power_kw=1.0)})
    result = envelope.run(breaching)

    breached = result.constraints["max_pump_power_kw"]
    assert breached.status == "fail"
    assert not breached.passed
    assert breached.limit == pytest.approx(1.0)

    assert "max_pump_power_kw" not in result.criteria
    assert "power_kw" not in result.criteria
    assert set(result.criteria) == SOLIT2_CRITERION_IDS


def test_a_breached_constraint_does_not_fail_the_solit2_gates():
    design = Design.load(REPO_ROOT / EXAMPLE_DESIGN)
    clean = envelope.run(design)
    breaching = envelope.run(design.model_copy(update={"constraints": Constraints(
        max_pump_power_kw=1.0, max_application_density_mm_min=0.01)}))

    assert breaching.score["gates_passed"] == clean.score["gates_passed"]
    assert breaching.score["gates_failed"] == clean.score["gates_failed"]
    assert set(breaching.score["gates_failed"]) <= SOLIT2_CRITERION_IDS


# --- test 7: the engine states what its constants rest on -------------------

def test_meta_reports_the_calibration_as_fitted_without_claiming_it_is_validated():
    """A least-squares fit against c4-c6 has been run, so the engine says so.

    The fit did not reach the reference values, so `fitted` must never be left
    to read as `validated`: the note carried in every result has to point at the
    command that reports how far the engine actually lands from the tests.
    """
    result = envelope.run(Design.load(REPO_ROOT / EXAMPLE_DESIGN))
    assert result.meta["calibration_fitted"] is True, (
        "validation/fit.py has been run against the reference cases, and an "
        "engine whose constants came from a fit must say so in its own output")
    note = result.meta["calibration_note"]
    assert note, "what the constants rest on must be stated in every result"
    assert "solit2 validate" in note, (
        "the note must send the reader to the command that lists the misses, "
        "or a fitted calibration reads as a validated one")
    assert isinstance(result.meta["calibration_anchors"], list)


def test_meta_names_the_surviving_reference_cases():
    result = envelope.run(Design.load(REPO_ROOT / EXAMPLE_DESIGN))
    assert set(result.meta["calibration_anchors"]) == {"c4", "c5", "c6"}


# --- the calibration basis and the validation basis must agree --------------

def test_every_anchor_the_calibration_cites_still_exists():
    """A constant citing a reference case that was deleted is a calibrated
    model resting on nothing, and nothing in the output would show it."""
    from validation import compare

    live = {anchor.id for anchor in compare.load_anchors()}
    calibration = json.loads((PRESET_DIR / "calibration.json").read_text())
    dangling = []
    for group, entries in calibration.items():
        if group == "provenance":
            continue
        for name, entry in entries.items():
            for anchor in str(entry.get("anchor", "none")).split(","):
                anchor = anchor.strip()
                if anchor and anchor != "none" and anchor not in live:
                    dangling.append(f"{group}.{name} cites {anchor!r}")
    assert not dangling, (
        "the calibration basis and the validation basis disagree:\n  "
        + "\n  ".join(dangling))


# --- test 8: retired project numbers must not creep back ---------------------

# A vendor's or a project's NAME is caught by test 2. A number is not, and a
# number is how the last project assumptions survived: two tube lengths priced
# every design against one bore, and one supplier's preferred discharge density
# marked every other design down. Both are read off the design now, so neither
# literal may reappear anywhere the tool ships -- in code, in a comment, in a
# shipped preset or in a worked example someone will copy.

def _scanned_files() -> list[Path]:
    return sorted(p for root in (PACKAGE_DIR, EXAMPLES_DIR) for p in root.rglob("*")
                  if p.is_file() and not SKIP_DIRS & set(p.parts))


def _lines_matching(pattern: str) -> list[str]:
    hits = []
    for path in _scanned_files():
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (UnicodeDecodeError, OSError):
            continue  # not text; nothing to read a number out of
        for number, line in enumerate(lines, start=1):
            if re.search(pattern, line):
                hits.append(f"{path.relative_to(REPO_ROOT)}:{number}: {line.strip()!r}")
    return hits


# Not preceded by a digit or a decimal point, so 14240 and 0.4240 are not hits;
# and not followed by one, so 3.88 m/s (a ventilation velocity) is not a hit for
# the density pattern either.
RETIRED_TUBE_LENGTHS = r"(?<![\d.])42[46]0(?!\d)"
RETIRED_DENSITY = r"(?<![\d.])3\.8(?!\d)"


def test_the_scan_covers_both_the_package_and_the_examples():
    """A guard on the guard: an empty file list would make the tests below vacuous."""
    scanned = _scanned_files()
    assert len(scanned) > 20
    assert any(EXAMPLES_DIR in p.parents for p in scanned)
    assert any(PACKAGE_DIR in p.parents for p in scanned)


def test_no_retired_tube_length_survives_in_the_package_or_the_examples():
    offences = _lines_matching(RETIRED_TUBE_LENGTHS)
    assert not offences, (
        "4240 m and 4260 m were one project's two tube lengths, and they used to "
        "decide the zone count and every pipe run of every design. Cost "
        "quantities come from tunnel.length_m and tunnel.tubes now:\n  "
        + "\n  ".join(offences))


def test_no_vendor_density_headroom_survives_in_the_package_or_the_examples():
    offences = [hit for hit in _lines_matching(RETIRED_DENSITY)
                if "density" in hit.lower()]
    assert not offences, (
        "3.8 mm/min was one supplier's preferred discharge density, and it used "
        "to deduct a point from every design that exceeded it. The score penalty "
        "reads the user's own constraints.max_application_density_mm_min now, "
        "and an undeclared limit is not a limit:\n  " + "\n  ".join(offences))


def test_a_declared_density_limit_costs_score_points_and_never_a_gate():
    """The one constraint whose VALUE reaches `score.compute`, and its ceiling.

    A penalty deducts from the total. Only a hard SOLIT2 criterion may zero it,
    so a local limit still cannot read as a failure against the standard.
    """
    design = Design.load(REPO_ROOT / EXAMPLE_DESIGN)
    undeclared = envelope.run(design.model_copy(update={"constraints": Constraints()}))
    declared = envelope.run(design.model_copy(update={"constraints": Constraints(
        max_application_density_mm_min=0.01)}))

    assert [p for p in undeclared.score["penalties"] if "density" in p] == [], (
        "no limit declared, so no density penalty at the density this design runs")
    breached = [p for p in declared.score["penalties"] if "density" in p]
    assert breached, "a declared limit the design exceeds must show in the score"
    assert "0.01" in breached[0], "the message must quote the user's own number"

    assert declared.score["total"] < undeclared.score["total"], "it costs points"
    assert declared.score["gates_passed"] == undeclared.score["gates_passed"]
    assert declared.score["gates_failed"] == undeclared.score["gates_failed"]


def test_the_scan_sees_a_name_wrapped_across_a_line_break():
    """A guard on the guard, written from the leak it was found by.

    A project name shipped inside the FDS deck module for weeks as a wrapped
    docstring line -- "takes the Orange" / "Gate baseline from 92.4 m3" -- which
    reads as the name to any human and matched nothing line by line.

    It catches a term broken by the wrap itself. A term broken by a comment
    marker or a quote on the next line ("the Orange" / "# Gate") is NOT caught:
    flattening those away would start matching prose that is not a name.
    """
    wrapped = ('    a CFD run short would shrink the tank -- takes the Orange\n'
               '    Gate baseline from 92.4 m3 to 30.8 m3 -- and break 5.2.8\n')
    assert not any(term in line.lower() for line in wrapped.splitlines()
                   for term in BANNED_TERMS), "the line-by-line scan cannot see it"
    offences = _wrapped_offences(Path("fake.py"), wrapped)
    assert offences and "orange gate" in offences[0] and "fake.py:1" in offences[0]


def test_the_wrapped_scan_stays_quiet_on_clean_text():
    assert _wrapped_offences(Path("x.py"), "a normal comment\nabout tunnels\n") == []
    # and does not double-report what the line-by-line scan already catches
    assert _wrapped_offences(Path("x.py"), "# the orange gate tunnel\n") == []


# --- the calibration states, in every result, what it was fitted on -----------

SHIPPED_REFERENCE_NOZZLE = REPO_ROOT / "designs" / "solit2-reference-nozzle.json"


def _provenance() -> dict:
    from solit2.schema.presets import load_calibration
    return load_calibration()["provenance"]


def test_the_shipped_calibration_was_fitted_on_the_reference_nozzle_that_ships_beside_it():
    """A refit that is not recorded, or a reference nozzle edited after the fit,
    leaves every result describing constants that are not the ones it ran on."""
    import hashlib
    recorded = _provenance()["fit"]["reference_nozzle"]
    assert recorded["path"] == "designs/solit2-reference-nozzle.json"
    assert recorded["sha256"] == hashlib.sha256(SHIPPED_REFERENCE_NOZZLE.read_bytes()).hexdigest(), (
        "the reference nozzle changed after the fit: refit with validation.fit")
    declared = json.loads(SHIPPED_REFERENCE_NOZZLE.read_text())["data_status"]
    assert recorded["data_status"] == declared


def test_the_calibration_note_is_the_one_the_fit_wrote():
    provenance = _provenance()
    fit = provenance["fit"]
    assert fit["reference_nozzle"]["sha256"][:12] in provenance["note"]
    assert f"{fit['passed']} of {fit['comparisons']}" in provenance["note"]


def test_a_result_on_a_calibration_not_fitted_on_measured_data_says_it_is_not_independent():
    result = envelope.run(Design.load(REPO_ROOT / EXAMPLE_DESIGN))
    status = result.meta["calibration_reference_nozzle"]
    assert status is not None
    flagged = [w for w in result.warnings if "not the SOLIT2 test system's measured nozzle" in w]
    assert bool(flagged) == (status != "measured")
    if status != "measured":
        assert "no result computed on them is independent evidence" in result.meta["calibration_note"]


def _with_provenance(monkeypatch, fit):
    import copy
    from solit2.schema.presets import load_calibration
    cal = copy.deepcopy(load_calibration())
    if fit is None:
        cal["provenance"].pop("fit", None)
    else:
        cal["provenance"]["fit"] = fit
    monkeypatch.setattr(envelope, "load_calibration", lambda: cal)


def test_a_reference_nozzle_changed_after_the_fit_is_flagged(monkeypatch):
    fit = dict(_provenance()["fit"])
    fit["reference_nozzle"] = {**fit["reference_nozzle"], "sha256": "0" * 64}
    _with_provenance(monkeypatch, fit)
    assert any("has changed since the constants were fitted" in w
               for w in envelope.calibration_warnings())


def test_a_measured_and_unchanged_reference_nozzle_raises_no_calibration_warning(monkeypatch):
    fit = dict(_provenance()["fit"])
    fit["reference_nozzle"] = {**fit["reference_nozzle"], "data_status": "measured"}
    _with_provenance(monkeypatch, fit)
    assert envelope.calibration_warnings() == []


def test_a_calibration_with_no_fit_record_is_flagged(monkeypatch):
    _with_provenance(monkeypatch, None)
    assert any("records no fit provenance" in w for w in envelope.calibration_warnings())

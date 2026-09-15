"""The tool ships the standard; the user supplies the product and the project.

These are the tests that keep the evaluator independent: that nothing shipped
inside the package names a manufacturer or a commissioning project, that the
acceptance criteria are the standard's and nothing else, that a user's own
engineering limits are judged separately from the standard's, and that the
engine states in its own output what its constants rest on.
"""
import json
from pathlib import Path

import pytest

from solit2.engines.reduced import constraints as constraints_mod
from solit2.engines.reduced import criteria as criteria_mod
from solit2.engines.reduced import envelope
from solit2.schema.design import Constraints, Design
from solit2.schema.presets import EXAMPLE_PRESET_DIR, PRESET_DIR, load_preset

REPO_ROOT = Path(__file__).resolve().parent.parent
PACKAGE_DIR = REPO_ROOT / "solit2"
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
    return sorted(p for p in PACKAGE_DIR.rglob("*")
                  if p.is_file() and not SKIP_DIRS & set(p.parts))


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

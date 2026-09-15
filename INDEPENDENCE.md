# Independence

This tool exists to give an answer that is worth something to whoever reads it.
That is only possible if it has no stake in the answer. Three rules keep it that
way. They are not aspirations; each one is enforced by a test.

## 1. The tool ships no manufacturer's performance data

Nothing inside `solit2/` describes any real product. There is a
`nozzle_template.json`, and it is a placeholder with a K-factor of 1.0 that
announces itself as a placeholder in every result computed from it. Real nozzle
performance — K-factor, drop spectrum, spray geometry, mounting — is a user
input, supplied as a preset of the user's own.

The one exception is named as such: `nozzle_solit2_reference.json` carries
*assumed* values used only to reproduce the published reference cases, because
SOLIT² Annex 2 publishes neither a K-factor nor a drop spectrum. It is not a
product, not an endorsement, and not fit for assessing a real system.

*Enforced by:* `tests/test_independence.py::test_no_file_in_the_package_names_a_vendor_or_a_project`,
which greps every file under `solit2/` — code, presets, docstrings and comments
— for manufacturer, project and tender-document names, and fails with the file
and line.

## 2. Every acceptance limit comes from the authority having jurisdiction

SOLIT² Engineering Guidance Annex 7 §7.1 says so itself: it "gives some guidance
for selecting minimum acceptance requirements but do[es] not specify in detail
absolute values", and "the detailed acceptance criteria shall be defined by
authorities having jurisdiction based on the risk analysis of every individual
tunnel".

So the tool ships the *structure* of Annex 7 §7 and none of the numbers. Every
limit is read off the design's `ahj` block, and a limit nobody has set is
reported as `unset` rather than quietly borrowed from a vendor's report or a
tender. A design that passes only because nobody asked anything of it is listed
in `score.criteria_unset` so that `gates_passed` can never be read as approval.

The one absolute rule Annex 7 does mandate — §7.2.1, that the target must not
ignite — carries no limit and no AHJ dependency, because the standard states it
outright.

A user's own engineering limits are real and must be checked, but they are not
the standard. They go in the design's `constraints` block and are reported in
their own `constraints` block of the result. **A breached constraint is never a
SOLIT² failure** and can never appear in `gates_failed`.

*Enforced by:* `test_default_criteria_are_exactly_the_solit2_derived_set`,
`test_a_breached_constraint_is_reported_apart_from_the_criteria` and
`test_a_breached_constraint_does_not_fail_the_solit2_gates`.

## 3. The calibration reference cases are published research, cited

The engine's constants are grounded in the SOLIT² Engineering Guidance Annex 2
full-scale fire tests (cases `c4`, `c5`, `c6`), which are published and
checkable. Every constant in `solit2/presets/calibration.json` names the
reference cases it was set against, or `"none"`.

Every result states what the constants rest on, in its own `meta` block:

- `calibration_fitted` — whether a fit against reference data has been run at all.
- `calibration_anchors` — the reference case ids the constants cite.
- `calibration_note` — what the basis is, in a sentence.

**`calibration_fitted` is now `true`**: a least-squares fit of twelve constants
against `c4`–`c6` has been run, and the tool says so rather than letting a reader
assume the constants are still hand-set. Everything else in `calibration.json` is
hand-set from published literature and is not a fitted value.

**Fitted is not validated.** The fit moved the cost by 0.02 % and did not reach
the reference values: `c4` and `c5` still model a 150 MW peak against 30 and
20 MW measured. `calibration_note` says so in every result and names
`solit2 validate` as the command that lists the misses, so `fitted: true` can
never be read as a claim that the model agrees with the tests.

*Enforced by:*
`test_meta_reports_the_calibration_as_fitted_without_claiming_it_is_validated`,
which fails if the note stops pointing at that command, and
`test_every_anchor_the_calibration_cites_still_exists`, which fails if any
constant cites a reference case that is not in `validation/anchors/`.

## What this does not claim

Independence is about having no stake in the answer. It is not a claim that the
model is right. The engine is a reduced-order one; `solit2 validate` reports how
far it lands from the published tests, and `calibration_fitted: false` is there
so nobody mistakes a hand-set constant for a fitted one.

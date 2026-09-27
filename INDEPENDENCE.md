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

There is no exception. The SOLIT² reference test nozzle is not shipped either:
Annex 2 publishes no K-factor, pressure, drop spectrum or mounting for it, so it
is the tester's input too (§3).

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
- `calibration_note` — what the basis is: written by the fit, not by hand.
- `calibration_reference_nozzle` — what the tester declared the reference nozzle
  data to be.

**The fit writes its own provenance.** `validation/fit.py` records, in
`calibration.json`'s `provenance` block, the reference nozzle file it ran on
(path and sha256), that file's declared `data_status`, how many constants were
fitted against how many comparisons, how many pass afterwards, and each miss. The
`calibration_note` every result carries is generated from that record, so it
cannot go on describing a fit that is no longer the one in the file. A
hand-written note did exactly that once: after a refit it still reported the
superseded constants' misses.

**Fitted is not validated.** The same comparisons that set the constants are
the ones `solit2 validate` checks, so passing them is weak evidence and failing
them is a finding. `calibration_note` says so in every result and names
`solit2 validate` as the command that lists the misses.

**The reference nozzle is the tester's, not ours.** Annex 2 publishes what
`c4`–`c6` measured and nothing about the nozzle that produced it: its §4.1.3
lists "Type of the nozzle (Shape, K-factor, etc.)" only as a parameter that
"corresponded to the real installation" and never gives a value. So the anchors
run only on a reference nozzle the tester supplies
(`designs/solit2-reference-nozzle.json`, or `--reference-nozzle PATH`), and that
file must declare its `data_status`:

- `measured` — the SOLIT² test system's own nozzle, measured;
- `estimated` — that nozzle, with estimated values;
- `placeholder` — not that nozzle at all.

The tool does not assume it. Only `measured` makes the calibration independent.
With anything else, the fitted constants have absorbed whatever the stand-in gets
wrong, and **every result carries a warning that no figure in it is independent
evidence**. That matters most when the stand-in is the nozzle being assessed. A
calibration tuned so that nozzle reproduces the reference tests will then agree
with itself when it assesses that nozzle, which is circular. The warning is how
the tool says so.

A result also warns if the reference nozzle file has changed since the fit
(its sha256 no longer matches), or if `calibration.json` carries no fit record at
all.

*Enforced by:*
`test_meta_reports_the_calibration_as_fitted_without_claiming_it_is_validated`,
`test_every_anchor_the_calibration_cites_still_exists`,
`test_no_reference_nozzle_ships_with_the_tool`,
`test_anchors_refuse_without_a_tester_supplied_reference_nozzle`,
`test_validate_refuses_cleanly_without_a_reference_nozzle`,
`test_a_reference_nozzle_must_say_whether_it_is_measured`,
`test_the_shipped_calibration_was_fitted_on_the_reference_nozzle_that_ships_beside_it`
(fails if the reference nozzle is edited without a refit),
`test_the_calibration_note_is_the_one_the_fit_wrote`,
`test_a_result_on_a_calibration_not_fitted_on_measured_data_says_it_is_not_independent`
and `test_a_reference_nozzle_changed_after_the_fit_is_flagged`.

## What this does not claim

Independence is about having no stake in the answer. It is not a claim that the
model is right. The engine is a reduced-order one. `solit2 validate` reports how
far it lands from the published tests, and the calibration warnings say when the
constants cannot be shown to rest on measured reference data.

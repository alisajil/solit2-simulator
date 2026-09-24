"""Step 5: is the planned fire test SOLIT2-compliant, clause by clause."""
from __future__ import annotations

import json
from pathlib import Path

import streamlit as st

from solit2.compliance import check
from solit2.compliance.spec import ComplianceSpec
from solit2.compliance.verdict import Headline, Verdict
from solit2.reports import compliance as report_md
from solit2.schema.presets import PRESET_DIR, reload_calibration

SPEC_ROOTS: tuple[Path, ...] = (Path("designs"), Path("examples/compliance"))
ICON = {Verdict.COMPLIES: "✅", Verdict.FAILS: "❌", Verdict.DEVIATION_ACCEPTED: "🟦",
        Verdict.NEEDS_EVIDENCE: "🟧", Verdict.NOT_APPLICABLE: "—"}


def find_specs(root: Path) -> list[Path]:
    """Compliance specs are the JSON files that declare a `spec_version`."""
    found = []
    for path in sorted(root.glob("*.json")):
        try:
            if "spec_version" in json.loads(path.read_text()):
                found.append(path)
        except (OSError, json.JSONDecodeError):
            continue
    return found


def _dependency_paths(spec_path: Path) -> tuple[Path, ...]:
    """Every file a compliance run actually reads: the spec itself, its test
    and installation designs, its project rules file if it names one, and the
    calibration presets every Tier 1 run consults.

    Used only to build the Streamlit cache key below -- a design or the
    calibration changing on disk must invalidate a cached report exactly as
    editing the spec file itself does, or the step keeps showing a report for
    inputs that no longer exist.
    """
    spec = ComplianceSpec.model_validate(json.loads(spec_path.read_text()))
    base = spec_path.parent
    paths = [spec_path, *(base / rel for rel in spec.test_designs.values()),
             base / spec.installation_design]
    if spec.project_rules:
        paths.append(base / spec.project_rules)
    paths.append(PRESET_DIR / "calibration.json")
    return tuple(paths)


def _mtimes(paths: tuple[Path, ...]) -> tuple[float, ...]:
    """mtime per path, skipping one that does not exist -- `check.run` itself
    raises the real, user-facing error for a missing file; this is only ever
    used to invalidate a cache key."""
    return tuple(p.stat().st_mtime for p in paths if p.exists())


@st.cache_data(show_spinner="Checking every clause…")
def _run(path: str, dependency_mtimes: tuple[float, ...]) -> check.ComplianceReport:
    # This body only runs on a cache miss, i.e. exactly when `dependency_mtimes` says
    # something the run reads has changed on disk -- including, possibly,
    # solit2/presets/calibration.json. `load_calibration` is a process-wide cache the
    # Streamlit app keeps across reruns, so without this the Tier 1 engine below would
    # keep computing on the calibration that was loaded when this process started, even
    # though the cache key just decided a recompute was warranted.
    reload_calibration()
    return check.run(path)


def _verdict(headline: Headline) -> None:
    """The headline as the app's `.verdict` banner: pass only at 100 %."""
    cls = "pass" if headline.full else "fail"
    label = "COMPLIANT" if headline.full else "NOT COMPLIANT"
    st.markdown(
        f'<div class="verdict {cls}"><span class="verdict-label">{label}</span>'
        f'<span class="verdict-score">{headline.text}</span></div>',
        unsafe_allow_html=True)


def _chips(headline: Headline) -> None:
    """Verdict counts as chips, in the same PASS/FAIL/UNSET palette as the Result step.

    Three more chips break the complying count down by basis kind (I6): a
    single "% comply" figure otherwise mixes a laboratory measurement with a
    Tier 1 prediction of the same clause, which is not the same claim.
    """
    complies = f"Complies {headline.complying}"
    if headline.by_deviation:
        complies += f" ({headline.by_deviation} by deviation)"
    chips = (f'<span class="chip pass">{complies}</span>'
             f'<span class="chip fail">Fails {headline.fails}</span>'
             f'<span class="chip unset">Needs evidence {headline.needs_evidence}</span>'
             f'<span class="chip pass">Evidenced {headline.evidenced}</span>'
             f'<span class="chip pass">Planned {headline.planned}</span>'
             f'<span class="chip pass">Predicted {headline.predicted}</span>')
    st.markdown(chips, unsafe_allow_html=True)


def render() -> None:
    st.header("Compliance")
    st.caption("Every SOLIT² clause the planned test and its installation must meet. "
               "Needs evidence is never counted as compliant.")
    specs = [p for root in SPEC_ROOTS if root.exists() for p in find_specs(root)]
    if not specs:
        st.info("No compliance spec found. Add a *.json file with `spec_version` to designs/.")
        return
    choice = st.selectbox("Compliance spec", specs, format_func=str, key="compliance_spec")
    try:
        report = _run(str(choice), _mtimes(_dependency_paths(choice)))
    except (ValueError, FileNotFoundError, KeyError, RuntimeError, ArithmeticError) as exc:
        st.error(f"This spec cannot be checked: {exc}")
        return
    _verdict(report.headline)
    _chips(report.headline)
    st.subheader("Blockers")
    if report.blockers:
        st.dataframe([{"": ICON[f.verdict], "rule": f.rule_id, "clause": f.clause,
                       "found": f.found, "required": f.required, "basis": f.basis,
                       "basis kind": f.basis_kind}
                      for f in report.blockers], width="stretch", hide_index=True)
    else:
        st.markdown("None — every applicable clause complies.")
    st.download_button("Download what the lab must supply", report_md.lab_checklist(report),
                       file_name="compliance-checklist.md", key="compliance_checklist",
                       width="stretch")
    st.download_button("Download the full report", report_md.render(report),
                       file_name="compliance.md", key="compliance_report", width="stretch")
    st.subheader("Clause matrix")
    for group, items in report_md.by_group(report.findings):
        with st.expander(group):
            for f in items:
                st.markdown(f"{ICON[f.verdict]} **{f.rule_id}** — {f.clause}: {f.requirement}  \n"
                            f"found {f.found}; required {f.required}; basis {f.basis} "
                            f"({f.basis_kind})"
                            + (f"; evidence {f.evidence}" if f.evidence else "")
                            + (f"; {f.deviation}" if f.deviation else ""))

"""Step 5: the documents this design produces. Nothing here is uploaded — every
input is what the earlier steps already computed, and the exports are the
only downloads in the wizard."""
from __future__ import annotations

import streamlit as st

from app import state
from app.views import cfd
from app.views.result import ensure_result
from solit2.engines.reduced import envelope
from solit2.reports import correlation, test_plan, twin
from solit2.schema.design import Design
from solit2.schema.result import Result

EXPORT_COLUMNS = 3


def ensure_twin_result(design: Design) -> tuple[Design, Result] | None:
    """The test-facility twin and its Tier 1 result, or None after reporting why not."""
    try:
        twin_design = twin.test_facility_twin(design)
    except ValueError as exc:
        st.error(f"The test-facility twin could not be built: {exc}")
        return None
    result = state.get_twin_result()
    if result is None:
        try:
            with st.spinner("Running the test-facility twin…"):
                result = envelope.run(twin_design)
        except (ArithmeticError, RuntimeError, ValueError, KeyError) as exc:
            st.error(f"The test-facility twin could not be run: {exc}")
            return None
        state.set_twin_result(result)
    return twin_design, result


def _exports(items: list[tuple[str, str, str]]) -> None:
    st.subheader("Export")
    columns = st.columns(EXPORT_COLUMNS)
    for i, (file_name, data, label) in enumerate(items):
        columns[i % EXPORT_COLUMNS].download_button(label, data, file_name=file_name,
                                                    key=f"export_{i}", width="stretch")


def render() -> None:
    st.header("Reports")
    design = state.get_design()
    if design is None:
        st.info("Build a design first.")
        return
    result = ensure_result(design)
    name = design.meta.name
    exports = [(f"{name}.json", design.model_dump_json(indent=2), "Design JSON"),
               (f"{name}-result.json", result.model_dump_json(indent=2), "Tier 1 result JSON")]

    st.subheader("Test plan")
    plan_md = test_plan.render(design, result)
    st.markdown(plan_md)
    exports.append((f"{name}-test-plan.md", plan_md, "Test plan (.md)"))

    st.subheader("Site vs test facility")
    pair = ensure_twin_result(design)
    if pair is not None:
        twin_design, twin_result = pair
        st.info(twin_design.meta.notes)
        site_vs_test = correlation.render(twin_result, result)
        st.markdown(site_vs_test)
        exports += [("correlation-site-vs-test-facility.md", site_vs_test,
                     "Site vs test facility (.md)"),
                    (f"{twin_design.meta.name}-result.json", twin_result.model_dump_json(indent=2),
                     "Twin result JSON")]

    st.subheader("Tier 1 vs Tier 2")
    tier2 = state.get_tier2_result()
    if tier2 is None:
        st.caption("Run the CFD step to add the Tier 2 comparison.")
    else:
        tiers = correlation.render(result, tier2)
        # The caveat travels with the export: off-screen the table loses all its context.
        caveat = cfd.window_caveat(cfd.run_dir_for(design), design)
        if caveat:
            tiers = f"{tiers}\n\n> **{caveat}**\n"
            st.warning(caveat)
        st.markdown(tiers)
        exports += [("correlation-tier1-vs-tier2.md", tiers, "Tier 1 vs Tier 2 (.md)"),
                    (f"{name}-fds-result.json", tier2.model_dump_json(indent=2),
                     "Tier 2 result JSON")]
    _exports(exports)

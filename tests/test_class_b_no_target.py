"""Annex 7 5.2.6 sites a fire target for Class A fires only. A Class B run has
none, so Tier 1 must not invent one and the drawings must not draw one."""
import pytest

from solit2.engines.reduced import envelope
from solit2.engines.reduced.geometry import section_geometry
from solit2.schema.design import Design

CLASS_A = "examples/designs/solit2-test-protocol.json"
CLASS_B = "examples/designs/solit2-test-protocol-class-b.json"


@pytest.fixture(scope="module")
def class_b_result():
    return envelope.run(Design.load(CLASS_B))


def test_only_a_class_a_fire_has_a_target():
    assert Design.load(CLASS_A).fire.has_target is True
    assert Design.load(CLASS_B).fire.has_target is False


def test_a_class_b_run_has_no_target_criterion_and_no_target_flux(class_b_result):
    # No target, so no "target did not ignite" verdict to pass or fail: the
    # criterion is absent rather than a trivially passed one.
    assert "target_ignited" not in class_b_result.criteria
    assert class_b_result.peaks["target_peak_flux_kwm2"] == 0.0
    assert class_b_result.peaks["target_max_exposure_s"] == 0.0
    assert "hrr_below_tvs_design_mw" in class_b_result.criteria


def test_a_class_a_run_still_judges_the_target():
    result = envelope.run(Design.load(CLASS_A))
    assert "target_ignited" in result.criteria
    assert result.peaks["target_peak_flux_kwm2"] > 0.0


def test_the_plan_view_draws_a_target_only_for_class_a():
    from app.components import overview
    a, b = Design.load(CLASS_A), Design.load(CLASS_B)
    assert len(overview.fire_and_target(a, section_geometry(a))) == 2
    assert len(overview.fire_and_target(b, section_geometry(b))) == 1


def test_the_readings_tiles_cope_with_a_class_b_result(class_b_result):
    from app.components import readings
    (tile,) = [t for t in readings.tiles(class_b_result) if t.label == "Target"]
    assert tile.value == "none"


@pytest.fixture(scope="module")
def class_b_run():
    from solit2.engines.reduced.sim import run_once
    design = Design.load(CLASS_B)
    return design, run_once(design, design.tunnel.section, design.ventilation.velocity_range_ms[0])


def test_the_2d_twin_draws_no_target_for_class_b(class_b_run):
    from app.components import twin_canvas
    design, trace = class_b_run
    geom = section_geometry(design)
    traces, shapes = twin_canvas.tunnel_layer(design, geom, twin_canvas.WINDOW_M, trace.steps[0])
    assert [s for s in shapes if s.get("line", {}).get("dash") == "dot"] == []
    labels = [t for tr in traces if getattr(tr, "name", "") == "labels" for t in tr.text]
    assert not any("target" in label for label in labels)
    lo, hi = twin_canvas.core_window_m(design)
    # the zoom window is sized from the active zone and the mock-up, not a target
    assert hi == pytest.approx(max(design.active_length_m / 2, design.fire.footprint.length_m / 2)
                               + twin_canvas.CORE_WINDOW_MARGIN_M)


def test_the_3d_twin_and_the_cross_section_draw_no_target_for_class_b(class_b_run):
    from app.components import cross_section, tunnel3d
    design, trace = class_b_run
    geom = section_geometry(design)
    mesh = tunnel3d._target(design, geom, trace.steps[0])
    assert len(mesh.x) == 0
    assert cross_section.fuel_section(design, geom, "Target") is None


def test_the_live_charts_omit_the_target_flux_line_for_class_b(class_b_run):
    from app.components import live_figure
    design, trace = class_b_run
    names = [line.name for _, line in live_figure._series(trace, design)]
    assert "flux at the target" not in names

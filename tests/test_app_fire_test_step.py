from solit2 import history


def test_fire_test_step_renders_hmi_canvas_timeline_and_station_chart(run_view, monkeypatch, tmp_path):
    monkeypatch.setattr(history, "DEFAULT_PATH", tmp_path / "h.jsonl")
    at = run_view("fire_test")
    assert not at.exception
    assert [m.label for m in at.metric][:5] == ["Test clock", "HRR", "Water", "Tank remaining", "Ventilation"]
    assert len(at.select_slider) == 1 and len(at.toggle) == 1 and len(at.selectbox) == 1
    assert any('class="lamps"' in m.value for m in at.markdown)
    assert not at.get("file_uploader") and not at.get("download_button")


def test_the_clock_slider_drives_the_readouts(run_view, monkeypatch, tmp_path):
    monkeypatch.setattr(history, "DEFAULT_PATH", tmp_path / "h.jsonl")
    at = run_view("fire_test")
    first = at.select_slider(key="twin_clock").options[0]
    at.select_slider(key="twin_clock").set_value(first).run()
    assert at.metric[0].value == first and at.metric[2].value == "0 L/min"
    last = at.select_slider(key="twin_clock").options[-1]
    at.select_slider(key="twin_clock").set_value(last).run()
    assert at.metric[0].value == last


def test_zoom_toggle_and_station_pick_rerender_cleanly(run_view, monkeypatch, tmp_path):
    monkeypatch.setattr(history, "DEFAULT_PATH", tmp_path / "h.jsonl")
    at = run_view("fire_test")
    at.toggle(key="twin_zoom").set_value(True).run()
    at.selectbox(key="station").set_value("U45").run()
    assert not at.exception


def test_zoom_toggle_uses_a_window_derived_from_the_design_not_a_fixed_constant(
        run_view, monkeypatch, tmp_path):
    """`CORE_WINDOW_M` is a fixed constant borrowed from the FDS deck's simulation
    domain; the zoom toggle must derive its window from the actual design instead,
    or a design with a wider active zone gets its own heads and mist clipped."""
    import json

    from app.views import fire_test
    from tests.conftest import EXAMPLE_DESIGN
    from solit2.schema.design import Design

    monkeypatch.setattr(history, "DEFAULT_PATH", tmp_path / "h.jsonl")
    at = run_view("fire_test")
    at.toggle(key="twin_zoom").set_value(True).run()
    assert not at.exception

    canvas = next(e for e in at.get("plotly_chart") if e.key == "twin_canvas")
    rendered_range = tuple(json.loads(canvas.proto.spec)["layout"]["xaxis"]["range"])

    design = Design.load(EXAMPLE_DESIGN)
    assert rendered_range == fire_test.twin_canvas.core_window_m(design)
    assert rendered_range != fire_test.twin_canvas.CORE_WINDOW_M

from solit2 import history


def test_the_trace_cache_is_bounded():
    """I-2: one cached `RunTrace` is 4-7 MB, and the simulator makes one per
    slider release, shared by every session on the server -- an unbounded cache
    would grow without limit."""
    from app.views import fire_test

    assert fire_test._trace._info.max_entries == 16


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


def test_cross_section_renders_and_follows_the_station_picker(run_view, monkeypatch, tmp_path):
    monkeypatch.setattr(history, "DEFAULT_PATH", tmp_path / "h.jsonl")
    at = run_view("fire_test")
    assert not at.exception
    assert any(e.key == "cross_section" for e in at.get("plotly_chart"))

    at.selectbox(key="station").set_value("D15").run()
    assert not at.exception
    cross = next(e for e in at.get("plotly_chart") if e.key == "cross_section")
    assert "D15" in cross.proto.spec


def test_charts_with_a_temperature_colourscale_opt_out_of_streamlits_theme(
        run_view, monkeypatch, tmp_path):
    """Streamlit's own theme rewrites a sequential colourscale's near-black stop to an
    accent colour unless the chart opts out with theme=None -- caught live when a 30 C
    thermocouple reading rendered the same bright colour as a genuinely hot one. Every
    chart using Inferno (twin_canvas, cross_section) must carry that flag."""
    monkeypatch.setattr(history, "DEFAULT_PATH", tmp_path / "h.jsonl")
    at = run_view("fire_test")
    for key in ("twin_canvas", "cross_section"):
        chart = next(e for e in at.get("plotly_chart") if e.key == key)
        assert chart.proto.theme == "", f"{key} must pass theme=None or Inferno's cold end breaks"

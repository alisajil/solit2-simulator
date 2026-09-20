"""No FDS is assumed: the runner is stubbed at the module boundary."""
from pathlib import Path

from solit2 import history
from solit2.engines.fds import reader as fds_reader
from solit2.engines.fds import runner as fds_runner
from solit2.engines.reduced import envelope
from solit2.engines.reduced.envelope import _design_sha
from solit2.schema.design import Design

EXAMPLE = "examples/designs/road-tunnel-twin-bore.json"


def _isolate(monkeypatch, tmp_path, problems):
    from app.views import cfd
    monkeypatch.setattr(history, "DEFAULT_PATH", tmp_path / "h.jsonl")
    monkeypatch.setattr(cfd, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setattr(fds_runner, "preflight", lambda: problems)
    monkeypatch.setattr(fds_runner, "smokeview_binary", lambda: None)
    return tmp_path / "runs" / _design_sha(Design.load(EXAMPLE))


def _fake_run(run_dir: Path, log: str, t_end: float = 1200.0) -> None:
    run_dir.mkdir(parents=True)
    (run_dir / "deck.fds").write_text(f"&HEAD CHID='x' /\n&TIME T_END={t_end} /\n")
    (run_dir / "x.out").write_text(log)


def test_without_fds_the_step_says_so_and_offers_no_start(run_view, monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path, ["the fds binary is not on PATH"])
    at = run_view("cfd")
    assert not at.exception
    assert any("fds binary" in m.value for m in at.markdown)
    assert all(b.key != "fds_start" for b in at.button)
    assert not at.get("file_uploader")


def test_with_fds_ready_the_start_button_names_the_default_window(run_view, monkeypatch, tmp_path):
    _isolate(monkeypatch, tmp_path, [])
    at = run_view("cfd")
    assert at.radio(key="fds_minutes").value == "20 min"
    assert at.button(key="fds_start").label == "Start FDS run (20 min)"


def test_start_writes_the_shortened_deck_and_launches(run_view, monkeypatch, tmp_path):
    run_dir = _isolate(monkeypatch, tmp_path, [])
    launched = []
    monkeypatch.setattr(fds_runner, "run", lambda deck, out: launched.append((deck, out)) or out.name)
    at = run_view("cfd")
    at.radio(key="fds_minutes").set_value("5 min").run()
    at.button(key="fds_start").click().run()
    assert launched and launched[0][1] == run_dir
    assert "T_END=300.0" in (run_dir / "deck.fds").read_text()


def test_a_running_run_shows_progress_and_hides_start(run_view, monkeypatch, tmp_path):
    run_dir = _isolate(monkeypatch, tmp_path, [])
    _fake_run(run_dir, "Time Step 10\n Total Time:  120.0 s\n")
    at = run_view("cfd")
    assert not at.exception
    assert at.get("progress") and all(b.key != "fds_start" for b in at.button)
    assert any("Preliminary" in c.value or "not written" in c.value
               for c in list(at.info) + list(at.caption))


def test_a_finished_run_reads_tier_two_and_correlates(run_view, monkeypatch, tmp_path):
    run_dir = _isolate(monkeypatch, tmp_path, [])
    _fake_run(run_dir, "Total Time: 1200.0 s\nSTOP: FDS completed successfully\n")
    tier1 = envelope.run(Design.load(EXAMPLE))
    monkeypatch.setattr(fds_reader, "read", lambda d, design, **kw: tier1)
    at = run_view("cfd")
    assert not at.exception
    assert at.session_state["tier2_result"] is not None
    assert any(m.value.startswith("# Correlation") for m in at.markdown)
    assert at.button(key="open_smv").disabled
    assert at.button(key="fds_start").label.startswith("Re-run FDS")


def test_stamp_changes_when_a_slice_file_changes(tmp_path):
    from app.views import cfd
    (tmp_path / "a_1_1.sf").write_bytes(b"1")
    before = cfd.stamp(tmp_path)
    (tmp_path / "a_1_1.sf").write_bytes(b"12")
    assert cfd.stamp(tmp_path) != before


def test_a_failed_run_never_captions_its_field_as_complete(run_view, monkeypatch, tmp_path):
    """A run that died mid-simulation must not describe its partial field as finished.

    The canvas caption keys off the run's actual state, not merely "is it still
    running", so `failed` gets its own wording rather than falling through to the
    completed-run sentence.
    """
    import numpy as np

    from app.views import cfd
    from solit2.engines.fds.slices import Slice

    run_dir = _isolate(monkeypatch, tmp_path, [])
    _fake_run(run_dir, "Total Time: 300.0 s\n ERROR: Numerical instability\n")
    partial = Slice("TEMPERATURE", "C", np.linspace(-10.0, 10.0, 4), np.linspace(0.0, 6.0, 3),
                    np.array([0.0, 150.0, 300.0]), np.zeros((3, 3, 4)))
    monkeypatch.setattr(cfd, "_load_slice", lambda *a, **kw: partial)
    at = run_view("cfd")

    assert not at.exception
    captions = [c.value for c in at.caption]
    assert any("did not finish" in c for c in captions), captions
    assert not any(c.startswith("Preliminary") for c in captions), captions
    assert not any("frames to t =" in c for c in captions), captions


def test_a_failed_run_with_no_slice_says_the_run_died_not_that_the_field_is_absent(
        run_view, monkeypatch, tmp_path):
    """Absence of a slice after a crash is not the same claim as a run that simply has none."""
    run_dir = _isolate(monkeypatch, tmp_path, [])
    _fake_run(run_dir, "Total Time: 300.0 s\n ERROR: Numerical instability\n")
    at = run_view("cfd")

    assert not at.exception
    notes = [i.value for i in at.info]
    assert any("did not finish and never wrote" in n for n in notes), notes
    assert not any("holds no" in n for n in notes), notes


def test_an_unreadable_slice_is_reported_without_taking_the_step_down(
        run_view, monkeypatch, tmp_path):
    """A real run can hold meshes the reader cannot stitch; that must not crash the page."""
    from app.views import cfd

    run_dir = _isolate(monkeypatch, tmp_path, [])
    _fake_run(run_dir, "Total Time: 1200.0 s\nSTOP: FDS completed successfully\n")

    def unreadable(*a, **kw):
        raise ValueError("meshes on the centreline do not share a z grid")

    monkeypatch.setattr(cfd, "_load_slice", unreadable)
    monkeypatch.setattr(fds_reader, "read", lambda d, design, **kw: envelope.run(Design.load(EXAMPLE)))
    at = run_view("cfd")

    assert not at.exception
    assert any("could not be read" in w.value for w in at.warning)


def test_a_shortened_tier_two_window_is_named_beside_the_correlation(
        run_view, monkeypatch, tmp_path):
    """A truncated FDS run is biased toward passing; the table must say the windows differ.

    Peak and dose criteria (max_air_temp_c, max_fed, max_co_ppm, exposure duration) are
    evaluated over whatever trace exists, so comparing a 20-minute Tier 2 against a
    full-length Tier 1 without saying so overstates the agreement.
    """
    run_dir = _isolate(monkeypatch, tmp_path, [])
    _fake_run(run_dir, "Total Time: 1200.0 s\nSTOP: FDS completed successfully\n", t_end=1200.0)
    monkeypatch.setattr(fds_reader, "read", lambda d, design, **kw: envelope.run(Design.load(EXAMPLE)))
    at = run_view("cfd")

    assert not at.exception
    warnings = [w.value for w in at.warning]
    assert any("not comparable" in w and "1200" in w for w in warnings), warnings


def test_a_full_length_window_carries_no_caveat(monkeypatch, tmp_path):
    from app.views import cfd

    design = Design.load(EXAMPLE)
    run_dir = tmp_path / "full"
    run_dir.mkdir()
    full_s = design.zones.duration_min * 60.0
    (run_dir / "deck.fds").write_text(f"&HEAD CHID='x' /\n&TIME T_END={full_s} /\n")
    assert cfd.window_caveat(run_dir, design) is None


def test_only_the_selected_field_is_built(run_view, monkeypatch, tmp_path):
    """st.tabs runs every tab body on every rerun; each figure costs seconds and megabytes.

    This step reruns every few seconds while a run is live, so building the two fields
    nobody is looking at is most of the work it does.
    """
    from app.views import cfd

    run_dir = _isolate(monkeypatch, tmp_path, [])
    _fake_run(run_dir, "Total Time: 1200.0 s\nSTOP: FDS completed successfully\n", t_end=1200.0)
    monkeypatch.setattr(fds_reader, "read", lambda d, design, **kw: envelope.run(Design.load(EXAMPLE)))

    asked: list[str] = []

    def record(run_dir_str, quantity, stamp_key):
        asked.append(quantity)
        return None

    monkeypatch.setattr(cfd, "_load_slice", record)
    at = run_view("cfd")

    assert not at.exception
    assert asked == ["TEMPERATURE"], asked


def test_the_cfd_chart_opts_out_of_streamlits_theme(run_view, monkeypatch, tmp_path):
    """Same bug class as the fire-test twin: Streamlit rewrites a sequential
    colourscale's near-black stop to an accent colour unless the chart carries
    theme=None, which would make a cold cell read as the hottest thing on screen."""
    import numpy as np

    from app.views import cfd
    from solit2.engines.fds.slices import Slice

    run_dir = _isolate(monkeypatch, tmp_path, [])
    _fake_run(run_dir, "Total Time: 1200.0 s\nSTOP: FDS completed successfully\n", t_end=1200.0)
    partial = Slice("TEMPERATURE", "C", np.linspace(-10.0, 10.0, 4), np.linspace(0.0, 6.0, 3),
                    np.array([0.0, 600.0, 1200.0]), np.zeros((3, 3, 4)))
    monkeypatch.setattr(cfd, "_load_slice", lambda *a, **kw: partial)
    at = run_view("cfd")
    chart = next(e for e in at.get("plotly_chart") if e.key == "cfd_TEMPERATURE")
    assert chart.proto.theme == ""


def _heatmap(chart) -> dict:
    import json
    return next(tr for tr in json.loads(chart.proto.spec)["data"] if tr.get("type") == "heatmap")


def _z_values(heat: dict) -> list[float]:
    """Plotly ships a numeric array as base64 binary, not a nested list."""
    import base64

    import numpy as np
    z = heat["z"]
    if isinstance(z, dict):
        return list(np.frombuffer(base64.b64decode(z["bdata"]), dtype=z["dtype"]))
    return [v for row in z for v in row]


def _control(at, key: str):
    """A segmented control: AppTest exposes it as a button group."""
    return next(c for c in at.get("button_group") if c.key == key)


def _free_dir(run_dir: Path) -> Path:
    from solit2.engines.fds import deck
    return run_dir.parent / deck.chid(Design.load(EXAMPLE), suppression=False)


def test_the_free_burn_scenario_launches_its_own_deck_without_a_mist_system(run_view, monkeypatch, tmp_path):
    run_dir = _isolate(monkeypatch, tmp_path, [])
    launched = []
    monkeypatch.setattr(fds_runner, "run", lambda deck, out: launched.append(out) or out.name)
    at = run_view("cfd")
    _control(at, "cfd_scenario").set_value("Free burn").run()
    at.button(key="fds_start_free").click().run()
    free = _free_dir(run_dir)
    assert launched == [free] and free != run_dir
    text = (free / "deck.fds").read_text()
    assert "&PART" not in text and "PROP_ID=" not in text
    assert "SURF_IDS='FIRE0'" in text, "same fire, no water"


def test_the_free_burn_field_selector_offers_no_mist_field(run_view, monkeypatch, tmp_path):
    from app.views import cfd
    run_dir = _isolate(monkeypatch, tmp_path, [])
    _fake_run(_free_dir(run_dir), "Total Time: 1200.0 s\nSTOP: FDS completed successfully\n")
    monkeypatch.setattr(cfd, "_load_slice", lambda *a, **kw: None)
    at = run_view("cfd")
    _control(at, "cfd_scenario").set_value("Free burn").run()
    assert not at.exception
    fields = _control(at, "cfd_quantity")
    assert "Mist" not in fields.options and "Temperature" in fields.options


def test_with_both_runs_the_difference_field_is_offered_and_drawn(run_view, monkeypatch, tmp_path):
    import numpy as np

    from app.views import cfd
    from solit2.engines.fds.slices import Slice

    run_dir = _isolate(monkeypatch, tmp_path, [])
    done = "Total Time: 1200.0 s\nSTOP: FDS completed successfully\n"
    _fake_run(run_dir, done)
    _fake_run(_free_dir(run_dir), done)
    x, z, t = np.linspace(-10.0, 10.0, 4), np.linspace(0.0, 6.0, 3), np.array([0.0, 600.0, 1200.0])
    mist = Slice("TEMPERATURE", "C", x, z, t, np.full((3, 3, 4), 100.0))
    free = Slice("TEMPERATURE", "C", x, z, t, np.full((3, 3, 4), 400.0))
    monkeypatch.setattr(cfd, "_load_slice", lambda d, q, k: mist if d == str(run_dir) else free)
    monkeypatch.setattr(fds_reader, "read", lambda d, design, **kw: envelope.run(Design.load(EXAMPLE)))
    at = run_view("cfd")
    assert not at.exception
    assert any(e.key == "cfd_TEMPERATURE" for e in at.get("plotly_chart"))
    at.checkbox(key="cfd_compare").check().run()
    chart = next(e for e in at.get("plotly_chart") if e.key == "cfd_diff_TEMPERATURE")
    assert chart.proto.theme == ""
    heat = _heatmap(chart)
    assert _z_values(heat)[0] == -300.0, "mist minus free burn: cooler with mist reads negative"
    assert heat["zmin"] == -heat["zmax"], "a difference field is centred on zero"


def test_the_hrr_comparison_draws_every_curve_that_exists_and_no_placeholder(run_view, monkeypatch, tmp_path):
    import json

    from app.views import cfd
    from solit2.engines.fds import deck

    run_dir = _isolate(monkeypatch, tmp_path, [])
    done = "Total Time: 1200.0 s\nSTOP: FDS completed successfully\n"
    _fake_run(run_dir, done)
    design = Design.load(EXAMPLE)
    (run_dir / f"{deck.chid(design)}_hrr.csv").write_text(
        "s,kW\nTime,HRR\n0.0,0.0\n600.0,20000.0\n1200.0,30000.0\n")
    monkeypatch.setattr(cfd, "_load_slice", lambda *a, **kw: None)
    monkeypatch.setattr(fds_reader, "read", lambda d, design, **kw: envelope.run(design))
    at = run_view("cfd")
    assert not at.exception
    chart = next(e for e in at.get("plotly_chart") if e.key == "cfd_hrr")
    names = [tr["name"] for tr in json.loads(chart.proto.spec)["data"]]
    assert "Tier 2 · with mist" in names and "Tier 2 · free burn" not in names
    assert "Tier 1 · with mist" in names and "Tier 1 · free burn" in names


def test_a_finished_free_burn_feeds_the_tier_two_reader(run_view, monkeypatch, tmp_path):
    run_dir = _isolate(monkeypatch, tmp_path, [])
    done = "Total Time: 1200.0 s\nSTOP: FDS completed successfully\n"
    _fake_run(run_dir, done)
    _fake_run(_free_dir(run_dir), done)
    seen = {}

    def fake_read(d, design, **kw):
        seen.update(kw)
        return envelope.run(design)

    monkeypatch.setattr(fds_reader, "read", fake_read)
    at = run_view("cfd")
    assert not at.exception
    assert seen.get("free_burn_dir") == _free_dir(run_dir)


def test_switching_to_the_free_burn_while_the_mist_field_is_selected_does_not_break(
        run_view, monkeypatch, tmp_path):
    """The Mist field exists only for the suppressed run. A viewer who selects it
    and then switches scenario leaves a held widget value that is no longer an
    option -- the widget-state trap this project has been bitten by before."""
    from app.views import cfd
    run_dir = _isolate(monkeypatch, tmp_path, [])
    done = "Total Time: 1200.0 s\nSTOP: FDS completed successfully\n"
    _fake_run(run_dir, done)
    _fake_run(_free_dir(run_dir), done)
    asked: list[str] = []

    def record(run_dir_str, quantity, stamp_key):
        asked.append(quantity)
        return None

    monkeypatch.setattr(cfd, "_load_slice", record)
    monkeypatch.setattr(fds_reader, "read", lambda d, design, **kw: envelope.run(Design.load(EXAMPLE)))
    at = run_view("cfd")
    _control(at, "cfd_quantity").set_value("Mist").run()
    assert not at.exception and asked[-1] == "FINE MPUV"
    _control(at, "cfd_scenario").set_value("Free burn").run()
    assert not at.exception, "a held field that the new scenario does not offer must not crash"
    assert asked[-1] != "FINE MPUV", "a free burn has no particles to show"

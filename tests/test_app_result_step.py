import json
from pathlib import Path

from streamlit.testing.v1 import AppTest

from solit2 import history
from tests.conftest import EXAMPLE_DESIGN


def _redirect_history(monkeypatch, tmp_path):
    path = tmp_path / "history.jsonl"
    monkeypatch.setattr(history, "DEFAULT_PATH", path)
    return path


def test_result_step_auto_runs_records_history_and_shows_an_honest_verdict(run_view, monkeypatch, tmp_path):
    path = _redirect_history(monkeypatch, tmp_path)
    at = run_view("result")
    assert not at.exception and not at.button  # no "run" button anywhere
    result = at.session_state["result"]
    assert result is not None and len(path.read_text().splitlines()) == 1
    banner = next(m.value for m in at.markdown if 'class="verdict' in m.value)
    assert ("PASS" in banner) == (not result.score["gates_failed"])
    unset = result.score["criteria_unset"]
    assert (f"{len(unset)} criteria not judged" in banner) == bool(unset)


def test_a_rerun_does_not_append_history_again(run_view, monkeypatch, tmp_path):
    path = _redirect_history(monkeypatch, tmp_path)
    at = run_view("result")
    at.run()
    assert len(path.read_text().splitlines()) == 1


def test_gate_chips_carry_each_hard_criterions_status(run_view, monkeypatch, tmp_path):
    _redirect_history(monkeypatch, tmp_path)
    at = run_view("result")
    result = at.session_state["result"]
    chips = next(m.value for m in at.markdown if 'class="chip' in m.value)
    for name, c in result.criteria.items():
        if c.hard:
            assert f'class="chip {c.status}">{name}<' in chips


def test_leaderboard_marks_the_current_design(run_view, monkeypatch, tmp_path):
    _redirect_history(monkeypatch, tmp_path)
    at = run_view("result")
    table = next(d.value for d in at.dataframe if "this" in d.value.columns)
    assert list(table["this"]) == ["◀"]


def test_a_failed_gate_never_reads_pass(monkeypatch, tmp_path):
    """The load-bearing honesty guarantee, driven from a design that actually fails.

    Every other test here seeds the example design, which passes every gate it is
    judged against, so they only ever exercise the PASS side of the banner. This one
    sets an air-temperature limit the design cannot meet -- the kind of limit an AHJ
    declares -- so `gates_failed` is non-empty and the FAIL branch is exercised.
    """
    _redirect_history(monkeypatch, tmp_path)
    raw = json.loads(Path(EXAMPLE_DESIGN).read_text())
    raw["ahj"] = {**(raw.get("ahj") or {}), "max_air_temp_c": 1.0}
    failing = tmp_path / "failing.json"
    failing.write_text(json.dumps(raw))

    at = AppTest.from_string(
        "import streamlit as st\n"
        "from app import state, theme\n"
        "from app.views import result as view\n"
        "from solit2.schema.design import Design\n"
        "theme.inject()\n"
        f'state.set_design(Design.load(r"{failing}"))\n'
        "view.render()\n", default_timeout=90.0)
    at.run()

    assert not at.exception
    result = at.session_state["result"]
    assert result.score["gates_failed"], "fixture must actually fail a gate"
    banner = next(m.value for m in at.markdown if 'class="verdict' in m.value)
    assert "FAIL" in banner and "PASS" not in banner
    assert f'{len(result.score["criteria_unset"])} criteria not judged' in banner


def test_the_verdict_states_what_the_engine_rests_on(run_view, monkeypatch, tmp_path):
    """INDEPENDENCE rule 3: a green PASS must not read as a measurement.

    The engine's constants were fitted against reference cases that used a different
    nozzle, so every number here is an extrapolation until a full-scale test exists.
    The result carries that sentence in its own meta; the screen has to show it.
    """
    _redirect_history(monkeypatch, tmp_path)
    at = run_view("result")
    captions = [c.value for c in at.caption]
    assert any("not a measurement" in c for c in captions), captions
    assert any(at.session_state["result"].meta["calibration_note"] in c for c in captions)

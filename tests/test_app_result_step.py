from solit2 import history


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

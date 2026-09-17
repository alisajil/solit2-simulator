from pathlib import Path

from streamlit.testing.v1 import AppTest


def test_leaderboard_page_shows_an_empty_state_with_no_history(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)  # history.py's DEFAULT_PATH is relative: runs/history.jsonl
    at = AppTest.from_file("../app/streamlit_app.py")
    at.run()
    at.sidebar.radio[0].set_value("Leaderboard").run()
    assert not at.exception
    assert any("no run" in i.value.lower() for i in at.info)


def test_saving_a_run_makes_it_appear_on_the_leaderboard(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    at = AppTest.from_file("../app/streamlit_app.py")
    at.run()
    at.sidebar.radio[0].set_value("Design").run()
    at.button[0].click().run()
    at.sidebar.radio[0].set_value("Run").run()
    at.button[0].click().run()
    at.sidebar.radio[0].set_value("Leaderboard").run()
    assert not at.exception
    assert any("save" in b.label.lower() for b in at.button)
    [b for b in at.button if "save" in b.label.lower()][0].click().run()
    assert Path("runs/history.jsonl").exists()
    at.run()
    assert len(at.dataframe) >= 1

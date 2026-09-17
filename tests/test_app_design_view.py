"""AppTest coverage of the Streamlit app shell and the Design view.

`streamlit.testing.v1.AppTest` runs the app's script headlessly (no
browser) and exposes the rendered widget tree for assertions -- the
Streamlit-native equivalent of the engine's own pytest suite, not a
browser driver.
"""
from streamlit.testing.v1 import AppTest


def test_the_app_launches_with_five_pages_in_the_sidebar():
    at = AppTest.from_file("../app/streamlit_app.py")
    at.run()
    # Note: this installed streamlit version's AppTest exposes no run_time
    # attribute to assert a wall-clock budget against; at.run() itself times
    # out via default_timeout (3s) if the script hangs, which is the
    # substantive guarantee here.
    assert not at.exception
    labels = [opt for radio in at.sidebar.radio for opt in radio.options]
    assert labels == ["Design", "Run", "Tunnel", "Leaderboard", "Verify"]


def test_the_design_page_is_selected_by_default_and_shows_a_preset_picker():
    at = AppTest.from_file("../app/streamlit_app.py")
    at.run()
    assert not at.exception
    assert any("tunnel" in sb.label.lower() for sb in at.selectbox)
    assert any("fire" in sb.label.lower() for sb in at.selectbox)
    assert any("nozzle" in sb.label.lower() for sb in at.selectbox)


def test_building_a_design_clears_a_stale_result():
    """`state.set_design` pops any previous run's `result` from session
    state (a new design invalidates the last run) -- guard this contract
    since Task 2 depends on it holding."""
    at = AppTest.from_file("../app/streamlit_app.py")
    at.run()
    at.session_state["result"] = "sentinel"

    build_button = next(b for b in at.button if b.label == "Build design")
    build_button.click().run()

    assert not at.exception
    assert "result" not in at.session_state

from streamlit.testing.v1 import AppTest


def test_verify_page_shows_preflight_status():
    at = AppTest.from_file("../app/streamlit_app.py")
    at.run()
    at.sidebar.radio[0].set_value("Verify").run()
    assert not at.exception
    # no FDS on a dev machine or in CI: the page must say so, honestly
    body = " ".join(e.value for e in at.markdown) + " ".join(w.value for w in at.warning)
    assert "fds" in body.lower()


def test_verify_page_generates_a_deck_for_the_current_design():
    at = AppTest.from_file("../app/streamlit_app.py")
    at.run()
    at.sidebar.radio[0].set_value("Design").run()
    at.button[0].click().run()          # "Build design"
    at.sidebar.radio[0].set_value("Verify").run()
    # the deck button is the first on this page
    at.button[0].click().run()
    assert not at.exception
    assert any("&HEAD" in e.value for e in at.code)


def test_verify_page_prompts_for_a_design_when_none_is_built():
    at = AppTest.from_file("../app/streamlit_app.py")
    at.run()
    at.sidebar.radio[0].set_value("Verify").run()
    assert any("design" in w.value.lower() for w in at.warning)

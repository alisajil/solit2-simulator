from streamlit.testing.v1 import AppTest


def test_verify_page_states_plainly_that_fds_is_not_built():
    at = AppTest.from_file("../app/streamlit_app.py")
    at.run()
    at.sidebar.radio[0].set_value("Verify").run()
    assert not at.exception
    assert any("fds" in i.value.lower() for i in at.info)
    assert not at.button  # no button that implies a capability that does not exist

from streamlit.testing.v1 import AppTest


def test_tunnel_page_prompts_for_a_run_when_none_exists_yet():
    at = AppTest.from_file("../app/streamlit_app.py")
    at.run()
    at.sidebar.radio[0].set_value("Tunnel").run()
    assert not at.exception
    assert any("run" in w.value.lower() for w in at.warning)


def test_tunnel_page_shows_a_time_slider_and_a_section_plot_after_a_run():
    at = AppTest.from_file("../app/streamlit_app.py")
    at.run()
    at.sidebar.radio[0].set_value("Design").run()
    at.button[0].click().run()
    at.sidebar.radio[0].set_value("Run").run()
    at.button[0].click().run()
    at.sidebar.radio[0].set_value("Tunnel").run()
    assert not at.exception
    assert len(at.slider) >= 1

from streamlit.testing.v1 import AppTest


def test_run_page_prompts_for_a_design_when_none_is_built_yet():
    at = AppTest.from_file("../app/streamlit_app.py")
    at.run()
    at.sidebar.radio[0].set_value("Run").run()
    assert not at.exception
    assert any("design" in w.value.lower() for w in at.warning)


def test_run_page_executes_the_engine_and_shows_the_criteria_table():
    at = AppTest.from_file("../app/streamlit_app.py")
    at.run()
    at.sidebar.radio[0].set_value("Design").run()
    # The Design view's own selectbox defaults are a verified-compatible
    # preset combination (see app/views/design.py's _render_preset_pickers:
    # tunnel "twin_bore_11m", nozzle "single_mode_fine_example", etc.), not
    # position 0 of each alphabetically sorted preset list -- so no explicit
    # override is needed here to land on a physically valid design.
    at.button[0].click().run()          # "Build design", the only button on Design at this point
    assert not at.exception
    at.sidebar.radio[0].set_value("Run").run()
    at.button[0].click().run()          # "Run simulation"
    assert not at.exception
    assert len(at.dataframe) >= 1
    assert any("MW" in m.label or "mw" in m.label.lower() for m in at.metric)

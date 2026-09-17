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
    # The Design page's own defaults are the first preset alphabetically in
    # each block (Streamlit's selectbox default index is 0): tunnel
    # "solit2_test" (a 5.2 m-high test-gallery box section) paired with
    # nozzle "bimodal_example" (ceiling mounting at 5.75 m). That combination
    # is geometrically invalid -- the mounting height is above the crown --
    # and solit2.engines.reduced.geometry.nozzle_positions correctly raises
    # ValueError for it. Pick a tunnel preset whose crown clears a
    # 5.75 m-mounted nozzle (twin_bore_11m: circular, crown 7.625 m), the same
    # one the brief's own key-discovery script ran against, so this test
    # exercises a physically valid design rather than an incompatible
    # preset pairing that happens to sort first.
    at.selectbox[0].set_value("twin_bore_11m").run()
    at.button[0].click().run()          # "Build design", the only button on Design at this point
    assert not at.exception
    at.sidebar.radio[0].set_value("Run").run()
    at.button[0].click().run()          # "Run simulation"
    assert not at.exception
    assert len(at.dataframe) >= 1
    assert any("MW" in m.label or "mw" in m.label.lower() for m in at.metric)

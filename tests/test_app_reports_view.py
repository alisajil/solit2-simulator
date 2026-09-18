from streamlit.testing.v1 import AppTest

from solit2.engines.reduced import envelope
from solit2.schema.design import Design

SITE_DESIGN = "examples/designs/road-tunnel-twin-bore.json"
TEST_DESIGN = "examples/designs/solit2-test-protocol.json"


def test_reports_page_prompts_for_a_run_when_none_exists_yet():
    at = AppTest.from_file("../app/streamlit_app.py")
    at.run()
    at.sidebar.radio[0].set_value("Reports").run()
    assert not at.exception
    assert any("run" in w.value.lower() for w in at.warning)


def test_reports_page_shows_the_test_plan_after_a_run():
    at = AppTest.from_file("../app/streamlit_app.py")
    at.run()
    at.sidebar.radio[0].set_value("Design").run()
    at.button[0].click().run()          # "Build design"
    at.sidebar.radio[0].set_value("Run").run()
    at.button[0].click().run()          # "Run simulation"
    at.sidebar.radio[0].set_value("Reports").run()
    assert not at.exception
    assert any("# Test Plan" in m.value for m in at.markdown)


def test_reports_page_shows_the_correlation_table_once_both_files_are_uploaded():
    test_result = envelope.run(Design.load(TEST_DESIGN))
    site_result = envelope.run(Design.load(SITE_DESIGN))

    at = AppTest.from_file("../app/streamlit_app.py")
    at.run()
    at.sidebar.radio[0].set_value("Reports").run()
    at.file_uploader[0].set_value(
        ("test.json", test_result.model_dump_json().encode(), "application/json")).run()
    at.file_uploader[1].set_value(
        ("site.json", site_result.model_dump_json().encode(), "application/json")).run()
    assert not at.exception
    assert any("# Correlation" in m.value for m in at.markdown)
    assert any("solit2-test-protocol" in m.value for m in at.markdown)
    assert any("road-tunnel-twin-bore" in m.value for m in at.markdown)

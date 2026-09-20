def test_summary_card_shows_live_hydraulics_before_building(run_view):
    at = run_view("design", seed_design=False)
    assert not at.exception
    labels = [m.label for m in at.metric]
    assert labels[:3] == ["Active heads", "Per head", "Zone flow"]
    assert "L/min" in at.metric[2].value and "m³" in at.metric[4].value


def test_build_and_continue_sets_the_design_and_advances(run_view):
    at = run_view("design", seed_design=False)
    assert "design" not in at.session_state
    at.button(key="build_design").click().run()
    assert not at.exception
    assert at.session_state["design"].meta.name == "streamlit-design"
    assert at.session_state["step"] == 2


def test_design_step_has_no_download_or_upload(run_view):
    at = run_view("design", seed_design=False)
    assert not at.get("download_button") and not at.get("file_uploader")


def test_changing_pressure_changes_the_summary(run_view):
    at = run_view("design", seed_design=False)
    before = at.metric[1].value
    at.number_input(key="d_pressure").set_value(100.0).run()
    assert at.metric[1].value != before

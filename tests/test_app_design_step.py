import json
from app.views import design as design_view
from solit2.engines.reduced import envelope


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


def test_acceptance_limits_start_empty_and_stay_unset(run_view):
    """This tool never supplies a limit nobody set: an empty field is not a zero."""
    at = run_view("design", seed_design=False)
    for _field, key, *_rest in design_view.AHJ_FIELDS:
        assert at.number_input(key=key).value is None, key
    at.button(key="build_design").click().run()
    ahj = at.session_state["design"].ahj
    assert ahj.max_air_temp_c is None and ahj.max_co_ppm is None
    assert ahj.tvs_design_fire_mw is None


def test_a_limit_the_authority_sets_is_carried_into_the_design_and_judged(run_view):
    """A set limit has to reach the engine, or entering it would be theatre."""
    at = run_view("design", seed_design=False)
    at.number_input(key="ahj_air_temp").set_value(1.0).run()
    at.button(key="build_design").click().run()

    design = at.session_state["design"]
    assert design.ahj.max_air_temp_c == 1.0
    result = envelope.run(design)
    assert "max_air_temp_c" in result.score["gates_failed"]
    assert "max_air_temp_c" not in result.score["criteria_unset"]


def test_prefill_takes_a_files_limits_and_invents_none_of_the_others(run_view, monkeypatch,
                                                                     tmp_path):
    """A design file's own `ahj` block seeds the fields; a null it leaves stays empty.

    This is the sanctioned way to carry real project limits: they live in the user's
    `designs/` space with their provenance, not as defaults baked into the tool.
    """
    (tmp_path / "site.json").write_text(json.dumps({
        "ahj": {"tvs_design_fire_mw": 50.0, "max_air_temp_c": None,
                "note": "Section 6 of the tender requires 150 MW reduced to <= 50 MW."}}))
    monkeypatch.setattr(design_view, "DESIGNS_DIR", tmp_path)

    at = run_view("design", seed_design=False)
    at.selectbox(key="ahj_source").set_value("site.json").run()

    assert not at.exception
    assert at.number_input(key="ahj_tvs").value == 50.0
    assert at.number_input(key="ahj_air_temp").value is None
    assert any("site.json" in c.value for c in at.caption)
    assert any("tender" in c.value for c in at.caption), "the file's provenance note must show"

    at.button(key="build_design").click().run()
    ahj = at.session_state["design"].ahj
    assert ahj.tvs_design_fire_mw == 50.0 and ahj.max_air_temp_c is None

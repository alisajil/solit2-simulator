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


def test_a_design_file_seeds_every_field_and_invents_no_limit(run_view, monkeypatch, tmp_path):
    """Selecting a file starts the whole form from it — presets, parameters and limits.

    The limits are the careful part: a limit the file declares is carried, and one it
    leaves null stays empty. Real project values live in the user's `designs/` space
    with their provenance, never as defaults baked into the tool.
    """
    (tmp_path / "site.json").write_text(json.dumps({
        "tunnel": {"preset": "template"},
        "nozzles": {"k_factor_lpm_bar05": 6.5, "pressure_bar": 80.0,
                    "mounting": {"rows": 3, "pitch_m": 1.5}},
        "zones": {"section_length_m": 42.0, "sections_simultaneous": 2},
        "ventilation": {"velocity_range_ms": [2.5, 4.0]},
        "ahj": {"tvs_design_fire_mw": 50.0, "max_air_temp_c": None,
                "note": "Section 6 of the tender requires 150 MW reduced to <= 50 MW."}}))
    monkeypatch.setattr(design_view, "DESIGNS_DIR", tmp_path)

    at = run_view("design", seed_design=False)
    at.selectbox(key="design_source").set_value("site.json").run()
    assert not at.exception

    assert at.number_input(key="d_k").value == 6.5
    assert at.number_input(key="d_pressure").value == 80.0
    assert at.number_input(key="d_rows").value == 3
    assert at.number_input(key="d_pitch").value == 1.5
    assert at.number_input(key="d_section_len").value == 42.0
    assert at.number_input(key="d_sections").value == 2
    assert at.number_input(key="d_v_lo").value == 2.5
    assert at.number_input(key="d_v_hi").value == 4.0
    assert at.selectbox(key="d_tunnel").value == "template"

    assert at.number_input(key="ahj_tvs").value == 50.0
    assert at.number_input(key="ahj_air_temp").value is None
    assert any("site.json" in c.value for c in at.caption)
    assert any("tender" in c.value for c in at.caption), "the file's provenance note must show"

    at.button(key="build_design").click().run()
    design = at.session_state["design"]
    assert design.ahj.tvs_design_fire_mw == 50.0 and design.ahj.max_air_temp_c is None
    assert design.nozzles.pressure_bar == 80.0
    assert design.zones.section_length_m == 42.0


def test_a_value_outside_the_form_range_is_clamped_not_crashed(run_view, monkeypatch, tmp_path):
    """A file may predate a bound this form imposes; loading it must not blow up."""
    (tmp_path / "wide.json").write_text(json.dumps(
        {"nozzles": {"pressure_bar": 999.0}, "zones": {"sections_simultaneous": 99}}))
    monkeypatch.setattr(design_view, "DESIGNS_DIR", tmp_path)

    at = run_view("design", seed_design=False)
    at.selectbox(key="design_source").set_value("wide.json").run()

    assert not at.exception
    assert at.number_input(key="d_pressure").value == 140.0
    assert at.number_input(key="d_sections").value == 6

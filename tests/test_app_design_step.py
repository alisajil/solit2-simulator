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


def test_the_file_list_excludes_the_compliance_spec_and_the_project_rules_file(run_view):
    """designs/ holds the project's real design files alongside its compliance
    spec and its project-rules file (I5); only the designs belong in this
    picker, or choosing one of the other two would build a `Design` out of
    the wrong JSON shape."""
    at = run_view("design", seed_design=False)
    options = at.selectbox(key="design_source").options
    assert "og-test-spec.json" not in options
    assert "og-tender-r2.rules.json" not in options
    assert "og-dbr-rev0.json" in options


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


def test_a_file_overwrites_stale_widget_state_rather_than_clearing_the_key(monkeypatch):
    """The fields are assigned, not released — and this is the one guard on that.

    Deleting a widget's key does not reset it once the widget has rendered in a live
    browser: with a file declaring 40 bar selected, a pressure field that had already
    drawn its 50 bar default went on showing 50, so the form silently disagreed with
    the file it said it was showing. `AppTest` does not reproduce that (a rendered
    AppTest widget *does* re-read `value=` after its key is popped), so a view-level
    test cannot catch it. This pins the mechanism instead: whatever is already in
    widget state is overwritten, so the browser has nothing stale left to show.
    """
    stale = {"d_pressure": 50.0, "d_k": 7.7, "d_tunnel": "template",
             "d_v_lo": 9.9, "d_v_hi": 9.9,
             "ahj_tvs": 999.0, "ahj_air_temp": 123.0}
    monkeypatch.setattr(design_view.st, "session_state", stale)

    design_view._apply_to_widgets({
        "nozzles": {"pressure_bar": 40.0},
        "ventilation": {"velocity_range_ms": [2.0, 3.0]},
        "ahj": {"tvs_design_fire_mw": 50.0},
    })

    assert stale["d_pressure"] == 40.0, "a declared value must replace what was on screen"
    assert stale["d_v_lo"] == 2.0 and stale["d_v_hi"] == 3.0
    assert stale["ahj_tvs"] == 50.0, "a declared limit must be carried"
    assert stale["ahj_air_temp"] is None, "a limit this file omits must be cleared, not kept"
    # Fields this file is silent on return to the form's default, not the last file's value.
    assert stale["d_k"] == 4.1
    assert stale["d_tunnel"] == "twin_bore_11m"


def test_every_seeded_widget_is_written_so_none_can_go_stale(monkeypatch):
    """A field added to the form but forgotten here would keep the previous file's value."""
    written: dict = {}
    monkeypatch.setattr(design_view.st, "session_state", written)
    design_view._apply_to_widgets({})

    expected = {key for key, *_rest in design_view.SEEDED_FIELDS}
    expected |= {key for _field, key, *_rest in design_view.AHJ_FIELDS}
    assert set(written) == expected


def test_a_design_seeded_from_a_file_keeps_that_file_s_name():
    """The name is half of what identifies a result. It used to be
    "streamlit-design" whatever the design was seeded from, so the same design
    assessed from the app and from the CLI produced different names AND
    different shas -- the sha is taken over the whole design, name included --
    and landed in different run directories with no way to tell they were the
    same design."""
    from app.views.design import design_identity
    assert design_identity({})["name"] == "streamlit-design", "nothing to take a name from"
    seeded = design_identity({"meta": {"name": "og-dbr-rev0", "notes": "the baseline"}})
    assert seeded["name"] == "og-dbr-rev0"
    assert "the baseline" in seeded["notes"], "the file's own notes travel with it"
    assert "edited afterwards" in seeded["notes"], "and the caveat that they may not match"


def test_the_app_and_the_cli_identify_an_unedited_design_identically():
    """The whole point: assess the same file both ways and the results must be
    recognisably the same design."""
    import json
    from pathlib import Path

    from app.views.design import design_identity
    from solit2.engines.fds import deck
    from solit2.schema.design import Design

    raw = json.loads(Path("designs/og-dbr-rev0.json").read_text())
    from_cli = Design.from_dict(raw)
    as_app_would = Design.from_dict({**raw, "meta": design_identity(raw)})
    assert as_app_would.meta.name == from_cli.meta.name
    # the notes differ by design, so the shas differ; the NAME is what a reader
    # matches on, and it no longer says something unrelated to the file
    assert deck.chid(as_app_would) != "" and from_cli.meta.name == "og-dbr-rev0"


def test_a_design_loaded_from_a_file_is_not_quietly_rebuilt_from_presets():
    """`_assemble` used to compose a design from the four presets plus twelve
    form fields, whatever the source file said. Everything the form does not
    expose was replaced: drop size, cone angle and launch velocity came from
    the nozzle preset, and row offsets, detection, activation delay and
    discharge duration were hardcoded.

    A user who loads their own design file and presses Build is told "every
    field below starts from" that file. They must not then be assessing a
    different system. Anything the form cannot edit has to survive."""
    from pathlib import Path
    from solit2.schema.design import Design

    path = Path("designs/og-ds01-rev00-cd-meas.json")
    if not path.is_file():
        import pytest
        pytest.skip("needs a project design file carrying real nozzle data")
    raw_source = json.loads(path.read_text())
    n = raw_source["nozzles"]
    # pitch and some other fields live in the preset, not the file, so read the
    # form's starting values off the RESOLVED design, exactly as the form does.
    resolved = Design.from_dict(raw_source)
    built = design_view._assemble(
        raw_source["tunnel"]["preset"], raw_source["fire"]["preset"],
        n["preset"], raw_source["hydraulics"]["preset"],
        n["k_factor_lpm_bar05"], n["pressure_bar"],
        resolved.nozzles.mounting.rows, resolved.nozzles.mounting.pitch_m,
        raw_source["zones"]["section_length_m"], raw_source["zones"]["sections_simultaneous"],
        raw_source["ventilation"]["velocity_range_ms"][0],
        raw_source["ventilation"]["velocity_range_ms"][1],
        raw_source.get("ahj") or {}, raw_source)

    from_file, from_form = Design.from_dict(raw_source), Design.from_dict(built)
    mode_of = lambda d: d.nozzles.modes[0]
    assert mode_of(from_form).smd_um == mode_of(from_file).smd_um, "drop size was dropped"
    assert mode_of(from_form).launch_velocity_ms == mode_of(from_file).launch_velocity_ms
    assert mode_of(from_form).cone_half_angle_deg == mode_of(from_file).cone_half_angle_deg
    assert (from_form.nozzles.mounting.row_lateral_offsets_m
            == from_file.nozzles.mounting.row_lateral_offsets_m), "offsets were hardcoded"
    assert (from_form.nozzles.mounting.height_above_carriageway_m
            == from_file.nozzles.mounting.height_above_carriageway_m)
    assert from_form.zones.activation_delay_s == from_file.zones.activation_delay_s
    assert from_form.zones.duration_min == from_file.zones.duration_min
    assert from_form.detection.threshold_c == from_file.detection.threshold_c
    assert from_form.zones.manual_activation_s == from_file.zones.manual_activation_s, \
        "the form's manual-activation default must not override the file's timetable"


def test_building_without_a_source_file_still_composes_from_the_presets():
    """The from-scratch path is what a user gets with no file chosen, and it
    must keep working."""
    from solit2.schema.design import Design
    raw = design_view._assemble("twin_bore_11m", "hgv_150mw", "single_mode_fine_example",
                                "example", 4.1, 50.0, 2, 2.4, 30.0, 3, 3.88, 5.08, {}, None)
    built = Design.from_dict(raw)
    assert built.meta.name == "streamlit-design"
    assert built.nozzles.mounting.rows == 2

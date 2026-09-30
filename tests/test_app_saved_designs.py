"""The Design step saves designs against the signed-in user and loads them back."""
import json
from pathlib import Path

from app import auth
from app.designs import service
from app.designs import store as designs_store
from app.designs.service import Requester
from tests.conftest import EXAMPLE_DESIGN, fill_nozzle, make_account


def _save_example_as(user_id: int, name: str) -> service.SavedVersion:
    raw = json.loads(Path(EXAMPLE_DESIGN).read_text())
    return service.save_new(designs_store.db_path(), Requester(user_id, "team"), name, raw)


def _options(at) -> list[str]:
    return list(at.selectbox(key="design_source").options)


def test_a_saved_design_is_offered_in_the_picker_with_its_id_version_and_owner(run_view):
    other = make_account(email="owner@example.test")
    _save_example_as(other.id, "Orange Gate")
    at = run_view("design", seed_design=False)
    assert not at.exception
    assert "Saved · Orange Gate · #1 v1 · owner@example.test" in _options(at)


def test_choosing_a_saved_design_seeds_the_form_from_it(run_view):
    raw = json.loads(Path(EXAMPLE_DESIGN).read_text())
    raw["zones"]["section_length_m"] = 44.0
    service.save_new(designs_store.db_path(), Requester(make_account().id, "team"), "wide", raw)
    at = run_view("design", seed_design=False)
    label = next(o for o in _options(at) if o.startswith("Saved · wide"))
    at.selectbox(key="design_source").select(label).run()
    assert not at.exception
    assert at.number_input(key="d_section_len").value == 44.0
    assert at.selectbox(key="design_version_1").value == 1


def test_a_saved_designs_meta_is_kept_exactly_as_saved(run_view):
    """design_identity appends a 'Seeded from' note; on a saved design that would change
    the SHA on every load, so an unedited design could never read as unchanged."""
    from app.views import design as design_view
    saved = {"meta": {"name": "kept", "notes": "as saved"}}
    raw = design_view._assemble("twin_bore_11m", "hgv_150mw", "example", None,
                                30.0, 3, 3.88, 5.08, {}, saved, keep_meta=True)
    assert raw["meta"] == {"name": "kept", "notes": "as saved"}


def _built(run_view):
    at = fill_nozzle(run_view("design", seed_design=False))
    at.text_input(key="save_name").set_value("my design").run()
    return at


def test_saving_a_new_design_makes_version_one_and_points_the_picker_at_it(run_view):
    at = _built(run_view)
    at.button(key="save_new_design").click().run()
    assert not at.exception
    assert any(s.value.startswith("Saved #1 v1 · sha ") for s in at.success)
    assert at.selectbox(key="design_source").value.startswith("Saved · my design · #1 v1")
    user_id = at.session_state[auth.USER_ID_KEY]
    rows = service.list_visible(designs_store.db_path(), Requester(user_id, "team"))
    assert [(r.id, r.latest_version, r.owner_id) for r in rows] == [(1, 1, user_id)]


def test_an_edit_saved_again_is_the_next_version_and_no_edit_is_refused(run_view):
    at = _built(run_view)
    at.button(key="save_new_design").click().run()
    at.button(key="save_new_version").click().run()
    assert any("No changes since v1" in e.value for e in at.error)
    at.number_input(key="d_section_len").set_value(40.0).run()
    at.button(key="save_new_version").click().run()
    assert not at.exception
    assert any(s.value.startswith("Saved #1 v2") for s in at.success)


def test_saving_is_disabled_until_the_nozzle_is_entered(run_view):
    at = run_view("design", seed_design=False)
    assert at.button(key="save_new_design").disabled
    assert not at.get("download_button")


def test_a_complete_design_can_be_downloaded(run_view):
    at = _built(run_view)
    assert at.get("download_button")


def test_someone_elses_design_can_only_be_saved_as_a_new_one(run_view):
    other = make_account(email="owner@example.test")
    _save_example_as(other.id, "theirs")
    at = run_view("design", seed_design=False)
    label = next(o for o in _options(at) if o.startswith("Saved · theirs"))
    at.selectbox(key="design_source").select(label).run()
    keys = [b.key for b in at.button]
    assert "save_new_design" in keys and "save_new_version" not in keys

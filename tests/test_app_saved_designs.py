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

"""Who may list, load and version a saved design, and what a save must be."""
import json
from pathlib import Path

import pytest

from app.designs import service
from app.designs.service import Requester
from solit2.engines.reduced import envelope
from solit2.schema.design import Design

EXAMPLE = Path("examples/designs/road-tunnel-twin-bore.json")
ALICE = Requester(user_id=1, role="team")
BOB = Requester(user_id=2, role="team")
CAROL = Requester(user_id=3, role="customer")
ADMIN = Requester(user_id=4, role="admin")


@pytest.fixture
def db(tmp_path):
    return tmp_path / "designs.db"


def _payload(section_length_m: float = 30.0) -> dict:
    raw = json.loads(EXAMPLE.read_text())
    raw["zones"]["section_length_m"] = section_length_m
    return raw


def test_a_new_design_is_version_one_under_its_given_name(db):
    saved = service.save_new(db, ALICE, "  Orange   Gate  ", _payload())
    assert (saved.design_id, saved.version, saved.name) == (1, 1, "Orange Gate")
    assert saved.payload["meta"]["name"] == "Orange Gate"
    expected = _payload()
    expected["meta"]["name"] = "Orange Gate"
    assert saved.payload == expected


def test_saving_again_adds_a_version_and_keeps_the_old_one(db):
    first = service.save_new(db, ALICE, "og", _payload(30.0))
    second = service.save_version(db, ALICE, first.design_id, "og", _payload(40.0))
    assert second.version == 2
    assert service.load(db, ALICE, first.design_id, 1).payload["zones"]["section_length_m"] == 30.0
    assert service.load(db, ALICE, first.design_id).payload["zones"]["section_length_m"] == 40.0


def test_an_identical_save_is_refused(db):
    first = service.save_new(db, ALICE, "og", _payload())
    with pytest.raises(service.NoChanges, match="since v1"):
        service.save_version(db, ALICE, first.design_id, "og", _payload())


def test_only_the_owner_may_add_a_version(db):
    first = service.save_new(db, ALICE, "og", _payload())
    with pytest.raises(service.NotAllowed):
        service.save_version(db, BOB, first.design_id, "og", _payload(40.0))


def test_team_and_admin_see_every_design_and_a_customer_only_its_own(db):
    a = service.save_new(db, ALICE, "alice's", _payload())
    c = service.save_new(db, CAROL, "carol's", _payload())
    assert {r.id for r in service.list_visible(db, BOB)} == {a.design_id, c.design_id}
    assert {r.id for r in service.list_visible(db, ADMIN)} == {a.design_id, c.design_id}
    assert [r.id for r in service.list_visible(db, CAROL)] == [c.design_id]


def test_a_customer_cannot_load_someone_elses_design(db):
    a = service.save_new(db, ALICE, "alice's", _payload())
    with pytest.raises(service.NotAllowed):
        service.load(db, CAROL, a.design_id)


def test_an_unknown_design_or_version_is_not_found(db):
    a = service.save_new(db, ALICE, "og", _payload())
    with pytest.raises(service.DesignNotFound):
        service.load(db, ALICE, a.design_id + 1)
    with pytest.raises(service.DesignNotFound):
        service.load(db, ALICE, a.design_id, 2)


def test_the_saved_sha_is_the_one_its_results_carry(db):
    saved = service.save_new(db, ALICE, "og", _payload())
    result = envelope.run(Design.from_dict(saved.payload))
    assert saved.sha == result.meta["design_sha"]


def test_an_invalid_design_is_refused_with_the_schemas_reason(db):
    with pytest.raises(service.InvalidDesign, match="Not a valid design"):
        service.save_new(db, ALICE, "og", {**_payload(), "bogus_block": 1})


def test_a_design_needs_a_name(db):
    with pytest.raises(service.InvalidDesign, match="name"):
        service.save_new(db, ALICE, "   ", _payload())
    with pytest.raises(service.InvalidDesign, match=str(service.NAME_MAX_CHARS)):
        service.save_new(db, ALICE, "x" * (service.NAME_MAX_CHARS + 1), _payload())

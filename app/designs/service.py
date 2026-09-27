"""The saved-design rules: who may list, load and version a design, and what a save must be.

Every function opens one short connection and does its whole job in that one transaction.
What a person can fix raises a DesignError, whose message is written for them and safe to
show. Nothing here imports Streamlit, and nothing here reads the account store: the caller
says who is asking, by user ID and role.
"""
from __future__ import annotations

import copy
import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from app.designs import store
from app.designs.store import DesignRow
from solit2.engines.reduced.envelope import design_sha
from solit2.schema.design import Design

NAME_MAX_CHARS = 100
# The roles that share the project workspace, and so see every saved design.
SHARED_ROLES = frozenset({"admin", "team"})


class DesignError(ValueError):
    """A request the saved-design rules refuse. The message is written for the person."""


class NotAllowed(DesignError):
    pass


class NoChanges(DesignError):
    pass


class InvalidDesign(DesignError):
    pass


class DesignNotFound(DesignError):
    pass


@dataclass(frozen=True)
class Requester:
    user_id: int
    role: str | None


@dataclass(frozen=True)
class SavedVersion:
    design_id: int
    version: int
    name: str
    payload: dict
    sha: str
    saved_by: int
    saved_at: datetime


def _now(now: datetime | None) -> datetime:
    return datetime.now(UTC) if now is None else now.astimezone(UTC)


def _checked_name(raw: str) -> str:
    name = " ".join(raw.split())
    if not name:
        raise InvalidDesign("Give the design a name.")
    if len(name) > NAME_MAX_CHARS:
        raise InvalidDesign(f"Keep the design's name to {NAME_MAX_CHARS} characters.")
    return name


def _named(payload: dict, name: str) -> tuple[dict, str]:
    """The payload carrying `name` as its `meta.name`, and that design's SHA."""
    named = copy.deepcopy(payload)
    named["meta"] = {**(named.get("meta") or {}), "name": name}
    try:
        design = Design.from_dict(named)
    except Exception as exc:  # noqa: BLE001 -- the schema's own reason, shown to the person
        raise InvalidDesign(f"Not a valid design: {exc}") from exc
    return named, design_sha(design)


def _may_see(who: Requester, row: DesignRow) -> bool:
    return who.role in SHARED_ROLES or row.owner_id == who.user_id


def _stored(named: dict) -> str:
    return json.dumps(named, sort_keys=True)


def save_new(db: Path, who: Requester, name: str, payload: dict, *,
             now: datetime | None = None) -> SavedVersion:
    """A new design owned by `who`, as its version 1."""
    name = _checked_name(name)
    named, sha = _named(payload, name)
    at = _now(now)
    store.init(db)
    with store.connect(db) as conn:
        design_id = store.insert_design(conn, owner_id=who.user_id, name=name, now=at)
        store.insert_version(conn, design_id=design_id, version=1, payload=_stored(named),
                             sha=sha, saved_by=who.user_id, now=at)
    return SavedVersion(design_id, 1, name, named, sha, who.user_id, at)


def save_version(db: Path, who: Requester, design_id: int, name: str, payload: dict, *,
                 now: datetime | None = None) -> SavedVersion:
    """The next version of `design_id`. Only its owner may add one, and only a changed one."""
    name = _checked_name(name)
    named, sha = _named(payload, name)
    at = _now(now)
    store.init(db)
    with store.connect(db) as conn:
        store.begin_write(conn)
        row = store.design_by_id(conn, design_id)
        if row is None:
            raise DesignNotFound(f"There is no saved design #{design_id}.")
        if row.owner_id != who.user_id:
            raise NotAllowed(f"Only the owner of #{design_id} can save a new version of it; "
                             "save your own copy as a new design instead.")
        if row.latest_sha == sha:
            raise NoChanges(f"No changes since v{row.latest_version} of #{design_id}.")
        version = row.latest_version + 1
        store.insert_version(conn, design_id=design_id, version=version,
                             payload=_stored(named), sha=sha, saved_by=who.user_id, now=at)
        store.rename_design(conn, design_id, name)
    return SavedVersion(design_id, version, name, named, sha, who.user_id, at)


def list_visible(db: Path, who: Requester) -> list[DesignRow]:
    """The designs `who` may see, most recently saved first."""
    store.init(db)
    with store.connect(db) as conn:
        return store.list_designs(conn, None if who.role in SHARED_ROLES else who.user_id)


def load(db: Path, who: Requester, design_id: int, version: int | None = None) -> SavedVersion:
    """One version of a design `who` may see; the latest when `version` is None."""
    store.init(db)
    with store.connect(db) as conn:
        row = store.design_by_id(conn, design_id)
        if row is None:
            raise DesignNotFound(f"There is no saved design #{design_id}.")
        if not _may_see(who, row):
            raise NotAllowed(f"Saved design #{design_id} is not yours to open.")
        wanted = row.latest_version if version is None else version
        found = store.version_row(conn, design_id, wanted)
    if found is None:
        raise DesignNotFound(f"Saved design #{design_id} has no v{wanted}.")
    payload = json.loads(found.payload)
    return SavedVersion(design_id, found.version, payload["meta"]["name"], payload,
                        found.sha, found.saved_by, found.saved_at)

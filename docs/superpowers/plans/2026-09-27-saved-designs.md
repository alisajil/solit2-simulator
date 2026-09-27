# Saved Designs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Team and admin users can save a design built in the Design step against their user ID. Each
design has a design ID and append-only versions, can be loaded back from the picker, and can be downloaded
as JSON.

**Architecture:** A new `app/designs/` package mirrors `app/accounts/`. `store.py` holds the plain SQL on
`$SOLIT2_DATA_DIR/designs.db`; `service.py` holds the rules, takes the requester as a user ID plus role, and
never imports Streamlit. A new component, `app/components/save_design.py`, adds the saved entries to the
Design step's picker and draws the save panel. `app/views/design.py` only wires it in. A saved version's
SHA is `envelope.design_sha`, made public, so it equals the `meta.design_sha` of any result run on it.

**Tech Stack:** Python 3.12, standard-library `sqlite3`, Streamlit 1.64 (AppTest for the screen tests),
pytest, the project's `Design` schema.

**Spec:** `docs/superpowers/specs/2026-09-27-saved-designs-design.md`

## Global Constraints

- Storage is local SQLite only: `$SOLIT2_DATA_DIR/designs.db`, default `data/designs.db` (git-ignored). The file is mode `0600`; a directory it creates is `0700`; WAL mode.
- The store is separate from `accounts.db`, has its own `PRAGMA user_version`, and refuses a store newer than it knows.
- Versions are append-only. Nothing updates or deletes a `design_versions` row.
- Every save is validated with `Design.from_dict`, the same check as **Build & continue**. There are no incomplete drafts.
- Visibility: roles `admin` and `team` see every saved design; any other role sees only its own. Only the owner may add a version.
- Customers stay locked out of the screens (`app/state.py` `ROLE_VIEWS` is unchanged).
- No Streamlit import in `app/designs/`.
- Commit messages end with `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Run tests with `uv run pytest -q -p no:cacheprovider <paths>`. The project config suppresses the summary line, so read the exit code.

## File Structure

| File | Responsibility |
|---|---|
| `solit2/engines/reduced/envelope.py` (modify) | `_design_sha` becomes public `design_sha` |
| `solit2/cli.py`, `solit2/engines/fds/deck.py`, 5 test files (modify) | follow the rename |
| `app/designs/__init__.py` (create) | package marker |
| `app/designs/store.py` (create) | schema, `init`, plain SQL reads and writes |
| `app/designs/service.py` (create) | errors, `Requester`, `save_new`, `save_version`, `list_visible`, `load` |
| `app/components/save_design.py` (create) | picker entries, version box, save panel, download |
| `app/views/design.py` (modify) | wire the component in; keep a saved design's `meta` as saved |
| `tests/test_design_sha.py` (create) | the public SHA is the result's |
| `tests/test_designs_store.py` (create) | store behaviour |
| `tests/test_designs_service.py` (create) | rules |
| `tests/test_app_saved_designs.py` (create) | the screen, via AppTest |
| `docs/superpowers/specs/2026-09-26-accounts-design.md` (modify) | Phase 2 points at the saved-designs spec for designs |

---

### Task 1: Make the design SHA public

**Files:**
- Modify: `solit2/engines/reduced/envelope.py:174` (and its use at `:317`)
- Modify: `solit2/cli.py:176-177`, `solit2/engines/fds/deck.py:27,175`
- Modify: `tests/test_fds_deck.py`, `tests/test_fds_reader.py`, `tests/test_app_cfd_step.py`, `tests/test_cli.py`
- Test: `tests/test_design_sha.py` (create)

**Interfaces:**
- Produces: `solit2.engines.reduced.envelope.design_sha(design: Design) -> str` (12 hex chars, unchanged algorithm)

- [ ] **Step 1: Write the failing test**

```python
"""The design SHA a saved design records is the one its results carry."""
from solit2.engines.reduced import envelope
from solit2.schema.design import Design

EXAMPLE = "examples/designs/road-tunnel-twin-bore.json"


def test_the_design_sha_is_public_and_is_what_a_result_carries():
    design = Design.load(EXAMPLE)
    assert envelope.run(design).meta["design_sha"] == envelope.design_sha(design)
```

- [ ] **Step 2: Run it to verify it fails**

Run: `uv run pytest -q -p no:cacheprovider tests/test_design_sha.py`
Expected: FAIL with `AttributeError: module 'solit2.engines.reduced.envelope' has no attribute 'design_sha'`

- [ ] **Step 3: Rename everywhere**

```bash
grep -rl "_design_sha" solit2 tests | xargs sed -i '' 's/\b_design_sha\b/design_sha/g'
grep -rn "_design_sha" solit2 tests   # expect no output
```

The definition in `envelope.py` now reads:

```python
def design_sha(design: Design) -> str:
    payload = json.dumps(design.model_dump(mode="json"), sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()[:DESIGN_SHA_CHARS]
```

- [ ] **Step 4: Run the test and the renamed callers' tests**

Run: `uv run pytest -q -p no:cacheprovider tests/test_design_sha.py tests/test_fds_deck.py tests/test_fds_reader.py tests/test_app_cfd_step.py tests/test_cli.py; echo EXIT=$?`
Expected: `EXIT=0`

- [ ] **Step 5: Commit**

```bash
git add -A solit2 tests
git commit -m "refactor(envelope): make the design SHA public for the saved-design store

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 2: The saved-design store

**Files:**
- Create: `app/designs/__init__.py`, `app/designs/store.py`
- Test: `tests/test_designs_store.py`

**Interfaces:**
- Consumes: `app.accounts.store.connect`, `DATA_DIR_ENV`, `DEFAULT_DATA_DIR`, `DIR_MODE`, `FILE_MODE`
- Produces:
  - `db_path() -> Path`
  - `init(db: Path) -> None`
  - `connect` (re-exported)
  - `begin_write(conn) -> None`
  - `insert_design(conn, *, owner_id: int, name: str, now: datetime) -> int`
  - `insert_version(conn, *, design_id: int, version: int, payload: str, sha: str, saved_by: int, now: datetime) -> None`
  - `rename_design(conn, design_id: int, name: str) -> None`
  - `design_by_id(conn, design_id: int) -> DesignRow | None`
  - `list_designs(conn, owner_id: int | None = None) -> list[DesignRow]`
  - `version_row(conn, design_id: int, version: int) -> VersionRow | None`
  - `DesignRow(id, owner_id, name, created_at, latest_version, latest_sha, updated_at)`
  - `VersionRow(design_id, version, payload, sha, saved_by, saved_at)`

- [ ] **Step 1: Write the failing tests**

`tests/test_designs_store.py`:

```python
"""The saved-design store: its file, its schema version, and its plain SQL."""
import os
import sqlite3
from datetime import UTC, datetime, timedelta

import pytest

from app.designs import store

T0 = datetime(2026, 9, 27, 9, 0, tzinfo=UTC)


def _db(tmp_path):
    db = tmp_path / "fresh" / store.DB_NAME
    store.init(db)
    return db


def test_the_store_is_owner_only(tmp_path):
    db = _db(tmp_path)
    assert os.stat(db).st_mode & 0o777 == 0o600
    assert os.stat(db.parent).st_mode & 0o777 == 0o700


def test_the_store_lives_beside_the_accounts_in_the_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv(store.DATA_DIR_ENV, str(tmp_path))
    assert store.db_path() == tmp_path / "designs.db"


def test_a_store_newer_than_the_code_is_refused(tmp_path):
    db = _db(tmp_path)
    with store.connect(db) as conn:
        conn.execute(f"PRAGMA user_version = {store.SCHEMA_VERSION + 1}")
    with pytest.raises(sqlite3.DatabaseError, match="newer"):
        store.init(db)


def test_a_listing_carries_the_latest_version_newest_first(tmp_path):
    db = _db(tmp_path)
    with store.connect(db) as conn:
        a = store.insert_design(conn, owner_id=1, name="a", now=T0)
        store.insert_version(conn, design_id=a, version=1, payload="{}", sha="aaa1",
                             saved_by=1, now=T0)
        b = store.insert_design(conn, owner_id=2, name="b", now=T0)
        store.insert_version(conn, design_id=b, version=1, payload="{}", sha="bbb1",
                             saved_by=2, now=T0 + timedelta(minutes=1))
        store.insert_version(conn, design_id=a, version=2, payload="{}", sha="aaa2",
                             saved_by=1, now=T0 + timedelta(minutes=2))
        rows = store.list_designs(conn)
        mine = store.list_designs(conn, owner_id=2)
    assert [(r.id, r.latest_version, r.latest_sha) for r in rows] == [(a, 2, "aaa2"),
                                                                       (b, 1, "bbb1")]
    assert [r.id for r in mine] == [b]


def test_a_version_number_cannot_be_written_twice(tmp_path):
    db = _db(tmp_path)
    with store.connect(db) as conn:
        a = store.insert_design(conn, owner_id=1, name="a", now=T0)
        store.insert_version(conn, design_id=a, version=1, payload="{}", sha="x",
                             saved_by=1, now=T0)
    with pytest.raises(sqlite3.IntegrityError), store.connect(db) as conn:
        store.insert_version(conn, design_id=a, version=1, payload="{}", sha="y",
                             saved_by=1, now=T0)


def test_a_version_reads_back_exactly(tmp_path):
    db = _db(tmp_path)
    with store.connect(db) as conn:
        a = store.insert_design(conn, owner_id=1, name="a", now=T0)
        store.insert_version(conn, design_id=a, version=1, payload='{"k": 1}', sha="s",
                             saved_by=1, now=T0)
        row = store.version_row(conn, a, 1)
        missing = store.version_row(conn, a, 2)
    assert (row.payload, row.sha, row.saved_by, row.saved_at) == ('{"k": 1}', "s", 1, T0)
    assert missing is None
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest -q -p no:cacheprovider tests/test_designs_store.py`
Expected: FAIL with `ModuleNotFoundError: No module named 'app.designs'`

- [ ] **Step 3: Write the store**

`app/designs/__init__.py`:

```python
"""Designs saved from the app, per user, with append-only versions."""
```

`app/designs/store.py`:

```python
"""The saved-design store: SQLite from the standard library, one short connection per operation.

The file is $SOLIT2_DATA_DIR/designs.db (default data/designs.db, git-ignored), beside the
account store and kept the same way: owner read/write, in an owner-only directory, WAL
mode. It is a separate file so that it carries its own schema version and never touches
accounts.db.

Plain SQL only: who may see or save what lives in service.py. Versions are append-only --
nothing here updates or deletes a row of design_versions.
"""
from __future__ import annotations

import os
import sqlite3
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from app.accounts.store import DATA_DIR_ENV, DEFAULT_DATA_DIR, DIR_MODE, FILE_MODE, connect

__all__ = ["DATA_DIR_ENV", "DB_NAME", "SCHEMA_VERSION", "DesignRow", "VersionRow", "begin_write",
           "connect", "db_path", "design_by_id", "init", "insert_design", "insert_version",
           "list_designs", "rename_design", "version_row"]

DB_NAME = "designs.db"
SCHEMA_VERSION = 1

_SCHEMA = """
CREATE TABLE IF NOT EXISTS designs (
    id         INTEGER PRIMARY KEY,
    owner_id   INTEGER NOT NULL,   -- accounts users.id; another file, so checked by the service
    name       TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS design_versions (
    design_id INTEGER NOT NULL REFERENCES designs (id),
    version   INTEGER NOT NULL CHECK (version >= 1),
    payload   TEXT NOT NULL,
    sha       TEXT NOT NULL,
    saved_by  INTEGER NOT NULL,
    saved_at  TEXT NOT NULL,
    PRIMARY KEY (design_id, version)
);
"""
# Each design with its latest version, found by version number rather than time, so two
# saves in the same second cannot tie.
_LATEST = (
    "SELECT d.id, d.owner_id, d.name, d.created_at, v.version AS latest_version,"
    " v.sha AS latest_sha, v.saved_at AS updated_at"
    " FROM designs d JOIN design_versions v ON v.design_id = d.id"
    " AND v.version = (SELECT MAX(version) FROM design_versions WHERE design_id = d.id)")


@dataclass(frozen=True)
class DesignRow:
    id: int
    owner_id: int
    name: str
    created_at: datetime
    latest_version: int
    latest_sha: str
    updated_at: datetime


@dataclass(frozen=True)
class VersionRow:
    design_id: int
    version: int
    payload: str
    sha: str
    saved_by: int
    saved_at: datetime


def db_path() -> Path:
    return Path(os.environ.get(DATA_DIR_ENV) or DEFAULT_DATA_DIR) / DB_NAME


def init(db: Path) -> None:
    """Create the store if it is missing -- directory, file, tables -- and keep the file
    owner-only. Cheap and safe to call before every operation.

    A store at a newer schema version than this code knows is refused before anything is
    created in it, rather than being given this version's tables."""
    db.parent.mkdir(parents=True, exist_ok=True, mode=DIR_MODE)
    if not db.exists():
        db.touch(mode=FILE_MODE)
    os.chmod(db, FILE_MODE)
    with connect(db) as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        stored_version = conn.execute("PRAGMA user_version").fetchone()[0]
        if stored_version > SCHEMA_VERSION:
            raise sqlite3.DatabaseError(
                f"the design store is at schema version {stored_version}, newer than "
                f"this code's {SCHEMA_VERSION}; upgrade the app before it opens this store")
        conn.executescript(_SCHEMA)
        if stored_version < SCHEMA_VERSION:
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def begin_write(conn: sqlite3.Connection) -> None:
    """Take the write lock now, so a read-then-write (the next version number) cannot race."""
    conn.execute("BEGIN IMMEDIATE")


def _iso(value: datetime) -> str:
    return value.isoformat(timespec="seconds")


def _design(row: sqlite3.Row) -> DesignRow:
    return DesignRow(id=row["id"], owner_id=row["owner_id"], name=row["name"],
                     created_at=datetime.fromisoformat(row["created_at"]),
                     latest_version=row["latest_version"], latest_sha=row["latest_sha"],
                     updated_at=datetime.fromisoformat(row["updated_at"]))


def insert_design(conn: sqlite3.Connection, *, owner_id: int, name: str, now: datetime) -> int:
    cursor = conn.execute("INSERT INTO designs (owner_id, name, created_at) VALUES (?, ?, ?)",
                          (owner_id, name, _iso(now)))
    return int(cursor.lastrowid)


def insert_version(conn: sqlite3.Connection, *, design_id: int, version: int, payload: str,
                   sha: str, saved_by: int, now: datetime) -> None:
    conn.execute(
        "INSERT INTO design_versions (design_id, version, payload, sha, saved_by, saved_at)"
        " VALUES (?, ?, ?, ?, ?, ?)", (design_id, version, payload, sha, saved_by, _iso(now)))


def rename_design(conn: sqlite3.Connection, design_id: int, name: str) -> None:
    conn.execute("UPDATE designs SET name = ? WHERE id = ?", (name, design_id))


def design_by_id(conn: sqlite3.Connection, design_id: int) -> DesignRow | None:
    row = conn.execute(f"{_LATEST} WHERE d.id = ?", (design_id,)).fetchone()
    return None if row is None else _design(row)


def list_designs(conn: sqlite3.Connection, owner_id: int | None = None) -> list[DesignRow]:
    """Every design, or only `owner_id`'s, most recently saved first."""
    where, params = ("", ()) if owner_id is None else (" WHERE d.owner_id = ?", (owner_id,))
    rows = conn.execute(f"{_LATEST}{where} ORDER BY updated_at DESC, d.id DESC",
                        params).fetchall()
    return [_design(row) for row in rows]


def version_row(conn: sqlite3.Connection, design_id: int, version: int) -> VersionRow | None:
    row = conn.execute(
        "SELECT design_id, version, payload, sha, saved_by, saved_at FROM design_versions"
        " WHERE design_id = ? AND version = ?", (design_id, version)).fetchone()
    if row is None:
        return None
    return VersionRow(design_id=row["design_id"], version=row["version"],
                      payload=row["payload"], sha=row["sha"], saved_by=row["saved_by"],
                      saved_at=datetime.fromisoformat(row["saved_at"]))
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest -q -p no:cacheprovider tests/test_designs_store.py; echo EXIT=$?`
Expected: `EXIT=0`

- [ ] **Step 5: Commit**

```bash
git add app/designs tests/test_designs_store.py
git commit -m "feat(designs): a local SQLite store for saved designs and their versions

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 3: The saved-design rules

**Files:**
- Create: `app/designs/service.py`
- Test: `tests/test_designs_service.py`

**Interfaces:**
- Consumes: Task 1 `design_sha`; Task 2 `store.*`, `DesignRow`
- Produces:
  - Errors: `DesignError(ValueError)` and its subclasses `NotAllowed`, `NoChanges`, `InvalidDesign`, `DesignNotFound`
  - `Requester(user_id: int, role: str | None)`
  - `SavedVersion(design_id, version, name, payload: dict, sha, saved_by, saved_at)`
  - `save_new(db, who, name, payload, *, now=None) -> SavedVersion`
  - `save_version(db, who, design_id, name, payload, *, now=None) -> SavedVersion`
  - `list_visible(db, who) -> list[DesignRow]`
  - `load(db, who, design_id, version=None) -> SavedVersion`
  - Constants: `SHARED_ROLES`, `NAME_MAX_CHARS`

- [ ] **Step 1: Write the failing tests**

`tests/test_designs_service.py`:

```python
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
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest -q -p no:cacheprovider tests/test_designs_service.py`
Expected: FAIL with `ImportError: cannot import name 'service' from 'app.designs'`

- [ ] **Step 3: Write the service**

`app/designs/service.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

Run: `uv run pytest -q -p no:cacheprovider tests/test_designs_service.py tests/test_designs_store.py; echo EXIT=$?`
Expected: `EXIT=0`

- [ ] **Step 5: Commit**

```bash
git add app/designs/service.py tests/test_designs_service.py
git commit -m "feat(designs): rules for saving, versioning, listing and loading saved designs

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 4: Saved designs in the Design step's picker

**Files:**
- Create: `app/components/save_design.py` (picker half)
- Modify: `app/views/design.py`, in `_render_source_picker` (~line 357), `_apply_to_widgets` (~line 326), `_overlay` (~line 454), `_assemble` (~line 490) and `render` (~line 52)
- Test: `tests/test_app_saved_designs.py` (create)

**Interfaces:**
- Consumes: Task 3 `service.*`, `Requester`, `SavedVersion`; `app.auth.current_user`; `app.accounts.service.list_users`, `app.accounts.store.db_path`
- Produces (in `app.components.save_design`):
  - `NAME_KEY = "save_name"`
  - `requester() -> Requester | None`
  - `saved_options() -> dict[str, DesignRow]` (label → row)
  - `pop_pending() -> tuple[int, int] | None`
  - `render_version_picker(row: DesignRow) -> SavedVersion | None`
  - `set_seeded(row: DesignRow | None, version: int | None) -> None`
  - `seeded() -> Seeded | None`
  - `Seeded(design_id, owner_id, latest_version, version)`
  - `label(row, emails) -> str`
- Produces (in `app.views.design`): `_assemble(..., keep_meta: bool = False)`

A saved design's `meta` is kept exactly as saved. `design_identity` appends a "Seeded from…" note whenever it seeds from a source. If that ran on a saved design, every load would change the notes and so the SHA. An unedited design could then never read as "no changes".

- [ ] **Step 1: Write the failing tests**

`tests/test_app_saved_designs.py`:

```python
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
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest -q -p no:cacheprovider tests/test_app_saved_designs.py`
Expected: FAIL. The saved label is missing from the options, and `_assemble` rejects `keep_meta` with `TypeError`.

- [ ] **Step 3: Write the picker half of the component**

`app/components/save_design.py`:

```python
"""Saved designs in the Design step: the picker's saved entries and the save panel.

The rules live in app/designs/service.py. This module only asks them, on behalf of the
signed-in account, and shows what they answer.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import streamlit as st

from app import auth
from app.accounts import service as accounts
from app.accounts import store as accounts_store
from app.designs import service as designs
from app.designs import store as designs_store
from app.designs.service import Requester, SavedVersion
from app.designs.store import DesignRow

NAME_KEY = "save_name"
_SEEDED_KEY = "_saved_seeded"
_PENDING_KEY = "_saved_pending"
_NOTICE_KEY = "_saved_notice"
SAVED_PREFIX = "Saved · "


@dataclass(frozen=True)
class Seeded:
    """The saved design and version the form was seeded from."""
    design_id: int
    owner_id: int
    latest_version: int
    version: int


def requester() -> Requester | None:
    user = auth.current_user(touch=False)
    return None if user is None else Requester(user.id, user.role)


def label(row: DesignRow, emails: dict[int, str]) -> str:
    owner = emails.get(row.owner_id, f"user {row.owner_id}")
    return f"{SAVED_PREFIX}{row.name} · #{row.id} v{row.latest_version} · {owner}"


def saved_options() -> dict[str, DesignRow]:
    """Label -> design, for every saved design the signed-in account may see."""
    who = requester()
    if who is None:
        return {}
    try:
        rows = designs.list_visible(designs_store.db_path(), who)
        emails = {u.id: u.email for u in accounts.list_users(accounts_store.db_path())}
    except sqlite3.Error as exc:
        st.warning(f"Saved designs could not be read: {exc}")
        return {}
    return {label(row, emails): row for row in rows}


def pop_pending() -> tuple[int, int] | None:
    """The (design ID, version) a save just made, for the picker to point at."""
    return st.session_state.pop(_PENDING_KEY, None)


def version_key(design_id: int) -> str:
    return f"design_version_{design_id}"


def render_version_picker(row: DesignRow) -> SavedVersion | None:
    versions = list(range(row.latest_version, 0, -1))
    version = st.selectbox("Version", versions, key=version_key(row.id),
                           format_func=lambda v: f"v{v}" + (" (latest)" if v == versions[0] else ""))
    try:
        return designs.load(designs_store.db_path(), requester(), row.id, version)
    except (designs.DesignError, sqlite3.Error) as exc:
        st.warning(f"That saved design could not be opened: {exc}")
        return None


def set_seeded(row: DesignRow | None, version: int | None) -> None:
    st.session_state[_SEEDED_KEY] = (None if row is None or version is None
                                     else Seeded(row.id, row.owner_id, row.latest_version, version))


def seeded() -> Seeded | None:
    return st.session_state.get(_SEEDED_KEY)
```

- [ ] **Step 4: Wire the picker into the Design view**

In `app/views/design.py`, add the import after `from app.components.design_files import design_files`:

```python
from app.components import save_design
```

Replace `_render_source_picker` with:

```python
def _render_source_picker() -> dict:
    """Start the whole form from a saved design or a design file the user keeps."""
    saved = save_design.saved_options()
    names = _design_files()
    pending = save_design.pop_pending()
    just_saved = None if pending is None else next(
        (text for text, row in saved.items() if row.id == pending[0]), None)
    if just_saved is not None:
        # A save just made this version: point the picker at it before the widgets draw.
        # The form already holds exactly its values, so it is marked applied, not re-seeded.
        design_id, version = pending
        st.session_state["design_source"] = just_saved
        st.session_state[save_design.version_key(design_id)] = version
        st.session_state[_APPLIED_SOURCE] = f"saved:{design_id}:v{version}"
    if not saved and not names:
        save_design.set_seeded(None, None)
        return {}
    chosen = st.selectbox("Start from a saved design or file", [NO_SOURCE, *saved, *names],
                          key="design_source",
                          help="Seeds every field below from it. Edit anything afterwards; "
                               "nothing is written back unless you save.")
    if chosen == NO_SOURCE:
        st.session_state[_APPLIED_SOURCE] = None
        save_design.set_seeded(None, None)
        return {}
    if chosen in saved:
        loaded = save_design.render_version_picker(saved[chosen])
        if loaded is None:
            save_design.set_seeded(None, None)
            return {}
        raw, applied = loaded.payload, f"saved:{loaded.design_id}:v{loaded.version}"
        shown = f"#{loaded.design_id} v{loaded.version} ({loaded.name})"
        save_design.set_seeded(saved[chosen], loaded.version)
    else:
        raw, applied, shown = _read_design(chosen), chosen, chosen
        save_design.set_seeded(None, None)
    # Re-seed on a change of source: Streamlit honours `value=`/`index=` only on a
    # key's first render, so without this the widgets keep the previous source's values.
    if st.session_state.get(_APPLIED_SOURCE) != applied:
        _apply_to_widgets(raw)
        st.session_state[_APPLIED_SOURCE] = applied
    st.caption(f"Every field below starts from **{shown}**. Edit anything for this run.")
    return raw
```

At the end of `_apply_to_widgets`, add:

```python
    # The save panel's name follows the source, like every other field.
    st.session_state[save_design.NAME_KEY] = (raw.get("meta") or {}).get("name", "")
```

Give `_overlay` a `keep_meta` parameter and use it for `meta`:

```python
def _overlay(scratch: dict, raw_source: dict, nozzles: dict | None,
             section_length_m: float, sections_simultaneous: int,
             velocity_lo: float, velocity_hi: float, ahj: dict,
             keep_meta: bool = False) -> dict:
```

```python
    raw["meta"] = dict(raw_source["meta"]) if keep_meta else design_identity(raw_source)
```

Give `_assemble` the keyword `keep_meta: bool = False`, after `pump_ramp_s`, and pass it through. The scratch `meta` becomes:

```python
        "meta": (dict(raw_source["meta"]) if keep_meta and raw_source
                 else design_identity(raw_source or {})),
```

```python
    raw = scratch if not raw_source else _overlay(
        scratch, raw_source, nozzles, section_length_m, sections_simultaneous,
        velocity_lo, velocity_hi, ahj, keep_meta=keep_meta)
```

In `render()`, pass it:

```python
    raw = _assemble(tunnel_preset, fire_preset, hydraulics_preset, nozzles,
                    section_length_m, int(sections_simultaneous), velocity_lo, velocity_hi,
                    ahj, raw_source, pump_ramp_s=pump_ramp_s,
                    keep_meta=save_design.seeded() is not None)
```

- [ ] **Step 5: Run the new tests and the existing Design-step tests**

Run: `uv run pytest -q -p no:cacheprovider tests/test_app_saved_designs.py tests/test_app_design_step.py; echo EXIT=$?`
Expected: `EXIT=0`

- [ ] **Step 6: Commit**

```bash
git add app/components/save_design.py app/views/design.py tests/test_app_saved_designs.py
git commit -m "feat(design): the picker offers saved designs and seeds the form from a version

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

---

### Task 5: The save panel and Download JSON

**Files:**
- Modify: `app/components/save_design.py` (add the panel)
- Modify: `app/views/design.py`, in `render()`, between the missing-data warning and the Build button
- Modify: `docs/superpowers/specs/2026-09-26-accounts-design.md` (Phase 2 paragraph)
- Test: `tests/test_app_saved_designs.py` (append)

**Interfaces:**
- Consumes: Task 4 `requester`, `seeded`, `NAME_KEY`, `_PENDING_KEY`, `_NOTICE_KEY`; Task 3 `save_new`, `save_version`, `DesignError`
- Produces: `save_design.render(raw: dict, missing: list[str]) -> None`; `DURABILITY_NOTE: str`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_app_saved_designs.py`:

```python
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
```

- [ ] **Step 2: Run them to verify they fail**

Run: `uv run pytest -q -p no:cacheprovider tests/test_app_saved_designs.py`
Expected: FAIL with `KeyError` for widget key `save_name` / `save_new_design`

- [ ] **Step 3: Add the panel to the component**

Add to the imports of `app/components/save_design.py`:

```python
import json
import re
from collections.abc import Callable
```

Append:

```python
DURABILITY_NOTE = ("Saved designs are kept on this server. On Streamlit Community Cloud a "
                   "reboot erases them; download a copy to keep one.")


def _file_name(name: str) -> str:
    return (re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "design") + ".json"


def _save(action: Callable[[], SavedVersion]) -> None:
    try:
        saved = action()
    except designs.DesignError as exc:
        st.error(str(exc))
        return
    except sqlite3.Error as exc:
        st.error(f"The design store could not be written: {exc}")
        return
    st.session_state[_NOTICE_KEY] = f"Saved #{saved.design_id} v{saved.version} · sha {saved.sha}"
    st.session_state[_PENDING_KEY] = (saved.design_id, saved.version)
    st.rerun()


def render(raw: dict, missing: list[str]) -> None:
    """Save the design as it stands, as a new design or as the next version of the saved
    design it was seeded from, and offer it as a download."""
    who = requester()
    if who is None:
        return
    st.subheader("Save this design")
    notice = st.session_state.pop(_NOTICE_KEY, None)
    if notice:
        st.success(notice)
    if NAME_KEY not in st.session_state:
        st.session_state[NAME_KEY] = (raw.get("meta") or {}).get("name", "")
    name = st.text_input("Name", key=NAME_KEY)
    blocked = bool(missing)
    if blocked:
        st.caption("Saving needs the nozzle data above: " + ", ".join(missing))
    db = designs_store.db_path()
    source = seeded()
    left, right = st.columns(2)
    if source is not None and source.owner_id == who.user_id:
        if left.button(f"Save as v{source.latest_version + 1} of #{source.design_id}",
                       key="save_new_version", disabled=blocked):
            _save(lambda: designs.save_version(db, who, source.design_id, name, raw))
    if right.button("Save as new design", key="save_new_design", disabled=blocked):
        _save(lambda: designs.save_new(db, who, name, raw))
    if not blocked:
        named = {**raw, "meta": {**(raw.get("meta") or {}), "name": name}}
        st.download_button("Download JSON", data=json.dumps(named, indent=2),
                           file_name=_file_name(name), mime="application/json",
                           key="download_design")
    st.caption(DURABILITY_NOTE)
```

- [ ] **Step 4: Call it from the Design view**

In `app/views/design.py` `render()`, directly after

```python
    if missing:
        st.warning("Nozzle data still needed: " + ", ".join(missing))
```

add:

```python
    save_design.render(raw, missing)
```

- [ ] **Step 5: Point the accounts spec's Phase 2 at the saved-designs spec**

In `docs/superpowers/specs/2026-09-26-accounts-design.md`, change the sentence that begins "A customer brings designs in by **saving** one built in the app" to:

```markdown
A customer brings designs in by **saving** one built in the app, into the saved-design store
(`2026-09-27-saved-designs-design.md`), which already keeps designs per owner with versions, or by
**uploading** a design JSON, validated with the schema before it is stored.
```

- [ ] **Step 6: Run the screen tests, then the whole suite**

Run: `uv run pytest -q -p no:cacheprovider tests/test_app_saved_designs.py tests/test_app_design_step.py; echo EXIT=$?`
Expected: `EXIT=0`

Run: `uv run pytest -q -p no:cacheprovider; echo EXIT=$?`
Expected: `EXIT=0`, with only the 2 known XFAILs (the MTX Dv50/Dv90)

- [ ] **Step 7: Check it in the browser**

Start the app with `preview_start` (the `.claude/launch.json` Streamlit entry) and sign in as a local test account. Then:

1. In the Design step, fill in the nozzle.
2. **Save as new design**, and see "Saved #1 v1".
3. Edit a field, then **Save as v2 of #1**.
4. Pick **v1** in the Version box and see the fields return to it.
5. Take a screenshot as proof.

- [ ] **Step 8: Commit**

```bash
git add app/components/save_design.py app/views/design.py tests/test_app_saved_designs.py docs/superpowers/specs/2026-09-26-accounts-design.md
git commit -m "feat(design): save a design as new or as its next version, and download it

Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"
```

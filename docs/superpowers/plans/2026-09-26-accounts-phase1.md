# Accounts Phase 1 — Accounts and Approval — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Everyone logs in to the app; visitors sign up and wait for an admin's approval; the admin approves, rejects, disables, re-enables and resets passwords on an Admin screen; the first admin is made from the command line.

**Architecture:** Pure account logic with no Streamlit import in `app/accounts/` (argon2id hashing, a stdlib-SQLite store, the rules). A thin Streamlit session layer (`app/auth.py`) keeps the signed-in account id in `st.session_state` and ends idle or no-longer-approved sessions. A login gate at the top of `app/streamlit_app.py` shows the login screens and stops the run for anyone who is not an approved, signed-in account. Timed fragments re-check the session.

**Tech Stack:** Python 3.12, Streamlit 1.64 (AppTest for tests), stdlib `sqlite3`, `argon2-cffi` (the one new dependency), argparse CLI, pytest.

**Spec:** `docs/superpowers/specs/2026-09-26-accounts-design.md` — this plan is its **Phase 1** only.

**Base branch:** `feat/live-simulator` (PR #1, not yet merged): the gate changes files that only exist on that branch. Before Task 1:

```bash
cd /Users/sajil/Solit2_simulator
git worktree add .worktrees/accounts -b feat/accounts feat/live-simulator
cd .worktrees/accounts
git merge --no-edit main        # brings in the accounts spec and this plan (docs only)
uv sync
PATH=$(echo "$PATH" | tr ':' '\n' | grep -v -i fds | paste -sd: -) perl -e 'alarm shift; exec @ARGV' 900 uv run pytest
```

Baseline: `1035 passed` on `feat/live-simulator` at ffc0209.

## Global Constraints

Copied from the spec, verbatim where the spec gives a value:

- Passwords hashed with **argon2id** (`argon2-cffi`, **the one new dependency**; its default parameters exceed the OWASP minimum), verified with the library's constant-time check, **re-hashed when the parameters change**.
- Passwords **at least 12 characters**. The **same "email or password is wrong" message** for an unknown email and a wrong password. On sign-up, **a neutral message for an email already registered**.
- **Lockout: 5 failed logins lock the account for 15 minutes** (counted in the database, per account).
- A session is the Streamlit session: **the user id lives in `st.session_state`, never in a URL or a cookie**; **an idle session expires after 8 hours**; a refresh asks for the login again.
- **The login gate runs at the top of `app/streamlit_app.py`, before anything else renders; nothing below it runs for a visitor who is not an approved user.** (`st.set_page_config` must be the first Streamlit call and `theme.inject()` is CSS only, so both stay above the gate.)
- **Password reset is done by an admin, with no email service**: a temporary password shown once on the admin's screen; the account must set a new password at its next login. **No reset token ever travels in a URL.**
- **The first admin** is created with `solit2 accounts create-admin --email …`, which **asks for the password twice (never an argument, never a default)**.
- **Storage:** SQLite (stdlib `sqlite3`) at **`$SOLIT2_DATA_DIR/accounts.db` (default `data/accounts.db`, git-ignored)**, **WAL mode, one short connection per operation**. Tables exactly: `users` (id, email unique case-insensitively, name, organisation, password_hash, must_change_password, role, state, failed_logins, locked_until, created_at, approved_at, approved_by, last_login_at) and `admin_actions` (id, admin_id, action, target_user_id, detail, at).
- Roles **admin / team / customer**; states **pending → approved (as team or customer) / rejected; approved → disabled** (and back). Only approved accounts get past the login.
- **Code layout:** pure logic with **no Streamlit import in `app/accounts/`** (`passwords.py`, `store.py`, `service.py`); screens in `app/views/login.py` and `app/views/admin.py`; the CLI command in `solit2/cli.py`.
- **The server keeps its Caddy IP allowlist** until a security review of this phase has passed. This plan deploys nothing.
- Out of scope here: email sending, single sign-on, workspaces (Phase 2), usage and credits (Phase 3), payment (Phase 4).
- **INDEPENDENCE** (see `INDEPENDENCE.md`): no project or vendor names anywhere under `solit2/`, `app/`, `examples/` — the scan in `tests/test_independence.py` covers every new file. Test data uses `@example.test` emails and neutral names.
- **Commits:** conventional messages; **no `Co-Authored-By` trailer** (attribution is disabled for this user).
- **Test commands:** no GNU `timeout` on this Mac, and `pytest` already adds `-q` (never pass it). A file: `perl -e 'alarm shift; exec @ARGV' 900 uv run pytest tests/<file>.py -x`. The full suite, FDS stripped from PATH: `PATH=$(echo "$PATH" | tr ':' '\n' | grep -v -i fds | paste -sd: -) perl -e 'alarm shift; exec @ARGV' 900 uv run pytest`.

## Rulings (decisions this plan makes where the spec is silent)

1. **Customers see a holding screen in Phase 1.** The spec gives a customer "only their own workspace"; workspaces are Phase 2. Showing a customer the shared `designs/` and runs would leak the project's confidential data, so until Phase 2 a customer gets the nav's Log out and one holding message, and no project screen.
2. **Streamlit session code lives in `app/auth.py`** (it needs Streamlit, which `app/accounts/` must not import), and times are formatted by a tiny `app/components/local_time.py` shared by both screens.
3. **Timed fragments re-check the session** (`auth.guard_fragment()` first in each `st.fragment(run_every=…)`): a timed refresh does not pass through the gate, and must not keep running for an ended session.
4. **An admin cannot change their own account** on the Admin screen (no self-lockout); admins are made only by the CLI; approval is as team or customer only.
5. **A new password must differ from the current one** — the temporary password is known to the admin, so keeping it would defeat the forced change.
6. **Log out, idle expiry and loss of access clear the whole `st.session_state`**, so the next person to sign in on that tab starts from nothing.
7. **Reject asks once more** (a rejected account stays rejected).
8. **An unknown email still runs one argon2 verify** against a dummy hash, so the answer takes as long as a wrong password.
9. **Emails are restricted to a conservative character set** at sign-up; **names and organisations are never rendered as markdown** (only `st.text` or table cells), because visitors type them and the admin reads them.
10. **`create-admin` also takes `--name` and `--organisation`** (both are `NOT NULL` columns).
11. **The store file is owner read/write (0600); a data directory the store creates is owner-only (0700).** An existing directory's mode is never changed.
12. **Login forms use `st.form`**, so a keystroke never reruns the app and the password travels once, on submit.

## File map

| File | Task | Responsibility |
|---|---|---|
| `app/accounts/__init__.py` | 1 | package marker |
| `app/accounts/passwords.py` | 1 | argon2id hash/verify/rehash, dummy verify, policy, temporary passwords |
| `app/accounts/store.py` | 2 | SQLite file, schema, `User`/`AdminAction`, plain SQL |
| `app/accounts/service.py` | 3 | the rules: sign-up, login + lockout, state machine, temp and changed passwords, first admin |
| `solit2/cli.py` | 4 | `solit2 accounts create-admin` |
| `app/auth.py` | 5 | the signed-in session: sign in/out, idle and access checks, fragment guard |
| `app/views/simulator.py`, `app/views/runs.py`, `app/views/cfd.py` | 5 | guard each timed fragment |
| `tests/conftest.py` | 2, 5, 6 | per-test account store; `make_account`, `sign_in`, `screen_text` |
| `app/components/local_time.py` | 6 | datetimes in the server's zone, zone named |
| `app/views/login.py` | 6 | the gate and its screens |
| `app/state.py`, `app/components/nav.py`, `app/streamlit_app.py` | 6, 7 | role-aware screens, Log out, the gate's place, the Admin screen's place |
| `app/views/admin.py` | 7 | the Admin screen |
| `README.md` | 4, 6, 7 | Accounts section; login in "Running the app" |
| `.gitignore` | 2 | `/data/` |

---

### Task 1: Password hashing and the password policy

**Files:**
- Create: `app/accounts/__init__.py`, `app/accounts/passwords.py`
- Modify: `pyproject.toml`, `uv.lock` (through `uv add`)
- Test: `tests/test_accounts_passwords.py`

**Interfaces:**
- Consumes: nothing.
- Produces: `passwords.MIN_CHARS = 12`, `passwords.MAX_CHARS = 256`, `passwords.TEMPORARY_ALPHABET: str`, `hash_password(password: str) -> str`, `verify(stored_hash: str, password: str) -> bool`, `verify_dummy(password: str) -> None`, `needs_rehash(stored_hash: str) -> bool`, `policy_error(password: str, confirm: str) -> str | None`, `temporary_password() -> str`.

- [ ] **Step 1: Add the dependency**

Run: `uv add argon2-cffi`
Expected: `pyproject.toml`'s `dependencies` gains `argon2-cffi>=…` and `uv.lock` updates. No other dependency is added.

- [ ] **Step 2: Write the failing test** — `tests/test_accounts_passwords.py`

```python
"""Password hashing and policy: argon2id, rehash on new parameters, the policy's limits."""
import re

import argon2
from argon2 import PasswordHasher

from app.accounts import passwords

PASSWORD = "correct horse battery staple"
# OWASP's lowest-memory argon2id configuration: 19 MiB of memory, 2 passes.
OWASP_MIN_MEMORY_KIB, OWASP_MIN_PASSES = 19 * 1024, 2


def test_a_hash_is_argon2id_at_or_above_the_owasp_minimum():
    stored = passwords.hash_password(PASSWORD)
    params = argon2.extract_parameters(stored)
    assert params.type is argon2.Type.ID
    assert params.memory_cost >= OWASP_MIN_MEMORY_KIB
    assert params.time_cost >= OWASP_MIN_PASSES


def test_the_right_password_verifies_and_a_wrong_one_does_not():
    stored = passwords.hash_password(PASSWORD)
    assert passwords.verify(stored, PASSWORD)
    assert not passwords.verify(stored, PASSWORD + "!")


def test_one_password_hashes_differently_each_time():
    assert passwords.hash_password(PASSWORD) != passwords.hash_password(PASSWORD)


def test_an_unreadable_hash_is_a_mismatch_not_a_crash():
    assert not passwords.verify("not a hash", PASSWORD)


def test_a_hash_made_under_other_parameters_verifies_and_asks_for_a_rehash():
    old = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash(PASSWORD)
    assert passwords.verify(old, PASSWORD)
    assert passwords.needs_rehash(old)
    assert not passwords.needs_rehash(passwords.hash_password(PASSWORD))


def test_the_dummy_check_accepts_any_input_quietly():
    assert passwords.verify_dummy("anything at all") is None


def test_the_policy_bounds_the_length_and_wants_the_two_entries_to_match():
    shortest = "x" * passwords.MIN_CHARS
    longest = "x" * passwords.MAX_CHARS
    assert passwords.policy_error(shortest, shortest) is None
    assert passwords.policy_error(longest, longest) is None
    assert passwords.policy_error(shortest[:-1], shortest[:-1]) == (
        "The password must be at least 12 characters.")
    assert passwords.policy_error(longest + "x", longest + "x") == (
        "The password can be at most 256 characters.")
    assert passwords.policy_error(shortest, shortest + "y") == "The two passwords do not match."


def test_a_temporary_password_is_readable_random_and_passes_the_policy():
    char = f"[{passwords.TEMPORARY_ALPHABET}]"
    shape = re.compile(rf"{char}{{4}}(-{char}{{4}}){{3}}")
    first, second = passwords.temporary_password(), passwords.temporary_password()
    assert shape.fullmatch(first) and shape.fullmatch(second)
    assert first != second
    assert passwords.policy_error(first, first) is None
```

- [ ] **Step 3: Run it to see it fail**

Run: `perl -e 'alarm shift; exec @ARGV' 900 uv run pytest tests/test_accounts_passwords.py -x`
Expected: FAIL — `ModuleNotFoundError: No module named 'app.accounts'`

- [ ] **Step 4: Write the implementation**

`app/accounts/__init__.py`:

```python
"""User accounts: passwords, the account store and the rules over them.

Nothing in this package imports Streamlit, so the command line uses it as the app does.
"""
```

`app/accounts/passwords.py`:

```python
"""Password hashing and the password policy.

argon2id through argon2-cffi. The library's default parameters (64 MiB, 3 passes,
4 lanes: RFC 9106's low-memory profile) exceed the OWASP minimum, and its verify
compares in constant time. A hash made under other parameters still verifies, and
`needs_rehash` tells the caller to store a fresh one.
"""
from __future__ import annotations

import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

MIN_CHARS = 12
MAX_CHARS = 256
# Temporary passwords: four groups of four from an alphabet without look-alikes
# (no 0/O, no 1/l/I), so an admin can read one out without a mistake.
TEMPORARY_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"
TEMPORARY_GROUPS = 4
TEMPORARY_GROUP_CHARS = 4

_HASHER = PasswordHasher()
# Checked when an email has no account, so that answer costs what a wrong password
# costs and its timing does not tell which emails exist.
_DUMMY_HASH = _HASHER.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return _HASHER.hash(password)


def verify(stored_hash: str, password: str) -> bool:
    """True when `password` matches; False on a mismatch or on a hash that cannot be read."""
    try:
        return _HASHER.verify(stored_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def verify_dummy(password: str) -> None:
    verify(_DUMMY_HASH, password)


def needs_rehash(stored_hash: str) -> bool:
    return _HASHER.check_needs_rehash(stored_hash)


def policy_error(password: str, confirm: str) -> str | None:
    """Why the password (typed twice) is refused, or None when it is acceptable."""
    if len(password) < MIN_CHARS:
        return f"The password must be at least {MIN_CHARS} characters."
    if len(password) > MAX_CHARS:
        return f"The password can be at most {MAX_CHARS} characters."
    if password != confirm:
        return "The two passwords do not match."
    return None


def temporary_password() -> str:
    return "-".join(
        "".join(secrets.choice(TEMPORARY_ALPHABET) for _ in range(TEMPORARY_GROUP_CHARS))
        for _ in range(TEMPORARY_GROUPS))
```

- [ ] **Step 5: Run it to see it pass**

Run: `perl -e 'alarm shift; exec @ARGV' 900 uv run pytest tests/test_accounts_passwords.py tests/test_independence.py -x`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml uv.lock app/accounts/__init__.py app/accounts/passwords.py tests/test_accounts_passwords.py
git commit -m "feat(accounts): argon2id password hashing and the password policy"
```

---

### Task 2: The account store

**Files:**
- Create: `app/accounts/store.py`
- Modify: `.gitignore` (append), `tests/conftest.py` (one autouse fixture and one import)
- Test: `tests/test_accounts_store.py`

**Interfaces:**
- Consumes: nothing from Task 1.
- Produces:
  - constants `DATA_DIR_ENV = "SOLIT2_DATA_DIR"`, `DEFAULT_DATA_DIR = Path("data")`, `DB_NAME = "accounts.db"`, `SCHEMA_VERSION = 1`, `FILE_MODE = 0o600`, `DIR_MODE = 0o700`;
  - `@dataclass(frozen=True) User(id, email, name, organisation, role: str | None, state, must_change_password: bool, failed_logins: int, locked_until: datetime | None, created_at: datetime, approved_at: datetime | None, approved_by: int | None, last_login_at: datetime | None)` — **no password_hash field**;
  - `@dataclass(frozen=True) AdminAction(id, at: datetime, admin_email: str, action: str, target_email: str | None, detail: str)`;
  - `db_path() -> Path`, `init(db: Path) -> None`, `connect(db: Path)` (context manager yielding `sqlite3.Connection`);
  - `insert_user(conn, *, email, name, organisation, password_hash, state, now, role=None, must_change_password=False, approved_at=None, approved_by=None) -> int`;
  - `user_by_id(conn, user_id) -> User | None`, `credentials_by_email(conn, email) -> tuple[User, str] | None`, `password_hash(conn, user_id) -> str | None`, `list_users(conn) -> list[User]` (newest first);
  - `update_user(conn, user_id, **fields) -> None` (only updatable columns; datetimes and bools converted);
  - `record_failed_login(conn, user_id, *, limit: int, lock_until: datetime) -> None`;
  - `record_action(conn, *, admin_id, action, target_user_id, detail, now) -> None`, `list_actions(conn, limit: int) -> list[AdminAction]` (newest first).

- [ ] **Step 1: Write the failing test** — `tests/test_accounts_store.py`

```python
"""The account store: its file and schema, and the constraints the database itself enforces."""
import dataclasses
import sqlite3
import stat
from datetime import UTC, datetime, timedelta

import pytest

from app.accounts import store

T0 = datetime(2026, 9, 26, 10, 0, tzinfo=UTC)


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "data" / "accounts.db"
    store.init(path)
    return path


def _add(conn, email="a@example.test", state="pending", role=None, **extra):
    return store.insert_user(conn, email=email, name="A Person", organisation="An Org",
                             password_hash="$argon2id$fake", state=state, role=role, now=T0,
                             **extra)


def test_the_store_lives_under_the_data_dir_env(monkeypatch, tmp_path):
    monkeypatch.setenv(store.DATA_DIR_ENV, str(tmp_path))
    assert store.db_path() == tmp_path / "accounts.db"
    monkeypatch.delenv(store.DATA_DIR_ENV)
    assert store.db_path() == store.DEFAULT_DATA_DIR / "accounts.db"


def test_init_makes_an_owner_only_wal_database_with_both_tables(db):
    assert stat.S_IMODE(db.stat().st_mode) == store.FILE_MODE
    assert stat.S_IMODE(db.parent.stat().st_mode) == store.DIR_MODE
    with store.connect(db) as conn:
        assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert conn.execute("PRAGMA user_version").fetchone()[0] == store.SCHEMA_VERSION
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
    assert {"users", "admin_actions"} <= tables


def test_init_again_keeps_what_is_stored(db):
    with store.connect(db) as conn:
        _add(conn)
    store.init(db)
    with store.connect(db) as conn:
        assert len(store.list_users(conn)) == 1


def test_a_user_round_trips_with_aware_times_and_has_no_hash_field(db):
    with store.connect(db) as conn:
        user = store.user_by_id(conn, _add(conn, must_change_password=True))
    assert (user.email, user.state, user.role, user.must_change_password) == (
        "a@example.test", "pending", None, True)
    assert user.created_at == T0 and user.created_at.tzinfo is not None
    assert "password_hash" not in {f.name for f in dataclasses.fields(store.User)}


def test_email_is_unique_whatever_its_case(db):
    with store.connect(db) as conn:
        _add(conn, email="a@example.test")
    with pytest.raises(sqlite3.IntegrityError), store.connect(db) as conn:
        _add(conn, email="A@Example.TEST")


@pytest.mark.parametrize("state, role", [
    ("approved", None), ("disabled", None), ("pending", "team"), ("rejected", "customer"),
    ("approved", "owner"), ("gone", None)])
def test_the_database_refuses_a_state_and_role_that_do_not_fit(db, state, role):
    with pytest.raises(sqlite3.IntegrityError), store.connect(db) as conn:
        _add(conn, state=state, role=role)


def test_credentials_come_only_through_their_own_readers(db):
    with store.connect(db) as conn:
        user_id = _add(conn)
        user, stored = store.credentials_by_email(conn, "a@example.test")
        assert (user.id, stored) == (user_id, "$argon2id$fake")
        assert store.password_hash(conn, user_id) == "$argon2id$fake"
        assert store.credentials_by_email(conn, "nobody@example.test") is None


def test_update_names_only_updatable_columns(db):
    with store.connect(db) as conn:
        user_id = _add(conn)
    for bad in ({"email": "b@example.test"}, {"id": 9}, {"created_at": T0}, {}):
        with pytest.raises(ValueError), store.connect(db) as conn:
            store.update_user(conn, user_id, **bad)
    with store.connect(db) as conn:
        store.update_user(conn, user_id, state="approved", role="team", approved_at=T0,
                          must_change_password=False)
        user = store.user_by_id(conn, user_id)
    assert (user.state, user.role, user.approved_at, user.email) == (
        "approved", "team", T0, "a@example.test")


def test_the_fifth_failed_login_locks_and_restarts_the_count(db):
    until = T0 + timedelta(minutes=15)
    with store.connect(db) as conn:
        user_id = _add(conn)
        for _ in range(4):
            store.record_failed_login(conn, user_id, limit=5, lock_until=until)
        user = store.user_by_id(conn, user_id)
        assert (user.failed_logins, user.locked_until) == (4, None)
        store.record_failed_login(conn, user_id, limit=5, lock_until=until)
        user = store.user_by_id(conn, user_id)
    assert (user.failed_logins, user.locked_until) == (0, until)


def test_a_block_that_raises_leaves_nothing_behind(db):
    with pytest.raises(RuntimeError), store.connect(db) as conn:
        _add(conn)
        raise RuntimeError("boom")
    with store.connect(db) as conn:
        assert store.list_users(conn) == []


def test_admin_actions_list_newest_first_with_both_emails(db):
    with store.connect(db) as conn:
        admin_id = _add(conn, email="admin@example.test", state="approved", role="admin")
        target_id = _add(conn, email="t@example.test")
        store.record_action(conn, admin_id=admin_id, action="approve", target_user_id=target_id,
                            detail="role=team", now=T0)
        store.record_action(conn, admin_id=admin_id, action="create_admin", target_user_id=None,
                            detail="", now=T0 + timedelta(minutes=1))
        actions = store.list_actions(conn, limit=10)
        assert [a.action for a in actions] == ["create_admin", "approve"]
        assert (actions[1].admin_email, actions[1].target_email, actions[1].detail) == (
            "admin@example.test", "t@example.test", "role=team")
        assert actions[0].target_email is None
        assert len(store.list_actions(conn, limit=1)) == 1
```

- [ ] **Step 2: Run it to see it fail**

Run: `perl -e 'alarm shift; exec @ARGV' 900 uv run pytest tests/test_accounts_store.py -x`
Expected: FAIL — `ImportError: cannot import name 'store' from 'app.accounts'`

- [ ] **Step 3: Write the implementation** — `app/accounts/store.py`

```python
"""The account store: SQLite from the standard library, one short connection per operation.

The file is $SOLIT2_DATA_DIR/accounts.db (default data/accounts.db, git-ignored). It holds
password hashes, so it is kept owner read/write, and a data directory it creates is
owner-only. WAL mode lets the app's sessions read while one of them writes.

Plain SQL only: who may do what, the lockout and the state machine live in service.py.
A password hash is read only through `credentials_by_email` and `password_hash`; it is
never a field of `User`, so nothing that shows a User can show a hash.
"""
from __future__ import annotations

import os
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

DATA_DIR_ENV = "SOLIT2_DATA_DIR"
DEFAULT_DATA_DIR = Path("data")
DB_NAME = "accounts.db"
SCHEMA_VERSION = 1
BUSY_TIMEOUT_S = 5.0
DIR_MODE, FILE_MODE = 0o700, 0o600

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id                   INTEGER PRIMARY KEY,
    email                TEXT NOT NULL UNIQUE COLLATE NOCASE,
    name                 TEXT NOT NULL,
    organisation         TEXT NOT NULL,
    password_hash        TEXT NOT NULL,
    must_change_password INTEGER NOT NULL DEFAULT 0,
    role                 TEXT CHECK (role IN ('admin', 'team', 'customer')),
    state                TEXT NOT NULL
                         CHECK (state IN ('pending', 'approved', 'rejected', 'disabled')),
    failed_logins        INTEGER NOT NULL DEFAULT 0,
    locked_until         TEXT,
    created_at           TEXT NOT NULL,
    approved_at          TEXT,
    approved_by          INTEGER REFERENCES users (id),
    last_login_at        TEXT,
    -- an approved or disabled account has a role; a pending or rejected one has none
    CHECK ((state IN ('approved', 'disabled')) = (role IS NOT NULL))
);
CREATE TABLE IF NOT EXISTS admin_actions (
    id             INTEGER PRIMARY KEY,
    admin_id       INTEGER NOT NULL REFERENCES users (id),
    action         TEXT NOT NULL,
    target_user_id INTEGER REFERENCES users (id),
    detail         TEXT NOT NULL DEFAULT '',
    at             TEXT NOT NULL
);
"""
_USER_COLUMNS = ("id, email, name, organisation, role, state, must_change_password, "
                 "failed_logins, locked_until, created_at, approved_at, approved_by, last_login_at")
_UPDATABLE = frozenset({"name", "organisation", "password_hash", "must_change_password", "role",
                        "state", "failed_logins", "locked_until", "approved_at", "approved_by",
                        "last_login_at"})


@dataclass(frozen=True)
class User:
    id: int
    email: str
    name: str
    organisation: str
    role: str | None
    state: str
    must_change_password: bool
    failed_logins: int
    locked_until: datetime | None
    created_at: datetime
    approved_at: datetime | None
    approved_by: int | None
    last_login_at: datetime | None


@dataclass(frozen=True)
class AdminAction:
    id: int
    at: datetime
    admin_email: str
    action: str
    target_email: str | None
    detail: str


def db_path() -> Path:
    return Path(os.environ.get(DATA_DIR_ENV) or DEFAULT_DATA_DIR) / DB_NAME


@contextmanager
def connect(db: Path) -> Iterator[sqlite3.Connection]:
    """One short connection: commits if the block succeeds, rolls back if it raises, always closes."""
    conn = sqlite3.connect(db, timeout=BUSY_TIMEOUT_S)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
        yield conn
        conn.commit()
    except BaseException:
        conn.rollback()
        raise
    finally:
        conn.close()


def init(db: Path) -> None:
    """Create the store if it is missing -- directory, file, tables -- and keep the file
    owner-only. Cheap and safe to call on every run of the app."""
    db.parent.mkdir(parents=True, exist_ok=True, mode=DIR_MODE)
    if not db.exists():
        db.touch(mode=FILE_MODE)
    os.chmod(db, FILE_MODE)
    with connect(db) as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(_SCHEMA)
        if conn.execute("PRAGMA user_version").fetchone()[0] != SCHEMA_VERSION:
            conn.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")


def _iso(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat(timespec="seconds")


def _dt(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


def _user(row: sqlite3.Row) -> User:
    return User(id=row["id"], email=row["email"], name=row["name"],
                organisation=row["organisation"], role=row["role"], state=row["state"],
                must_change_password=bool(row["must_change_password"]),
                failed_logins=row["failed_logins"], locked_until=_dt(row["locked_until"]),
                created_at=datetime.fromisoformat(row["created_at"]),
                approved_at=_dt(row["approved_at"]), approved_by=row["approved_by"],
                last_login_at=_dt(row["last_login_at"]))


def insert_user(conn: sqlite3.Connection, *, email: str, name: str, organisation: str,
                password_hash: str, state: str, now: datetime, role: str | None = None,
                must_change_password: bool = False, approved_at: datetime | None = None,
                approved_by: int | None = None) -> int:
    cursor = conn.execute(
        "INSERT INTO users (email, name, organisation, password_hash, must_change_password,"
        " role, state, created_at, approved_at, approved_by)"
        " VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (email, name, organisation, password_hash, int(must_change_password), role, state,
         _iso(now), _iso(approved_at), approved_by))
    return int(cursor.lastrowid)


def user_by_id(conn: sqlite3.Connection, user_id: int) -> User | None:
    row = conn.execute(f"SELECT {_USER_COLUMNS} FROM users WHERE id = ?", (user_id,)).fetchone()
    return None if row is None else _user(row)


def credentials_by_email(conn: sqlite3.Connection, email: str) -> tuple[User, str] | None:
    row = conn.execute(f"SELECT {_USER_COLUMNS}, password_hash FROM users WHERE email = ?",
                       (email,)).fetchone()
    return None if row is None else (_user(row), row["password_hash"])


def password_hash(conn: sqlite3.Connection, user_id: int) -> str | None:
    row = conn.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,)).fetchone()
    return None if row is None else row["password_hash"]


def list_users(conn: sqlite3.Connection) -> list[User]:
    rows = conn.execute(
        f"SELECT {_USER_COLUMNS} FROM users ORDER BY created_at DESC, id DESC").fetchall()
    return [_user(row) for row in rows]


def update_user(conn: sqlite3.Connection, user_id: int, **fields: object) -> None:
    """Set the named columns. Only the columns in _UPDATABLE may be named, so a column
    name never comes from anywhere else into the SQL."""
    unknown = sorted(set(fields) - _UPDATABLE)
    if unknown or not fields:
        raise ValueError(f"cannot update {unknown or 'nothing'}")
    values = [_iso(v) if isinstance(v, datetime) else int(v) if isinstance(v, bool) else v
              for v in fields.values()]
    assignments = ", ".join(f"{name} = ?" for name in fields)
    conn.execute(f"UPDATE users SET {assignments} WHERE id = ?", (*values, user_id))


def record_failed_login(conn: sqlite3.Connection, user_id: int, *, limit: int,
                        lock_until: datetime) -> None:
    """Count one failed login inside the database, so two at once cannot both slip under
    the limit. The `limit`-th failure in a row locks the account until `lock_until` and
    starts the count again."""
    conn.execute(
        "UPDATE users SET"
        " locked_until = CASE WHEN failed_logins + 1 >= :max_failed"
        "                THEN :until ELSE locked_until END,"
        " failed_logins = CASE WHEN failed_logins + 1 >= :max_failed"
        "                 THEN 0 ELSE failed_logins + 1 END"
        " WHERE id = :id",
        {"max_failed": limit, "until": _iso(lock_until), "id": user_id})


def record_action(conn: sqlite3.Connection, *, admin_id: int, action: str,
                  target_user_id: int | None, detail: str, now: datetime) -> None:
    conn.execute(
        "INSERT INTO admin_actions (admin_id, action, target_user_id, detail, at)"
        " VALUES (?, ?, ?, ?, ?)", (admin_id, action, target_user_id, detail, _iso(now)))


def list_actions(conn: sqlite3.Connection, limit: int) -> list[AdminAction]:
    rows = conn.execute(
        "SELECT a.id, a.at, admin.email AS admin_email, a.action,"
        " target.email AS target_email, a.detail"
        " FROM admin_actions a JOIN users admin ON admin.id = a.admin_id"
        " LEFT JOIN users target ON target.id = a.target_user_id"
        " ORDER BY a.at DESC, a.id DESC LIMIT ?", (limit,)).fetchall()
    return [AdminAction(id=row["id"], at=datetime.fromisoformat(row["at"]),
                        admin_email=row["admin_email"], action=row["action"],
                        target_email=row["target_email"], detail=row["detail"])
            for row in rows]
```

- [ ] **Step 4: Git-ignore the data directory** — append to `.gitignore`:

```
# the app's account store (password hashes) -- never committed. Anchored, like /reports/.
/data/
```

- [ ] **Step 5: Give every test its own store** — in `tests/conftest.py`, add the import next to the existing ones and this fixture after `EXAMPLE_DESIGN`:

```python
from app.accounts import store
```

```python
@pytest.fixture(autouse=True)
def _account_store_per_test(tmp_path_factory, monkeypatch):
    """Every test gets its own empty account store; no test touches data/accounts.db."""
    monkeypatch.setenv(store.DATA_DIR_ENV, str(tmp_path_factory.mktemp("accounts")))
```

- [ ] **Step 6: Run the tests**

Run: `perl -e 'alarm shift; exec @ARGV' 900 uv run pytest tests/test_accounts_store.py tests/test_independence.py -x`
Expected: PASS. Then `git status --short` shows no `data/` entry.

- [ ] **Step 7: Commit**

```bash
git add app/accounts/store.py tests/test_accounts_store.py tests/conftest.py .gitignore
git commit -m "feat(accounts): the SQLite account store"
```

---

### Task 3: The account rules

**Files:**
- Create: `app/accounts/service.py`
- Test: `tests/test_accounts_service.py`

**Interfaces:**
- Consumes: `passwords.*` (Task 1), `store.*` (Task 2).
- Produces:
  - constants `MAX_FAILED_LOGINS = 5`, `LOCKOUT = timedelta(minutes=15)`, `NAME_MAX_CHARS = 100`, `EMAIL_MAX_CHARS = 254`, `AUDIT_ROWS = 200`, `APPROVAL_ROLES = ("team", "customer")`;
  - `class AccountError(ValueError)` with `.field: str`; its message is safe to show;
  - `@dataclass(frozen=True) LoginResult(status, user: User | None = None, locked_until: datetime | None = None)`, status one of `"ok" | "wrong" | "locked" | "pending" | "rejected" | "disabled"`;
  - `normalise_email(raw) -> str`;
  - `sign_up(db, *, name, organisation, email, password, confirm, now=None) -> None`;
  - `log_in(db, email, password, *, now=None) -> LoginResult`;
  - `get_user(db, user_id) -> User | None`, `list_users(db) -> list[User]`, `list_actions(db, limit=AUDIT_ROWS) -> list[AdminAction]`;
  - `approve(db, admin_id, user_id, role, *, now=None) -> User`, `reject(db, admin_id, user_id, *, now=None) -> User`, `disable(...) -> User`, `enable(...) -> User`;
  - `issue_temporary_password(db, admin_id, user_id, *, now=None) -> str`;
  - `change_password(db, user_id, password, confirm) -> None`;
  - `create_admin(db, *, email, name, organisation, password, confirm, now=None) -> User`.

- [ ] **Step 1: Write the failing test** — `tests/test_accounts_service.py`

```python
"""The account rules: sign-up, login and lockout, the admin's state machine, temporary passwords."""
import ast
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from argon2 import PasswordHasher

from app.accounts import passwords, service, store
from app.accounts.service import AccountError

T0 = datetime(2026, 9, 26, 10, 0, tzinfo=UTC)
PASSWORD = "a long enough password"
NEW_PASSWORD = "another long password"
WRONG = "a wrong password!"


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "accounts.db"
    store.init(path)
    return path


@pytest.fixture
def admin(db):
    return service.create_admin(db, email="admin@example.test", name="Ada Admin",
                                organisation="Ops", password=PASSWORD, confirm=PASSWORD, now=T0)


def _by_email(db, email):
    return next(u for u in service.list_users(db) if u.email == email)


def _sign_up(db, email="new@example.test", name="Nia New"):
    service.sign_up(db, name=name, organisation="Customer Co", email=email, password=PASSWORD,
                    confirm=PASSWORD, now=T0)
    return _by_email(db, service.normalise_email(email))


def _approved(db, admin, email="team@example.test", role="team"):
    return service.approve(db, admin.id, _sign_up(db, email=email).id, role, now=T0)


def test_the_account_package_does_not_import_streamlit():
    for source in Path(service.__file__).parent.glob("*.py"):
        tree = ast.parse(source.read_text())
        imported = {alias.name.split(".")[0] for node in ast.walk(tree)
                    if isinstance(node, ast.Import) for alias in node.names}
        imported |= {node.module.split(".")[0] for node in ast.walk(tree)
                     if isinstance(node, ast.ImportFrom) and node.module}
        assert "streamlit" not in imported, source.name


# --- sign-up ------------------------------------------------------------------

def test_a_sign_up_waits_for_approval_with_no_role(db):
    user = _sign_up(db, email="  New@Example.TEST ")
    assert (user.email, user.state, user.role, user.name) == (
        "new@example.test", "pending", None, "Nia New")


def test_signing_up_an_email_already_registered_changes_nothing_and_says_nothing(db):
    _sign_up(db, name="First")
    service.sign_up(db, name="Second", organisation="Other", email="NEW@example.test",
                    password=NEW_PASSWORD, confirm=NEW_PASSWORD, now=T0)  # no error: neutral
    [user] = service.list_users(db)
    assert user.name == "First"
    assert service.log_in(db, "new@example.test", PASSWORD, now=T0).status == "pending"


@pytest.mark.parametrize("fields, field, message", [
    ({"name": "  "}, "name", "Enter your name."),
    ({"organisation": ""}, "organisation", "Enter your organisation."),
    ({"name": "x" * 101}, "name", "Your name can be at most 100 printable characters."),
    ({"name": "Two\nlines"}, "name", "Your name can be at most 100 printable characters."),
    ({"email": "not-an-email"}, "email", "Enter a valid email address."),
    ({"email": "[x](y)@example.test"}, "email", "Enter a valid email address."),
    ({"password": "short", "confirm": "short"}, "password",
     "The password must be at least 12 characters."),
    ({"confirm": PASSWORD + "x"}, "password", "The two passwords do not match."),
])
def test_a_sign_up_the_rules_refuse_stores_nothing(db, fields, field, message):
    values = {"name": "Nia", "organisation": "Co", "email": "n@example.test",
              "password": PASSWORD, "confirm": PASSWORD, **fields}
    with pytest.raises(AccountError) as refused:
        service.sign_up(db, **values)
    assert (refused.value.field, str(refused.value)) == (field, message)
    assert service.list_users(db) == []


# --- login and lockout --------------------------------------------------------

def test_an_unknown_email_and_a_wrong_password_get_the_same_answer(db, admin):
    unknown = service.log_in(db, "nobody@example.test", PASSWORD, now=T0)
    wrong = service.log_in(db, "admin@example.test", WRONG, now=T0)
    assert unknown == wrong == service.LoginResult("wrong")
    assert _by_email(db, "admin@example.test").failed_logins == 1


@pytest.mark.parametrize("final_state", ["pending", "rejected", "disabled"])
def test_only_a_correct_password_learns_an_unapproved_accounts_state(db, admin, final_state):
    user = _sign_up(db)
    if final_state == "rejected":
        service.reject(db, admin.id, user.id, now=T0)
    elif final_state == "disabled":
        service.approve(db, admin.id, user.id, "team", now=T0)
        service.disable(db, admin.id, user.id, now=T0)
    assert service.log_in(db, user.email, WRONG, now=T0).status == "wrong"
    result = service.log_in(db, user.email, PASSWORD, now=T0)
    assert (result.status, result.user) == (final_state, None)


def test_an_approved_login_returns_the_account_and_stamps_it(db, admin):
    user = _approved(db, admin)
    service.log_in(db, user.email, WRONG, now=T0)
    later = T0 + timedelta(minutes=1)
    result = service.log_in(db, " TEAM@example.test ", PASSWORD, now=later)
    assert result.status == "ok"
    assert (result.user.id, result.user.last_login_at, result.user.failed_logins) == (
        user.id, later, 0)


def test_five_wrong_passwords_lock_the_account_for_fifteen_minutes(db, admin):
    user = _approved(db, admin)
    for _ in range(service.MAX_FAILED_LOGINS):
        assert service.log_in(db, user.email, WRONG, now=T0).status == "wrong"
    locked = service.log_in(db, user.email, PASSWORD, now=T0 + timedelta(minutes=14))
    assert locked == service.LoginResult("locked", locked_until=T0 + service.LOCKOUT)
    after = T0 + service.LOCKOUT + timedelta(seconds=1)
    assert service.log_in(db, user.email, PASSWORD, now=after).status == "ok"


def test_a_locked_account_does_not_check_the_password_or_extend_the_lock(db, admin):
    user = _approved(db, admin)
    for _ in range(service.MAX_FAILED_LOGINS):
        service.log_in(db, user.email, WRONG, now=T0)
    service.log_in(db, user.email, WRONG, now=T0 + timedelta(minutes=5))
    assert _by_email(db, user.email).locked_until == T0 + service.LOCKOUT
    assert _by_email(db, user.email).failed_logins == 0


def test_a_hash_under_old_parameters_is_replaced_at_the_next_login(db, admin):
    user = _approved(db, admin)
    old = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash(PASSWORD)
    with store.connect(db) as conn:
        store.update_user(conn, user.id, password_hash=old)
    assert service.log_in(db, user.email, PASSWORD, now=T0).status == "ok"
    with store.connect(db) as conn:
        fresh = store.password_hash(conn, user.id)
    assert fresh != old and not passwords.needs_rehash(fresh)


# --- the admin's state machine ------------------------------------------------

def test_approving_sets_the_role_and_who_approved_it(db, admin):
    approved = service.approve(db, admin.id, _sign_up(db).id, "customer", now=T0)
    assert (approved.state, approved.role, approved.approved_by, approved.approved_at) == (
        "approved", "customer", admin.id, T0)


def test_an_account_is_approved_as_team_or_customer_only(db, admin):
    user = _sign_up(db)
    with pytest.raises(AccountError):
        service.approve(db, admin.id, user.id, "admin", now=T0)
    assert _by_email(db, user.email).state == "pending"


def test_a_rejected_account_stays_rejected(db, admin):
    user = _sign_up(db)
    assert service.reject(db, admin.id, user.id, now=T0).state == "rejected"
    with pytest.raises(AccountError, match="only pending accounts can be approved"):
        service.approve(db, admin.id, user.id, "team", now=T0)


def test_disable_and_re_enable_keep_the_role(db, admin):
    user = _approved(db, admin, role="customer")
    assert service.disable(db, admin.id, user.id, now=T0).state == "disabled"
    with pytest.raises(AccountError, match="only approved accounts can be disabled"):
        service.disable(db, admin.id, user.id, now=T0)
    enabled = service.enable(db, admin.id, user.id, now=T0)
    assert (enabled.state, enabled.role) == ("approved", "customer")


def test_an_admin_cannot_change_their_own_account(db, admin):
    with pytest.raises(AccountError, match="your own account"):
        service.disable(db, admin.id, admin.id, now=T0)
    with pytest.raises(AccountError, match="your own account"):
        service.issue_temporary_password(db, admin.id, admin.id, now=T0)


def test_only_an_approved_admin_can_act(db, admin):
    team = _approved(db, admin)
    other = _sign_up(db, email="other@example.test")
    with pytest.raises(AccountError, match="Only an administrator"):
        service.approve(db, team.id, other.id, "team", now=T0)
    second = service.create_admin(db, email="second@example.test", name="Bo", organisation="Ops",
                                  password=PASSWORD, confirm=PASSWORD, now=T0)
    service.disable(db, admin.id, second.id, now=T0)
    with pytest.raises(AccountError, match="Only an administrator"):
        service.approve(db, second.id, other.id, "team", now=T0)
    assert _by_email(db, other.email).state == "pending"


def test_every_admin_action_lands_in_the_audit_trail(db, admin):
    user = _sign_up(db)
    service.approve(db, admin.id, user.id, "team", now=T0 + timedelta(minutes=1))
    service.disable(db, admin.id, user.id, now=T0 + timedelta(minutes=2))
    service.enable(db, admin.id, user.id, now=T0 + timedelta(minutes=3))
    service.issue_temporary_password(db, admin.id, user.id, now=T0 + timedelta(minutes=4))
    refused = _sign_up(db, email="no@example.test")
    service.reject(db, admin.id, refused.id, now=T0 + timedelta(minutes=5))
    trail = service.list_actions(db)
    assert [(a.action, a.target_email) for a in trail] == [
        ("reject", "no@example.test"), ("temporary_password", user.email),
        ("enable", user.email), ("disable", user.email), ("approve", user.email),
        ("create_admin", "admin@example.test")]
    assert {a.admin_email for a in trail} == {"admin@example.test"}
    assert trail[-2].detail == "role=team"


# --- temporary and changed passwords -----------------------------------------

def test_a_temporary_password_replaces_the_old_one_clears_a_lock_and_must_be_changed(db, admin):
    user = _approved(db, admin)
    for _ in range(service.MAX_FAILED_LOGINS):
        service.log_in(db, user.email, WRONG, now=T0)
    temporary = service.issue_temporary_password(db, admin.id, user.id, now=T0)
    assert service.log_in(db, user.email, PASSWORD, now=T0).status == "wrong"
    result = service.log_in(db, user.email, temporary, now=T0)
    assert (result.status, result.user.must_change_password) == ("ok", True)
    assert temporary not in " ".join(a.detail for a in service.list_actions(db))


def test_a_temporary_password_is_for_approved_accounts_only(db, admin):
    user = _sign_up(db)
    with pytest.raises(AccountError, match="only approved accounts"):
        service.issue_temporary_password(db, admin.id, user.id, now=T0)


def test_changing_the_password_clears_the_must_change_flag(db, admin):
    user = _approved(db, admin)
    temporary = service.issue_temporary_password(db, admin.id, user.id, now=T0)
    with pytest.raises(AccountError, match="different from the one you have now"):
        service.change_password(db, user.id, temporary, temporary)
    with pytest.raises(AccountError, match="do not match"):
        service.change_password(db, user.id, NEW_PASSWORD, NEW_PASSWORD + "x")
    service.change_password(db, user.id, NEW_PASSWORD, NEW_PASSWORD)
    result = service.log_in(db, user.email, NEW_PASSWORD, now=T0)
    assert (result.status, result.user.must_change_password) == ("ok", False)
    assert service.log_in(db, user.email, temporary, now=T0).status == "wrong"


# --- the first admin ----------------------------------------------------------

def test_create_admin_makes_an_approved_admin_and_records_it(db, admin):
    assert (admin.role, admin.state, admin.approved_at) == ("admin", "approved", T0)
    assert service.log_in(db, "ADMIN@example.test", PASSWORD, now=T0).user.role == "admin"
    [action] = service.list_actions(db)
    assert (action.action, action.target_email) == ("create_admin", "admin@example.test")


def test_create_admin_refuses_an_email_already_registered(db, admin):
    with pytest.raises(AccountError, match="already exists"):
        service.create_admin(db, email="Admin@Example.test", name="X", organisation="Y",
                             password=PASSWORD, confirm=PASSWORD, now=T0)


# --- nothing secret leaks -----------------------------------------------------

def test_no_password_or_hash_is_ever_logged(db, admin, caplog):
    caplog.set_level(logging.DEBUG)
    user = _approved(db, admin)
    service.log_in(db, user.email, WRONG, now=T0)
    service.log_in(db, user.email, PASSWORD, now=T0)
    temporary = service.issue_temporary_password(db, admin.id, user.id, now=T0)
    service.change_password(db, user.id, NEW_PASSWORD, NEW_PASSWORD)
    with store.connect(db) as conn:
        stored = store.password_hash(conn, user.id)
    for secret in (PASSWORD, NEW_PASSWORD, WRONG, temporary, stored, "$argon2"):
        assert secret not in caplog.text
```

- [ ] **Step 2: Run it to see it fail**

Run: `perl -e 'alarm shift; exec @ARGV' 900 uv run pytest tests/test_accounts_service.py -x`
Expected: FAIL — `ImportError: cannot import name 'service' from 'app.accounts'`

- [ ] **Step 3: Write the implementation** — `app/accounts/service.py`

```python
"""The account rules: sign-up, login and lockout, the admin's approvals, temporary passwords.

Every function opens one short connection and does its whole job in that one
transaction. What a person can fix raises AccountError, whose message is written for
them and safe to show. Nothing here imports Streamlit: the screens and the command
line both call this module.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from app.accounts import passwords, store
from app.accounts.store import AdminAction, User

MAX_FAILED_LOGINS = 5
LOCKOUT = timedelta(minutes=15)
NAME_MAX_CHARS = 100
EMAIL_MAX_CHARS = 254
AUDIT_ROWS = 200
APPROVAL_ROLES = ("team", "customer")
# A conservative address shape. It also keeps every stored email free of the characters
# markdown acts on, so an email is safe inside an on-screen message.
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
# action -> (the state it applies to, the state it leaves the account in)
_TRANSITIONS = {"approve": ("pending", "approved"), "reject": ("pending", "rejected"),
                "disable": ("approved", "disabled"), "enable": ("disabled", "approved")}
_DONE = {"approve": "approved", "reject": "rejected", "disable": "disabled",
         "enable": "re-enabled"}

LoginStatus = Literal["ok", "wrong", "locked", "pending", "rejected", "disabled"]


class AccountError(ValueError):
    """A request the account rules refuse. The message is written for the person who made it."""

    def __init__(self, message: str, field: str = "account") -> None:
        super().__init__(message)
        self.field = field


@dataclass(frozen=True)
class LoginResult:
    status: LoginStatus
    user: User | None = None
    locked_until: datetime | None = None


def _now(now: datetime | None) -> datetime:
    return datetime.now(UTC) if now is None else now.astimezone(UTC)


def normalise_email(raw: str) -> str:
    return raw.strip().lower()


def _checked_email(raw: str) -> str:
    email = normalise_email(raw)
    if len(email) > EMAIL_MAX_CHARS or not _EMAIL.fullmatch(email):
        raise AccountError("Enter a valid email address.", "email")
    return email


def _checked_text(raw: str, label: str) -> str:
    text = raw.strip()
    if not text:
        raise AccountError(f"Enter your {label}.", label)
    if len(text) > NAME_MAX_CHARS or not text.isprintable():
        raise AccountError(f"Your {label} can be at most {NAME_MAX_CHARS} printable characters.",
                           label)
    return text


def _checked_password(password: str, confirm: str) -> None:
    problem = passwords.policy_error(password, confirm)
    if problem:
        raise AccountError(problem, "password")


def _is_duplicate_email(exc: sqlite3.IntegrityError) -> bool:
    return "UNIQUE" in str(exc)


def sign_up(db: Path, *, name: str, organisation: str, email: str, password: str,
            confirm: str, now: datetime | None = None) -> None:
    """Record a sign-up, pending approval. An email already registered gets the same
    outcome and changes nothing, so the form never tells a visitor which emails exist."""
    clean_name, clean_org = _checked_text(name, "name"), _checked_text(organisation, "organisation")
    clean_email = _checked_email(email)
    _checked_password(password, confirm)
    hashed = passwords.hash_password(password)  # before the insert: both outcomes cost the same
    with store.connect(db) as conn:
        try:
            store.insert_user(conn, email=clean_email, name=clean_name, organisation=clean_org,
                              password_hash=hashed, state="pending", now=_now(now))
        except sqlite3.IntegrityError as exc:
            if not _is_duplicate_email(exc):
                raise


def log_in(db: Path, email: str, password: str, *, now: datetime | None = None) -> LoginResult:
    """Check a login. Only a correct password learns the account's state; a wrong password
    and an unknown email get the same answer, and every wrong password counts toward
    the lockout."""
    moment = _now(now)
    with store.connect(db) as conn:
        found = store.credentials_by_email(conn, normalise_email(email))
        if found is None:
            passwords.verify_dummy(password)
            return LoginResult("wrong")
        user, stored = found
        if user.locked_until is not None and user.locked_until > moment:
            return LoginResult("locked", locked_until=user.locked_until)
        if not passwords.verify(stored, password):
            store.record_failed_login(conn, user.id, limit=MAX_FAILED_LOGINS,
                                      lock_until=moment + LOCKOUT)
            return LoginResult("wrong")
        fields: dict[str, object] = {"failed_logins": 0, "locked_until": None}
        if passwords.needs_rehash(stored):
            fields["password_hash"] = passwords.hash_password(password)
        if user.state != "approved":
            store.update_user(conn, user.id, **fields)
            return LoginResult(user.state)
        store.update_user(conn, user.id, last_login_at=moment, **fields)
        return LoginResult("ok", user=store.user_by_id(conn, user.id))


def get_user(db: Path, user_id: int) -> User | None:
    with store.connect(db) as conn:
        return store.user_by_id(conn, user_id)


def list_users(db: Path) -> list[User]:
    with store.connect(db) as conn:
        return store.list_users(conn)


def list_actions(db: Path, limit: int = AUDIT_ROWS) -> list[AdminAction]:
    with store.connect(db) as conn:
        return store.list_actions(conn, limit)


def _acting_admin(conn: sqlite3.Connection, admin_id: int) -> User:
    """The admin, re-read from the store: the screens' own checks are not trusted alone."""
    admin = store.user_by_id(conn, admin_id)
    if admin is None or admin.role != "admin" or admin.state != "approved":
        raise AccountError("Only an administrator can do that.")
    return admin


def _target(conn: sqlite3.Connection, admin: User, user_id: int) -> User:
    target = store.user_by_id(conn, user_id)
    if target is None:
        raise AccountError("That account does not exist.")
    if target.id == admin.id:
        raise AccountError("You cannot change your own account here.")
    return target


def _transition(db: Path, admin_id: int, user_id: int, action: str, *,
                now: datetime | None, role: str | None = None) -> User:
    moment = _now(now)
    before, after = _TRANSITIONS[action]
    with store.connect(db) as conn:
        admin = _acting_admin(conn, admin_id)
        target = _target(conn, admin, user_id)
        if target.state != before:
            raise AccountError(f"This account is {target.state}; "
                               f"only {before} accounts can be {_DONE[action]}.")
        fields: dict[str, object] = {"state": after}
        if action == "approve":
            fields.update(role=role, approved_at=moment, approved_by=admin.id)
        store.update_user(conn, target.id, **fields)
        store.record_action(conn, admin_id=admin.id, action=action, target_user_id=target.id,
                            detail=f"role={role}" if role else "", now=moment)
        return store.user_by_id(conn, target.id)


def approve(db: Path, admin_id: int, user_id: int, role: str, *,
            now: datetime | None = None) -> User:
    if role not in APPROVAL_ROLES:
        raise AccountError(f"An account is approved as {' or '.join(APPROVAL_ROLES)}.", "role")
    return _transition(db, admin_id, user_id, "approve", now=now, role=role)


def reject(db: Path, admin_id: int, user_id: int, *, now: datetime | None = None) -> User:
    return _transition(db, admin_id, user_id, "reject", now=now)


def disable(db: Path, admin_id: int, user_id: int, *, now: datetime | None = None) -> User:
    return _transition(db, admin_id, user_id, "disable", now=now)


def enable(db: Path, admin_id: int, user_id: int, *, now: datetime | None = None) -> User:
    return _transition(db, admin_id, user_id, "enable", now=now)


def issue_temporary_password(db: Path, admin_id: int, user_id: int, *,
                             now: datetime | None = None) -> str:
    """A new temporary password for an approved account, returned once for the admin to
    pass on. It is stored only as a hash, never in the audit trail; the account must
    choose its own at its next login; issuing one also clears a lockout."""
    moment = _now(now)
    temporary = passwords.temporary_password()
    with store.connect(db) as conn:
        admin = _acting_admin(conn, admin_id)
        target = _target(conn, admin, user_id)
        if target.state != "approved":
            raise AccountError(f"This account is {target.state}; "
                               "only approved accounts get a temporary password.")
        store.update_user(conn, target.id, password_hash=passwords.hash_password(temporary),
                          must_change_password=True, failed_logins=0, locked_until=None)
        store.record_action(conn, admin_id=admin.id, action="temporary_password",
                            target_user_id=target.id,
                            detail="must choose a new password at the next login", now=moment)
    return temporary


def change_password(db: Path, user_id: int, password: str, confirm: str) -> None:
    """Set the account's own new password. It may not be the one it has now -- a
    temporary password is known to the admin who issued it."""
    _checked_password(password, confirm)
    with store.connect(db) as conn:
        user = store.user_by_id(conn, user_id)
        current = store.password_hash(conn, user_id)
        if user is None or current is None or user.state != "approved":
            raise AccountError("This account cannot change its password.")
        if passwords.verify(current, password):
            raise AccountError("Choose a password different from the one you have now.",
                               "password")
        store.update_user(conn, user_id, password_hash=passwords.hash_password(password),
                          must_change_password=False)


def create_admin(db: Path, *, email: str, name: str, organisation: str, password: str,
                 confirm: str, now: datetime | None = None) -> User:
    """An approved admin, made on the server's command line: the first admin has nobody
    to approve it."""
    moment = _now(now)
    clean_email = _checked_email(email)
    clean_name, clean_org = _checked_text(name, "name"), _checked_text(organisation, "organisation")
    _checked_password(password, confirm)
    hashed = passwords.hash_password(password)
    with store.connect(db) as conn:
        try:
            user_id = store.insert_user(conn, email=clean_email, name=clean_name,
                                        organisation=clean_org, password_hash=hashed,
                                        state="approved", role="admin", now=moment,
                                        approved_at=moment)
        except sqlite3.IntegrityError as exc:
            if not _is_duplicate_email(exc):
                raise
            raise AccountError("An account with this email already exists.", "email") from None
        store.record_action(conn, admin_id=user_id, action="create_admin",
                            target_user_id=user_id, detail="created from the command line",
                            now=moment)
        return store.user_by_id(conn, user_id)
```

- [ ] **Step 4: Run the tests**

Run: `perl -e 'alarm shift; exec @ARGV' 900 uv run pytest tests/test_accounts_service.py tests/test_accounts_store.py tests/test_accounts_passwords.py tests/test_independence.py -x`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add app/accounts/service.py tests/test_accounts_service.py
git commit -m "feat(accounts): sign-up, login with lockout, admin approvals and temporary passwords"
```

---

### Task 4: `solit2 accounts create-admin`

**Files:**
- Modify: `solit2/cli.py` (imports at the top; one command function before `build_parser`; one parser block before `return parser`)
- Modify: `README.md` (a new `## Accounts` section right before `## Development`)
- Test: `tests/test_cli_accounts.py`

**Interfaces:**
- Consumes: `store.db_path`, `store.init`, `store.DATA_DIR_ENV`, `service.create_admin`, `service.AccountError` (`.field`).
- Produces: `solit2 accounts create-admin --email E --name N --organisation O`, exit `EXIT_OK` (0) with stdout JSON `{"created": "admin", "id", "email", "store"}`; `EXIT_BAD_INPUT` (2) for a refused value; `EXIT_ENGINE` (3) for an unavailable store; errors on stderr through the existing `_fail`.

- [ ] **Step 1: Write the failing test** — `tests/test_cli_accounts.py`

```python
"""`solit2 accounts create-admin`: the first admin, made on the server's command line."""
import json

import pytest

from app.accounts import service, store
from solit2 import cli

PASSWORD = "a long enough password"
ARGS = ["accounts", "create-admin", "--email", "Admin@Example.test", "--name", "Ada",
        "--organisation", "Ops"]


def _answers(monkeypatch, *replies):
    queue = iter(replies)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": next(queue))


def test_create_admin_asks_twice_and_makes_an_approved_admin(monkeypatch, capsys):
    _answers(monkeypatch, PASSWORD, PASSWORD)
    assert cli.main(ARGS) == cli.EXIT_OK
    out, err = capsys.readouterr()
    assert json.loads(out)["email"] == "admin@example.test"
    assert PASSWORD not in out + err
    result = service.log_in(store.db_path(), "admin@example.test", PASSWORD)
    assert (result.status, result.user.role) == ("ok", "admin")


@pytest.mark.parametrize("first, second, message", [
    (PASSWORD, PASSWORD + "x", "The two passwords do not match."),
    ("short", "short", "The password must be at least 12 characters."),
])
def test_a_refused_password_is_a_clean_error_and_creates_nothing(monkeypatch, capsys, first,
                                                                  second, message):
    _answers(monkeypatch, first, second)
    assert cli.main(ARGS) == cli.EXIT_BAD_INPUT
    error = json.loads(capsys.readouterr().err)
    assert (error["error"], error["field"]) == (message, "password")
    assert service.list_users(store.db_path()) == []


def test_an_email_already_registered_is_refused(monkeypatch, capsys):
    _answers(monkeypatch, PASSWORD, PASSWORD, PASSWORD, PASSWORD)
    assert cli.main(ARGS) == cli.EXIT_OK
    capsys.readouterr()
    assert cli.main(ARGS) == cli.EXIT_BAD_INPUT
    assert "already exists" in json.loads(capsys.readouterr().err)["error"]


def test_the_password_is_never_an_argument():
    with pytest.raises(SystemExit):
        cli.main([*ARGS, "--password", PASSWORD])


def test_an_unavailable_store_is_reported_before_any_password_is_asked(monkeypatch, capsys,
                                                                       tmp_path):
    blocker = tmp_path / "a-file"
    blocker.write_text("not a directory")
    monkeypatch.setenv(store.DATA_DIR_ENV, str(blocker))
    _answers(monkeypatch)  # no replies: asking for a password would raise StopIteration
    assert cli.main(ARGS) == cli.EXIT_ENGINE
    assert "unavailable" in json.loads(capsys.readouterr().err)["error"]
```

- [ ] **Step 2: Run it to see it fail**

Run: `perl -e 'alarm shift; exec @ARGV' 900 uv run pytest tests/test_cli_accounts.py -x`
Expected: FAIL — `AttributeError: module 'solit2.cli' has no attribute 'getpass'`

- [ ] **Step 3: Write the implementation** — in `solit2/cli.py`:

Add `import getpass` and `import sqlite3` to the standard-library imports, keeping them alphabetical (`argparse`, `getpass`, `json`, `sqlite3`, `sys`, `time`).

Add this function right before `def build_parser()`:

```python
def _cmd_accounts_create_admin(args: argparse.Namespace) -> int:
    # The account code belongs to the app it guards; only this command needs it, so it
    # is imported here and no other command depends on the app package.
    from app.accounts import service, store

    db = store.db_path()
    try:
        store.init(db)
        password = getpass.getpass("Password: ")
        confirm = getpass.getpass("Password again: ")
        admin = service.create_admin(db, email=args.email, name=args.name,
                                     organisation=args.organisation, password=password,
                                     confirm=confirm)
    except service.AccountError as exc:
        return _fail(str(exc), exc.field, "correct it and run the command again", EXIT_BAD_INPUT)
    except (sqlite3.Error, OSError) as exc:
        return _fail(f"the account store at {db} is unavailable: {exc}", store.DATA_DIR_ENV,
                     "point SOLIT2_DATA_DIR at a directory this user can write", EXIT_ENGINE)
    json.dump({"created": "admin", "id": admin.id, "email": admin.email, "store": str(db)},
              sys.stdout)
    sys.stdout.write("\n")
    return EXIT_OK
```

Add this block in `build_parser()` right before `return parser`:

```python
    accounts = sub.add_parser("accounts", help="manage the app's user accounts")
    accounts_sub = accounts.add_subparsers(dest="accounts_command", required=True)
    acreate = accounts_sub.add_parser(
        "create-admin",
        help="create an approved admin account; asks for the password twice, "
             "never takes it as an argument")
    acreate.add_argument("--email", required=True)
    acreate.add_argument("--name", required=True)
    acreate.add_argument("--organisation", required=True)
    acreate.set_defaults(func=_cmd_accounts_create_admin)
```

- [ ] **Step 4: Document it** — insert this section in `README.md` right before the line `## Development`:

```markdown
## Accounts

The app asks everyone to log in, and an admin approves every new account as **team** (the
shared project: designs, runs, the CFD runs manager) or **customer**. Customers see a holding
screen until customer workspaces open.

Create the first admin on the server, from the app's checkout and with the same
`SOLIT2_DATA_DIR` the app's service uses. It asks for the password twice; the password is
never an argument:

    SOLIT2_DATA_DIR=/path/to/app-data uv run solit2 accounts create-admin \
        --email you@example.com --name "Your Name" --organisation "Your organisation"

Accounts live in one SQLite file, `$SOLIT2_DATA_DIR/accounts.db` (default `data/accounts.db`,
never committed), readable by its owner only. Back it up with
`sqlite3 "$SOLIT2_DATA_DIR/accounts.db" ".backup accounts-backup.db"`.

A forgotten password is reset by an admin, who issues a temporary one; the account must choose
its own at its next login. An admin who forgets their own asks another admin, or makes a second
admin with the command above.

The server keeps its IP allowlist in front of the app until a security review of the accounts
has passed.
```

- [ ] **Step 5: Run the tests**

Run: `perl -e 'alarm shift; exec @ARGV' 900 uv run pytest tests/test_cli_accounts.py tests/test_cli.py tests/test_independence.py -x`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add solit2/cli.py tests/test_cli_accounts.py README.md
git commit -m "feat(cli): solit2 accounts create-admin"
```

---

### Task 5: The signed-in session, and timed fragments that respect it

**Files:**
- Create: `app/auth.py`
- Modify: `app/views/simulator.py` (`_cfd_panel`), `app/views/runs.py` (`_live_panel`), `app/views/cfd.py` (`_live_statistics`, `_live_progress`)
- Modify: `tests/conftest.py` (account helpers; `run_view` signs in)
- Modify: `tests/test_app_nav.py`, `tests/test_app_wizard.py`, `tests/test_app_compliance_step.py`, `tests/test_app_simulator.py`, `tests/test_app_runs_step.py` (sign in every whole-app AppTest)
- Test: `tests/test_app_session.py`

**Interfaces:**
- Consumes: `service.get_user`, `store.db_path`, `store.User`, and (tests) `store.init/connect/insert_user/user_by_id/list_users/update_user`, `passwords.hash_password`.
- Produces:
  - `auth.USER_ID_KEY = "auth_user_id"`, `auth.LAST_SEEN_KEY = "auth_last_seen"`, `auth.NOTICE_KEY = "auth_notice"`, `auth.IDLE_TIMEOUT_S = 28800`, `auth.IDLE_NOTICE`, `auth.NO_ACCESS_NOTICE`, `auth.LOGGED_OUT_NOTICE`;
  - `auth.sign_in(user: User) -> None`, `auth.sign_out(notice: str | None = None) -> None`, `auth.current_user(*, touch: bool) -> User | None`, `auth.guard_fragment() -> None`;
  - tests: `tests.conftest.TEST_PASSWORD`, `make_account(role="team", state="approved", email=None, must_change_password=False) -> User`, `sign_in(at, role="team", email=None) -> User`.

Why the migration is in this task: from now on a timed fragment shows nothing for a session nobody signed in to, so every test that renders a whole view must sign its session in — as a login will once Task 6 adds the gate.

- [ ] **Step 1: Write the failing test** — `tests/test_app_session.py`

```python
"""The signed-in session: who it is, when it ends, and timed fragments that respect it."""
import time

from streamlit.testing.v1 import AppTest

from app import auth
from app.accounts import store
from tests.conftest import sign_in

WHO = ("import streamlit as st\n"
       "from app import auth\n"
       "user = auth.current_user(touch=True)\n"
       "st.write(f'user {user.email if user else None}')\n")

GUARDED = ("import streamlit as st\n"
           "from app import auth\n"
           "st.write('page')\n"
           "@st.fragment\n"
           "def panel():\n"
           "    auth.guard_fragment()\n"
           "    st.write('panel')\n"
           "panel()\n")

SIGN_OUT = ("import streamlit as st\n"
            "from app import auth\n"
            "st.session_state['left_over'] = 'anything the session held'\n"
            "if st.button('out', key='out'):\n"
            "    auth.sign_out(auth.LOGGED_OUT_NOTICE)\n")


def _written(at: AppTest) -> list[str]:
    return [m.value for m in at.markdown]


def test_a_fresh_session_has_nobody_signed_in():
    at = AppTest.from_string(WHO)
    at.run()
    assert _written(at) == ["user None"]


def test_a_signed_in_session_is_its_account_and_a_full_run_is_activity():
    at = AppTest.from_string(WHO)
    user = sign_in(at)
    at.session_state[auth.LAST_SEEN_KEY] = time.time() - 600
    at.run()
    assert _written(at) == [f"user {user.email}"]
    assert time.time() - at.session_state[auth.LAST_SEEN_KEY] < 60


def test_a_session_idle_past_the_limit_ends_says_why_and_keeps_nothing():
    at = AppTest.from_string(WHO)
    sign_in(at)
    at.session_state["left_over"] = "anything the session held"
    at.session_state[auth.LAST_SEEN_KEY] = time.time() - auth.IDLE_TIMEOUT_S - 1
    at.run()
    assert _written(at) == ["user None"]
    assert at.session_state[auth.NOTICE_KEY] == auth.IDLE_NOTICE
    assert "left_over" not in at.session_state and auth.USER_ID_KEY not in at.session_state


def test_a_session_just_inside_the_idle_limit_continues():
    at = AppTest.from_string(WHO)
    user = sign_in(at)
    at.session_state[auth.LAST_SEEN_KEY] = time.time() - auth.IDLE_TIMEOUT_S + 60
    at.run()
    assert _written(at) == [f"user {user.email}"]


def test_an_account_no_longer_approved_ends_its_session():
    at = AppTest.from_string(WHO)
    user = sign_in(at)
    with store.connect(store.db_path()) as conn:
        store.update_user(conn, user.id, state="disabled")
    at.run()
    assert _written(at) == ["user None"]
    assert at.session_state[auth.NOTICE_KEY] == auth.NO_ACCESS_NOTICE


def test_sign_out_keeps_only_its_notice():
    at = AppTest.from_string(SIGN_OUT)
    sign_in(at)
    at.run()
    at.button(key="out").click().run()
    assert at.session_state[auth.NOTICE_KEY] == auth.LOGGED_OUT_NOTICE
    assert "left_over" not in at.session_state and auth.USER_ID_KEY not in at.session_state


def test_a_timed_fragment_renders_for_a_live_session():
    at = AppTest.from_string(GUARDED)
    sign_in(at)
    at.run()
    assert _written(at) == ["page", "panel"]


def test_a_timed_fragment_is_not_activity():
    at = AppTest.from_string(GUARDED)
    sign_in(at)
    seen = time.time() - 600
    at.session_state[auth.LAST_SEEN_KEY] = seen
    at.run()
    assert at.session_state[auth.LAST_SEEN_KEY] == seen


def test_a_timed_fragment_of_an_ended_session_shows_nothing_and_ends_it():
    at = AppTest.from_string(GUARDED)
    sign_in(at)
    at.session_state[auth.LAST_SEEN_KEY] = time.time() - auth.IDLE_TIMEOUT_S - 1
    at.run()
    assert not at.exception
    assert "panel" not in _written(at)
    assert auth.USER_ID_KEY not in at.session_state


def test_a_timed_fragment_with_no_session_shows_nothing():
    at = AppTest.from_string(GUARDED)
    at.run()
    assert not at.exception
    assert _written(at) == ["page"]
```

- [ ] **Step 2: Run it to see it fail**

Run: `perl -e 'alarm shift; exec @ARGV' 900 uv run pytest tests/test_app_session.py -x`
Expected: FAIL — `ImportError: cannot import name 'sign_in' from 'tests.conftest'`

- [ ] **Step 3: Write `app/auth.py`**

```python
"""Who is signed in to this browser session, and when that ends.

The account id lives in `st.session_state` only, never in a URL or a cookie, so a browser
refresh starts a new session and asks for the login again (the accounts spec's stated
trade-off; the upgrade path is a small login gateway in front of the app). Every check
re-reads the account from the store, so an account an admin disables loses access at its
next interaction, and a session left idle for IDLE_TIMEOUT_S ends.
"""
from __future__ import annotations

import time

import streamlit as st

from app.accounts import service, store
from app.accounts.store import User

USER_ID_KEY = "auth_user_id"
LAST_SEEN_KEY = "auth_last_seen"
NOTICE_KEY = "auth_notice"
IDLE_TIMEOUT_S = 8 * 60 * 60
IDLE_NOTICE = (f"Your session ended after {IDLE_TIMEOUT_S // 3600} hours without activity. "
               "Log in again.")
NO_ACCESS_NOTICE = "This account no longer has access. Contact the administrator."
LOGGED_OUT_NOTICE = "You are logged out."


def sign_in(user: User) -> None:
    st.session_state[USER_ID_KEY] = user.id
    st.session_state[LAST_SEEN_KEY] = time.time()


def sign_out(notice: str | None = None) -> None:
    """End the session and drop everything it held -- designs, results, choices -- so
    whoever signs in next on this tab starts from nothing."""
    st.session_state.clear()
    if notice:
        st.session_state[NOTICE_KEY] = notice


def current_user(*, touch: bool) -> User | None:
    """The approved account signed in to this session, or None.

    Ends the session when it has been idle longer than IDLE_TIMEOUT_S or its account is
    no longer approved. `touch` counts this run as activity: a full run of the app does,
    a fragment's timed refresh does not.
    """
    user_id = st.session_state.get(USER_ID_KEY)
    if user_id is None:
        return None
    now = time.time()
    if now - st.session_state.get(LAST_SEEN_KEY, 0.0) > IDLE_TIMEOUT_S:
        sign_out(IDLE_NOTICE)
        return None
    user = service.get_user(store.db_path(), user_id)
    if user is None or user.state != "approved":
        sign_out(NO_ACCESS_NOTICE)
        return None
    if touch:
        st.session_state[LAST_SEEN_KEY] = now
    return user


def guard_fragment() -> None:
    """The first line of every timed fragment. A timed refresh does not pass through the
    login gate and is not activity, yet it must not keep showing data to a session that
    has ended: a session that just ended reruns the whole app, which shows the login, and
    a run with no session at all shows nothing."""
    had_session = st.session_state.get(USER_ID_KEY) is not None
    if current_user(touch=False) is None:
        if had_session:
            st.rerun()
        st.stop()
```

- [ ] **Step 4: Guard the four timed fragments** — add `auth` to each file's imports and make `auth.guard_fragment()` the first statement of each fragment (after its docstring, where it has one):

`app/views/simulator.py` — imports: `from app import auth, plot_theme, state`

```python
@st.fragment(run_every=cfd_live.REFRESH_S)
def _cfd_panel(design: Design) -> None:
    auth.guard_fragment()
    st.markdown('<div class="sim-label">CFD · LIVE</div>', unsafe_allow_html=True)
```

`app/views/runs.py` — imports: add `from app import auth` on the line before `from app.components import run_states`

```python
@st.fragment(run_every=POLL)
def _live_panel(state_dir: Path, roots: tuple[Path, ...]) -> None:
    auth.guard_fragment()
    infos = fleet.list_runs(roots=roots, state_dir=state_dir)
```

`app/views/cfd.py` — imports: `from app import auth, palette, plot_theme, state`

```python
@st.fragment(run_every=POLL)
def _live_statistics(run_dir: Path, trace: RunTrace) -> None:
    """Charts polled from the run's own CSVs while it works.

    Separate from the progress metrics and on its own fragment clock, because
    these read whole files rather than their last line and there is no reason
    to make the progress figures wait on that.
    """
    auth.guard_fragment()
    hrr = fds_runner.series(run_dir, "_hrr.csv", HRR_COLUMNS)
```

```python
@st.fragment(run_every=POLL)
def _live_progress(run_dir: Path) -> None:
    auth.guard_fragment()
    status = fds_runner.status(run_dir)
```

Check: `grep -n -A3 "@st.fragment" app/views/*.py` shows `auth.guard_fragment()` in all four.

- [ ] **Step 5: Account helpers in `tests/conftest.py`** — the whole file becomes:

```python
"""Shared AppTest scaffolding: render one view the way the shell does (theme +
optional seeded design), without the stepper so buttons are addressed by key only;
and the accounts every app test needs now that the app has a login."""
import time
from datetime import UTC, datetime
from functools import cache

import pytest
from streamlit.testing.v1 import AppTest

from app import auth
from app.accounts import passwords, store

EXAMPLE_DESIGN = "examples/designs/road-tunnel-twin-bore.json"
TEST_PASSWORD = "a test password, long enough"


@pytest.fixture(autouse=True)
def _account_store_per_test(tmp_path_factory, monkeypatch):
    """Every test gets its own empty account store; no test touches data/accounts.db."""
    monkeypatch.setenv(store.DATA_DIR_ENV, str(tmp_path_factory.mktemp("accounts")))


@cache
def _test_hash() -> str:
    return passwords.hash_password(TEST_PASSWORD)


def make_account(role: str | None = "team", state: str = "approved", email: str | None = None,
                 must_change_password: bool = False) -> store.User:
    """An account in this test's own store, whose password is TEST_PASSWORD. Without an
    email it gets one numbered by how many accounts the store already holds."""
    db = store.db_path()
    store.init(db)
    now = datetime.now(UTC)
    with store.connect(db) as conn:
        address = email or f"{role or state}-{len(store.list_users(conn))}@example.test"
        user_id = store.insert_user(
            conn, email=address, name=f"Test {role or state}", organisation="Test organisation",
            password_hash=_test_hash(), state=state, role=role,
            must_change_password=must_change_password, now=now,
            approved_at=now if state in ("approved", "disabled") else None)
        return store.user_by_id(conn, user_id)


def sign_in(at: AppTest, role: str = "team", email: str | None = None) -> store.User:
    """Make an approved `role` account and sign `at`'s session in as it, as a login does."""
    user = make_account(role=role, email=email)
    at.session_state[auth.USER_ID_KEY] = user.id
    at.session_state[auth.LAST_SEEN_KEY] = time.time()
    return user


def view_script(view: str, seed_design: bool) -> str:
    seed = (f'if state.get_design() is None:\n'
            f'    state.set_design(Design.load("{EXAMPLE_DESIGN}"))\n') if seed_design else ""
    return ("import streamlit as st\n"
            "from app import state, theme\n"
            f"from app.views import {view} as view\n"
            "from solit2.schema.design import Design\n"
            "theme.inject()\n"
            f"{seed}"
            "view.render()\n")


@pytest.fixture
def run_view():
    def _run(view: str, seed_design: bool = True, timeout: float = 90.0) -> AppTest:
        at = AppTest.from_string(view_script(view, seed_design), default_timeout=timeout)
        sign_in(at)
        at.run()
        return at
    return _run
```

- [ ] **Step 6: Sign in every whole-app AppTest** — in each of the five files below, add `from tests.conftest import sign_in` to the imports and put `sign_in(at)` on the line right after **every** `at = AppTest.from_file(APP, default_timeout=180)`:

| File | Sites |
|---|---|
| `tests/test_app_nav.py` | `_app` |
| `tests/test_app_wizard.py` | `_app` |
| `tests/test_app_compliance_step.py` | `test_the_step_shows_the_headline_and_the_blockers` |
| `tests/test_app_simulator.py` | `_app`; `test_judged_elsewhere_is_absent_when_the_envelope_has_only_one_case`; the test that builds `wide` (velocity range 9.0–10.5) |
| `tests/test_app_runs_step.py` | `_app`; `test_the_nav_switches_to_the_manager_and_back_to_the_wizard`; `test_switching_to_the_manager_keeps_the_current_wizard_step` |

For example, `tests/test_app_nav.py`'s helper becomes:

```python
def _app(monkeypatch, tmp_path) -> AppTest:
    monkeypatch.setattr(history, "DEFAULT_PATH", tmp_path / "h.jsonl")
    monkeypatch.setattr(cfd, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setenv("SOLIT2_RUN_ROOTS", str(tmp_path / "runs"))
    monkeypatch.setenv("SOLIT2_CFD_STATE_DIR", str(tmp_path / "state"))
    at = AppTest.from_file(APP, default_timeout=180)
    sign_in(at)
    at.run()
    return at
```

Check: `grep -n -A1 "AppTest.from_file" tests/test_app_*.py` — every match is followed by `sign_in(at)`; there are nine.

- [ ] **Step 7: Run the tests**

Run: `perl -e 'alarm shift; exec @ARGV' 900 uv run pytest tests/test_app_session.py -x`
Expected: PASS. Then the full suite (command in Global Constraints). Expected: every test passes. A test that renders a timed fragment and now fails because the fragment shows nothing is a test that renders a view without a session: sign its AppTest in with `sign_in(at)` the same way — never weaken the guard.

- [ ] **Step 8: Commit**

```bash
git add app/auth.py app/views/simulator.py app/views/runs.py app/views/cfd.py tests/conftest.py tests/test_app_session.py tests/test_app_nav.py tests/test_app_wizard.py tests/test_app_compliance_step.py tests/test_app_simulator.py tests/test_app_runs_step.py
git commit -m "feat(app): the signed-in session, and timed fragments that respect it"
```

---

### Task 6: The login gate — log in, sign up, the forced password change

**Files:**
- Create: `app/components/local_time.py`, `app/views/login.py`
- Modify: `app/state.py` (role-aware screens), `app/components/nav.py` (the account's email and Log out), `app/streamlit_app.py` (the gate and the dispatch)
- Modify: `tests/conftest.py` (add `screen_text`), `tests/test_app_nav.py` (one test), `README.md` ("Running the app")
- Test: `tests/test_app_login.py`

**Interfaces:**
- Consumes: `auth.*` (Task 5), `service.sign_up/log_in/change_password/AccountError/EMAIL_MAX_CHARS/NAME_MAX_CHARS/MAX_FAILED_LOGINS` (Task 3), `passwords.MIN_CHARS/MAX_CHARS` (Task 1), `store.db_path/init/DATA_DIR_ENV/DB_NAME` (Task 2).
- Produces:
  - `local_time(moment: datetime | None, fmt: str = DATE_TIME) -> str` with `DATE_TIME = "%Y-%m-%d %H:%M %Z"`, `CLOCK = "%H:%M %Z"`;
  - `login.gate() -> User`, `login.render_workspace_pending() -> None`; messages `login.STORE_UNAVAILABLE`, `SIGNED_UP`, `NO_ACCESS`, `WRONG`, `PENDING`, `WORKSPACE_PENDING`; widget keys `login_email`, `login_password`, `login_submit`, `signup_name`, `signup_org`, `signup_email`, `signup_password`, `signup_confirm`, `signup_submit`, `change_password`, `change_confirm`, `change_submit`, `change_logout`;
  - `state.ROLE_VIEWS`, `state.views_for(role: str | None) -> tuple[str, ...]`, `state.current_view(role: str | None) -> str | None`;
  - `nav.render(user: User) -> None` with the `nav_logout` button;
  - tests: `tests.conftest.screen_text(at) -> str`.

- [ ] **Step 1: Write the failing test** — `tests/test_app_login.py`

```python
"""The login gate, headless: a visitor sees only the login and the sign-up, an approved
account sees the app, and a temporary password is replaced before anything else.

The tests land on the CFD runs manager (empty run roots) only because it renders
fastest; the gate in front of it is the subject."""
import time

import pytest
from streamlit.testing.v1 import AppTest

from app import auth
from app.accounts import service, store
from app.components import nav
from app.views import cfd, login, runs, simulator
from solit2 import history
from tests.conftest import TEST_PASSWORD, make_account, screen_text, sign_in

APP = "../app/streamlit_app.py"
NEW_PASSWORD = "another long password"


def _app(monkeypatch, tmp_path, view: str = "runs") -> AppTest:
    monkeypatch.setattr(history, "DEFAULT_PATH", tmp_path / "h.jsonl")
    monkeypatch.setattr(cfd, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setenv("SOLIT2_RUN_ROOTS", str(tmp_path / "runs"))
    monkeypatch.setenv("SOLIT2_CFD_STATE_DIR", str(tmp_path / "state"))
    at = AppTest.from_file(APP, default_timeout=180)
    at.session_state["view"] = view
    return at


def _keys(at: AppTest) -> set[str]:
    return {b.key for b in at.button}


def _nav(at: AppTest) -> set[str]:
    return {k for k in _keys(at) if k.startswith("nav_")}


def _log_in(at: AppTest, email: str, password: str) -> AppTest:
    at.text_input(key="login_email").input(email)
    at.text_input(key="login_password").input(password)
    at.button(key="login_submit").click().run()
    return at


def _sign_up(at: AppTest, email: str, password: str, confirm: str, name: str = "Ada") -> AppTest:
    at.text_input(key="signup_name").input(name)
    at.text_input(key="signup_org").input("Analytical Engines")
    at.text_input(key="signup_email").input(email)
    at.text_input(key="signup_password").input(password)
    at.text_input(key="signup_confirm").input(confirm)
    at.button(key="signup_submit").click().run()
    return at


def _change(at: AppTest, password: str, confirm: str) -> AppTest:
    at.text_input(key="change_password").input(password)
    at.text_input(key="change_confirm").input(confirm)
    at.button(key="change_submit").click().run()
    return at


def test_a_visitor_sees_only_the_login_and_the_sign_up(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    at.run()
    assert not at.exception
    assert {"login_submit", "signup_submit"} <= _keys(at)
    assert not _nav(at)
    assert not any("CFD runs" in h.value for h in at.header)


def test_nothing_below_the_gate_runs_for_a_visitor(monkeypatch, tmp_path):
    def rendered(*_args, **_kwargs):
        raise AssertionError("rendered for a visitor")
    for module, name in ((nav, "render"), (simulator, "render"), (runs, "render"),
                         (login, "render_workspace_pending")):
        monkeypatch.setattr(module, name, rendered)
    at = _app(monkeypatch, tmp_path)
    at.run()
    assert not at.exception
    assert "login_submit" in _keys(at)


def test_a_sign_up_waits_for_approval_and_says_so(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    at.run()
    _sign_up(at, "Ada@Example.test", TEST_PASSWORD, TEST_PASSWORD)
    assert not at.exception
    assert [s.value for s in at.success] == [login.SIGNED_UP]
    [user] = service.list_users(store.db_path())
    assert (user.email, user.state, user.role) == ("ada@example.test", "pending", None)


def test_signing_up_a_registered_email_gets_the_same_message_and_changes_nothing(monkeypatch,
                                                                                 tmp_path):
    make_account(role="team", email="ada@example.test")
    at = _app(monkeypatch, tmp_path)
    at.run()
    _sign_up(at, "ada@example.test", NEW_PASSWORD, NEW_PASSWORD, name="Someone Else")
    assert [s.value for s in at.success] == [login.SIGNED_UP]
    [user] = service.list_users(store.db_path())
    assert (user.name, user.state) == ("Test team", "approved")


def test_a_refused_sign_up_says_why_and_stores_nothing(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    at.run()
    _sign_up(at, "ada@example.test", TEST_PASSWORD, TEST_PASSWORD + "x")
    assert [e.value for e in at.error] == ["The two passwords do not match."]
    assert service.list_users(store.db_path()) == []


def test_a_pending_account_sees_only_the_wait_message(monkeypatch, tmp_path):
    make_account(role=None, state="pending", email="p@example.test")
    at = _app(monkeypatch, tmp_path)
    at.run()
    _log_in(at, "p@example.test", TEST_PASSWORD)
    assert [w.value for w in at.warning] == [login.PENDING]
    assert not _nav(at)
    assert auth.USER_ID_KEY not in at.session_state


@pytest.mark.parametrize("role, state", [(None, "rejected"), ("team", "disabled")])
def test_rejected_and_disabled_accounts_have_no_access(monkeypatch, tmp_path, role, state):
    make_account(role=role, state=state, email="x@example.test")
    at = _app(monkeypatch, tmp_path)
    at.run()
    _log_in(at, "x@example.test", TEST_PASSWORD)
    assert [e.value for e in at.error] == [login.NO_ACCESS]
    assert not _nav(at)


def test_a_wrong_password_and_an_unknown_email_get_the_same_message(monkeypatch, tmp_path):
    make_account(role="team", email="t@example.test")
    at = _app(monkeypatch, tmp_path)
    at.run()
    _log_in(at, "t@example.test", "a wrong password!")
    assert [e.value for e in at.error] == [login.WRONG]
    _log_in(at, "nobody@example.test", TEST_PASSWORD)
    assert [e.value for e in at.error] == [login.WRONG]


def test_a_locked_account_is_told_when_to_try_again(monkeypatch, tmp_path):
    make_account(role="team", email="t@example.test")
    for _ in range(service.MAX_FAILED_LOGINS):
        service.log_in(store.db_path(), "t@example.test", "a wrong password!")
    at = _app(monkeypatch, tmp_path)
    at.run()
    _log_in(at, "t@example.test", TEST_PASSWORD)
    [message] = [e.value for e in at.error]
    assert message.startswith("Too many failed attempts. Try again after ")
    assert not _nav(at)


def test_an_approved_login_opens_the_app(monkeypatch, tmp_path):
    make_account(role="team", email="t@example.test")
    at = _app(monkeypatch, tmp_path)
    at.run()
    _log_in(at, " T@Example.test ", TEST_PASSWORD)
    assert not at.exception
    assert {"nav_simulator", "nav_wizard", "nav_runs", "nav_logout"} <= _keys(at)
    assert "Signed in as t@example.test" in [c.value for c in at.caption]
    assert any("CFD runs" in h.value for h in at.header)


def test_log_out_ends_the_session_and_drops_its_state(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    sign_in(at)
    at.session_state["left_over"] = "anything the session held"
    at.run()
    at.button(key="nav_logout").click().run()
    assert not at.exception
    assert "login_submit" in _keys(at)
    assert auth.LOGGED_OUT_NOTICE in [i.value for i in at.info]
    assert "left_over" not in at.session_state and auth.USER_ID_KEY not in at.session_state


def test_an_idle_session_meets_the_login_with_the_reason(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    sign_in(at)
    at.session_state[auth.LAST_SEEN_KEY] = time.time() - auth.IDLE_TIMEOUT_S - 1
    at.run()
    assert "login_submit" in _keys(at)
    assert auth.IDLE_NOTICE in [i.value for i in at.info]


def test_a_temporary_password_is_replaced_before_anything_else(monkeypatch, tmp_path):
    make_account(role="team", email="t@example.test", must_change_password=True)
    at = _app(monkeypatch, tmp_path)
    at.run()
    _log_in(at, "t@example.test", TEST_PASSWORD)
    assert "change_submit" in _keys(at)
    assert not _nav(at)
    _change(at, TEST_PASSWORD, TEST_PASSWORD)
    assert [e.value for e in at.error] == [
        "Choose a password different from the one you have now."]
    _change(at, NEW_PASSWORD, NEW_PASSWORD)
    assert not at.exception
    assert "nav_runs" in _keys(at)
    result = service.log_in(store.db_path(), "t@example.test", NEW_PASSWORD)
    assert result.user.must_change_password is False


def test_an_unreadable_store_shows_that_and_nothing_else(monkeypatch, tmp_path):
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / store.DB_NAME).write_text("this is not a database")
    monkeypatch.setenv(store.DATA_DIR_ENV, str(broken))
    at = _app(monkeypatch, tmp_path)
    at.run()
    assert not at.exception
    assert [e.value for e in at.error] == [login.STORE_UNAVAILABLE]
    assert not _keys(at)


def test_a_customer_sees_the_holding_screen_and_no_project_screen(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)  # asks for the runs manager, which a customer may not open
    sign_in(at, role="customer")
    at.run()
    assert not at.exception
    assert [i.value for i in at.info] == [login.WORKSPACE_PENDING]
    assert _nav(at) == {"nav_logout"}
    assert not any("CFD runs" in h.value for h in at.header)


def test_no_password_or_hash_reaches_the_screen(monkeypatch, tmp_path):
    make_account(role="team", email="t@example.test")
    at = _app(monkeypatch, tmp_path)
    at.run()
    _log_in(at, "t@example.test", "a wrong password!")
    assert "a wrong password!" not in screen_text(at)
    _log_in(at, "t@example.test", TEST_PASSWORD)
    text = screen_text(at)
    assert TEST_PASSWORD not in text and "$argon2" not in text
```

Add to `tests/test_app_nav.py`:

```python
def test_a_role_lands_only_on_a_screen_it_may_open():
    script = ("import streamlit as st\nfrom app import state\n"
              "st.write(' '.join(f'{r}={state.current_view(r)}' "
              "for r in ('admin', 'team', 'customer', None)))\n")
    at = AppTest.from_string(script)
    at.session_state["view"] = "wizard"
    at.run()
    assert at.markdown[0].value == "admin=wizard team=wizard customer=None None=None"
```

Add to `tests/conftest.py`, after `sign_in`:

```python
SCREEN_ELEMENTS = ("title", "header", "subheader", "markdown", "caption", "text", "code",
                   "error", "warning", "info", "success")


def screen_text(at: AppTest) -> str:
    """Everything an AppTest's page shows as text, tables included."""
    parts = [str(element.value) for kind in SCREEN_ELEMENTS for element in getattr(at, kind)]
    parts += [table.value.to_csv() for table in at.dataframe]
    return "\n".join(parts)
```

- [ ] **Step 2: Run it to see it fail**

Run: `perl -e 'alarm shift; exec @ARGV' 900 uv run pytest tests/test_app_login.py -x`
Expected: FAIL — `ImportError: cannot import name 'login' from 'app.views'`

- [ ] **Step 3: Write `app/components/local_time.py`**

```python
"""Times as the server's clock shows them, with the zone named."""
from __future__ import annotations

from datetime import datetime

DATE_TIME = "%Y-%m-%d %H:%M %Z"
CLOCK = "%H:%M %Z"


def local_time(moment: datetime | None, fmt: str = DATE_TIME) -> str:
    return "—" if moment is None else moment.astimezone().strftime(fmt)
```

- [ ] **Step 4: Write `app/views/login.py`**

```python
"""The login gate and the screens in front of the app: log in, sign up, the forced
password change, and a customer's holding screen.

`gate()` runs at the top of the app, after the page setup and the theme's CSS. It
returns only for an approved, signed-in account; for anyone else it renders one of
these screens and stops the run, so nothing below it runs.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import streamlit as st

from app import auth
from app.accounts import passwords, service, store
from app.accounts.store import User
from app.components.local_time import CLOCK, local_time

# The screens sit in the middle column of three.
CARD_COLUMNS = (1, 1.3, 1)
STORE_UNAVAILABLE = ("The account store is unavailable, so nobody can log in right now. "
                     "Tell the administrator.")
SIGNED_UP = ("Thank you. Your sign-up waits for an administrator's approval; "
             "you can log in once it is approved.")
NO_ACCESS = "This account has no access. Contact the administrator."
WRONG = "The email or password is wrong."
PENDING = "Your account is waiting for approval by an administrator."
WORKSPACE_PENDING = ("Your account is approved. Customer workspaces, where your own designs "
                     "and runs will live, are not open yet; the administrator will tell you "
                     "when they are.")


def gate() -> User:
    try:
        return _gate(store.db_path())
    except (sqlite3.Error, OSError):
        st.error(STORE_UNAVAILABLE)
        st.stop()


def _gate(db: Path) -> User:
    store.init(db)
    user = auth.current_user(touch=True)
    if user is None:
        _visitor(db)
        st.stop()
    if user.must_change_password:
        _change_password(db, user)
        st.stop()
    return user


def _visitor(db: Path) -> None:
    notice = st.session_state.pop(auth.NOTICE_KEY, None)
    with st.columns(CARD_COLUMNS)[1]:
        st.title("SOLIT2 Simulator")
        st.caption("Log in to use the simulator. New here? Sign up, and an administrator "
                   "approves your account.")
        if notice:
            st.info(notice)
        log_in_tab, sign_up_tab = st.tabs(["Log in", "Sign up"])
        with log_in_tab:
            _log_in(db)
        with sign_up_tab:
            _sign_up(db)


def _log_in(db: Path) -> None:
    with st.form("login_form"):
        email = st.text_input("Email", key="login_email", max_chars=service.EMAIL_MAX_CHARS,
                              autocomplete="username")
        password = st.text_input("Password", key="login_password", type="password",
                                 max_chars=passwords.MAX_CHARS, autocomplete="current-password")
        submitted = st.form_submit_button("Log in", key="login_submit", type="primary")
    if not submitted:
        return
    result = service.log_in(db, email, password)
    if result.status == "ok":
        auth.sign_in(result.user)
        st.rerun()
    if result.status == "pending":
        st.warning(PENDING)
    elif result.status == "locked":
        st.error("Too many failed attempts. "
                 f"Try again after {local_time(result.locked_until, CLOCK)}.")
    elif result.status == "wrong":
        st.error(WRONG)
    else:
        st.error(NO_ACCESS)


def _sign_up(db: Path) -> None:
    with st.form("signup_form"):
        name = st.text_input("Name", key="signup_name", max_chars=service.NAME_MAX_CHARS,
                             autocomplete="name")
        organisation = st.text_input("Organisation", key="signup_org",
                                     max_chars=service.NAME_MAX_CHARS,
                                     autocomplete="organization")
        email = st.text_input("Email", key="signup_email", max_chars=service.EMAIL_MAX_CHARS,
                              autocomplete="email")
        password = st.text_input(f"Password (at least {passwords.MIN_CHARS} characters)",
                                 key="signup_password", type="password",
                                 max_chars=passwords.MAX_CHARS, autocomplete="new-password")
        confirm = st.text_input("Password again", key="signup_confirm", type="password",
                                max_chars=passwords.MAX_CHARS, autocomplete="new-password")
        submitted = st.form_submit_button("Sign up", key="signup_submit", type="primary")
    if not submitted:
        return
    try:
        service.sign_up(db, name=name, organisation=organisation, email=email,
                        password=password, confirm=confirm)
    except service.AccountError as exc:
        st.error(str(exc))
        return
    st.success(SIGNED_UP)


def _change_password(db: Path, user: User) -> None:
    with st.columns(CARD_COLUMNS)[1]:
        st.title("Choose a new password")
        st.write(f"You logged in as {user.email} with a temporary password. "
                 "Choose your own to continue.")
        with st.form("change_form"):
            password = st.text_input(f"New password (at least {passwords.MIN_CHARS} characters)",
                                     key="change_password", type="password",
                                     max_chars=passwords.MAX_CHARS, autocomplete="new-password")
            confirm = st.text_input("New password again", key="change_confirm", type="password",
                                    max_chars=passwords.MAX_CHARS, autocomplete="new-password")
            submitted = st.form_submit_button("Set password", key="change_submit",
                                              type="primary")
        if st.button("Log out", key="change_logout"):
            auth.sign_out(auth.LOGGED_OUT_NOTICE)
            st.rerun()
        if not submitted:
            return
        try:
            service.change_password(db, user.id, password, confirm)
        except service.AccountError as exc:
            st.error(str(exc))
            return
        st.rerun()


def render_workspace_pending() -> None:
    """A customer's only screen until customer workspaces exist (Phase 2 of the accounts
    spec): until then no project design, run or history is shown to a customer."""
    with st.columns(CARD_COLUMNS)[1]:
        st.title("Welcome")
        st.info(WORKSPACE_PENDING)
```

- [ ] **Step 5: Role-aware screens in `app/state.py`** — add after `DEFAULT_VIEW = "simulator"`:

```python
# Which screens each role may open. A customer opens none of the project's screens
# until customer workspaces exist (Phase 2 of the accounts spec): until then the shared
# designs, runs and history are the team's alone.
ROLE_VIEWS = {"admin": VIEWS, "team": VIEWS, "customer": ()}


def views_for(role: str | None) -> tuple[str, ...]:
    return ROLE_VIEWS.get(role or "", ())


def current_view(role: str | None) -> str | None:
    """The screen to show an account of this role: the chosen one when the role may open
    it, else the first it may open; None when it may open none."""
    allowed = views_for(role)
    if not allowed:
        return None
    view = get_view()
    return view if view in allowed else allowed[0]
```

- [ ] **Step 6: The nav shows who is signed in, with Log out** — `app/components/nav.py` becomes:

```python
"""The top-level nav: one button per screen the account may open, the current one
highlighted, and on the right who is signed in with a Log out button."""
from __future__ import annotations

import streamlit as st

from app import auth, state
from app.accounts.store import User

LABELS = {"simulator": "Simulator", "wizard": "Wizard", "runs": "CFD runs"}
# One narrow column per screen, a spacer, then the account's email and Log out.
VIEW_COLUMN, SPACER_COLUMN, EMAIL_COLUMN, LOGOUT_COLUMN = 1, 3, 2, 1


def render(user: User) -> None:
    views = state.views_for(user.role)
    current = state.current_view(user.role)
    widths = [VIEW_COLUMN] * len(views) + [SPACER_COLUMN, EMAIL_COLUMN, LOGOUT_COLUMN]
    *view_columns, _, email_column, logout_column = st.columns(widths,
                                                               vertical_alignment="center")
    for column, view in zip(view_columns, views):
        kind = "primary" if view == current else "secondary"
        if column.button(LABELS[view], key=f"nav_{view}", type=kind, width="stretch"):
            state.set_view(view)
            st.rerun()
    email_column.caption(f"Signed in as {user.email}")
    if logout_column.button("Log out", key="nav_logout", width="stretch"):
        auth.sign_out(auth.LOGGED_OUT_NOTICE)
        st.rerun()
```

- [ ] **Step 7: Put the gate at the top of the app** — `app/streamlit_app.py` becomes:

```python
"""Entry point. Run with: uv run streamlit run app/streamlit_app.py"""
from __future__ import annotations

import streamlit as st

from app import state, theme
from app.components import nav, stepper
from app.views import cfd, compliance, design, fire_test, login, reports, result, runs, simulator

st.set_page_config(page_title="SOLIT2 Simulator", layout="wide",
                   initial_sidebar_state="expanded")
theme.inject()
# The login gate. It returns only for an approved, signed-in account; for anyone else it
# shows the login screens and stops the run, so nothing below this line runs.
user = login.gate()

STEP_VIEWS = {1: design.render, 2: result.render, 3: fire_test.render,
              4: cfd.render, 5: compliance.render, 6: reports.render}


def _wizard() -> None:
    stepper.render_header()
    step = state.get_step()
    if step > state.STEP_MIN and state.get_design() is None:
        st.info("Build a design first — every later step is computed from it.")
        if st.button("Go to Design", key="goto_design", type="primary"):
            state.set_step(state.STEP_MIN)
            st.rerun()
    else:
        STEP_VIEWS[step]()
    stepper.render_footer()


SCREENS = {"simulator": simulator.render, "wizard": _wizard, "runs": runs.render}

nav.render(user)
view = state.current_view(user.role)
if view is None:
    login.render_workspace_pending()
else:
    SCREENS[view]()
```

- [ ] **Step 8: Say so in the README** — in `README.md`'s `## Running the app`, insert this paragraph right after the `uv run streamlit run app/streamlit_app.py` line, and change the next paragraph's opening words "The app opens on the **Simulator**" to "Once you are in, the app opens on the **Simulator**":

```markdown
Everyone logs in first. A visitor signs up with a name, organisation, email and a password of
at least 12 characters, then waits until an admin approves the account (see
[Accounts](#accounts)). A browser refresh asks for the login again, and a session left idle for
eight hours ends.
```

- [ ] **Step 9: Run the tests**

Run: `perl -e 'alarm shift; exec @ARGV' 900 uv run pytest tests/test_app_login.py tests/test_app_nav.py tests/test_app_session.py tests/test_independence.py -x`
Expected: PASS. Then the full suite (command in Global Constraints). Expected: every test passes.

- [ ] **Step 10: Commit**

```bash
git add app/components/local_time.py app/views/login.py app/state.py app/components/nav.py app/streamlit_app.py tests/conftest.py tests/test_app_login.py tests/test_app_nav.py README.md
git commit -m "feat(app): the login gate: log in, sign up, the forced password change"
```

---

### Task 7: The Admin screen

**Files:**
- Create: `app/views/admin.py`
- Modify: `app/state.py` (`VIEWS`, `ROLE_VIEWS`, the screens comment), `app/components/nav.py` (`LABELS`), `app/streamlit_app.py` (the Admin screen's place), `README.md` (Accounts)
- Test: `tests/test_app_admin.py`

**Interfaces:**
- Consumes: `service.list_users/list_actions/approve/reject/disable/enable/issue_temporary_password/AccountError/AUDIT_ROWS`, `store.db_path`, `store.User`, `local_time`, `tests.conftest.make_account/sign_in/screen_text/TEST_PASSWORD`.
- Produces: `admin.render(user: User) -> None`; button keys `adm_team_<id>`, `adm_customer_<id>`, `adm_reject_<id>`, `adm_reject_confirm_<id>`, `adm_reject_cancel_<id>`, `adm_disable_<id>`, `adm_enable_<id>`, `adm_temp_<id>`, nav key `nav_admin`; `admin.FLASH_KEY`, `admin.CONFIRM_REJECT_KEY`.

- [ ] **Step 1: Write the failing test** — `tests/test_app_admin.py`

```python
"""The Admin screen, headless: approvals, account actions and the trail they leave."""
import streamlit as st
from streamlit.testing.v1 import AppTest

from app.accounts import service, store
from app.views import cfd, simulator
from solit2 import history
from tests.conftest import TEST_PASSWORD, make_account, screen_text, sign_in

APP = "../app/streamlit_app.py"


def _app(monkeypatch, tmp_path, role: str = "admin", view: str = "admin"):
    monkeypatch.setattr(history, "DEFAULT_PATH", tmp_path / "h.jsonl")
    monkeypatch.setattr(cfd, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setenv("SOLIT2_RUN_ROOTS", str(tmp_path / "runs"))
    monkeypatch.setenv("SOLIT2_CFD_STATE_DIR", str(tmp_path / "state"))
    at = AppTest.from_file(APP, default_timeout=180)
    user = sign_in(at, role=role)
    at.session_state["view"] = view
    at.run()
    return at, user


def _keys(at: AppTest) -> set[str]:
    return {b.key for b in at.button}


def _user(email: str):
    return next(u for u in service.list_users(store.db_path()) if u.email == email)


def test_the_admin_screen_is_for_admins_only():
    script = ("import streamlit as st\nfrom app import state\n"
              "st.write(' '.join(f'{r}={state.current_view(r)}' "
              "for r in ('admin', 'team', 'customer')))\n")
    at = AppTest.from_string(script)
    at.session_state["view"] = "admin"
    at.run()
    assert at.markdown[0].value == "admin=admin team=simulator customer=None"


def test_a_team_member_who_asks_for_the_admin_screen_gets_the_simulator(monkeypatch, tmp_path):
    monkeypatch.setattr(simulator, "render", lambda: st.write("the simulator"))
    at, _ = _app(monkeypatch, tmp_path, role="team")
    assert not at.exception
    assert "nav_admin" not in _keys(at)
    assert "the simulator" in [m.value for m in at.markdown]
    assert "Waiting for approval" not in [s.value for s in at.subheader]


def test_an_admin_has_the_nav_entry_and_the_three_sections(monkeypatch, tmp_path):
    at, _ = _app(monkeypatch, tmp_path)
    assert not at.exception
    assert "nav_admin" in _keys(at)
    assert [s.value for s in at.subheader] == ["Waiting for approval", "Accounts", "Admin actions"]


def test_approving_a_sign_up_as_team(monkeypatch, tmp_path):
    pending = make_account(role=None, state="pending", email="p@example.test")
    at, _ = _app(monkeypatch, tmp_path)
    at.button(key=f"adm_team_{pending.id}").click().run()
    assert not at.exception
    assert (_user("p@example.test").state, _user("p@example.test").role) == ("approved", "team")
    assert [s.value for s in at.success] == ["Approved p@example.test as team."]
    assert f"adm_team_{pending.id}" not in _keys(at)
    assert f"adm_disable_{pending.id}" in _keys(at)


def test_approving_a_sign_up_as_customer(monkeypatch, tmp_path):
    pending = make_account(role=None, state="pending", email="c@example.test")
    at, _ = _app(monkeypatch, tmp_path)
    at.button(key=f"adm_customer_{pending.id}").click().run()
    assert _user("c@example.test").role == "customer"


def test_reject_asks_once_more_and_cancel_leaves_it_pending(monkeypatch, tmp_path):
    pending = make_account(role=None, state="pending", email="r@example.test")
    at, _ = _app(monkeypatch, tmp_path)
    at.button(key=f"adm_reject_{pending.id}").click().run()
    assert _user("r@example.test").state == "pending"
    at.button(key=f"adm_reject_cancel_{pending.id}").click().run()
    assert _user("r@example.test").state == "pending"
    at.button(key=f"adm_reject_{pending.id}").click().run()
    at.button(key=f"adm_reject_confirm_{pending.id}").click().run()
    assert not at.exception
    assert _user("r@example.test").state == "rejected"


def test_disable_and_re_enable_but_never_the_admins_own_account(monkeypatch, tmp_path):
    member = make_account(role="team", email="m@example.test")
    at, admin = _app(monkeypatch, tmp_path)
    assert f"adm_disable_{admin.id}" not in _keys(at)
    assert f"adm_temp_{admin.id}" not in _keys(at)
    at.button(key=f"adm_disable_{member.id}").click().run()
    assert _user("m@example.test").state == "disabled"
    at.button(key=f"adm_enable_{member.id}").click().run()
    assert _user("m@example.test").state == "approved"


def test_a_temporary_password_is_shown_once_and_never_in_the_trail(monkeypatch, tmp_path):
    member = make_account(role="team", email="m@example.test")
    at, _ = _app(monkeypatch, tmp_path)
    at.button(key=f"adm_temp_{member.id}").click().run()
    [shown] = [c.value for c in at.code]
    result = service.log_in(store.db_path(), "m@example.test", shown)
    assert (result.status, result.user.must_change_password) == ("ok", True)
    assert shown not in "".join(table.value.to_csv() for table in at.dataframe)
    at.run()
    assert shown not in screen_text(at)


def test_the_admin_screen_lists_accounts_and_never_shows_a_hash(monkeypatch, tmp_path):
    make_account(role=None, state="pending", email="p@example.test")
    make_account(role="team", email="m@example.test")
    at, _ = _app(monkeypatch, tmp_path)
    text = screen_text(at)
    assert "p@example.test" in text and "m@example.test" in text
    assert "$argon2" not in text and TEST_PASSWORD not in text
```

- [ ] **Step 2: Run it to see it fail**

Run: `perl -e 'alarm shift; exec @ARGV' 900 uv run pytest tests/test_app_admin.py -x`
Expected: FAIL — the first test's markdown is `admin=simulator team=simulator customer=None` ("admin" is not a view yet)

- [ ] **Step 3: Write `app/views/admin.py`**

```python
"""The Admin screen: approve or reject sign-ups, disable and re-enable accounts, issue
temporary passwords, and read the trail every admin action leaves.

Names and organisations are what visitors typed, so they appear only as plain text
(st.text) or table cells, never inside markdown. Every action goes through
app.accounts.service, which checks again that the one acting is an approved admin.
"""
from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

import pandas as pd
import streamlit as st

from app.accounts import service, store
from app.accounts.store import User
from app.components.local_time import local_time

FLASH_KEY = "adm_flash"
CONFIRM_REJECT_KEY = "adm_confirm_reject"
PENDING_COLUMNS = (4, 1.4, 1.6, 1.2)
ACCOUNT_COLUMNS = (3, 3, 1.2, 1.8)


def render(user: User) -> None:
    if user.role != "admin":
        st.error("Only an administrator can open this screen.")
        return
    db = store.db_path()
    st.header("Admin")
    flash = st.session_state.pop(FLASH_KEY, None)
    if flash:
        st.success(flash)
    users = service.list_users(db)
    _pending(db, user, [u for u in users if u.state == "pending"])
    _accounts(db, user, [u for u in users if u.state != "pending"])
    _audit(db)


def _act(action: Callable[[], object], message: str) -> None:
    """Run one account action. On success flash `message` and rerun, so every list shows
    the change; a refusal is shown where the button was."""
    try:
        action()
    except service.AccountError as exc:
        st.error(str(exc))
        return
    st.session_state[FLASH_KEY] = message
    st.rerun()


def _pending(db: Path, admin: User, pending: list[User]) -> None:
    st.subheader("Waiting for approval")
    if not pending:
        st.caption("No sign-ups are waiting.")
        return
    for user in pending:
        with st.container(border=True):
            info, team, customer, reject = st.columns(PENDING_COLUMNS,
                                                      vertical_alignment="center")
            info.text(f"{user.name} · {user.organisation}\n"
                      f"{user.email} · signed up {local_time(user.created_at)}")
            if team.button("Approve as team", key=f"adm_team_{user.id}", type="primary",
                           width="stretch"):
                _act(partial(service.approve, db, admin.id, user.id, "team"),
                     f"Approved {user.email} as team.")
            if customer.button("Approve as customer", key=f"adm_customer_{user.id}",
                               width="stretch"):
                _act(partial(service.approve, db, admin.id, user.id, "customer"),
                     f"Approved {user.email} as customer.")
            _reject(db, admin, user, reject)


def _reject(db: Path, admin: User, user: User, column) -> None:
    """A rejection is final, so Reject asks once more before it acts."""
    if st.session_state.get(CONFIRM_REJECT_KEY) != user.id:
        if column.button("Reject", key=f"adm_reject_{user.id}", width="stretch"):
            st.session_state[CONFIRM_REJECT_KEY] = user.id
            st.rerun()
        return
    st.warning(f"Reject {user.email}? A rejected account cannot be approved later.")
    confirm, cancel, _ = st.columns((1, 1, 4))
    if confirm.button("Confirm reject", key=f"adm_reject_confirm_{user.id}", type="primary",
                      width="stretch"):
        st.session_state.pop(CONFIRM_REJECT_KEY, None)
        _act(partial(service.reject, db, admin.id, user.id), f"Rejected {user.email}.")
    if cancel.button("Cancel", key=f"adm_reject_cancel_{user.id}", width="stretch"):
        st.session_state.pop(CONFIRM_REJECT_KEY, None)
        st.rerun()


def _accounts(db: Path, admin: User, users: list[User]) -> None:
    st.subheader("Accounts")
    for user in users:
        with st.container(border=True):
            who, status, first, second = st.columns(ACCOUNT_COLUMNS,
                                                    vertical_alignment="center")
            who.text(f"{user.email}\n{user.name} · {user.organisation}")
            status.text(_status(user))
            if user.id == admin.id:
                first.caption("Your account")
            elif user.state == "approved":
                if first.button("Disable", key=f"adm_disable_{user.id}", width="stretch"):
                    _act(partial(service.disable, db, admin.id, user.id),
                         f"Disabled {user.email}.")
                if second.button("Temporary password", key=f"adm_temp_{user.id}",
                                 width="stretch"):
                    _temporary_password(db, admin, user)
            elif user.state == "disabled":
                if first.button("Re-enable", key=f"adm_enable_{user.id}", width="stretch"):
                    _act(partial(service.enable, db, admin.id, user.id),
                         f"Re-enabled {user.email}.")


def _status(user: User) -> str:
    lines = [f"{user.role or 'no role'} · {user.state}",
             f"created {local_time(user.created_at)} · "
             f"last login {local_time(user.last_login_at)}"]
    if user.must_change_password:
        lines.append("must choose a new password at the next login")
    if user.locked_until is not None and user.locked_until > datetime.now(UTC):
        lines.append(f"locked until {local_time(user.locked_until)}")
    return "\n".join(lines)


def _temporary_password(db: Path, admin: User, user: User) -> None:
    """Issue one and show it this once: it is stored only as a hash, so it cannot be
    shown again."""
    try:
        temporary = service.issue_temporary_password(db, admin.id, user.id)
    except service.AccountError as exc:
        st.error(str(exc))
        return
    st.warning(f"Temporary password for {user.email}, shown only now: pass it on privately. "
               "The account must choose its own password at its next login.")
    st.code(temporary, language=None)


def _audit(db: Path) -> None:
    st.subheader("Admin actions")
    actions = service.list_actions(db)
    if not actions:
        st.caption("No admin actions yet.")
        return
    st.dataframe(pd.DataFrame([{"When": local_time(a.at), "Admin": a.admin_email,
                                "Action": a.action, "Account": a.target_email or "—",
                                "Detail": a.detail} for a in actions]),
                 hide_index=True)
    st.caption(f"Newest first; the latest {service.AUDIT_ROWS} are shown.")
```

- [ ] **Step 4: Give the Admin screen its place**

`app/state.py` — replace everything from the comment above `VIEWS` down to and including the `ROLE_VIEWS = …` line with the block below. Leave `views_for`, `current_view`, `get_view`, `set_view` and everything else as they are:

```python
# The app's top-level screens: the live simulator is the landing screen, the wizard
# carries the formal record, the runs manager watches the FDS fleet, and Admin (admins
# only) manages the accounts.
VIEWS = ("simulator", "wizard", "runs", "admin")
PROJECT_VIEWS = ("simulator", "wizard", "runs")
DEFAULT_VIEW = "simulator"
# Which screens each role may open. A customer opens none of the project's screens
# until customer workspaces exist (Phase 2 of the accounts spec): until then the shared
# designs, runs and history are the team's alone.
ROLE_VIEWS = {"admin": VIEWS, "team": PROJECT_VIEWS, "customer": ()}
```

`app/components/nav.py` — `LABELS = {"simulator": "Simulator", "wizard": "Wizard", "runs": "CFD runs", "admin": "Admin"}`

`app/streamlit_app.py` — add `from functools import partial` below `from __future__ import annotations`; add `admin` to the views import (`from app.views import admin, cfd, compliance, design, fire_test, login, reports, result, runs, simulator`); and make the screens map:

```python
SCREENS = {"simulator": simulator.render, "wizard": _wizard, "runs": runs.render,
           "admin": partial(admin.render, user)}
```

- [ ] **Step 5: Document it** — in `README.md`'s `## Accounts`, add after the paragraph that ends "Customers see a holding screen until customer workspaces open.":

```markdown
The **Admin** screen (admins only) lists the sign-ups waiting for approval — approve as team or
customer, or reject — and every account with its role, state and last login, with Disable,
Re-enable and Temporary password. A temporary password is shown once, to pass on privately.
Every admin action is kept in the trail at the bottom of the screen.
```

- [ ] **Step 6: Run the tests**

Run: `perl -e 'alarm shift; exec @ARGV' 900 uv run pytest tests/test_app_admin.py tests/test_app_login.py tests/test_app_nav.py tests/test_independence.py -x`
Expected: PASS. Then the full suite (command in Global Constraints). Expected: every test passes.

- [ ] **Step 7: Commit**

```bash
git add app/views/admin.py app/state.py app/components/nav.py app/streamlit_app.py tests/test_app_admin.py README.md
git commit -m "feat(app): the Admin screen"
```

---

## After the last task

The final whole-branch review carries a **security lens**, because the spec keeps the IP allowlist until "a security review of this phase has passed". It checks at least:

- nothing renders app content for a visitor: the gate comes before `nav.render`, and every timed fragment starts with `auth.guard_fragment()`;
- a hash leaves `store.py` only through `credentials_by_email`/`password_hash`, and no password or hash reaches a log, the screen or an error message; the temporary password is shown once and never stored in the clear;
- the unknown-email path spends a real argon2 verify; the lockout counts inside one UPDATE;
- `service` re-reads the acting admin from the store for every admin action;
- every SQL statement is parameterised, and `update_user` takes column names only from `_UPDATABLE`;
- the store file is 0600;
- names and organisations never go through markdown;
- **known gap to decide before any public exposure:** there is no per-client rate limit on sign-up or login (only the per-account lockout). It is acceptable behind the allowlist, and is a review item before the allowlist goes.

Then a check in the browser: run the branch's app, create an admin with the CLI into a scratch `SOLIT2_DATA_DIR`, sign up a second account, approve it, log in as it, issue a temporary password and change it.

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
    session_epoch        INTEGER NOT NULL DEFAULT 0,
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
                 "failed_logins, locked_until, created_at, approved_at, approved_by, "
                 "last_login_at, session_epoch")
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
    session_epoch: int


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
    owner-only. Cheap and safe to call on every run of the app.

    Never stamps the schema version backwards: a store already at a newer version than
    this code knows about is refused outright, rather than silently rewound to a version
    whose migration would then run again."""
    db.parent.mkdir(parents=True, exist_ok=True, mode=DIR_MODE)
    if not db.exists():
        db.touch(mode=FILE_MODE)
    os.chmod(db, FILE_MODE)
    with connect(db) as conn:
        conn.execute("PRAGMA journal_mode = WAL")
        conn.executescript(_SCHEMA)
        stored_version = conn.execute("PRAGMA user_version").fetchone()[0]
        if stored_version > SCHEMA_VERSION:
            raise sqlite3.DatabaseError(
                f"the account store is at schema version {stored_version}, newer than "
                f"this code's {SCHEMA_VERSION}; upgrade the app before it opens this store")
        if stored_version < SCHEMA_VERSION:
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
                last_login_at=_dt(row["last_login_at"]), session_epoch=row["session_epoch"])


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


def update_user(conn: sqlite3.Connection, user_id: int, *, expected_state: str | None = None,
               **fields: object) -> bool:
    """Set the named columns. Only the columns in _UPDATABLE may be named, so a column
    name never comes from anywhere else into the SQL.

    When `expected_state` is given, the UPDATE only applies if the row's current state
    still matches it -- so a caller that read the row, decided what to write, and now
    writes it back is not silently overwriting a state it never saw. The return value
    says whether a row actually changed; a caller that needed `expected_state` to hold
    should treat False as "look at the account again", not as a no-op."""
    unknown = sorted(set(fields) - _UPDATABLE)
    if unknown or not fields:
        raise ValueError(f"cannot update {unknown or 'nothing'}")
    values = [_iso(v) if isinstance(v, datetime) else int(v) if isinstance(v, bool) else v
              for v in fields.values()]
    assignments = ", ".join(f"{name} = ?" for name in fields)
    where, params = "WHERE id = ?", [*values, user_id]
    if expected_state is not None:
        where += " AND state = ?"
        params.append(expected_state)
    cursor = conn.execute(f"UPDATE users SET {assignments} {where}", params)
    return cursor.rowcount == 1


def bump_session_epoch(conn: sqlite3.Connection, user_id: int) -> None:
    """End every session the account has open: each one checks the epoch it signed in with."""
    conn.execute("UPDATE users SET session_epoch = session_epoch + 1 WHERE id = ?", (user_id,))


def claim_login_attempt(conn: sqlite3.Connection, user_id: int, *, limit: int,
                        lock_until: datetime, now: datetime) -> bool:
    """Count one login attempt before its password is checked, in one UPDATE that also refuses a
    locked account, so attempts arriving at once cannot all slip under the limit. False means the
    account is locked and nothing was counted. The `limit`-th attempt in a row locks the account
    until `lock_until` and starts the count again; a successful login clears both."""
    cursor = conn.execute(
        "UPDATE users SET"
        " locked_until = CASE WHEN failed_logins + 1 >= :max_failed"
        "                THEN :until ELSE locked_until END,"
        " failed_logins = CASE WHEN failed_logins + 1 >= :max_failed"
        "                 THEN 0 ELSE failed_logins + 1 END"
        " WHERE id = :id AND (locked_until IS NULL OR locked_until <= :now)",
        {"max_failed": limit, "until": _iso(lock_until), "id": user_id, "now": _iso(now)})
    return cursor.rowcount == 1


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

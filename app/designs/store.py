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

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

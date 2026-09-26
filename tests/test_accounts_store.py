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

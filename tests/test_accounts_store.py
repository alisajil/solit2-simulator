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


def test_init_stamps_a_store_below_the_current_version(db):
    with store.connect(db) as conn:
        conn.execute("PRAGMA user_version = 0")
    store.init(db)
    with store.connect(db) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == store.SCHEMA_VERSION


def test_init_refuses_a_store_stamped_newer_than_this_code(db):
    newer = store.SCHEMA_VERSION + 1
    with store.connect(db) as conn:
        conn.execute(f"PRAGMA user_version = {newer}")
    with pytest.raises(sqlite3.DatabaseError) as excinfo:
        store.init(db)
    message = str(excinfo.value)
    assert str(newer) in message and str(store.SCHEMA_VERSION) in message
    with store.connect(db) as conn:
        assert conn.execute("PRAGMA user_version").fetchone()[0] == newer  # left untouched


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


def test_has_admin_is_false_until_one_exists(db):
    with store.connect(db) as conn:
        assert store.has_admin(conn) is False
        _add(conn, email="team@example.test", state="approved", role="team")
        assert store.has_admin(conn) is False
        _add(conn, email="admin@example.test", state="approved", role="admin")
        assert store.has_admin(conn) is True


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
        changed = store.update_user(conn, user_id, state="approved", role="team", approved_at=T0,
                                    must_change_password=False)
        user = store.user_by_id(conn, user_id)
    assert changed is True
    assert (user.state, user.role, user.approved_at, user.email) == (
        "approved", "team", T0, "a@example.test")


def test_update_user_with_expected_state_only_applies_when_it_still_matches(db):
    with store.connect(db) as conn:
        user_id = _add(conn, state="pending")
        stale = store.update_user(conn, user_id, expected_state="approved", state="rejected")
        assert stale is False
        assert store.user_by_id(conn, user_id).state == "pending"
        fresh = store.update_user(conn, user_id, expected_state="pending", state="rejected")
        assert fresh is True
        assert store.user_by_id(conn, user_id).state == "rejected"


def test_session_epoch_defaults_to_zero_and_bump_increments_it(db):
    with store.connect(db) as conn:
        user_id = _add(conn)
        assert store.user_by_id(conn, user_id).session_epoch == 0
        store.bump_session_epoch(conn, user_id)
        store.bump_session_epoch(conn, user_id)
        assert store.user_by_id(conn, user_id).session_epoch == 2


def test_claim_login_attempt_counts_locks_at_the_limit_and_refuses_while_locked(db):
    until = T0 + timedelta(minutes=15)
    with store.connect(db) as conn:
        user_id = _add(conn)
        for _ in range(4):
            assert store.claim_login_attempt(
                conn, user_id, limit=5, lock_until=until, now=T0) is True
        user = store.user_by_id(conn, user_id)
        assert (user.failed_logins, user.locked_until) == (4, None)
        # the 5th claim in a row locks the account and restarts the count
        assert store.claim_login_attempt(conn, user_id, limit=5, lock_until=until, now=T0) is True
        user = store.user_by_id(conn, user_id)
        assert (user.failed_logins, user.locked_until) == (0, until)
        # a claim while still locked is refused and changes nothing
        assert store.claim_login_attempt(conn, user_id, limit=5, lock_until=until, now=T0) is False
        user = store.user_by_id(conn, user_id)
        assert (user.failed_logins, user.locked_until) == (0, until)
        # once locked_until has passed, a claim succeeds again
        after = until + timedelta(seconds=1)
        assert store.claim_login_attempt(
            conn, user_id, limit=5, lock_until=after + timedelta(minutes=15), now=after) is True


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

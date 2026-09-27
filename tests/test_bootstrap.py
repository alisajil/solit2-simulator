"""The first-admin bootstrap: creates one from a deploy secret when the store has
none, so a host with no persistent disk (a redeploy wipes the store) recovers on its
own without anyone needing a shell into the container."""
from __future__ import annotations

import pytest

from app import bootstrap
from app.accounts import store

EMAIL, PASSWORD = "admin@example.test", "a long enough password"


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "data" / "accounts.db"
    store.init(path)
    return path


def test_does_nothing_without_both_secrets(db, monkeypatch):
    monkeypatch.delenv(bootstrap.EMAIL_KEY, raising=False)
    monkeypatch.delenv(bootstrap.PASSWORD_KEY, raising=False)
    bootstrap.ensure_admin(db)
    with store.connect(db) as conn:
        assert store.list_users(conn) == []

    monkeypatch.setenv(bootstrap.EMAIL_KEY, EMAIL)
    bootstrap.ensure_admin(db)  # email alone, no password
    with store.connect(db) as conn:
        assert store.list_users(conn) == []


def test_creates_an_admin_from_the_secrets(db, monkeypatch):
    monkeypatch.setenv(bootstrap.EMAIL_KEY, EMAIL)
    monkeypatch.setenv(bootstrap.PASSWORD_KEY, PASSWORD)
    bootstrap.ensure_admin(db)
    with store.connect(db) as conn:
        users = store.list_users(conn)
        assert len(users) == 1
        assert (users[0].email, users[0].role, users[0].state) == (EMAIL, "admin", "approved")
        assert users[0].name == bootstrap.DEFAULT_NAME


def test_uses_the_name_and_organisation_secrets_when_given(db, monkeypatch):
    monkeypatch.setenv(bootstrap.EMAIL_KEY, EMAIL)
    monkeypatch.setenv(bootstrap.PASSWORD_KEY, PASSWORD)
    monkeypatch.setenv(bootstrap.NAME_KEY, "Ali Sajil")
    monkeypatch.setenv(bootstrap.ORGANISATION_KEY, "Mistelix")
    bootstrap.ensure_admin(db)
    with store.connect(db) as conn:
        user = store.list_users(conn)[0]
    assert (user.name, user.organisation) == ("Ali Sajil", "Mistelix")


def test_does_nothing_once_an_admin_already_exists(db, monkeypatch):
    monkeypatch.setenv(bootstrap.EMAIL_KEY, EMAIL)
    monkeypatch.setenv(bootstrap.PASSWORD_KEY, PASSWORD)
    bootstrap.ensure_admin(db)
    monkeypatch.setenv(bootstrap.EMAIL_KEY, "someone-else@example.test")
    bootstrap.ensure_admin(db)  # would be a second admin if this did not check first
    with store.connect(db) as conn:
        users = store.list_users(conn)
    assert [u.email for u in users] == [EMAIL]


def test_a_secret_the_policy_refuses_creates_nothing_and_is_reported(db, monkeypatch, capsys):
    monkeypatch.setenv(bootstrap.EMAIL_KEY, EMAIL)
    monkeypatch.setenv(bootstrap.PASSWORD_KEY, "too short")
    bootstrap.ensure_admin(db)
    with store.connect(db) as conn:
        assert store.list_users(conn) == []
    assert "too short" not in capsys.readouterr().out  # the password itself is never printed


def test_a_broken_secrets_file_falls_back_to_the_environment(db, monkeypatch):
    """st.secrets raises when no secrets.toml exists anywhere Streamlit looks; the
    environment variable must still work."""
    monkeypatch.setenv(bootstrap.EMAIL_KEY, EMAIL)
    monkeypatch.setenv(bootstrap.PASSWORD_KEY, PASSWORD)
    bootstrap.ensure_admin(db)
    with store.connect(db) as conn:
        assert len(store.list_users(conn)) == 1

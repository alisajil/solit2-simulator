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

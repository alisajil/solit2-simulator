"""Shared AppTest scaffolding: render one view the way the shell does (theme +
optional seeded design), without the stepper so buttons are addressed by key only;
and the accounts every app test needs now that the app has a login."""
import time
from datetime import UTC, datetime
from functools import cache
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from app import auth
from app.accounts import passwords, store

EXAMPLE_DESIGN = "examples/designs/road-tunnel-twin-bore.json"
# TEST VALUES, NOT DATA: a single-mode head for the Design step's tester-input
# fields. Dv50/Dv90 give a Rosin-Rammler n of 2.5; 5.0 m fits the SOLIT2 gallery.
TEST_NOZZLE_FIELDS = {"d_k": 4.1, "d_pressure": 50.0, "d_smd": 100.0, "d_dv50": 128.61184,
                      "d_dv90": 207.891648, "d_cone": 45.0, "d_launch": 20.0,
                      "d_mount_h": 5.0, "d_rows": 2, "d_pitch": 2.4, "d_tilt": 0.0}
TEST_NOZZLE_OFFSETS = "-2.75, 2.75"
# TEST VALUE, NOT DATA: the system's pump ramp, typed into the Design step.
TEST_PUMP_RAMP_S = 30.0
# The SOLIT2 protocol example: its template head sits at 5.0 m, inside the 5.2 m gallery.
PROTOCOL_DESIGN = "examples/designs/solit2-test-protocol.json"
# TEST VALUES, NOT DATA, typed into the Fire test step's Annex 7 fields: the
# conditions Annex 7 leaves to the AHJ or the test day.
TEST_ANNEX7_WIDGETS = {"a7_class": "A", "a7_activation": 150.0, "a7_ambient": 20.0,
                       "a7_rh": 60.0, "a7_alpha": 0.1876, "a7_incubation": 243.0}


def fill_nozzle(at: AppTest) -> AppTest:
    """Type the test head and its pump ramp into the Design step, as a tester would."""
    for key, value in TEST_NOZZLE_FIELDS.items():
        at.number_input(key=key).set_value(value)
    at.text_input(key="d_offsets").set_value(TEST_NOZZLE_OFFSETS)
    at.number_input(key="d_pump_ramp").set_value(TEST_PUMP_RAMP_S)
    return at.run()
TEST_PASSWORD = "a test password, long enough"


REFERENCE_NOZZLE_FIXTURE = (Path(__file__).parent / "fixtures"
                            / "solit2_reference_nozzle_TEST_FIXTURE.json")


@pytest.fixture(autouse=True, scope="session")
def _reference_nozzle_fixture():
    """The anchors run on the labelled fixture; the product reads the tester's own file.

    Session-scoped so module-scoped fixtures that load anchors see it too; a test
    that needs the file absent overrides it with its own function-scoped monkeypatch.
    """
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("SOLIT2_REFERENCE_NOZZLE", str(REFERENCE_NOZZLE_FIXTURE))
        yield


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
    at.session_state[auth.EPOCH_KEY] = user.session_epoch
    return user


SCREEN_ELEMENTS = ("title", "header", "subheader", "markdown", "caption", "text", "code",
                   "error", "warning", "info", "success")


def screen_text(at: AppTest) -> str:
    """Everything an AppTest's page shows as text, tables included."""
    parts = [str(element.value) for kind in SCREEN_ELEMENTS for element in getattr(at, kind)]
    parts += [table.value.to_csv() for table in at.dataframe]
    return "\n".join(parts)


def view_script(view: str, seed_design: bool, design_path: str = EXAMPLE_DESIGN) -> str:
    seed = (f'if state.get_design() is None:\n'
            f'    state.set_design(Design.load("{design_path}"))\n') if seed_design else ""
    return ("import streamlit as st\n"
            "from app import state, theme\n"
            f"from app.views import {view} as view\n"
            "from solit2.schema.design import Design\n"
            "theme.inject()\n"
            f"{seed}"
            "view.render()\n")


@pytest.fixture
def run_view():
    def _run(view: str, seed_design: bool = True, timeout: float = 90.0,
             design_path: str = EXAMPLE_DESIGN, session: dict | None = None) -> AppTest:
        at = AppTest.from_string(view_script(view, seed_design, design_path),
                                 default_timeout=timeout)
        sign_in(at)
        for key, value in (session or {}).items():
            at.session_state[key] = value
        at.run()
        return at
    return _run

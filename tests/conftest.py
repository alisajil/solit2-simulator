"""Shared AppTest scaffolding: render one view the way the shell does (theme +
optional seeded design), without the stepper so buttons are addressed by key only."""
import pytest
from streamlit.testing.v1 import AppTest

from app.accounts import store

EXAMPLE_DESIGN = "examples/designs/road-tunnel-twin-bore.json"


@pytest.fixture(autouse=True)
def _account_store_per_test(tmp_path_factory, monkeypatch):
    """Every test gets its own empty account store; no test touches data/accounts.db."""
    monkeypatch.setenv(store.DATA_DIR_ENV, str(tmp_path_factory.mktemp("accounts")))


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
        at.run()
        return at
    return _run

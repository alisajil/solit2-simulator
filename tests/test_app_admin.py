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

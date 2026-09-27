"""The login gate, headless: a visitor sees only the login and the sign-up, an approved
account sees the app, and a temporary password is replaced before anything else.

The tests land on the CFD runs manager (empty run roots) only because it renders
fastest; the gate in front of it is the subject."""
import time

import pytest
from streamlit.testing.v1 import AppTest

from app import auth
from app.accounts import service, store
from app.components import nav
from app.views import cfd, login, runs, simulator
from solit2 import history
from tests.conftest import TEST_PASSWORD, make_account, screen_text, sign_in

APP = "../app/streamlit_app.py"
NEW_PASSWORD = "another long password"


def _app(monkeypatch, tmp_path, view: str = "runs") -> AppTest:
    monkeypatch.setattr(history, "DEFAULT_PATH", tmp_path / "h.jsonl")
    monkeypatch.setattr(cfd, "RUNS_DIR", tmp_path / "runs")
    monkeypatch.setenv("SOLIT2_RUN_ROOTS", str(tmp_path / "runs"))
    monkeypatch.setenv("SOLIT2_CFD_STATE_DIR", str(tmp_path / "state"))
    at = AppTest.from_file(APP, default_timeout=180)
    at.session_state["view"] = view
    return at


def _keys(at: AppTest) -> set[str]:
    return {b.key for b in at.button}


def _nav(at: AppTest) -> set[str]:
    return {k for k in _keys(at) if k.startswith("nav_")}


def _log_in(at: AppTest, email: str, password: str) -> AppTest:
    at.text_input(key="login_email").input(email)
    at.text_input(key="login_password").input(password)
    at.button(key="login_submit").click().run()
    return at


def _sign_up(at: AppTest, email: str, password: str, confirm: str, name: str = "Ada") -> AppTest:
    at.text_input(key="signup_name").input(name)
    at.text_input(key="signup_org").input("Analytical Engines")
    at.text_input(key="signup_email").input(email)
    at.text_input(key="signup_password").input(password)
    at.text_input(key="signup_confirm").input(confirm)
    at.button(key="signup_submit").click().run()
    return at


def _change(at: AppTest, password: str, confirm: str) -> AppTest:
    at.text_input(key="change_password").input(password)
    at.text_input(key="change_confirm").input(confirm)
    at.button(key="change_submit").click().run()
    return at


def test_a_visitor_sees_only_the_login_and_the_sign_up(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    at.run()
    assert not at.exception
    assert {"login_submit", "signup_submit"} <= _keys(at)
    assert not _nav(at)
    assert not any("CFD runs" in h.value for h in at.header)


def test_the_gate_bootstraps_an_admin_from_the_deploy_secret(monkeypatch, tmp_path):
    from app import bootstrap
    monkeypatch.setenv(bootstrap.EMAIL_KEY, "admin@example.test")
    monkeypatch.setenv(bootstrap.PASSWORD_KEY, TEST_PASSWORD)
    at = _app(monkeypatch, tmp_path)
    at.run()
    assert not at.exception
    _log_in(at, "admin@example.test", TEST_PASSWORD)
    assert not at.exception
    assert "nav_admin" in _nav(at)


def test_nothing_below_the_gate_runs_for_a_visitor(monkeypatch, tmp_path):
    def rendered(*_args, **_kwargs):
        raise AssertionError("rendered for a visitor")
    for module, name in ((nav, "render"), (simulator, "render"), (runs, "render"),
                         (login, "render_workspace_pending")):
        monkeypatch.setattr(module, name, rendered)
    at = _app(monkeypatch, tmp_path)
    at.run()
    assert not at.exception
    assert "login_submit" in _keys(at)


def test_a_sign_up_waits_for_approval_and_says_so(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    at.run()
    _sign_up(at, "Ada@Example.test", TEST_PASSWORD, TEST_PASSWORD)
    assert not at.exception
    assert [s.value for s in at.success] == [login.SIGNED_UP]
    [user] = service.list_users(store.db_path())
    assert (user.email, user.state, user.role) == ("ada@example.test", "pending", None)


def test_signing_up_a_registered_email_gets_the_same_message_and_changes_nothing(monkeypatch,
                                                                                 tmp_path):
    make_account(role="team", email="ada@example.test")
    at = _app(monkeypatch, tmp_path)
    at.run()
    _sign_up(at, "ada@example.test", NEW_PASSWORD, NEW_PASSWORD, name="Someone Else")
    assert [s.value for s in at.success] == [login.SIGNED_UP]
    [user] = service.list_users(store.db_path())
    assert (user.name, user.state) == ("Test team", "approved")


def test_a_refused_sign_up_says_why_and_stores_nothing(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    at.run()
    _sign_up(at, "ada@example.test", TEST_PASSWORD, TEST_PASSWORD + "x")
    assert [e.value for e in at.error] == ["The two passwords do not match."]
    assert service.list_users(store.db_path()) == []


def test_a_pending_account_sees_only_the_wait_message(monkeypatch, tmp_path):
    make_account(role=None, state="pending", email="p@example.test")
    at = _app(monkeypatch, tmp_path)
    at.run()
    _log_in(at, "p@example.test", TEST_PASSWORD)
    assert [w.value for w in at.warning] == [login.PENDING]
    assert not _nav(at)
    assert auth.USER_ID_KEY not in at.session_state


@pytest.mark.parametrize("role, state", [(None, "rejected"), ("team", "disabled")])
def test_rejected_and_disabled_accounts_have_no_access(monkeypatch, tmp_path, role, state):
    make_account(role=role, state=state, email="x@example.test")
    at = _app(monkeypatch, tmp_path)
    at.run()
    _log_in(at, "x@example.test", TEST_PASSWORD)
    assert [e.value for e in at.error] == [login.NO_ACCESS]
    assert not _nav(at)


def test_a_wrong_password_and_an_unknown_email_get_the_same_message(monkeypatch, tmp_path):
    make_account(role="team", email="t@example.test")
    at = _app(monkeypatch, tmp_path)
    at.run()
    _log_in(at, "t@example.test", "a wrong password!")
    assert [e.value for e in at.error] == [login.WRONG]
    _log_in(at, "nobody@example.test", TEST_PASSWORD)
    assert [e.value for e in at.error] == [login.WRONG]


def test_a_locked_account_is_told_when_to_try_again(monkeypatch, tmp_path):
    make_account(role="team", email="t@example.test")
    for _ in range(service.MAX_FAILED_LOGINS):
        service.log_in(store.db_path(), "t@example.test", "a wrong password!")
    at = _app(monkeypatch, tmp_path)
    at.run()
    _log_in(at, "t@example.test", TEST_PASSWORD)
    [message] = [e.value for e in at.error]
    assert message.startswith("Too many failed attempts. Try again after ")
    assert not _nav(at)


def test_an_approved_login_opens_the_app(monkeypatch, tmp_path):
    make_account(role="team", email="t@example.test")
    at = _app(monkeypatch, tmp_path)
    at.run()
    _log_in(at, " T@Example.test ", TEST_PASSWORD)
    assert not at.exception
    assert {"nav_simulator", "nav_wizard", "nav_runs", "nav_logout"} <= _keys(at)
    assert "Signed in as `t@example.test`" in [c.value for c in at.caption]
    assert any("CFD runs" in h.value for h in at.header)


def test_log_out_ends_the_session_and_drops_its_state(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    sign_in(at)
    at.session_state["left_over"] = "anything the session held"
    at.run()
    at.button(key="nav_logout").click().run()
    assert not at.exception
    assert "login_submit" in _keys(at)
    assert auth.LOGGED_OUT_NOTICE in [i.value for i in at.info]
    assert "left_over" not in at.session_state and auth.USER_ID_KEY not in at.session_state


def test_an_idle_session_meets_the_login_with_the_reason(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)
    sign_in(at)
    at.session_state[auth.LAST_SEEN_KEY] = time.time() - auth.IDLE_TIMEOUT_S - 1
    at.run()
    assert "login_submit" in _keys(at)
    assert auth.IDLE_NOTICE in [i.value for i in at.info]


def test_a_temporary_password_is_replaced_before_anything_else(monkeypatch, tmp_path):
    make_account(role="team", email="t@example.test", must_change_password=True)
    at = _app(monkeypatch, tmp_path)
    at.run()
    _log_in(at, "t@example.test", TEST_PASSWORD)
    assert "change_submit" in _keys(at)
    assert not _nav(at)
    _change(at, TEST_PASSWORD, TEST_PASSWORD)
    assert [e.value for e in at.error] == [
        "Choose a password different from the one you have now."]
    _change(at, NEW_PASSWORD, NEW_PASSWORD)
    assert not at.exception
    assert "nav_runs" in _keys(at)
    result = service.log_in(store.db_path(), "t@example.test", NEW_PASSWORD)
    assert result.user.must_change_password is False


def test_a_temporary_password_ends_the_accounts_other_live_sessions(monkeypatch, tmp_path):
    """I1 regression -- the review's own reproduction: before the fix, a session that was
    already signed in when the admin issued a temporary password could finish the forced
    change on its NEXT run with no login and no knowledge of the temporary password at
    all. The fix must show that session the login instead, with REVOKED_NOTICE, and
    never the change form."""
    user = make_account(role="team", email="t@example.test")
    admin = make_account(role="admin", email="admin@example.test")
    session = _app(monkeypatch, tmp_path)
    session.session_state[auth.USER_ID_KEY] = user.id
    session.session_state[auth.LAST_SEEN_KEY] = time.time()
    session.session_state[auth.EPOCH_KEY] = user.session_epoch
    session.run()
    assert "nav_runs" in _keys(session)  # the session starts out live

    service.issue_temporary_password(store.db_path(), admin.id, user.id)
    session.run()
    assert not session.exception
    assert "change_submit" not in _keys(session)
    assert "login_submit" in _keys(session)
    assert auth.REVOKED_NOTICE in [i.value for i in session.info]


def test_changing_the_password_keeps_the_changing_session_in_and_ends_the_others(monkeypatch,
                                                                                 tmp_path):
    """I1: the session that makes the change stays signed in, with the new epoch; a
    second, separate session of the same account -- signed in with the same temporary
    password -- is ended at its next run instead of being allowed to finish the change
    itself."""
    user = make_account(role="team", email="t@example.test", must_change_password=True)

    def _seeded_session() -> AppTest:
        session = _app(monkeypatch, tmp_path)
        session.session_state[auth.USER_ID_KEY] = user.id
        session.session_state[auth.LAST_SEEN_KEY] = time.time()
        session.session_state[auth.EPOCH_KEY] = user.session_epoch
        return session

    changing, other = _seeded_session(), _seeded_session()
    changing.run()
    other.run()
    assert "change_submit" in _keys(changing) and "change_submit" in _keys(other)

    _change(changing, NEW_PASSWORD, NEW_PASSWORD)
    assert not changing.exception
    assert "nav_runs" in _keys(changing)  # the changing session stays signed in

    other.run()
    assert "login_submit" in _keys(other)
    assert auth.REVOKED_NOTICE in [i.value for i in other.info]


def test_a_stale_reset_during_the_change_form_signs_out_with_the_revoked_notice(monkeypatch,
                                                                               tmp_path):
    """I1 residual (app level): when service.change_password finds its expected_epoch
    stale -- a reset landed while the change form was open -- the form must sign the
    session out and show the login with REVOKED_NOTICE, not its own error banner."""
    make_account(role="team", email="t@example.test", must_change_password=True)
    at = _app(monkeypatch, tmp_path)
    at.run()
    _log_in(at, "t@example.test", TEST_PASSWORD)
    assert "change_submit" in _keys(at)

    def raise_session_ended(*_args, **_kwargs):
        raise service.AccountError(
            "Your session ended because this account's password was reset. Log in again.",
            "session")

    monkeypatch.setattr(service, "change_password", raise_session_ended)
    _change(at, NEW_PASSWORD, NEW_PASSWORD)
    assert not at.exception
    assert "login_submit" in _keys(at)
    assert auth.REVOKED_NOTICE in [i.value for i in at.info]


def test_an_unreadable_store_shows_that_and_nothing_else(monkeypatch, tmp_path):
    broken = tmp_path / "broken"
    broken.mkdir()
    (broken / store.DB_NAME).write_text("this is not a database")
    monkeypatch.setenv(store.DATA_DIR_ENV, str(broken))
    at = _app(monkeypatch, tmp_path)
    at.run()
    assert not at.exception
    assert [e.value for e in at.error] == [login.STORE_UNAVAILABLE]
    assert not _keys(at)


def test_a_customer_sees_the_holding_screen_and_no_project_screen(monkeypatch, tmp_path):
    at = _app(monkeypatch, tmp_path)  # asks for the runs manager, which a customer may not open
    sign_in(at, role="customer")
    at.run()
    assert not at.exception
    assert [i.value for i in at.info] == [login.WORKSPACE_PENDING]
    assert _nav(at) == {"nav_logout"}
    assert not any("CFD runs" in h.value for h in at.header)


def test_no_password_or_hash_reaches_the_screen(monkeypatch, tmp_path):
    make_account(role="team", email="t@example.test")
    at = _app(monkeypatch, tmp_path)
    at.run()
    _log_in(at, "t@example.test", "a wrong password!")
    assert "a wrong password!" not in screen_text(at)
    _log_in(at, "t@example.test", TEST_PASSWORD)
    text = screen_text(at)
    assert TEST_PASSWORD not in text and "$argon2" not in text

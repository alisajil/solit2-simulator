"""The account rules: sign-up, login and lockout, the admin's state machine, temporary passwords."""
import ast
import logging
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from argon2 import PasswordHasher

from app.accounts import passwords, service, store
from app.accounts.service import AccountError

T0 = datetime(2026, 9, 26, 10, 0, tzinfo=UTC)
PASSWORD = "a long enough password"
NEW_PASSWORD = "another long password"
WRONG = "a wrong password!"


@pytest.fixture
def db(tmp_path):
    path = tmp_path / "accounts.db"
    store.init(path)
    return path


@pytest.fixture
def admin(db):
    return service.create_admin(db, email="admin@example.test", name="Ada Admin",
                                organisation="Ops", password=PASSWORD, confirm=PASSWORD, now=T0)


def _by_email(db, email):
    return next(u for u in service.list_users(db) if u.email == email)


def _sign_up(db, email="new@example.test", name="Nia New"):
    service.sign_up(db, name=name, organisation="Customer Co", email=email, password=PASSWORD,
                    confirm=PASSWORD, now=T0)
    return _by_email(db, service.normalise_email(email))


def _approved(db, admin, email="team@example.test", role="team"):
    return service.approve(db, admin.id, _sign_up(db, email=email).id, role, now=T0)


def test_the_account_package_does_not_import_streamlit():
    for source in Path(service.__file__).parent.glob("*.py"):
        tree = ast.parse(source.read_text())
        imported = {alias.name.split(".")[0] for node in ast.walk(tree)
                    if isinstance(node, ast.Import) for alias in node.names}
        imported |= {node.module.split(".")[0] for node in ast.walk(tree)
                     if isinstance(node, ast.ImportFrom) and node.module}
        assert "streamlit" not in imported, source.name


# --- sign-up ------------------------------------------------------------------

def test_a_sign_up_waits_for_approval_with_no_role(db):
    user = _sign_up(db, email="  New@Example.TEST ")
    assert (user.email, user.state, user.role, user.name) == (
        "new@example.test", "pending", None, "Nia New")


def test_signing_up_an_email_already_registered_changes_nothing_and_says_nothing(db):
    _sign_up(db, name="First")
    service.sign_up(db, name="Second", organisation="Other", email="NEW@example.test",
                    password=NEW_PASSWORD, confirm=NEW_PASSWORD, now=T0)  # no error: neutral
    [user] = service.list_users(db)
    assert user.name == "First"
    assert service.log_in(db, "new@example.test", PASSWORD, now=T0).status == "pending"


@pytest.mark.parametrize("fields, field, message", [
    ({"name": "  "}, "name", "Enter your name."),
    ({"organisation": ""}, "organisation", "Enter your organisation."),
    ({"name": "x" * 101}, "name", "Your name can be at most 100 printable characters."),
    ({"name": "Two\nlines"}, "name", "Your name can be at most 100 printable characters."),
    ({"email": "not-an-email"}, "email", "Enter a valid email address."),
    ({"email": "[x](y)@example.test"}, "email", "Enter a valid email address."),
    ({"password": "short", "confirm": "short"}, "password",
     "The password must be at least 12 characters."),
    ({"confirm": PASSWORD + "x"}, "password", "The two passwords do not match."),
])
def test_a_sign_up_the_rules_refuse_stores_nothing(db, fields, field, message):
    values = {"name": "Nia", "organisation": "Co", "email": "n@example.test",
              "password": PASSWORD, "confirm": PASSWORD, **fields}
    with pytest.raises(AccountError) as refused:
        service.sign_up(db, **values)
    assert (refused.value.field, str(refused.value)) == (field, message)
    assert service.list_users(db) == []


# --- login and lockout --------------------------------------------------------

def test_an_unknown_email_and_a_wrong_password_get_the_same_answer(db, admin):
    unknown = service.log_in(db, "nobody@example.test", PASSWORD, now=T0)
    wrong = service.log_in(db, "admin@example.test", WRONG, now=T0)
    assert unknown == wrong == service.LoginResult("wrong")
    assert _by_email(db, "admin@example.test").failed_logins == 1


@pytest.mark.parametrize("final_state", ["pending", "rejected", "disabled"])
def test_only_a_correct_password_learns_an_unapproved_accounts_state(db, admin, final_state):
    user = _sign_up(db)
    if final_state == "rejected":
        service.reject(db, admin.id, user.id, now=T0)
    elif final_state == "disabled":
        service.approve(db, admin.id, user.id, "team", now=T0)
        service.disable(db, admin.id, user.id, now=T0)
    assert service.log_in(db, user.email, WRONG, now=T0).status == "wrong"
    result = service.log_in(db, user.email, PASSWORD, now=T0)
    assert (result.status, result.user) == (final_state, None)


def test_an_approved_login_returns_the_account_and_stamps_it(db, admin):
    user = _approved(db, admin)
    service.log_in(db, user.email, WRONG, now=T0)
    later = T0 + timedelta(minutes=1)
    result = service.log_in(db, " TEAM@example.test ", PASSWORD, now=later)
    assert result.status == "ok"
    assert (result.user.id, result.user.last_login_at, result.user.failed_logins) == (
        user.id, later, 0)


def test_five_wrong_passwords_lock_the_account_for_fifteen_minutes(db, admin):
    user = _approved(db, admin)
    for _ in range(service.MAX_FAILED_LOGINS):
        assert service.log_in(db, user.email, WRONG, now=T0).status == "wrong"
    locked = service.log_in(db, user.email, PASSWORD, now=T0 + timedelta(minutes=14))
    assert locked == service.LoginResult("locked", locked_until=T0 + service.LOCKOUT)
    after = T0 + service.LOCKOUT + timedelta(seconds=1)
    assert service.log_in(db, user.email, PASSWORD, now=after).status == "ok"


def test_a_locked_account_does_not_check_the_password_or_extend_the_lock(db, admin):
    user = _approved(db, admin)
    for _ in range(service.MAX_FAILED_LOGINS):
        service.log_in(db, user.email, WRONG, now=T0)
    service.log_in(db, user.email, WRONG, now=T0 + timedelta(minutes=5))
    assert _by_email(db, user.email).locked_until == T0 + service.LOCKOUT
    assert _by_email(db, user.email).failed_logins == 0


def test_a_hash_under_old_parameters_is_replaced_at_the_next_login(db, admin):
    user = _approved(db, admin)
    old = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash(PASSWORD)
    with store.connect(db) as conn:
        store.update_user(conn, user.id, password_hash=old)
    assert service.log_in(db, user.email, PASSWORD, now=T0).status == "ok"
    with store.connect(db) as conn:
        fresh = store.password_hash(conn, user.id)
    assert fresh != old and not passwords.needs_rehash(fresh)


# --- the admin's state machine ------------------------------------------------

def test_approving_sets_the_role_and_who_approved_it(db, admin):
    approved = service.approve(db, admin.id, _sign_up(db).id, "customer", now=T0)
    assert (approved.state, approved.role, approved.approved_by, approved.approved_at) == (
        "approved", "customer", admin.id, T0)


def test_an_account_is_approved_as_team_or_customer_only(db, admin):
    user = _sign_up(db)
    with pytest.raises(AccountError):
        service.approve(db, admin.id, user.id, "admin", now=T0)
    assert _by_email(db, user.email).state == "pending"


def test_a_rejected_account_stays_rejected(db, admin):
    user = _sign_up(db)
    assert service.reject(db, admin.id, user.id, now=T0).state == "rejected"
    with pytest.raises(AccountError, match="only pending accounts can be approved"):
        service.approve(db, admin.id, user.id, "team", now=T0)


def test_disable_and_re_enable_keep_the_role(db, admin):
    user = _approved(db, admin, role="customer")
    assert service.disable(db, admin.id, user.id, now=T0).state == "disabled"
    with pytest.raises(AccountError, match="only approved accounts can be disabled"):
        service.disable(db, admin.id, user.id, now=T0)
    enabled = service.enable(db, admin.id, user.id, now=T0)
    assert (enabled.state, enabled.role) == ("approved", "customer")


def test_an_admin_cannot_change_their_own_account(db, admin):
    with pytest.raises(AccountError, match="your own account"):
        service.disable(db, admin.id, admin.id, now=T0)
    with pytest.raises(AccountError, match="your own account"):
        service.issue_temporary_password(db, admin.id, admin.id, now=T0)


def test_only_an_approved_admin_can_act(db, admin):
    team = _approved(db, admin)
    other = _sign_up(db, email="other@example.test")
    with pytest.raises(AccountError, match="Only an administrator"):
        service.approve(db, team.id, other.id, "team", now=T0)
    second = service.create_admin(db, email="second@example.test", name="Bo", organisation="Ops",
                                  password=PASSWORD, confirm=PASSWORD, now=T0)
    service.disable(db, admin.id, second.id, now=T0)
    with pytest.raises(AccountError, match="Only an administrator"):
        service.approve(db, second.id, other.id, "team", now=T0)
    assert _by_email(db, other.email).state == "pending"


def test_every_admin_action_lands_in_the_audit_trail(db, admin):
    user = _sign_up(db)
    service.approve(db, admin.id, user.id, "team", now=T0 + timedelta(minutes=1))
    service.disable(db, admin.id, user.id, now=T0 + timedelta(minutes=2))
    service.enable(db, admin.id, user.id, now=T0 + timedelta(minutes=3))
    service.issue_temporary_password(db, admin.id, user.id, now=T0 + timedelta(minutes=4))
    refused = _sign_up(db, email="no@example.test")
    service.reject(db, admin.id, refused.id, now=T0 + timedelta(minutes=5))
    trail = service.list_actions(db)
    assert [(a.action, a.target_email) for a in trail] == [
        ("reject", "no@example.test"), ("temporary_password", user.email),
        ("enable", user.email), ("disable", user.email), ("approve", user.email),
        ("create_admin", "admin@example.test")]
    assert {a.admin_email for a in trail} == {"admin@example.test"}
    assert trail[-2].detail == "role=team"


# --- temporary and changed passwords -----------------------------------------

def test_a_temporary_password_replaces_the_old_one_clears_a_lock_and_must_be_changed(db, admin):
    user = _approved(db, admin)
    for _ in range(service.MAX_FAILED_LOGINS):
        service.log_in(db, user.email, WRONG, now=T0)
    temporary = service.issue_temporary_password(db, admin.id, user.id, now=T0)
    assert service.log_in(db, user.email, PASSWORD, now=T0).status == "wrong"
    result = service.log_in(db, user.email, temporary, now=T0)
    assert (result.status, result.user.must_change_password) == ("ok", True)
    assert temporary not in " ".join(a.detail for a in service.list_actions(db))


def test_a_temporary_password_is_for_approved_accounts_only(db, admin):
    user = _sign_up(db)
    with pytest.raises(AccountError, match="only approved accounts"):
        service.issue_temporary_password(db, admin.id, user.id, now=T0)


def test_changing_the_password_clears_the_must_change_flag(db, admin):
    user = _approved(db, admin)
    temporary = service.issue_temporary_password(db, admin.id, user.id, now=T0)
    with pytest.raises(AccountError, match="different from the one you have now"):
        service.change_password(db, user.id, temporary, temporary)
    with pytest.raises(AccountError, match="do not match"):
        service.change_password(db, user.id, NEW_PASSWORD, NEW_PASSWORD + "x")
    service.change_password(db, user.id, NEW_PASSWORD, NEW_PASSWORD)
    result = service.log_in(db, user.email, NEW_PASSWORD, now=T0)
    assert (result.status, result.user.must_change_password) == ("ok", False)
    assert service.log_in(db, user.email, temporary, now=T0).status == "wrong"


# --- the first admin ----------------------------------------------------------

def test_create_admin_makes_an_approved_admin_and_records_it(db, admin):
    assert (admin.role, admin.state, admin.approved_at) == ("admin", "approved", T0)
    assert service.log_in(db, "ADMIN@example.test", PASSWORD, now=T0).user.role == "admin"
    [action] = service.list_actions(db)
    assert (action.action, action.target_email) == ("create_admin", "admin@example.test")


def test_create_admin_refuses_an_email_already_registered(db, admin):
    with pytest.raises(AccountError, match="already exists"):
        service.create_admin(db, email="Admin@Example.test", name="X", organisation="Y",
                             password=PASSWORD, confirm=PASSWORD, now=T0)


# --- nothing secret leaks -----------------------------------------------------

def test_no_password_or_hash_is_ever_logged(db, admin, caplog):
    caplog.set_level(logging.DEBUG)
    user = _approved(db, admin)
    service.log_in(db, user.email, WRONG, now=T0)
    service.log_in(db, user.email, PASSWORD, now=T0)
    temporary = service.issue_temporary_password(db, admin.id, user.id, now=T0)
    service.change_password(db, user.id, NEW_PASSWORD, NEW_PASSWORD)
    with store.connect(db) as conn:
        stored = store.password_hash(conn, user.id)
    for secret in (PASSWORD, NEW_PASSWORD, WRONG, temporary, stored, "$argon2"):
        assert secret not in caplog.text

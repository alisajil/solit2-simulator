"""The account rules: sign-up, login and lockout, the admin's approvals, temporary passwords.

Every function opens one short connection and does its whole job in that one
transaction. What a person can fix raises AccountError, whose message is written for
them and safe to show. Nothing here imports Streamlit: the screens and the command
line both call this module.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Literal

from app.accounts import passwords, store
from app.accounts.store import AdminAction, User

MAX_FAILED_LOGINS = 5
LOCKOUT = timedelta(minutes=15)
NAME_MAX_CHARS = 100
EMAIL_MAX_CHARS = 254
AUDIT_ROWS = 200
APPROVAL_ROLES = ("team", "customer")
# A conservative address shape. It keeps out everything that could inject HTML, a link
# with its own text, an image or a code span -- but not everything markdown acts on: `_`
# can still italicise part of an address, and the renderer auto-links every email as a
# mailto: (GFM literal autolinks). A message that interpolates one wraps it in backticks,
# which escapes the `_` and blocks the autolink.
_EMAIL = re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9-]+(\.[A-Za-z0-9-]+)*\.[A-Za-z]{2,}")
# action -> (the state it applies to, the state it leaves the account in)
_TRANSITIONS = {"approve": ("pending", "approved"), "reject": ("pending", "rejected"),
                "disable": ("approved", "disabled"), "enable": ("disabled", "approved")}
_DONE = {"approve": "approved", "reject": "rejected", "disable": "disabled",
         "enable": "re-enabled"}

LoginStatus = Literal["ok", "wrong", "locked", "pending", "rejected", "disabled"]


class AccountError(ValueError):
    """A request the account rules refuse. The message is written for the person who made it."""

    def __init__(self, message: str, field: str = "account") -> None:
        super().__init__(message)
        self.field = field


@dataclass(frozen=True)
class LoginResult:
    status: LoginStatus
    user: User | None = None
    locked_until: datetime | None = None


def _now(now: datetime | None) -> datetime:
    return datetime.now(UTC) if now is None else now.astimezone(UTC)


def normalise_email(raw: str) -> str:
    return raw.strip().lower()


def _checked_email(raw: str) -> str:
    email = normalise_email(raw)
    if len(email) > EMAIL_MAX_CHARS or not _EMAIL.fullmatch(email):
        raise AccountError("Enter a valid email address.", "email")
    return email


def _checked_text(raw: str, label: str) -> str:
    text = raw.strip()
    if not text:
        raise AccountError(f"Enter your {label}.", label)
    if len(text) > NAME_MAX_CHARS or not text.isprintable():
        raise AccountError(f"Your {label} can be at most {NAME_MAX_CHARS} printable characters.",
                           label)
    return text


def _checked_password(password: str, confirm: str) -> None:
    problem = passwords.policy_error(password, confirm)
    if problem:
        raise AccountError(problem, "password")


def _is_duplicate_email(exc: sqlite3.IntegrityError) -> bool:
    return "UNIQUE" in str(exc)


def sign_up(db: Path, *, name: str, organisation: str, email: str, password: str,
            confirm: str, now: datetime | None = None) -> None:
    """Record a sign-up, pending approval. An email already registered gets the same
    outcome and changes nothing, so the form never tells a visitor which emails exist."""
    clean_name, clean_org = _checked_text(name, "name"), _checked_text(organisation, "organisation")
    clean_email = _checked_email(email)
    _checked_password(password, confirm)
    hashed = passwords.hash_password(password)  # before the insert: both outcomes cost the same
    with store.connect(db) as conn:
        try:
            store.insert_user(conn, email=clean_email, name=clean_name, organisation=clean_org,
                              password_hash=hashed, state="pending", now=_now(now))
        except sqlite3.IntegrityError as exc:
            if not _is_duplicate_email(exc):
                raise


def log_in(db: Path, email: str, password: str, *, now: datetime | None = None) -> LoginResult:
    """Check a login. Only a correct password learns the account's state; a wrong password
    and an unknown email get the same answer. A password longer than passwords.MAX_CHARS is
    refused immediately, with a dummy verify so its timing still matches a real check, and
    is never claimed -- it cannot even count toward the lockout. Before the password is
    verified, the attempt is claimed -- counted, and checked against the lockout -- in one
    short UPDATE that is committed right away, so a burst of attempts arriving at once
    cannot all slip under the limit, and no write lock is held through the slow argon2
    verify that follows. The success UPDATE is conditioned on the session epoch read
    together with the verified hash: a reset that lands while the verify is running bumps
    that epoch first, so the UPDATE changes nothing and the answer is "wrong" -- the
    password just checked, and any rehash of it, is no longer the account's."""
    if len(password) > passwords.MAX_CHARS:
        passwords.verify_dummy(password[:passwords.MAX_CHARS])
        return LoginResult("wrong")
    moment = _now(now)
    with store.connect(db) as conn:
        found = store.credentials_by_email(conn, normalise_email(email))
        if found is None:
            passwords.verify_dummy(password)
            return LoginResult("wrong")
        user, stored = found
        claimed = store.claim_login_attempt(conn, user.id, limit=MAX_FAILED_LOGINS,
                                            lock_until=moment + LOCKOUT, now=moment)
        conn.commit()
        if not claimed:
            return LoginResult("locked", locked_until=store.user_by_id(conn, user.id).locked_until)
        if not passwords.verify(stored, password):
            return LoginResult("wrong")  # already counted by the claim above
        fields: dict[str, object] = {"failed_logins": 0, "locked_until": None}
        if passwords.needs_rehash(stored):
            fields["password_hash"] = passwords.hash_password(password)
        if user.state != "approved":
            changed = store.update_user(conn, user.id, expected_epoch=user.session_epoch,
                                        **fields)
            return LoginResult(user.state) if changed else LoginResult("wrong")
        changed = store.update_user(conn, user.id, expected_epoch=user.session_epoch,
                                    last_login_at=moment, **fields)
        if not changed:
            return LoginResult("wrong")
        return LoginResult("ok", user=store.user_by_id(conn, user.id))


def get_user(db: Path, user_id: int) -> User | None:
    with store.connect(db) as conn:
        return store.user_by_id(conn, user_id)


def list_users(db: Path) -> list[User]:
    with store.connect(db) as conn:
        return store.list_users(conn)


def list_actions(db: Path, limit: int = AUDIT_ROWS) -> list[AdminAction]:
    with store.connect(db) as conn:
        return store.list_actions(conn, limit)


def _acting_admin(conn: sqlite3.Connection, admin_id: int) -> User:
    """The admin, re-read from the store: the screens' own checks are not trusted alone."""
    admin = store.user_by_id(conn, admin_id)
    if admin is None or admin.role != "admin" or admin.state != "approved":
        raise AccountError("Only an administrator can do that.")
    return admin


def _target(conn: sqlite3.Connection, admin: User, user_id: int) -> User:
    target = store.user_by_id(conn, user_id)
    if target is None:
        raise AccountError("That account does not exist.")
    if target.id == admin.id:
        raise AccountError("You cannot change your own account here.")
    return target


def _transition(db: Path, admin_id: int, user_id: int, action: str, *,
                now: datetime | None, role: str | None = None) -> User:
    moment = _now(now)
    before, after = _TRANSITIONS[action]
    with store.connect(db) as conn:
        admin = _acting_admin(conn, admin_id)
        target = _target(conn, admin, user_id)
        if target.state != before:
            raise AccountError(f"This account is {target.state}; "
                               f"only {before} accounts can be {_DONE[action]}.")
        fields: dict[str, object] = {"state": after}
        if action == "approve":
            fields.update(role=role, approved_at=moment, approved_by=admin.id)
        changed = store.update_user(conn, target.id, expected_state=before, **fields)
        if not changed:
            raise AccountError("This account changed a moment ago; look at it again.")
        if action == "disable":
            store.bump_session_epoch(conn, target.id)  # ends every session already open
        store.record_action(conn, admin_id=admin.id, action=action, target_user_id=target.id,
                            detail=f"role={role}" if role else "", now=moment)
        return store.user_by_id(conn, target.id)


def approve(db: Path, admin_id: int, user_id: int, role: str, *,
            now: datetime | None = None) -> User:
    if role not in APPROVAL_ROLES:
        raise AccountError(f"An account is approved as {' or '.join(APPROVAL_ROLES)}.", "role")
    return _transition(db, admin_id, user_id, "approve", now=now, role=role)


def reject(db: Path, admin_id: int, user_id: int, *, now: datetime | None = None) -> User:
    return _transition(db, admin_id, user_id, "reject", now=now)


def disable(db: Path, admin_id: int, user_id: int, *, now: datetime | None = None) -> User:
    return _transition(db, admin_id, user_id, "disable", now=now)


def enable(db: Path, admin_id: int, user_id: int, *, now: datetime | None = None) -> User:
    return _transition(db, admin_id, user_id, "enable", now=now)


def issue_temporary_password(db: Path, admin_id: int, user_id: int, *,
                             now: datetime | None = None) -> str:
    """A new temporary password for an approved account, returned once for the admin to
    pass on. It is stored only as a hash, never in the audit trail; the account must
    choose its own at its next login; issuing one also clears a lockout and ends every
    session already signed in to the account, so a reset actually evicts whoever it was
    meant to lock out."""
    moment = _now(now)
    temporary = passwords.temporary_password()
    with store.connect(db) as conn:
        admin = _acting_admin(conn, admin_id)
        target = _target(conn, admin, user_id)
        if target.state != "approved":
            raise AccountError(f"This account is {target.state}; "
                               "only approved accounts get a temporary password.")
        changed = store.update_user(conn, target.id, expected_state="approved",
                                    password_hash=passwords.hash_password(temporary),
                                    must_change_password=True, failed_logins=0,
                                    locked_until=None)
        if not changed:
            raise AccountError("This account changed a moment ago; look at it again.")
        store.bump_session_epoch(conn, target.id)
        store.record_action(conn, admin_id=admin.id, action="temporary_password",
                            target_user_id=target.id,
                            detail="must choose a new password at the next login", now=moment)
    return temporary


def change_password(db: Path, user_id: int, password: str, confirm: str, *,
                    expected_epoch: int) -> User:
    """Set the account's own new password, and end every session of the account -- the
    caller re-signs its own session in with the account this returns. It may not be the
    one it has now -- a temporary password is known to the admin who issued it.

    The UPDATE is conditioned on `expected_epoch`, the epoch the caller last read the
    account with: a reset that lands before or during this call -- an admin's temporary
    password, or another session's own change -- bumps the epoch first, so the UPDATE
    (the new hash included) changes nothing, and this raises rather than overwriting it."""
    _checked_password(password, confirm)
    with store.connect(db) as conn:
        user = store.user_by_id(conn, user_id)
        current = store.password_hash(conn, user_id)
        if user is None or current is None or user.state != "approved":
            raise AccountError("This account cannot change its password.")
        if passwords.verify(current, password):
            raise AccountError("Choose a password different from the one you have now.",
                               "password")
        hashed = passwords.hash_password(password)
        changed = store.update_user(conn, user_id, expected_epoch=expected_epoch,
                                    password_hash=hashed, must_change_password=False)
        if not changed:
            raise AccountError(
                "Your session ended because this account's password was reset. "
                "Log in again.", "session")
        store.bump_session_epoch(conn, user_id)
        return store.user_by_id(conn, user_id)


def create_admin(db: Path, *, email: str, name: str, organisation: str, password: str,
                 confirm: str, now: datetime | None = None) -> User:
    """An approved admin, made on the server's command line: the first admin has nobody
    to approve it."""
    moment = _now(now)
    clean_email = _checked_email(email)
    clean_name, clean_org = _checked_text(name, "name"), _checked_text(organisation, "organisation")
    _checked_password(password, confirm)
    hashed = passwords.hash_password(password)
    with store.connect(db) as conn:
        try:
            user_id = store.insert_user(conn, email=clean_email, name=clean_name,
                                        organisation=clean_org, password_hash=hashed,
                                        state="approved", role="admin", now=moment,
                                        approved_at=moment)
        except sqlite3.IntegrityError as exc:
            if not _is_duplicate_email(exc):
                raise
            raise AccountError("An account with this email already exists.", "email") from None
        store.record_action(conn, admin_id=user_id, action="create_admin",
                            target_user_id=user_id, detail="created from the command line",
                            now=moment)
        return store.user_by_id(conn, user_id)

"""The Admin screen: approve or reject sign-ups, disable and re-enable accounts, issue
temporary passwords, and read the trail every admin action leaves.

Names and organisations are what visitors typed, so they appear only as plain text
(st.text) or table cells, never inside markdown. Every action goes through
app.accounts.service, which checks again that the one acting is an approved admin.
"""
from __future__ import annotations

import sqlite3
from collections.abc import Callable
from datetime import UTC, datetime
from functools import partial
from pathlib import Path

import pandas as pd
import streamlit as st

from app.accounts import service, store
from app.accounts.store import User
from app.components.local_time import local_time

FLASH_KEY = "adm_flash"
CONFIRM_REJECT_KEY = "adm_confirm_reject"
PENDING_COLUMNS = (4, 1.4, 1.6, 1.2)
ACCOUNT_COLUMNS = (3, 3, 1.2, 1.8)
STORE_UNAVAILABLE = "The account store is unavailable; try again in a moment."


def render(user: User) -> None:
    if user.role != "admin":
        st.error("Only an administrator can open this screen.")
        return
    db = store.db_path()
    st.header("Admin")
    flash = st.session_state.pop(FLASH_KEY, None)
    if flash:
        st.success(flash)
    users = service.list_users(db)
    _pending(db, user, [u for u in users if u.state == "pending"])
    _accounts(db, user, [u for u in users if u.state != "pending"])
    _audit(db)


def _act(action: Callable[[], object], message: str) -> None:
    """Run one account action. On success flash `message` and rerun, so every list shows
    the change; a refusal, or a store error, is shown where the button was rather than
    surfacing as a traceback."""
    try:
        action()
    except service.AccountError as exc:
        st.error(str(exc))
        return
    except sqlite3.Error:
        st.error(STORE_UNAVAILABLE)
        return
    st.session_state[FLASH_KEY] = message
    st.rerun()


def _pending(db: Path, admin: User, pending: list[User]) -> None:
    st.subheader("Waiting for approval")
    if not pending:
        st.caption("No sign-ups are waiting.")
        return
    st.caption("Sign-ups are not verified. Confirm each one with the person, through a "
              "channel you already trust, before you approve it.")
    for user in pending:
        with st.container(border=True):
            info, team, customer, reject = st.columns(PENDING_COLUMNS,
                                                      vertical_alignment="center")
            info.text(f"{user.name} · {user.organisation}\n"
                      f"{user.email} · signed up {local_time(user.created_at)}")
            if team.button("Approve as team", key=f"adm_team_{user.id}", type="primary",
                           width="stretch"):
                _act(partial(service.approve, db, admin.id, user.id, "team"),
                     f"Approved `{user.email}` as team.")
            if customer.button("Approve as customer", key=f"adm_customer_{user.id}",
                               width="stretch"):
                _act(partial(service.approve, db, admin.id, user.id, "customer"),
                     f"Approved `{user.email}` as customer.")
            _reject(db, admin, user, reject)


def _reject(db: Path, admin: User, user: User, column) -> None:
    """A rejection is final, so Reject asks once more before it acts."""
    if st.session_state.get(CONFIRM_REJECT_KEY) != user.id:
        if column.button("Reject", key=f"adm_reject_{user.id}", width="stretch"):
            st.session_state[CONFIRM_REJECT_KEY] = user.id
            st.rerun()
        return
    st.warning(f"Reject `{user.email}`? A rejected account cannot be approved later.")
    confirm, cancel, _ = st.columns((1, 1, 4))
    if confirm.button("Confirm reject", key=f"adm_reject_confirm_{user.id}", type="primary",
                      width="stretch"):
        st.session_state.pop(CONFIRM_REJECT_KEY, None)
        _act(partial(service.reject, db, admin.id, user.id), f"Rejected `{user.email}`.")
    if cancel.button("Cancel", key=f"adm_reject_cancel_{user.id}", width="stretch"):
        st.session_state.pop(CONFIRM_REJECT_KEY, None)
        st.rerun()


def _accounts(db: Path, admin: User, users: list[User]) -> None:
    st.subheader("Accounts")
    for user in users:
        with st.container(border=True):
            who, status, first, second = st.columns(ACCOUNT_COLUMNS,
                                                    vertical_alignment="center")
            who.text(f"{user.email}\n{user.name} · {user.organisation}")
            status.text(_status(user))
            if user.id == admin.id:
                first.caption("Your account")
            elif user.state == "approved":
                if first.button("Disable", key=f"adm_disable_{user.id}", width="stretch"):
                    _act(partial(service.disable, db, admin.id, user.id),
                         f"Disabled `{user.email}`.")
                if second.button("Temporary password", key=f"adm_temp_{user.id}",
                                 width="stretch"):
                    _temporary_password(db, admin, user)
            elif user.state == "disabled":
                if first.button("Re-enable", key=f"adm_enable_{user.id}", width="stretch"):
                    _act(partial(service.enable, db, admin.id, user.id),
                         f"Re-enabled `{user.email}`.")


def _status(user: User) -> str:
    lines = [f"{user.role or 'no role'} · {user.state}",
             f"created {local_time(user.created_at)} · "
             f"last login {local_time(user.last_login_at)}"]
    if user.must_change_password:
        lines.append("must choose a new password at the next login")
    if user.locked_until is not None and user.locked_until > datetime.now(UTC):
        lines.append(f"locked until {local_time(user.locked_until)}")
    return "\n".join(lines)


def _temporary_password(db: Path, admin: User, user: User) -> None:
    """Issue one and show it this once: it is stored only as a hash, so it cannot be
    shown again."""
    try:
        temporary = service.issue_temporary_password(db, admin.id, user.id)
    except service.AccountError as exc:
        st.error(str(exc))
        return
    st.warning(f"Temporary password for `{user.email}`, shown only now: pass it on privately. "
               "The account must choose its own password at its next login.")
    st.code(temporary, language=None)


def _audit(db: Path) -> None:
    st.subheader("Admin actions")
    actions = service.list_actions(db)
    if not actions:
        st.caption("No admin actions yet.")
        return
    st.dataframe(pd.DataFrame([{"When": local_time(a.at), "Admin": a.admin_email,
                                "Action": a.action, "Account": a.target_email or "—",
                                "Detail": a.detail} for a in actions]),
                 hide_index=True)
    st.caption(f"Newest first; the latest {service.AUDIT_ROWS} are shown.")

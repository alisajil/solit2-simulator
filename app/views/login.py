"""The login gate and the screens in front of the app: log in, sign up, the forced
password change, and a customer's holding screen.

`gate()` runs at the top of the app, after the page setup and the theme's CSS. It
returns only for an approved, signed-in account; for anyone else it renders one of
these screens and stops the run, so nothing below it runs.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

import streamlit as st

from app import auth
from app.accounts import passwords, service, store
from app.accounts.store import User
from app.components.local_time import CLOCK, local_time

# The screens sit in the middle column of three.
CARD_COLUMNS = (1, 1.3, 1)
STORE_UNAVAILABLE = ("The account store is unavailable, so nobody can log in right now. "
                     "Tell the administrator.")
SIGNED_UP = ("Thank you. Your sign-up waits for an administrator's approval; "
             "you can log in once it is approved.")
NO_ACCESS = "This account has no access. Contact the administrator."
WRONG = "The email or password is wrong."
PENDING = "Your account is waiting for approval by an administrator."
WORKSPACE_PENDING = ("Your account is approved. Customer workspaces, where your own designs "
                     "and runs will live, are not open yet; the administrator will tell you "
                     "when they are.")


def gate() -> User:
    try:
        return _gate(store.db_path())
    except (sqlite3.Error, OSError):
        st.error(STORE_UNAVAILABLE)
        st.stop()


def _gate(db: Path) -> User:
    store.init(db)
    user = auth.current_user(touch=True)
    if user is None:
        _visitor(db)
        st.stop()
    if user.must_change_password:
        _change_password(db, user)
        st.stop()
    return user


def _visitor(db: Path) -> None:
    notice = st.session_state.pop(auth.NOTICE_KEY, None)
    with st.columns(CARD_COLUMNS)[1]:
        st.title("SOLIT2 Simulator")
        st.caption("Log in to use the simulator. New here? Sign up, and an administrator "
                   "approves your account.")
        if notice:
            st.info(notice)
        log_in_tab, sign_up_tab = st.tabs(["Log in", "Sign up"])
        with log_in_tab:
            _log_in(db)
        with sign_up_tab:
            _sign_up(db)


def _log_in(db: Path) -> None:
    with st.form("login_form"):
        email = st.text_input("Email", key="login_email", max_chars=service.EMAIL_MAX_CHARS,
                              autocomplete="username")
        password = st.text_input("Password", key="login_password", type="password",
                                 autocomplete="current-password")
        submitted = st.form_submit_button("Log in", key="login_submit", type="primary")
    if not submitted:
        return
    result = service.log_in(db, email, password)
    if result.status == "ok":
        auth.sign_in(result.user)
        st.rerun()
    if result.status == "pending":
        st.warning(PENDING)
    elif result.status == "locked":
        st.error("Too many failed attempts. "
                 f"Try again after {local_time(result.locked_until, CLOCK)}.")
    elif result.status == "wrong":
        st.error(WRONG)
    else:
        st.error(NO_ACCESS)


def _sign_up(db: Path) -> None:
    with st.form("signup_form"):
        name = st.text_input("Name", key="signup_name", max_chars=service.NAME_MAX_CHARS,
                             autocomplete="name")
        organisation = st.text_input("Organisation", key="signup_org",
                                     max_chars=service.NAME_MAX_CHARS,
                                     autocomplete="organization")
        email = st.text_input("Email", key="signup_email", max_chars=service.EMAIL_MAX_CHARS,
                              autocomplete="email")
        password = st.text_input(f"Password (at least {passwords.MIN_CHARS} characters)",
                                 key="signup_password", type="password",
                                 autocomplete="new-password")
        confirm = st.text_input("Password again", key="signup_confirm", type="password",
                                autocomplete="new-password")
        submitted = st.form_submit_button("Sign up", key="signup_submit", type="primary")
    if not submitted:
        return
    try:
        service.sign_up(db, name=name, organisation=organisation, email=email,
                        password=password, confirm=confirm)
    except service.AccountError as exc:
        st.error(str(exc))
        return
    st.success(SIGNED_UP)


def _change_password(db: Path, user: User) -> None:
    with st.columns(CARD_COLUMNS)[1]:
        st.title("Choose a new password")
        st.write(f"You logged in as `{user.email}` with a temporary password. "
                 "Choose your own to continue.")
        with st.form("change_form"):
            password = st.text_input(f"New password (at least {passwords.MIN_CHARS} characters)",
                                     key="change_password", type="password",
                                     autocomplete="new-password")
            confirm = st.text_input("New password again", key="change_confirm", type="password",
                                    autocomplete="new-password")
            submitted = st.form_submit_button("Set password", key="change_submit",
                                              type="primary")
        if st.button("Log out", key="change_logout"):
            auth.sign_out(auth.LOGGED_OUT_NOTICE)
            st.rerun()
        if not submitted:
            return
        try:
            updated = service.change_password(db, user.id, password, confirm)
        except service.AccountError as exc:
            st.error(str(exc))
            return
        auth.sign_in(updated)
        st.rerun()


def render_workspace_pending() -> None:
    """A customer's only screen until customer workspaces exist (Phase 2 of the accounts
    spec): until then no project design, run or history is shown to a customer."""
    with st.columns(CARD_COLUMNS)[1]:
        st.title("Welcome")
        st.info(WORKSPACE_PENDING)

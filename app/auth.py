"""Who is signed in to this browser session, and when that ends.

The account id lives in `st.session_state` only, never in a URL or a cookie, so a browser
refresh starts a new session and asks for the login again (the accounts spec's stated
trade-off; the upgrade path is a small login gateway in front of the app). Every check
re-reads the account from the store, so an account an admin disables loses access at its
next interaction; a session left idle for IDLE_TIMEOUT_S ends; and a session whose
account's password was reset, or was otherwise changed while it stayed signed in, ends
too, because its session epoch no longer matches the account's.
"""
from __future__ import annotations

import sqlite3
import time

import streamlit as st

from app.accounts import service, store
from app.accounts.store import User

USER_ID_KEY = "auth_user_id"
LAST_SEEN_KEY = "auth_last_seen"
EPOCH_KEY = "auth_session_epoch"
NOTICE_KEY = "auth_notice"
IDLE_TIMEOUT_S = 8 * 60 * 60
IDLE_NOTICE = (f"Your session ended after {IDLE_TIMEOUT_S // 3600} hours without activity. "
               "Log in again.")
NO_ACCESS_NOTICE = "This account no longer has access. Contact the administrator."
REVOKED_NOTICE = ("Your session ended because this account's password was reset or its "
                  "access changed. Log in again.")
LOGGED_OUT_NOTICE = "You are logged out."


def sign_in(user: User) -> None:
    st.session_state[USER_ID_KEY] = user.id
    st.session_state[LAST_SEEN_KEY] = time.time()
    st.session_state[EPOCH_KEY] = user.session_epoch


def sign_out(notice: str | None = None) -> None:
    """End the session and drop everything it held -- designs, results, choices -- so
    whoever signs in next on this tab starts from nothing."""
    st.session_state.clear()
    if notice:
        st.session_state[NOTICE_KEY] = notice


def current_user(*, touch: bool) -> User | None:
    """The approved account signed in to this session, or None.

    Ends the session when it has been idle longer than IDLE_TIMEOUT_S, its account is
    no longer approved, or its session epoch no longer matches the one it signed in
    with (a password reset or a disable bumps the epoch, so every other session of the
    account ends). `touch` counts this run as activity: a full run of the app does, a
    fragment's timed refresh does not.
    """
    user_id = st.session_state.get(USER_ID_KEY)
    if user_id is None:
        return None
    now = time.time()
    if now - st.session_state.get(LAST_SEEN_KEY, 0.0) > IDLE_TIMEOUT_S:
        sign_out(IDLE_NOTICE)
        return None
    user = service.get_user(store.db_path(), user_id)
    if user is None or user.state != "approved":
        sign_out(NO_ACCESS_NOTICE)
        return None
    if user.session_epoch != st.session_state.get(EPOCH_KEY):
        sign_out(REVOKED_NOTICE)
        return None
    if touch:
        st.session_state[LAST_SEEN_KEY] = now
    return user


def guard_fragment() -> bool:
    """The first check in every fragment and dialog: `if not auth.guard_fragment(): return`.

    A fragment or dialog reruns without passing through the login gate -- and Streamlit
    keeps a session's stored fragments and dialogs even after a full run the gate
    stopped -- so every one of them must make this same check itself, or a session that
    has ended could still keep rendering, or acting on, one it registered earlier.

    A timed refresh is not activity either, yet it must not keep showing data to a
    session that has ended. A session that just ended reruns the whole app, which shows
    the login. A run with no session at all gets False, so the fragment renders nothing
    -- and only the fragment: st.stop() here would halt the whole script whenever the
    fragment runs inline in a full run. A store error fails closed (False, no
    traceback) rather than showing one.
    """
    had_session = st.session_state.get(USER_ID_KEY) is not None
    try:
        user = current_user(touch=False)
    except sqlite3.Error:
        return False
    if user is not None:
        return True
    if had_session:
        st.rerun()
    return False

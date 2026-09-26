"""Who is signed in to this browser session, and when that ends.

The account id lives in `st.session_state` only, never in a URL or a cookie, so a browser
refresh starts a new session and asks for the login again (the accounts spec's stated
trade-off; the upgrade path is a small login gateway in front of the app). Every check
re-reads the account from the store, so an account an admin disables loses access at its
next interaction, and a session left idle for IDLE_TIMEOUT_S ends.
"""
from __future__ import annotations

import time

import streamlit as st

from app.accounts import service, store
from app.accounts.store import User

USER_ID_KEY = "auth_user_id"
LAST_SEEN_KEY = "auth_last_seen"
NOTICE_KEY = "auth_notice"
IDLE_TIMEOUT_S = 8 * 60 * 60
IDLE_NOTICE = (f"Your session ended after {IDLE_TIMEOUT_S // 3600} hours without activity. "
               "Log in again.")
NO_ACCESS_NOTICE = "This account no longer has access. Contact the administrator."
LOGGED_OUT_NOTICE = "You are logged out."


def sign_in(user: User) -> None:
    st.session_state[USER_ID_KEY] = user.id
    st.session_state[LAST_SEEN_KEY] = time.time()


def sign_out(notice: str | None = None) -> None:
    """End the session and drop everything it held -- designs, results, choices -- so
    whoever signs in next on this tab starts from nothing."""
    st.session_state.clear()
    if notice:
        st.session_state[NOTICE_KEY] = notice


def current_user(*, touch: bool) -> User | None:
    """The approved account signed in to this session, or None.

    Ends the session when it has been idle longer than IDLE_TIMEOUT_S or its account is
    no longer approved. `touch` counts this run as activity: a full run of the app does,
    a fragment's timed refresh does not.
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
    if touch:
        st.session_state[LAST_SEEN_KEY] = now
    return user


def guard_fragment() -> None:
    """The first line of every timed fragment. A timed refresh does not pass through the
    login gate and is not activity, yet it must not keep showing data to a session that
    has ended: a session that just ended reruns the whole app, which shows the login, and
    a run with no session at all shows nothing."""
    had_session = st.session_state.get(USER_ID_KEY) is not None
    if current_user(touch=False) is None:
        if had_session:
            st.rerun()
        st.stop()

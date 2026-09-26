"""The signed-in session: who it is, when it ends, and timed fragments that respect it."""
import time

from streamlit.testing.v1 import AppTest

from app import auth
from app.accounts import store
from tests.conftest import sign_in

WHO = ("import streamlit as st\n"
       "from app import auth\n"
       "user = auth.current_user(touch=True)\n"
       "st.write(f'user {user.email if user else None}')\n")

GUARDED = ("import streamlit as st\n"
           "from app import auth\n"
           "st.write('page')\n"
           "@st.fragment\n"
           "def panel():\n"
           "    if not auth.guard_fragment():\n"
           "        return\n"
           "    st.write('panel')\n"
           "panel()\n"
           "st.write('after')\n")

SIGN_OUT = ("import streamlit as st\n"
            "from app import auth\n"
            "st.session_state['left_over'] = 'anything the session held'\n"
            "if st.button('out', key='out'):\n"
            "    auth.sign_out(auth.LOGGED_OUT_NOTICE)\n")


def _written(at: AppTest) -> list[str]:
    return [m.value for m in at.markdown]


def test_a_fresh_session_has_nobody_signed_in():
    at = AppTest.from_string(WHO)
    at.run()
    assert _written(at) == ["user None"]


def test_a_signed_in_session_is_its_account_and_a_full_run_is_activity():
    at = AppTest.from_string(WHO)
    user = sign_in(at)
    at.session_state[auth.LAST_SEEN_KEY] = time.time() - 600
    at.run()
    assert _written(at) == [f"user {user.email}"]
    assert time.time() - at.session_state[auth.LAST_SEEN_KEY] < 60


def test_a_session_idle_past_the_limit_ends_says_why_and_keeps_nothing():
    at = AppTest.from_string(WHO)
    sign_in(at)
    at.session_state["left_over"] = "anything the session held"
    at.session_state[auth.LAST_SEEN_KEY] = time.time() - auth.IDLE_TIMEOUT_S - 1
    at.run()
    assert _written(at) == ["user None"]
    assert at.session_state[auth.NOTICE_KEY] == auth.IDLE_NOTICE
    assert "left_over" not in at.session_state and auth.USER_ID_KEY not in at.session_state


def test_a_session_just_inside_the_idle_limit_continues():
    at = AppTest.from_string(WHO)
    user = sign_in(at)
    at.session_state[auth.LAST_SEEN_KEY] = time.time() - auth.IDLE_TIMEOUT_S + 60
    at.run()
    assert _written(at) == [f"user {user.email}"]


def test_an_account_no_longer_approved_ends_its_session():
    at = AppTest.from_string(WHO)
    user = sign_in(at)
    with store.connect(store.db_path()) as conn:
        store.update_user(conn, user.id, state="disabled")
    at.run()
    assert _written(at) == ["user None"]
    assert at.session_state[auth.NOTICE_KEY] == auth.NO_ACCESS_NOTICE


def test_sign_out_keeps_only_its_notice():
    at = AppTest.from_string(SIGN_OUT)
    sign_in(at)
    at.run()
    at.button(key="out").click().run()
    assert at.session_state[auth.NOTICE_KEY] == auth.LOGGED_OUT_NOTICE
    assert "left_over" not in at.session_state and auth.USER_ID_KEY not in at.session_state


def test_a_timed_fragment_renders_for_a_live_session():
    at = AppTest.from_string(GUARDED)
    sign_in(at)
    at.run()
    assert _written(at) == ["page", "panel", "after"]


def test_a_timed_fragment_is_not_activity():
    at = AppTest.from_string(GUARDED)
    sign_in(at)
    seen = time.time() - 600
    at.session_state[auth.LAST_SEEN_KEY] = seen
    at.run()
    assert at.session_state[auth.LAST_SEEN_KEY] == seen


def test_a_timed_fragment_of_an_ended_session_shows_nothing_and_ends_it():
    at = AppTest.from_string(GUARDED)
    sign_in(at)
    at.session_state[auth.LAST_SEEN_KEY] = time.time() - auth.IDLE_TIMEOUT_S - 1
    at.run()
    assert not at.exception
    assert "panel" not in _written(at)
    assert auth.USER_ID_KEY not in at.session_state
    assert _written(at) == ["page", "after"]


def test_a_timed_fragment_with_no_session_shows_nothing():
    at = AppTest.from_string(GUARDED)
    at.run()
    assert not at.exception
    assert _written(at) == ["page", "after"]

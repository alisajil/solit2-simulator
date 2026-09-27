"""Saved designs in the Design step: the picker's saved entries and the save panel.

The rules live in app/designs/service.py. This module only asks them, on behalf of the
signed-in account, and shows what they answer.
"""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass

import streamlit as st

from app import auth
from app.accounts import service as accounts
from app.accounts import store as accounts_store
from app.designs import service as designs
from app.designs import store as designs_store
from app.designs.service import Requester, SavedVersion
from app.designs.store import DesignRow

NAME_KEY = "save_name"
_SEEDED_KEY = "_saved_seeded"
_PENDING_KEY = "_saved_pending"
_NOTICE_KEY = "_saved_notice"
SAVED_PREFIX = "Saved · "


@dataclass(frozen=True)
class Seeded:
    """The saved design and version the form was seeded from."""
    design_id: int
    owner_id: int
    latest_version: int
    version: int


def requester() -> Requester | None:
    user = auth.current_user(touch=False)
    return None if user is None else Requester(user.id, user.role)


def label(row: DesignRow, emails: dict[int, str]) -> str:
    owner = emails.get(row.owner_id, f"user {row.owner_id}")
    return f"{SAVED_PREFIX}{row.name} · #{row.id} v{row.latest_version} · {owner}"


def saved_options() -> dict[str, DesignRow]:
    """Label -> design, for every saved design the signed-in account may see."""
    who = requester()
    if who is None:
        return {}
    try:
        rows = designs.list_visible(designs_store.db_path(), who)
        emails = {u.id: u.email for u in accounts.list_users(accounts_store.db_path())}
    except sqlite3.Error as exc:
        st.warning(f"Saved designs could not be read: {exc}")
        return {}
    return {label(row, emails): row for row in rows}


def pop_pending() -> tuple[int, int] | None:
    """The (design ID, version) a save just made, for the picker to point at."""
    return st.session_state.pop(_PENDING_KEY, None)


def version_key(design_id: int) -> str:
    return f"design_version_{design_id}"


def render_version_picker(row: DesignRow) -> SavedVersion | None:
    versions = list(range(row.latest_version, 0, -1))
    version = st.selectbox("Version", versions, key=version_key(row.id),
                           format_func=lambda v: f"v{v}" + (" (latest)" if v == versions[0] else ""))
    try:
        return designs.load(designs_store.db_path(), requester(), row.id, version)
    except (designs.DesignError, sqlite3.Error) as exc:
        st.warning(f"That saved design could not be opened: {exc}")
        return None


def set_seeded(row: DesignRow | None, version: int | None) -> None:
    st.session_state[_SEEDED_KEY] = (None if row is None or version is None
                                     else Seeded(row.id, row.owner_id, row.latest_version, version))


def seeded() -> Seeded | None:
    return st.session_state.get(_SEEDED_KEY)

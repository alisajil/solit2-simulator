"""Saved designs in the Design step: the picker's saved entries and the save panel.

The rules live in app/designs/service.py. This module only asks them, on behalf of the
signed-in account, and shows what they answer.
"""
from __future__ import annotations

import json
import re
import sqlite3
from collections.abc import Callable
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


DURABILITY_NOTE = ("Saved designs are kept on this server. On Streamlit Community Cloud a "
                   "reboot erases them; download a copy to keep one.")


def _file_name(name: str) -> str:
    return (re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-") or "design") + ".json"


def _save(action: Callable[[], SavedVersion]) -> None:
    try:
        saved = action()
    except designs.DesignError as exc:
        st.error(str(exc))
        return
    except sqlite3.Error as exc:
        st.error(f"The design store could not be written: {exc}")
        return
    st.session_state[_NOTICE_KEY] = f"Saved #{saved.design_id} v{saved.version} · sha {saved.sha}"
    st.session_state[_PENDING_KEY] = (saved.design_id, saved.version)
    st.rerun()


def render(raw: dict, missing: list[str]) -> None:
    """Save the design as it stands, as a new design or as the next version of the saved
    design it was seeded from, and offer it as a download."""
    who = requester()
    if who is None:
        return
    st.subheader("Save this design")
    notice = st.session_state.pop(_NOTICE_KEY, None)
    if notice:
        st.success(notice)
    if NAME_KEY not in st.session_state:
        st.session_state[NAME_KEY] = (raw.get("meta") or {}).get("name", "")
    name = st.text_input("Name", key=NAME_KEY)
    blocked = bool(missing)
    if blocked:
        st.caption("Saving needs the nozzle data above: " + ", ".join(missing))
    db = designs_store.db_path()
    source = seeded()
    left, right = st.columns(2)
    if source is not None and source.owner_id == who.user_id:
        if left.button(f"Save as v{source.latest_version + 1} of #{source.design_id}",
                       key="save_new_version", disabled=blocked):
            _save(lambda: designs.save_version(db, who, source.design_id, name, raw))
    if right.button("Save as new design", key="save_new_design", disabled=blocked):
        _save(lambda: designs.save_new(db, who, name, raw))
    if not blocked:
        named = {**raw, "meta": {**(raw.get("meta") or {}), "name": name}}
        st.download_button("Download JSON", data=json.dumps(named, indent=2),
                           file_name=_file_name(name), mime="application/json",
                           key="download_design")
    st.caption(DURABILITY_NOTE)

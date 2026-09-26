"""Create the first admin from a deploy secret when the store has none yet. Called on
every unauthenticated page load, so it also recovers the first admin after a host with
no persistent disk (a redeploy, a sleep/wake cycle) wipes the store -- it does real
work only once, then becomes a single cheap existence check.

The email and password never pass through this app's own account rules screen: they
are set directly wherever the deploy's secrets live (Streamlit Cloud's Secrets panel,
or the environment), never typed into a form or committed to the repo.
"""
from __future__ import annotations

import os
from pathlib import Path

import streamlit as st

from app.accounts import service, store

EMAIL_KEY = "SOLIT2_ADMIN_EMAIL"
PASSWORD_KEY = "SOLIT2_ADMIN_PASSWORD"
NAME_KEY = "SOLIT2_ADMIN_NAME"
ORGANISATION_KEY = "SOLIT2_ADMIN_ORGANISATION"
DEFAULT_NAME = "Administrator"
DEFAULT_ORGANISATION = "—"


def _secret(key: str) -> str | None:
    """`st.secrets` raises when no secrets.toml exists anywhere Streamlit looks (the
    common case for a plain `SOLIT2_*` environment variable), so a miss there falls
    back to the environment rather than crashing the page for every visitor."""
    try:
        value = st.secrets.get(key)
    except Exception:
        value = None
    return value or os.environ.get(key) or None


def ensure_admin(db: Path) -> None:
    email, password = _secret(EMAIL_KEY), _secret(PASSWORD_KEY)
    if not email or not password:
        return
    with store.connect(db) as conn:
        if store.has_admin(conn):
            return
    try:
        service.create_admin(db, email=email, name=_secret(NAME_KEY) or DEFAULT_NAME,
                             organisation=_secret(ORGANISATION_KEY) or DEFAULT_ORGANISATION,
                             password=password, confirm=password)
    except service.AccountError as exc:
        print(f"admin bootstrap from {EMAIL_KEY}/{PASSWORD_KEY} refused: {exc}")

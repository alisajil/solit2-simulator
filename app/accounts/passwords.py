"""Password hashing and the password policy.

argon2id through argon2-cffi. The library's default parameters (64 MiB, 3 passes,
4 lanes: RFC 9106's low-memory profile) exceed the OWASP minimum, and its verify
compares in constant time. A hash made under other parameters still verifies, and
`needs_rehash` tells the caller to store a fresh one.
"""
from __future__ import annotations

import secrets

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError

MIN_CHARS = 12
MAX_CHARS = 256
# Temporary passwords: four groups of four from an alphabet without look-alikes
# (no 0/O, no 1/l/I), so an admin can read one out without a mistake.
TEMPORARY_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZabcdefghjkmnpqrstuvwxyz23456789"
TEMPORARY_GROUPS = 4
TEMPORARY_GROUP_CHARS = 4

_HASHER = PasswordHasher()
# Checked when an email has no account, so that answer costs what a wrong password
# costs and its timing does not tell which emails exist.
_DUMMY_HASH = _HASHER.hash(secrets.token_urlsafe(16))


def hash_password(password: str) -> str:
    return _HASHER.hash(password)


def verify(stored_hash: str, password: str) -> bool:
    """True when `password` matches; False on a mismatch or on a hash that cannot be read."""
    try:
        return _HASHER.verify(stored_hash, password)
    except (VerificationError, InvalidHashError):
        return False


def verify_dummy(password: str) -> None:
    verify(_DUMMY_HASH, password)


def needs_rehash(stored_hash: str) -> bool:
    return _HASHER.check_needs_rehash(stored_hash)


def policy_error(password: str, confirm: str) -> str | None:
    """Why the password (typed twice) is refused, or None when it is acceptable."""
    if len(password) < MIN_CHARS:
        return f"The password must be at least {MIN_CHARS} characters."
    if len(password) > MAX_CHARS:
        return f"The password can be at most {MAX_CHARS} characters."
    if password != confirm:
        return "The two passwords do not match."
    return None


def temporary_password() -> str:
    return "-".join(
        "".join(secrets.choice(TEMPORARY_ALPHABET) for _ in range(TEMPORARY_GROUP_CHARS))
        for _ in range(TEMPORARY_GROUPS))

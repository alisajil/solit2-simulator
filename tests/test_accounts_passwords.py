"""Password hashing and policy: argon2id, rehash on new parameters, the policy's limits."""
import re

import argon2
from argon2 import PasswordHasher

from app.accounts import passwords

PASSWORD = "correct horse battery staple"
# OWASP's lowest-memory argon2id configuration: 19 MiB of memory, 2 passes.
OWASP_MIN_MEMORY_KIB, OWASP_MIN_PASSES = 19 * 1024, 2


def test_a_hash_is_argon2id_at_or_above_the_owasp_minimum():
    stored = passwords.hash_password(PASSWORD)
    params = argon2.extract_parameters(stored)
    assert params.type is argon2.Type.ID
    assert params.memory_cost >= OWASP_MIN_MEMORY_KIB
    assert params.time_cost >= OWASP_MIN_PASSES


def test_the_right_password_verifies_and_a_wrong_one_does_not():
    stored = passwords.hash_password(PASSWORD)
    assert passwords.verify(stored, PASSWORD)
    assert not passwords.verify(stored, PASSWORD + "!")


def test_one_password_hashes_differently_each_time():
    assert passwords.hash_password(PASSWORD) != passwords.hash_password(PASSWORD)


def test_an_unreadable_hash_is_a_mismatch_not_a_crash():
    assert not passwords.verify("not a hash", PASSWORD)


def test_a_hash_made_under_other_parameters_verifies_and_asks_for_a_rehash():
    old = PasswordHasher(time_cost=1, memory_cost=8, parallelism=1).hash(PASSWORD)
    assert passwords.verify(old, PASSWORD)
    assert passwords.needs_rehash(old)
    assert not passwords.needs_rehash(passwords.hash_password(PASSWORD))


def test_the_dummy_check_accepts_any_input_quietly():
    assert passwords.verify_dummy("anything at all") is None


def test_the_policy_bounds_the_length_and_wants_the_two_entries_to_match():
    shortest = "x" * passwords.MIN_CHARS
    longest = "x" * passwords.MAX_CHARS
    assert passwords.policy_error(shortest, shortest) is None
    assert passwords.policy_error(longest, longest) is None
    assert passwords.policy_error(shortest[:-1], shortest[:-1]) == (
        "The password must be at least 12 characters.")
    assert passwords.policy_error(longest + "x", longest + "x") == (
        "The password can be at most 256 characters.")
    assert passwords.policy_error(shortest, shortest + "y") == "The two passwords do not match."


def test_a_temporary_password_is_readable_random_and_passes_the_policy():
    char = f"[{passwords.TEMPORARY_ALPHABET}]"
    shape = re.compile(rf"{char}{{4}}(-{char}{{4}}){{3}}")
    first, second = passwords.temporary_password(), passwords.temporary_password()
    assert shape.fullmatch(first) and shape.fullmatch(second)
    assert first != second
    assert passwords.policy_error(first, first) is None

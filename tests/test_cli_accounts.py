"""`solit2 accounts create-admin`: the first admin, made on the server's command line."""
import json

import pytest

from app.accounts import service, store
from solit2 import cli

PASSWORD = "a long enough password"
ARGS = ["accounts", "create-admin", "--email", "Admin@Example.test", "--name", "Ada",
        "--organisation", "Ops"]


def _answers(monkeypatch, *replies):
    queue = iter(replies)
    monkeypatch.setattr(cli.getpass, "getpass", lambda prompt="": next(queue))


def test_create_admin_asks_twice_and_makes_an_approved_admin(monkeypatch, capsys):
    _answers(monkeypatch, PASSWORD, PASSWORD)
    assert cli.main(ARGS) == cli.EXIT_OK
    out, err = capsys.readouterr()
    assert json.loads(out)["email"] == "admin@example.test"
    assert PASSWORD not in out + err
    result = service.log_in(store.db_path(), "admin@example.test", PASSWORD)
    assert (result.status, result.user.role) == ("ok", "admin")


@pytest.mark.parametrize("first, second, message", [
    (PASSWORD, PASSWORD + "x", "The two passwords do not match."),
    ("short", "short", "The password must be at least 12 characters."),
])
def test_a_refused_password_is_a_clean_error_and_creates_nothing(monkeypatch, capsys, first,
                                                                  second, message):
    _answers(monkeypatch, first, second)
    assert cli.main(ARGS) == cli.EXIT_BAD_INPUT
    error = json.loads(capsys.readouterr().err)
    assert (error["error"], error["field"]) == (message, "password")
    assert service.list_users(store.db_path()) == []


def test_an_email_already_registered_is_refused(monkeypatch, capsys):
    _answers(monkeypatch, PASSWORD, PASSWORD, PASSWORD, PASSWORD)
    assert cli.main(ARGS) == cli.EXIT_OK
    capsys.readouterr()
    assert cli.main(ARGS) == cli.EXIT_BAD_INPUT
    assert "already exists" in json.loads(capsys.readouterr().err)["error"]


def test_the_password_is_never_an_argument():
    with pytest.raises(SystemExit):
        cli.main([*ARGS, "--password", PASSWORD])


def test_an_unavailable_store_is_reported_before_any_password_is_asked(monkeypatch, capsys,
                                                                       tmp_path):
    blocker = tmp_path / "a-file"
    blocker.write_text("not a directory")
    monkeypatch.setenv(store.DATA_DIR_ENV, str(blocker))
    _answers(monkeypatch)  # no replies: asking for a password would raise StopIteration
    assert cli.main(ARGS) == cli.EXIT_ENGINE
    assert "unavailable" in json.loads(capsys.readouterr().err)["error"]

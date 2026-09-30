import pytest

from solit2 import cli

BASELINE = "examples/designs/road-tunnel-twin-bore.json"


def test_the_command_writes_a_comparison_whose_late_run_activates_at_the_supplied_time(
        tmp_path, capsys):
    out = tmp_path / "activation.md"
    code = cli.main(["report", "activation-timing", BASELINE, "--late-s", "420",
                     "--out", str(out)])
    assert code == cli.EXIT_OK
    text = out.read_text()
    assert "# Activation timing" in text
    assert "Late activation time: 420 s, supplied by the user." in text
    assert "pinned at 420 s" in text


def test_the_late_time_is_required_and_has_no_default(capsys):
    with pytest.raises(SystemExit) as exit_info:
        cli.main(["report", "activation-timing", BASELINE])
    assert exit_info.value.code != 0
    assert "--late-s" in capsys.readouterr().err


def test_a_late_time_after_the_end_of_the_run_is_bad_input(tmp_path, capsys):
    code = cli.main(["report", "activation-timing", BASELINE, "--late-s", "99999",
                     "--out", str(tmp_path / "x.md")])
    assert code == cli.EXIT_BAD_INPUT
    assert "after the end of the run" in capsys.readouterr().err


def test_a_missing_design_is_bad_input(tmp_path):
    code = cli.main(["report", "activation-timing", str(tmp_path / "nope.json"),
                     "--late-s", "420"])
    assert code == cli.EXIT_BAD_INPUT


def test_an_engine_failure_exits_with_the_engine_code(monkeypatch):
    monkeypatch.setattr("solit2.engines.reduced.envelope.run",
                        lambda design, **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    assert cli.main(["report", "activation-timing", BASELINE, "--late-s", "420"]) == cli.EXIT_ENGINE

# tests/test_cli_report_virtual_test.py
import subprocess

SPEC = "examples/compliance/solit2-example.spec.json"


def test_the_cli_writes_an_html_file(tmp_path):
    out = tmp_path / "v.html"
    done = subprocess.run(
        ["uv", "run", "solit2", "report", "virtual-test", SPEC, "--out", str(out)],
        capture_output=True, text=True)
    assert done.returncode == 0, done.stderr
    text = out.read_text()
    assert text.strip().startswith("<!DOCTYPE html>")
    assert "VIRTUAL TEST" in text


def test_cli_engine_failure_exits_with_engine_code(monkeypatch, tmp_path):
    from solit2 import cli
    out = tmp_path / "v.html"
    monkeypatch.setattr("solit2.engines.reduced.envelope.run",
                        lambda design, **kw: (_ for _ in ()).throw(RuntimeError("boom")))
    result = cli.main(["report", "virtual-test", SPEC, "--out", str(out)])
    assert result == cli.EXIT_ENGINE

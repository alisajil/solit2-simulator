import json
import subprocess
import sys


def _run(args, **kwargs):
    return subprocess.run([sys.executable, "-m", "solit2.cli", *args],
                          capture_output=True, text=True, **kwargs)


def test_run_emits_a_valid_result_json(tmp_path):
    proc = _run(["run", "designs/og-dbr-rev0.json", "--no-history"])
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["meta"]["engine"] == "reduced"
    assert "hrr_control_mw" in payload["criteria"]
    assert "total" in payload["score"]


def test_run_appends_a_history_row(tmp_path):
    hist = tmp_path / "history.jsonl"
    proc = _run(["run", "designs/og-dbr-rev0.json", "--history", str(hist)])
    assert proc.returncode == 0, proc.stderr
    rows = [json.loads(line) for line in hist.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["design_name"] == "og-dbr-rev0"
    assert "score" in rows[0] and "gates_passed" in rows[0]


def test_bad_field_exits_two_with_a_named_error(tmp_path):
    raw = json.loads(open("designs/og-dbr-rev0.json").read())
    raw["nozzles"]["pressure_bar"] = 12.0
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(raw))
    proc = _run(["run", str(bad), "--no-history"])
    assert proc.returncode == 2
    err = json.loads(proc.stderr)
    assert "pressure_bar" in err["error"]
    assert err["fix"]


def test_history_subcommand_lists_the_leaderboard(tmp_path):
    hist = tmp_path / "history.jsonl"
    _run(["run", "designs/og-dbr-rev0.json", "--history", str(hist)])
    proc = _run(["history", "--history", str(hist), "--top", "5"])
    assert proc.returncode == 0, proc.stderr
    assert "og-dbr-rev0" in proc.stdout

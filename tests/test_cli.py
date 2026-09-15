import json
import subprocess
import sys


def _run(args, **kwargs):
    return subprocess.run([sys.executable, "-m", "solit2.cli", *args],
                          capture_output=True, text=True, **kwargs)


def test_run_emits_a_valid_result_json(tmp_path):
    proc = _run(["run", "examples/designs/road-tunnel-twin-bore.json", "--no-history"])
    assert proc.returncode == 0, proc.stderr
    payload = json.loads(proc.stdout)
    assert payload["meta"]["engine"] == "reduced"
    assert "target_ignited" in payload["criteria"]
    assert "criteria_unset" in payload["score"]
    assert "total" in payload["score"]


def test_run_appends_a_history_row(tmp_path):
    hist = tmp_path / "history.jsonl"
    proc = _run(["run", "examples/designs/road-tunnel-twin-bore.json", "--history", str(hist)])
    assert proc.returncode == 0, proc.stderr
    rows = [json.loads(line) for line in hist.read_text().splitlines()]
    assert len(rows) == 1
    assert rows[0]["design_name"] == "road-tunnel-twin-bore"
    assert "score" in rows[0] and "gates_passed" in rows[0]


def test_bad_field_exits_two_with_a_named_error(tmp_path):
    raw = json.loads(open("examples/designs/road-tunnel-twin-bore.json").read())
    raw["nozzles"]["pressure_bar"] = 12.0
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(raw))
    proc = _run(["run", str(bad), "--no-history"])
    assert proc.returncode == 2
    err = json.loads(proc.stderr)
    assert "pressure_bar" in err["error"]
    assert err["fix"]


def test_unwritable_history_path_does_not_lose_the_result(tmp_path):
    # a regular file where the history's parent directory has to be
    blocked = tmp_path / "blocked"
    blocked.write_text("not a directory")
    proc = _run(["run", "examples/designs/road-tunnel-twin-bore.json",
                 "--history", str(blocked / "history.jsonl")])
    assert proc.returncode != 1, "exit 1 is reserved for a validation miss"
    assert json.loads(proc.stdout)["meta"]["engine"] == "reduced"
    err = json.loads(proc.stderr)
    assert "blocked" in err["error"]
    assert err["fix"]


def test_engine_failure_exits_three_with_a_json_error(tmp_path):
    raw = json.loads(open("examples/designs/road-tunnel-twin-bore.json").read())
    raw["detection"]["threshold_c"] = 5000.0
    blind = tmp_path / "blind.json"
    blind.write_text(json.dumps(raw))
    proc = _run(["run", str(blind), "--no-history"])
    assert proc.returncode == 3
    err = json.loads(proc.stderr)
    assert "5000.0" in err["error"] and "60.0" in err["error"]
    assert err["fix"]


def test_history_subcommand_lists_the_leaderboard(tmp_path):
    hist = tmp_path / "history.jsonl"
    _run(["run", "examples/designs/road-tunnel-twin-bore.json", "--history", str(hist)])
    proc = _run(["history", "--history", str(hist), "--top", "5"])
    assert proc.returncode == 0, proc.stderr
    assert "road-tunnel-twin-bore" in proc.stdout

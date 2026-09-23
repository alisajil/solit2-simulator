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


def test_report_test_plan_emits_markdown_with_inputs_and_outcomes():
    proc = _run(["report", "test-plan", "examples/designs/road-tunnel-twin-bore.json"])
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith("# Fire test protocol")
    assert "road-tunnel-twin-bore" in proc.stdout
    assert "## 13. Predicted outcomes" in proc.stdout


def test_report_test_plan_writes_the_out_file(tmp_path):
    out = tmp_path / "plan.md"
    proc = _run(["report", "test-plan", "examples/designs/road-tunnel-twin-bore.json",
                 "--out", str(out)])
    assert proc.returncode == 0, proc.stderr
    assert out.read_text() == proc.stdout


def test_report_test_plan_bad_field_exits_two_with_a_named_error(tmp_path):
    raw = json.loads(open("examples/designs/road-tunnel-twin-bore.json").read())
    raw["nozzles"]["pressure_bar"] = 12.0
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(raw))
    proc = _run(["report", "test-plan", str(bad)])
    assert proc.returncode == 2
    err = json.loads(proc.stderr)
    assert "pressure_bar" in err["error"]


def test_report_correlation_puts_both_runs_side_by_side(tmp_path):
    test_out = tmp_path / "test.json"
    site_out = tmp_path / "site.json"
    _run(["run", "examples/designs/solit2-test-protocol.json", "--no-history",
          "--out", str(test_out)])
    _run(["run", "examples/designs/road-tunnel-twin-bore.json", "--no-history",
          "--out", str(site_out)])
    proc = _run(["report", "correlation", "--test", str(test_out), "--site", str(site_out)])
    assert proc.returncode == 0, proc.stderr
    assert proc.stdout.startswith("# Correlation")
    assert "solit2-test-protocol" in proc.stdout
    assert "road-tunnel-twin-bore" in proc.stdout


def test_report_correlation_missing_file_exits_two():
    proc = _run(["report", "correlation", "--test", "does/not/exist.json",
                 "--site", "examples/designs/road-tunnel-twin-bore.json"])
    assert proc.returncode == 2
    err = json.loads(proc.stderr)
    assert err["fix"]


def test_fds_deck_writes_a_namelist(tmp_path):
    out = tmp_path / "case.fds"
    proc = _run(["fds-deck", "examples/designs/road-tunnel-twin-bore.json", "--out", str(out)])
    assert proc.returncode == 0, proc.stderr
    text = out.read_text()
    assert text.startswith("&HEAD")
    assert "&TAIL /" in text


def test_fds_deck_honours_the_dx_override(tmp_path):
    # Both must succeed: two refused sizes both print nothing, and nothing
    # equals nothing -- which is how this test once passed with neither deck.
    coarse = _run(["fds-deck", "examples/designs/road-tunnel-twin-bore.json", "--dx", "0.75"])
    fine = _run(["fds-deck", "examples/designs/road-tunnel-twin-bore.json", "--dx", "0.25"])
    assert coarse.returncode == 0, coarse.stderr
    assert fine.returncode == 0, fine.stderr
    assert coarse.stdout != fine.stdout


def test_fds_deck_on_a_bad_design_exits_two(tmp_path):
    raw = json.loads(open("examples/designs/road-tunnel-twin-bore.json").read())
    raw["nozzles"]["pressure_bar"] = 12.0
    bad = tmp_path / "bad.json"
    bad.write_text(json.dumps(raw))
    proc = _run(["fds-deck", str(bad)])
    assert proc.returncode == 2
    assert json.loads(proc.stderr)["fix"]


def test_fds_status_reports_a_missing_run(tmp_path):
    proc = _run(["fds-status", str(tmp_path / "nope")])
    assert proc.returncode == 0, proc.stderr
    assert "failed" in proc.stdout


def test_run_with_engine_fds_refuses_without_a_binary(tmp_path):
    # no FDS on this machine: the pre-flight must say so plainly, not crash
    proc = _run(["run", "examples/designs/road-tunnel-twin-bore.json", "--engine", "fds", "--no-history"])
    assert proc.returncode == 3
    err = json.loads(proc.stderr)
    assert "fds" in err["error"]
    assert err["fix"]


def test_run_with_engine_fds_completes_end_to_end(tmp_path, monkeypatch, capsys):
    """The promised happy path: generate, launch, poll, read.

    There is no FDS binary on this machine by design, so the launch and the
    status polling are stubbed -- the status stub reports `running` once and
    then `done`, so the CLI's poll loop is actually entered and left -- and the
    reader is pointed at the committed device fixture.
    """
    import shutil
    from pathlib import Path

    from solit2 import cli
    from solit2.engines.fds import runner as fds_runner
    from solit2.engines.reduced.envelope import _design_sha
    from solit2.schema.design import Design

    design_path = "designs/og-dbr-rev0.json"
    chid = _design_sha(Design.load(design_path))
    fixtures = Path("tests/fixtures/fds")
    states = [{"state": "running", "progress": 0.0, "detail": ""},
              {"state": "done", "progress": 1.0, "detail": ""}]

    def fake_run(deck_path, out_dir):
        shutil.copy(fixtures / "sample_devc.csv", Path(out_dir) / f"{chid}_devc.csv")
        shutil.copy(fixtures / "sample_hrr.csv", Path(out_dir) / f"{chid}_hrr.csv")
        shutil.copy(fixtures / "sample_ctrl.csv", Path(out_dir) / f"{chid}_ctrl.csv")
        return Path(out_dir).name

    monkeypatch.setattr(fds_runner, "preflight", lambda: [])
    monkeypatch.setattr(fds_runner, "run", fake_run)
    monkeypatch.setattr(fds_runner, "status", lambda run_dir: states.pop(0) if states
                        else {"state": "done", "progress": 1.0, "detail": ""})
    monkeypatch.setattr(cli, "FDS_POLL_S", 0.0)

    hist = tmp_path / "history.jsonl"
    assert cli.main(["run", design_path, "--engine", "fds", "--history", str(hist)]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["meta"]["engine"] == "fds"
    assert "target_ignited" in payload["criteria"]
    assert "total" in payload["score"]
    assert (tmp_path / chid / "deck.fds").read_text().startswith("&HEAD")
    assert json.loads(hist.read_text().splitlines()[0])["design_name"] == "og-dbr-rev0"


def test_fds_deck_minutes_shortens_the_run_not_the_design():
    # zones.duration_min sizes the water tank and the cost index; --minutes
    # must shorten only the simulated window.
    full = _run(["fds-deck", "designs/og-cand-a.json"])
    short = _run(["fds-deck", "designs/og-cand-a.json", "--minutes", "20"])
    assert full.returncode == 0 and short.returncode == 0, short.stderr
    assert "T_END=3600.0" in full.stdout
    assert "T_END=1200.0" in short.stdout
    # everything except the T_END line is identical
    a = [ln for ln in full.stdout.splitlines() if not ln.startswith("&TIME")]
    b = [ln for ln in short.stdout.splitlines() if not ln.startswith("&TIME")]
    assert a == b


def test_fds_calibrate_e_writes_decks_and_reports_what_did_not_finish(tmp_path):
    out = tmp_path / "ecal"
    proc = _run(["fds-calibrate-e", "--anchor", "c4", "c5", "--e", "0.1", "0.2", "0.4", "0.8",
                "--dx", "0.6", "--out", str(out), "--report"])
    assert proc.returncode == 0, proc.stderr
    assert len(list(out.rglob("deck.fds"))) == 8
    assert (out / "report.md").exists() and (out / "report.json").exists()
    payload = json.loads((out / "report.json").read_text())
    assert payload["dx_m"] == 0.6
    assert len(payload["points"]) == 8
    assert all(not p["included"] for p in payload["points"]), "nothing was actually run"
    assert payload["fit"]["best_e"] is None


def test_fds_calibrate_e_on_an_unknown_anchor_exits_two(tmp_path):
    proc = _run(["fds-calibrate-e", "--anchor", "not-a-real-anchor", "--e", "0.4",
                "--dx", "0.6", "--out", str(tmp_path / "ecal")])
    assert proc.returncode == 2
    err = json.loads(proc.stderr)
    assert err["fix"]


def test_fds_calibrate_e_run_refuses_without_a_binary(tmp_path):
    proc = _run(["fds-calibrate-e", "--anchor", "c4", "--e", "0.4", "--dx", "0.6",
                "--out", str(tmp_path / "ecal"), "--run"])
    assert proc.returncode == 3
    err = json.loads(proc.stderr)
    assert "fds" in err["error"]


def test_fds_grid_study_writes_three_decks_and_reports_what_is_missing(tmp_path):
    out = tmp_path / "grid"
    proc = _run(["fds-grid-study", "designs/og-dbr-rev0.json", "--dx", "1.2", "0.75", "0.6",
                "--t-end", "300", "--out", str(out), "--report"])
    assert proc.returncode == 0, proc.stderr
    assert len(list(out.rglob("deck.fds"))) == 3
    payload = json.loads((out / "report.json").read_text())
    assert payload["t_end_s"] == 300.0
    assert len(payload["grids"]) == 3
    assert all(not g["included"] for g in payload["grids"])
    assert "needs exactly 3" in payload["error"]


def test_fds_grid_study_on_a_bad_dx_exits_two(tmp_path):
    proc = _run(["fds-grid-study", "designs/og-dbr-rev0.json", "--dx", "0.37", "0.6", "1.2",
                "--t-end", "300", "--out", str(tmp_path / "grid")])
    assert proc.returncode == 2
    err = json.loads(proc.stderr)
    assert "--dx" in err["field"]


def test_fds_campaign_refuses_without_a_binary_before_writing_anything(tmp_path):
    out = tmp_path / "campaign"
    proc = _run(["fds-campaign", "designs/og-dbr-rev0.json", "--grid-dx", "1.2", "0.75", "0.6",
                "--grid-t-end", "300", "--out", str(out)])
    assert proc.returncode == 3
    err = json.loads(proc.stderr)
    assert "fds" in err["error"]
    assert not out.exists(), "preflight must refuse before any deck is written"

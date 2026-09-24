"""`exec_run.run_foreground` against FAKE `mpiexec`/`fds` binaries on PATH --
the same style `tests/test_tier2_campaign_script.py` uses for a shell
wrapper, because this module's whole job is gluing together subprocess
launch, the resume/mesh-change check and the exec.log, and none of that is
exercised by monkeypatching `subprocess.run` away entirely.

The fake `fds` never simulates anything: it reads the CHID this test set in
`FAKE_FDS_CHID` and writes the two log lines `runner.status` parses,
standing in for an FDS run that either completed or errored. The fake
`mpiexec` logs its own argv and environment, strips `-n <count>` and any
further flags, and execs what is left -- exactly the shape both `runner.run`
and `run_foreground` invoke it in.
"""
import os
import re
import stat
from pathlib import Path

import pytest

from solit2.engines.fds import exec_run
from solit2.engines.fds import runner as runner_mod
from solit2.schema.design import Design

DESIGN_PATH = "designs/og-dbr-rev0.json"


def _make_executable(path: Path, content: str) -> None:
    path.write_text(content)
    path.chmod(path.stat().st_mode | stat.S_IEXEC | stat.S_IXGRP | stat.S_IXOTH)


def _fake_bin(tmp_path: Path, *, fds_ok: bool = True) -> tuple[Path, Path]:
    bindir = tmp_path / "bin"
    bindir.mkdir()
    mpiexec_log = tmp_path / "mpiexec.log"
    _make_executable(
        bindir / "mpiexec",
        "#!/usr/bin/env bash\n"
        'echo "argv: $@" >> "$FAKE_LOG"\n'
        'echo "OMP_NUM_THREADS=$OMP_NUM_THREADS" >> "$FAKE_LOG"\n'
        "shift 2\n"
        'while [[ $# -gt 0 && "$1" == -* ]]; do shift; done\n'
        'exec "$@"\n')
    tail = ('echo "STOP: FDS completed successfully" >> "${FAKE_FDS_CHID}.out"\n'
           if fds_ok else
           'echo "ERROR: the fake FDS was told to fail" >> "${FAKE_FDS_CHID}.out"\nexit 1\n')
    _make_executable(
        bindir / "fds",
        "#!/usr/bin/env bash\n"
        'echo "Total Time:        100.000 s" >> "${FAKE_FDS_CHID}.out"\n'
        + tail)
    return bindir, mpiexec_log


@pytest.fixture
def ready(monkeypatch):
    """An environment where preflight passes and PATH lookups are real, so a
    bin dir prepended to PATH by a test is what `_binary()`/`shutil.which`
    actually find."""
    monkeypatch.delenv(runner_mod.REMOTE_ENV, raising=False)
    monkeypatch.delenv(runner_mod.BIN_ENV, raising=False)
    monkeypatch.setattr(
        runner_mod.shutil, "disk_usage",
        lambda p: runner_mod.shutil._ntuple_diskusage(0, 0, runner_mod.MIN_FREE_BYTES * 2))


def _on_path(monkeypatch, bindir: Path) -> None:
    monkeypatch.setenv("PATH", f"{bindir}:{os.environ['PATH']}")


def _fresh_deck(run_dir: Path, chid: str = "c1") -> None:
    (run_dir / "deck.fds").write_text(
        f"&HEAD CHID='{chid}' /\n"
        "&MESH IJK=1,1,1, XB=0,1,0,1,0,1 /\n"
        "&MESH IJK=1,1,1, XB=1,2,0,1,0,1 /\n"
        "&TIME T_END=100.0 /\n"
        "&TAIL /\n")


def test_a_fresh_run_launches_mpiexec_with_the_deck_mesh_count(ready, monkeypatch, tmp_path):
    bindir, mlog = _fake_bin(tmp_path)
    _on_path(monkeypatch, bindir)
    monkeypatch.setenv("FAKE_LOG", str(mlog))
    monkeypatch.setenv("FAKE_FDS_CHID", "c1")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _fresh_deck(run_dir)

    returncode = exec_run.run_foreground(run_dir)

    assert returncode == 0
    assert (run_dir / "c1.out").exists()
    assert "STOP: FDS completed successfully" in (run_dir / "c1.out").read_text()
    argv_line = next(ln for ln in mlog.read_text().splitlines() if ln.startswith("argv:"))
    assert "-n 2" in argv_line
    assert argv_line.rstrip().endswith("deck.fds")
    assert "OMP_NUM_THREADS=1" in mlog.read_text()


def test_status_reads_done_after_a_successful_foreground_run(ready, monkeypatch, tmp_path):
    bindir, mlog = _fake_bin(tmp_path)
    _on_path(monkeypatch, bindir)
    monkeypatch.setenv("FAKE_LOG", str(mlog))
    monkeypatch.setenv("FAKE_FDS_CHID", "c1")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _fresh_deck(run_dir)

    exec_run.run_foreground(run_dir)

    assert runner_mod.status(run_dir)["state"] == "done"


def test_an_openmp_thread_the_caller_set_is_left_alone(ready, monkeypatch, tmp_path):
    bindir, mlog = _fake_bin(tmp_path)
    _on_path(monkeypatch, bindir)
    monkeypatch.setenv("FAKE_LOG", str(mlog))
    monkeypatch.setenv("FAKE_FDS_CHID", "c1")
    monkeypatch.setenv("OMP_NUM_THREADS", "4")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _fresh_deck(run_dir)

    exec_run.run_foreground(run_dir)

    assert "OMP_NUM_THREADS=4" in mlog.read_text()


def test_extra_mpiexec_args_from_the_env_var_are_forwarded(ready, monkeypatch, tmp_path):
    bindir, mlog = _fake_bin(tmp_path)
    _on_path(monkeypatch, bindir)
    monkeypatch.setenv("FAKE_LOG", str(mlog))
    monkeypatch.setenv("FAKE_FDS_CHID", "c1")
    monkeypatch.setenv(exec_run.MPIEXEC_ARGS_ENV, "--oversubscribe --mca btl self")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _fresh_deck(run_dir)

    exec_run.run_foreground(run_dir)

    argv_line = next(ln for ln in mlog.read_text().splitlines() if ln.startswith("argv:"))
    assert "--oversubscribe --mca btl self" in argv_line
    # the extra args sit between the rank count and the binary, not appended
    # after the deck name -- otherwise they would be parsed as FDS's own args
    assert argv_line.index("--oversubscribe") < argv_line.rindex("deck.fds")


def test_a_failing_fds_returns_nonzero_and_status_reads_failed(ready, monkeypatch, tmp_path):
    bindir, mlog = _fake_bin(tmp_path, fds_ok=False)
    _on_path(monkeypatch, bindir)
    monkeypatch.setenv("FAKE_LOG", str(mlog))
    monkeypatch.setenv("FAKE_FDS_CHID", "c1")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _fresh_deck(run_dir)

    returncode = exec_run.run_foreground(run_dir)

    assert returncode != 0
    assert runner_mod.status(run_dir)["state"] == "failed"


def test_exec_log_carries_ist_stamped_start_and_end_lines(ready, monkeypatch, tmp_path):
    bindir, mlog = _fake_bin(tmp_path)
    _on_path(monkeypatch, bindir)
    monkeypatch.setenv("FAKE_LOG", str(mlog))
    monkeypatch.setenv("FAKE_FDS_CHID", "c1")
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _fresh_deck(run_dir)

    exec_run.run_foreground(run_dir)

    text = (run_dir / exec_run.LOG_NAME).read_text()
    lines = [ln for ln in text.splitlines() if ln.strip()]
    assert any("start:" in ln for ln in lines)
    assert any("end:" in ln for ln in lines)
    assert not any("resume:" in ln for ln in lines), "a fresh run never resumes"
    for ln in lines:
        assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\+05:30\s", ln), ln


def test_no_deck_and_no_restart_files_raises(ready, monkeypatch, tmp_path):
    bindir, _ = _fake_bin(tmp_path)
    _on_path(monkeypatch, bindir)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    with pytest.raises(FileNotFoundError, match="deck.fds"):
        exec_run.run_foreground(run_dir)


def test_resume_regenerates_the_deck_from_design_json_and_logs_it(ready, monkeypatch, tmp_path):
    from solit2.engines.fds import deck as deck_mod

    design = Design.load(DESIGN_PATH)
    chid = deck_mod.chid(design)
    bindir, mlog = _fake_bin(tmp_path)
    _on_path(monkeypatch, bindir)
    monkeypatch.setenv("FAKE_LOG", str(mlog))
    monkeypatch.setenv("FAKE_FDS_CHID", chid)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "deck.fds").write_text(deck_mod.generate(design, t_end_s=300.0))
    (run_dir / "design.json").write_text(Path(DESIGN_PATH).read_text())
    (run_dir / "x.restart").write_text("")

    returncode = exec_run.run_foreground(run_dir, t_end_s=50.0)

    assert returncode == 0
    deck_text = (run_dir / "deck.fds").read_text()
    assert "RESTART=.TRUE." in deck_text
    assert "T_END=50.0" in deck_text
    log_text = (run_dir / exec_run.LOG_NAME).read_text()
    assert "resume:" in log_text
    assert "design.json" in log_text


def test_resume_without_design_json_refuses_before_touching_mpiexec(ready, monkeypatch, tmp_path):
    from solit2.engines.fds import deck as deck_mod

    design = Design.load(DESIGN_PATH)
    bindir, mlog = _fake_bin(tmp_path)
    _on_path(monkeypatch, bindir)
    monkeypatch.setenv("FAKE_LOG", str(mlog))
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    (run_dir / "deck.fds").write_text(deck_mod.generate(design))
    (run_dir / "x.restart").write_text("")
    # deliberately no design.json

    with pytest.raises(FileNotFoundError, match="design.json"):
        exec_run.run_foreground(run_dir)
    assert not mlog.exists(), "mpiexec must never be launched when the resume setup fails"


def test_a_setup_failure_is_logged_and_raises_without_launching(monkeypatch, tmp_path):
    monkeypatch.delenv(runner_mod.REMOTE_ENV, raising=False)
    monkeypatch.delenv(runner_mod.BIN_ENV, raising=False)
    monkeypatch.setattr(
        runner_mod.shutil, "disk_usage",
        lambda p: runner_mod.shutil._ntuple_diskusage(0, 0, runner_mod.MIN_FREE_BYTES * 2))
    monkeypatch.setattr(runner_mod.shutil, "which", lambda name: None)
    run_dir = tmp_path / "run"
    run_dir.mkdir()
    _fresh_deck(run_dir)

    with pytest.raises(RuntimeError):
        exec_run.run_foreground(run_dir)

    log_text = (run_dir / exec_run.LOG_NAME).read_text()
    assert "start: refused" in log_text

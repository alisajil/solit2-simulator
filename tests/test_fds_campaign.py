import pytest

from solit2.engines.fds import campaign
from solit2.schema.design import Design

BASELINE = "designs/og-dbr-rev0.json"


def test_estimate_rate_is_none_with_no_run_under_out(tmp_path):
    assert campaign.estimate_rate(tmp_path) is None


def test_estimate_rate_reads_the_most_recently_written_steps_csv(tmp_path, monkeypatch):
    from solit2.engines.fds import runner as runner_mod
    old_dir = tmp_path / "old_run"
    new_dir = tmp_path / "new_run"
    old_dir.mkdir()
    new_dir.mkdir()
    (old_dir / f"x{runner_mod.STEPS_SUFFIX}").write_text("stale\n")
    (new_dir / f"x{runner_mod.STEPS_SUFFIX}").write_text("fresh\n")
    import os
    import time
    now = time.time()
    os.utime(old_dir / f"x{runner_mod.STEPS_SUFFIX}", (now - 100, now - 100))
    os.utime(new_dir / f"x{runner_mod.STEPS_SUFFIX}", (now, now))

    seen = []

    def fake_live(run_dir):
        seen.append(run_dir)
        return {"rate_s_per_s": 3.5 if run_dir == new_dir else 1.0}
    monkeypatch.setattr(runner_mod, "live", fake_live)
    assert campaign.estimate_rate(tmp_path) == pytest.approx(3.5)
    assert seen[0] == new_dir, "the most recently written steps csv must be tried first"


def test_estimate_rate_falls_through_to_an_older_run_with_a_usable_rate(tmp_path, monkeypatch):
    """The newest run may not have enough steps yet for a rate; an older
    finished run's own measured rate is still real data, never invented."""
    from solit2.engines.fds import runner as runner_mod
    old_dir, new_dir = tmp_path / "old", tmp_path / "new"
    old_dir.mkdir()
    new_dir.mkdir()
    import os
    import time
    now = time.time()
    (old_dir / f"x{runner_mod.STEPS_SUFFIX}").write_text("a\n")
    (new_dir / f"x{runner_mod.STEPS_SUFFIX}").write_text("b\n")
    os.utime(old_dir / f"x{runner_mod.STEPS_SUFFIX}", (now - 100, now - 100))
    os.utime(new_dir / f"x{runner_mod.STEPS_SUFFIX}", (now, now))
    monkeypatch.setattr(runner_mod, "live",
                        lambda d: {"rate_s_per_s": None if d == new_dir else 2.0})
    assert campaign.estimate_rate(tmp_path) == pytest.approx(2.0)


def test_run_e_sweep_writes_decks_and_launches_every_point(tmp_path, monkeypatch):
    from solit2.engines.fds import runner as runner_mod
    monkeypatch.setattr(runner_mod, "status", lambda d: {"state": "done"})
    launched = []
    monkeypatch.setattr(runner_mod, "run", lambda deck, out: launched.append(out))
    out = campaign.run_e_sweep(("c4", "c5"), (0.2, 0.4), 0.6, tmp_path, poll_s=0.0)
    assert out == tmp_path / "ecal"
    assert list(out.rglob("deck.fds")), "decks must be written regardless of launch state"


def test_run_grid_study_writes_and_launches_three_grids(tmp_path, monkeypatch):
    from solit2.engines.fds import runner as runner_mod
    monkeypatch.setattr(runner_mod, "status", lambda d: {"state": "done"})
    out = campaign.run_grid_study(Design.load(BASELINE), (1.2, 0.75, 0.6), 600.0,
                                   tmp_path, poll_s=0.0)
    assert out == tmp_path / "grid"
    assert len(list(out.rglob("deck.fds"))) == 3


def test_run_full_duration_writes_one_deck_at_the_designs_own_duration(tmp_path, monkeypatch):
    from solit2.engines.fds import deck as deck_mod
    from solit2.engines.fds import runner as runner_mod
    design = Design.load(BASELINE)
    monkeypatch.setattr(runner_mod, "status", lambda d: {"state": "done"})
    run_dir = campaign.run_full_duration(design, tmp_path, poll_s=0.0)
    deck_text = (run_dir / "deck.fds").read_text()
    assert f"T_END={design.zones.duration_min * 60.0:.1f}" in deck_text
    assert deck_mod.chid(design) in str(run_dir)


def test_run_full_duration_does_not_overwrite_an_existing_deck(tmp_path, monkeypatch):
    """A deck already on disk may carry RESTART=.TRUE. from a previous resume;
    overwriting it unconditionally on every campaign re-run would erase that."""
    from solit2.engines.fds import deck as deck_mod
    from solit2.engines.fds import runner as runner_mod
    design = Design.load(BASELINE)
    run_dir = tmp_path / campaign.FULL_RUN_DIR_NAME / deck_mod.chid(design)
    run_dir.mkdir(parents=True)
    (run_dir / "deck.fds").write_text("SENTINEL")
    monkeypatch.setattr(runner_mod, "status", lambda d: {"state": "done"})
    campaign.run_full_duration(design, tmp_path, poll_s=0.0)
    assert (run_dir / "deck.fds").read_text() == "SENTINEL"


def test_run_campaign_prints_an_unknown_rate_with_nothing_finished_yet(tmp_path, monkeypatch):
    from solit2.engines.fds import runner as runner_mod
    monkeypatch.setattr(runner_mod, "status", lambda d: {"state": "done"})
    messages = []
    campaign.run_campaign(
        Design.load(BASELINE), tmp_path, e_anchor_ids=("c4",), e_values=(0.4,), dx_m=0.6,
        grid_dx=(1.2, 0.75, 0.6), grid_t_end_s=60.0, poll_s=0.0, print_fn=messages.append)
    assert any("rate" in m and "unknown" in m for m in messages)
    assert any("step 1/3" in m for m in messages)
    assert any("step 2/3" in m for m in messages)
    assert any("step 3/3" in m for m in messages)


def test_run_campaign_never_invents_a_rate_number(tmp_path, monkeypatch):
    """Only ever prints a rate this function actually measured -- see
    estimate_rate's own contract."""
    from solit2.engines.fds import runner as runner_mod
    monkeypatch.setattr(runner_mod, "status", lambda d: {"state": "done"})
    monkeypatch.setattr(campaign, "estimate_rate", lambda out: None)
    messages = []
    campaign.run_campaign(
        Design.load(BASELINE), tmp_path, e_anchor_ids=("c4",), e_values=(0.4,), dx_m=0.6,
        grid_dx=(1.2, 0.75, 0.6), grid_t_end_s=60.0, poll_s=0.0, print_fn=messages.append)
    rate_message = next(m for m in messages if "rate" in m)
    assert "unknown" in rate_message
    assert "simulated s / wall s" not in rate_message, \
        "the measured-rate phrasing must not appear when no rate was measured"

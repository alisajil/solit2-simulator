"""One run-state -> chip-class map, shared by the simulator's CFD panel and the
runs manager (M-3)."""
from app.components import run_states


def test_a_running_run_never_reads_as_a_pass():
    assert run_states.chip_class("running") != "pass"


def test_terminal_states_map_to_their_own_chip():
    assert run_states.chip_class("done") == "pass"
    assert run_states.chip_class("failed") == "fail"
    assert run_states.chip_class("stopped") == "fail"


def test_an_unreadable_run_reads_as_a_problem_not_a_neutral_unset():
    assert run_states.chip_class("unreadable") == "fail"


def test_an_unmapped_state_falls_back_to_unset():
    assert run_states.chip_class("some-future-state") == "unset"

import json

import pytest
from solit2.schema.presets import PRESET_DIR, load_calibration, reload_calibration
from validation import fit

CALIBRATION_PATH = PRESET_DIR / "calibration.json"


@pytest.fixture
def restored_calibration():
    """Put calibration.json back exactly as it was, however the test ends.

    `apply_vector` writes the real file on purpose -- the engine's physics
    modules read it through a memoised loader and a fit has to move what they
    actually read -- so a test that calls it has to undo itself.
    """
    original = CALIBRATION_PATH.read_text()
    yield
    CALIBRATION_PATH.write_text(original)
    reload_calibration()


def test_every_fitted_key_exists_in_the_calibration_with_a_value_inside_its_bounds():
    calibration = load_calibration()
    for group, name, low, high in fit.FITTED_KEYS:
        assert group in calibration, f"{group!r} is not a calibration group"
        assert name in calibration[group], f"{group}.{name} is not in the calibration"
        value = calibration[group][name]["value"]
        assert low <= value <= high, f"{group}.{name}={value} is outside [{low}, {high}]"


def test_apply_vector_rejects_a_value_outside_its_bounds(restored_calibration):
    """Test 7. The error has to name the constant and the bounds, or a fit that
    wandered out of range would be a number with no explanation attached."""
    group, name, low, high = fit.FITTED_KEYS[0]
    bad = fit.current_vector()
    bad[0] = high + 1.0

    with pytest.raises(ValueError) as exc:
        fit.apply_vector(bad)

    message = str(exc.value)
    assert name in message
    assert str(low) in message and str(high) in message
    assert str(high + 1.0) in message


def test_a_rejected_vector_leaves_the_calibration_untouched(restored_calibration):
    before = CALIBRATION_PATH.read_text()
    bad = fit.current_vector()
    bad[0] = fit.FITTED_KEYS[0][3] + 1.0

    with pytest.raises(ValueError):
        fit.apply_vector(bad)

    assert CALIBRATION_PATH.read_text() == before


def test_apply_vector_then_current_vector_round_trips(restored_calibration):
    """Test 8. Whatever the optimiser hands back has to be readable again, or
    the reported fit and the calibration on disk would drift apart."""
    wanted = [low + 0.37 * (high - low) for _, _, low, high in fit.FITTED_KEYS]

    fit.apply_vector(wanted)

    assert fit.current_vector() == pytest.approx(wanted)


def test_apply_vector_keeps_the_rest_of_the_calibration_intact(restored_calibration):
    before = json.loads(CALIBRATION_PATH.read_text())
    fitted = {(g, n) for g, n, _, _ in fit.FITTED_KEYS}

    fit.apply_vector(fit.current_vector())

    after = json.loads(CALIBRATION_PATH.read_text())
    assert after.keys() == before.keys()
    for group, entries in before.items():
        assert after[group].keys() == entries.keys()
        for name, entry in entries.items():
            if (group, name) not in fitted:
                assert after[group][name] == entry, f"{group}.{name} was not being fitted"


def test_ceiling_excess_coefficient_is_published_not_fitted():
    """The fit may not move the ceiling correlation: at its 0.3 floor it was
    buying suppressed HRR with 3x-low temperatures (accuracy-roadmap item 3)."""
    assert all(name != "ceiling_excess_coefficient" for _, name, _, _ in fit.FITTED_KEYS)
    assert load_calibration()["thermal"]["ceiling_excess_coefficient"]["value"] == 1.0


def test_fitted_keys_round_trip_through_the_calibration_file(restored_calibration):
    vector = fit.current_vector()
    fit.apply_vector(vector)
    assert fit.current_vector() == pytest.approx(vector)


def test_the_flame_length_coefficient_is_constrained_not_fitted(restored_calibration):
    """thermal.flame_length_coefficient is deliberately NOT in FITTED_KEYS.

    It decides how far a flame that cannot rise into the headroom reaches
    downstream, and so whether the Annex 7 section 7.2.1 target is in flame
    contact. That outcome is a BOOLEAN, so its residual is a step function of
    this constant and least_squares sees exactly zero gradient between steps -- a
    run with it in FITTED_KEYS left it at 4.3, untouched, while every other
    constant moved. It is set by bisection against the c4 measured target
    outcome instead, so listing it as fitted would be a claim the fit cannot
    honour.

    The guard is the pairing: the constant exists and is calibratable by hand,
    and it is absent from the fitted set."""
    names = [(group, name) for group, name, _, _ in fit.FITTED_KEYS]
    assert ("thermal", "flame_length_coefficient") not in names
    assert "flame_length_coefficient" in load_calibration()["thermal"]

    # and the value honours the constraint it was set from: above 1.1666 the c4
    # target ignites, which contradicts the measured outcome that anchor carries.
    assert load_calibration()["thermal"]["flame_length_coefficient"]["value"] < 1.1666


def test_the_flame_length_coefficient_records_what_calibrated_it():
    """A constant that was calibrated must not still claim a literature
    provenance: `anchor` says what a value was set against, and "none" would tell
    a reader it was read off a correlation and left alone. This one was set by
    bisection against c4's measured target outcome, not by the fit, and the
    entry has to say so -- naming the anchor without naming the method would
    imply it moves with every refit, and it does not."""
    entry = load_calibration()["thermal"]["flame_length_coefficient"]
    assert entry["anchor"] != "none"
    # `anchor` is machine-parsed as a comma-separated list of anchor ids, so the
    # METHOD cannot live there -- putting prose in it breaks the independence
    # checks that read it. It goes in the note.
    assert entry["anchor"] == "c4"
    assert "CONSTRAINT" in entry["note"]


def test_apply_vector_is_visible_to_the_memoised_loader(restored_calibration):
    """A fit that wrote the file but left the cached dict in place would move
    nothing at all, and every residual would come back identical."""
    group, name, low, high = fit.FITTED_KEYS[0]
    moved = fit.current_vector()
    moved[0] = low + 0.5 * (high - low)

    fit.apply_vector(moved)

    assert load_calibration()[group][name]["value"] == pytest.approx(moved[0])

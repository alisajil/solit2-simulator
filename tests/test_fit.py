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


def test_apply_vector_is_visible_to_the_memoised_loader(restored_calibration):
    """A fit that wrote the file but left the cached dict in place would move
    nothing at all, and every residual would come back identical."""
    group, name, low, high = fit.FITTED_KEYS[0]
    moved = fit.current_vector()
    moved[0] = low + 0.5 * (high - low)

    fit.apply_vector(moved)

    assert load_calibration()[group][name]["value"] == pytest.approx(moved[0])

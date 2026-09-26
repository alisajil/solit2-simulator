import pytest
from solit2.schema.presets import list_presets


def test_list_presets_finds_shipped_and_example_tunnels():
    names = list_presets("tunnel")
    assert "solit2_test" in names            # shipped (solit2/presets/)
    assert "twin_bore_11m" in names           # example (examples/presets/)
    assert names == sorted(names)


def test_list_presets_rejects_an_unknown_kind():
    with pytest.raises(KeyError, match="unknown preset kind"):
        list_presets("nope")

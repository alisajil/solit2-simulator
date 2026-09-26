"""The theme is configuration; these tests pin the contract the views rely on."""
import re
import tomllib
from pathlib import Path

from streamlit.testing.v1 import AppTest

REQUIRED_TOKENS = {"primaryColor", "backgroundColor", "secondaryBackgroundColor",
                   "textColor", "borderColor", "redColor", "greenColor", "orangeColor"}


def test_theme_defines_light_and_dark_with_every_token():
    cfg = tomllib.loads(Path(".streamlit/config.toml").read_text())
    for variant in ("light", "dark"):
        assert REQUIRED_TOKENS <= set(cfg["theme"][variant]), variant
    assert cfg["theme"]["font"].startswith("IBM Plex Sans")
    assert cfg["theme"]["codeFont"].startswith("IBM Plex Mono")
    assert cfg["theme"]["light"]["primaryColor"] == "#1D8F8A"
    assert cfg["theme"]["dark"]["backgroundColor"] == "#1B2230"


def test_inject_renders_exactly_one_style_block():
    at = AppTest.from_string("from app import theme\ntheme.inject()\n")
    at.run()
    assert not at.exception
    assert sum("<style>" in m.value for m in at.markdown) == 1
    assert any("fonts.googleapis.com" in m.value for m in at.markdown)


def test_the_style_block_has_no_blank_lines():
    """Streamlit's markdown renderer ends a raw-HTML block at the first blank line.

    A blank line inside `<style>` therefore pushes every later rule group out of the
    stylesheet and renders it as visible CSS text at the top of the page — which the
    "exactly one <style> block" check above cannot catch, since the source string is
    still well-formed.
    """
    from app import theme

    inner = theme.CSS[theme.CSS.index("<style>"):theme.CSS.index("</style>")]
    assert re.search(r"\n[ \t]*\n", inner) is None


def test_the_toml_colours_match_the_palette():
    """Streamlit reads TOML, not Python, so the tokens are necessarily stated twice.

    Nothing but this test stops the two copies drifting — and a drift would show as a
    chart disagreeing with the chip beside it, which reads as a bug in the numbers.
    """
    from app import palette

    theme = tomllib.loads(Path(".streamlit/config.toml").read_text())["theme"]
    wanted = {"primaryColor": palette.PRIMARY, "greenColor": palette.PASS,
              "redColor": palette.FAIL, "orangeColor": palette.UNSET}
    for key, token in wanted.items():
        assert theme["light"][key].upper() == token.upper(), key
    # Dark is deliberately not the same colour: the same token on a dark ground reads
    # muddy, so each is brightened. It must still be *defined*, or a chip loses its
    # meaning in dark mode.
    for key in wanted:
        assert theme["dark"][key].startswith("#"), key
        assert theme["dark"][key].upper() != theme["light"][key].upper(), key


def test_rgba_expands_a_token_without_changing_it():
    from app import palette

    assert palette.rgba("#1D8F8A", 0.5) == "rgba(29,143,138,0.5)"
    assert palette.rgba(palette.GREY, 0.35) == "rgba(138,148,166,0.35)"


def test_rgba_never_emits_scientific_notation():
    """`:g` formatting switches to exponential below 1e-4, which Plotly's own colour
    parser rejects outright -- caught live via a real ignition-progress fraction that
    landed at 4.8e-05. Any alpha a real fraction can produce must stay parseable."""
    from app import palette

    for alpha in (4.8271e-05, 1e-8, 0.0, 0.00001, 0.999999):
        text = palette.rgba(palette.FAIL, alpha)
        assert "e-" not in text and "e+" not in text, text
        assert text.startswith("rgba(") and text.endswith(")")


def test_dark_is_the_default_theme():
    cfg = tomllib.loads(Path(".streamlit/config.toml").read_text())
    assert cfg["theme"]["base"] == "dark"


def test_the_instrument_styles_are_defined_and_respect_reduced_motion():
    from app import theme

    for cls in (".sim-head", ".sim-label", ".tiles", ".tile-value", ".diag", ".pill", ".dot"):
        assert cls in theme.CSS, cls
    assert "prefers-reduced-motion" in theme.CSS

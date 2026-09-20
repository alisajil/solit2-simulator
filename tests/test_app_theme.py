"""The theme is configuration; these tests pin the contract the views rely on."""
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

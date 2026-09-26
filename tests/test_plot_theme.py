"""Figures drawn with theme=None follow the viewer's Streamlit theme."""
import tomllib
from pathlib import Path

from app import plot_theme

CONFIG = tomllib.loads(Path(".streamlit/config.toml").read_text())["theme"]


def test_the_dark_template_uses_the_dark_palette():
    t = plot_theme.template("dark")
    assert t.layout.paper_bgcolor.upper() == CONFIG["dark"]["backgroundColor"].upper()
    assert t.layout.font.color.upper() == CONFIG["dark"]["textColor"].upper()


def test_the_light_template_uses_the_light_palette():
    t = plot_theme.template("light")
    assert t.layout.paper_bgcolor.upper() == CONFIG["light"]["backgroundColor"].upper()


def test_an_unknown_theme_falls_back_to_dark():
    assert plot_theme.template(None).layout.paper_bgcolor == plot_theme.template("dark").layout.paper_bgcolor

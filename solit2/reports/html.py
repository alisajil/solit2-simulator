# solit2/reports/html.py
"""A self-contained HTML document shell shared by every HTML report: the print
stylesheet, the mandatory prediction band, a table builder, and offline Plotly
embedding. No report-specific content lives here.
"""
from __future__ import annotations

import html as _html
import re

import plotly.graph_objects as go
import plotly.io as pio

BAND_TEXT = "VIRTUAL TEST — prediction, not a measurement."
# Appears once in an inline Plotly bundle (its licence header) and nowhere else.
BUNDLE_MARK = "plotly.js v"

PRINT_CSS = """
@page { size: A4; margin: 20mm 16mm; }
body { font-family: -apple-system, Helvetica, Arial, sans-serif; color: #111;
       margin: 0 auto; max-width: 960px; padding: 0 16px; }
header.report-header { position: sticky; top: 0; background: #fff;
       border-bottom: 2px solid #b00; padding: 8px 0; z-index: 1; }
.band { background: #b00; color: #fff; font-weight: 700; text-align: center;
        padding: 6px 0; letter-spacing: 0.02em; }
section { break-inside: avoid-page; margin-top: 24px; }
h2 { border-bottom: 1px solid #ccc; padding-bottom: 4px; }
table { border-collapse: collapse; width: 100%; margin: 12px 0; }
th, td { border: 1px solid #ccc; padding: 4px 8px; text-align: left;
         font-variant-numeric: tabular-nums; }
th { background: #f2f2f2; }
@media print {
  /* position: fixed repeats on every printed page in Chromium and Firefox;
     position: running() is a Paged-Media feature browsers ignore. */
  header.report-header { position: fixed; top: 0; left: 0; right: 0; }
  body { padding-top: 56px; }
  section { page-break-after: always; }
}
"""


def escape(text: str) -> str:
    """HTML-escape untrusted text (design names come from user-supplied files)."""
    return _html.escape(text)


_SCRIPT_BODY = re.compile(r"<script\b[^>]*>.*?</script>", re.DOTALL | re.IGNORECASE)
_SCRIPT_OPEN = re.compile(r"<script\b[^>]*>", re.IGNORECASE)
_EXTERNAL = (
    re.compile(r"<script\b[^>]*\ssrc\s*=", re.IGNORECASE),
    re.compile(r"<link\b", re.IGNORECASE),
    re.compile(r"""\b(?:src|href|action)\s*=\s*["']?(?:https?:)?//""", re.IGNORECASE),
    re.compile(r"@import\b", re.IGNORECASE),
    re.compile(r"""url\(\s*["']?(?:https?:)?//""", re.IGNORECASE),
)


def external_references(document_html: str) -> list[str]:
    """Anything that would make a browser fetch something when the file opens.

    Script BODIES are skipped: the embedded Plotly bundle holds many `https://`
    strings that are never requested. A `<script src=...>` tag is still caught,
    because the opening tag is kept when its body is dropped."""
    outside = _SCRIPT_BODY.sub(lambda m: _SCRIPT_OPEN.match(m.group(0)).group(0) + "</script>",
                               document_html)
    return [m.group(0) for rx in _EXTERNAL for m in rx.finditer(outside)]


def without_scripts(document_html: str) -> str:
    """The page with every <script>...</script> removed, for scanning what a reader sees."""
    return _SCRIPT_BODY.sub("", document_html)


def document(title: str, sections: list[tuple[str, str]]) -> str:
    """`sections` is (heading, inner_html) pairs, in the order they appear.
    Every section repeats the band; the header is fixed so it repeats on
    every printed page."""
    safe_title = escape(title)
    body_sections = "\n".join(
        f'<section id="s{i}">\n<div class="band">{BAND_TEXT}</div>\n'
        f"<h2>{i}. {escape(heading)}</h2>\n{inner}\n</section>"
        for i, (heading, inner) in enumerate(sections, start=1))
    return (
        "<!DOCTYPE html>\n"
        f'<html lang="en"><head><meta charset="utf-8"><title>{safe_title}</title>\n'
        f"<style>{PRINT_CSS}</style></head>\n"
        "<body>\n"
        f'<header class="report-header"><div class="band">{BAND_TEXT}</div>'
        f"<strong>{safe_title}</strong></header>\n"
        f"{body_sections}\n"
        "</body></html>\n"
    )


def table(headers: list[str], rows: list[list[str]]) -> str:
    head = "".join(f"<th>{escape(h)}</th>" for h in headers)
    body = "\n".join(
        "<tr>" + "".join(f"<td>{escape(str(cell))}</td>" for cell in row) + "</tr>"
        for row in rows)
    return f"<table><thead><tr>{head}</tr></thead><tbody>\n{body}\n</tbody></table>"


def figure_html(fig: go.Figure, *, first: bool) -> str:
    """`first=True` embeds the Plotly JS bundle inline (once per document);
    every later figure in the same document passes `first=False`."""
    return pio.to_html(fig, full_html=False,
                       include_plotlyjs="inline" if first else False,
                       config={"displayModeBar": False})

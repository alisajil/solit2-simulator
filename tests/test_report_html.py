# tests/test_report_html.py
import plotly.graph_objects as go

from solit2.reports import html


def test_document_contains_no_network_reference():
    out = html.document("Test", [("Introduction", "<p>hello</p>")])
    assert "http://" not in out and "https://" not in out
    assert "<script src=" not in out
    assert "<link " not in out or 'rel="stylesheet" href="http' not in out


def test_document_carries_the_prediction_band_and_is_well_formed():
    out = html.document("Test", [("Introduction", "<p>hello</p>")])
    assert html.BAND_TEXT in out
    assert out.strip().startswith("<!DOCTYPE html>")
    assert "<h2>1. Introduction</h2>" in out


def test_table_escapes_untrusted_cell_content():
    out = html.table(["Name"], [["<script>alert(1)</script>"]])
    assert "<script>alert(1)</script>" not in out
    assert "&lt;script&gt;" in out


def test_only_the_first_figure_embeds_plotly_js():
    fig = go.Figure(data=[go.Scatter(x=[1, 2], y=[3, 4])])
    first = html.figure_html(fig, first=True)
    second = html.figure_html(fig, first=False)
    assert "Plotly.newPlot" in first and html.BUNDLE_MARK in first  # the bundle itself
    assert html.BUNDLE_MARK not in second  # no bundle the second time
    assert "Plotly.newPlot" in second  # but the figure still renders


def test_external_references_finds_a_cdn_script_and_ignores_urls_inside_script_bodies():
    bad = '<html><script src="https://cdn.example/x.js"></script><link href="a.css"></html>'
    assert html.external_references(bad)
    # The embedded Plotly bundle contains https:// strings; they are never fetched.
    fine = "<html><script>var help = 'https://example.org/docs';</script><p>ok</p></html>"
    assert html.external_references(fine) == []
    assert html.external_references('<img src="//host/x.png">')
    assert html.external_references('<p style="background:url(http://h/x)">')


def test_a_real_plotly_bundle_is_not_an_external_reference():
    fig = go.Figure(data=[go.Scatter(x=[1, 2], y=[3, 4])])
    doc = html.document("T", [("Figure", html.figure_html(fig, first=True))])
    assert html.external_references(doc) == []


def test_escape_neutralises_markup():
    assert html.escape("<b>&") == "&lt;b&gt;&amp;"


def test_without_scripts_drops_script_bodies_but_keeps_the_page():
    doc = "<p>hello</p><script>var logo = 1;</script><p>world</p>"
    assert html.without_scripts(doc) == "<p>hello</p><p>world</p>"

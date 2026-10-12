from __future__ import annotations

from tether.capabilities import MarkdownLevel
from tether.render.markdown import render_markdown


def test_rich_keeps_heading_and_code():
    text, media = render_markdown("# Title\n\n```py\nx=1\n```", MarkdownLevel.RICH)
    assert "# Title" in text
    assert "```py" in text
    assert not media


def test_basic_downgrades_heading_to_bold():
    text, _ = render_markdown("# Title", MarkdownLevel.BASIC)
    assert text == "**Title**"


def test_none_uppercases_heading_and_plain_links():
    text, _ = render_markdown("# title\n\n[t](http://x)", MarkdownLevel.NONE)
    assert "TITLE" in text
    assert "t (http://x)" in text


def test_table_rich_vs_basic():
    table = "| a | b |\n|---|---|\n| 1 | 2 |"
    rich, _ = render_markdown(table, MarkdownLevel.RICH)
    assert "| a | b |" in rich
    basic, _ = render_markdown(table, MarkdownLevel.BASIC)
    assert "a: 1" in basic


def test_images_extracted_to_media():
    text, media = render_markdown("![shot](http://img/x.png)", MarkdownLevel.RICH)
    assert len(media) == 1
    assert media[0].url == "http://img/x.png"
    assert media[0].caption == "shot"


def test_list_rendering():
    text, _ = render_markdown("- a\n- b", MarkdownLevel.STANDARD)
    assert "- a" in text
    assert "- b" in text

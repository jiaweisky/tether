"""Rendering layer: parse Markdown and turn a document into an outbound plan."""

from __future__ import annotations

from tether.models import RichDoc, Segment
from tether.render.markdown import MarkdownRenderer, render_markdown
from tether.render.renderer import DefaultRenderer

__all__ = [
    "DefaultRenderer",
    "MarkdownRenderer",
    "render_markdown",
    "RichDoc",
    "Segment",
]

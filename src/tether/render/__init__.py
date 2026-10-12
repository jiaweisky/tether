"""Rendering layer: parse Markdown and turn a document into an outbound plan."""

from __future__ import annotations

from ..models import RichDoc, Segment
from .markdown import MarkdownRenderer, render_markdown
from .renderer import DefaultRenderer

__all__ = [
    "DefaultRenderer",
    "MarkdownRenderer",
    "render_markdown",
    "RichDoc",
    "Segment",
]

"""Turn a rendered document into one or more platform-shaped outbound plans.

The renderer degrades Markdown to the channel's level, pulls images out into
separate media segments, appends an optional reasoning block and usage line, and
splits over-long text on semantic boundaries.
"""

from __future__ import annotations

from ..capabilities import Capabilities
from ..models import (
    MediaSegment,
    OutboundPlan,
    RichDoc,
    Segment,
    TextSegment,
    Usage,
)
from .markdown import render_markdown


class DefaultRenderer:
    def __init__(
        self,
        *,
        show_usage: bool = True,
        context_limit: int | None = None,
        reasoning_style: str = "collapsible",
        max_chars_override: int | None = None,
    ) -> None:
        self.show_usage = show_usage
        self.context_limit = context_limit
        self.reasoning_style = reasoning_style
        self.max_chars_override = max_chars_override

    def render(self, doc: RichDoc, caps: Capabilities) -> OutboundPlan:
        limit = self.max_chars_override or caps.max_text_chars
        body, images = render_markdown(doc.markdown, caps.markdown)
        body = self._decorate(body, doc)
        segments: list[Segment] = [TextSegment(text=c) for c in self._chunk(body, limit)]
        segments += [MediaSegment(media=media) for media in [*doc.media, *images]]
        return OutboundPlan(segments=segments)

    # -- decoration --------------------------------------------------------
    def _decorate(self, body: str, doc: RichDoc) -> str:
        if doc.reasoning:
            body = self._reasoning_block(doc.reasoning) + body
        if self.show_usage and doc.usage is not None:
            usage_line = self._usage_line(doc.usage)
            if usage_line:
                body = f"{body}\n\n{usage_line}" if body else usage_line
        return body

    def _reasoning_block(self, reasoning: str) -> str:
        text = reasoning.strip()
        if not text:
            return ""
        if self.reasoning_style == "inline":
            return f"💭 {text}\n\n"
        return f"**💭 Thinking**\n\n{text}\n\n"

    def _usage_line(self, usage: Usage) -> str:
        parts = [
            part
            for part in (
                self._context_part(usage),
                self._turn_part(usage),
                self._cost_part(usage),
            )
            if part
        ]
        return "📊 " + " · ".join(parts) if parts else ""

    def _context_part(self, usage: Usage) -> str:
        if usage.context_tokens is None:
            return ""
        limit = usage.context_limit or self.context_limit
        used = _fmt_tokens(usage.context_tokens)
        if not limit:
            return f"context {used}"
        pct = int(round(usage.context_tokens / limit * 100))
        return f"context {used}/{_fmt_tokens(limit)} ({pct}%)"

    @staticmethod
    def _turn_part(usage: Usage) -> str:
        if not usage.input_tokens and not usage.output_tokens:
            return ""
        used_in = _fmt_tokens(usage.input_tokens)
        used_out = _fmt_tokens(usage.output_tokens)
        return f"this turn in {used_in}/out {used_out}"

    @staticmethod
    def _cost_part(usage: Usage) -> str:
        return f"${usage.cost:.4f}" if usage.cost else ""

    # -- chunking ----------------------------------------------------------
    def _chunk(self, text: str, limit: int) -> list[str]:
        if limit <= 0 or len(text) <= limit:
            return [text] if text else []
        chunks: list[str] = []
        for paragraph in text.split("\n\n"):
            if len(paragraph) <= limit:
                _append_paragraph(chunks, paragraph, limit)
            else:
                chunks.extend(_split_semantic(paragraph, limit))
        chunks = [c for c in chunks if c]
        if len(chunks) <= 1:
            return chunks
        return [f"{c}\n\n({i + 1}/{len(chunks)})" for i, c in enumerate(chunks)]


def _append_paragraph(chunks: list[str], paragraph: str, limit: int) -> None:
    if chunks and len(f"{chunks[-1]}\n\n{paragraph}") <= limit:
        chunks[-1] = f"{chunks[-1]}\n\n{paragraph}"
    else:
        chunks.append(paragraph)


def _split_semantic(text: str, limit: int) -> list[str]:
    """Split ``text`` preferring line breaks, then spaces, then a hard cut."""
    if len(text) <= limit:
        return [text]
    for separator in ("\n", " "):
        pieces = _pack(text, separator, limit)
        if all(len(piece) <= limit for piece in pieces):
            return pieces
    return [text[i : i + limit] for i in range(0, len(text), limit)]


def _pack(text: str, separator: str, limit: int) -> list[str]:
    out: list[str] = []
    buffer = ""
    for piece in text.split(separator):
        candidate = f"{buffer}{separator}{piece}" if buffer else piece
        if len(candidate) <= limit:
            buffer = candidate
            continue
        if buffer:
            out.append(buffer)
        while len(piece) > limit:
            out.append(piece[:limit])
            piece = piece[limit:]
        buffer = piece
    if buffer:
        out.append(buffer)
    return out


def _fmt_tokens(count: int) -> str:
    return f"{count / 1000:.1f}k" if count >= 1000 else str(count)


__all__ = ["DefaultRenderer", "render_markdown"]

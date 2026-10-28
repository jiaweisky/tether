"""Parse Markdown and degrade it to the level a channel can display.

The renderer tokenises with ``markdown-it-py``, rebuilds a small node tree and
re-emits the content at the requested :class:`MarkdownLevel`. Degradation only
loses formatting, never content, and images are pulled out as media instead of
being inlined.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from markdown_it import MarkdownIt
from markdown_it.token import Token

from tether.capabilities import MarkdownLevel
from tether.models import RichMedia

# Inline wrappers: opening token -> (closing token, marker used at rich levels).
_WRAPPED = {
    "strong_open": ("strong_close", "**"),
    "em_open": ("em_close", "*"),
    "s_open": ("s_close", "~~"),
}


@dataclass
class _Node:
    type: str
    tag: str = ""
    content: str = ""
    info: str = ""
    attrs: dict[str, Any] = field(default_factory=dict)
    children: list[_Node] = field(default_factory=list)
    inline: list[Token] = field(default_factory=list)


def _build_tree(tokens: list[Token]) -> _Node:
    root = _Node(type="root")
    stack = [root]
    for token in tokens:
        node = _Node(
            type=token.type,
            tag=token.tag or "",
            content=token.content,
            info=token.info if token.type == "fence" else "",
            attrs=token.attrs or {},
        )
        if token.type == "inline":
            node.inline = list(token.children or [])
            stack[-1].children.append(node)
        elif token.nesting == 1:
            stack[-1].children.append(node)
            stack.append(node)
        elif token.nesting == -1:
            if len(stack) > 1:
                stack.pop()
        else:
            stack[-1].children.append(node)
    return root


def _parser() -> MarkdownIt:
    return MarkdownIt("commonmark").enable(["table", "strikethrough"])


class MarkdownRenderer:
    """Degrades Markdown to a target level, extracting image media."""

    def __init__(self, level: MarkdownLevel) -> None:
        self.level = level
        self.media: list[RichMedia] = []
        self._inline_simple = {
            "text": lambda token: token.content,
            "code_inline": lambda token: (
                f"`{token.content}`" if level >= MarkdownLevel.BASIC else token.content
            ),
            "softbreak": lambda token: "\n",
            "hardbreak": lambda token: "\n",
            "html_inline": lambda token: token.content if level >= MarkdownLevel.RICH else "",
        }
        self._block_handlers = {
            "heading_open": lambda n: [self._heading(n)],
            "paragraph_open": lambda n: [self._paragraph(n)],
            "fence": lambda n: [self._code(n)],
            "code_block": lambda n: [self._code(n)],
            "bullet_list_open": lambda n: [self._list(n, ordered=False)],
            "ordered_list_open": lambda n: [self._list(n, ordered=True)],
            "blockquote_open": lambda n: [self._quote(n)],
            "table_open": lambda n: [self._table(n)],
            "hr": lambda n: ["---"],
            "html_block": lambda n: [n.content.strip()],
        }

    def render(self, text: str) -> tuple[str, list[RichMedia]]:
        tree = _build_tree(_parser().parse(text))
        blocks = self._blocks(tree.children)
        out = "\n\n".join(b for b in blocks if b.strip())
        return out, self.media

    # -- blocks ------------------------------------------------------------
    def _blocks(self, nodes: list[_Node]) -> list[str]:
        out: list[str] = []
        for node in nodes:
            out.extend(self._block(node))
        return out

    def _block(self, node: _Node) -> list[str]:
        handler = self._block_handlers.get(node.type)
        if handler is not None:
            return handler(node)
        if node.children:
            return self._blocks(node.children)
        return []

    def _inline_node(self, node: _Node) -> _Node | None:
        for child in node.children:
            if child.type == "inline":
                return child
        return None

    def _heading(self, node: _Node) -> str:
        inline = self._inline_node(node)
        text = self._render_inline(inline.inline if inline else [])
        try:
            depth = int(node.tag[1])
        except (IndexError, ValueError):
            depth = 1
        if self.level >= MarkdownLevel.RICH:
            return f"{'#' * depth} {text}"
        if self.level >= MarkdownLevel.BASIC:
            return f"**{text}**"
        return text.upper()

    def _paragraph(self, node: _Node) -> str:
        inline = self._inline_node(node)
        return self._render_inline(inline.inline if inline else [])

    def _code(self, node: _Node) -> str:
        body = node.content.rstrip("\n")
        if self.level >= MarkdownLevel.BASIC:
            return f"```{node.info}\n{body}\n```"
        return "\n".join("    " + line for line in body.splitlines())

    def _list(self, node: _Node, *, ordered: bool) -> str:
        lines: list[str] = []
        index = 1
        for item in node.children:
            if item.type != "list_item_open":
                continue
            inner = self._blocks(item.children)
            marker = f"{index}." if ordered else "-"
            index += 1
            if not inner:
                lines.append(marker)
                continue
            lines.append(f"{marker} {inner[0]}")
            pad = " " * (len(marker) + 1)
            for extra in inner[1:]:
                lines.extend(f"{pad}{line}" if line else "" for line in extra.splitlines())
        return "\n".join(lines)

    def _quote(self, node: _Node) -> str:
        inner = "\n\n".join(self._blocks(node.children))
        if self.level >= MarkdownLevel.STANDARD:
            return "\n".join(f"> {line}" if line else ">" for line in inner.splitlines())
        return f"「{inner}」"

    def _table(self, node: _Node) -> str:
        rows = self._table_rows(node)
        if not rows:
            return ""
        width = max(len(row) for row in rows)
        rows = [row + [""] * (width - len(row)) for row in rows]
        if self.level >= MarkdownLevel.RICH:
            return self._table_as_markdown(rows)
        if self.level == MarkdownLevel.STANDARD:
            return self._table_as_columns(rows, width)
        if self.level == MarkdownLevel.BASIC:
            return self._table_as_pairs(rows, width)
        return "\n".join(" | ".join(row) for row in rows)

    def _table_rows(self, node: _Node) -> list[list[str]]:
        rows: list[list[str]] = []
        for section in node.children:
            for row in section.children:
                if row.type != "tr_open":
                    continue
                cells = []
                for cell in row.children:
                    inline = self._inline_node(cell)
                    cells.append(self._render_inline(inline.inline if inline else []))
                if cells:
                    rows.append(cells)
        return rows

    @staticmethod
    def _table_as_markdown(rows: list[list[str]]) -> str:
        header = rows[0]
        lines = [
            "| " + " | ".join(header) + " |",
            "| " + " | ".join("---" for _ in header) + " |",
        ]
        lines += ["| " + " | ".join(row) + " |" for row in rows[1:]]
        return "\n".join(lines)

    @staticmethod
    def _table_as_columns(rows: list[list[str]], width: int) -> str:
        widths = [max(len(row[c]) for row in rows) for c in range(width)]
        return "\n".join(
            "  ".join(row[c].ljust(widths[c]) for c in range(width)).rstrip() for row in rows
        )

    @staticmethod
    def _table_as_pairs(rows: list[list[str]], width: int) -> str:
        header = rows[0]
        return "\n".join(
            " | ".join(f"{header[c]}: {row[c]}" for c in range(width)) for row in rows[1:]
        )

    # -- inline ------------------------------------------------------------
    def _render_inline(self, tokens: list[Token]) -> str:
        out: list[str] = []
        index = 0
        while index < len(tokens):
            piece, index = self._inline_token(tokens, index)
            if piece:
                out.append(piece)
        return "".join(out)

    def _inline_token(self, tokens: list[Token], index: int) -> tuple[str, int]:
        token = tokens[index]
        simple = self._inline_simple.get(token.type)
        if simple is not None:
            return simple(token), index + 1
        if token.type == "image":
            return self._inline_image(token), index + 1
        if token.type == "link_open":
            return self._inline_link(tokens, index)
        if token.type in _WRAPPED:
            return self._inline_wrapped(tokens, index, token.type)
        return "", index + 1

    def _inline_image(self, token: Token) -> str:
        src = str(token.attrGet("src") or "")
        alt = token.content or ""
        self.media.append(RichMedia(kind="image", url=src, caption=alt or None))
        if self.level == MarkdownLevel.NONE:
            return f"{alt} ({src})" if alt else src
        return alt

    def _inline_link(self, tokens: list[Token], index: int) -> tuple[str, int]:
        href = str(tokens[index].attrGet("href") or "")
        text, end = self._inline_until(tokens, index + 1, "link_close")
        if self.level == MarkdownLevel.NONE:
            return f"{text} ({href})", end
        return f"[{text}]({href})", end

    def _inline_wrapped(self, tokens: list[Token], index: int, open_type: str) -> tuple[str, int]:
        close_type, marker = _WRAPPED[open_type]
        text, end = self._inline_until(tokens, index + 1, close_type)
        keep_plain = (open_type == "s_open" and self.level < MarkdownLevel.STANDARD) or (
            open_type in ("strong_open", "em_open") and self.level <= MarkdownLevel.BASIC
        )
        return (text if keep_plain else f"{marker}{text}{marker}"), end

    def _inline_until(self, tokens: list[Token], start: int, close_type: str) -> tuple[str, int]:
        chunk: list[Token] = []
        index = start
        while index < len(tokens) and tokens[index].type != close_type:
            chunk.append(tokens[index])
            index += 1
        return self._render_inline(chunk), index


def render_markdown(text: str, level: MarkdownLevel) -> tuple[str, list[RichMedia]]:
    return MarkdownRenderer(level).render(text)

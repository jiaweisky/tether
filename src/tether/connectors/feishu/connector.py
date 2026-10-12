"""Feishu connector scaffold: card-patch streaming and action callbacks.

The declared capabilities are best-effort estimates; delivery behaviour and
interaction fields must be confirmed against the live platform before use.
"""

from __future__ import annotations

from ...capabilities import Capabilities, MarkdownLevel
from ..stub import ScaffoldConnector

feishu_capabilities = Capabilities(
    markdown=MarkdownLevel.RICH,
    code_block=True,
    tables=True,
    headings=True,
    images_inline=False,
    edit_message=True,
    native_stream=False,
    buttons=True,
    reactions=False,
    typing=False,
    proactive=True,
    groups=True,
    mention=True,
    callback_actor_identity=True,
    member_roles=False,
    direct_delivery="unknown",
    group_delivery="mention_only",
    max_text_chars=4000,
    media_in=frozenset({"image", "audio", "video", "file"}),
    media_out=frozenset({"image", "audio", "video", "file"}),
)


class FeishuConnector(ScaffoldConnector):
    def __init__(self, *, app_id: str, app_secret: str) -> None:
        super().__init__("feishu", feishu_capabilities)
        self.app_id = app_id
        self.app_secret = app_secret

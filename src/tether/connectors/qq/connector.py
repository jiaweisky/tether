"""QQ (botpy) connector scaffold.

The declared capabilities are best-effort estimates; event names, parameters
and message-type values must be confirmed against the live platform.
"""

from __future__ import annotations

from ...capabilities import Capabilities, MarkdownLevel
from ..stub import ScaffoldConnector

qq_capabilities = Capabilities(
    markdown=MarkdownLevel.BASIC,
    code_block=True,
    tables=False,
    headings=False,
    images_inline=False,
    edit_message=False,
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
    max_text_chars=2000,
    media_in=frozenset({"image", "video", "audio", "file"}),
    media_out=frozenset({"image", "video", "audio", "file"}),
)


class QQConnector(ScaffoldConnector):
    def __init__(self, *, appid: str, secret: str) -> None:
        super().__init__("qq", qq_capabilities)
        self.appid = appid
        self.secret = secret

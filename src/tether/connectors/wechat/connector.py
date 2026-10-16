"""Personal WeChat (openclaw-weixin / iLink Bot) connector scaffold.

Declared with no Markdown, buttons, or message editing, so prompts degrade to
numbered options and replies are sent in one shot.
"""

from __future__ import annotations

from ...capabilities import Capabilities, MarkdownLevel
from ..stub import ScaffoldConnector

wechat_capabilities = Capabilities(
    markdown=MarkdownLevel.NONE,
    code_block=False,
    tables=False,
    headings=False,
    images_inline=False,
    edit_message=False,
    native_stream=False,
    buttons=False,
    reactions=False,
    typing=True,
    proactive=False,
    groups=False,
    mention=False,
    callback_actor_identity=False,
    member_roles=False,
    direct_delivery="unknown",
    group_delivery="unknown",
    max_text_chars=2000,
    media_in=frozenset({"image", "audio", "video", "file"}),
    media_out=frozenset({"image", "audio", "video", "file"}),
)


class WeChatConnector(ScaffoldConnector):
    def __init__(self, *, cred_path: str) -> None:
        super().__init__("wechat", wechat_capabilities)
        self.cred_path = cred_path

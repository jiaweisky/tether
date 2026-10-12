"""An in-memory connector used by tests and local development.

It records everything sent and lets tests register attachments to download and
inject inbound items.
"""

from __future__ import annotations

from typing import Any

from ..capabilities import Capabilities, MarkdownLevel
from ..models import (
    Attachment,
    BotIdentity,
    Card,
    Conversation,
    MediaBytes,
    MediaHandle,
    RichMedia,
    SentRef,
    normalize_media_kind,
)
from .base import BaseConnector


def fake_capabilities() -> Capabilities:
    return Capabilities(
        markdown=MarkdownLevel.RICH,
        code_block=True,
        tables=True,
        headings=True,
        images_inline=False,
        edit_message=True,
        native_stream=False,
        buttons=True,
        reactions=True,
        typing=True,
        proactive=True,
        groups=True,
        mention=True,
        callback_actor_identity=True,
        member_roles=False,
        direct_delivery="always",
        group_delivery="mention_only",
        max_text_chars=4000,
        max_cards=5,
        media_in=frozenset({"image", "audio", "video", "file"}),
        media_out=frozenset({"image", "audio", "video", "file"}),
    )


class FakeConnector(BaseConnector):
    name = "fake"

    def __init__(
        self, *, bot_name: str = "Assistant", bot_description: str | None = "A helpful assistant."
    ) -> None:
        super().__init__(fake_capabilities())
        self.bot_name = bot_name
        self.bot_description = bot_description
        self.messages: list[dict[str, Any]] = []
        self.cards: list[Card] = []
        self.typing_calls: list[str] = []
        self.reactions: list[tuple[str, str]] = []
        self.acknowledgements: list[tuple[str, str]] = []
        self.uploads: list[MediaHandle] = []
        self._attachments: dict[str, MediaBytes] = {}
        self._counter = 0

    # -- test helpers ------------------------------------------------------
    def register_attachment(
        self, handle: str, data: bytes, mime: str = "image/png", name: str = "file.png"
    ) -> Attachment:
        self._attachments[handle] = MediaBytes(data=data, mime=mime, name=name)
        return Attachment(kind="image", mime=mime, name=name, size=len(data), handle=handle)

    def last_text(self) -> str:
        for message in reversed(self.messages):
            if message["kind"] == "text":
                return message["text"]
        return ""

    def _next_id(self) -> str:
        self._counter += 1
        return f"m{self._counter}"

    # -- primitives --------------------------------------------------------
    async def _send_text(
        self, conv: Conversation, text: str, reply_to: str | None, *, final: bool = True
    ) -> str:
        message_id = self._next_id()
        self.messages.append({"id": message_id, "kind": "text", "text": text, "conv": conv.key})
        return message_id

    async def _update_text(self, ref: SentRef, text: str, *, final: bool = True) -> None:
        for message in self.messages:
            if message["id"] == ref.id:
                message["text"] = text
                return
        self.messages.append(
            {"id": ref.id, "kind": "text", "text": text, "conv": ref.conversation.key}
        )

    async def _send_media(self, conv: Conversation, media: RichMedia) -> str:
        message_id = self._next_id()
        self.messages.append({"id": message_id, "kind": "media", "media": media, "conv": conv.key})
        return message_id

    async def _send_card(self, conv: Conversation, card: Card) -> str:
        message_id = self._next_id()
        self.cards.append(card)
        self.messages.append({"id": message_id, "kind": "card", "card": card, "conv": conv.key})
        return message_id

    async def _typing(self, conv: Conversation) -> None:
        self.typing_calls.append(conv.key)

    async def _react(self, ref: SentRef, emoji: str) -> None:
        self.reactions.append((ref.id, emoji))

    async def download(self, att: Attachment) -> MediaBytes:
        media = self._attachments.get(str(att.handle))
        return media or MediaBytes(data=b"", mime=att.mime, name=att.name)

    async def upload(self, data: MediaBytes, *, kind: str) -> MediaHandle:
        handle = MediaHandle(handle=f"up-{len(self.uploads)}", kind=normalize_media_kind(kind))
        self.uploads.append(handle)
        return handle

    async def identity(self, conv: Conversation) -> BotIdentity:
        return BotIdentity(
            name=self.bot_name, description=self.bot_description, aliases=(self.bot_name,)
        )

    async def acknowledge(self, interaction, text: str) -> None:  # noqa: ANN001
        self.acknowledgements.append((interaction.value, text))


__all__ = ["FakeConnector", "fake_capabilities"]

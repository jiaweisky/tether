"""Shared connector behaviour: turn an outbound plan into platform calls.

A concrete connector implements the small platform primitives (send text,
update text, send media, send a card, typing, reactions, download, upload). The
base class walks the plan, splits over-long text, applies a per-conversation
rate limit, and raises :class:`Unsupported` for primitives a channel lacks.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from ..capabilities import Capabilities
from ..connector import Unsupported
from ..models import (
    Attachment,
    BotIdentity,
    Card,
    CardSegment,
    Conversation,
    ConversationInfo,
    InboundMessage,
    IncomingInteraction,
    IncomingItem,
    MediaBytes,
    MediaHandle,
    MediaSegment,
    OutboundPlan,
    RichMedia,
    Segment,
    SentRef,
    TextSegment,
)
from ..util.throttle import TokenBucket

Emit = Callable[[IncomingItem], Awaitable[None]]


class BaseConnector:
    name: str = "base"
    capabilities: Capabilities

    def __init__(self, capabilities: Capabilities) -> None:
        self.capabilities = capabilities
        self._emit: Emit | None = None
        self._buckets: dict[str, TokenBucket] = {}

    # -- lifecycle ---------------------------------------------------------
    async def start(self, emit: Emit) -> None:
        self._emit = emit
        await self._connect()

    async def stop(self) -> None:
        await self._disconnect()

    async def _connect(self) -> None:
        return None

    async def _disconnect(self) -> None:
        return None

    async def emit(self, item: IncomingItem) -> None:
        if self._emit is not None:
            await self._emit(item)

    # -- outbound ----------------------------------------------------------
    async def send(self, conv: Conversation, plan: OutboundPlan) -> SentRef:
        await self._rate_limit(conv)
        first_ref: str | None = None
        for segment in plan.segments:
            ref = await self._dispatch_segment(conv, segment, plan.reply_to, final=plan.final)
            first_ref = first_ref or ref
        return SentRef(id=first_ref or "", conversation=conv)

    async def _dispatch_segment(
        self, conv: Conversation, segment: Segment, reply_to: str | None, *, final: bool
    ) -> str | None:
        if isinstance(segment, TextSegment):
            return await self._send_text_chunks(conv, segment.text, reply_to, final=final)
        if isinstance(segment, MediaSegment) and segment.media is not None:
            return await self._send_media(conv, segment.media)
        if isinstance(segment, CardSegment) and segment.card is not None:
            return await self._send_card(conv, segment.card)
        return None

    async def _send_text_chunks(
        self, conv: Conversation, text: str, reply_to: str | None, *, final: bool
    ) -> str | None:
        first_ref: str | None = None
        for chunk in self._chunk(text):
            ref = await self._send_text(conv, chunk, reply_to, final=final)
            first_ref = first_ref or ref
        return first_ref

    async def update(self, ref: SentRef, plan: OutboundPlan) -> None:
        await self._rate_limit(ref.conversation)
        if len(plan.segments) == 1 and isinstance(plan.segments[0], TextSegment):
            await self._update_text(ref, plan.segments[0].text, final=plan.final)
            return
        raise Unsupported("this plan cannot be patched in place")

    async def reply(self, in_reply_to: InboundMessage, plan: OutboundPlan) -> SentRef:
        # A reply is a complete message; a caller wanting an interim frame should
        # use send/update directly.
        plan.reply_to = plan.reply_to or in_reply_to.message_id
        plan.final = True
        return await self.send(in_reply_to.conversation, plan)

    async def send_typing(self, conv: Conversation) -> None:
        await self._typing(conv)

    async def react(self, ref: SentRef, emoji: str) -> None:
        await self._react(ref, emoji)

    async def send_card(
        self,
        conv: Conversation,
        card: Card,
        *,
        stream_id: str | None = None,
        text: str | None = None,
    ) -> SentRef:
        # stream_id/text let a channel attach the card to an active streamed
        # message (e.g. WeCom); channels that cannot ignore them.
        ref = await self._send_card(conv, card)
        return SentRef(id=ref or "", conversation=conv)

    def supports_streaming(self, conv: Conversation) -> bool:
        """Whether this conversation can be refreshed in place.

        Channels without an edit or native-stream capability send a placeholder
        and then the final message only.
        """
        return bool(self.capabilities.native_stream or self.capabilities.edit_message)

    async def acknowledge(self, interaction: IncomingInteraction, text: str) -> None:
        """Reflect a handled card interaction back onto the card.

        Default is a no-op; channels whose cards can be updated override this.
        """
        return None

    # -- media -------------------------------------------------------------
    async def download(self, att: Attachment) -> MediaBytes:
        raise Unsupported(f"{self.name} cannot download attachments")

    async def upload(self, data: MediaBytes, *, kind: str) -> MediaHandle:
        raise Unsupported(f"{self.name} cannot upload media")

    # -- facts -------------------------------------------------------------
    async def identity(self, conv: Conversation) -> BotIdentity:
        return BotIdentity(name="Assistant")

    async def conversation_info(self, conv: Conversation) -> ConversationInfo:
        return ConversationInfo()

    # -- platform primitives (subclass hooks) ------------------------------
    async def _send_text(
        self, conv: Conversation, text: str, reply_to: str | None, *, final: bool = True
    ) -> str:
        raise Unsupported(f"{self.name} cannot send text")

    async def _update_text(self, ref: SentRef, text: str, *, final: bool = True) -> None:
        raise Unsupported(f"{self.name} cannot update a message")

    async def _send_media(self, conv: Conversation, media: RichMedia) -> str:
        raise Unsupported(f"{self.name} cannot send media")

    async def _send_card(self, conv: Conversation, card: Card) -> str:
        raise Unsupported(f"{self.name} cannot send cards")

    async def _typing(self, conv: Conversation) -> None:
        raise Unsupported(f"{self.name} has no typing indicator")

    async def _react(self, ref: SentRef, emoji: str) -> None:
        raise Unsupported(f"{self.name} has no reactions")

    # -- helpers -----------------------------------------------------------
    async def _rate_limit(self, conv: Conversation) -> None:
        rate = self.capabilities.rate_limit_per_min
        if not rate:
            return
        bucket = self._buckets.get(conv.key)
        if bucket is None:
            bucket = TokenBucket(rate)
            self._buckets[conv.key] = bucket
        await bucket.acquire()

    def _chunk(self, text: str) -> list[str]:
        limit = self.capabilities.max_text_chars
        if limit <= 0 or len(text) <= limit:
            return [text]
        return [text[i : i + limit] for i in range(0, len(text), limit)]

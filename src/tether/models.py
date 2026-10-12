"""Core data model: IM conversations, inbound/outbound carriers and routes.

These types are the shared vocabulary between connectors, the engine and the
renderer. They contain no platform-specific or agent-protocol detail.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

MediaKind = Literal["image", "audio", "video", "file", "voice"]
NormalizedMediaKind = Literal["image", "audio", "video", "file"]

_NORMALIZED_KINDS: frozenset[str] = frozenset({"image", "audio", "video", "file"})


def normalize_media_kind(kind: str) -> NormalizedMediaKind:
    """Collapse a platform media kind into one of the four canonical kinds.

    Voice messages are treated as audio; anything unknown is treated as a file.
    """
    if kind == "voice":
        return "audio"
    if kind in _NORMALIZED_KINDS:
        return kind  # type: ignore[return-value]
    return "file"


@dataclass(frozen=True)
class Conversation:
    channel: str
    kind: Literal["direct", "group", "channel"]
    id: str
    name: str | None = None
    thread: str | None = None
    tenant: str | None = None

    @property
    def key(self) -> str:
        """Stable identity used to map a conversation to one agent session."""
        return f"{self.channel}:{self.kind}:{self.tenant}:{self.id}:{self.thread}"

    @property
    def is_group(self) -> bool:
        return self.kind in ("group", "channel")


@dataclass(frozen=True)
class BotIdentity:
    name: str
    description: str | None = None
    aliases: tuple[str, ...] = ()
    avatar_url: str | None = None


@dataclass(frozen=True)
class ConversationInfo:
    name: str | None = None
    members: tuple[Sender, ...] = ()


@dataclass
class Sender:
    id: str
    name: str | None = None
    is_bot: bool = False


@dataclass
class Attachment:
    kind: MediaKind
    mime: str | None = None
    name: str | None = None
    size: int | None = None
    handle: Any = None
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None


@dataclass
class InboundMessage:
    channel: str
    message_id: str
    conversation: Conversation
    sender: Sender
    text: str
    mentions: list[Sender] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)
    quoted: InboundMessage | None = None
    timestamp: float = 0.0
    raw: Any = None


@dataclass
class IncomingInteraction:
    """A card/button callback, e.g. the user clicking a HITL button."""

    conversation: Conversation
    message_id: str
    sender: Sender
    value: str
    raw: Any = None


@dataclass
class ConnectorEvent:
    """A non-message platform event, e.g. a user entering the chat."""

    kind: Literal["enter_chat", "feedback", "other"]
    conversation: Conversation
    sender: Sender | None = None
    raw: Any = None


IncomingItem = InboundMessage | IncomingInteraction | ConnectorEvent


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cached_tokens: int = 0
    cost: float = 0.0
    context_tokens: int | None = None
    context_limit: int | None = None


# ---------------------------------------------------------------------------
# Rendering carriers
# ---------------------------------------------------------------------------


@dataclass
class RichMedia:
    kind: NormalizedMediaKind
    data: bytes | None = None
    mime: str | None = None
    name: str | None = None
    url: str | None = None
    caption: str | None = None


@dataclass
class Button:
    text: str
    value: str
    style: str | None = None


@dataclass
class Card:
    title: str | None
    body: str
    buttons: list[Button] = field(default_factory=list)
    fields: dict[str, str] = field(default_factory=dict)


@dataclass
class Segment:
    kind: str = "text"


@dataclass
class TextSegment(Segment):
    text: str = ""
    kind: str = "text"


@dataclass
class MediaSegment(Segment):
    media: RichMedia | None = None
    kind: str = "media"


@dataclass
class CardSegment(Segment):
    card: Card | None = None
    kind: str = "card"


@dataclass
class OutboundPlan:
    segments: list[Segment] = field(default_factory=list)
    reply_to: str | None = None
    final: bool = False


@dataclass
class RichDoc:
    """The canonical renderer input: Markdown plus optional reasoning, usage,
    attached media and interactive buttons."""

    markdown: str = ""
    reasoning: str | None = None
    usage: Usage | None = None
    media: list[RichMedia] = field(default_factory=list)
    interactive: list[Button] = field(default_factory=list)


@dataclass
class SentRef:
    id: str
    conversation: Conversation
    raw: Any = None


@dataclass
class MediaBytes:
    data: bytes
    mime: str | None = None
    name: str | None = None


@dataclass
class MediaHandle:
    handle: Any
    kind: NormalizedMediaKind


@dataclass
class PendingInteraction:
    """An unanswered permission or question awaiting a user's reply.

    ``owner`` is the sender whose turn raised it, ``scope`` decides who may
    answer, and ``options`` backs the numbered fallback used on channels without
    buttons.
    """

    kind: Literal["permission", "question"]
    owner: str | None = None
    scope: str = "initiator"
    options: list[str] = field(default_factory=list)
    request_id: str | None = None


@dataclass
class Route:
    """The persisted mapping between one IM conversation and one agent session,
    together with the per-conversation state the bridge needs across turns."""

    conversation: Conversation
    session_id: str
    server_base: str
    agent: str
    model: str | None = None
    project_id: str | None = None
    # Multi-user group-chat state.
    participants: dict[str, str] = field(default_factory=dict)
    active_turn_sender: str | None = None
    queue_depth: int = 0
    # Bot identity synchronised from the platform.
    bot_name: str | None = None
    bot_description: str | None = None
    context_dirty: bool = False
    identity_injected: bool = False
    created_at: float = 0.0
    last_active: float = 0.0
    # Ordered map of request id -> pending interaction.
    pending_interactions: dict[str, PendingInteraction] = field(default_factory=dict)
    stream_ref: dict | None = None

    @property
    def key(self) -> str:
        return self.conversation.key

"""The connector contract and its registry.

A connector encapsulates one IM platform: connection handling, event parsing,
sending, media and cards. Adding a platform means adding a connector and a
capability declaration, without touching the engine.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Protocol, runtime_checkable

from .capabilities import Capabilities
from .models import (
    Attachment,
    BotIdentity,
    Card,
    Conversation,
    ConversationInfo,
    InboundMessage,
    IncomingItem,
    MediaBytes,
    MediaHandle,
    OutboundPlan,
    SentRef,
)

Emit = Callable[[IncomingItem], Awaitable[None]]


class Unsupported(Exception):
    """Raised by a connector when an optional primitive is unavailable."""


@runtime_checkable
class IMConnector(Protocol):
    name: str
    capabilities: Capabilities

    async def start(self, emit: Emit) -> None: ...
    async def stop(self) -> None: ...

    # Outbound primitives
    async def send(self, conv: Conversation, plan: OutboundPlan) -> SentRef: ...
    async def update(self, ref: SentRef, plan: OutboundPlan) -> None: ...
    async def reply(self, in_reply_to: InboundMessage, plan: OutboundPlan) -> SentRef: ...
    async def send_typing(self, conv: Conversation) -> None: ...
    async def react(self, ref: SentRef, emoji: str) -> None: ...
    async def send_card(self, conv: Conversation, card: Card) -> SentRef: ...

    # Media
    async def download(self, att: Attachment) -> MediaBytes: ...
    async def upload(self, data: MediaBytes, *, kind: str) -> MediaHandle: ...

    # Platform facts
    async def identity(self, conv: Conversation) -> BotIdentity: ...
    async def conversation_info(self, conv: Conversation) -> ConversationInfo: ...


ConnectorFactory = Callable[..., IMConnector]

_REGISTRY: dict[str, ConnectorFactory] = {}


def register_connector(name: str, factory: ConnectorFactory) -> None:
    _REGISTRY[name] = factory


def known_connectors() -> list[str]:
    return sorted(_REGISTRY)


def build_connectors(config: Any) -> list[IMConnector]:
    """Instantiate every enabled connector declared in ``config.channels``.

    Connectors are imported lazily so the core carries no hard dependency on any
    platform SDK.
    """
    from .connectors import build_enabled

    return build_enabled(config)

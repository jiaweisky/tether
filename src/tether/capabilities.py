"""Declarative description of what each IM platform can do.

A connector states these facts; the engine and renderer read them to pick a
streaming strategy, a Markdown degradation level and a fallback for channels
without buttons. No rendering logic lives in a connector.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import IntEnum
from typing import Literal

# How the platform decides which messages to push to the bot. This is a fact
# recorded for operators and integration testing; the bridge forwards whatever
# it receives rather than applying its own trigger filter.
DeliveryModel = Literal["always", "mention_only", "on_session", "unknown"]


class MarkdownLevel(IntEnum):
    """Ordered Markdown support. Higher = richer."""

    NONE = 0
    BASIC = 1
    STANDARD = 2
    RICH = 3


@dataclass(frozen=True)
class Capabilities:
    """Facts about one platform's outbound/inbound surface."""

    markdown: MarkdownLevel
    code_block: bool = False
    tables: bool = False
    headings: bool = False
    images_inline: bool = False
    edit_message: bool = False
    native_stream: bool = False
    buttons: bool = False
    reactions: bool = False
    typing: bool = False
    proactive: bool = False
    groups: bool = False
    mention: bool = False
    # Whether callbacks carry the identity of the person who acted, and whether
    # the platform exposes group member roles. These decide whether a HITL
    # request can be restricted to its initiator or to group admins.
    callback_actor_identity: bool = False
    member_roles: bool = False
    direct_delivery: DeliveryModel = "unknown"
    group_delivery: DeliveryModel = "unknown"
    max_text_chars: int = 4000
    max_cards: int = 1
    media_in: frozenset[str] = field(default_factory=lambda: frozenset({"image"}))
    media_out: frozenset[str] = field(default_factory=lambda: frozenset({"image"}))
    rate_limit_per_min: int | None = None

    def supports_media_in(self, kind: str) -> bool:
        return kind in self.media_in

    def supports_media_out(self, kind: str) -> bool:
        return kind in self.media_out

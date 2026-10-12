"""Assemble the text sent to the agent for one inbound message.

The agent only ever receives prompt text, so group speaker labels, mention
handling and a small ``<bridge-context>`` preamble (bot identity and
conversation metadata) are all injected here. User text is sanitised first so
it cannot forge that preamble or impersonate another speaker.
"""

from __future__ import annotations

import re

from ..config import Config
from ..models import Attachment, BotIdentity, InboundMessage, Route, Sender, normalize_media_kind

_SPEAKER_PREFIX_RE = re.compile(r"^\s*\[[^\]]{1,64}\]:\s*", re.MULTILINE)


def sanitize_user_text(text: str, tag: str) -> str:
    """Strip forged context markers and line-leading speaker prefixes.

    Removes any ``<tag>``/``</tag>`` wrappers and ``[name]:`` prefixes at the
    start of a line, so a user cannot fake system context or another speaker.
    """
    text = re.sub(rf"</?{re.escape(tag)}>", "", text)
    return _SPEAKER_PREFIX_RE.sub("", text)


def strip_bot_mention(text: str, identity: BotIdentity) -> str:
    """Remove any mention of the bot's name or aliases from the text."""
    for name in _identity_names(identity):
        text = re.sub(rf"[@＠]{re.escape(name)}\s*", "", text)
    return text.strip()


def render_mentions(
    text: str, mentions: list[Sender], identity: BotIdentity, *, keep_others: bool
) -> str:
    """Keep non-bot mentions as ``@{name}`` when requested, else drop them."""
    bot_names = _identity_names(identity)
    for sender in mentions:
        if not sender.name or sender.name in bot_names:
            continue
        token = f"@{sender.name}"
        if keep_others:
            if token not in text:
                text = f"{text} {token}"
        else:
            text = text.replace(token, "")
    return text.strip()


def build_bridge_context(
    *,
    channel: str,
    identity: BotIdentity,
    agent: str,
    conversation_key: str,
    participants: list[str],
    tag: str = "bridge-context",
) -> str:
    """Render the structured preamble that tells the agent who and where it is."""
    lines = [f"<{tag}>", f"channel: {channel}", f"bot_name: {identity.name}"]
    if identity.aliases:
        lines.append(f"bot_aliases: [{', '.join(identity.aliases)}]")
    if identity.description:
        lines.append(f"bot_description: {identity.description}")
    lines.append(f"agent: {agent}")
    lines.append(f"conversation: {conversation_key}")
    if participants:
        lines.append(f"participants: {', '.join(participants)}")
    lines.append(f"</{tag}>")
    return "\n".join(lines)


def _identity_names(identity: BotIdentity) -> list[str]:
    return [name for name in {identity.name, *identity.aliases} if name]


def _attachment_placeholder(attachments: list[Attachment]) -> str:
    labels = [att.name or normalize_media_kind(att.kind) for att in attachments]
    if len(labels) == 1:
        return f"[{labels[0]}]"
    return f"[{len(labels)} attachments: {', '.join(labels)}]"


class PromptComposer:
    def __init__(self, config: Config) -> None:
        self.config = config

    def should_inject(self, route: Route) -> bool:
        """Whether the identity preamble should be prepended to this prompt."""
        mode = self.config.identity.inject
        if mode == "always":
            return True
        if mode == "once":
            return not route.identity_injected
        return route.context_dirty or not route.identity_injected

    def compose(
        self,
        *,
        route: Route,
        inbound: InboundMessage,
        identity: BotIdentity,
        agent_description: str | None,
        include_identity: bool | None = None,
    ) -> str:
        conversation = route.conversation
        text = self._compose_body(conversation.is_group, inbound, identity)
        if not text.strip() and inbound.attachments:
            # A caption-less attachment still needs non-empty prompt text: the
            # agent service rejects an empty prompt, and the media itself is
            # delivered out of band as a file part.
            text = _attachment_placeholder(inbound.attachments)
        inject = include_identity if include_identity is not None else self.should_inject(route)
        if not inject:
            return text
        preamble = self._build_preamble(route, identity, agent_description)
        return f"{preamble}\n{text}"

    def _compose_body(self, is_group: bool, inbound: InboundMessage, identity: BotIdentity) -> str:
        text = sanitize_user_text(inbound.text, self.config.identity.preamble_tag)
        text = strip_bot_mention(text, identity)
        if not is_group:
            return text
        text = render_mentions(
            text,
            inbound.mentions,
            identity,
            keep_others=self.config.group.mention_others,
        )
        if self.config.group.inject_speaker:
            name = inbound.sender.name or inbound.sender.id
            text = self.config.group.speaker_format.format(name=name, text=text)
        return text

    def _build_preamble(
        self, route: Route, identity: BotIdentity, agent_description: str | None
    ) -> str:
        conversation = route.conversation
        resolved = self._resolve_identity(identity, agent_description)
        participants: list[str] = []
        if conversation.is_group and self.config.identity.sync_participants and route.participants:
            participants = list(route.participants.values())
        return build_bridge_context(
            channel=conversation.channel,
            identity=resolved,
            agent=route.agent,
            conversation_key=f"{conversation.kind}:{conversation.name or conversation.id}",
            participants=participants,
            tag=self.config.identity.preamble_tag,
        )

    def _resolve_identity(
        self, identity: BotIdentity, agent_description: str | None
    ) -> BotIdentity:
        cfg = self.config.identity
        name = identity.name
        description = identity.description
        if cfg.source == "config":
            name = cfg.display_name or name
            description = cfg.description or description
        elif cfg.source == "agent":
            description = agent_description or description
        else:
            description = description or agent_description
        return BotIdentity(
            name=name,
            description=description or agent_description,
            aliases=identity.aliases,
        )

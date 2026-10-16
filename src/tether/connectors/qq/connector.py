"""QQ Bot Open Platform connector over api-v2 (thin client, no official SDK).

The platform protocol lives in :mod:`.sdk` behind the :class:`QQSDK` protocol,
so this connector can be exercised against a fake with no network. As with the
other long-connection connectors, the (blocking) WebSocket loop runs in a
dedicated thread owned by the SDK; inbound dispatch callbacks hop back onto
Tether's event loop and every REST call is dispatched with ``asyncio.to_thread``.

Inbound events are plain dicts: ``C2C_MESSAGE_CREATE`` / ``GROUP_AT_MESSAGE_CREATE``
become messages, ``INTERACTION_CREATE`` becomes an interaction and ``READY``
carries the bot's display name. Direct and group messages share one shape, so a
single parser handles both and only the conversation id / sender id differ.
"""

from __future__ import annotations

import asyncio
from datetime import datetime
from typing import Any

from ...capabilities import Capabilities, MarkdownLevel
from ...connector import Unsupported
from ...models import (
    Attachment,
    BotIdentity,
    Button,
    Card,
    ConnectorEvent,
    Conversation,
    InboundMessage,
    IncomingInteraction,
    MediaBytes,
    MediaHandle,
    MediaKind,
    RichMedia,
    Sender,
    normalize_media_kind,
)
from ...util.dedup import DedupCache
from ...util.logging import get_logger
from ..base import BaseConnector
from .sdk import QQSDK, QQClient, QQError

log = get_logger("tether.qq")

# Voice is carried as audio by the shared media model, but both spellings are
# listed so the capability check accepts either form.
qq_capabilities = Capabilities(
    markdown=MarkdownLevel.STANDARD,
    code_block=True,
    tables=False,
    headings=False,
    images_inline=False,
    edit_message=False,
    native_stream=False,
    buttons=True,
    reactions=False,
    typing=False,
    progress_placeholder=False,
    proactive=True,
    groups=True,
    mention=True,
    callback_actor_identity=True,
    member_roles=False,
    direct_delivery="always",
    group_delivery="mention_only",
    max_text_chars=4000,
    media_in=frozenset({"image", "audio", "video", "file", "voice"}),
    media_out=frozenset({"image", "audio", "video", "file", "voice"}),
    # A local per-conversation ceiling, well under the platform's 100 QPS.
    rate_limit_per_min=30,
)

# Passive replies are bounded per inbound message; beyond the cap the message is
# sent proactively instead of being rejected.
_C2C_REPLY_LIMIT = 4
_GROUP_REPLY_LIMIT = 5

# Our normalized media kinds -> the platform's ``file_type``.
_FILE_TYPE = {"image": 1, "video": 2, "audio": 3, "file": 4}

# Events that are neither a message nor an interaction; surfaced as a generic
# connector event so the bridge can log them without treating them as input.
_PASSIVE_EVENTS = frozenset(
    {"FRIEND_ADD", "GROUP_ADD_ROBOT", "C2C_MSG_RECEIVE", "GROUP_MSG_RECEIVE"}
)


class QQConnector(BaseConnector):
    name = "qq"
    capabilities = qq_capabilities

    def __init__(
        self,
        *,
        appid: str,
        secret: str,
        sdk: QQSDK | None = None,
    ) -> None:
        super().__init__(qq_capabilities)
        self._appid = appid
        self._secret = secret
        self._sdk: QQSDK = sdk or QQClient(appid, secret)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._bot_name: str | None = None
        # Markdown permission is per scene (C2C allows it, groups reject it), so
        # remember the outcome per conversation once a send tells us.
        self._markdown_ok: dict[str, bool] = {}
        self._dedup = DedupCache()
        self._msg_seq: dict[str, int] = {}
        self._last_inbound: dict[str, str] = {}

    # -- lifecycle ---------------------------------------------------------
    async def _connect(self) -> None:
        self._loop = asyncio.get_running_loop()
        try:
            await asyncio.to_thread(self._sdk.start, self._on_dispatch)
        except Exception:  # noqa: BLE001 - a failed channel must not kill Tether
            log.error("qq_stream_failed", exc_info=True)

    async def _disconnect(self) -> None:
        try:
            await asyncio.to_thread(self._sdk.stop)
        except Exception:  # noqa: BLE001
            log.warning("qq_stop_failed", exc_info=True)

    @property
    def connected(self) -> bool:
        return self._sdk.connected

    # -- inbound dispatch (called from the SDK thread) ---------------------
    def _on_dispatch(self, event: str, data: dict[str, Any]) -> None:
        try:
            self._route_event(event, data)
        except Exception:  # noqa: BLE001 - a parse error must not kill the stream
            log.warning("qq_event_failed", event=event, exc_info=True)

    def _route_event(self, event: str, data: dict[str, Any]) -> None:
        if event == "READY":
            self._on_ready(data)
            return
        if event == "C2C_MESSAGE_CREATE":
            self._queue_message(data, "direct")
        elif event in ("GROUP_AT_MESSAGE_CREATE", "GROUP_MESSAGE_CREATE"):
            self._queue_message(data, "group")
        elif event == "INTERACTION_CREATE":
            self._queue_interaction(data)
        elif event in _PASSIVE_EVENTS:
            self._queue_passive(event, data)

    def _on_ready(self, data: dict[str, Any]) -> None:
        user = data.get("user")
        name = user.get("username") if isinstance(user, dict) else None
        if name:
            self._bot_name = str(name)

    def _queue_message(self, data: dict[str, Any], kind: str) -> None:
        item = self._inbound_message(data, kind)
        if item is None or not item.message_id:
            return
        if self._dedup.is_duplicate(f"msg:{item.message_id}"):
            return
        # Media and cards carry no reply target of their own, so they reply to
        # the conversation's most recent inbound message; the previous message's
        # sequence entry can no longer be replied to, so drop it.
        previous = self._last_inbound.get(item.conversation.key)
        if previous and previous != item.message_id:
            self._msg_seq.pop(previous, None)
        self._last_inbound[item.conversation.key] = item.message_id
        self._submit(item)

    def _queue_interaction(self, data: dict[str, Any]) -> None:
        item, interaction_id = self._inbound_interaction(data)
        if item is None or not interaction_id:
            return
        if self._dedup.is_duplicate(f"interaction:{interaction_id}"):
            return
        self._submit_interaction(item, interaction_id)

    def _queue_passive(self, event: str, data: dict[str, Any]) -> None:
        conv = _passive_conversation(self.name, event, data)
        if conv is not None:
            self._submit(ConnectorEvent(kind="other", conversation=conv, raw=data))

    def _submit(self, item: Any) -> None:
        loop = self._loop
        if loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._emit_item(item), loop)

    def _submit_interaction(self, item: IncomingInteraction, interaction_id: str) -> None:
        loop = self._loop
        if loop is None:
            return
        asyncio.run_coroutine_threadsafe(self._emit_interaction(item, interaction_id), loop)

    async def _emit_item(self, item: Any) -> None:
        try:
            await self.emit(item)
        except Exception:  # noqa: BLE001 - the bridge handles a bad item
            log.warning("qq_emit_failed", exc_info=True)

    async def _emit_interaction(self, item: IncomingInteraction, interaction_id: str) -> None:
        # A clicked inline keyboard keeps the client in a loading state until the
        # platform is told the event was handled, so acknowledge before emitting.
        try:
            await asyncio.to_thread(self._sdk.put_interaction, interaction_id, 0)
        except Exception:  # noqa: BLE001 - acknowledgement is best-effort
            log.warning("qq_interaction_ack_failed", exc_info=True)
        await self._emit_item(item)

    # -- inbound mapping ---------------------------------------------------
    def _inbound_message(self, data: dict[str, Any], kind: str) -> InboundMessage | None:
        message_id = str(data.get("id") or "")
        if not message_id:
            return None
        raw_author = data.get("author")
        author: dict[str, Any] = raw_author if isinstance(raw_author, dict) else {}
        text, attachments = _parts(data)
        return InboundMessage(
            channel=self.name,
            message_id=message_id,
            conversation=self._conversation(data, kind),
            sender=_sender(author, kind),
            text=text,
            mentions=_mentions(data.get("mentions")),
            attachments=attachments,
            timestamp=_timestamp(data.get("timestamp")),
            raw=data,
        )

    def _inbound_interaction(
        self, data: dict[str, Any]
    ) -> tuple[IncomingInteraction | None, str]:
        interaction_id = str(data.get("id") or "")
        if not interaction_id:
            return None, ""
        conv, actor = _interaction_scope(self.name, data)
        resolved = (data.get("data") or {}).get("resolved")
        value = resolved.get("button_data") if isinstance(resolved, dict) else None
        raw: dict[str, Any] = {
            "event": "interaction",
            "interaction_id": interaction_id,
            "type": data.get("type"),
        }
        item = IncomingInteraction(
            conversation=conv,
            message_id=interaction_id,
            sender=Sender(id=actor),
            value=str(value or ""),
            raw=raw,
        )
        return item, interaction_id

    def _conversation(self, data: dict[str, Any], kind: str) -> Conversation:
        if kind == "group":
            identifier = data.get("group_openid")
            return Conversation(channel=self.name, kind="group", id=str(identifier or ""))
        raw_author = data.get("author")
        author: dict[str, Any] = raw_author if isinstance(raw_author, dict) else {}
        identifier = author.get("user_openid")
        return Conversation(channel=self.name, kind="direct", id=str(identifier or ""))

    # -- outbound ----------------------------------------------------------
    async def _send_text(
        self, conv: Conversation, text: str, reply_to: str | None, *, final: bool = True
    ) -> str:
        # Without an explicit target, reply to the conversation's latest inbound
        # message. QQ group bots may not send proactive messages, so every send
        # stays a passive reply whenever it can.
        target = self._reply_target(conv, reply_to)
        fields = self._reply_fields(conv, target)
        if self._markdown_ok.get(conv.key, True) and text:
            try:
                return await self._post(
                    conv, {**fields, "msg_type": 2, "markdown": {"content": text}}
                )
            except QQError:
                # Some bots (or scenes, e.g. groups) lack the markdown
                # permission; fall back to plain text and remember per conversation.
                log.warning("qq_markdown_failed", conversation=conv.key)
                self._markdown_ok[conv.key] = False
                fields = self._reply_fields(conv, target)
        return await self._post(conv, {**fields, "msg_type": 0, "content": text})

    async def _send_media(self, conv: Conversation, media: RichMedia) -> str:
        if media.data is None and not media.url:
            raise Unsupported("qq media send needs bytes or a url")
        scope = "group" if conv.is_group else "c2c"
        file_info = await self._call(
            self._sdk.upload_file,
            scope=scope,
            target_id=conv.id,
            file_type=_file_type(media.kind),
            filename=media.name,
            data=media.data,
            url=media.url,
        )
        fields = self._reply_fields(conv, self._reply_target(conv))
        try:
            return await self._post(
                conv, {**fields, "msg_type": 7, "media": {"file_info": file_info}}
            )
        except QQError:
            if not fields:
                raise
            # The passive window may have expired; retry as a proactive message.
            log.warning("qq_media_reply_failed", conversation=conv.key)
        return await self._post(conv, {"msg_type": 7, "media": {"file_info": file_info}})

    async def _send_card(self, conv: Conversation, card: Card) -> str:
        # A card is sent as a plain message carrying an inline keyboard; the
        # button payload is taken from the published examples and is not yet
        # confirmed against a live bot.
        fields = self._reply_fields(conv, self._reply_target(conv))
        payload: dict[str, Any] = {**fields, "msg_type": 0, "content": _card_text(card)}
        keyboard = _keyboard(card.buttons)
        if keyboard is not None:
            payload["keyboard"] = keyboard
        return await self._post(conv, payload)

    async def _post(self, conv: Conversation, fields: dict[str, Any]) -> str:
        if conv.is_group:
            return await self._call(self._sdk.post_group_message, conv.id, **fields)
        return await self._call(self._sdk.post_c2c_message, conv.id, **fields)

    def _reply_fields(self, conv: Conversation, reply_to: str | None) -> dict[str, Any]:
        """The ``msg_id``/``msg_seq`` pair for a passive reply, if it still fits.

        The same ``msg_id`` + ``msg_seq`` cannot be sent twice, so the sequence
        increments per reply; once the platform's per-message reply budget is
        spent, an empty dict makes the caller send the message proactively.
        """
        if not reply_to:
            return {}
        limit = _GROUP_REPLY_LIMIT if conv.is_group else _C2C_REPLY_LIMIT
        seq = self._msg_seq.get(reply_to, 0) + 1
        if seq > limit:
            return {}
        self._msg_seq[reply_to] = seq
        return {"msg_id": reply_to, "msg_seq": seq}

    def _reply_target(self, conv: Conversation, reply_to: str | None = None) -> str | None:
        """The inbound message a reply attaches to; an explicit target wins."""
        return reply_to or self._last_inbound.get(conv.key)

    # -- media / identity --------------------------------------------------
    async def download(self, att: Attachment) -> MediaBytes:
        handle = att.handle if isinstance(att.handle, dict) else {}
        url = handle.get("url")
        if normalize_media_kind(att.kind) == "audio" and handle.get("voice_wav_url"):
            url = handle["voice_wav_url"]
        if not url:
            raise Unsupported("qq attachment has no url")
        data = await self._call(self._sdk.download, str(url))
        return MediaBytes(data=data, mime=att.mime, name=att.name)

    async def upload(self, data: MediaBytes, *, kind: str) -> MediaHandle:
        # api-v2 uploads are scoped to a user or group, so there is no
        # conversation-independent handle to return here; media is uploaded from
        # ``_send_media`` where the target conversation is known.
        raise Unsupported("qq media is uploaded against a conversation")

    async def identity(self, conv: Conversation) -> BotIdentity:
        name = self._bot_name or self._appid
        return BotIdentity(name=name, aliases=(name,) if name else ())

    async def _call(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        return await asyncio.to_thread(fn, *args, **kwargs)


def _parts(data: dict[str, Any]) -> tuple[str, list[Attachment]]:
    """The message text and attachments, folding a voice transcript into text."""
    text = str(data.get("content") or "").strip()
    attachments: list[Attachment] = []
    for raw in data.get("attachments") or []:
        att = _attachment(raw)
        if att is None:
            continue
        if att.kind == "voice":
            transcript = str(raw.get("asr_refer_text") or "").strip()
            if transcript:
                text = f"{text} {transcript}".strip() if text else transcript
                continue
        attachments.append(att)
    if not text:
        text = _flatten_elements(data.get("msg_elements"))
    return text, attachments


def _attachment(raw: Any) -> Attachment | None:
    if not isinstance(raw, dict):
        return None
    content_type = str(raw.get("content_type") or "")
    return Attachment(
        kind=_kind_for_content_type(content_type),
        mime=content_type if "/" in content_type else None,
        name=raw.get("filename"),
        size=raw.get("size"),
        handle={
            "url": raw.get("url"),
            "voice_wav_url": raw.get("voice_wav_url"),
            "content_type": content_type,
        },
        width=raw.get("width"),
        height=raw.get("height"),
    )


def _kind_for_content_type(content_type: str) -> MediaKind:
    if content_type.startswith("image/"):
        return "image"
    if content_type.startswith("video/"):
        return "video"
    if content_type == "voice":
        return "voice"
    return "file"


def _flatten_elements(elements: Any) -> str:
    texts: list[str] = []
    for element in elements or []:
        if isinstance(element, dict):
            content = str(element.get("content") or "").strip()
            if content:
                texts.append(content)
    return "\n".join(texts)


def _sender(author: dict[str, Any], kind: str) -> Sender:
    if kind == "group":
        identifier = author.get("member_openid") or author.get("user_openid") or author.get("id")
    else:
        identifier = author.get("user_openid") or author.get("id")
    return Sender(
        id=str(identifier or ""),
        name=author.get("username") or None,
        is_bot=bool(author.get("bot")),
    )


def _interaction_scope(channel: str, data: dict[str, Any]) -> tuple[Conversation, str]:
    """The conversation and acting user of an interaction callback."""
    if data.get("scene") == "group" or data.get("chat_type") == 1:
        conv = Conversation(channel=channel, kind="group", id=str(data.get("group_openid") or ""))
        actor = data.get("group_member_openid")
    else:
        conv = Conversation(channel=channel, kind="direct", id=str(data.get("user_openid") or ""))
        actor = data.get("user_openid")
    return conv, str(actor or "")


def _mentions(raw: Any) -> list[Sender]:
    out: list[Sender] = []
    for item in raw or []:
        if not isinstance(item, dict):
            continue
        identifier = item.get("member_openid") or item.get("user_openid") or item.get("id")
        out.append(
            Sender(
                id=str(identifier or ""),
                name=item.get("username"),
                is_bot=bool(item.get("bot")),
            )
        )
    return out


def _passive_conversation(
    channel: str, event: str, data: dict[str, Any]
) -> Conversation | None:
    if event in ("GROUP_ADD_ROBOT", "GROUP_MSG_RECEIVE"):
        identifier = data.get("group_openid")
        return Conversation(channel=channel, kind="group", id=str(identifier or ""))
    if event in ("FRIEND_ADD", "C2C_MSG_RECEIVE"):
        return Conversation(channel=channel, kind="direct", id=str(data.get("openid") or ""))
    return None


def _file_type(kind: str) -> int:
    return _FILE_TYPE.get(normalize_media_kind(kind), 4)


def _card_text(card: Card) -> str:
    if card.title:
        return f"{card.title}\n\n{card.body}".strip()
    return card.body


def _keyboard(buttons: list[Button]) -> dict[str, Any] | None:
    """A custom inline keyboard (rows of callback buttons), or None if empty.

    Each button carries the interaction payload as its ``data``, so a click
    returns it in ``INTERACTION_CREATE``. Buttons are packed three per row.
    """
    rows: list[dict[str, Any]] = []
    row: list[dict[str, Any]] = []
    for index, button in enumerate(buttons):
        row.append(
            {
                "id": str(index),
                "render_data": {
                    "label": button.text,
                    "visited_label": button.text,
                    "style": 1,
                },
                "action": {"type": 1, "data": button.value, "permission": {"type": 0}},
            }
        )
        if len(row) == 3:
            rows.append({"buttons": row})
            row = []
    if row:
        rows.append({"buttons": row})
    return {"content": {"rows": rows}} if rows else None


def _timestamp(value: Any) -> float:
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str) and value:
        try:
            return datetime.fromisoformat(value).timestamp()
        except ValueError:
            return 0.0
    return 0.0


__all__ = ["QQConnector", "QQSDK", "qq_capabilities"]

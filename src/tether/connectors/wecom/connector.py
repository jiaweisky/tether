"""WeCom smart-robot connector over the official long-connection SDK.

The SDK is hidden behind the :class:`WeComSDK` protocol so the core stays
SDK-free and this connector can be exercised with a fake SDK. Frames are plain
dicts shaped ``{"cmd": ..., "headers": {"req_id": ...}, "body": {...}}``.
"""

from __future__ import annotations

import json
import mimetypes
import os
import uuid
from collections.abc import Callable
from typing import Any, Protocol

from ...capabilities import Capabilities, MarkdownLevel
from ...connector import Unsupported
from ...models import (
    Attachment,
    BotIdentity,
    Card,
    ConnectorEvent,
    Conversation,
    InboundMessage,
    IncomingInteraction,
    MediaBytes,
    MediaHandle,
    RichMedia,
    Sender,
    SentRef,
    normalize_media_kind,
)
from ...util.logging import get_logger
from ..base import BaseConnector

log = get_logger("tether.wecom")

# Outbound media is uploaded as a WeCom temporary material (chunked) and sent
# by media id; inbound media is downloaded and AES-decrypted by the SDK.
wecom_capabilities = Capabilities(
    markdown=MarkdownLevel.RICH,
    code_block=True,
    tables=True,
    headings=True,
    images_inline=False,
    edit_message=False,
    native_stream=True,
    card_in_stream=False,
    buttons=True,
    question_form=True,
    reactions=False,
    typing=False,
    proactive=True,
    groups=True,
    mention=True,
    callback_actor_identity=True,
    member_roles=False,
    direct_delivery="always",
    group_delivery="mention_only",
    max_text_chars=4096,
    max_cards=1,
    media_in=frozenset({"image", "audio", "file"}),
    media_out=frozenset({"image", "audio", "video", "file"}),
)

# Connection/lifecycle events the SDK emits (not message content).
_LIFECYCLE_EVENTS = ("connected", "authenticated", "disconnected", "reconnecting", "error")

# Our normalized media kinds -> WeCom media types.
_MEDIA_TYPES = {"image": "image", "audio": "voice", "video": "video", "file": "file"}
# Inbound WeCom message/media type -> our normalized kind.
_KIND_BY_TYPE = {"image": "image", "voice": "voice", "video": "video", "file": "file"}
_CHUNK_SIZE = 512 * 1024
_MAX_CHUNKS = 100


class WeComSDK(Protocol):
    """The subset of the official SDK this connector uses."""

    def on(self, event: str, handler: Callable[..., Any]) -> None: ...
    async def connect(self) -> Any: ...
    def disconnect(self) -> None: ...
    async def reply_stream(
        self, frame: Any, stream_id: str, content: str, finish: bool, msg_item: list | None = None
    ) -> Any: ...
    async def reply_welcome(self, frame: Any, body: dict) -> Any: ...
    async def reply_template_card(self, frame: Any, card: dict) -> Any: ...
    async def update_template_card(self, frame: Any, card: dict) -> Any: ...
    async def send_message(self, chatid: str, body: dict) -> Any: ...
    async def download_file(self, url: str, aes_key: str | None) -> tuple[bytes, str | None]: ...
    async def upload_media(self, data: bytes, media_type: str, filename: str) -> str: ...
    async def reply_media(self, frame: Any, media_type: str, media_id: str) -> Any: ...
    async def send_media_message(self, chatid: str, media_type: str, media_id: str) -> Any: ...
    def generate_stream_id(self) -> str: ...


class AibotSDK:
    """Adapter over the real ``wecom-aibot-python-sdk`` (``aibot``).

    The pinned SDK (1.0.2) is behind the Node SDK and omits media upload, but the
    WebSocket protocol is identical, so upload is implemented here on top of the
    SDK's generic ``reply``.
    """

    def __init__(self, bot_id: str, secret: str, *, reconnect_max_ms: int | None = None) -> None:
        self._bot_id = bot_id
        self._secret = secret
        self._reconnect_max_ms = reconnect_max_ms
        self._client: Any = None

    def _ensure_client(self):
        if self._client is None:
            try:
                import aibot
            except ImportError as exc:  # optional extra not installed
                raise Unsupported(
                    "wecom-aibot-python-sdk is not installed; install tether[wecom]"
                ) from exc
            self._client = aibot.WSClient(
                aibot.WSClientOptions(
                    bot_id=self._bot_id,
                    secret=self._secret,
                    # Retry forever: a transient DNS/network blip must not leave the
                    # bot permanently offline (the SDK's default gives up after 10).
                    max_reconnect_attempts=-1,
                )
            )
            ceiling = self._reconnect_max_ms
            manager = getattr(self._client, "_ws_manager", None)
            if ceiling and ceiling > 0 and manager is not None:
                # The SDK hard-codes the reconnect backoff ceiling (30s) with no
                # option for it, so set it on the connection manager directly.
                manager._reconnect_max_delay = ceiling
        return self._client

    def on(self, event: str, handler: Callable[..., Any]) -> None:
        self._ensure_client().on(event, handler)

    async def connect(self) -> Any:
        return await self._ensure_client().connect()

    def disconnect(self) -> None:
        if self._client is not None:
            self._client.disconnect()

    async def reply_stream(self, frame, stream_id, content, finish, msg_item=None) -> Any:
        return await self._ensure_client().reply_stream(
            frame, stream_id, content, finish=finish, msg_item=msg_item
        )

    async def reply_welcome(self, frame, body) -> Any:
        return await self._ensure_client().reply_welcome(frame, body)

    async def reply_template_card(self, frame, card) -> Any:
        return await self._ensure_client().reply_template_card(frame, card)

    async def update_template_card(self, frame, card) -> Any:
        return await self._ensure_client().update_template_card(frame, card)

    async def send_message(self, chatid, body) -> Any:
        return await self._ensure_client().send_message(chatid, body)

    async def download_file(self, url, aes_key):
        return await self._ensure_client().download_file(url, aes_key)

    async def upload_media(self, data: bytes, media_type: str, filename: str) -> str:
        import base64
        import hashlib

        import aibot

        total = len(data)
        total_chunks = max(1, (total + _CHUNK_SIZE - 1) // _CHUNK_SIZE)
        if total_chunks > _MAX_CHUNKS:
            raise Unsupported("wecom media exceeds the ~50MB upload limit")
        client = self._ensure_client()
        init = await _upload_cmd(
            client,
            aibot,
            "aibot_upload_media_init",
            {
                "type": media_type,
                "filename": filename,
                "total_size": total,
                "total_chunks": total_chunks,
                "md5": hashlib.md5(data).hexdigest(),
            },
        )
        upload_id = (init.get("body") or {}).get("upload_id")
        if not upload_id:
            raise Unsupported("wecom upload init returned no upload_id")
        for index in range(total_chunks):
            chunk = data[index * _CHUNK_SIZE : (index + 1) * _CHUNK_SIZE]
            await _upload_cmd(
                client,
                aibot,
                "aibot_upload_media_chunk",
                {
                    "upload_id": upload_id,
                    "chunk_index": index,
                    "base64_data": base64.b64encode(chunk).decode(),
                },
            )
        finish = await _upload_cmd(
            client, aibot, "aibot_upload_media_finish", {"upload_id": upload_id}
        )
        media_id = (finish.get("body") or {}).get("media_id")
        if not media_id:
            raise Unsupported("wecom upload finish returned no media_id")
        return str(media_id)

    async def reply_media(self, frame, media_type, media_id) -> Any:
        return await self._ensure_client().reply(frame, _media_body(media_type, media_id))

    async def send_media_message(self, chatid, media_type, media_id) -> Any:
        return await self._ensure_client().send_message(chatid, _media_body(media_type, media_id))

    def generate_stream_id(self) -> str:
        import aibot

        return aibot.generate_req_id("stream")


async def _upload_cmd(client: Any, aibot: Any, cmd: str, body: dict) -> dict:
    """Send one upload command over the WS channel and return its ack frame.

    The SDK's ``reply`` passes a synthetic frame so a fresh request id is used
    for each command (init/chunk/finish), which is how the Node SDK does it.
    """
    frame = {"headers": {"req_id": aibot.generate_req_id(cmd)}}
    return await client.reply(frame, body, cmd)


def _media_body(media_type: str, media_id: str) -> dict:
    return {"msgtype": media_type, media_type: {"media_id": media_id}}


def _wecom_media_type(kind: str) -> str:
    """Map our normalized media kind to WeCom's msgtype."""
    return _MEDIA_TYPES.get(normalize_media_kind(kind), "file")


def _kind_for(msgtype: str) -> str:
    """Map an inbound WeCom message/media type to our normalized kind."""
    return _KIND_BY_TYPE.get(msgtype, "file")


def _filename(name: str | None, mime: str | None, fallback: str) -> str:
    """Ensure an upload has a filename with an extension.

    WeCom expects a filename, and some types reject one without an extension; if
    the source name lacks one, derive it from the MIME type.
    """
    if name and os.path.splitext(name)[1]:
        return name
    extension = mimetypes.guess_extension(mime) if mime else None
    return f"{name or fallback}{extension or ''}"


class WeComConnector(BaseConnector):
    name = "wecom"
    capabilities = wecom_capabilities

    def __init__(
        self,
        *,
        bot_id: str,
        secret: str,
        sdk: WeComSDK | None = None,
        welcome_text: str | None = None,
        reconnect_max_ms: int | None = None,
    ) -> None:
        super().__init__(wecom_capabilities)
        self._bot_id = bot_id
        self._secret = secret
        self._sdk: WeComSDK = sdk or AibotSDK(
            bot_id, secret, reconnect_max_ms=reconnect_max_ms
        )
        self._welcome_text = welcome_text
        self._frames: dict[str, Any] = {}

    # -- lifecycle ---------------------------------------------------------
    async def _connect(self) -> None:
        self._sdk.on("message", self._on_frame)
        self._sdk.on("event.enter_chat", self._on_enter_chat)
        self._sdk.on("event.template_card_event", self._on_card_event)
        self._sdk.on("event.feedback_event", self._on_feedback)
        for event in _LIFECYCLE_EVENTS:
            self._sdk.on(event, self._on_lifecycle)
        await self._sdk.connect()

    async def _on_frame(self, frame: Any) -> None:
        """Dispatch an inbound message callback by its ``msgtype``.

        The SDK's typed ``message.<type>`` events omit ``video`` (its enum lacks
        it), but the generic ``message`` event carries every callback, so route
        by type here to avoid dropping a supported kind.
        """
        handlers = {
            "text": self._on_text,
            "image": self._on_media,
            "file": self._on_media,
            "video": self._on_media,
            "voice": self._on_voice,
            "mixed": self._on_mixed,
        }
        handler = handlers.get(str(_body(frame).get("msgtype") or ""))
        if handler is not None:
            await handler(frame)

    async def _disconnect(self) -> None:
        self._sdk.disconnect()

    def supports_streaming(self, conv: Conversation) -> bool:
        # WeCom refreshes a message only as a passive reply to a callback, so a
        # conversation with no inbound frame cannot stream.
        return super().supports_streaming(conv) and conv.key in self._frames

    # -- inbound handlers --------------------------------------------------
    async def _on_text(self, frame: Any) -> None:
        conv = self._conversation(frame)
        self._frames[conv.key] = frame
        body = _body(frame)
        quote_text, quote_media = self._quote_parts(body)
        text = _with_quote(str(_get(body, "text", "content", default="")).strip(), quote_text)
        await self.emit(
            InboundMessage(
                channel=self.name,
                message_id=self._message_id(frame),
                conversation=conv,
                sender=self._sender(body),
                text=text,
                mentions=self._mentions(body),
                attachments=quote_media,
                raw=frame,
            )
        )

    async def _on_media(self, frame: Any) -> None:
        conv = self._conversation(frame)
        self._frames[conv.key] = frame
        body = _body(frame)
        msgtype = str(body.get("msgtype", "file"))
        kind = _kind_for(msgtype)
        quote_text, quote_media = self._quote_parts(body)
        await self.emit(
            InboundMessage(
                channel=self.name,
                message_id=self._message_id(frame),
                conversation=conv,
                sender=self._sender(body),
                text=quote_text,
                attachments=[self._attachment(body, msgtype, kind), *quote_media],
                raw=frame,
            )
        )

    async def _on_voice(self, frame: Any) -> None:
        conv = self._conversation(frame)
        self._frames[conv.key] = frame
        body = _body(frame)
        # Voice messages usually carry platform-recognised text; if they do, that
        # is the user's message and there is no need to fetch the audio (the
        # model cannot consume it anyway). Only fall back to the audio when no
        # text was recognised, so the ingest pipeline can spool it.
        text = str(_get(body, "voice", "content", default="") or "")
        quote_text, quote_media = self._quote_parts(body)
        if not text:
            text = quote_text
        attachments = list(quote_media)
        if not text and _get(body, "voice", "url"):
            attachments.append(self._attachment(body, "voice", "voice"))
        await self.emit(
            InboundMessage(
                channel=self.name,
                message_id=self._message_id(frame),
                conversation=conv,
                sender=self._sender(body),
                text=text,
                attachments=attachments,
                raw=frame,
            )
        )

    async def _on_mixed(self, frame: Any) -> None:
        conv = self._conversation(frame)
        self._frames[conv.key] = frame
        body = _body(frame)
        items = _get(body, "mixed", "msg_item", default=None) or body.get("msg_item") or []
        text, attachments = self._mixed_parts(items)
        quote_text, quote_media = self._quote_parts(body)
        await self.emit(
            InboundMessage(
                channel=self.name,
                message_id=self._message_id(frame),
                conversation=conv,
                sender=self._sender(body),
                text=_with_quote(text, quote_text),
                attachments=[*attachments, *quote_media],
                raw=frame,
            )
        )

    async def _on_enter_chat(self, frame: Any) -> None:
        conv = self._conversation(frame)
        # Not a message callback: do not overwrite `_frames` (see _on_card_event).
        await self.emit(ConnectorEvent(kind="enter_chat", conversation=conv, raw=frame))
        if self._welcome_text:
            try:
                await self._sdk.reply_welcome(
                    frame, {"msgtype": "text", "text": {"content": self._welcome_text}}
                )
            except Exception:  # noqa: BLE001 - welcome is best-effort
                log.warning("welcome_failed", conversation=conv.key)

    async def _on_feedback(self, frame: Any) -> None:
        body = _body(frame)
        await self.emit(
            ConnectorEvent(
                kind="feedback",
                conversation=self._conversation(frame),
                sender=self._sender(body),
                raw=frame,
            )
        )

    async def _on_card_event(self, frame: Any) -> None:
        # Do NOT overwrite `_frames`: streaming replies must use the original
        # message callback's req_id, not this event's (whose req_id is invalid
        # for reply_stream -> WeCom 846605 invalid req_id).
        conv = self._conversation(frame)
        body = _body(frame)
        event = body.get("event") or {}
        # The click payload is nested: event.template_card_event.event_key.
        payload = event.get("template_card_event") if isinstance(event, dict) else None
        if isinstance(payload, dict):
            value = str(payload.get("event_key") or payload.get("key") or "")
            form = _selection_form(payload, value)
        else:
            value = str(event.get("event_key") or event.get("key") or "")
            form = {}
        await self.emit(
            IncomingInteraction(
                conversation=conv,
                message_id=self._message_id(frame),
                sender=self._sender(body),
                value=value,
                form=form,
                raw=frame,
            )
        )

    async def _on_lifecycle(self, *args: Any) -> None:
        # Note: structlog reserves the "event" key for the message, so the detail
        # must use a different field name.
        log.info("wecom_lifecycle", detail=str(args[0]) if args else "")

    # -- outbound primitives ----------------------------------------------
    async def _send_text(
        self, conv: Conversation, text: str, reply_to: str | None, *, final: bool = True
    ) -> str:
        frame = self._frames.get(conv.key)
        stream_id = self._sdk.generate_stream_id()
        if frame is not None:
            # finish closes the streamed message; interim frames keep it open so
            # later updates append to the same message.
            await self._sdk.reply_stream(frame, stream_id, text, finish=final)
        else:
            await self._sdk.send_message(
                conv.id, {"msgtype": "markdown", "markdown": {"content": text}}
            )
        return stream_id

    async def _update_text(self, ref, text: str, *, final: bool = True) -> None:  # noqa: ANN001
        frame = self._frames.get(ref.conversation.key)
        if frame is None:
            raise Unsupported("no active frame to stream an update")
        await self._sdk.reply_stream(frame, ref.id, text, finish=final)

    async def send_card(
        self,
        conv: Conversation,
        card: Card,
        *,
        stream_id: str | None = None,
        text: str | None = None,
    ) -> SentRef:
        """Send an interaction card as a standalone passive reply.

        The streamed-card combination is delivered unreliably by the
        long-connection bot, so every card is sent on its own: a passive reply
        to the inbound frame, then a proactive push as a fallback. ``stream_id``
        and ``text`` are accepted for interface compatibility and ignored.
        """
        payload = _card_payload(card)
        frame = self._frames.get(conv.key)
        if frame is not None:
            # A standalone passive reply renders the card; the streamed-card
            # combination is delivered unreliably by the long-connection bot, so
            # every card is sent on its own.
            try:
                await self._sdk.reply_template_card(frame, payload)
                return SentRef(id="", conversation=conv)
            except Exception as exc:  # noqa: BLE001 - try a proactive card
                log.warning("reply_template_card_failed", conversation=conv.key, error=str(exc))
        await self._sdk.send_message(
            conv.id, {"msgtype": "template_card", "template_card": payload}
        )
        return SentRef(id="", conversation=conv)

    async def acknowledge(self, interaction: IncomingInteraction, text: str) -> None:
        """Rewrite the clicked card to a text notice showing the outcome.

        Uses the click callback's frame (req_id) and the card's task_id, within
        WeCom's 5s update window.
        """
        frame = interaction.raw
        if not isinstance(frame, dict):
            return
        event = _body(frame).get("event") or {}
        payload = event.get("template_card_event") if isinstance(event, dict) else None
        task_id = payload.get("task_id") if isinstance(payload, dict) else None
        if not task_id:
            return
        card = {
            "card_type": "text_notice",
            "main_title": {"title": text},
            # A text_notice card requires a card_action; keep it a plain notice.
            "card_action": {"type": 1, "url": "https://work.weixin.qq.com"},
            "task_id": task_id,
        }
        try:
            await self._sdk.update_template_card(frame, card)
        except Exception as exc:  # noqa: BLE001 - best-effort acknowledgement
            log.warning(
                "acknowledge_failed", conversation=interaction.conversation.key, error=str(exc)
            )

    async def _send_card(self, conv: Conversation, card: Card) -> str:
        payload = _card_payload(card)
        frame = self._frames.get(conv.key)
        if frame is not None:
            await self._sdk.reply_template_card(frame, payload)
        else:
            await self._sdk.send_message(
                conv.id, {"msgtype": "template_card", "template_card": payload}
            )
        return "card"

    async def _send_media(self, conv: Conversation, media: RichMedia) -> str:
        if media.data is None:
            raise Unsupported("wecom media send requires bytes")
        media_type = _wecom_media_type(media.kind)
        filename = _filename(media.name, media.mime, media_type)
        media_id = await self._sdk.upload_media(media.data, media_type, filename)
        frame = self._frames.get(conv.key)
        if frame is not None:
            try:
                await self._sdk.reply_media(frame, media_type, media_id)
                return "media"
            except Exception as exc:  # noqa: BLE001
                # The reply slot may already hold the text stream or a card, so
                # fall through to a proactive push instead of failing.
                log.warning("wecom_reply_media_failed", conversation=conv.key, error=str(exc))
        await self._sdk.send_media_message(conv.id, media_type, media_id)
        return "media"

    async def _typing(self, conv: Conversation) -> None:
        raise Unsupported("WeCom has no typing indicator")

    # -- media -------------------------------------------------------------
    async def download(self, att: Attachment) -> MediaBytes:
        handle = att.handle or {}
        url = handle.get("url")
        if not url:
            raise Unsupported("wecom attachment has no url")
        data, name = await self._sdk.download_file(url, handle.get("aeskey"))
        return MediaBytes(data=data, mime=att.mime, name=name or att.name)

    async def upload(self, data: MediaBytes, *, kind: str) -> MediaHandle:
        media_type = _wecom_media_type(kind)
        filename = _filename(data.name, data.mime, media_type)
        media_id = await self._sdk.upload_media(data.data, media_type, filename)
        return MediaHandle(handle=media_id, kind=normalize_media_kind(kind))

    async def identity(self, conv: Conversation) -> BotIdentity:
        # WeCom never sends the bot's name (the callback carries only `aibotid`),
        # so this id is just a fallback: the configured identity overrides it.
        return BotIdentity(name=self._bot_id, aliases=(self._bot_id,))

    # -- helpers -----------------------------------------------------------
    def _message_id(self, frame: Any) -> str:
        """A stable per-message id, falling back to the push request id.

        Without a non-empty id, the bridge's dedup key would be identical for
        every message in a conversation and all but the first would be dropped.
        """
        body = _body(frame)
        message_id = body.get("msgid") or body.get("message_id")
        if message_id:
            return str(message_id)
        headers = frame.get("headers") if isinstance(frame, dict) else None
        if isinstance(headers, dict) and headers.get("req_id"):
            return str(headers["req_id"])
        return ""

    def _quote_parts(self, body: dict) -> tuple[str, list[Attachment]]:
        """A referenced ("quoted") message: its text and any media attachment.

        A WeCom reply/quote is delivered inside the message body's ``quote``
        field, carrying the same shape as a normal message, so a quoted file
        must be turned into an attachment or it is lost.
        """
        quote = body.get("quote")
        if not isinstance(quote, dict):
            return "", []
        qtype = str(quote.get("msgtype") or "")
        if qtype == "text":
            section = quote.get("text") or {}
            return str(section.get("content") or ""), []
        if qtype in ("image", "file", "voice", "video"):
            return "", [self._attachment(quote, qtype, _kind_for(qtype))]
        if qtype == "mixed":
            items = _get(quote, "mixed", "msg_item", default=None) or quote.get("msg_item") or []
            return self._mixed_parts(items)
        return "", []

    def _mixed_parts(self, items: Any) -> tuple[str, list[Attachment]]:
        texts: list[str] = []
        attachments: list[Attachment] = []
        for item in items or []:
            if not isinstance(item, dict):
                continue
            item_type = item.get("msgtype")
            if item_type == "text":
                texts.append(str(_get(item, "text", "content", default="")))
            elif item_type in ("image", "file", "voice"):
                attachments.append(self._attachment(item, item_type, _kind_for(item_type)))
        return "\n".join(t for t in texts if t), attachments

    def _attachment(self, body: dict, msgtype: str, kind: str) -> Attachment:
        section = body.get(msgtype) or {}
        handle = {"url": section.get("url"), "aeskey": section.get("aeskey")}
        name = section.get("filename") or section.get("name")
        return Attachment(kind=kind, name=name, handle=handle)  # type: ignore[arg-type]

    def _conversation(self, frame: Any) -> Conversation:
        body = _body(frame)
        chatid = str(body.get("chatid") or "")
        chattype = str(body.get("chattype") or "").lower()
        is_group = chattype == "group"
        identifier = chatid or str(_get(body, "from", "userid", default="") or "")
        return Conversation(
            channel=self.name, kind="group" if is_group else "direct", id=identifier
        )

    def _sender(self, body: dict) -> Sender:
        raw_from = body.get("from")
        if isinstance(raw_from, dict):
            return Sender(
                id=str(raw_from.get("userid") or raw_from.get("id") or ""),
                name=raw_from.get("name"),
            )
        if raw_from is not None:
            return Sender(id=str(raw_from))
        return Sender(id=str(body.get("userid") or "unknown"))

    def _mentions(self, body: dict) -> list[Sender]:
        raw = body.get("mentions") or []
        out: list[Sender] = []
        for item in raw:
            if isinstance(item, dict):
                out.append(
                    Sender(
                        id=str(item.get("userid") or item.get("id") or ""), name=item.get("name")
                    )
                )
        return out


def _body(frame: Any) -> dict:
    return frame.get("body") or {} if isinstance(frame, dict) else {}


def _with_quote(text: str, quote_text: str) -> str:
    """Prefix the referenced ("quoted") text, if any, above the message text."""
    if not quote_text:
        return text
    return f"[quoting] {quote_text}\n{text}".rstrip()


def _get(obj: Any, *keys: str, default: Any = None) -> Any:
    for key in keys:
        if not isinstance(obj, dict):
            return default
        obj = obj.get(key)
        if obj is None:
            return default
    return obj


def _card_payload(card: Card) -> dict:
    """Build the WeCom template card for our card model.

    Questions that need a form (a multi-choice question, or several questions)
    use ``vote_interaction`` / ``multiple_interaction``; everything else uses a
    ``button_interaction`` card. A shape WeCom cannot express raises
    :class:`Unsupported` so the caller can fall back to a numbered prompt.
    """
    if card.questions:
        return _questions_card(card)
    return _button_card(card)


def _button_card(card: Card) -> dict:
    """Build a WeCom ``button_interaction`` template card from our card model.

    WeCom requires ``task_id`` on interaction cards; a missing one makes the
    platform drop the buttons (the card renders without the selectable options).
    """
    button_list = [
        {"text": button.text, "key": button.value, "style": _button_style(button.style, index)}
        for index, button in enumerate(card.buttons)
    ]
    return {
        "card_type": "button_interaction",
        "main_title": {"title": card.title or "", "desc": card.body},
        "button_list": button_list,
        "task_id": f"tether-{uuid.uuid4().hex}",
    }


def _button_style(style: str | None, index: int) -> int:
    """Map a button's semantic style to a WeCom button style (1..4)."""
    return {"primary": 1, "danger": 4}.get(style or "", (index % 4) + 1)


def _questions_card(card: Card) -> dict:
    """Build a WeCom card for a multi-choice or multiple-question prompt.

    A single multi-choice question becomes a ``vote_interaction`` (checkbox with
    ``mode: 1``); several single-choice questions become a ``multiple_interaction``
    (one dropdown each). Any other mix is not expressible as a WeCom card and
    raises :class:`Unsupported` so the caller falls back to numbered text.
    """
    if len(card.questions) == 1:
        question = card.questions[0]
        return {
            "card_type": "vote_interaction",
            "main_title": {"title": card.title or "", "desc": question.header or question.body},
            "checkbox": {
                "question_key": "q0",
                "mode": 1 if question.multiple else 0,
                "option_list": [
                    {"id": str(index), "text": label, "is_checked": False}
                    for index, label in enumerate(question.options)
                ],
            },
            "submit_button": {"text": "提交", "key": card.submit_value},
            "task_id": f"tether-{uuid.uuid4().hex}",
        }
    # A ``multiple_interaction`` card holds at most 3 selectors; a multi-choice
    # question cannot be combined with others. Anything else falls back to the
    # numbered prompt.
    if len(card.questions) > 3 or any(question.multiple for question in card.questions):
        raise Unsupported("WeCom supports at most 3 single-choice questions per card")
    return {
        "card_type": "multiple_interaction",
        "main_title": {"title": card.title or "", "desc": ""},
        "select_list": [
            {
                "question_key": f"q{index}",
                "title": question.header or question.body or f"问题 {index + 1}",
                "option_list": [
                    {"id": str(option_index), "text": label}
                    for option_index, label in enumerate(question.options)
                ],
            }
            for index, question in enumerate(card.questions)
        ],
        "submit_button": {"text": "提交", "key": card.submit_value},
        "task_id": f"tether-{uuid.uuid4().hex}",
    }


def _selection_form(payload: dict, value: str) -> dict[str, Any]:
    """Map a vote/multiple-interaction submit to our ``q{i}`` / ``q{i}_{j}`` form.

    The card encodes each option's ``id`` as its index and each question's
    ``question_key`` as ``q{i}``; the submit key carries the specs, so the
    selected indices resolve back to option labels here.
    """
    items = (payload.get("selected_items") or {}).get("selected_item") or []
    specs = _question_specs(value)
    if not specs or not items:
        return {}
    form: dict[str, Any] = {}
    for item in items:
        key = str(item.get("question_key") or "")
        if len(key) < 2 or key[0] != "q" or not key[1:].isdigit():
            continue
        index = int(key[1:])
        if index >= len(specs):
            continue
        option_ids = (item.get("option_ids") or {}).get("option_id") or []
        spec = specs[index]
        if spec.get("multiple"):
            for option_id in option_ids:
                form[f"q{index}_{option_id}"] = True
        elif option_ids:
            options = spec.get("options") or []
            raw = str(option_ids[0])
            choice = int(raw) if raw.isdigit() else -1
            if 0 <= choice < len(options):
                form[f"q{index}"] = options[choice]
    return form


def _question_specs(value: str) -> list[dict]:
    """The question specs encoded in a form's submit key (``{"specs": [...]}``)."""
    try:
        data = json.loads(value)
    except (ValueError, TypeError):
        return []
    specs = data.get("specs") if isinstance(data, dict) else None
    return specs if isinstance(specs, list) else []


__all__ = ["WeComConnector", "WeComSDK", "AibotSDK", "wecom_capabilities"]

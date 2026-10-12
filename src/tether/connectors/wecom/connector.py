"""WeCom smart-robot connector over the official long-connection SDK.

The SDK is hidden behind the :class:`WeComSDK` protocol so the core stays
SDK-free and this connector can be exercised with a fake SDK. Frames are plain
dicts shaped ``{"cmd": ..., "headers": {"req_id": ...}, "body": {...}}``.
"""

from __future__ import annotations

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
    buttons=True,
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
    async def reply_stream_with_card(
        self, frame: Any, stream_id: str, content: str, finish: bool, template_card: dict
    ) -> Any: ...
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

    def __init__(self, bot_id: str, secret: str) -> None:
        self._bot_id = bot_id
        self._secret = secret
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
                aibot.WSClientOptions(bot_id=self._bot_id, secret=self._secret)
            )
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

    async def reply_stream_with_card(self, frame, stream_id, content, finish, template_card) -> Any:
        return await self._ensure_client().reply_stream_with_card(
            frame, stream_id, content, finish=finish, template_card=template_card
        )

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
    ) -> None:
        super().__init__(wecom_capabilities)
        self._bot_id = bot_id
        self._secret = secret
        self._sdk: WeComSDK = sdk or AibotSDK(bot_id, secret)
        self._welcome_text = welcome_text
        self._frames: dict[str, Any] = {}

    # -- lifecycle ---------------------------------------------------------
    async def _connect(self) -> None:
        self._sdk.on("message.text", self._on_text)
        self._sdk.on("message.image", self._on_media)
        self._sdk.on("message.file", self._on_media)
        self._sdk.on("message.voice", self._on_voice)
        self._sdk.on("message.mixed", self._on_mixed)
        self._sdk.on("event.enter_chat", self._on_enter_chat)
        self._sdk.on("event.template_card_event", self._on_card_event)
        self._sdk.on("event.feedback_event", self._on_feedback)
        for event in _LIFECYCLE_EVENTS:
            self._sdk.on(event, self._on_lifecycle)
        await self._sdk.connect()

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
        await self.emit(
            InboundMessage(
                channel=self.name,
                message_id=self._message_id(frame),
                conversation=conv,
                sender=self._sender(body),
                text=str(_get(body, "text", "content", default="")),
                mentions=self._mentions(body),
                raw=frame,
            )
        )

    async def _on_media(self, frame: Any) -> None:
        conv = self._conversation(frame)
        self._frames[conv.key] = frame
        body = _body(frame)
        msgtype = str(body.get("msgtype", "file"))
        kind = {"image": "image", "file": "file", "voice": "voice"}.get(msgtype, "file")
        await self.emit(
            InboundMessage(
                channel=self.name,
                message_id=self._message_id(frame),
                conversation=conv,
                sender=self._sender(body),
                text="",
                attachments=[self._attachment(body, msgtype, kind)],
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
        attachments = []
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
        texts: list[str] = []
        attachments = []
        for item in items:
            if not isinstance(item, dict):
                continue
            item_type = item.get("msgtype")
            if item_type == "text":
                texts.append(str(_get(item, "text", "content", default="")))
            elif item_type in ("image", "file", "voice"):
                attachments.append(self._attachment(item, item_type, item_type))
        await self.emit(
            InboundMessage(
                channel=self.name,
                message_id=self._message_id(frame),
                conversation=conv,
                sender=self._sender(body),
                text="\n".join(t for t in texts if t),
                attachments=attachments,
                raw=frame,
            )
        )

    async def _on_enter_chat(self, frame: Any) -> None:
        from ...models import ConnectorEvent

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
        from ...models import ConnectorEvent

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
        else:
            value = str(event.get("event_key") or event.get("key") or "")
        await self.emit(
            IncomingInteraction(
                conversation=conv,
                message_id=self._message_id(frame),
                sender=self._sender(body),
                value=value,
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
        """Send an interaction card with fallbacks.

        WeCom binds a message to a single reply mode, so a card attached to an
        already-open text stream (``stream_with_template_card``) can be rejected.
        Try, in order: attach to the stream, a standalone passive card, then a
        proactive card — so the user always gets the selectable options.
        """
        payload = _button_card(card)
        frame = self._frames.get(conv.key)
        if frame is not None:
            sid = stream_id or self._sdk.generate_stream_id()
            try:
                await self._sdk.reply_stream_with_card(
                    frame, sid, text or "", finish=False, template_card=payload
                )
                return SentRef(id=sid, conversation=conv)
            except Exception as exc:  # noqa: BLE001 - try the standalone forms
                log.warning("reply_stream_with_card_failed", conversation=conv.key, error=str(exc))
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
        card = {"card_type": "text_notice", "main_title": {"title": text}, "task_id": task_id}
        try:
            await self._sdk.update_template_card(frame, card)
        except Exception:  # noqa: BLE001 - best-effort acknowledgement
            log.warning("acknowledge_failed", conversation=interaction.conversation.key)

    async def _send_card(self, conv: Conversation, card: Card) -> str:
        payload = _button_card(card)
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


def _get(obj: Any, *keys: str, default: Any = None) -> Any:
    for key in keys:
        if not isinstance(obj, dict):
            return default
        obj = obj.get(key)
        if obj is None:
            return default
    return obj


def _button_card(card: Card) -> dict:
    """Build a WeCom ``button_interaction`` template card from our card model.

    WeCom requires ``task_id`` on interaction cards; a missing one makes the
    platform drop the buttons (the card renders without the selectable options).
    """
    button_list = [
        {"text": button.text, "key": button.value, "style": (index % 4) + 1}
        for index, button in enumerate(card.buttons)
    ]
    return {
        "card_type": "button_interaction",
        "main_title": {"title": card.title or "", "desc": card.body},
        "button_list": button_list,
        "task_id": f"tether-{uuid.uuid4().hex}",
    }


__all__ = ["WeComConnector", "WeComSDK", "AibotSDK", "wecom_capabilities"]

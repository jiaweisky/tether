"""WeCom smart-robot connector over the long-connection API.

The official SDK is hidden behind the :class:`WeComSDK` protocol so the core
stays SDK-free and this connector can be exercised with a fake SDK. The exact
SDK call signatures must be verified against the live service before use.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
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
)
from ...util.logging import get_logger
from ..base import BaseConnector

log = get_logger("tether.wecom")

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
    media_out=frozenset({"image", "file", "audio", "video"}),
)


class WeComSDK(Protocol):
    async def start(self, handlers: dict[str, Callable[..., Awaitable[None]]]) -> None: ...
    async def stop(self) -> None: ...
    async def reply_stream(
        self,
        frame: Any,
        stream_id: str,
        content: str,
        finish: bool,
        msg_item: list[dict] | None = None,
    ) -> None: ...
    async def reply_template_card(self, frame: Any, card: dict) -> None: ...
    async def send_message(self, chatid: str, body: dict) -> None: ...
    async def download_file(self, url: str, aes_key: str) -> tuple[bytes, str]: ...
    async def upload_media(self, data: bytes, kind: str, name: str | None) -> dict: ...


class AibotSDK:
    """Adapter over the real ``wecom-aibot-python-sdk`` (``aibot``)."""

    def __init__(self, bot_id: str, secret: str) -> None:
        self.bot_id = bot_id
        self.secret = secret
        self._client: Any = None

    async def start(self, handlers: dict[str, Callable[..., Awaitable[None]]]) -> None:
        try:
            import aibot
        except ImportError as exc:  # pragma: no cover - optional extra
            raise Unsupported(
                "wecom-aibot-python-sdk is not installed; install tether[wecom]"
            ) from exc
        self._client = aibot.WSClient(aibot.WSClientOptions(bot_id=self.bot_id, secret=self.secret))
        for event, handler in handlers.items():
            self._client.on(event, handler)
        self._runner = asyncio.ensure_future(self._client.run_forever())

    async def stop(self) -> None:
        if self._client is not None:
            close = getattr(self._client, "close", None)
            if close:
                result = close()
                if asyncio.iscoroutine(result):
                    await result

    async def reply_stream(self, frame, stream_id, content, finish, msg_item=None) -> None:
        await self._client.reply_stream(frame, stream_id, content, finish=finish, msg_item=msg_item)

    async def reply_template_card(self, frame, card) -> None:
        await self._client.reply_template_card(frame, card)

    async def send_message(self, chatid, body) -> None:
        await self._client.send_message(chatid, body)

    async def download_file(self, url, aes_key):
        return await self._client.download_file(url, aes_key)

    async def upload_media(self, data, kind, name):
        return await self._client.upload_media(data, kind, name)


class WeComConnector(BaseConnector):
    name = "wecom"
    capabilities = wecom_capabilities

    def __init__(self, *, bot_id: str, secret: str, sdk: WeComSDK | None = None) -> None:
        super().__init__(wecom_capabilities)
        self._bot_id = bot_id
        self._secret = secret
        self._sdk: WeComSDK = sdk or AibotSDK(bot_id, secret)
        self._frames: dict[str, Any] = {}
        self._stream_ids: dict[str, str] = {}

    async def _connect(self) -> None:
        await self._sdk.start(
            {
                "message.text": self._on_text,
                "message.image": self._on_media_message,
                "message.file": self._on_media_message,
                "message.voice": self._on_media_message,
                "message.mixed": self._on_mixed,
                "event.enter_chat": self._on_enter_chat,
                "event.template_card_event": self._on_card_event,
                "event.feedback_event": self._on_feedback,
            }
        )

    async def _disconnect(self) -> None:
        await self._sdk.stop()

    # -- inbound handlers --------------------------------------------------
    async def _on_text(self, frame: Any) -> None:
        conv = self._conversation(frame)
        self._frames[conv.key] = frame
        sender = self._sender(frame)
        text = _get(frame, "body.text", "text", default="")
        await self.emit(
            InboundMessage(
                channel=self.name,
                message_id=str(_get(frame, "msg_id", "message_id", default="")),
                conversation=conv,
                sender=sender,
                text=str(text or ""),
                mentions=self._mentions(frame),
                raw=frame,
            )
        )

    async def _on_media_message(self, frame: Any) -> None:
        conv = self._conversation(frame)
        self._frames[conv.key] = frame
        body = frame.get("body", frame) if isinstance(frame, dict) else {}
        kind = str(body.get("msgtype") or "file")
        att = Attachment(
            kind=kind if kind in ("image", "voice", "file") else "file",  # type: ignore[arg-type]
            handle={"url": body.get("url"), "aeskey": body.get("aeskey")},
        )
        await self.emit(
            InboundMessage(
                channel=self.name,
                message_id=str(_get(frame, "msg_id", default="")),
                conversation=conv,
                sender=self._sender(frame),
                text="",
                attachments=[att],
                raw=frame,
            )
        )

    async def _on_mixed(self, frame: Any) -> None:
        await self._on_text(frame)

    async def _on_enter_chat(self, frame: Any) -> None:
        from ...models import ConnectorEvent

        conv = self._conversation(frame)
        self._frames[conv.key] = frame
        await self.emit(ConnectorEvent(kind="enter_chat", conversation=conv, raw=frame))

    async def _on_feedback(self, frame: Any) -> None:
        from ...models import ConnectorEvent

        conv = self._conversation(frame)
        await self.emit(
            ConnectorEvent(
                kind="feedback", conversation=conv, sender=self._sender(frame), raw=frame
            )
        )

    async def _on_card_event(self, frame: Any) -> None:
        conv = self._conversation(frame)
        event = frame.get("event", {}) if isinstance(frame, dict) else {}
        await self.emit(
            IncomingInteraction(
                conversation=conv,
                message_id=str(_get(frame, "msg_id", default="")),
                sender=self._sender(frame),
                value=str(event.get("value") or _get(frame, "body.event_key", default="")),
                raw=frame,
            )
        )

    # -- outbound primitives ----------------------------------------------
    async def _send_text(self, conv, text, reply_to):
        frame = self._frames.get(conv.key)
        stream_id = f"stream-{conv.key}-{len(self._stream_ids)}"
        self._stream_ids[conv.key] = stream_id
        if frame is not None:
            await self._sdk.reply_stream(frame, stream_id, text, finish=True)
        else:
            await self._sdk.send_message(
                conv.id, {"msgtype": "markdown", "markdown": {"content": text}}
            )
        return stream_id

    async def _update_text(self, ref, text):
        frame = self._frames.get(ref.conversation.key)
        if frame is None:
            raise Unsupported("no active frame for streaming update")
        await self._sdk.reply_stream(frame, ref.id, text, finish=False)

    async def _send_card(self, conv, card: Card):
        frame = self._frames.get(conv.key)
        payload = {
            "card_type": "button_interaction",
            "main_title": {"title": card.title or ""},
            "sub_title_text": card.body,
            "button_list": [{"text": b.text, "key": b.value} for b in card.buttons],
        }
        if frame is not None:
            await self._sdk.reply_template_card(frame, payload)
        else:
            await self._sdk.send_message(
                conv.id, {"msgtype": "template_card", "template_card": payload}
            )
        return "card"

    async def _send_media(self, conv, media: RichMedia):
        if media.data is None:
            raise Unsupported("wecom outbound media requires bytes")
        ref = await self._sdk.upload_media(media.data, media.kind, media.name)
        body = {"msgtype": _wecom_msgtype(media.kind), _wecom_body_key(media.kind): ref}
        frame = self._frames.get(conv.key)
        if frame is not None:
            await self._sdk.send_message(conv.id, body)
        else:
            await self._sdk.send_message(conv.id, body)
        return "media"

    # -- media -------------------------------------------------------------
    async def download(self, att: Attachment) -> MediaBytes:
        handle = att.handle or {}
        url = handle.get("url")
        aeskey = handle.get("aeskey", "")
        if not url:
            raise Unsupported("wecom attachment has no url")
        data, name = await self._sdk.download_file(url, aeskey)
        return MediaBytes(data=data, mime=att.mime, name=name or att.name)

    async def upload(self, data: MediaBytes, *, kind: str) -> MediaHandle:
        ref = await self._sdk.upload_media(data.data, kind, data.name)
        return MediaHandle(handle=ref, kind=kind)  # type: ignore[arg-type]

    async def identity(self, conv: Conversation) -> BotIdentity:
        return BotIdentity(name=self._bot_id, aliases=(self._bot_id,))

    # -- helpers -----------------------------------------------------------
    def _conversation(self, frame: Any) -> Conversation:
        chatid = str(_get(frame, "chatid", "chat_id", "from", default="unknown"))
        is_group = bool(
            _get(frame, "chattype", default="") == "group"
            or str(_get(frame, "chatid", default="")).startswith("wr")
        )
        return Conversation(channel=self.name, kind="group" if is_group else "direct", id=chatid)

    def _sender(self, frame: Any) -> Sender:
        return Sender(
            id=str(_get(frame, "from", "userid", "sender", default="unknown")),
            name=_get(frame, "sender_name", "name"),
        )

    def _mentions(self, frame: Any) -> list[Sender]:
        raw = _get(frame, "mentions", default=[]) or []
        out: list[Sender] = []
        for m in raw:
            if isinstance(m, dict):
                out.append(Sender(id=str(m.get("id", "")), name=m.get("name")))
        return out


def _get(obj: Any, *keys: str, default: Any = None) -> Any:
    if not isinstance(obj, dict):
        return default
    for key in keys:
        if key in obj and obj[key] is not None:
            return obj[key]
    return default


def _wecom_msgtype(kind: str) -> str:
    return {"image": "image", "audio": "voice", "video": "video", "file": "file"}.get(kind, "file")


def _wecom_body_key(kind: str) -> str:
    return {"image": "image", "audio": "voice", "video": "video", "file": "file"}.get(kind, "file")

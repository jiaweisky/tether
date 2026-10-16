"""Feishu (Lark) connector over the official ``lark-oapi`` long connection.

The SDK's WebSocket client is *blocking* (it runs its own event loop and invokes
*synchronous* handlers), and its REST client is synchronous too. So the stream
runs in a dedicated daemon thread, its handlers hop back onto Tether's loop, and
every REST call is dispatched with ``asyncio.to_thread``. The SDK is hidden
behind the :class:`FeishuSDK` protocol so the connector can be exercised with a
fake (no network, no thread).
"""

from __future__ import annotations

import asyncio
import json
import threading
from typing import Any, Protocol

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
    RichMedia,
    Sender,
    SentRef,
    normalize_media_kind,
)
from ...util.logging import get_logger
from ..base import BaseConnector

log = get_logger("tether.feishu")

feishu_capabilities = Capabilities(
    markdown=MarkdownLevel.STANDARD,
    code_block=True,
    tables=False,
    headings=False,
    images_inline=False,
    edit_message=True,
    native_stream=False,
    buttons=True,
    question_form=True,
    reactions=False,
    typing=False,
    proactive=True,
    groups=True,
    mention=True,
    callback_actor_identity=True,
    member_roles=False,
    direct_delivery="unknown",
    group_delivery="mention_only",
    max_text_chars=8000,
    media_in=frozenset({"image", "audio", "video", "file"}),
    media_out=frozenset({"image", "audio", "video", "file"}),
)

# Feishu message_type values we accept inbound.
_MEDIA_TYPES = {
    "image": "image",
    "file": "file",
    "audio": "audio",
    "media": "video",
    "sticker": "image",
}


class FeishuSDK(Protocol):
    """The subset of the Feishu SDK the connector uses (sync calls)."""

    def start(self, on_message: Any, on_card: Any, on_recall: Any) -> None: ...
    def stop(self) -> None: ...
    @property
    def connected(self) -> bool: ...
    def reply(self, message_id: str, msg_type: str, content: dict) -> str: ...
    def send(self, chat_id: str, msg_type: str, content: dict) -> str: ...
    def patch(self, message_id: str, content: dict) -> None: ...
    def upload_image(self, data: bytes, filename: str) -> str: ...
    def upload_file(self, data: bytes, filename: str, kind: str) -> str: ...
    def download(self, message_id: str, file_key: str, kind: str) -> bytes: ...
    def bot_info(self) -> tuple[str | None, str | None]: ...


class FeishuConnector(BaseConnector):
    name = "feishu"

    def __init__(
        self,
        *,
        app_id: str,
        app_secret: str,
        sdk: FeishuSDK | None = None,
    ) -> None:
        super().__init__(feishu_capabilities)
        self._app_id = app_id
        self._app_secret = app_secret
        self._sdk: FeishuSDK = sdk or LarkSDK(app_id, app_secret)
        self._loop: asyncio.AbstractEventLoop | None = None
        self._bot: tuple[str | None, str | None] | None = None

    # -- lifecycle ---------------------------------------------------------
    async def _connect(self) -> None:
        self._loop = asyncio.get_running_loop()
        try:
            await asyncio.to_thread(
                self._sdk.start, self._on_message, self._on_card, self._on_recall
            )
        except Exception:  # noqa: BLE001 - a failed channel must not kill Tether
            log.error("feishu_stream_failed", exc_info=True)
        try:
            self._bot = await asyncio.to_thread(self._sdk.bot_info)
        except Exception:  # noqa: BLE001 - identity is best-effort
            log.warning("feishu_bot_info_failed", exc_info=True)

    async def _disconnect(self) -> None:
        try:
            await asyncio.to_thread(self._sdk.stop)
        except Exception:  # noqa: BLE001
            log.warning("feishu_stop_failed", exc_info=True)

    @property
    def connected(self) -> bool:
        return self._sdk.connected

    # -- inbound (called from the SDK thread; hop back to Tether's loop) ---
    def _on_message(self, event: Any) -> None:
        try:
            item = self._inbound_message(event)
        except Exception:  # noqa: BLE001 - a parse error must not kill the stream
            log.warning("feishu_message_parse_failed", exc_info=True)
            return
        if item is not None:
            self._submit(item)

    def _on_card(self, event: Any) -> None:
        try:
            item = self._inbound_card(event)
        except Exception:  # noqa: BLE001
            log.warning("feishu_card_parse_failed", exc_info=True)
            return
        if item is not None:
            self._submit(item)

    def _on_recall(self, event: Any) -> None:
        try:
            message = _get(event, "event", "message") or {}
            item = ConnectorEvent(
                kind="recall",
                conversation=self._conversation(message),
                message_id=str(_get(message, "message_id") or ""),
                raw={"event": "recall"},
            )
        except Exception:  # noqa: BLE001
            log.warning("feishu_recall_parse_failed", exc_info=True)
            return
        self._submit(item)

    def _submit(self, item: Any) -> None:
        loop = self._loop
        if loop is None:
            return
        asyncio.run_coroutine_threadsafe(self.emit(item), loop)

    def _inbound_message(self, event: Any) -> InboundMessage | None:
        message = _get(event, "event", "message") or {}
        message_id = str(_get(message, "message_id") or "")
        if not message_id:
            return None
        sender = _get(event, "event", "sender") or {}
        raw_mentions = _get(message, "mentions") or []
        content = _parse_content(_get(message, "message_type"), _get(message, "content"))
        conv = self._conversation(message)
        return InboundMessage(
            channel=self.name,
            message_id=message_id,
            conversation=conv,
            sender=self._sender(sender),
            text=_replace_mentions(content.text, raw_mentions),
            mentions=_mentions(raw_mentions),
            attachments=content.attachments(message_id),
            raw={"message": message},
        )

    def _inbound_card(self, event: Any) -> IncomingInteraction | None:
        action = _get(event, "event", "action") or {}
        value = _get(action, "value")
        if isinstance(value, dict):
            payload = str(value.get("key") or json.dumps(value))
        else:
            payload = str(value or "")
        operator = _get(event, "event", "operator") or {}
        context = _get(event, "event", "context") or {}
        sender = _get(operator, "open_id") or _get(operator, "user_id") or "unknown"
        form = _get(action, "form_value")
        return IncomingInteraction(
            conversation=self._conversation_from(
                _get(context, "chat_id"), _get(context, "chat_type")
            ),
            message_id=str(_get(context, "open_message_id") or ""),
            sender=Sender(id=str(sender)),
            value=payload,
            form=dict(form) if isinstance(form, dict) else {},
            raw={"event": "card"},
        )

    # -- conversation / sender helpers ------------------------------------
    def _conversation(self, message: dict) -> Conversation:
        return self._conversation_from(_get(message, "chat_id"), _get(message, "chat_type"))

    def _conversation_from(self, chat_id: Any, chat_type: Any) -> Conversation:
        return Conversation(
            channel=self.name,
            kind="group" if chat_type == "group" else "direct",
            id=str(chat_id or ""),
        )

    def _sender(self, sender: dict) -> Sender:
        sid = _get(sender, "sender_id") or {}
        ident = _get(sid, "open_id") or _get(sid, "user_id") or _get(sid, "union_id") or "unknown"
        return Sender(id=str(ident))

    # -- outbound ----------------------------------------------------------
    async def _send_text(
        self, conv: Conversation, text: str, reply_to: str | None, *, final: bool = True
    ) -> str:
        # Text goes out as an interactive card whose body is a ``markdown``
        # component, so Markdown renders; a plain ``text`` message would show it
        # literally.
        card = _markdown_card(text)
        if reply_to:
            try:
                return await self._call(self._sdk.reply, reply_to, "interactive", card)
            except Exception:  # noqa: BLE001 - a stale reply target: send fresh
                log.warning("feishu_reply_failed", exc_info=True)
        return await self._call(self._sdk.send, conv.id, "interactive", card)

    async def _update_text(self, ref: SentRef, text: str, *, final: bool = True) -> None:
        if not ref.id:
            raise Unsupported("feishu has no message id to edit")
        await self._call(self._sdk.patch, ref.id, _markdown_card(text))

    async def acknowledge(self, interaction: IncomingInteraction, text: str) -> None:
        """Rewrite the clicked card to a text notice showing the outcome."""
        if not interaction.message_id:
            return
        # The clicked card is JSON 2.0, so the replacement content must be too.
        notice = _card2([{"tag": "markdown", "content": text}])
        try:
            await self._call(self._sdk.patch, interaction.message_id, notice)
        except Exception:  # noqa: BLE001 - best-effort acknowledgement
            log.warning("feishu_acknowledge_failed", conversation=interaction.conversation.key)

    async def _send_card(self, conv: Conversation, card: Card) -> str:
        payload = _interactive_card(card)
        return await self._call(self._sdk.send, conv.id, "interactive", payload)

    async def _send_media(self, conv: Conversation, media: RichMedia) -> str:
        if media.data is None:
            raise Unsupported("feishu media send requires bytes")
        kind = normalize_media_kind(media.kind)
        filename = media.name or kind
        if kind == "image":
            key = await self._call(self._sdk.upload_image, media.data, filename)
            content = {"image_key": key}
        else:
            key = await self._call(self._sdk.upload_file, media.data, filename, kind)
            content = {"file_key": key}
        msg_type = "image" if kind == "image" else "file"
        return await self._call(self._sdk.send, conv.id, msg_type, content)

    async def _typing(self, conv: Conversation) -> None:
        raise Unsupported("Feishu has no typing indicator")

    async def _react(self, ref: SentRef, emoji: str) -> None:
        raise Unsupported("Feishu reactions are not wired")

    # -- media / identity --------------------------------------------------
    async def download(self, att: Attachment) -> MediaBytes:
        handle = att.handle or {}
        message_id = str(handle.get("message_id") or "")
        file_key = str(handle.get("file_key") or "")
        if not message_id or not file_key:
            raise Unsupported("feishu attachment has no message_id/file_key")
        kind = "image" if normalize_media_kind(att.kind) == "image" else "file"
        data = await self._call(self._sdk.download, message_id, file_key, kind)
        return MediaBytes(data=data, mime=att.mime, name=att.name)

    async def upload(self, data: MediaBytes, *, kind: str) -> MediaHandle:
        normalized = normalize_media_kind(kind)
        if normalized == "image":
            key = await self._call(self._sdk.upload_image, data.data, data.name or "image")
        else:
            key = await self._call(
                self._sdk.upload_file, data.data, data.name or "file", normalized
            )
        return MediaHandle(handle=key, kind=normalized)

    async def identity(self, conv: Conversation) -> BotIdentity:
        name, description = self._bot or (None, None)
        return BotIdentity(
            name=name or self._app_id, description=description, aliases=(name,) if name else ()
        )

    async def _call(self, fn: Any, *args: Any) -> Any:
        return await asyncio.to_thread(fn, *args)


# -- inbound content parsing ----------------------------------------------


class _ParsedContent:
    def __init__(self, text: str, media: list[tuple[str, str, str | None]]) -> None:
        self.text = text
        self._media = media  # (kind, file_key, name)

    def attachments(self, message_id: str) -> list[Attachment]:
        return [
            Attachment(
                kind=kind,  # type: ignore[arg-type]
                name=name,
                handle={"message_id": message_id, "file_key": key},
            )
            for kind, key, name in self._media
        ]


def _parse_content(message_type: Any, content: Any) -> _ParsedContent:
    data = _json(content)
    kind = str(message_type or "")
    if kind == "text":
        return _ParsedContent(str(data.get("text") or ""), [])
    if kind == "post":
        return _ParsedContent(_post_text(data), [])
    if kind in _MEDIA_TYPES:
        media_kind = _MEDIA_TYPES[kind]
        # Only images/stickers carry ``image_key``; a video ("media") also has a
        # cover ``image_key``, so its file must be read from ``file_key``.
        source = "image_key" if media_kind == "image" else "file_key"
        key = str(data.get(source) or "")
        name = data.get("file_name")
        media = [(media_kind, key, str(name) if name else None)] if key else []
        return _ParsedContent("", media)
    return _ParsedContent("", [])


def _post_text(data: dict) -> str:
    """Flatten a Feishu ``post`` (rich text) body into plain text."""
    parts: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, str):
            parts.append(node)
        elif isinstance(node, dict):
            if node.get("tag") in ("text", "a") and node.get("text"):
                parts.append(str(node["text"]))
            elif node.get("tag") == "at" and node.get("user_id"):
                parts.append(f"@{node.get('user_id')}")
            else:
                for value in node.values():
                    walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    title = data.get("title")
    if isinstance(title, str) and title:
        parts.append(title)
    walk(data.get("content"))
    return "".join(parts).strip()


def _replace_mentions(text: str, raw: Any) -> str:
    """Replace Feishu's ``@_user_N`` placeholders with the mentioned name."""
    for item in raw or []:
        key, name = _get(item, "key"), _get(item, "name")
        if key and name:
            text = text.replace(str(key), f"@{name}")
    return text


def _mentions(raw: Any) -> list[Sender]:
    out: list[Sender] = []
    for item in raw or []:
        out.append(
            Sender(
                id=str(_get(item, "id", "open_id") or _get(item, "key") or ""),
                name=_get(item, "name"),
            )
        )
    return out


def _markdown_card(text: str) -> dict:
    """An interactive card whose body is a ``markdown`` component.

    That component renders lists, code blocks, horizontal rules and inline
    styles; a ``div`` with a ``lark_md`` text element renders only inline
    markup. The component requires Feishu client >= 7.6.
    """
    return _card([{"tag": "markdown", "content": text}])


def _card(elements: list[dict], title: str | None = None) -> dict:
    card: dict[str, Any] = {"config": {"wide_screen_mode": True}, "elements": elements}
    if title:
        card["header"] = {"title": {"tag": "plain_text", "content": title}}
    return card


def _card2(elements: list[dict], title: str | None = None) -> dict:
    """A card in JSON 2.0 shape, required for the ``card.action.trigger`` callback."""
    card: dict[str, Any] = {
        "schema": "2.0",
        "config": {"wide_screen_mode": True},
        "body": {"elements": elements},
    }
    if title:
        card["header"] = {"title": {"tag": "plain_text", "content": title}}
    return card


def _interactive_card(card: Card) -> dict:
    if card.questions:
        elements = [_questions_form(card)]
    else:
        elements = [{"tag": "markdown", "content": card.body}]
        if card.buttons:
            elements.append(_button_row(card.buttons))
    return _card2(elements, card.title or "Confirm")


def _button_row(buttons: list[Button]) -> dict:
    return {
        "tag": "column_set",
        "flex_mode": "bisect",
        "columns": [
            {
                "tag": "column",
                "width": "weighted",
                "weight": 1,
                "elements": [_button(button, index)],
            }
            for index, button in enumerate(buttons)
        ],
    }


def _button(button: Button, index: int) -> dict:
    return {
        "tag": "button",
        "text": {"tag": "plain_text", "content": button.text},
        "type": _button_type(button.style, index),
        "behaviors": [{"type": "callback", "value": {"key": button.value}}],
    }


def _button_type(style: str | None, index: int) -> str:
    """Map a button's semantic style to a Feishu button type.

    Feishu accepts ``default``/``primary``/``danger``; a button without a style
    keeps the first one emphasized.
    """
    if style in ("primary", "danger", "default"):
        return style
    return "primary" if index == 0 else "default"


def _questions_form(card: Card) -> dict:
    """A form that collects one answer per question and submits them together.

    Single-choice questions become dropdowns (``select_static``) and multi-choice
    questions become checkboxes (``checker``); ``form_value`` then keys each
    answer by ``q{question}`` / ``q{question}_{option}``.
    """
    elements: list[dict] = []
    for q_index, question in enumerate(card.questions):
        label = question.header or question.body
        if label:
            elements.append({"tag": "markdown", "content": f"**{label}**"})
        if question.multiple:
            elements.extend(
                {
                    "tag": "checker",
                    "name": f"q{q_index}_{o_index}",
                    "checked": False,
                    "text": {"tag": "lark_md", "content": option},
                }
                for o_index, option in enumerate(question.options)
            )
        else:
            elements.append(
                {
                    "tag": "select_static",
                    "name": f"q{q_index}",
                    "placeholder": {"tag": "plain_text", "content": "请选择"},
                    "options": [
                        {"text": {"tag": "plain_text", "content": option}, "value": option}
                        for option in question.options
                    ],
                }
            )
    elements.append(_submit_button(card.submit_value))
    return {"tag": "form", "name": "question_form", "elements": elements}


def _submit_button(value: str) -> dict:
    return {
        "tag": "button",
        "type": "primary",
        "text": {"tag": "plain_text", "content": "提交"},
        "form_action_type": "submit",
        "name": "submit",
        "behaviors": [{"type": "callback", "value": {"key": value}}],
    }


def _json(value: Any) -> dict:
    if isinstance(value, dict):
        return value
    if isinstance(value, str) and value:
        try:
            parsed = json.loads(value)
            return parsed if isinstance(parsed, dict) else {}
        except json.JSONDecodeError:
            return {}
    return {}


def _get(obj: Any, *keys: str) -> Any:
    for key in keys:
        if obj is None:
            return None
        obj = obj.get(key) if isinstance(obj, dict) else getattr(obj, key, None)
    return obj


# -- real SDK (lark-oapi) --------------------------------------------------


def _ok(resp: Any, action: str) -> Any:
    """Return ``resp`` if the call succeeded, else raise.

    The SDK reports REST failures in the response body rather than raising, so
    callers must check explicitly to trigger their fallbacks.
    """
    if not resp.success():
        raise RuntimeError(f"feishu {action} failed: code={resp.code} msg={resp.msg}")
    return resp


# Backoff for re-establishing the long connection if its thread ever dies.
_STREAM_BACKOFF_S = 5.0
_STREAM_BACKOFF_MAX_S = 30.0


class LarkSDK:
    """``lark-oapi`` implementation: blocking WS in a thread + sync REST."""

    def __init__(self, app_id: str, app_secret: str) -> None:
        self._app_id = app_id
        self._app_secret = app_secret
        self._rest: Any = None
        self._ws: Any = None
        self._ws_loop: asyncio.AbstractEventLoop | None = None
        self._ready = threading.Event()
        self._stopped = threading.Event()
        self._error: BaseException | None = None

    def start(self, on_message: Any, on_card: Any, on_recall: Any) -> None:
        self._stopped.clear()
        threading.Thread(
            target=self._run, args=(on_message, on_card, on_recall), daemon=True
        ).start()
        # Return once the thread has built the client (or failed); do not block
        # the caller on the socket itself.
        self._ready.wait(timeout=10)
        if self._error is not None:
            raise self._error

    def _run(self, on_message: Any, on_card: Any, on_recall: Any) -> None:
        # Import inside the thread so lark's module-level event loop binds here.
        asyncio.set_event_loop(asyncio.new_event_loop())
        try:
            self._build(on_message, on_card, on_recall)
        except Exception as exc:  # noqa: BLE001 - surface build failure to start()
            self._error = exc
            self._ready.set()
            return
        self._ready.set()
        self._supervise(on_message, on_card, on_recall)

    def _supervise(self, on_message: Any, on_card: Any, on_recall: Any) -> None:
        """Keep the blocking stream alive; rebuild it if its thread ever ends.

        The SDK reconnects indefinitely on its own, but ``start()`` ends the
        thread if the socket dies for good, so restart it here.
        """
        backoff = _STREAM_BACKOFF_S
        while not self._stopped.is_set():
            log.info("feishu_stream_connecting")
            try:
                self._ws.start()  # blocks while connected
                log.warning("feishu_stream_ended")
            except Exception:  # noqa: BLE001 - rebuild and retry below
                log.warning("feishu_stream_failed", exc_info=True)
            if self._stopped.is_set():
                break
            log.warning("feishu_stream_restarting", backoff_s=backoff)
            self._stopped.wait(backoff)
            backoff = min(backoff * 2, _STREAM_BACKOFF_MAX_S)
            try:
                self._build(on_message, on_card, on_recall)
            except Exception:  # noqa: BLE001 - retry the rebuild next tick
                log.warning("feishu_stream_rebuild_failed", exc_info=True)

    def _build(self, on_message: Any, on_card: Any, on_recall: Any) -> None:
        import lark_oapi as lark
        from lark_oapi.ws import client as ws_module

        self._ws_loop = ws_module.loop
        self._rest = (
            lark.Client.builder().app_id(self._app_id).app_secret(self._app_secret).build()
        )
        builder = lark.EventDispatcherHandler.builder("", "")
        builder.register_p2_im_message_receive_v1(on_message)
        builder.register_p2_card_action_trigger(on_card)
        builder.register_p2_im_message_recalled_v1(on_recall)
        self._ws = lark.ws.Client(self._app_id, self._app_secret, event_handler=builder.build())

    def stop(self) -> None:
        self._stopped.set()
        ws, loop = self._ws, self._ws_loop
        conn = getattr(ws, "_conn", None) if ws is not None else None
        if conn is not None and loop is not None:
            loop.call_soon_threadsafe(lambda: asyncio.ensure_future(conn.close()))

    @property
    def connected(self) -> bool:
        # The SDK holds the open socket on ``_conn`` (cleared on disconnect).
        return self._ws is not None and getattr(self._ws, "_conn", None) is not None

    # -- REST (sync) -------------------------------------------------------
    def reply(self, message_id: str, msg_type: str, content: dict) -> str:
        from lark_oapi.api.im.v1 import ReplyMessageRequest, ReplyMessageRequestBody

        request = (
            ReplyMessageRequest.builder()
            .message_id(message_id)
            .request_body(
                ReplyMessageRequestBody.builder()
                .msg_type(msg_type)
                .content(json.dumps(content))
                .build()
            )
            .build()
        )
        resp = _ok(self._rest.im.v1.message.reply(request), "reply")
        return str(getattr(resp.data, "message_id", ""))

    def send(self, chat_id: str, msg_type: str, content: dict) -> str:
        from lark_oapi.api.im.v1 import CreateMessageRequest, CreateMessageRequestBody

        request = (
            CreateMessageRequest.builder()
            .receive_id_type("chat_id")
            .request_body(
                CreateMessageRequestBody.builder()
                .receive_id(chat_id)
                .msg_type(msg_type)
                .content(json.dumps(content))
                .build()
            )
            .build()
        )
        resp = _ok(self._rest.im.v1.message.create(request), "send")
        return str(getattr(resp.data, "message_id", ""))

    def patch(self, message_id: str, content: dict) -> None:
        from lark_oapi.api.im.v1 import PatchMessageRequest, PatchMessageRequestBody

        request = (
            PatchMessageRequest.builder()
            .message_id(message_id)
            .request_body(PatchMessageRequestBody.builder().content(json.dumps(content)).build())
            .build()
        )
        _ok(self._rest.im.v1.message.patch(request), "patch")

    def upload_image(self, data: bytes, filename: str) -> str:
        import io

        from lark_oapi.api.im.v1 import CreateImageRequest, CreateImageRequestBody

        request = (
            CreateImageRequest.builder()
            .request_body(
                CreateImageRequestBody.builder()
                .image_type("message")
                .image(io.BytesIO(data))
                .build()
            )
            .build()
        )
        resp = _ok(self._rest.im.v1.image.create(request), "upload_image")
        return str(getattr(resp.data, "image_key", ""))

    def upload_file(self, data: bytes, filename: str, kind: str) -> str:
        import io

        from lark_oapi.api.im.v1 import CreateFileRequest, CreateFileRequestBody

        file_type = {"audio": "opus", "video": "mp4"}.get(kind, "stream")
        request = (
            CreateFileRequest.builder()
            .request_body(
                CreateFileRequestBody.builder()
                .file_type(file_type)
                .file_name(filename)
                .file(io.BytesIO(data))
                .build()
            )
            .build()
        )
        resp = _ok(self._rest.im.v1.file.create(request), "upload_file")
        return str(getattr(resp.data, "file_key", ""))

    def download(self, message_id: str, file_key: str, kind: str) -> bytes:
        from lark_oapi.api.im.v1 import GetMessageResourceRequest

        request = (
            GetMessageResourceRequest.builder()
            .message_id(message_id)
            .file_key(file_key)
            .type(kind)
            .build()
        )
        resp = _ok(self._rest.im.v1.message_resource.get(request), "download")
        return resp.file.read()

    def bot_info(self) -> tuple[str | None, str | None]:
        token = self._tenant_token()
        if not token:
            return None, None
        import httpx

        resp = httpx.get(
            "https://open.feishu.cn/open-apis/bot/v3/info",
            headers={"Authorization": f"Bearer {token}"},
            timeout=10,
        )
        data = resp.json().get("bot") or {}
        return data.get("app_name"), None

    def _tenant_token(self) -> str | None:
        import httpx

        resp = httpx.post(
            "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
            json={"app_id": self._app_id, "app_secret": self._app_secret},
            timeout=10,
        )
        return (resp.json() or {}).get("tenant_access_token")


__all__ = ["FeishuConnector", "FeishuSDK", "LarkSDK", "feishu_capabilities"]

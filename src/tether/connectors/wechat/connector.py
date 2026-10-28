"""Personal WeChat (iLink Bot) connector.

Direct-chat only: the platform returns ``ChatType: "direct"`` and has no group
routing. One connector instance owns one logged-in bot (token, long-poll cursor,
per-peer context tokens); multiple bots are separate instances keyed by
``Conversation.account``.
"""

from __future__ import annotations

import asyncio
import base64
import mimetypes
import os
import time
import uuid
from collections.abc import Awaitable, Callable
from typing import TYPE_CHECKING, Any

from tether.capabilities import Capabilities, MarkdownLevel
from tether.config import WeChatBotSpec
from tether.connector import Unsupported
from tether.connectors.base import BaseConnector
from tether.connectors.wechat.client import (
    DEFAULT_CDN_BASE,
    LONG_POLL_TIMEOUT_S,
    MAX_CDN_BYTES,
    WeChatAPIError,
    WeChatAuthError,
    WeChatClient,
    WeChatClientProtocol,
    build_download_url,
    build_upload_url,
    decrypt_ecb,
    encrypt_ecb,
    md5_hex,
    padded_size,
    parse_aes_key,
)
from tether.connectors.wechat.login import (
    WeChatLoginError,
    WeChatLoginService,
    qr_png,
)
from tether.connectors.wechat.storage import WeChatCredential, WeChatState
from tether.metrics import metrics
from tether.models import (
    Attachment,
    BotIdentity,
    Conversation,
    InboundMessage,
    MediaBytes,
    RichMedia,
    Sender,
    normalize_media_kind,
)
from tether.util.logging import get_logger

if TYPE_CHECKING:
    from tether.store.sqlite import RouteStore

log = get_logger("tether.wechat")

wechat_capabilities = Capabilities(
    markdown=MarkdownLevel.NONE,
    code_block=False,
    tables=False,
    headings=False,
    images_inline=False,
    edit_message=False,
    native_stream=False,
    buttons=False,
    reactions=False,
    typing=True,
    progress_placeholder=False,
    proactive=False,
    groups=False,
    mention=False,
    callback_actor_identity=False,
    member_roles=False,
    direct_delivery="always",
    group_delivery="unknown",
    max_text_chars=2000,
    media_in=frozenset({"image", "audio", "video", "file", "voice"}),
    media_out=frozenset({"image", "video", "file"}),
)

_TEXT = 1
_IMAGE = 2
_VOICE = 3
_FILE = 4
_VIDEO = 5

# Protocol enum values used on the wire.
_MESSAGE_TYPE_BOT = 2
_MESSAGE_STATE_FINISHED = 2
_ENCRYPT_TYPE_PACKED = 1

_UPLOAD_IMAGE = 1
_UPLOAD_VIDEO = 2
_UPLOAD_FILE = 3
_UPLOAD_TYPE = {
    "image": _UPLOAD_IMAGE,
    "video": _UPLOAD_VIDEO,
    "file": _UPLOAD_FILE,
}
_MEDIA_LABEL = {_IMAGE: "[图片]", _VIDEO: "[视频]", _FILE: "[文件]", _VOICE: "[语音]"}
_MAX_MEDIA_BYTES = MAX_CDN_BYTES
_TYPING_TICKET_TTL_S = 600.0
_TYPING_STATUS_TYPING = 1

_POLL_BACKOFF_START_S = 1.0
_POLL_BACKOFF_MAX_S = 30.0

_STATE_UNBOUND = "unbound"
_STATE_LOGIN_REQUIRED = "login_required"
_STATE_UP = "up"
_STATE_DISABLED = "disabled"

ApiFactory = Callable[[WeChatCredential], WeChatClientProtocol]
QRCallback = Callable[[bytes | None, str], Awaitable[None]]


class WeChatConnector(BaseConnector):
    name = "wechat"

    def __init__(
        self,
        *,
        spec: WeChatBotSpec,
        channel_enabled: bool,
        store: RouteStore | None = None,
        api_factory: ApiFactory | None = None,
        cdn_base_url: str = DEFAULT_CDN_BASE,
        qr_timeout_s: int = 480,
    ) -> None:
        super().__init__(wechat_capabilities)
        self.account = spec.id
        self.spec = spec
        self.enabled = spec.enabled
        self.channel_enabled = channel_enabled
        self.qr_timeout_s = qr_timeout_s
        self.store = store
        self._api_factory = api_factory or self._default_api
        self._cdn_base_url = cdn_base_url
        self._api: WeChatClientProtocol | None = None
        self._credential: WeChatCredential | None = None
        self._state = _STATE_UNBOUND
        self._runtime = WeChatState()
        self._poll_task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()
        self._poll_timeout_s = LONG_POLL_TIMEOUT_S
        self._typing_tickets: dict[str, tuple[str, float]] = {}
        self._login_lock = asyncio.Lock()
        self._identity = spec.identity

    # -- lifecycle ---------------------------------------------------------
    async def _connect(self) -> None:
        if not self.enabled:
            # A disabled bot is still built so it can be pre-provisioned with
            # `/login`; it simply never starts its long-poll.
            self._state = _STATE_DISABLED
            self._publish_login_state()
            log.info("wechat_bot_disabled", bot=self.spec.slot)
            return

        credential = await self._load_credential()
        if credential is None:
            self._state = await self._initial_state()
            self._publish_login_state()
            log.info("wechat_bot_not_logged_in", bot=self.spec.slot, state=self._state)
            return

        await self._apply_credential(credential, start_polling=True)

    async def _load_credential(self) -> WeChatCredential | None:
        if self.store is None:
            return None

        row = await self.store.wechat_account(self.spec.slot)
        if not row or not row.get("token") or not row.get("base_url"):
            return None

        return WeChatCredential(
            token=str(row["token"]),
            base_url=str(row["base_url"]),
            bot_id=str(row["ilink_bot_id"]) if row.get("ilink_bot_id") else None,
            user_id=str(row["user_id"]) if row.get("user_id") else None,
            saved_at=float(str(row.get("token_saved_at") or 0.0)),
        )

    async def _disconnect(self) -> None:
        self._stop.set()
        task = self._poll_task
        self._poll_task = None

        if task is not None:
            task.cancel()
            try:
                await task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

        if self._api is not None:
            try:
                await self._api.notify_stop()
            except Exception:  # noqa: BLE001 - best effort
                pass
            try:
                await self._api.close()
            except Exception:  # noqa: BLE001
                pass

        self._api = None
        if self._state == _STATE_UP:
            self._state = _STATE_DISABLED
            self._publish_login_state()

    @property
    def connected(self) -> bool | None:
        # A disabled slot is intentionally not running (untracked by health);
        # ``unbound``/``login_required`` are enabled but not usable, so they are
        # reported as down and surface in ``/healthz`` and the down alert.
        if self._state == _STATE_DISABLED:
            return None

        return self._state == _STATE_UP

    @property
    def state(self) -> str:
        return self._state

    def _publish_login_state(self) -> None:
        metrics.set(
            f"wechat_login_required_{self.spec.slot}",
            1.0 if self._state == _STATE_LOGIN_REQUIRED else 0.0,
        )

    def apply_bot_policy(self, spec: WeChatBotSpec) -> None:
        """Hot-apply per-bot identity (and login_via is read from config).

        Bot enablement still requires a restart.
        """
        self.spec = spec
        self._identity = spec.identity

    async def _initial_state(self) -> str:
        if self.store is not None:
            try:
                if await self.store.wechat_binding(self.spec.slot) is not None:
                    return _STATE_LOGIN_REQUIRED
            except Exception:  # noqa: BLE001 - a store error must not stop the channel
                log.warning(
                    "wechat_binding_lookup_failed", bot=self.spec.slot, exc_info=True
                )

        return _STATE_UNBOUND

    async def _apply_credential(
        self, credential: WeChatCredential, *, start_polling: bool
    ) -> None:
        old_task = self._poll_task
        self._poll_task = None
        if old_task is not None:
            old_task.cancel()
            try:
                await old_task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass

        if self._api is not None:
            try:
                await self._api.close()
            except Exception:  # noqa: BLE001
                pass

        self._credential = credential

        if self.store is not None:
            try:
                cursor, tokens = await self.store.wechat_state(self.spec.slot)
                self._runtime = WeChatState(cursor=cursor, context_tokens=tokens)
            except Exception:  # noqa: BLE001 - start with empty state rather than fail
                log.warning(
                    "wechat_state_load_failed", bot=self.spec.slot, exc_info=True
                )
                self._runtime = WeChatState()
        else:
            self._runtime = WeChatState()

        self._stop = asyncio.Event()
        self._typing_tickets.clear()

        if not start_polling:
            self._state = _STATE_DISABLED
            self._api = None
            self._publish_login_state()
            return

        self._api = self._api_factory(credential)
        self._state = _STATE_UP
        self._publish_login_state()

        try:
            await self._api.notify_start()
        except Exception:  # noqa: BLE001 - lifecycle ping is best-effort
            log.debug("wechat_notify_start_failed", account=self.spec.slot, exc_info=True)

        self._poll_task = asyncio.create_task(
            self._poll_loop(), name=f"wechat-poll-{self.spec.slot}"
        )

        log.info("wechat_bot_started", bot=self.spec.slot, instance=self.instance_id)

    async def _poll_loop(self) -> None:
        backoff = _POLL_BACKOFF_START_S

        while not self._stop.is_set():
            api = self._api
            if api is None:
                return

            try:
                response = await api.get_updates(
                    self._runtime.cursor, timeout_s=self._poll_timeout_s
                )
            except WeChatAuthError:
                self._mark_login_required(reason="poll")
                return
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001 - retry per bot
                log.warning(
                    "wechat_poll_failed",
                    bot=self.spec.slot,
                    error=str(exc),
                    backoff_s=backoff,
                )
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, _POLL_BACKOFF_MAX_S)
                continue

            backoff = _POLL_BACKOFF_START_S
            await self._apply_poll_response(response)

    async def _apply_poll_response(self, response: dict[str, Any]) -> None:
        cursor = response.get("get_updates_buf")
        if isinstance(cursor, str) and cursor:
            self._runtime.cursor = cursor
            await self._save_cursor()

        timeout_ms = response.get("longpolling_timeout_ms")
        if isinstance(timeout_ms, (int, float)) and timeout_ms > 0:
            self._poll_timeout_s = float(timeout_ms) / 1000.0

        for raw in response.get("msgs") or []:
            if not isinstance(raw, dict):
                continue

            try:
                await self._handle_message(raw)
            except Exception:  # noqa: BLE001 - one bad message must not stop the poll
                log.exception("wechat_inbound_failed", bot=self.spec.slot)

    async def _save_cursor(self) -> None:
        if self.store is None:
            return

        try:
            await self.store.save_wechat_cursor(
                self.spec.slot, self._runtime.cursor
            )
        except Exception:  # noqa: BLE001 - cursor persistence is best-effort
            log.warning(
                "wechat_state_save_failed",
                bot=self.spec.slot,
                exc_info=True,
            )

    def _mark_login_required(self, *, reason: str) -> None:
        self._state = _STATE_LOGIN_REQUIRED
        self._publish_login_state()
        log.error("wechat_login_required", bot=self.spec.slot, reason=reason)

    # -- inbound -----------------------------------------------------------
    async def _handle_message(self, raw: dict[str, Any]) -> None:
        if raw.get("message_type") == _MESSAGE_TYPE_BOT:
            return

        if raw.get("group_id"):  # the protocol is direct-only; never route a group
            log.warning("wechat_group_message_ignored", account=self.spec.slot)
            return

        from_user = str(raw.get("from_user_id") or "").strip()
        if not from_user:
            return

        context_token = str(raw.get("context_token") or "").strip()
        if context_token:
            self._runtime.context_tokens[from_user] = context_token
            if self.store is not None:
                try:
                    await self.store.save_wechat_context_token(
                        self.spec.slot, from_user, context_token
                    )
                except Exception:  # noqa: BLE001 - token persistence is best-effort
                    log.warning(
                        "wechat_state_save_failed",
                        account=self.spec.slot,
                        exc_info=True,
                    )

        text, attachments = _parse_items(raw)
        conversation = Conversation(
            channel="wechat",
            kind="direct",
            id=from_user,
            account=self.account,
        )
        message_id = _message_id(raw)
        timestamp = float(raw.get("create_time_ms") or 0) / 1000.0

        await self.emit(
            InboundMessage(
                channel="wechat",
                message_id=message_id,
                conversation=conversation,
                sender=Sender(id=from_user),
                text=text,
                attachments=attachments,
                timestamp=timestamp,
                raw=raw,
            )
        )

    # -- outbound ----------------------------------------------------------
    async def _send_text(
        self, conv: Conversation, text: str, reply_to: str | None, *, final: bool = True
    ) -> str:
        return await self._send_item(
            conv, {"type": _TEXT, "text_item": {"text": text}}
        )

    async def _send_item(self, conv: Conversation, item: dict[str, Any]) -> str:
        api = self._api
        if api is None:
            raise Unsupported("wechat is not connected")

        context_token = self._runtime.context_tokens.get(conv.id)
        if not context_token:
            log.warning("wechat_context_token_missing", conversation=conv.key)

        client_id = f"tether-{uuid.uuid4().hex}"
        msg: dict[str, Any] = {
            "from_user_id": "",
            "to_user_id": conv.id,
            "client_id": client_id,
            "message_type": _MESSAGE_TYPE_BOT,
            "message_state": _MESSAGE_STATE_FINISHED,
            "item_list": [item],
        }

        if context_token:
            msg["context_token"] = context_token

        try:
            response = await api.send_message(msg)
        except WeChatAuthError:
            self._mark_login_required(reason="send")
            raise
        return str(response.get("message_id") or client_id)

    async def _send_media(self, conv: Conversation, media: RichMedia) -> str:
        kind = normalize_media_kind(media.kind)
        if kind not in _UPLOAD_TYPE:
            raise Unsupported(f"wechat cannot send {media.kind} media")

        if media.data is None:
            raise Unsupported("wechat media requires bytes")

        api = self._api
        if api is None:
            raise Unsupported("wechat is not connected")

        data = media.data
        if len(data) > _MAX_MEDIA_BYTES:
            raise Unsupported("media exceeds the WeChat upload limit")

        media_ref, filesize = await self._upload_media(api, conv, data, kind)
        name = os.path.basename(media.name) if media.name else _default_name(media.mime)
        item = _build_media_item(kind, media_ref, filesize, name, len(data))

        return await self._send_item(conv, item)

    async def _upload_media(
        self,
        api: WeChatClientProtocol,
        conv: Conversation,
        data: bytes,
        kind: str,
    ) -> tuple[dict[str, Any], int]:
        filekey = uuid.uuid4().hex
        aeskey = os.urandom(16)
        filesize = padded_size(len(data))

        try:
            upload = await api.get_upload_url(
                {
                    "filekey": filekey,
                    "media_type": _UPLOAD_TYPE[kind],
                    "to_user_id": conv.id,
                    "rawsize": len(data),
                    "rawfilemd5": md5_hex(data),
                    "filesize": filesize,
                    "no_need_thumb": True,
                    "aeskey": aeskey.hex(),
                }
            )
        except WeChatAuthError:
            self._mark_login_required(reason="upload")
            raise

        full_url = str(upload.get("upload_full_url") or "").strip()
        upload_param = str(upload.get("upload_param") or "").strip()
        if not full_url and not upload_param:
            raise WeChatAPIError("getUploadUrl returned no upload URL")

        url = full_url or build_upload_url(upload_param, filekey, self._cdn_base_url)
        param = await api.upload_cdn(url, encrypt_ecb(data, aeskey))
        media_ref = {
            "encrypt_query_param": param,
            "aes_key": base64.b64encode(aeskey).decode(),
            "encrypt_type": _ENCRYPT_TYPE_PACKED,
        }

        return media_ref, filesize

    async def _typing(self, conv: Conversation) -> None:
        api = self._api
        if api is None:
            return

        ticket = await self._typing_ticket(conv.id)
        if not ticket:
            return

        try:
            await api.send_typing(conv.id, ticket, status=_TYPING_STATUS_TYPING)
        except WeChatAuthError:
            self._mark_login_required(reason="typing")
        except Exception:  # noqa: BLE001 - typing is best-effort
            log.debug("wechat_typing_failed", conversation=conv.key, exc_info=True)

    async def _typing_ticket(self, user_id: str) -> str | None:
        cached = self._typing_tickets.get(user_id)
        if cached and time.monotonic() - cached[1] < _TYPING_TICKET_TTL_S:
            return cached[0]

        api = self._api
        if api is None:
            return None

        try:
            response = await api.get_config(
                user_id, self._runtime.context_tokens.get(user_id)
            )
        except WeChatAuthError:
            self._mark_login_required(reason="typing")
            return None
        except Exception:  # noqa: BLE001 - typing is best-effort
            return None

        ticket = str(response.get("typing_ticket") or "")
        if ticket:
            self._typing_tickets[user_id] = (ticket, time.monotonic())

        return ticket or None

    # -- media inbound -----------------------------------------------------
    async def download(self, att: Attachment) -> MediaBytes:
        api = self._api
        if api is None:
            raise Unsupported("wechat is not connected")

        item = att.handle
        if not isinstance(item, dict):
            raise Unsupported("wechat attachment has no media reference")

        ref = _media_ref(item)
        if ref is None:
            raise Unsupported("wechat attachment has no media reference")

        media, aes_key = ref
        url = str(media.get("full_url") or "").strip()
        param = str(media.get("encrypt_query_param") or "").strip()
        if not url:
            if not param:
                raise Unsupported("wechat attachment has no download URL")
            url = build_download_url(param, self._cdn_base_url)

        if item.get("type") in (_VOICE, _FILE, _VIDEO) and not aes_key:
            raise Unsupported("wechat media has no aes key")

        encrypted = await api.download_cdn(url)
        data = decrypt_ecb(encrypted, parse_aes_key(aes_key)) if aes_key else encrypted
        if len(data) > _MAX_MEDIA_BYTES:
            raise Unsupported("wechat media exceeds the download limit")

        return MediaBytes(data=data, mime=att.mime, name=att.name)

    # -- facts -------------------------------------------------------------
    async def identity(self, conv: Conversation) -> BotIdentity:
        name = self._identity.display_name
        if not name:
            name = f"WeChat {self.account}" if self.account else "WeChat"

        return BotIdentity(name=name, description=self._identity.description)

    # -- login -------------------------------------------------------------
    async def login(
        self,
        *,
        on_qr: QRCallback | None = None,
        request_verify_code: Callable[[], Awaitable[str]] | None = None,
    ) -> WeChatCredential:
        if self._login_lock.locked():
            raise WeChatLoginError(
                f"a login is already in progress for bot {self.spec.slot!r}"
            )

        pending_key = f"wechat_login_pending_{self.spec.slot}"
        metrics.set(pending_key, 1.0)

        try:
            async with self._login_lock:
                return await self._login(
                    on_qr=on_qr,
                    request_verify_code=request_verify_code,
                )
        finally:
            metrics.set(pending_key, 0.0)

    async def _login(
        self,
        *,
        on_qr: QRCallback | None,
        request_verify_code: Callable[[], Awaitable[str]] | None,
    ) -> WeChatCredential:
        service = WeChatLoginService(
            store=self.store,
            channel_enabled=self.channel_enabled,
            qr_timeout_s=self.qr_timeout_s,
        )
        session = await service.start(
            self.spec, local_tokens=self._local_tokens()
        )

        async def show(content: str) -> None:
            if on_qr is not None:
                await on_qr(qr_png(content), content)

        try:
            await show(session.content)
        except BaseException:
            await session.client.close()
            raise
        credential = await service.wait(
            session,
            on_refresh=show,
            request_verify_code=request_verify_code,
        )
        await self._apply_credential(credential, start_polling=self.enabled)
        return credential

    def _local_tokens(self) -> list[str]:
        if self._credential and self._credential.token:
            return [self._credential.token]
        return []

    def _default_api(self, credential: WeChatCredential) -> WeChatClientProtocol:
        return WeChatClient(
            base_url=credential.base_url,
            token=credential.token,
            cdn_base_url=self._cdn_base_url,
        )


# ---------------------------------------------------------------------------
# Inbound item parsing
# ---------------------------------------------------------------------------


def _parse_items(raw: dict[str, Any]) -> tuple[str, list[Attachment]]:
    texts: list[str] = []
    attachments: list[Attachment] = []
    quoted: str | None = None

    for item in raw.get("item_list") or []:
        if not isinstance(item, dict):
            continue

        ref = item.get("ref_msg")
        if isinstance(ref, dict) and quoted is None:
            quoted = _quote_text(ref)
            nested = ref.get("message_item")
            if isinstance(nested, dict):
                _add_media_attachment(nested, attachments)

        kind = item.get("type")
        if kind == _TEXT:
            value = (item.get("text_item") or {}).get("text")
            if value:
                texts.append(str(value))
        elif kind == _VOICE:
            value = (item.get("voice_item") or {}).get("text")
            if value:
                texts.append(str(value))
            else:
                _add_media_attachment(item, attachments)
        elif kind in (_IMAGE, _FILE, _VIDEO):
            _add_media_attachment(item, attachments)

    text = "\n".join(texts).strip()
    if quoted:
        text = f"[quoting] {quoted}\n{text}".strip()

    return text, attachments


def _add_media_attachment(
    item: dict[str, Any], attachments: list[Attachment]
) -> None:
    kind = item.get("type")

    media, _ = _media_ref(item) or ({}, None)
    if not media:
        return

    sub = _media_sub(item)
    if kind == _IMAGE:
        size = _int_or_none(sub.get("mid_size") or sub.get("hd_size"))
        attachments.append(
            Attachment(kind="image", mime="image/jpeg", size=size, handle=item)
        )
    elif kind == _VIDEO:
        attachments.append(
            Attachment(
                kind="video",
                mime="video/mp4",
                size=_int_or_none(sub.get("video_size")),
                duration_ms=_int_or_none(sub.get("play_length")),
                handle=item,
            )
        )
    elif kind == _FILE:
        name = str(sub.get("file_name") or "") or None
        mime = mimetypes.guess_type(name)[0] if name else None
        attachments.append(
            Attachment(
                kind="file",
                mime=mime,
                name=name,
                size=_int_or_none(sub.get("len")),
                handle=item,
            )
        )
    elif kind == _VOICE:
        attachments.append(
            Attachment(
                kind="audio",
                mime="audio/silk",
                duration_ms=_int_or_none(sub.get("playtime")),
                handle=item,
            )
        )


def _media_ref(item: dict[str, Any]) -> tuple[dict[str, Any], str | None] | None:
    sub = _media_sub(item)

    media = sub.get("media")
    if not isinstance(media, dict):
        return None

    key = media.get("aes_key")
    if item.get("type") == _IMAGE:
        hex_key = sub.get("aeskey")

        if isinstance(hex_key, str) and len(hex_key) == 32:
            try:
                key = base64.b64encode(bytes.fromhex(hex_key)).decode()
            except ValueError:
                pass

    return media, str(key) if key else None


def _media_sub(item: dict[str, Any]) -> dict[str, Any]:
    item_type = item.get("type")
    key = (
        {
            _IMAGE: "image_item",
            _VOICE: "voice_item",
            _FILE: "file_item",
            _VIDEO: "video_item",
        }.get(item_type)
        if isinstance(item_type, int)
        else None
    )
    value = item.get(key) if key else None

    return value if isinstance(value, dict) else {}


def _quote_text(ref: dict[str, Any]) -> str:
    parts: list[str] = []

    title = str(ref.get("title") or "").strip()
    if title:
        parts.append(title)

    nested = ref.get("message_item")
    if isinstance(nested, dict):
        kind = nested.get("type")
        if kind == _TEXT:
            text = (nested.get("text_item") or {}).get("text")
            if text:
                parts.append(str(text))
        elif kind == _VOICE:
            text = (nested.get("voice_item") or {}).get("text")
            if text:
                parts.append(str(text))
        elif isinstance(kind, int) and kind in _MEDIA_LABEL:
            parts.append(_MEDIA_LABEL[kind])

    return " | ".join(parts)


def _message_id(raw: dict[str, Any]) -> str:
    for key in ("message_id", "client_id", "seq"):
        value = str(raw.get(key) or "").strip()
        if value:
            return value

    for item in raw.get("item_list") or []:
        if isinstance(item, dict):
            item_id = str(item.get("msg_id") or "").strip()
            if item_id:
                return item_id

    return uuid.uuid4().hex


def _int_or_none(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def _build_media_item(
    kind: str,
    media_ref: dict[str, Any],
    filesize: int,
    name: str,
    raw_size: int,
) -> dict[str, Any]:
    if kind == "image":
        return {
            "type": _IMAGE,
            "image_item": {"media": media_ref, "mid_size": filesize},
        }
    if kind == "video":
        return {
            "type": _VIDEO,
            "video_item": {"media": media_ref, "video_size": filesize},
        }

    return {
        "type": _FILE,
        "file_item": {
            "media": media_ref,
            "file_name": name,
            "len": str(raw_size),
        },
    }


def _default_name(mime: str | None) -> str:
    extension = mimetypes.guess_extension(mime or "") or ".bin"
    return f"wechat-{uuid.uuid4().hex[:8]}{extension}"

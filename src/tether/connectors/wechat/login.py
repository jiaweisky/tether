"""QR login and binding admission for WeChat bots.

The flow is always per bot: request a QR, poll it, then atomically bind the
returned platform account and store its token. A rejected scan never persists
the token; an already-bound bot cannot be silently switched to another account.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING

from tether.config import WeChatBotSpec
from tether.connectors.wechat.client import DEFAULT_API_BASE, WeChatClient, WeChatClientProtocol
from tether.connectors.wechat.storage import WeChatCredential, str_or_none
from tether.metrics import metrics
from tether.store.sqlite import WeChatBindingConflict, WeChatRebindRequired
from tether.util.logging import get_logger

if TYPE_CHECKING:
    from tether.store.sqlite import RouteStore

log = get_logger("tether.wechat.login")

_QR_REFRESH_LIMIT = 3
_POLL_INTERVAL_S = 1.0


class WeChatLoginError(Exception):
    """The login flow could not be completed."""


class WeChatLoginRejected(WeChatLoginError):
    """The scanned account failed admission (no token was written)."""

    def __init__(self, bot_id: str | None, reason: str) -> None:
        super().__init__(reason)
        self.bot_id = bot_id
        self.reason = reason


class WeChatVerifyCodeRequired(WeChatLoginError):
    """The server asked for the verification code shown by the phone."""


@dataclass
class LoginSession:
    client: WeChatClientProtocol
    bot: WeChatBotSpec
    qrcode: str
    content: str
    base_url: str = DEFAULT_API_BASE


class WeChatLoginService:
    def __init__(
        self,
        *,
        store: RouteStore | None,
        channel_enabled: bool,
        qr_timeout_s: int = 480,
    ) -> None:
        self.store = store
        self.channel_enabled = channel_enabled
        self.qr_timeout_s = qr_timeout_s

    async def start(
        self,
        bot: WeChatBotSpec,
        *,
        local_tokens: list[str] | None = None,
    ) -> LoginSession:
        self._ensure_channel_enabled()
        client = WeChatClient(base_url=DEFAULT_API_BASE)

        try:
            payload = await client.get_qr(local_tokens=local_tokens)
        except BaseException:
            await client.close()
            raise

        return LoginSession(
            client=client,
            bot=bot,
            qrcode=str(payload["qrcode"]),
            content=str(payload["qrcode_img_content"]),
        )

    async def wait(
        self,
        session: LoginSession,
        *,
        timeout_s: int | None = None,
        on_refresh: Callable[[str], Awaitable[None]] | None = None,
        request_verify_code: Callable[[], Awaitable[str]] | None = None,
    ) -> WeChatCredential:
        timeout = timeout_s if timeout_s is not None else self.qr_timeout_s
        deadline = time.monotonic() + timeout
        pending_verify: str | None = None
        refreshes = 0

        try:
            while time.monotonic() < deadline:
                status = await session.client.poll_qr(
                    session.qrcode,
                    verify_code=pending_verify,
                    base_url=session.base_url,
                )

                state = str(status.get("status") or "wait")
                if state in ("wait", "scaned"):
                    if pending_verify:
                        pending_verify = None
                elif state == "need_verifycode":
                    if request_verify_code is None:
                        raise WeChatVerifyCodeRequired(
                            "this login needs a verification code, which the "
                            "in-chat flow cannot collect"
                        )
                    pending_verify = (await request_verify_code()).strip()
                    continue
                elif state == "scaned_but_redirect":
                    host = str(status.get("redirect_host") or "").strip()
                    if host:
                        session.base_url = f"https://{host}"
                elif state in ("expired", "verify_code_blocked"):
                    refreshes += 1
                    if refreshes > _QR_REFRESH_LIMIT:
                        raise WeChatLoginError("the QR code expired too many times")
                    pending_verify = None
                    await self._refresh_qr(session, on_refresh)
                elif state == "binded_redirect":
                    raise WeChatLoginRejected(
                        None, "this WeChat account is already bound to another instance"
                    )
                elif state == "confirmed":
                    return await self._confirmed(session.bot, status)
                await asyncio.sleep(_POLL_INTERVAL_S)
        finally:
            await session.client.close()

        raise WeChatLoginError("timed out waiting for the QR code to be scanned")

    async def _confirmed(
        self,
        bot: WeChatBotSpec,
        status: dict,
    ) -> WeChatCredential:
        bot_id = str(status.get("ilink_bot_id") or "").strip()
        token = str(status.get("bot_token") or "").strip()
        if not bot_id or not token:
            raise WeChatLoginRejected(bot_id or None, "login confirmation was incomplete")

        credential = WeChatCredential(
            token=token,
            base_url=str(status.get("baseurl") or DEFAULT_API_BASE).rstrip("/"),
            bot_id=bot_id,
            user_id=str_or_none(status.get("ilink_user_id")),
            saved_at=time.time(),
        )

        if self.store is None:
            raise WeChatLoginError("no route store is configured")

        try:
            await self.store.save_wechat_login(
                bot.slot,
                bot_id,
                token,
                credential.base_url,
                credential.user_id,
            )
        except WeChatBindingConflict as exc:
            metrics.inc("wechat_login_rejected")
            raise WeChatLoginRejected(
                bot_id,
                f"this WeChat account is already bound to bot {exc.other_slot!r}",
            ) from exc
        except WeChatRebindRequired as exc:
            metrics.inc("wechat_login_rejected")
            raise WeChatLoginRejected(
                bot_id,
                f"bot {bot.slot!r} is already bound to {exc.current_bot_id}; "
                "clear the binding before logging in a different account",
            ) from exc

        log.info(
            "wechat_login_bound",
            bot=bot.slot,
            bot_id=bot_id,
            base_url=credential.base_url,
        )

        return credential

    async def _refresh_qr(
        self,
        session: LoginSession,
        on_refresh: Callable[[str], Awaitable[None]] | None,
    ) -> None:
        payload = await session.client.get_qr()
        session.qrcode = str(payload["qrcode"])
        session.content = str(payload["qrcode_img_content"])
        session.base_url = DEFAULT_API_BASE

        if on_refresh is not None:
            await on_refresh(session.content)

    def _ensure_channel_enabled(self) -> None:
        if not self.channel_enabled:
            raise WeChatLoginError("channels.wechat.enabled is false")


def qr_png(content: str) -> bytes | None:
    """Render the QR content to PNG; ``None`` if the qrcode package is absent."""
    try:
        import io

        import qrcode
    except ImportError:
        return None

    image = qrcode.make(content)
    buffer = io.BytesIO()
    image.save(buffer, format="PNG")

    return buffer.getvalue()

"""Thin HTTP client for the Weixin iLink Bot protocol.

The server exposes QR login, a long-poll inbox, text/media sending and a
small typing/config API over HTTPS. This module owns only transport, headers,
AES-128-ECB media and those endpoints; message normalisation lives in the
connector.
"""

from __future__ import annotations

import asyncio
import base64
import binascii
import hashlib
import json
import random
from typing import Any, Protocol
from urllib.parse import quote

import httpx
from cryptography.hazmat.primitives import padding
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

DEFAULT_API_BASE = "https://ilinkai.weixin.qq.com"
DEFAULT_CDN_BASE = "https://novac2c.cdn.weixin.qq.com/c2c"
APP_ID = "bot"
CHANNEL_VERSION = "2.4.8"
CLIENT_VERSION = 0x00010000  # 0x00MMNNPP
BOT_AGENT = "Tether/0.1.0"
DEFAULT_API_TIMEOUT_S = 15.0
LONG_POLL_TIMEOUT_S = 35.0
CDN_TIMEOUT_S = 30.0
MAX_CDN_BYTES = 100 * 1024 * 1024
_CDN_UPLOAD_RETRIES = 3
_CDN_RETRY_BASE_S = 0.5

# The server returns this application code when the bot token is stale or
# expired. A new QR login is the only recovery; retrying the same token will
# not help.
STALE_TOKEN_ERRCODE = -14


class WeChatAPIError(Exception):
    def __init__(
        self,
        message: str,
        *,
        ret: int | None = None,
        errcode: int | None = None,
        errmsg: str | None = None,
    ) -> None:
        super().__init__(message)
        self.ret = ret
        self.errcode = errcode
        self.errmsg = errmsg


class WeChatAuthError(WeChatAPIError):
    """The bot token is stale/expired (``STALE_TOKEN_ERRCODE``); re-login via QR."""


class WeChatClientProtocol(Protocol):
    async def get_qr(self, *, local_tokens: list[str] | None = None) -> dict[str, Any]: ...
    async def poll_qr(
        self,
        qrcode: str,
        *,
        verify_code: str | None = None,
        base_url: str | None = None,
        timeout_s: float = LONG_POLL_TIMEOUT_S,
    ) -> dict[str, Any]: ...
    async def get_updates(
        self, cursor: str = "", *, timeout_s: float = LONG_POLL_TIMEOUT_S
    ) -> dict[str, Any]: ...
    async def send_message(self, msg: dict[str, Any]) -> dict[str, Any]: ...
    async def get_upload_url(self, payload: dict[str, Any]) -> dict[str, Any]: ...
    async def upload_cdn(self, url: str, ciphertext: bytes) -> str: ...
    async def download_cdn(self, url: str) -> bytes: ...
    async def get_config(self, user_id: str, context_token: str | None) -> dict[str, Any]: ...
    async def send_typing(
        self, user_id: str, typing_ticket: str, *, status: int = 1
    ) -> None: ...
    async def notify_start(self) -> None: ...
    async def notify_stop(self) -> None: ...
    async def close(self) -> None: ...


class WeChatClient:
    """Concrete HTTP client (unauthenticated for QR, token-backed otherwise)."""

    def __init__(
        self,
        *,
        base_url: str = DEFAULT_API_BASE,
        token: str | None = None,
        cdn_base_url: str = DEFAULT_CDN_BASE,
        timeout_s: float = DEFAULT_API_TIMEOUT_S,
        http: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.cdn_base_url = cdn_base_url.rstrip("/")
        self.timeout_s = timeout_s
        self._http = http
        self._owns_http = http is None

    async def __aenter__(self) -> WeChatClient:
        return self

    async def __aexit__(self, *_: Any) -> None:
        await self.close()

    async def close(self) -> None:
        if self._owns_http and self._http is not None:
            await self._http.aclose()
        self._http = None

    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(follow_redirects=True)
        return self._http

    # -- headers / wire ----------------------------------------------------
    def _app_headers(self) -> dict[str, str]:
        uin = base64.b64encode(str(random.getrandbits(32)).encode()).decode()
        return {
            "iLink-App-Id": APP_ID,
            "iLink-App-ClientVersion": str(CLIENT_VERSION),
            "X-WECHAT-UIN": uin,
        }

    def _headers(self, *, authenticated: bool) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "AuthorizationType": "ilink_bot_token",
            **self._app_headers(),
        }
        if authenticated:
            if not self.token:
                raise WeChatAuthError("missing bot token")
            headers["Authorization"] = f"Bearer {self.token}"
        return headers

    def _base_info(self) -> dict[str, str]:
        return {"channel_version": CHANNEL_VERSION, "bot_agent": BOT_AGENT}

    async def _post(
        self,
        endpoint: str,
        body: dict[str, Any],
        *,
        authenticated: bool = True,
        timeout_s: float | None = None,
    ) -> dict[str, Any]:
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        try:
            response = await self._client().post(
                url,
                headers=self._headers(authenticated=authenticated),
                json=body,
                timeout=timeout_s or self.timeout_s,
            )
            response.raise_for_status()
        except httpx.TimeoutException:
            raise
        except httpx.HTTPError as exc:
            raise WeChatAPIError(f"{endpoint}: {exc}") from exc
        return _json_object(response)

    async def _get(
        self,
        endpoint: str,
        params: dict[str, str],
        *,
        timeout_s: float | None = None,
        base_url: str | None = None,
    ) -> dict[str, Any]:
        base = (base_url or self.base_url).rstrip("/")
        url = f"{base}/{endpoint.lstrip('/')}"
        try:
            response = await self._client().get(
                url,
                headers=self._app_headers(),
                params=params,
                timeout=timeout_s or self.timeout_s,
            )
            response.raise_for_status()
        except httpx.TimeoutException:
            raise
        except httpx.HTTPError as exc:
            raise WeChatAPIError(f"{endpoint}: {exc}") from exc
        return _json_object(response)

    @staticmethod
    def _check(payload: dict[str, Any], *, label: str) -> None:
        ret = payload.get("ret")
        errcode = payload.get("errcode")
        if ret in (None, 0) and errcode in (None, 0):
            return
        errmsg = str(payload.get("errmsg") or "")
        if ret == STALE_TOKEN_ERRCODE or errcode == STALE_TOKEN_ERRCODE:
            raise WeChatAuthError(
                f"{label}: bot token is stale; a QR re-login is required",
                ret=ret,
                errcode=errcode,
                errmsg=errmsg,
            )
        raise WeChatAPIError(
            f"{label}: ret={ret} errcode={errcode} {errmsg}".strip(),
            ret=ret,
            errcode=errcode,
            errmsg=errmsg,
        )

    # -- login -------------------------------------------------------------
    async def get_qr(self, *, local_tokens: list[str] | None = None) -> dict[str, Any]:
        payload = await self._post(
            "ilink/bot/get_bot_qrcode?bot_type=3",
            {"local_token_list": list(local_tokens or [])[:10]},
            authenticated=False,
        )
        if not payload.get("qrcode") or not payload.get("qrcode_img_content"):
            raise WeChatAPIError("QR response is missing qrcode/qrcode_img_content")
        return payload

    async def poll_qr(
        self,
        qrcode: str,
        *,
        verify_code: str | None = None,
        base_url: str | None = None,
        timeout_s: float = LONG_POLL_TIMEOUT_S,
    ) -> dict[str, Any]:
        params = {"qrcode": qrcode}
        if verify_code:
            params["verify_code"] = verify_code
        try:
            return await self._get(
                "ilink/bot/get_qrcode_status",
                params,
                timeout_s=timeout_s,
                base_url=base_url,
            )
        except httpx.TimeoutException:
            return {"status": "wait"}

    # -- bot API -----------------------------------------------------------
    async def get_updates(
        self, cursor: str = "", *, timeout_s: float = LONG_POLL_TIMEOUT_S
    ) -> dict[str, Any]:
        payload = {
            "get_updates_buf": cursor,
            "base_info": self._base_info(),
        }
        try:
            response = await self._post(
                "ilink/bot/getupdates", payload, timeout_s=timeout_s
            )
        except httpx.TimeoutException:
            # A long-poll timeout is normal.
            return {"ret": 0, "msgs": [], "get_updates_buf": cursor}
        self._check(response, label="getUpdates")
        return response

    async def send_message(self, msg: dict[str, Any]) -> dict[str, Any]:
        response = await self._post(
            "ilink/bot/sendmessage", {"msg": msg, "base_info": self._base_info()}
        )
        self._check(response, label="sendMessage")
        return response

    async def get_upload_url(self, payload: dict[str, Any]) -> dict[str, Any]:
        body = {**payload, "base_info": self._base_info()}
        response = await self._post("ilink/bot/getuploadurl", body)
        self._check(response, label="getUploadUrl")
        return response

    async def upload_cdn(self, url: str, ciphertext: bytes) -> str:
        last_error: WeChatAPIError | None = None
        for attempt in range(_CDN_UPLOAD_RETRIES):
            try:
                response = await self._client().post(
                    url,
                    content=ciphertext,
                    headers={"Content-Type": "application/octet-stream"},
                    timeout=max(self.timeout_s, CDN_TIMEOUT_S),
                )
            except httpx.HTTPError as exc:
                last_error = WeChatAPIError(f"CDN upload: {exc}")
            else:
                message = response.headers.get("x-error-message", "")
                if 400 <= response.status_code < 500:
                    raise WeChatAPIError(
                        f"CDN upload client error HTTP {response.status_code}: {message}"
                    )
                if response.status_code == 200:
                    param = response.headers.get("x-encrypted-param")
                    if param:
                        return param
                    last_error = WeChatAPIError(
                        "CDN upload response missing x-encrypted-param"
                    )
                else:
                    last_error = WeChatAPIError(
                        f"CDN upload server error HTTP {response.status_code}: {message}"
                    )
            if attempt < _CDN_UPLOAD_RETRIES - 1:
                await asyncio.sleep(_CDN_RETRY_BASE_S * (attempt + 1))
        raise last_error or WeChatAPIError("CDN upload failed")

    async def download_cdn(self, url: str) -> bytes:
        limit = MAX_CDN_BYTES
        chunks: list[bytes] = []
        total = 0
        try:
            async with self._client().stream(
                "GET", url, timeout=max(self.timeout_s, CDN_TIMEOUT_S)
            ) as response:
                response.raise_for_status()
                async for chunk in response.aiter_bytes():
                    total += len(chunk)
                    if total > limit:
                        raise WeChatAPIError(
                            f"CDN download exceeds the {limit // (1024 * 1024)} MB limit"
                        )
                    chunks.append(chunk)
        except httpx.HTTPError as exc:
            raise WeChatAPIError(f"CDN download: {exc}") from exc
        return b"".join(chunks)

    async def get_config(
        self, user_id: str, context_token: str | None
    ) -> dict[str, Any]:
        response = await self._post(
            "ilink/bot/getconfig",
            {
                "ilink_user_id": user_id,
                "context_token": context_token,
                "base_info": self._base_info(),
            },
        )
        self._check(response, label="getConfig")
        return response

    async def send_typing(
        self, user_id: str, typing_ticket: str, *, status: int = 1
    ) -> None:
        response = await self._post(
            "ilink/bot/sendtyping",
            {
                "ilink_user_id": user_id,
                "typing_ticket": typing_ticket,
                "status": status,
                "base_info": self._base_info(),
            },
        )
        self._check(response, label="sendTyping")

    async def notify_start(self) -> None:
        await self._post(
            "ilink/bot/msg/notifystart", {"base_info": self._base_info()}
        )

    async def notify_stop(self) -> None:
        await self._post(
            "ilink/bot/msg/notifystop", {"base_info": self._base_info()}
        )


# ---------------------------------------------------------------------------
# AES-128-ECB / CDN helpers
# ---------------------------------------------------------------------------


def md5_hex(data: bytes) -> str:
    return hashlib.md5(data).hexdigest()


def padded_size(size: int) -> int:
    return ((size + 16) // 16) * 16


def encrypt_ecb(plaintext: bytes, key: bytes) -> bytes:
    padder = padding.PKCS7(128).padder()
    padded = padder.update(plaintext) + padder.finalize()
    encryptor = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    return encryptor.update(padded) + encryptor.finalize()


def decrypt_ecb(ciphertext: bytes, key: bytes) -> bytes:
    decryptor = Cipher(algorithms.AES(key), modes.ECB()).decryptor()
    padded = decryptor.update(ciphertext) + decryptor.finalize()
    unpadder = padding.PKCS7(128).unpadder()
    return unpadder.update(padded) + unpadder.finalize()


def parse_aes_key(value: str) -> bytes:
    """Parse the two encodings seen in the wild: base64(raw 16) or base64(hex)."""
    try:
        decoded = base64.b64decode(value)
    except (binascii.Error, ValueError) as exc:
        raise WeChatAPIError("aes_key is not valid base64") from exc
    if len(decoded) == 16:
        return decoded
    if len(decoded) == 32:
        try:
            return bytes.fromhex(decoded.decode("ascii"))
        except (UnicodeDecodeError, ValueError):
            pass
    raise WeChatAPIError("aes_key must decode to 16 raw bytes or 32 hex chars")


def build_download_url(encrypt_query_param: str, cdn_base_url: str) -> str:
    return (
        f"{cdn_base_url.rstrip('/')}/download"
        f"?encrypted_query_param={quote(encrypt_query_param, safe='')}"
    )


def build_upload_url(upload_param: str, filekey: str, cdn_base_url: str) -> str:
    return (
        f"{cdn_base_url.rstrip('/')}/upload"
        f"?encrypted_query_param={quote(upload_param, safe='')}"
        f"&filekey={quote(filekey, safe='')}"
    )


def _json_object(response: httpx.Response) -> dict[str, Any]:
    try:
        payload = json.loads(response.text or "{}")
    except ValueError as exc:
        raise WeChatAPIError(f"invalid JSON response: {exc}") from exc
    if not isinstance(payload, dict):
        raise WeChatAPIError("response is not a JSON object")
    return payload

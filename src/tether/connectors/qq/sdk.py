"""Thin client over the QQ Bot Open Platform api-v2 (no official SDK).

This module owns the pieces the connector needs and nothing more: the
``getAppAccessToken`` credential, the WebSocket gateway handshake
(Hello/Identify/Heartbeat/Resume) and a few REST calls (send a direct or group
message, upload rich media, respond to an interaction, fetch a URL). It is
deliberately dependency-light — ``httpx`` for REST and ``websockets`` for the
gateway — and knows nothing about the Tether connector layer, so the connector
can hide it behind :class:`QQSDK` and be exercised against a fake.

The WebSocket runs in its own thread with its own event loop (the public
``start``/``stop`` API is synchronous); REST methods are synchronous too, so the
connector dispatches them with ``asyncio.to_thread``.
"""

from __future__ import annotations

import asyncio
import base64
import contextlib
import json
import threading
import time
from collections.abc import Callable
from typing import Any, Protocol
from urllib.parse import urlparse

import httpx
import websockets

from tether.util.logging import get_logger
from tether.util.net import is_public_host

log = get_logger("tether.qq")

API_BASE = "https://api.bot.qq.com"
TOKEN_PATH = "/app/getAppAccessToken"
GATEWAY_PATH = "/gateway"
DEFAULT_GATEWAY = "wss://api.bot.qq.com/websocket/"

# Gateway opcodes.
OP_DISPATCH = 0
OP_HEARTBEAT = 1
OP_IDENTIFY = 2
OP_RESUME = 6
OP_RECONNECT = 7
OP_INVALID_SESSION = 9
OP_HELLO = 10
OP_HEARTBEAT_ACK = 11

# Event subscription intents (bitmask).
INTENT_GROUP_AND_C2C = 1 << 25
INTENT_INTERACTION = 1 << 26
DEFAULT_INTENTS = INTENT_GROUP_AND_C2C | INTENT_INTERACTION

# WebSocket close codes and the reconnect they call for.
# No retry makes sense for these (bad opcode/payload, shard/version, intents,
# sandbox/banned) — a reconnect would fail the same way.
_CLOSE_FATAL = frozenset({4001, 4002, 4010, 4011, 4012, 4013, 4014, 4914, 4915})
# These require a fresh Identify (invalid session / seq / too fast / internal).
_CLOSE_IDENTIFY = frozenset({4006, 4007, 4008}) | frozenset(range(4900, 4914))

# The URL/file endpoint also accepts a direct base64 payload, capped at 5 MiB;
# larger media needs the multipart flow (not implemented).
_BINARY_UPLOAD_MAX = 5 * 1024 * 1024
_TOKEN_REFRESH_MARGIN_S = 60.0
_BACKOFF_MIN_S = 1.0
_BACKOFF_MAX_S = 30.0
_HELLO_TIMEOUT_S = 10.0
# A connection must live this long before its success resets the backoff.
_STABLE_CONNECTION_S = 30.0
# Reconnect after this many heartbeat intervals with no frame from the gateway.
_MAX_MISSED_ACKS = 2


class QQError(Exception):
    """A QQ api-v2 call failed."""


class QQAuthError(QQError):
    """The access token could not be obtained."""


class QQAPIError(QQError):
    """A REST call returned a business error (``err_code``)."""

    def __init__(self, code: Any, message: str = "") -> None:
        super().__init__(f"qq api error {code}: {message}")
        self.code = code
        self.message = message


class QQUnsupported(QQError):
    """A requested capability is not implemented by this client."""


class _FatalGatewayError(QQError):
    """The gateway will not accept this bot (sandbox/banned); stop retrying."""


class QQSDK(Protocol):
    """The subset of the api-v2 client the connector uses (all synchronous)."""

    def start(self, on_event: Callable[[str, dict[str, Any]], None]) -> None: ...
    def stop(self) -> None: ...
    @property
    def connected(self) -> bool: ...
    def post_c2c_message(self, openid: str, **fields: Any) -> str: ...
    def post_group_message(self, group_openid: str, **fields: Any) -> str: ...
    def upload_file(
        self,
        *,
        scope: str,
        target_id: str,
        file_type: int,
        filename: str | None = None,
        data: bytes | None = None,
        url: str | None = None,
    ) -> str: ...
    def put_interaction(self, interaction_id: str, code: int = 0) -> None: ...
    def download(self, url: str) -> bytes: ...


class QQClient:
    """api-v2 client: cached access token, WebSocket gateway and REST helpers."""

    def __init__(
        self,
        appid: str,
        secret: str,
        *,
        intents: int | None = None,
        shard: tuple[int, int] = (0, 1),
        api_base: str = API_BASE,
    ) -> None:
        self._appid = appid
        self._secret = secret
        self._intents = intents if intents is not None else DEFAULT_INTENTS
        self._shard = shard
        self._api_base = api_base.rstrip("/")
        self._token_url = self._api_base + TOKEN_PATH

        self._token: str | None = None
        self._token_expiry = 0.0
        self._token_lock = threading.Lock()

        self._loop: asyncio.AbstractEventLoop | None = None
        self._ws: Any = None
        self._session_id: str | None = None
        self._seq: int | None = None
        self._connected = False
        self._stop_event = asyncio.Event()
        self._stopped = threading.Event()
        self._ready = threading.Event()
        self._heartbeat_task: asyncio.Task[None] | None = None
        self._missed_acks = 0

    # -- access token ------------------------------------------------------
    def _access_token(self) -> str:
        with self._token_lock:
            now = time.monotonic()
            if self._token and now < self._token_expiry - _TOKEN_REFRESH_MARGIN_S:
                return self._token

            resp = httpx.post(
                self._token_url,
                json={"appId": self._appid, "clientSecret": self._secret},
                timeout=10,
            )
            data = _json(resp)

            token = data.get("access_token")
            if not token:
                # Token failures report a business code in the body while the
                # HTTP status stays 200, so read the body rather than the status.
                raise QQAuthError(f"access token failed: code={data.get('code')}")

            self._token = str(token)
            self._token_expiry = now + float(data.get("expires_in") or 7200)

            return self._token

    def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"QQBot {self._access_token()}",
            "Content-Type": "application/json; charset=utf-8",
        }

    # -- REST --------------------------------------------------------------
    def _get(self, path: str) -> dict[str, Any]:
        resp = httpx.get(self._api_base + path, headers=self._headers(), timeout=30)
        return _json(resp, check_error=True)

    def _post(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        resp = httpx.post(self._api_base + path, headers=self._headers(), json=body, timeout=30)
        return _json(resp, check_error=True)

    def _put(self, path: str, body: dict[str, Any]) -> dict[str, Any]:
        resp = httpx.put(self._api_base + path, headers=self._headers(), json=body, timeout=30)
        return _json(resp, check_error=True)

    def post_c2c_message(self, openid: str, **fields: Any) -> str:
        return self._send(f"/v2/users/{openid}/messages", fields)

    def post_group_message(self, group_openid: str, **fields: Any) -> str:
        return self._send(f"/v2/groups/{group_openid}/messages", fields)

    def _send(self, path: str, fields: dict[str, Any]) -> str:
        data = self._post(path, fields)
        return str(data.get("id") or "")

    def upload_file(
        self,
        *,
        scope: str,
        target_id: str,
        file_type: int,
        filename: str | None = None,
        data: bytes | None = None,
        url: str | None = None,
    ) -> str:
        resource = "groups" if scope == "group" else "users"
        body: dict[str, Any] = {"file_type": file_type, "srv_send_msg": False}

        if data is not None:
            if len(data) > _BINARY_UPLOAD_MAX:
                raise QQUnsupported(
                    "qq media larger than 5 MiB needs the multipart upload flow"
                )

            body["file_data"] = base64.b64encode(data).decode()
            body["file_name"] = filename or f"file.{file_type}"
        elif url:
            body["url"] = url
        else:
            raise QQUnsupported("qq upload needs file data or a url")

        result = self._post(f"/v2/{resource}/{target_id}/files", body)
        file_info = result.get("file_info")
        if not file_info:
            raise QQAPIError(0, "upload returned no file_info")

        return str(file_info)

    def put_interaction(self, interaction_id: str, code: int = 0) -> None:
        self._put(f"/interactions/{interaction_id}", {"code": code})

    def download(self, url: str) -> bytes:
        host = urlparse(url).hostname or ""
        if not is_public_host(host):
            raise QQError(f"refusing to fetch non-public media url: {host}")

        resp = httpx.get(url, timeout=60, follow_redirects=True)
        resp.raise_for_status()

        return resp.content

    # -- gateway URL -------------------------------------------------------
    def _gateway_url(self) -> str:
        try:
            return str(self._get(GATEWAY_PATH).get("url") or DEFAULT_GATEWAY)
        except QQError:
            log.warning("qq_gateway_url_failed", exc_info=True)
            return DEFAULT_GATEWAY

    # -- lifecycle ---------------------------------------------------------
    def start(self, on_event: Callable[[str, dict[str, Any]], None]) -> None:
        self._stopped.clear()
        self._ready.clear()
        threading.Thread(target=self._run, args=(on_event,), daemon=True).start()
        # Return once the gateway thread has tried to connect (or failed its
        # first attempt); do not block the caller on the socket itself.
        self._ready.wait(timeout=_HELLO_TIMEOUT_S)

    def stop(self) -> None:
        self._stopped.set()
        loop = self._loop
        if loop is not None and not loop.is_closed():
            with contextlib.suppress(RuntimeError):
                loop.call_soon_threadsafe(self._wake)

    @property
    def connected(self) -> bool:
        return self._connected and self._ws is not None

    def _wake(self) -> None:
        self._stop_event.set()
        ws = self._ws
        if ws is not None:
            asyncio.ensure_future(ws.close())

    def _run(self, on_event: Callable[[str, dict[str, Any]], None]) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._stop_event.clear()

        try:
            loop.run_until_complete(self._serve(on_event))
        except Exception:  # noqa: BLE001 - a dead thread must not crash Tether
            log.error("qq_gateway_thread_failed", exc_info=True)
        finally:
            self._ready.set()
            self._loop = None
            with contextlib.suppress(Exception):
                loop.close()

    async def _serve(self, on_event: Callable[[str, dict[str, Any]], None]) -> None:
        backoff = _BACKOFF_MIN_S
        first = True

        while not self._stopped.is_set():
            # A raised transport error (e.g. DNS) leaves an existing session
            # intact, so keep it and resume on the next attempt; only a fresh
            # start needs an Identify.
            action = "resume" if self._session_id is not None else "identify"
            started = time.monotonic()

            try:
                action = await self._connect(on_event)
                # Only a connection that lived a while proves the endpoint is
                # healthy; a connect-then-drop loop keeps backing off.
                if time.monotonic() - started >= _STABLE_CONNECTION_S:
                    backoff = _BACKOFF_MIN_S
            except _FatalGatewayError as exc:
                log.error("qq_gateway_gave_up", code=getattr(exc, "args", ("",))[0])
                break
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - reconnect on any transport error
                log.warning("qq_gateway_error", exc_info=True)
            finally:
                if first:
                    self._ready.set()
                    first = False

            if self._stopped.is_set():
                break

            if action == "identify":
                self._reset_session()

            await self._sleep(backoff)
            backoff = min(backoff * 2, _BACKOFF_MAX_S)

    async def _connect(self, on_event: Callable[[str, dict[str, Any]], None]) -> str:
        uri = await asyncio.to_thread(self._gateway_url)
        log.info("qq_gateway_connecting")

        async with websockets.connect(uri, max_size=None) as ws:
            self._ws = ws
            code: int | None = None
            try:
                await self._handshake(ws, on_event)
                async for raw in ws:
                    await self._dispatch(raw, on_event)
            except websockets.ConnectionClosed:
                pass
            finally:
                self._connected = False
                self._ws = None
                await self._cancel_heartbeat()
                code = ws.close_code

        return self._close_action(code)

    def _close_action(self, code: int | None) -> str:
        if code in _CLOSE_FATAL:
            raise _FatalGatewayError(code)

        if code in _CLOSE_IDENTIFY:
            return "identify"

        # 4009 ("connection expired") and any normal/abnormal drop (no code,
        # 1000/1006, …): resume when a session exists so the gateway replays
        # missed events, else identify.
        return "resume" if self._session_id is not None else "identify"

    async def _handshake(
        self, ws: Any, on_event: Callable[[str, dict[str, Any]], None]
    ) -> None:
        interval_ms = await self._wait_hello(ws)

        if self._session_id is not None:
            await self._resume(ws)
        else:
            await self._identify(ws)

        self._missed_acks = 0
        self._connected = True
        self._ready.set()
        self._heartbeat_task = asyncio.ensure_future(
            self._heartbeat(ws, max(interval_ms, 1) / 1000)
        )

    async def _wait_hello(self, ws: Any) -> int:
        for _ in range(5):
            payload = _decode(await ws.recv())
            if payload.get("op") == OP_HELLO:
                data = payload.get("d")
                interval = data.get("heartbeat_interval") if isinstance(data, dict) else None
                return int(interval or 45000)

        raise QQError("qq gateway did not send a hello")

    async def _identify(self, ws: Any) -> None:
        token = await asyncio.to_thread(self._access_token)
        await ws.send(
            json.dumps(
                {
                    "op": OP_IDENTIFY,
                    "d": {
                        "token": f"QQBot {token}",
                        "intents": self._intents,
                        "shard": list(self._shard),
                        "properties": {
                            "$os": "python",
                            "$browser": "tether",
                            "$device": "tether",
                        },
                    },
                }
            )
        )

    async def _resume(self, ws: Any) -> None:
        token = await asyncio.to_thread(self._access_token)
        await ws.send(
            json.dumps(
                {
                    "op": OP_RESUME,
                    "d": {
                        "token": f"QQBot {token}",
                        "session_id": self._session_id,
                        "seq": self._seq,
                    },
                }
            )
        )

    async def _heartbeat(self, ws: Any, interval_s: float) -> None:
        try:
            while True:
                await asyncio.sleep(interval_s)
                await ws.send(json.dumps({"op": OP_HEARTBEAT, "d": self._seq}))
                # Any frame from the gateway clears this (see _dispatch); a
                # gateway that stops answering is dead even if the TCP is up.
                self._missed_acks += 1
                if self._missed_acks > _MAX_MISSED_ACKS:
                    log.warning("qq_heartbeat_unanswered", missed=self._missed_acks)
                    await self._close()
                    return
        except (asyncio.CancelledError, websockets.ConnectionClosed):
            return

    async def _dispatch(
        self, raw: Any, on_event: Callable[[str, dict[str, Any]], None]
    ) -> None:
        payload = _decode(raw)

        # Any frame proves the gateway is alive; clear the heartbeat-miss count.
        self._missed_acks = 0

        seq = payload.get("s")
        if isinstance(seq, int):
            self._seq = seq

        op = payload.get("op")
        if op == OP_DISPATCH:
            event = str(payload.get("t") or "")
            data = payload.get("d")
            record = data if isinstance(data, dict) else {}
            if event == "READY":
                self._session_id = str(record.get("session_id") or "") or None

            _notify(on_event, event, record)
        elif op == OP_INVALID_SESSION:
            # The session is gone: drop it and reconnect with a fresh Identify.
            self._reset_session()
            await self._close()
        elif op == OP_RECONNECT:
            await self._close()

    async def _cancel_heartbeat(self) -> None:
        task = self._heartbeat_task
        self._heartbeat_task = None
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    async def _close(self) -> None:
        ws = self._ws
        if ws is not None:
            with contextlib.suppress(Exception):
                await ws.close()

    async def _sleep(self, seconds: float) -> None:
        with contextlib.suppress(asyncio.TimeoutError):
            await asyncio.wait_for(self._stop_event.wait(), timeout=seconds)

    def _reset_session(self) -> None:
        self._session_id = None
        self._seq = None


def _json(resp: httpx.Response, *, check_error: bool = False) -> dict[str, Any]:
    """Decode a response body, raising on a business ``err_code`` if asked."""
    try:
        data = resp.json()
    except ValueError:
        if check_error:
            resp.raise_for_status()
        return {}

    if not isinstance(data, dict):
        return {}

    if check_error and data.get("err_code") not in (None, 0):
        raise QQAPIError(data.get("err_code"), str(data.get("message") or ""))

    if check_error:
        resp.raise_for_status()

    return data


def _decode(raw: Any) -> dict[str, Any]:
    if isinstance(raw, bytes):
        raw = raw.decode("utf-8", "replace")

    try:
        data = json.loads(raw)
    except (ValueError, TypeError):
        return {}

    return data if isinstance(data, dict) else {}


def _notify(on_event: Callable[[str, dict[str, Any]], None], event: str, data: dict) -> None:
    if not event:
        return

    try:
        on_event(event, data)
    except Exception:  # noqa: BLE001 - one bad event must not kill the read loop
        log.warning("qq_dispatch_callback_failed", event=event, exc_info=True)


__all__ = [
    "DEFAULT_INTENTS",
    "DEFAULT_GATEWAY",
    "INTENT_GROUP_AND_C2C",
    "INTENT_INTERACTION",
    "QQAPIError",
    "QQAuthError",
    "QQClient",
    "QQError",
    "QQSDK",
    "QQUnsupported",
]

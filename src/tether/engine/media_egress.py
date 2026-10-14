"""Collect media produced by tools and deliver it through a connector.

Tool results may reference files as inline data URLs, remote URLs or provider
file references. Anything the channel cannot receive degrades to a short text
link rather than being dropped.
"""

from __future__ import annotations

import base64
import binascii
import ipaddress
import os
import socket
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

import httpx

from ..config import Config
from ..connector import IMConnector
from ..metrics import metrics
from ..models import (
    Conversation,
    MediaSegment,
    NormalizedMediaKind,
    OutboundPlan,
    RichMedia,
    TextSegment,
    normalize_media_kind,
)
from ..util.logging import get_logger
from ..util.media import compress_image, sniff_mime

log = get_logger("tether.media")

_EXTENSION_KINDS = (
    ((".png", ".jpg", ".jpeg", ".gif", ".webp"), "image"),
    ((".mp3", ".wav", ".ogg", ".amr", ".silk"), "audio"),
    ((".mp4", ".mov", ".webm"), "video"),
)


def files_from_paths(paths: Any, *, base_dir: str | None, max_bytes: int) -> list[RichMedia]:
    """Read files an agent produced, named by path rather than by inline bytes.

    Tool results report produced files as ``outputPaths`` (absolute paths on the
    agent host) and step results as relative ``files`` (resolved against the
    project directory). Missing, non-file or oversized entries are skipped.
    """
    out: list[RichMedia] = []
    for raw in paths or []:
        if not isinstance(raw, str) or not raw:
            continue
        path = Path(raw) if os.path.isabs(raw) else Path(base_dir or ".").joinpath(raw)
        try:
            if not path.is_file() or path.stat().st_size > max_bytes:
                continue
            data = path.read_bytes()
        except OSError:
            log.warning("output_file_unreadable", path=raw)
            continue
        mime = sniff_mime(data, path.name, None)
        out.append(
            RichMedia(
                kind=normalize_media_kind(_media_kind(mime, path.name)),
                data=data,
                mime=mime,
                name=path.name,
            )
        )
    return out


_STRUCTURED_FILE_OPERATIONS = ("write", "edit")


def structured_file_paths(structured: Any) -> list[str]:
    """Produced file paths named in a tool's structured output.

    ``write`` names the file in ``structured.resource``/``target`` (its
    ``operation`` is ``write``); ``edit``/``apply_patch`` instead report a
    ``structured.files`` list where each entry carries ``file``.
    """
    if not isinstance(structured, dict):
        return []
    out: list[str] = []
    files = structured.get("files")
    if isinstance(files, list):
        for item in files:
            path = item.get("file") if isinstance(item, dict) else None
            if isinstance(path, str) and path:
                out.append(path)
    if structured.get("operation") in _STRUCTURED_FILE_OPERATIONS:
        for key in ("resource", "target"):
            value = structured.get(key)
            if isinstance(value, str) and value:
                out.append(value)
    return out


def extract_file_parts(data: Any) -> list[RichMedia]:
    """Collect every file-like part found anywhere within ``data``.

    A part is any mapping that declares ``type: "file"`` or carries a ``uri``
    together with a ``mime`` or ``mediaSource``. Inline data URLs are decoded to
    bytes; other URIs are kept as references.
    """
    out: list[RichMedia] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            if _is_file_part(node):
                out.append(_file_part_to_media(node))
                return
            for value in node.values():
                walk(value)
        elif isinstance(node, list):
            for value in node:
                walk(value)

    walk(data)
    return out


def _is_file_part(node: dict[str, Any]) -> bool:
    if node.get("type") == "file":
        return True
    return "uri" in node and ("mime" in node or "mediaSource" in node)


def _file_part_to_media(node: dict[str, Any]) -> RichMedia:
    uri = str(node.get("uri") or "")
    mime = node.get("mime")
    name = node.get("name")
    decoded = _decode_data_url(uri)
    return RichMedia(
        kind=normalize_media_kind(_media_kind(mime, name)),
        url=None if uri.startswith("data:") else uri or None,
        data=decoded[0] if decoded else None,
        mime=str(mime) if mime else None,
        name=str(name) if name else None,
    )


def _decode_data_url(uri: str) -> tuple[bytes, str | None] | None:
    if not uri.startswith("data:") or ";base64," not in uri:
        return None
    header, payload = uri.split(";base64,", 1)
    mime = header[len("data:") :] or None
    try:
        return base64.b64decode(payload), mime
    except (binascii.Error, ValueError):
        return None


def _media_kind(mime: Any, name: Any) -> str:
    value = str(mime or "")
    for prefix in ("image", "audio", "video"):
        if value.startswith(f"{prefix}/"):
            return prefix
    if isinstance(name, str):
        lower = name.lower()
        for extensions, kind in _EXTENSION_KINDS:
            if lower.endswith(extensions):
                return kind
    return "file"


class MediaEgress:
    def __init__(self, config: Config, connector: IMConnector) -> None:
        self.config = config
        self.connector = connector

    async def send(self, conv: Conversation, media: RichMedia) -> None:
        kind = normalize_media_kind(media.kind)
        if not self.connector.capabilities.supports_media_out(kind):
            await self._send_link(conv, media, reason="this channel cannot receive this media type")
            return
        data = await self._resolve_bytes(conv, media)
        if data is None:
            return
        mime = media.mime
        if kind == "image" and len(data) > self.config.media.outbound.image_max_bytes:
            data = compress_image(
                data,
                max_bytes=self.config.media.outbound.image_max_bytes,
                mime=mime or "image/png",
            )
        mime = sniff_mime(data, media.name, mime)
        await self._deliver(conv, media, kind, data, mime)

    async def _resolve_bytes(self, conv: Conversation, media: RichMedia) -> bytes | None:
        if media.data is not None:
            return media.data
        if not media.url:
            return None
        if not self.config.media.fetch_url_outbound:
            await self._send_link(conv, media, reason="remote media (proxied fetch disabled)")
            return None
        data = await self._fetch(media.url)
        if data is None:
            await self._send_link(conv, media, reason="fetch failed")
        return data

    async def _deliver(
        self,
        conv: Conversation,
        media: RichMedia,
        kind: NormalizedMediaKind,
        data: bytes,
        mime: str,
    ) -> None:
        segment = MediaSegment(media=RichMedia(kind=kind, data=data, mime=mime, name=media.name))
        plan = OutboundPlan(segments=[segment])
        if media.caption:
            plan.segments.insert(0, TextSegment(text=media.caption))
        try:
            await self.connector.send(conv, plan)
            metrics.inc("media_bytes_out", len(data))
        except Exception as exc:  # noqa: BLE001 - fall back to a link, never crash the turn
            metrics.inc("media_send_failures")
            log.warning("media_send_failed", kind=kind, error=str(exc))
            await self._send_link(conv, media, reason="send failed")

    async def _send_link(self, conv: Conversation, media: RichMedia, *, reason: str) -> None:
        label = media.name or media.kind
        if media.url:
            text = f"📎 {label}: {media.url} ({reason})"
        else:
            text = f"📎 {label} could not be sent ({reason})."
        await self.connector.send(conv, OutboundPlan(segments=[TextSegment(text=text)]))

    async def _fetch(self, url: str) -> bytes | None:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not _is_public_host(parsed.hostname or ""):
            return None
        try:
            async with httpx.AsyncClient(timeout=15.0, follow_redirects=False) as client:
                resp = await client.get(url)
                resp.raise_for_status()
                if len(resp.content) > self.config.media.max_bytes:
                    return None
                return resp.content
        except httpx.HTTPError:
            return None


def _is_public_host(host: str) -> bool:
    """Reject hosts that resolve to a private, loopback or reserved address."""
    if not host:
        return False
    try:
        addresses = socket.getaddrinfo(host, None)
    except OSError:
        return False
    for address in addresses:
        ip = ipaddress.ip_address(address[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved:
            log.warning("ssrf_blocked", host=host)
            return False
    return True

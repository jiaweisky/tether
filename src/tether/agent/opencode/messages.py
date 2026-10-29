"""Build a backend-neutral turn snapshot from OpenCode messages."""

from __future__ import annotations

import base64
import binascii
from typing import Any

from tether.agent.base import TurnSnapshot
from tether.models import RichMedia, normalize_media_kind


def snapshot_messages(
    messages: list[dict[str, Any]], *, after_message_id: str | None = None
) -> TurnSnapshot:
    start = _turn_start(messages, after_message_id)
    turn = [item for item in messages[start:] if isinstance(item, dict)]

    text: str | None = None
    for item in reversed(turn):
        if item.get("type") != "assistant":
            continue
        content = item.get("content")
        if not isinstance(content, list):
            continue
        parts = [
            str(part.get("text") or "")
            for part in content
            if isinstance(part, dict) and part.get("type") == "text"
        ]
        text = "".join(parts) or None
        break

    media: list[RichMedia] = []
    seen: set[str] = set()
    for item in turn:
        if item.get("type") != "assistant":
            continue
        for part in _assistant_parts(item):
            if part.get("type") != "file":
                continue
            item_media = _file_media(part)
            key = item_media.name or item_media.url or item_media.mime or ""
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            media.append(item_media)

    return TurnSnapshot(turn_id=None, text=text, media=media)


def _turn_start(messages: list[dict[str, Any]], after_message_id: str | None) -> int:
    if after_message_id:
        for index, item in enumerate(messages):
            if item.get("id") == after_message_id:
                return index + 1

    for index in range(len(messages) - 1, -1, -1):
        if messages[index].get("type") == "user":
            return index + 1
    return 0


def _assistant_parts(message: dict[str, Any]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    content = message.get("content")
    for item in content if isinstance(content, list) else []:
        if not isinstance(item, dict):
            continue
        if item.get("type") == "tool":
            state = item.get("state")
            if isinstance(state, dict):
                for part in state.get("content") or []:
                    if isinstance(part, dict):
                        out.append(part)
        elif item.get("type") == "file":
            out.append(item)
    return out


def _file_media(part: dict[str, Any]) -> RichMedia:
    uri = str(part.get("uri") or "")
    mime = _string_or_none(part.get("mime"))
    name = _string_or_none(part.get("name"))
    data = _decode_data_url(uri) if uri.startswith("data:") else None
    if data is not None and mime is None:
        mime = _data_url_mime(uri)

    return RichMedia(
        kind=normalize_media_kind(_kind(mime, name)),
        data=data,
        mime=mime,
        name=name,
        url=None if uri.startswith("data:") else uri or None,
    )


def _decode_data_url(uri: str) -> bytes | None:
    if ";base64," not in uri:
        return None
    _, payload = uri.split(";base64,", 1)
    try:
        return base64.b64decode(payload)
    except (binascii.Error, ValueError):
        return None


def _data_url_mime(uri: str) -> str | None:
    header = uri.split(";base64,", 1)[0]
    return header[len("data:") :] or None


def _kind(mime: str | None, name: str | None) -> str:
    value = (mime or "").lower()
    for kind in ("image", "audio", "video"):
        if value.startswith(f"{kind}/"):
            return kind

    lowered = (name or "").lower()
    if lowered.endswith((".png", ".jpg", ".jpeg", ".gif", ".webp")):
        return "image"
    if lowered.endswith((".mp3", ".wav", ".ogg", ".amr", ".silk")):
        return "audio"
    if lowered.endswith((".mp4", ".mov", ".webm")):
        return "video"
    return "file"


def _string_or_none(value: Any) -> str | None:
    return str(value) if value is not None else None


__all__ = ["snapshot_messages"]

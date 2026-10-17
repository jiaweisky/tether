"""In-memory WeChat credential/state types (persisted in SQLite)."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class WeChatCredential:
    token: str
    base_url: str
    bot_id: str | None = None
    user_id: str | None = None
    saved_at: float = 0.0

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WeChatCredential | None:
        token = str(data.get("token") or "").strip()
        base_url = str(data.get("baseUrl") or data.get("base_url") or "").strip()
        if not token or not base_url:
            return None
        return cls(
            token=token,
            base_url=base_url.rstrip("/"),
            bot_id=str_or_none(data.get("botId") or data.get("ilink_bot_id")),
            user_id=str_or_none(data.get("userId") or data.get("ilink_user_id")),
            saved_at=float(data.get("savedAt") or 0.0),
        )


@dataclass
class WeChatState:
    cursor: str = ""
    context_tokens: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> WeChatState:
        raw_tokens = data.get("context_tokens") or {}
        tokens = {
            str(key): str(value)
            for key, value in raw_tokens.items()
            if isinstance(value, str) and value
        }
        return cls(cursor=str(data.get("cursor") or ""), context_tokens=tokens)


def str_or_none(value: Any) -> str | None:
    text = str(value).strip() if value is not None else ""
    return text or None

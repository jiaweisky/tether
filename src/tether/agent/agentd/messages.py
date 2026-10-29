"""Translate agentd transcript messages into backend-neutral snapshots."""

from __future__ import annotations

from tether.models import RichMedia


def current_turn_messages(messages: list[dict]) -> list[dict]:
    """Messages after the latest user message (or the whole list if none)."""
    last_user = -1
    for index, message in enumerate(messages):
        if message.get("type") == "user":
            last_user = index

    return messages[last_user + 1 :] if last_user >= 0 else messages


def assistant_text(messages: list[dict]) -> str | None:
    """Final text of the latest assistant message in a transcript."""
    for message in reversed(messages):
        if message.get("type") != "assistant":
            continue

        parts = [
            str(part.get("text", ""))
            for part in (message.get("content") or [])
            if part.get("type") == "text"
        ]

        text = "".join(parts)
        if text:
            return text

    return None


def tool_media(messages: list[dict]) -> list[RichMedia]:
    """File parts produced by tool calls within a transcript."""
    from tether.engine.media_egress import extract_file_parts

    out: list[RichMedia] = []
    for message in messages:
        if message.get("type") != "assistant":
            continue

        for part in message.get("content") or []:
            if part.get("type") != "tool":
                continue

            state = part.get("state") or {}
            out.extend(extract_file_parts(state.get("content")))
            out.extend(extract_file_parts(state.get("attachments")))

    return out


def snapshot_messages(
    messages: list[dict], *, after_message_id: str | None = None
) -> tuple[str | None, list[RichMedia]]:
    if after_message_id:
        index = next(
            (
                i
                for i, message in enumerate(messages)
                if str(message.get("id", "")) == after_message_id
            ),
            -1,
        )
        current = messages[index + 1 :] if index >= 0 else current_turn_messages(messages)
    else:
        current = current_turn_messages(messages)

    return assistant_text(current), tool_media(current)


__all__ = [
    "assistant_text",
    "current_turn_messages",
    "snapshot_messages",
    "tool_media",
]

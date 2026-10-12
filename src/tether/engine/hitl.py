"""Build the interactive artifacts for permissions and questions.

A permission or question is presented either as a button card (when the channel
supports buttons) or as a numbered text prompt, and a clicked button is decoded
back into the action to send to the agent.
"""

from __future__ import annotations

import json
from typing import Any, Literal

from ..agent.events import PendingPermission, PendingQuestion
from ..config import Config
from ..models import (
    Button,
    Card,
    Conversation,
    PendingInteraction,
    Sender,
)


def encode_value(kind: str, sid: str, rid: str, **extra: Any) -> str:
    """Encode a button payload that carries the session, request and action."""
    payload = {"kind": kind, "sid": sid, "rid": rid, **extra}
    return json.dumps(payload, separators=(",", ":"))


def decode_value(value: str) -> dict[str, Any] | None:
    """Decode a button payload, returning ``None`` when it is not ours."""
    try:
        data = json.loads(value)
    except ValueError:
        return None
    return data if isinstance(data, dict) and "kind" in data else None


def permission_card(perm: PendingPermission) -> Card:
    resources = ", ".join(perm.resources) if perm.resources else "(all)"
    body = f"Tool `{perm.action}` requests access to: {resources}"
    buttons = [
        Button(
            text="Allow once",
            value=encode_value("permission", perm.session_id, perm.id, reply="once"),
        ),
        Button(
            text="Always allow",
            value=encode_value("permission", perm.session_id, perm.id, reply="always"),
            style="primary",
        ),
        Button(
            text="Deny",
            value=encode_value("permission", perm.session_id, perm.id, reply="reject"),
            style="danger",
        ),
    ]
    return Card(title="⚠️ Permission required", body=body, buttons=buttons)


def question_card(question: PendingQuestion) -> Card | None:
    """Build a button card for a single-choice question.

    Returns ``None`` for multi-select questions, which fall back to a numbered
    text prompt because the platform cannot express the choice as buttons.
    """
    if not question.questions:
        return None
    first = question.questions[0]
    if first.multiple:
        return None
    buttons = [
        Button(
            text=option.label or f"Option {i + 1}",
            value=encode_value("question", question.session_id, question.id, answer=[option.label]),
        )
        for i, option in enumerate(first.options)
    ]
    buttons.append(
        Button(
            text="Cancel",
            value=encode_value("question", question.session_id, question.id, reject=True),
            style="danger",
        )
    )
    body = first.question or first.header or "Please choose an option."
    return Card(title=first.header or "Question", body=body, buttons=buttons)


def question_numbered_text(question: PendingQuestion) -> tuple[str, list[str]]:
    """Render a question as numbered options and return the ordered labels."""
    lines: list[str] = []
    labels: list[str] = []
    for item in question.questions:
        lines.append(item.question or item.header)
        for index, option in enumerate(item.options):
            lines.append(f"{index + 1}. {option.label}")
            labels.append(option.label)
    return "\n".join(lines), labels


def make_pending(
    kind: Literal["permission", "question"],
    *,
    owner: str | None,
    scope: str,
    request_id: str,
    options: list[str] | None = None,
) -> PendingInteraction:
    return PendingInteraction(
        kind=kind, owner=owner, scope=scope, request_id=request_id, options=options or []
    )


def is_authorized(
    pending: PendingInteraction,
    sender: Sender,
    conv: Conversation,
    config: Config,
    *,
    active_turn_sender: str | None,
) -> bool:
    """Whether ``sender`` may answer a pending interaction in this conversation."""
    if not conv.is_group:
        return True
    if pending.scope == "participants":
        return True
    if pending.scope == "admins":
        return sender.id in config.group.admins
    owner = pending.owner or active_turn_sender
    return owner is None or sender.id == owner


def command_authorized(
    sender: Sender,
    conv: Conversation,
    config: Config,
    *,
    active_turn_sender: str | None,
) -> bool:
    """Whether ``sender`` may run the stop command against the current turn."""
    if not conv.is_group:
        return True
    if config.group.command_scope == "admins":
        return sender.id in config.group.admins
    if active_turn_sender is None:
        return True
    return sender.id == active_turn_sender

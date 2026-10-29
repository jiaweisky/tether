"""Map go-agent-sdk/agentd native events to the backend-neutral vocabulary."""

from __future__ import annotations

from typing import Any

from tether.agent.events import (
    ATTACHMENT_OMITTED,
    COMPACTION_DELTA,
    COMPACTION_ENDED,
    COMPACTION_STARTED,
    PERMISSION_ASKED,
    PERMISSION_REPLIED,
    QUESTION_ASKED,
    QUESTION_REJECTED,
    QUESTION_REPLIED,
    REASONING_DELTA,
    REASONING_ENDED,
    REASONING_STARTED,
    SERVER_CONNECTED,
    STEP_ENDED,
    STEP_FAILED,
    STEP_STARTED,
    TEXT_DELTA,
    TEXT_ENDED,
    TEXT_STARTED,
    TITLE_UPDATED,
    TOOL_CALLED,
    TOOL_FAILED,
    TOOL_PROGRESS,
    TOOL_SUCCESS,
    TURN_STATUS,
    Event,
)

AGENTD_EVENT_MAP: dict[str, str] = {
    "server.connected": SERVER_CONNECTED,
    "session.status": TURN_STATUS,
    "session.next.text.started": TEXT_STARTED,
    "session.next.text.delta": TEXT_DELTA,
    "session.next.text.ended": TEXT_ENDED,
    "session.next.reasoning.started": REASONING_STARTED,
    "session.next.reasoning.delta": REASONING_DELTA,
    "session.next.reasoning.ended": REASONING_ENDED,
    "session.next.tool.called": TOOL_CALLED,
    "session.next.tool.progress": TOOL_PROGRESS,
    "session.next.tool.success": TOOL_SUCCESS,
    "session.next.tool.failed": TOOL_FAILED,
    "session.next.step.started": STEP_STARTED,
    "session.next.step.ended": STEP_ENDED,
    "session.next.step.failed": STEP_FAILED,
    "session.next.attachment.omitted": ATTACHMENT_OMITTED,
    "session.next.title.updated": TITLE_UPDATED,
    "session.next.compaction.started": COMPACTION_STARTED,
    "session.next.compaction.ended": COMPACTION_ENDED,
    "session.next.compaction.delta": COMPACTION_DELTA,
    "permission.v2.asked": PERMISSION_ASKED,
    "permission.v2.replied": PERMISSION_REPLIED,
    "question.v2.asked": QUESTION_ASKED,
    "question.v2.replied": QUESTION_REPLIED,
    "question.v2.rejected": QUESTION_REJECTED,
}


def from_agentd_event(data: dict[str, Any]) -> Event | None:
    if not isinstance(data, dict):
        return None

    native_type = str(data.get("type", ""))
    event_type = AGENTD_EVENT_MAP.get(native_type, native_type)
    payload = dict(data.get("data") or {})
    durable = data.get("durable")
    session_id = _session_id(payload, durable)
    return Event(
        id=str(data.get("id", "")),
        type=event_type,
        data=payload,
        durable=durable,
        session_id=session_id,
    )


def _session_id(payload: dict[str, Any], durable: Any) -> str | None:
    for key in ("sessionID", "session_id", "sessionId"):
        if payload.get(key):
            return str(payload[key])
    if isinstance(durable, dict) and durable.get("aggregateID"):
        return str(durable["aggregateID"])
    return None


__all__ = ["AGENTD_EVENT_MAP", "from_agentd_event"]

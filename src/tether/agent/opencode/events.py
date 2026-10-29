"""Map OpenCode v1/v2 native events to Tether's neutral event vocabulary."""

from __future__ import annotations

from typing import Any

from tether.agent.events import (
    COMPACTION_DELTA,
    COMPACTION_ENDED,
    COMPACTION_STARTED,
    FORM_ASKED,
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
from tether.agent.opencode.forms import form_to_question, form_to_spec

OPENCODE_V2_EVENT_MAP: dict[str, str] = {
    "server.connected": SERVER_CONNECTED,
    "session.execution.started": TURN_STATUS,
    "session.execution.succeeded": TURN_STATUS,
    "session.execution.failed": TURN_STATUS,
    "session.execution.interrupted": TURN_STATUS,
    "session.status": TURN_STATUS,
    "session.idle": TURN_STATUS,
    "session.retry.scheduled": TURN_STATUS,
    "session.text.started": TEXT_STARTED,
    "session.text.delta": TEXT_DELTA,
    "session.text.ended": TEXT_ENDED,
    "session.reasoning.started": REASONING_STARTED,
    "session.reasoning.delta": REASONING_DELTA,
    "session.reasoning.ended": REASONING_ENDED,
    "session.step.started": STEP_STARTED,
    "session.step.ended": STEP_ENDED,
    "session.step.failed": STEP_FAILED,
    "session.tool.input.started": TOOL_CALLED,
    "session.tool.called": TOOL_CALLED,
    "session.tool.progress": TOOL_PROGRESS,
    "session.tool.success": TOOL_SUCCESS,
    "session.tool.failed": TOOL_FAILED,
    "session.compaction.started": COMPACTION_STARTED,
    "session.compaction.delta": COMPACTION_DELTA,
    "session.compaction.ended": COMPACTION_ENDED,
    "session.renamed": TITLE_UPDATED,
    "permission.asked": PERMISSION_ASKED,
    "permission.replied": PERMISSION_REPLIED,
    "form.created": QUESTION_ASKED,
    "form.replied": QUESTION_REPLIED,
    "form.cancelled": QUESTION_REJECTED,
}

OPENCODE_V1_EVENT_MAP: dict[str, str] = {
    "server.connected": SERVER_CONNECTED,
    "session.status": TURN_STATUS,
    "session.idle": TURN_STATUS,
    "session.next.retried": TURN_STATUS,
    "session.next.text.started": TEXT_STARTED,
    "session.next.text.delta": TEXT_DELTA,
    "session.next.text.ended": TEXT_ENDED,
    "session.next.reasoning.started": REASONING_STARTED,
    "session.next.reasoning.delta": REASONING_DELTA,
    "session.next.reasoning.ended": REASONING_ENDED,
    "session.next.step.started": STEP_STARTED,
    "session.next.step.ended": STEP_ENDED,
    "session.next.step.failed": STEP_FAILED,
    "session.next.tool.input.started": TOOL_CALLED,
    "session.next.tool.called": TOOL_CALLED,
    "session.next.tool.progress": TOOL_PROGRESS,
    "session.next.tool.success": TOOL_SUCCESS,
    "session.next.tool.failed": TOOL_FAILED,
    "session.next.compaction.started": COMPACTION_STARTED,
    "session.next.compaction.delta": COMPACTION_DELTA,
    "session.next.compaction.ended": COMPACTION_ENDED,
    "permission.v2.asked": PERMISSION_ASKED,
    "permission.v2.replied": PERMISSION_REPLIED,
    "question.v2.asked": QUESTION_ASKED,
    "question.v2.replied": QUESTION_REPLIED,
    "question.v2.rejected": QUESTION_REJECTED,
}

_TURN_END = {
    "session.execution.succeeded",
    "session.execution.failed",
    "session.execution.interrupted",
    "session.idle",
}
_TEXT_EVENTS = {
    TEXT_STARTED,
    TEXT_DELTA,
    TEXT_ENDED,
    REASONING_STARTED,
    REASONING_DELTA,
    REASONING_ENDED,
}


class OpenCodeEventMapper:
    """Stateful mapper for text-part aggregation and tool name completion."""

    synthesize_idle_on_step_end = False

    def __init__(
        self,
        event_map: dict[str, str] | None = None,
        *,
        supports_forms: bool = True,
    ) -> None:
        self.event_map = event_map or OPENCODE_V2_EVENT_MAP
        self.supports_forms = supports_forms
        self._text: dict[str, dict[tuple[str, str], str]] = {}
        self._reasoning: dict[str, dict[tuple[str, str], str]] = {}
        self._tool_names: dict[tuple[str, str, str], str] = {}

    def map_many(self, raw: dict[str, Any]) -> list[Event]:
        event = self.map(raw)
        if event is None:
            return []

        events = [event]
        data = raw.get("data") if isinstance(raw, dict) else None
        data = data if isinstance(data, dict) else {}

        if self.synthesize_idle_on_step_end and event.type == STEP_FAILED:
            events.append(_idle_event(event, raw))
        elif self.synthesize_idle_on_step_end and event.type == STEP_ENDED:
            # v1 does not publish session.status on every deployment. A step
            # ending with tool calls continues the turn; any other finish ends it.
            if str(data.get("finish") or "") != "tool-calls":
                events.append(_idle_event(event, raw))

        return events

    def map(self, raw: dict[str, Any]) -> Event | None:
        if not isinstance(raw, dict):
            return None

        native_type = str(raw.get("type") or "")
        data = raw.get("data") or {}
        if not isinstance(data, dict):
            data = {}

        event_type = self.event_map.get(native_type, native_type)
        session_id = self._session_id(native_type, data)
        payload: dict[str, Any]

        if event_type in (TEXT_STARTED, TEXT_DELTA, TEXT_ENDED):
            payload = self._text_payload(event_type, session_id, data, self._text)
        elif event_type in (REASONING_STARTED, REASONING_DELTA, REASONING_ENDED):
            payload = self._text_payload(event_type, session_id, data, self._reasoning)
        elif event_type == STEP_ENDED:
            payload = {
                "tokens": data.get("tokens"),
                "cost": data.get("cost"),
                "files": list(data.get("files") or []),
            }
        elif event_type == STEP_FAILED:
            payload = {"error": data.get("error")}
        elif event_type == TOOL_CALLED:
            payload = self._tool_called(session_id, data)
        elif event_type in (TOOL_PROGRESS, TOOL_SUCCESS):
            payload = {
                "content": list(data.get("content") or []),
                "structured": {"files": []},
            }
        elif event_type == TOOL_FAILED:
            payload = {"error": data.get("error")}
        elif event_type == TURN_STATUS:
            payload = self._turn_status(native_type, session_id, data)
        elif event_type == PERMISSION_ASKED:
            payload = dict(data)
        elif event_type == PERMISSION_REPLIED:
            payload = {"requestID": data.get("requestID"), "reply": data.get("reply")}
        elif event_type == QUESTION_ASKED:
            question_payload = self._question_asked(native_type, data)
            if question_payload is None:
                return None
            if isinstance(question_payload, tuple):
                event_type, payload = question_payload
            else:
                payload = question_payload
        elif event_type in (QUESTION_REPLIED, QUESTION_REJECTED):
            payload = {"requestID": data.get("requestID") or data.get("id")}
            session_id = str(data.get("sessionID") or session_id or "") or None
        elif event_type == COMPACTION_DELTA:
            payload = {"delta": data.get("text") or data.get("delta") or ""}
        elif event_type == COMPACTION_ENDED:
            payload = {}
        elif event_type == TITLE_UPDATED:
            payload = {"title": data.get("title") or ""}
        else:
            payload = dict(data)

        return Event(
            id=str(raw.get("id") or ""),
            type=event_type,
            data=payload,
            durable=raw.get("durable"),
            session_id=session_id,
        )

    def _turn_status(
        self, native_type: str, session_id: str | None, data: dict[str, Any]
    ) -> dict[str, Any]:
        if native_type in _TURN_END:
            self._clear_turn(session_id)
            return {"status": {"type": "idle"}}

        if native_type == "session.execution.started":
            return {"status": {"type": "busy"}}

        if native_type in ("session.retry.scheduled", "session.next.retried"):
            return {
                "status": {
                    "type": "retry",
                    "attempt": data.get("attempt"),
                    "next": data.get("at"),
                    "message": _error_text(data.get("error")),
                }
            }

        if native_type == "session.status":
            status = data.get("status") or data
            if isinstance(status, dict) and status.get("type") == "idle":
                self._clear_turn(session_id)
            return {"status": status}

        return {"status": data.get("status") or data}

    def _question_asked(
        self, native_type: str, data: dict[str, Any]
    ) -> dict[str, Any] | tuple[str, dict[str, Any]] | None:
        if native_type.startswith("form."):
            form_value = data.get("form")
            form: dict[str, Any] = form_value if isinstance(form_value, dict) else {}

            request = form_to_question(form)
            if request is None:
                if not self.supports_forms:
                    return None

                return FORM_ASKED, {"form": form_to_spec(form)}

            return {"request": request}

        return dict(data)

    def _text_payload(
        self,
        event_type: str,
        session_id: str | None,
        data: dict[str, Any],
        store: dict[str, dict[tuple[str, str], str]],
    ) -> dict[str, Any]:
        sid = session_id or ""
        message_id = str(data.get("assistantMessageID") or "")
        part_id = str(data.get("textID") or data.get("reasoningID") or data.get("ordinal") or "0")

        if event_type in (TEXT_STARTED, REASONING_STARTED):
            return {"ordinal": _int_or_none(part_id)}

        if event_type in (TEXT_DELTA, REASONING_DELTA):
            return {"delta": str(data.get("delta") or ""), "ordinal": _int_or_none(part_id)}

        parts = store.setdefault(sid, {})
        parts[(message_id, part_id)] = str(data.get("text") or "")
        complete = "".join(value for _, value in sorted(parts.items()))

        return {"text": complete, "ordinal": _int_or_none(part_id)}

    def _tool_called(self, session_id: str | None, data: dict[str, Any]) -> dict[str, Any]:
        key = (
            session_id or "",
            str(data.get("assistantMessageID") or ""),
            str(data.get("callID") or data.get("id") or ""),
        )

        name = str(data.get("name") or "")
        if name:
            self._tool_names[key] = name
        else:
            name = self._tool_names.get(key, "")

        return {"name": name, "toolID": key[2]}

    def _clear_turn(self, session_id: str | None) -> None:
        sid = session_id or ""
        self._text.pop(sid, None)
        self._reasoning.pop(sid, None)

        for key in [key for key in self._tool_names if key[0] == sid]:
            self._tool_names.pop(key, None)

    @staticmethod
    def _session_id(native_type: str, data: dict[str, Any]) -> str | None:
        if native_type.startswith("form."):
            form_value = data.get("form")
            form: dict[str, Any] = form_value if isinstance(form_value, dict) else {}
            sid = form.get("sessionID") or data.get("sessionID")
        else:
            sid = data.get("sessionID")

        return str(sid) if sid else None


class OpenCodeV1EventMapper(OpenCodeEventMapper):
    synthesize_idle_on_step_end = True

    def __init__(self) -> None:
        super().__init__(OPENCODE_V1_EVENT_MAP, supports_forms=False)


class OpenCodeV2EventMapper(OpenCodeEventMapper):
    def __init__(self) -> None:
        super().__init__(OPENCODE_V2_EVENT_MAP, supports_forms=True)


def _idle_event(event: Event, raw: dict[str, Any]) -> Event:
    return Event(
        id=f"{event.id}:idle",
        type=TURN_STATUS,
        data={"status": {"type": "idle"}},
        durable=raw.get("durable"),
        session_id=event.session_id,
    )


def _int_or_none(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None

    try:
        return int(value)
    except ValueError:
        return None


def _error_text(value: Any) -> str | None:
    if value is None:
        return None

    if isinstance(value, dict):
        return str(value.get("message") or value.get("type") or value)

    return str(value)


__all__ = [
    "OPENCODE_V1_EVENT_MAP",
    "OPENCODE_V2_EVENT_MAP",
    "OpenCodeEventMapper",
    "OpenCodeV1EventMapper",
    "OpenCodeV2EventMapper",
]

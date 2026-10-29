"""Data types for the agent's SSE event stream and discovery endpoints."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal

# Backend-neutral session event names.
TEXT_STARTED = "text.started"
TEXT_DELTA = "text.delta"
TEXT_ENDED = "text.ended"
REASONING_STARTED = "reasoning.started"
REASONING_DELTA = "reasoning.delta"
REASONING_ENDED = "reasoning.ended"
TOOL_CALLED = "tool.called"
TOOL_PROGRESS = "tool.progress"
TOOL_SUCCESS = "tool.success"
TOOL_FAILED = "tool.failed"
STEP_STARTED = "step.started"
STEP_ENDED = "step.ended"
STEP_FAILED = "step.failed"
ATTACHMENT_OMITTED = "attachment.omitted"
TITLE_UPDATED = "title.updated"
COMPACTION_STARTED = "compaction.started"
COMPACTION_ENDED = "compaction.ended"
COMPACTION_DELTA = "compaction.delta"
TURN_STATUS = "turn.status"
SESSION_STATUS = TURN_STATUS
SERVER_CONNECTED = "server.connected"
PERMISSION_ASKED = "permission.asked"
PERMISSION_REPLIED = "permission.replied"
QUESTION_ASKED = "question.asked"
QUESTION_REPLIED = "question.replied"
QUESTION_REJECTED = "question.rejected"
FORM_ASKED = "form.asked"


@dataclass
class Event:
    id: str
    type: str
    data: Any = field(default_factory=dict)
    durable: dict[str, Any] | None = None
    session_id: str | None = None

    def __post_init__(self) -> None:
        raw: Any = self.data
        sid = self.session_id
        if sid is None and isinstance(raw, dict):
            sid = raw.get("sessionID")
            if not sid:
                for key in ("session_id", "sessionId"):
                    if raw.get(key):
                        sid = raw[key]
                        break
        if not sid and self.durable and self.durable.get("aggregateID"):
            sid = self.durable["aggregateID"]
        if sid:
            self.session_id = str(sid)

        self.data = coerce_event_data(self.type, raw, self.session_id)


def event_seq(event: Event) -> int | None:
    """The durable aggregate sequence, when the event has one."""
    durable = event.durable if isinstance(event.durable, dict) else None
    if durable is None:
        return None

    value = durable.get("seq")
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None

    try:
        return int(value)
    except ValueError:
        return None


@dataclass
class AgentInfo:
    id: str
    description: str | None = None
    mode: str | None = None
    hidden: bool = False
    model: str | None = None
    backend: str | None = None


@dataclass
class ModelInfo:
    id: str
    protocol: str | None = None
    inputs: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    context_limit: int | None = None
    output_limit: int | None = None


@dataclass
class ToolInfo:
    name: str
    description: str | None = None


@dataclass
class SessionInfo:
    id: str
    agent: str | None = None
    model: str | None = None
    title: str | None = None
    location: str | None = None


@dataclass
class PendingPermission:
    id: str
    session_id: str
    action: str
    resources: list[str] = field(default_factory=list)
    save: list[str] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
    source: dict[str, Any] | None = None

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> PendingPermission:
        return cls(
            id=str(raw.get("id", "")),
            session_id=str(raw.get("sessionID", "")),
            action=str(raw.get("action", "")),
            resources=list(raw.get("resources") or []),
            save=list(raw.get("save") or []),
            metadata=dict(raw.get("metadata") or {}),
            source=raw.get("source"),
        )


@dataclass
class QuestionOption:
    label: str
    value: str
    description: str = ""


@dataclass
class QuestionItem:
    key: str
    question: str
    header: str = ""
    options: list[QuestionOption] = field(default_factory=list)
    multiple: bool = False
    custom: bool = False


@dataclass
class PendingQuestion:
    id: str
    session_id: str
    questions: list[QuestionItem] = field(default_factory=list)
    tool: dict[str, Any] | None = None

    @classmethod
    def from_json(cls, raw: dict[str, Any]) -> PendingQuestion:
        questions: list[QuestionItem] = []
        for q in raw.get("questions") or []:
            question = str(q.get("question", ""))
            questions.append(
                QuestionItem(
                    key=str(q.get("key") or q.get("header") or question),
                    question=question,
                    header=str(q.get("header", "")),
                    options=[
                        QuestionOption(
                            label=str(o.get("label", "")),
                            value=str(o.get("value") or o.get("label", "")),
                            description=str(o.get("description", "")),
                        )
                        for o in (q.get("options") or [])
                    ],
                    multiple=bool(q.get("multiple")),
                    custom=bool(q.get("custom")),
                )
            )

        return cls(
            id=str(raw.get("id", "")),
            session_id=str(raw.get("sessionID", "")),
            questions=questions,
            tool=raw.get("tool"),
        )


# -- typed event payloads -------------------------------------------------
@dataclass(frozen=True)
class EmptyData:
    pass


@dataclass(frozen=True)
class RawData:
    values: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TextData:
    delta: str = ""
    text: str | None = None
    ordinal: int | None = None


@dataclass(frozen=True)
class ErrorData:
    error: str = ""


@dataclass(frozen=True)
class ToolCalledData:
    name: str = ""
    tool_id: str | None = None


@dataclass(frozen=True)
class TextPart:
    text: str


@dataclass(frozen=True)
class FilePart:
    uri: str
    mime: str | None = None
    name: str | None = None


ToolPart = TextPart | FilePart


@dataclass(frozen=True)
class ToolStructured:
    files: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ToolData:
    content: list[ToolPart] = field(default_factory=list)
    structured: ToolStructured = field(default_factory=ToolStructured)


@dataclass(frozen=True)
class StatusInfo:
    type: Literal["idle", "busy", "retry"] | str = "idle"
    attempt: int | None = None
    message: str | None = None
    next: int | None = None


@dataclass(frozen=True)
class TurnStatusData:
    status: StatusInfo


@dataclass(frozen=True)
class StepEndedData:
    tokens: dict[str, Any] | None = None
    cost: float | None = None
    files: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class PermissionAskedData:
    request: PendingPermission


@dataclass(frozen=True)
class PermissionRepliedData:
    request_id: str = ""
    reply: str = ""


@dataclass(frozen=True)
class QuestionAskedData:
    request: PendingQuestion


@dataclass(frozen=True)
class QuestionClosedData:
    request_id: str = ""


@dataclass(frozen=True)
class FormAskedData:
    form: Any


@dataclass(frozen=True)
class AttachmentOmittedData:
    name: str = "attachment"
    reason: str = "unsupported"
    detail: str | None = None


@dataclass(frozen=True)
class TitleUpdatedData:
    title: str = ""


EventData = (
    EmptyData
    | RawData
    | TextData
    | ErrorData
    | ToolCalledData
    | ToolData
    | TurnStatusData
    | StepEndedData
    | PermissionAskedData
    | PermissionRepliedData
    | QuestionAskedData
    | QuestionClosedData
    | FormAskedData
    | AttachmentOmittedData
    | TitleUpdatedData
)

_TEXT_EVENTS = {
    TEXT_STARTED,
    TEXT_DELTA,
    TEXT_ENDED,
    REASONING_STARTED,
    REASONING_DELTA,
    REASONING_ENDED,
}


def coerce_event_data(event_type: str, raw: Any, session_id: str | None = None) -> EventData:
    if isinstance(
        raw,
        (
            EmptyData,
            RawData,
            TextData,
            ErrorData,
            ToolCalledData,
            ToolData,
            TurnStatusData,
            StepEndedData,
            PermissionAskedData,
            PermissionRepliedData,
            QuestionAskedData,
            QuestionClosedData,
            FormAskedData,
            AttachmentOmittedData,
            TitleUpdatedData,
        ),
    ):
        return raw

    data: dict[str, Any] = raw if isinstance(raw, dict) else {}

    if event_type in _TEXT_EVENTS:
        return TextData(
            delta=str(data.get("delta", "")),
            text=_optional_str(data.get("text")),
            ordinal=_optional_int(data.get("ordinal")),
        )
    if event_type == COMPACTION_DELTA:
        return TextData(delta=str(data.get("delta", "")), text=_optional_str(data.get("text")))
    if event_type == TOOL_CALLED:
        return ToolCalledData(
            name=str(data.get("name") or data.get("tool") or ""),
            tool_id=_optional_str(data.get("toolID") or data.get("tool_id")),
        )
    if event_type in (TOOL_PROGRESS, TOOL_SUCCESS):
        files = _structured_files(data.get("structured"))
        files.extend(str(path) for path in (data.get("outputPaths") or []) if str(path))
        return ToolData(
            content=_parts(data.get("content")),
            structured=ToolStructured(files=files),
        )
    if event_type in (TOOL_FAILED, STEP_FAILED):
        return ErrorData(error=_error_text(data.get("error")))
    if event_type == STEP_ENDED:
        tokens = data.get("tokens")
        cost = data.get("cost")
        numeric_cost = (
            float(cost)
            if isinstance(cost, (int, float)) and not isinstance(cost, bool)
            else None
        )
        return StepEndedData(
            tokens=tokens if isinstance(tokens, dict) else None,
            cost=numeric_cost,
            files=[str(path) for path in (data.get("files") or []) if str(path)],
        )
    if event_type == TURN_STATUS:
        return TurnStatusData(status=_status(data.get("status")))
    if event_type == PERMISSION_ASKED:
        request = data.get("request")
        if isinstance(request, PendingPermission):
            return PermissionAskedData(request=request)
        payload = dict(data)
        payload.setdefault("sessionID", session_id or "")
        return PermissionAskedData(request=PendingPermission.from_json(payload))
    if event_type == PERMISSION_REPLIED:
        return PermissionRepliedData(
            request_id=str(data.get("requestID") or data.get("request_id") or ""),
            reply=str(data.get("reply") or ""),
        )
    if event_type == QUESTION_ASKED:
        request = data.get("request")
        if isinstance(request, PendingQuestion):
            return QuestionAskedData(request=request)
        payload = dict(data)
        payload.setdefault("sessionID", session_id or "")
        return QuestionAskedData(request=PendingQuestion.from_json(payload))
    if event_type in (QUESTION_REPLIED, QUESTION_REJECTED):
        return QuestionClosedData(
            request_id=str(data.get("requestID") or data.get("request_id") or "")
        )
    if event_type == FORM_ASKED:
        return FormAskedData(form=data.get("form") or data)
    if event_type == ATTACHMENT_OMITTED:
        return AttachmentOmittedData(
            name=str(data.get("name") or "attachment"),
            reason=str(data.get("reason") or "unsupported"),
            detail=_optional_str(data.get("detail")),
        )
    if event_type == TITLE_UPDATED:
        return TitleUpdatedData(title=str(data.get("title") or ""))
    if event_type in (SERVER_CONNECTED, STEP_STARTED, COMPACTION_STARTED, COMPACTION_ENDED):
        return EmptyData()
    return RawData(values=dict(data))


def _optional_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _optional_str(value: Any) -> str | None:
    return str(value) if value is not None else None


def _error_text(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("message") or value.get("type") or "error")
    return str(value)


def _status(value: Any) -> StatusInfo:
    if not isinstance(value, dict):
        return StatusInfo()
    return StatusInfo(
        type=str(value.get("type") or "idle"),
        attempt=_optional_int(value.get("attempt")),
        message=_optional_str(value.get("message")),
        next=_optional_int(value.get("next")),
    )


def _parts(value: Any) -> list[ToolPart]:
    parts: list[ToolPart] = []
    for node in value if isinstance(value, list) else []:
        if not isinstance(node, dict):
            continue
        is_file = node.get("type") == "file" or (
            "uri" in node and ("mime" in node or "mediaSource" in node)
        )
        if is_file:
            parts.append(
                FilePart(
                    uri=str(node.get("uri") or ""),
                    mime=_optional_str(node.get("mime")),
                    name=_optional_str(node.get("name")),
                )
            )
        elif node.get("text") is not None:
            parts.append(TextPart(text=str(node["text"])))
    return parts


def _structured_files(value: Any) -> list[str]:
    if not isinstance(value, dict):
        return []
    out: list[str] = []
    files = value.get("files")
    if isinstance(files, list):
        for item in files:
            path: Any
            if isinstance(item, str):
                path = item
            elif isinstance(item, dict):
                path = item.get("file")
            else:
                path = None
            if isinstance(path, str) and path:
                out.append(path)
    if value.get("operation") in ("write", "edit"):
        for key in ("resource", "target"):
            path = value.get(key)
            if isinstance(path, str) and path:
                out.append(path)
    return out


__all__ = [
    "AttachmentOmittedData",
    "EmptyData",
    "ErrorData",
    "Event",
    "EventData",
    "FilePart",
    "FormAskedData",
    "PermissionAskedData",
    "PermissionRepliedData",
    "QuestionAskedData",
    "QuestionClosedData",
    "RawData",
    "StatusInfo",
    "StepEndedData",
    "TextData",
    "TextPart",
    "TitleUpdatedData",
    "ToolCalledData",
    "ToolData",
    "ToolPart",
    "ToolStructured",
    "TurnStatusData",
    "coerce_event_data",
    "event_seq",
]

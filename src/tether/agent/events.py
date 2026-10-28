"""Data types for the agent's SSE event stream and discovery endpoints."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# Session event type names emitted on the agent's event stream.
TEXT_STARTED = "session.next.text.started"
TEXT_DELTA = "session.next.text.delta"
TEXT_ENDED = "session.next.text.ended"
REASONING_STARTED = "session.next.reasoning.started"
REASONING_DELTA = "session.next.reasoning.delta"
REASONING_ENDED = "session.next.reasoning.ended"
TOOL_CALLED = "session.next.tool.called"
TOOL_PROGRESS = "session.next.tool.progress"
TOOL_SUCCESS = "session.next.tool.success"
TOOL_FAILED = "session.next.tool.failed"
STEP_STARTED = "session.next.step.started"
STEP_ENDED = "session.next.step.ended"
STEP_FAILED = "session.next.step.failed"
ATTACHMENT_OMITTED = "session.next.attachment.omitted"
TITLE_UPDATED = "session.next.title.updated"
COMPACTION_STARTED = "session.next.compaction.started"
COMPACTION_ENDED = "session.next.compaction.ended"
COMPACTION_DELTA = "session.next.compaction.delta"
SESSION_STATUS = "session.status"
SERVER_CONNECTED = "server.connected"
PERMISSION_ASKED = "permission.v2.asked"
PERMISSION_REPLIED = "permission.v2.replied"
QUESTION_ASKED = "question.v2.asked"
QUESTION_REPLIED = "question.v2.replied"
QUESTION_REJECTED = "question.v2.rejected"


@dataclass
class Event:
    id: str
    type: str
    data: dict[str, Any] = field(default_factory=dict)
    durable: dict[str, Any] | None = None

    @property
    def session_id(self) -> str | None:
        data = self.data or {}

        sid = data.get("sessionID")
        if sid:
            return str(sid)

        for key in ("session_id", "sessionId"):
            if data.get(key):
                return str(data[key])

        if self.durable and self.durable.get("aggregateID"):
            return str(self.durable["aggregateID"])

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
    description: str = ""


@dataclass
class QuestionItem:
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
            questions.append(
                QuestionItem(
                    question=str(q.get("question", "")),
                    header=str(q.get("header", "")),
                    options=[
                        QuestionOption(
                            label=str(o.get("label", "")),
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

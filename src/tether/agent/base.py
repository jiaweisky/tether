"""Backend-neutral port and DTOs for the agent service."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from dataclasses import dataclass, field
from typing import Any, Protocol

from tether.agent.events import (
    AgentInfo,
    Event,
    ModelInfo,
    PendingPermission,
    PendingQuestion,
    SessionInfo,
    ToolInfo,
)
from tether.models import RichMedia


@dataclass(frozen=True)
class BackendProfile:
    backend_id: str
    display_name: str
    supports_tool_discovery: bool
    supports_session_replay: bool
    supports_cross_session_permissions: bool
    supports_cross_session_questions: bool
    supports_rich_forms: bool
    supports_session_wait: bool
    supports_session_title: bool
    supports_isolated_projects: bool
    supports_multi_location: bool
    supports_changed_files: bool
    supports_pending_interaction_recovery: bool
    event_protocol: str


@dataclass
class ConfigSummary:
    default_agent: str | None = None
    default_model: str | None = None
    providers: list[str] = field(default_factory=list)
    agents: int = 0
    models: int = 0
    locations: list[str] = field(default_factory=list)


@dataclass
class BackendDescription:
    backend_id: str
    endpoint_id: str
    version: str | None = None
    pid: int | None = None
    urls: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    detail: ConfigSummary | None = None


@dataclass(frozen=True)
class PromptFile:
    uri: str
    name: str | None = None
    mime: str | None = None
    description: str | None = None


@dataclass(frozen=True)
class PermissionRule:
    action: str
    resource: str = "*"
    effect: str = "ask"


@dataclass
class QuestionAnswer:
    values: dict[str, list[str]] = field(default_factory=dict)


@dataclass(frozen=True)
class FormOption:
    value: str
    label: str
    description: str | None = None


@dataclass(frozen=True)
class FormField:
    key: str
    type: str
    title: str | None = None
    description: str | None = None
    required: bool = False
    hidden: bool = False
    custom: bool = False
    default: Any = None
    options: list[FormOption] = field(default_factory=list)
    when: list[dict[str, Any]] = field(default_factory=list)


@dataclass(frozen=True)
class FormSpec:
    id: str
    session_id: str
    title: str
    fields: list[FormField] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass
class FormAnswer:
    values: dict[str, Any] = field(default_factory=dict)


@dataclass
class TurnSnapshot:
    turn_id: str | None = None
    text: str | None = None
    media: list[RichMedia] = field(default_factory=list)


class AgentBackend(Protocol):
    endpoint_id: str
    profile: BackendProfile

    async def aclose(self) -> None: ...

    # discovery / metadata
    async def health(self) -> bool: ...
    async def describe(self) -> BackendDescription: ...
    async def config_summary(self, *, location: str | None = None) -> ConfigSummary: ...
    async def list_agents(self, *, location: str | None = None) -> list[AgentInfo]: ...
    async def list_models(self, *, location: str | None = None) -> list[ModelInfo]: ...
    async def agent_tools(
        self, agent: str, *, location: str | None = None
    ) -> list[ToolInfo]: ...
    async def active_sessions(self) -> set[str]: ...

    # session
    async def create_session(
        self,
        *,
        agent: str,
        model: str | None = None,
        title: str | None = None,
        location: str | None = None,
        permissions: list[PermissionRule] | None = None,
    ) -> SessionInfo: ...
    async def get_session(self, sid: str) -> SessionInfo: ...
    async def set_agent(self, sid: str, agent: str) -> None: ...
    async def set_model(self, sid: str, model: str) -> None: ...
    async def set_title(self, sid: str, title: str) -> None: ...
    async def delete_session(self, sid: str) -> None: ...

    # execution
    async def prompt(
        self,
        sid: str,
        *,
        prompt: str,
        files: Sequence[PromptFile | dict[str, Any]] | None = None,
        id: str | None = None,
        delivery: str = "queue",
    ) -> None: ...
    async def interrupt(self, sid: str) -> None: ...
    async def compact(self, sid: str) -> bool: ...
    async def wait(self, sid: str, timeout_s: float) -> bool: ...

    # read / recovery
    async def turn_snapshot(
        self, sid: str, *, after_message_id: str | None = None
    ) -> TurnSnapshot: ...
    async def session_replay(
        self, sid: str, *, after_seq: int = -1
    ) -> list[Event]: ...

    # interaction
    async def reply_permission(
        self, sid: str, rid: str, *, reply: str, message: str | None = None
    ) -> None: ...
    async def reply_question(
        self, sid: str, rid: str, answer: QuestionAnswer | list[list[str]]
    ) -> None: ...
    async def reply_form(self, sid: str, rid: str, answer: FormAnswer) -> None: ...
    async def reject_question(
        self, sid: str, rid: str, *, message: str | None = None
    ) -> None: ...
    async def list_permissions(
        self, *, locations: Sequence[str] | None = None
    ) -> list[PendingPermission]: ...
    async def list_questions(
        self, *, locations: Sequence[str] | None = None
    ) -> list[PendingQuestion]: ...

    # events
    def events(self) -> AsyncIterator[Event]: ...


__all__ = [
    "AgentBackend",
    "BackendDescription",
    "BackendProfile",
    "ConfigSummary",
    "FormAnswer",
    "FormField",
    "FormOption",
    "FormSpec",
    "PermissionRule",
    "PromptFile",
    "QuestionAnswer",
    "TurnSnapshot",
]

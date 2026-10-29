"""Agent-side integration ports and backend adapters."""

from __future__ import annotations

from tether.agent.agentd.client import AgentdBackend, HttpAgentClient
from tether.agent.base import (
    AgentBackend,
    BackendDescription,
    BackendProfile,
    ConfigSummary,
    FormAnswer,
    FormField,
    FormOption,
    FormSpec,
    PermissionRule,
    PromptFile,
    QuestionAnswer,
    TurnSnapshot,
)
from tether.agent.client import AgentClient
from tether.agent.errors import AgentError, user_message
from tether.agent.events import Event
from tether.agent.opencode.client import OpenCodeBackend

__all__ = [
    "AgentBackend",
    "AgentClient",
    "AgentError",
    "AgentdBackend",
    "BackendDescription",
    "BackendProfile",
    "ConfigSummary",
    "Event",
    "FormAnswer",
    "FormField",
    "FormOption",
    "FormSpec",
    "HttpAgentClient",
    "OpenCodeBackend",
    "PermissionRule",
    "PromptFile",
    "QuestionAnswer",
    "TurnSnapshot",
    "user_message",
]

"""Agent-side integration with the go-agent-sdk HTTP/SSE API."""

from __future__ import annotations

from .client import AgentClient, HttpAgentClient
from .errors import AgentError, user_message
from .events import Event

__all__ = ["AgentClient", "HttpAgentClient", "AgentError", "user_message", "Event"]

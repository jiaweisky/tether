"""Compatibility imports for the agentd backend.

New code should import :class:`AgentBackend` from ``tether.agent.base`` and use
the registry; this module keeps existing imports working during the refactor.
"""

from tether.agent.agentd.client import AgentdBackend, HttpAgentClient

AgentClient = AgentdBackend

__all__ = ["AgentClient", "AgentdBackend", "HttpAgentClient"]

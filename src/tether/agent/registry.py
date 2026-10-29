"""Create the configured agent backend adapter."""

from __future__ import annotations

from tether.agent.agentd.client import AgentdBackend
from tether.agent.base import AgentBackend
from tether.agent.opencode.client import OpenCodeBackend
from tether.config import ServerEndpoint


def create_backend(endpoint: ServerEndpoint) -> AgentBackend:
    auth = endpoint.auth
    if endpoint.backend == "agentd":
        token = auth.token if auth is not None and auth.type == "bearer" else None
        return AgentdBackend(
            endpoint.base_url,
            token,
            endpoint_id=endpoint.id,
        )

    if endpoint.backend == "opencode":
        username = "opencode"
        password: str | None = None
        if auth is not None:
            if auth.type == "basic":
                username = auth.username or username
                password = auth.password
            else:
                password = auth.token
        return OpenCodeBackend(
            endpoint.base_url,
            username=username,
            password=password,
            endpoint_id=endpoint.id,
            location=endpoint.working_directory,
        )

    raise ValueError(f"unsupported agent backend: {endpoint.backend!r}")


__all__ = ["create_backend"]

"""Map conversations to agent sessions and decide project isolation.

The router owns the canonical in-memory route for each conversation, creates
sessions on demand, leases isolated project instances for writable agents, and
keeps the bot identity in sync with the platform.
"""

from __future__ import annotations

import os
import time
from collections.abc import Callable

from ..agent.client import HttpAgentClient
from ..config import Config
from ..connector import IMConnector
from ..models import BotIdentity, Conversation, Route
from ..store.sqlite import RouteStore
from ..util.logging import get_logger
from .projects import LeaseManager, ProjectProvider

log = get_logger("tether.router")

# Tools whose presence marks an agent as able to modify the workspace.
MUTATION_TOOLS = frozenset({"write", "edit", "apply_patch", "bash", "task"})

ClientFactory = Callable[[str, str | None], HttpAgentClient]


def _default_client_factory(base_url: str, token: str | None) -> HttpAgentClient:
    return HttpAgentClient(base_url, token)


class Router:
    """Create, cache and persist the conversation-to-session mapping."""

    def __init__(
        self,
        config: Config,
        store: RouteStore,
        provider: ProjectProvider,
        *,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self.config = config
        self.store = store
        self.provider = provider
        self.leases = LeaseManager(provider, config.projects.ttl_s)
        self._client_factory = client_factory or _default_client_factory
        self._clients: dict[str, HttpAgentClient] = {}
        self._writable_cache: dict[tuple[str, str], bool] = {}
        self._routes: dict[str, Route] = {}
        self._by_session: dict[str, Route] = {}
        self._token_env: dict[str, str] = {}
        for entry in config.server.pool:
            self._token_env[entry.base_url.rstrip("/")] = entry.token_env

    # -- clients -----------------------------------------------------------
    def client_for_base(self, base_url: str) -> HttpAgentClient:
        base = base_url.rstrip("/")
        client = self._clients.get(base)
        if client is None:
            token_env = self._token_env.get(base, self.config.server.token_env)
            token = os.environ.get(token_env)
            client = self._client_factory(base, token)
            self._clients[base] = client
        return client

    def client_for(self, route: Route) -> HttpAgentClient:
        return self.client_for_base(route.server_base)

    async def close(self) -> None:
        await self.leases.release_all()
        for client in self._clients.values():
            await client.aclose()
        self._clients.clear()

    # -- read/write determination ------------------------------------------
    async def is_writable(self, base_url: str, agent: str) -> bool:
        """Decide whether an agent can modify the workspace.

        An explicit config override wins; otherwise the agent's tool list is
        inspected, and a failure to inspect is treated conservatively as
        writable so the agent is isolated.
        """
        override = self.config.writable_override(agent)
        if override is not None:
            return override
        key = (base_url.rstrip("/"), agent)
        if key in self._writable_cache:
            return self._writable_cache[key]
        try:
            tools = await self.client_for_base(base_url).agent_tools(agent)
            writable = bool({tool.name for tool in tools} & MUTATION_TOOLS)
        except Exception as exc:  # noqa: BLE001 - unknown is treated as writable
            log.warning("writable_determination_failed", agent=agent, error=str(exc))
            writable = True
        self._writable_cache[key] = writable
        return writable

    # -- routing -----------------------------------------------------------
    async def get_by_session(self, session_id: str) -> Route | None:
        cached = self._by_session.get(session_id)
        if cached is not None:
            return cached
        route = await self.store.get_by_session(session_id)
        if route is not None:
            self._remember(route)
        return route

    async def get(self, conv: Conversation) -> Route | None:
        cached = self._routes.get(conv.key)
        if cached is not None:
            return cached
        route = await self.store.get(conv.key)
        if route is not None:
            self._remember(route)
        return route

    def _remember(self, route: Route) -> Route:
        self._routes[route.key] = route
        self._by_session[route.session_id] = route
        return route

    async def get_or_create(
        self,
        conv: Conversation,
        *,
        agent: str | None = None,
        title: str | None = None,
    ) -> Route:
        existing = await self.get(conv)
        if existing is not None:
            return existing
        agent_id = agent or self.config.agent.default_agent
        readonly = not await self.is_writable(self._primary_base(), agent_id)
        lease = await self.provider.acquire(conv, agent=agent_id, readonly=readonly)
        await self.leases.register(conv.key, lease)
        client = self.client_for_base(lease.server_base)
        info = await client.create_session(
            agent=agent_id, model=self.config.agent.default_model, title=title
        )
        now = time.time()
        route = Route(
            conversation=conv,
            session_id=info.id,
            server_base=lease.server_base,
            agent=info.agent or agent_id,
            model=info.model or self.config.agent.default_model,
            project_id=lease.project_id,
            created_at=now,
            last_active=now,
            context_dirty=True,
        )
        self._remember(route)
        await self.store.put(route)
        log.info("route_created", conversation=conv.key, session=info.id, project=lease.project_id)
        return route

    def _primary_base(self) -> str:
        bases = self.config.server_bases()
        return bases[0][1]

    async def save(self, route: Route) -> None:
        route.last_active = time.time()
        self.leases.touch(route.key)
        await self.store.put(route)

    async def reclaim_idle(self) -> list[str]:
        reclaimed = await self.leases.reclaim_idle()
        for key in reclaimed:
            route = await self.store.get(key)
            if route is not None:
                await self.store.delete(key)
                self._routes.pop(key, None)
                self._by_session.pop(route.session_id, None)
        return reclaimed

    # -- identity sync -----------------------------------------------------
    async def refresh_identity(self, route: Route, connector: IMConnector) -> BotIdentity:
        """Fetch the bot identity and flag the context dirty when it changed."""
        try:
            identity = await connector.identity(route.conversation)
        except Exception as exc:  # noqa: BLE001 - fall back to configured identity
            log.warning("identity_unavailable", conversation=route.key, error=str(exc))
            identity = BotIdentity(name=self.config.identity.display_name or "Assistant")
        if self.config.identity.display_name:
            identity = BotIdentity(
                name=self.config.identity.display_name,
                description=identity.description or self.config.identity.description,
                aliases=identity.aliases,
            )
        if route.bot_name != identity.name or route.bot_description != identity.description:
            route.bot_name = identity.name
            route.bot_description = identity.description
            route.context_dirty = True
        return identity

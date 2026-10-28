"""Map conversations to agent sessions and decide project isolation.

The router owns the canonical in-memory route for each conversation, creates
sessions on demand, leases isolated project instances for writable agents, and
keeps the bot identity in sync with the platform.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from tether.agent.client import HttpAgentClient
from tether.agent.errors import AgentError
from tether.config import Config
from tether.connector import IMConnector
from tether.engine.projects import LeaseManager, ProjectProvider
from tether.models import BotIdentity, Conversation, Route
from tether.store.sqlite import RouteStore
from tether.util.logging import get_logger

log = get_logger("tether.router")

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
        self._agent_cache: dict[str, str] = {}
        self._models_cache: dict[str, dict[str, Any]] = {}
        # Session ids validated (or created) in this process, so the first-use
        # check runs once per route per process rather than every message.
        self._validated: set[str] = set()
        self._routes: dict[str, Route] = {}
        self._by_session: dict[str, Route] = {}

    # -- discovery ---------------------------------------------------------
    def _pool_entry(self, base_url: str) -> Any:
        base = base_url.rstrip("/")
        for entry in self.config.server.pool:
            if entry.base_url.rstrip("/") == base:
                return entry

        return None

    async def resolve_agent(self, base_url: str) -> str:
        """The agent to use for a base: an explicit override, else agentd's first.

        The override may come from the pool entry (per instance) or the top-level
        config; otherwise the first exposed agent is chosen, matching agentd's own
        default agent.
        """
        base = base_url.rstrip("/")

        cached = self._agent_cache.get(base)
        if cached is not None:
            return cached

        entry = self._pool_entry(base)
        override = (entry.default_agent if entry else None) or self.config.agent.default_agent
        agents = await self.client_for_base(base).list_agents()
        ids = [agent.id for agent in agents if not agent.hidden]

        if override:
            if ids and override not in ids:
                raise ValueError(f"agent {override!r} is not exposed by {base}")
            chosen = override
        elif ids:
            chosen = ids[0]
        else:
            raise ValueError(f"no agents are exposed by {base}")

        self._agent_cache[base] = chosen
        return chosen

    def resolve_model(self, base_url: str) -> str | None:
        """The model override for a base, or None to use agentd's default."""
        entry = self._pool_entry(base_url)
        return (entry.default_model if entry else None) or self.config.agent.default_model

    async def _model_map(self, base_url: str) -> dict[str, Any]:
        base = base_url.rstrip("/")
        cached = self._models_cache.get(base)
        if cached is None:
            models = await self.client_for_base(base).list_models()
            cached = {model.id: model for model in models}
            self._models_cache[base] = cached

        return cached

    async def resolve_context_limit(self, base_url: str, model_id: str | None) -> int | None:
        """The model's context window as reported by agentd, for the usage line."""
        if not model_id:
            return None

        try:
            model = (await self._model_map(base_url)).get(model_id)
        except Exception as exc:  # noqa: BLE001 - the limit is optional
            log.warning("model_lookup_failed", model=model_id, error=str(exc))
            return None

        return model.context_limit if model is not None else None

    async def warm_base(self, base_url: str) -> None:
        """Best-effort discovery so the first message does not pay for it."""
        await self.resolve_agent(base_url)

    def working_directory(self, route: Route) -> str | None:
        """The working directory of a route's project instance, when known.

        Isolated projects return the view path from the control API; a static
        pool entry carries it in configuration.
        """
        lease = self.leases.get(route.key)
        if lease is not None and lease.working_directory:
            return lease.working_directory

        for entry in self.config.server.pool:
            if entry.base_url.rstrip("/") == route.server_base.rstrip("/"):
                return entry.working_directory

        return self.config.server.working_directory

    # -- clients -----------------------------------------------------------
    def client_for_base(self, base_url: str) -> HttpAgentClient:
        base = base_url.rstrip("/")
        client = self._clients.get(base)
        if client is None:
            token = self.config.server_token(base)
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
            await self._ensure_lease(existing, agent=agent)
            await self._validate_session(existing)

            if existing.context_limit is None:
                # Backfill routes persisted before the limit was discovered, so
                # the usage line can show "context used / max".
                existing.context_limit = await self.resolve_context_limit(
                    existing.server_base, existing.model
                )

                if existing.context_limit is not None:
                    await self.store.put(existing)

            return existing

        primary = self._primary_base()
        agent_id = agent or await self.resolve_agent(primary)
        lease = await self.provider.acquire(conv, agent=agent_id)
        await self.leases.register(conv.key, lease)

        # Re-resolve against the leased base: pool entries may differ.
        agent_id = agent or await self.resolve_agent(lease.server_base)
        model = self.resolve_model(lease.server_base)

        client = self.client_for_base(lease.server_base)
        info = await client.create_session(agent=agent_id, model=model, title=title)

        now = time.time()
        route = Route(
            conversation=conv,
            session_id=info.id,
            server_base=lease.server_base,
            agent=info.agent or agent_id,
            model=info.model or model,
            project_id=lease.project_id,
            created_at=now,
            last_active=now,
            context_dirty=True,
        )

        self._remember(route)
        route.context_limit = await self.resolve_context_limit(lease.server_base, route.model)
        self._validated.add(route.session_id)
        await self.store.put(route)

        log.info("route_created", conversation=conv.key, session=info.id, project=lease.project_id)
        return route

    async def _validate_session(self, route: Route) -> None:
        """Ensure a loaded route's session still exists, once per process.

        Only the first message for a route pays for a GET; if the session is
        gone (agentd restarted with a fresh root) it is recreated so the
        conversation heals on the first message rather than failing.
        """
        if route.session_id in self._validated or not self.config.sessions.validate_session:
            return

        try:
            await self.client_for(route).get_session(route.session_id)
        except AgentError as exc:
            if exc.code != "not_found":
                return  # e.g. unreachable: let the prompt surface it
            log.warning("session_missing", session=route.session_id, conversation=route.key)
            await self.recreate_session(route)

        self._validated.add(route.session_id)

    def _primary_base(self) -> str:
        bases = self.config.server_bases()
        return bases[0][1]

    async def _ensure_lease(self, route: Route, *, agent: str | None) -> None:
        """Re-acquire an ephemeral (isolated) lease lost across a restart.

        Isolated views and their instances are gone once the bridge restarts (or
        a lease is reclaimed), so a loaded route points at a dead base. Lease a
        fresh view and rebuild the session on it — the previous context is gone.
        """
        if self.config.projects.mode != "isolated" or self.leases.get(route.key) is not None:
            return

        lease = await self.provider.acquire(route.conversation, agent=agent or route.agent)
        await self.leases.register(route.key, lease)

        route.server_base = lease.server_base
        route.project_id = lease.project_id

        log.info("lease_reacquired", conversation=route.key, project=lease.project_id)

        await self.recreate_session(route)

    async def recreate_session(self, route: Route) -> None:
        """Rebuild the agent session for an existing route.

        Used when the stored session no longer exists (for example agentd was
        restarted with a fresh state directory), so the conversation keeps
        working instead of failing forever.
        """
        client = self.client_for(route)
        model = self.resolve_model(route.server_base)
        info = await client.create_session(agent=route.agent, model=model)

        self._by_session.pop(route.session_id, None)

        route.session_id = info.id
        route.model = info.model or model
        route.context_limit = await self.resolve_context_limit(route.server_base, route.model)
        route.context_dirty = True
        route.identity_injected = False
        route.pending_interactions.clear()
        route.active_turn_sender = None
        route.queue_depth = 0
        route.last_seq = -1

        self._remember(route)
        self._validated.add(route.session_id)
        await self.store.put(route)

        log.info("session_recreated", conversation=route.key, session=info.id)

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

        # Name/description resolve channel override > global config > platform.
        cfg = self.config.identity
        channel = self.config.channels.identity_for(route.conversation.channel)

        account = self.config.channels.identity_for_account(
            route.conversation.channel, route.conversation.account
        )

        name = account.display_name or channel.display_name or cfg.display_name or identity.name
        description = (
            account.description
            or channel.description
            or cfg.description
            or identity.description
        )

        if name != identity.name or description != identity.description:
            identity = BotIdentity(name=name, description=description, aliases=identity.aliases)

        if route.bot_name != identity.name or route.bot_description != identity.description:
            route.bot_name = identity.name
            route.bot_description = identity.description
            route.context_dirty = True

        return identity

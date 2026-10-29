"""Map conversations to agent sessions and decide project isolation.

The router owns the canonical in-memory route for each conversation, creates
sessions on demand, leases isolated project instances for writable agents, and
keeps the bot identity in sync with the platform.
"""

from __future__ import annotations

import time
from collections.abc import Callable
from typing import Any

from tether.agent.base import AgentBackend, PermissionRule
from tether.agent.errors import AgentError
from tether.agent.registry import create_backend
from tether.config import Config, ServerEndpoint
from tether.connector import IMConnector
from tether.engine.projects import LeaseManager, ProjectProvider
from tether.models import BotIdentity, Conversation, Route
from tether.store.sqlite import RouteStore
from tether.util.logging import get_logger

log = get_logger("tether.router")


def _selectable_agent(agent: Any) -> bool:
    mode = getattr(agent, "mode", None)
    return mode not in ("subagent",)


ClientFactory = Callable[[ServerEndpoint], AgentBackend]


def _default_client_factory(endpoint: ServerEndpoint) -> AgentBackend:
    return create_backend(endpoint)


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
        self._clients: dict[tuple[str, str], AgentBackend] = {}
        self._agent_cache: dict[tuple[str, str | None], str] = {}
        self._models_cache: dict[tuple[str, str | None], dict[str, Any]] = {}
        # Session ids validated (or created) in this process, so the first-use
        # check runs once per route per process rather than every message.
        self._validated: set[str] = set()
        self._routes: dict[str, Route] = {}
        self._by_session: dict[str, Route] = {}

    # -- discovery ---------------------------------------------------------
    def _pool_entry(self, base_url: str) -> ServerEndpoint | None:
        return self.config.endpoint_for_base(base_url)

    async def resolve_agent(
        self,
        base_url: str,
        location: str | None = None,
        *,
        endpoint: ServerEndpoint | None = None,
    ) -> str:
        """The agent to use for a base: an explicit override, else agentd's first.

        The override may come from the pool entry (per instance) or the top-level
        config; otherwise the first exposed agent is chosen, matching agentd's own
        default agent.
        """
        base = base_url.rstrip("/")
        endpoint = endpoint or self._endpoint_for_base(base)
        cache_key = (endpoint.id, location)

        cached = self._agent_cache.get(cache_key)
        if cached is not None:
            return cached

        override = endpoint.default_agent or self.config.agent.default_agent
        agents = await self.client_for_base(base).list_agents(location=location)
        usable = [agent for agent in agents if not agent.hidden and _selectable_agent(agent)]
        ids = [agent.id for agent in usable]

        if override:
            if ids and override not in ids:
                raise ValueError(f"agent {override!r} is not usable by {base}")
            chosen = override
        elif ids:
            chosen = ids[0]
        else:
            raise ValueError(f"no agents are exposed by {base}")

        self._agent_cache[cache_key] = chosen
        return chosen

    def resolve_model(
        self,
        base_url: str,
        location: str | None = None,
        *,
        endpoint: ServerEndpoint | None = None,
    ) -> str | None:
        """The model override for a base, or None to use agentd's default."""
        endpoint = endpoint or self._pool_entry(base_url)
        return (endpoint.default_model if endpoint else None) or self.config.agent.default_model

    async def _model_map(
        self, base_url: str, location: str | None = None
    ) -> dict[str, Any]:
        endpoint = self._endpoint_for_base(base_url)
        cache_key = (endpoint.id, location)
        cached = self._models_cache.get(cache_key)
        if cached is None:
            models = await self.client_for_base(base_url).list_models(location=location)
            cached = {model.id: model for model in models}
            self._models_cache[cache_key] = cached

        return cached

    async def resolve_context_limit(
        self, base_url: str, model_id: str | None, *, location: str | None = None
    ) -> int | None:
        """The model's context window as reported by agentd, for the usage line."""
        if not model_id:
            return None

        try:
            models = await self._model_map(base_url, location)
            model = models.get(model_id) or models.get(model_id.split("#", 1)[0])
        except Exception as exc:  # noqa: BLE001 - the limit is optional
            log.warning("model_lookup_failed", model=model_id, error=str(exc))
            return None

        return model.context_limit if model is not None else None

    async def warm_base(self, base_url: str) -> None:
        """Best-effort discovery so the first message does not pay for it."""
        endpoint = self._endpoint_for_base(base_url)
        await self.resolve_agent(base_url, endpoint.working_directory)

    def locations_for_base(self, base_url: str) -> list[str]:
        """Locations worth querying for a base, including known route locations."""
        base = base_url.rstrip("/")
        locations: list[str] = []
        for endpoint in self.config.server_endpoints():
            if endpoint.base_url.rstrip("/") == base and endpoint.working_directory:
                locations.append(endpoint.working_directory)
        for route in self._routes.values():
            if route.server_base.rstrip("/") == base and route.location:
                locations.append(route.location)
        return list(dict.fromkeys(locations))

    def working_directory(self, route: Route) -> str | None:
        """The working directory of a route's project instance, when known.

        Isolated projects return the view path from the control API; a static
        pool entry carries it in configuration.
        """
        lease = self.leases.get(route.key)
        if lease is not None and lease.working_directory:
            return lease.working_directory
        if route.location:
            return route.location

        endpoint = self.config.endpoint_for_base(route.server_base)
        if endpoint is not None and endpoint.working_directory:
            return endpoint.working_directory

        return self.config.server.working_directory

    # -- clients -----------------------------------------------------------
    def _endpoint_for_base(self, base_url: str) -> ServerEndpoint:
        endpoint = self.config.endpoint_for_base(base_url)
        if endpoint is not None:
            return endpoint

        # Dynamic isolated agentd bases are not in the static config.
        return ServerEndpoint(
            id=base_url.rstrip("/"),
            name=base_url.rstrip("/"),
            backend="agentd",
            base_url=base_url.rstrip("/"),
            auth=None,
            working_directory=None,
            default_agent=None,
            default_model=None,
        )

    def _endpoint_for_lease(self, lease: Any) -> ServerEndpoint:
        endpoint_id = str(getattr(lease, "endpoint_id", "") or "")
        for endpoint in self.config.server_endpoints():
            if endpoint.id == endpoint_id:
                return endpoint

        base = str(getattr(lease, "server_base", "") or "").rstrip("/")
        return ServerEndpoint(
            id=endpoint_id or base,
            name=endpoint_id or base,
            backend=str(getattr(lease, "backend", "") or "agentd"),
            base_url=base,
            auth=None,
            working_directory=getattr(lease, "working_directory", None),
            default_agent=None,
            default_model=None,
        )

    def _endpoint_for_route(self, route: Route) -> ServerEndpoint:
        for endpoint in self.config.server_endpoints():
            if route.endpoint and endpoint.id == route.endpoint:
                return endpoint

        if route.endpoint:
            return ServerEndpoint(
                id=route.endpoint,
                name=route.endpoint,
                backend=route.backend or "agentd",
                base_url=route.server_base.rstrip("/"),
                auth=None,
                working_directory=route.location,
                default_agent=None,
                default_model=None,
            )

        return self._endpoint_for_base(route.server_base)

    def client_for_endpoint(self, endpoint: ServerEndpoint) -> AgentBackend:
        key = (endpoint.id, endpoint.base_url.rstrip("/"))
        client = self._clients.get(key)
        if client is None:
            client = self._client_factory(endpoint)
            self._clients[key] = client

        return client

    def client_for_base(self, base_url: str) -> AgentBackend:
        return self.client_for_endpoint(self._endpoint_for_base(base_url))

    def client_for(self, route: Route) -> AgentBackend:
        return self.client_for_endpoint(self._endpoint_for_route(route))

    async def close(self) -> None:
        if self.config.sessions.interrupt_on_shutdown:
            await self.leases.release_all()
        else:
            # Keep ephemeral worktrees/views so a restart can resume them.
            self.leases.forget_all()
        for client in self._clients.values():
            await client.aclose()
        self._clients.clear()

    async def cleanup_orphans(self) -> list[str]:
        cleanup = getattr(self.provider, "cleanup_orphans", None)
        if cleanup is None:
            return []

        routes = await self.store.all()
        referenced = {
            value
            for route in routes
            for value in (route.location, route.project_id)
            if value
        }
        active = self.leases.working_directories() | self.leases.project_ids()

        # OpenCode sessions are not tied to Route.project_id; resolve active
        # sessions to their locations before deleting any worktree.
        for endpoint in self.config.server_endpoints():
            if endpoint.backend != "opencode":
                continue
            try:
                client = self.client_for_endpoint(endpoint)
                session_ids = await client.active_sessions()
                for sid in session_ids:
                    info = await client.get_session(sid)
                    if info.location:
                        active.add(info.location)
            except AgentError as exc:
                # A failed probe must not turn into destructive cleanup.
                log.warning(
                    "orphan_active_probe_failed",
                    endpoint=endpoint.id,
                    error=exc.code,
                )
                return []

        removed = await cleanup(referenced=referenced, active=active)
        if removed:
            log.info("isolated_orphans_cleaned", count=len(removed))
        return removed

    # -- routing -----------------------------------------------------------
    async def get_by_session(self, session_id: str) -> Route | None:
        cached = self._by_session.get(session_id)
        if cached is not None:
            return cached

        route = await self.store.get_by_session(session_id)
        if route is not None:
            route = await self._normalize_loaded(route)
            if route is None:
                return None
            self._remember(route)

        return route

    async def get(self, conv: Conversation) -> Route | None:
        cached = self._routes.get(conv.key)
        if cached is not None:
            return cached

        route = await self.store.get(conv.key)
        if route is not None:
            route = await self._normalize_loaded(route)
            if route is None:
                return None
            self._remember(route)

        return route

    async def _normalize_loaded(self, route: Route) -> Route | None:
        """Bind a legacy route to an endpoint and reject incompatible state."""
        endpoints = self.config.server_endpoints()
        endpoint = next((item for item in endpoints if item.id == route.endpoint), None)

        if endpoint is None and route.endpoint is None:
            matches = [
                item
                for item in endpoints
                if item.base_url.rstrip("/") == route.server_base.rstrip("/")
            ]
            if len(matches) == 1:
                endpoint = matches[0]
            elif len(matches) > 1:
                log.warning(
                    "route_ambiguous_endpoint",
                    conversation=route.key,
                    base=route.server_base,
                )
                await self._discard_route(route)
                return None

        if endpoint is None:
            # Dynamic isolated agentd leases are intentionally not in config; the
            # lease is reacquired on first use.
            if self.config.projects.mode == "isolated" and route.project_id:
                route.backend = route.backend or "agentd"
                return route
            log.warning(
                "route_endpoint_missing",
                conversation=route.key,
                endpoint=route.endpoint,
            )
            await self._discard_route(route)
            return None

        if route.backend is not None and route.backend != endpoint.backend:
            log.warning(
                "route_backend_mismatch",
                conversation=route.key,
                endpoint=endpoint.id,
                route_backend=route.backend,
                configured_backend=endpoint.backend,
            )
            await self._discard_route(route)
            return None

        route.endpoint = endpoint.id
        route.backend = endpoint.backend
        return route

    async def _discard_route(self, route: Route) -> None:
        self._routes.pop(route.key, None)
        self._by_session.pop(route.session_id, None)
        await self.store.delete(route.key)

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
                    existing.server_base, existing.model, location=existing.location
                )

                if existing.context_limit is not None:
                    await self.store.put(existing)

            return existing

        await self._ensure_capacity()
        primary = self._primary_base()
        agent_id = agent or await self.resolve_agent(primary)
        lease = await self.provider.acquire(conv, agent=agent_id)
        await self.leases.register(conv.key, lease)

        # Re-resolve against the leased base: pool entries may differ.
        endpoint = self._endpoint_for_lease(lease)
        location = lease.working_directory or endpoint.working_directory
        agent_id = agent or await self.resolve_agent(
            lease.server_base, location, endpoint=endpoint
        )
        model = self.resolve_model(lease.server_base, location, endpoint=endpoint)

        client = self.client_for_endpoint(endpoint)
        info = await client.create_session(
            agent=agent_id,
            model=model,
            title=title,
            location=location,
            permissions=self._lease_permissions(),
        )

        now = time.time()
        route = Route(
            conversation=conv,
            session_id=info.id,
            server_base=lease.server_base,
            endpoint=endpoint.id,
            backend=endpoint.backend,
            location=info.location or location,
            agent=info.agent or agent_id,
            model=info.model or model,
            project_id=lease.project_id,
            created_at=now,
            last_active=now,
            context_dirty=True,
        )

        self._remember(route)
        route.context_limit = await self.resolve_context_limit(
            lease.server_base, route.model, location=route.location
        )
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

        await self._ensure_capacity()
        lease = await self.provider.acquire(route.conversation, agent=agent or route.agent)
        await self.leases.register(route.key, lease)

        endpoint = self._endpoint_for_lease(lease)
        route.server_base = lease.server_base
        route.endpoint = endpoint.id
        route.backend = endpoint.backend
        route.location = lease.working_directory or endpoint.working_directory
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
        endpoint = self._endpoint_for_route(route)
        model = self.resolve_model(route.server_base, route.location, endpoint=endpoint)
        info = await client.create_session(
            agent=route.agent,
            model=model,
            location=route.location,
            permissions=self._lease_permissions(),
        )

        self._by_session.pop(route.session_id, None)

        route.session_id = info.id
        route.model = info.model or model
        route.location = info.location or route.location
        route.context_limit = await self.resolve_context_limit(
            route.server_base, route.model, location=route.location
        )
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

    def _lease_permissions(self) -> list[PermissionRule] | None:
        if self.config.projects.mode != "isolated":
            return None
        return [
            PermissionRule(
                action=rule.action,
                resource=rule.resource,
                effect=rule.effect,
            )
            for rule in self.config.projects.inbound_permissions
        ]

    async def _ensure_capacity(self) -> None:
        if self.config.projects.mode != "isolated":
            return

        limit = self.config.projects.max_leases
        if limit <= 0 or self.leases.count < limit:
            return

        await self.reclaim_idle()
        active_by_base: dict[str, set[str]] = {}

        while self.leases.count >= limit:
            evicted = False
            for key in self.leases.ephemeral_keys():
                route = await self.store.get(key)
                if route is not None:
                    base = route.server_base.rstrip("/")
                    if base not in active_by_base:
                        try:
                            active_by_base[base] = await self.client_for(
                                route
                            ).active_sessions()
                        except AgentError as exc:
                            log.warning(
                                "lease_active_probe_failed", base=base, error=exc.code
                            )
                            continue
                    if route.session_id in active_by_base[base]:
                        self.leases.touch(key)
                        continue

                await self.leases.release(key)
                if route is not None:
                    await self.store.delete(key)
                    self._routes.pop(key, None)
                    self._by_session.pop(route.session_id, None)
                evicted = True
                break

            if not evicted:
                raise RuntimeError(
                    f"project lease limit reached ({limit}); no idle lease can be reclaimed"
                )

    async def reclaim_idle(self) -> list[str]:
        reclaimed: list[str] = []
        active_by_base: dict[str, set[str]] = {}

        for key in self.leases.expired_keys():
            route = await self.store.get(key)
            if route is not None:
                base = route.server_base.rstrip("/")
                if base not in active_by_base:
                    try:
                        active_by_base[base] = await self.client_for(route).active_sessions()
                    except AgentError as exc:
                        log.warning("lease_active_probe_failed", base=base, error=exc.code)
                        continue
                if route.session_id in active_by_base[base]:
                    self.leases.touch(key)
                    continue

            await self.leases.release(key)
            if route is not None:
                await self.store.delete(key)
                self._routes.pop(key, None)
                self._by_session.pop(route.session_id, None)
            reclaimed.append(key)

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

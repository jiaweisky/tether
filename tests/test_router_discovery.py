from __future__ import annotations

import pytest
from fakes import FakeAgentClient

from tether.agent.events import AgentInfo, ModelInfo
from tether.config import Config, ServerEndpoint
from tether.engine.projects import build_provider
from tether.engine.router import Router
from tether.store import RouteStore

# The single default base used when server.pool is empty.
BASE = "http://127.0.0.1:8787"


async def make_router(
    tmp_path, config: Config | None = None, client: FakeAgentClient | None = None
):
    config = config or Config()
    store = RouteStore(str(tmp_path / "routes.db"))
    await store.connect()
    client = client or FakeAgentClient()
    router = Router(config, store, build_provider(config), client_factory=lambda _endpoint: client)
    return router, client, store


@pytest.mark.asyncio
async def test_default_agent_is_discovered(tmp_path):
    router, client, _ = await make_router(tmp_path)
    client.agents = [AgentInfo("alpha"), AgentInfo("beta")]
    assert await router.resolve_agent(BASE) == "alpha"


@pytest.mark.asyncio
async def test_hidden_agents_are_skipped(tmp_path):
    router, client, _ = await make_router(tmp_path)
    client.agents = [AgentInfo("hidden", hidden=True), AgentInfo("visible")]
    assert await router.resolve_agent(BASE) == "visible"


@pytest.mark.asyncio
async def test_configured_default_agent_wins(tmp_path):
    router, client, _ = await make_router(
        tmp_path, Config.model_validate({"agent": {"default_agent": "beta"}})
    )
    client.agents = [AgentInfo("alpha"), AgentInfo("beta")]
    assert await router.resolve_agent(BASE) == "beta"


@pytest.mark.asyncio
async def test_unknown_default_agent_is_rejected(tmp_path):
    router, client, _ = await make_router(
        tmp_path, Config.model_validate({"agent": {"default_agent": "ghost"}})
    )
    client.agents = [AgentInfo("alpha")]
    with pytest.raises(ValueError):
        await router.resolve_agent(BASE)


@pytest.mark.asyncio
async def test_no_agents_is_an_error(tmp_path):
    router, client, _ = await make_router(tmp_path)
    client.agents = []
    with pytest.raises(ValueError):
        await router.resolve_agent(BASE)


def test_model_override_precedence(tmp_path):
    config = Config.model_validate(
        {
            "agent": {"default_model": "top"},
            "server": {"pool": [{"name": "a", "base_url": BASE, "default_model": "pool"}]},
        }
    )
    router = Router(config, RouteStore(str(tmp_path / "r.db")), build_provider(config))
    assert router.resolve_model(BASE) == "pool"
    assert router.resolve_model("http://other") == "top"


def test_model_absent_uses_agentd_default(tmp_path):
    config = Config()
    router = Router(config, RouteStore(str(tmp_path / "r.db")), build_provider(config))
    assert router.resolve_model(BASE) is None


@pytest.mark.asyncio
async def test_context_limit_is_discovered(tmp_path):
    router, client, _ = await make_router(tmp_path)
    client.models = [
        ModelInfo("m", "openai-responses", ["text"], [], context_limit=128000, output_limit=4096)
    ]
    assert await router.resolve_context_limit(BASE, "m") == 128000
    assert await router.resolve_context_limit(BASE, "ghost") is None
    assert await router.resolve_context_limit(BASE, None) is None


@pytest.mark.asyncio
async def test_loaded_route_with_dead_session_is_recreated(tmp_path):
    from tether.models import Conversation, Route

    router, client, store = await make_router(tmp_path)
    client.agents = [AgentInfo("build")]
    conv = Conversation(channel="wecom", kind="group", id="g1")
    # A persisted route (e.g. from before agentd lost its state directory).
    await store.put(
        Route(conversation=conv, session_id="ses_dead", server_base=BASE, agent="build")
    )

    route = await router.get_or_create(conv)
    assert route.session_id != "ses_dead"
    assert route.session_id in client.sessions


@pytest.mark.asyncio
async def test_identity_precedence_channel_over_global_over_platform(tmp_path):
    from tether.connectors.fake import FakeConnector
    from tether.models import Conversation

    config = Config.model_validate(
        {
            "identity": {"display_name": "Global", "description": "global-desc"},
            "channels": {"feishu": {"identity": {"display_name": "Channel"}}},
        }
    )
    router, _, _ = await make_router(tmp_path, config)
    conn = FakeConnector(bot_name="Platform", bot_description="platform-desc")

    route = await router.get_or_create(Conversation(channel="feishu", kind="direct", id="c1"))
    identity = await router.refresh_identity(route, conn)
    assert identity.name == "Channel"  # per-channel override wins
    assert identity.description == "global-desc"  # falls back to the global default

    route2 = await router.get_or_create(Conversation(channel="qq", kind="direct", id="c2"))
    identity2 = await router.refresh_identity(route2, conn)
    assert identity2.name == "Global"  # no channel override -> global default


class _CountingClient(FakeAgentClient):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.model_calls = 0

    async def list_models(self, *, location=None):
        self.model_calls += 1
        return await super().list_models(location=location)


def test_client_factory_is_cached_per_base_and_uses_pool_token(tmp_path):
    config = Config.model_validate(
        {
            "server": {
                "token": "top-token",
                "pool": [{"name": "a", "base_url": BASE, "token": "pool-token"}],
            }
        }
    )
    calls: list[tuple[str, str, str | None]] = []
    clients: list[FakeAgentClient] = []

    def factory(endpoint: ServerEndpoint) -> FakeAgentClient:
        auth = endpoint.auth
        token = auth.token if auth is not None else None
        calls.append((endpoint.base_url, endpoint.id, token))
        client = FakeAgentClient(endpoint.base_url, token)
        clients.append(client)
        return client

    router = Router(
        config,
        RouteStore(str(tmp_path / "r.db")),
        build_provider(config),
        client_factory=factory,
    )

    first = router.client_for_base(BASE)
    second = router.client_for_base(BASE + "/")
    assert first is second
    assert calls == [(BASE, "a", "pool-token")]
    assert clients[0].token == "pool-token"


@pytest.mark.asyncio
async def test_context_limit_model_list_is_cached_per_base(tmp_path):
    client = _CountingClient()
    client.models = [ModelInfo("m", context_limit=4096)]
    router = Router(
        Config(),
        RouteStore(str(tmp_path / "r.db")),
        build_provider(Config()),
        client_factory=lambda _endpoint: client,
    )

    assert await router.resolve_context_limit(BASE, "m") == 4096
    assert await router.resolve_context_limit(BASE, "m") == 4096
    assert client.model_calls == 1


@pytest.mark.asyncio
async def test_context_limit_lookup_failure_is_optional(tmp_path):
    class _BrokenModels(FakeAgentClient):
        async def list_models(self, *, location=None):
            raise RuntimeError("boom")

    client = _BrokenModels()
    router = Router(
        Config(),
        RouteStore(str(tmp_path / "r.db")),
        build_provider(Config()),
        client_factory=lambda _endpoint: client,
    )
    assert await router.resolve_context_limit(BASE, "m") is None


@pytest.mark.asyncio
async def test_get_or_create_persists_route_and_registers_session(tmp_path):
    from tether.models import Conversation

    client = _CountingClient()
    client.agents = [AgentInfo("build")]
    client.models = [ModelInfo("m", context_limit=8192)]
    config = Config.model_validate({"agent": {"default_model": "m"}})
    store = RouteStore(str(tmp_path / "r.db"))
    await store.connect()
    router = Router(
        config,
        store,
        build_provider(config),
        client_factory=lambda _endpoint: client,
    )
    conv = Conversation(channel="wecom", kind="direct", id="c1")
    route = await router.get_or_create(conv)

    assert route.session_id in client.sessions
    assert route.agent == "build"
    assert route.model == "m"
    assert route.context_limit == 8192
    assert route.server_base == BASE
    assert route.endpoint == "default"
    assert route.backend == "agentd"
    assert route.location is None
    assert await router.get_by_session(route.session_id) is route
    persisted = await router.store.get(conv.key)
    assert persisted is not None
    assert persisted.session_id == route.session_id


@pytest.mark.asyncio
async def test_working_directory_prefers_lease_then_pool(tmp_path):
    from tether.engine.projects import ProjectLease
    from tether.models import Conversation, Route

    config = Config.model_validate(
        {
            "server": {
                "working_directory": "/srv/default",
                "pool": [
                    {
                        "name": "a",
                        "base_url": BASE,
                        "working_directory": "/srv/pool",
                    }
                ],
            }
        }
    )
    router = Router(config, RouteStore(str(tmp_path / "r.db")), build_provider(config))
    conv = Conversation(channel="wecom", kind="direct", id="c1")
    route = Route(conversation=conv, session_id="s1", server_base=BASE, agent="build")

    assert router.working_directory(route) == "/srv/pool"
    await router.leases.register(
        route.key,
        ProjectLease(project_id="p", server_base=BASE, working_directory="/srv/lease"),
    )
    assert router.working_directory(route) == "/srv/lease"


@pytest.mark.asyncio
async def test_loaded_legacy_route_binds_to_single_endpoint(tmp_path):
    from tether.models import Conversation, Route

    config = Config()
    store = RouteStore(str(tmp_path / "r.db"))
    await store.connect()
    conv = Conversation(channel="wecom", kind="direct", id="c1")
    route = Route(conversation=conv, session_id="s1", server_base=BASE, agent="build")
    await store.put(route)

    router = Router(config, store, build_provider(config))
    loaded = await router.get(conv)

    assert loaded is not None
    assert loaded.session_id == "s1"
    assert loaded.endpoint == "default"
    assert loaded.backend == "agentd"


@pytest.mark.asyncio
async def test_loaded_route_with_incompatible_backend_is_discarded(tmp_path):
    from tether.models import Conversation, Route

    config = Config()
    store = RouteStore(str(tmp_path / "r.db"))
    await store.connect()
    conv = Conversation(channel="wecom", kind="direct", id="c1")
    await store.put(
        Route(
            conversation=conv,
            session_id="s1",
            server_base=BASE,
            endpoint="default",
            backend="opencode",
            agent="build",
        )
    )

    router = Router(config, store, build_provider(config))
    assert await router.get(conv) is None
    assert await store.get(conv.key) is None


@pytest.mark.asyncio
async def test_get_or_create_persists_endpoint_backend_and_location(tmp_path):
    from tether.models import Conversation

    client = _CountingClient()
    client.agents = [AgentInfo("build")]
    config = Config.model_validate(
        {
            "server": {
                "pool": [
                    {
                        "id": "site",
                        "name": "site",
                        "base_url": BASE,
                        "working_directory": "/srv/site",
                    }
                ]
            }
        }
    )
    store = RouteStore(str(tmp_path / "r.db"))
    await store.connect()
    router = Router(
        config,
        store,
        build_provider(config),
        client_factory=lambda _endpoint: client,
    )
    route = await router.get_or_create(Conversation(channel="wecom", kind="direct", id="c1"))

    assert route.endpoint == "site"
    assert route.backend == "agentd"
    assert route.location == "/srv/site"
    assert client.sessions[route.session_id].location == "/srv/site"


@pytest.mark.asyncio
async def test_agent_and_model_discovery_is_cached_per_location(tmp_path):
    class _LocationClient(FakeAgentClient):
        def __init__(self):
            super().__init__()
            self.agent_locations: list[str | None] = []
            self.model_locations: list[str | None] = []

        async def list_agents(self, *, location=None):
            self.agent_locations.append(location)
            return [AgentInfo(f"agent-{location or 'default'}")]

        async def list_models(self, *, location=None):
            self.model_locations.append(location)
            return [ModelInfo(f"model-{location or 'default'}", context_limit=4096)]

    client = _LocationClient()
    router = Router(
        Config(),
        RouteStore(str(tmp_path / "r.db")),
        build_provider(Config()),
        client_factory=lambda _endpoint: client,
    )

    assert await router.resolve_agent(BASE, "/a") == "agent-/a"
    assert await router.resolve_agent(BASE, "/a") == "agent-/a"
    assert await router.resolve_agent(BASE, "/b") == "agent-/b"
    assert client.agent_locations == ["/a", "/b"]

    assert await router.resolve_context_limit(BASE, "model-/a", location="/a") == 4096
    assert await router.resolve_context_limit(BASE, "model-/a", location="/a") == 4096
    assert client.model_locations == ["/a"]


@pytest.mark.asyncio
async def test_subagents_are_not_selected_as_primary(tmp_path):
    router, client, _ = await make_router(tmp_path)
    client.agents = [
        AgentInfo("task-only", mode="subagent"),
        AgentInfo("build", mode="primary"),
    ]
    assert await router.resolve_agent(BASE) == "build"


@pytest.mark.asyncio
async def test_max_leases_evicts_the_oldest_ephemeral_route(tmp_path):
    from tether.engine.projects import ProjectLease
    from tether.models import Conversation

    class _Provider:
        def __init__(self):
            self.counter = 0
            self.released: list[str] = []

        async def acquire(self, conv, *, agent, transport="http"):
            self.counter += 1
            return ProjectLease(
                project_id=f"p{self.counter}",
                endpoint_id=f"lease-{self.counter}",
                server_base=BASE,
                working_directory=f"/work/{self.counter}",
                ephemeral=True,
            )

        async def release(self, lease):
            self.released.append(lease.project_id)

        async def preflight(self):
            return None

    config = Config.model_validate(
        {
            "projects": {
                "mode": "isolated",
                "source_directory": "/src",
                "control_url": "http://control",
                "max_leases": 1,
            }
        }
    )
    provider = _Provider()
    client = FakeAgentClient()
    store = RouteStore(str(tmp_path / "r.db"))
    await store.connect()
    router = Router(
        config,
        store,
        provider,
        client_factory=lambda _endpoint: client,
    )

    first = await router.get_or_create(Conversation(channel="wecom", kind="direct", id="c1"))
    second = await router.get_or_create(Conversation(channel="wecom", kind="direct", id="c2"))

    assert provider.released == [first.project_id]
    assert await store.get(first.conversation.key) is None
    assert await store.get(second.conversation.key) is not None
    assert router.leases.count == 1
    await store.close()


@pytest.mark.asyncio
async def test_reclaim_idle_skips_active_sessions_and_shutdown_keeps_leases(tmp_path):
    from tether.engine.projects import ProjectLease
    from tether.models import Conversation

    class _Provider:
        def __init__(self):
            self.released: list[str] = []

        async def acquire(self, conv, *, agent, transport="http"):
            return ProjectLease(
                project_id="p1",
                endpoint_id="lease",
                server_base=BASE,
                working_directory="/work/1",
                ephemeral=True,
            )

        async def release(self, lease):
            self.released.append(lease.project_id)

        async def preflight(self):
            return None

    config = Config.model_validate(
        {
            "projects": {
                "mode": "isolated",
                "source_directory": "/src",
                "control_url": "http://control",
                "ttl_s": 1,
            }
        }
    )
    provider = _Provider()
    client = FakeAgentClient()
    store = RouteStore(str(tmp_path / "r.db"))
    await store.connect()
    router = Router(config, store, provider, client_factory=lambda _endpoint: client)
    now = [100]
    router.leases._clock = lambda: now[0]
    route = await router.get_or_create(Conversation(channel="wecom", kind="direct", id="c1"))
    client.active.add(route.session_id)

    assert await router.reclaim_idle() == []
    assert router.leases.count == 1

    client.active.discard(route.session_id)
    now[0] = 102
    assert await router.reclaim_idle() == [route.key]
    assert provider.released == ["p1"]
    assert await store.get(route.key) is None

    route2 = await router.get_or_create(Conversation(channel="wecom", kind="direct", id="c2"))
    provider.released.clear()
    await router.close()
    assert provider.released == []
    assert router.leases.count == 0
    assert route2.key
    await store.close()


@pytest.mark.asyncio
async def test_cleanup_orphans_includes_active_opencode_locations(tmp_path):
    from tether.agent.events import SessionInfo

    class _Provider:
        def __init__(self):
            self.active: set[str] = set()
            self.referenced: set[str] = set()

        async def acquire(self, conv, *, agent, transport="http"):
            raise AssertionError("not used")

        async def release(self, lease):
            return None

        async def preflight(self):
            return None

        async def cleanup_orphans(self, *, referenced, active):
            self.referenced = set(referenced)
            self.active = set(active)
            return []

    config = Config.model_validate(
        {
            "server": {
                "pool": [
                    {
                        "id": "oc",
                        "name": "oc",
                        "backend": "opencode",
                        "base_url": "http://oc",
                    }
                ]
            },
            "projects": {
                "mode": "isolated",
                "backend": "opencode",
                "endpoint": "oc",
                "source_directory": "/src",
                "base_dir": "/worktrees",
            },
        }
    )
    provider = _Provider()
    client = FakeAgentClient()
    client.active = {"ses_live"}
    client.sessions["ses_live"] = SessionInfo(
        id="ses_live", location="/worktrees/tether-live"
    )
    store = RouteStore(str(tmp_path / "r.db"))
    await store.connect()
    router = Router(config, store, provider, client_factory=lambda _endpoint: client)

    assert await router.cleanup_orphans() == []
    assert provider.active == {"/worktrees/tether-live"}
    await store.close()


@pytest.mark.asyncio
async def test_max_leases_does_not_limit_shared_mode(tmp_path):
    from tether.models import Conversation

    config = Config.model_validate({"projects": {"max_leases": 1}})
    client = FakeAgentClient()
    store = RouteStore(str(tmp_path / "r.db"))
    await store.connect()
    router = Router(
        config,
        store,
        build_provider(config),
        client_factory=lambda _endpoint: client,
    )

    first = await router.get_or_create(Conversation(channel="wecom", kind="direct", id="c1"))
    second = await router.get_or_create(Conversation(channel="wecom", kind="direct", id="c2"))

    assert first.key != second.key
    assert await store.get(first.key) is not None
    assert await store.get(second.key) is not None
    await store.close()


def test_client_cache_keys_include_base_url(tmp_path):
    created: list[ServerEndpoint] = []

    def factory(endpoint):
        created.append(endpoint)
        return FakeAgentClient()

    config = Config()
    router = Router(
        config,
        RouteStore(str(tmp_path / "r.db")),
        build_provider(config),
        client_factory=factory,
    )
    a = ServerEndpoint(
        id="lease",
        name="lease",
        backend="agentd",
        base_url="http://a",
        auth=None,
        working_directory=None,
        default_agent=None,
        default_model=None,
    )
    b = ServerEndpoint(
        id="lease",
        name="lease",
        backend="agentd",
        base_url="http://b",
        auth=None,
        working_directory=None,
        default_agent=None,
        default_model=None,
    )
    assert router.client_for_endpoint(a) is not router.client_for_endpoint(b)
    assert [endpoint.base_url for endpoint in created] == ["http://a", "http://b"]


@pytest.mark.asyncio
async def test_endpoint_defaults_are_used_with_shared_base_url(tmp_path):
    config = Config.model_validate(
        {
            "server": {
                "pool": [
                    {
                        "id": "a",
                        "name": "a",
                        "base_url": BASE,
                        "default_agent": "alpha",
                    },
                    {
                        "id": "b",
                        "name": "b",
                        "base_url": BASE,
                        "default_agent": "beta",
                    },
                ]
            }
        }
    )
    client = FakeAgentClient()
    client.agents = [AgentInfo("alpha"), AgentInfo("beta")]
    router = Router(
        config,
        RouteStore(str(tmp_path / "r.db")),
        build_provider(config),
        client_factory=lambda _endpoint: client,
    )
    endpoint_a, endpoint_b = config.server_endpoints()

    assert await router.resolve_agent(BASE, endpoint=endpoint_a) == "alpha"
    assert await router.resolve_agent(BASE, endpoint=endpoint_b) == "beta"

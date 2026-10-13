from __future__ import annotations

import pytest
from fakes import FakeAgentClient

from tether.agent.events import AgentInfo, ModelInfo
from tether.config import Config
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
    router = Router(config, store, build_provider(config), client_factory=lambda b, t: client)
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

from __future__ import annotations

import httpx
import pytest
from fakes import FakeAgentClient

from tether.config import Config
from tether.engine.projects import (
    AgentdControlProvider,
    SharedProjectProvider,
    build_provider,
)
from tether.engine.router import Router
from tether.models import Conversation
from tether.store.sqlite import RouteStore


def control_config(tmp_path, **over) -> Config:
    projects = {
        "mode": "isolated",
        "isolation": "worktree",
        "control_url": "http://127.0.0.1:9090",
        "source_directory": "/src/project",
        "base_dir": str(tmp_path / "views"),
        **over,
    }
    return Config.model_validate({"projects": projects})


def handler(request: httpx.Request) -> httpx.Response:
    if request.method == "POST" and request.url.path == "/admin/projects":
        return httpx.Response(
            201,
            json={
                "data": {
                    "project_id": "conv1",
                    "kind": "http",
                    "server_base": "http://127.0.0.1:5555",
                    "working_directory": "/views/conv1",
                    "readonly": False,
                }
            },
        )
    if request.method == "DELETE":
        return httpx.Response(204)
    if request.method == "GET" and request.url.path == "/admin/projects":
        return httpx.Response(200, json={"data": []})
    return httpx.Response(404)


def provider(tmp_path, config: Config | None = None) -> AgentdControlProvider:
    return AgentdControlProvider(
        config or control_config(tmp_path), transport=httpx.MockTransport(handler)
    )


@pytest.mark.asyncio
async def test_acquire_returns_view_lease(tmp_path):
    conv = Conversation(channel="wecom", kind="direct", id="u1")
    lease = await provider(tmp_path).acquire(conv, agent="build")
    assert lease.server_base == "http://127.0.0.1:5555"
    assert lease.working_directory == "/views/conv1"
    assert lease.ephemeral is True


@pytest.mark.asyncio
async def test_preflight_probes_control_api(tmp_path):
    await provider(tmp_path).preflight()  # must not raise


@pytest.mark.asyncio
async def test_acquire_without_config_raises(tmp_path):
    conv = Conversation(channel="wecom", kind="direct", id="u1")
    with pytest.raises(RuntimeError):
        await provider(tmp_path, Config()).acquire(conv, agent="build")


def test_build_provider_selects_control_for_isolated(tmp_path):
    assert isinstance(build_provider(control_config(tmp_path)), AgentdControlProvider)


def test_build_provider_selects_shared_by_default():
    assert isinstance(build_provider(Config()), SharedProjectProvider)


@pytest.mark.asyncio
async def test_isolated_route_reacquires_after_restart(tmp_path):
    config = control_config(tmp_path)
    client = FakeAgentClient()
    store = RouteStore(str(tmp_path / "r.db"))
    await store.connect()
    router = Router(
        config,
        store,
        AgentdControlProvider(config, transport=httpx.MockTransport(handler)),
        client_factory=lambda base, token: client,
    )
    conv = Conversation(channel="wecom", kind="direct", id="u1")
    route = await router.get_or_create(conv)
    first = route.session_id

    # Simulate a bridge restart: leases are in-memory and gone, the Route persists.
    router.leases._leases.clear()
    route2 = await router.get_or_create(conv)

    assert router.leases.get(conv.key) is not None  # a fresh view was leased
    assert route2.session_id != first  # and a new session was created on it
    await store.close()


@pytest.mark.asyncio
async def test_working_directory_falls_back_to_server_config(tmp_path):
    from tether.models import Route

    config = Config.model_validate(
        {"server": {"working_directory": "/wd"}, "projects": {"mode": "shared"}}
    )
    store = RouteStore(str(tmp_path / "r.db"))
    await store.connect()
    router = Router(config, store, SharedProjectProvider("http://x"))
    route = Route(
        conversation=Conversation(channel="fake", kind="direct", id="c"),
        session_id="s",
        server_base="http://x",
        agent="build",
    )
    assert router.working_directory(route) == "/wd"
    await store.close()

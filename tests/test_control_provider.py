from __future__ import annotations

import json
from pathlib import Path

import httpx
import pytest
from fakes import FakeAgentClient

from tether.agent.base import PermissionRule
from tether.config import Config, InboundPermissionRule, SandboxConfig
from tether.engine.projects import (
    AgentdControlProvider,
    OpenCodeWorktreeProvider,
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
    assert lease.endpoint_id == "agentd-lease:conv1"
    assert lease.backend == "agentd"
    assert lease.ephemeral is True


@pytest.mark.asyncio
async def test_preflight_probes_control_api_without_wiping_base_dir(tmp_path):
    config = control_config(tmp_path)
    marker = tmp_path / "views" / "keep.txt"
    marker.parent.mkdir(parents=True)
    marker.write_text("keep")
    await provider(tmp_path, config).preflight()  # must not raise
    assert marker.exists()


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
        client_factory=lambda _endpoint: client,
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


@pytest.mark.asyncio
async def test_acquire_passes_permissions_and_sandbox(tmp_path):
    config = control_config(tmp_path)
    config.projects.inbound_permissions = [
        InboundPermissionRule(action="bash", resource="*", effect="allow")
    ]
    config.projects.sandbox = SandboxConfig(process="seatbelt", failure_policy="fail-closed")
    seen: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(json.loads(request.content))
        return httpx.Response(201, json={"data": {"server_base": "http://x", "project_id": "p"}})

    provider = AgentdControlProvider(config, transport=httpx.MockTransport(handler))
    await provider.acquire(Conversation(channel="wecom", kind="direct", id="u1"), agent="build")
    assert seen["inboundPermissions"][0]["action"] == "bash"
    assert seen["sandbox"] == {"process": "seatbelt", "failurePolicy": "fail-closed"}


def opencode_config(tmp_path) -> Config:
    source = tmp_path / "source"
    source.mkdir()
    return Config.model_validate(
        {
            "server": {
                "pool": [
                    {
                        "id": "oc",
                        "name": "oc",
                        "backend": "opencode",
                        "base_url": "http://oc",
                        "auth": {"type": "basic", "username": "opencode", "password": "p"},
                        "working_directory": str(source),
                    }
                ]
            },
            "projects": {
                "mode": "isolated",
                "backend": "opencode",
                "endpoint": "oc",
                "isolation": "worktree",
                "source_directory": str(source),
                "base_dir": str(tmp_path / "worktrees"),
            },
        }
    )


@pytest.mark.asyncio
async def test_opencode_worktree_provider_create_and_release(tmp_path):
    config = opencode_config(tmp_path)
    source = config.projects.source_directory
    calls: list[tuple[str, str, dict]] = []

    def oc_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        calls.append((request.method, request.url.path, body))
        if request.method == "GET" and request.url.path == "/api/location":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "project": {
                            "id": "proj_1",
                            "canonical": source,
                        }
                    }
                },
            )
        if request.method == "GET" and request.url.path == "/api/worktree":
            return httpx.Response(200, json={"data": []})
        if request.method == "POST" and request.url.path == "/api/worktree":
            return httpx.Response(
                200,
                json={"data": {"directory": str(tmp_path / "worktrees" / body["name"])}},
            )
        if request.method == "DELETE" and request.url.path == "/api/worktree":
            return httpx.Response(204)
        return httpx.Response(404)

    provider = OpenCodeWorktreeProvider(
        config, config.server_endpoints(), transport=httpx.MockTransport(oc_handler)
    )
    await provider.preflight()
    assert not [call for call in calls if call[0] == "DELETE"]

    conv = Conversation(channel="wecom", kind="direct", id="u1")
    lease = await provider.acquire(conv, agent="build")
    assert lease.project_id == "proj_1"
    assert lease.endpoint_id == "oc"
    assert lease.backend == "opencode"
    assert lease.server_base == "http://oc"
    assert lease.working_directory is not None
    assert "tether-" in Path(lease.working_directory).name

    create = [call for call in calls if call[0] == "POST"][0][2]
    assert create["projectID"] == "proj_1"
    assert create["from"] == source
    assert create["branch"] == "HEAD"

    await provider.release(lease)
    delete = [call for call in calls if call[0] == "DELETE"][0][2]
    assert delete == {
        "projectID": "proj_1",
        "directory": lease.working_directory,
        "force": True,
    }


def test_build_provider_selects_opencode_worktree(tmp_path):
    assert isinstance(
        build_provider(opencode_config(tmp_path)), OpenCodeWorktreeProvider
    )


@pytest.mark.asyncio
async def test_opencode_cleanup_orphans_only_removes_unreferenced_tether_worktrees(tmp_path):
    config = opencode_config(tmp_path)
    seen: list[dict] = []

    def oc_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "DELETE":
            seen.append(json.loads(request.content))
        return httpx.Response(204)

    provider = OpenCodeWorktreeProvider(
        config, config.server_endpoints(), transport=httpx.MockTransport(oc_handler)
    )
    provider._project_id = "proj_1"
    known = {
        str(tmp_path / "worktrees" / "tether-a"),
        str(tmp_path / "worktrees" / "tether-b"),
        str(tmp_path / "worktrees" / "other"),
    }
    provider._known_worktrees = set(known)

    removed = await provider.cleanup_orphans(
        active={str(tmp_path / "worktrees" / "tether-b")},
        referenced={str(tmp_path / "worktrees" / "tether-a")},
    )
    assert removed == []
    assert seen == []

    removed = await provider.cleanup_orphans(active=set(), referenced=set())
    assert set(removed) == {
        str(tmp_path / "worktrees" / "tether-a"),
        str(tmp_path / "worktrees" / "tether-b"),
    }
    assert {item["directory"] for item in seen} == set(removed)
    assert all(item["projectID"] == "proj_1" for item in seen)


@pytest.mark.asyncio
async def test_isolated_opencode_route_uses_endpoint_and_worktree(tmp_path):
    config = opencode_config(tmp_path)
    config.projects.inbound_permissions = [
        InboundPermissionRule(action="bash", resource="*", effect="ask")
    ]
    source = config.projects.source_directory

    def oc_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        if request.method == "GET" and request.url.path == "/api/location":
            return httpx.Response(
                200,
                json={"data": {"project": {"id": "proj_1", "canonical": source}}},
            )
        if request.method == "POST" and request.url.path == "/api/worktree":
            return httpx.Response(
                200,
                json={"data": {"directory": str(tmp_path / "worktrees" / body["name"])}},
            )
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(404)

    provider = OpenCodeWorktreeProvider(
        config, config.server_endpoints(), transport=httpx.MockTransport(oc_handler)
    )
    client = FakeAgentClient()
    store = RouteStore(str(tmp_path / "r.db"))
    await store.connect()
    router = Router(
        config,
        store,
        provider,
        client_factory=lambda _endpoint: client,
    )
    route = await router.get_or_create(
        Conversation(channel="wecom", kind="direct", id="u1")
    )

    assert route.endpoint == "oc"
    assert route.backend == "opencode"
    assert route.location is not None
    assert "tether-" in Path(route.location).name
    assert client.sessions[route.session_id].location == route.location
    assert router.working_directory(route) == route.location
    assert client.created_permissions[-1] == [
        PermissionRule(action="bash", resource="*", effect="ask")
    ]
    await store.close()


@pytest.mark.asyncio
async def test_agentd_cleanup_orphans_skips_referenced_and_active_projects(tmp_path):
    deleted: list[str] = []

    def oc_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/admin/projects":
            return httpx.Response(200, json={"data": []})
        if request.method == "DELETE":
            deleted.append(request.url.path.rsplit("/", 1)[-1])
            return httpx.Response(204)
        return httpx.Response(404)

    provider = AgentdControlProvider(
        control_config(tmp_path), transport=httpx.MockTransport(oc_handler)
    )
    provider._known_projects = {"orphan", "route-ref", "active"}
    removed = await provider.cleanup_orphans(
        referenced={"route-ref"}, active={"active"}
    )
    assert removed == ["orphan"]
    assert deleted == ["orphan"]


@pytest.mark.asyncio
async def test_isolated_opencode_route_reacquires_after_restart(tmp_path):
    config = opencode_config(tmp_path)
    source = config.projects.source_directory
    worktrees = tmp_path / "worktrees"

    def oc_handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        if request.method == "GET" and request.url.path == "/api/location":
            return httpx.Response(
                200,
                json={"data": {"project": {"id": "proj_1", "canonical": source}}},
            )
        if request.method == "POST" and request.url.path == "/api/worktree":
            return httpx.Response(
                200, json={"data": {"directory": str(worktrees / body["name"])}}
            )
        if request.method == "DELETE":
            return httpx.Response(204)
        return httpx.Response(404)

    provider = OpenCodeWorktreeProvider(
        config, config.server_endpoints(), transport=httpx.MockTransport(oc_handler)
    )
    client = FakeAgentClient()
    store = RouteStore(str(tmp_path / "r.db"))
    await store.connect()
    router = Router(config, store, provider, client_factory=lambda _endpoint: client)
    conv = Conversation(channel="wecom", kind="direct", id="u1")
    route = await router.get_or_create(conv)
    first_session = route.session_id

    # A restart loses in-memory leases but keeps the Route.
    router.leases.forget_all()
    route2 = await router.get_or_create(conv)

    assert router.leases.get(conv.key) is not None
    assert route2.session_id != first_session
    assert route2.endpoint == "oc"
    assert route2.backend == "opencode"
    assert route2.location is not None
    await store.close()


@pytest.mark.asyncio
async def test_opencode_worktree_create_failure_does_not_leave_a_lease(tmp_path):
    config = opencode_config(tmp_path)
    source = config.projects.source_directory

    def oc_handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET" and request.url.path == "/api/location":
            return httpx.Response(
                200,
                json={"data": {"project": {"id": "proj_1", "canonical": source}}},
            )
        if request.method == "POST" and request.url.path == "/api/worktree":
            return httpx.Response(500, text="git worktree failed")
        return httpx.Response(404)

    provider = OpenCodeWorktreeProvider(
        config, config.server_endpoints(), transport=httpx.MockTransport(oc_handler)
    )
    with pytest.raises(RuntimeError, match="worktree create failed"):
        await provider.acquire(
            Conversation(channel="wecom", kind="direct", id="u1"), agent="build"
        )

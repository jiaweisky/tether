from __future__ import annotations

import json

import httpx
import pytest

from tether.agent.client import HttpAgentClient
from tether.agent.errors import AgentError


def make_client(handler) -> HttpAgentClient:
    transport = httpx.MockTransport(handler)
    raw = httpx.AsyncClient(transport=transport)
    return HttpAgentClient("http://test", "tok", client=raw)


def test_health_and_discovery():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/health":
            return httpx.Response(200, json={"data": {"healthy": True}})
        if request.url.path == "/api/agent":
            return httpx.Response(200, json={"data": [{"id": "build", "description": "b"}]})
        if request.url.path == "/api/tool":
            assert request.url.params["agent"] == "build"
            return httpx.Response(200, json={"data": [{"name": "read"}]})
        if request.url.path == "/api/model":
            return httpx.Response(200, json={"data": [{"id": "m", "input": ["text", "image"]}]})
        return httpx.Response(404, json={"error": "not_found"})

    client = make_client(handler)
    import asyncio

    async def run():
        assert await client.health() is True
        agents = await client.list_agents()
        assert agents[0].id == "build"
        tools = await client.agent_tools("build")
        assert tools[0].name == "read"
        models = await client.list_models()
        assert models[0].inputs == ["text", "image"]

    asyncio.run(run())


def test_error_mapping():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(409, json={"error": "conflict", "message": "busy"})

    client = make_client(handler)
    import asyncio

    async def run():
        with pytest.raises(AgentError) as exc:
            await client.create_session(agent="build")
        assert exc.value.code == "conflict"
        assert exc.value.status == 409

    asyncio.run(run())


def test_prompt_payload():
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/session/ses_1/prompt":
            captured.update(json.loads(request.content))
            return httpx.Response(202, json={"data": {"queued": True}})
        if request.method == "POST" and request.url.path == "/api/session":
            return httpx.Response(200, json={"data": {"id": "ses_1", "agent": "build"}})
        return httpx.Response(404)

    client = make_client(handler)
    import asyncio

    async def run():
        info = await client.create_session(agent="build", model="m")
        assert info.id == "ses_1"
        await client.prompt(
            info.id,
            prompt="hi",
            files=[
                {
                    "uri": "data:image/png;base64,AA",
                    "mime": "image/png",
                    "mediaSource": "inline",
                }
            ],
            id="fake:direct:None:d1:None:m1",
        )

    asyncio.run(run())
    assert captured["prompt"] == "hi"
    assert captured["id"].endswith(":m1")
    assert captured["files"][0]["mediaSource"] == "inline"


def test_events_parse_sse():
    body = (
        'event: message\ndata: {"id":"e1","type":"server.connected","data":{}}\n\n'
        'event: message\ndata: {"id":"e2","type":"session.next.text.delta",'
        '"data":{"sessionID":"ses_1","delta":"hi"}}\n\n'
        'event: message\ndata: {"id":"e3","type":"session.status",'
        '"data":{"sessionID":"ses_1","status":{"type":"idle"}}}\n\n'
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=body.encode()
        )

    client = make_client(handler)
    import asyncio

    async def run():
        events = []
        async for event in client.events():
            events.append(event)
        return events

    events = asyncio.run(run())
    assert [e.type for e in events] == [
        "server.connected",
        "session.next.text.delta",
        "session.status",
    ]
    assert events[1].session_id == "ses_1"
    assert events[1].data["delta"] == "hi"

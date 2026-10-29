from __future__ import annotations

import asyncio
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
            files=[{"uri": "data:image/png;base64,AA", "mime": "image/png", "name": "x.png"}],
            id="fake:direct:None:d1:None:m1",
        )

    asyncio.run(run())
    assert captured["prompt"] == "hi"
    assert captured["id"].endswith(":m1")
    assert captured["files"][0]["uri"].startswith("data:image/png")


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
        "text.delta",
        "turn.status",
    ]
    assert events[1].session_id == "ses_1"
    assert events[1].data.delta == "hi"


def test_create_session_parses_model_reference():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/session":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "id": "ses_1",
                        "agent": "build",
                        "model": {"id": "deepseek-flash", "providerID": "x", "variant": "default"},
                    }
                },
            )
        return httpx.Response(404)

    client = make_client(handler)
    import asyncio

    info = asyncio.run(client.create_session(agent="build"))
    assert info.model == "deepseek-flash"


def test_discovery_endpoints_and_shapes():
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/config":
            seen["config"] = dict(request.url.params)
            return httpx.Response(200, json={"data": {"config": {"x": 1}}})
        if path == "/api/info":
            return httpx.Response(200, json={"data": {"version": "1.2", "pid": 7}})
        if path == "/api/agent":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "build",
                            "description": "builder",
                            "mode": "primary",
                            "hidden": False,
                            "model": "m",
                            "backend": "go",
                        },
                        {"id": "hidden", "hidden": True},
                    ]
                },
            )
        if path == "/api/model":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "m1",
                            "protocol": "openai",
                            "input": ["text", "image"],
                            "sources": ["a", "b"],
                            "contextLimit": "1000",
                            "outputLimit": 200,
                        },
                        {"id": "m2", "input": "text"},
                    ]
                },
            )
        if path == "/api/tool":
            seen["tool_agent"] = request.url.params.get("agent")
            return httpx.Response(200, json={"data": [{"name": "read", "description": "r"}]})
        if path == "/api/session/active":
            return httpx.Response(200, json={"data": {"ses_1": {"type": "running"}}})
        return httpx.Response(404)

    client = make_client(handler)

    async def run():
        assert await client.get_config(section="servers", server="s1") == {
            "config": {"x": 1}
        }
        description = await client.describe()
        assert (description.version, description.pid) == ("1.2", 7)
        agents = await client.list_agents()
        assert [(a.id, a.description, a.mode, a.hidden, a.model, a.backend) for a in agents] == [
            ("build", "builder", "primary", False, "m", "go"),
            ("hidden", None, None, True, None, None),
        ]
        models = await client.list_models()
        assert [
            (m.id, m.protocol, m.inputs, m.sources, m.context_limit, m.output_limit)
            for m in models
        ] == [
            ("m1", "openai", ["text", "image"], ["a", "b"], 1000, 200),
            ("m2", None, ["text"], [], None, None),
        ]
        tools = await client.agent_tools("build")
        assert [(t.name, t.description) for t in tools] == [("read", "r")]
        assert await client.active_sessions() == {"ses_1"}

    asyncio.run(run())
    assert seen["config"] == {"section": "servers", "server": "s1"}
    assert seen["tool_agent"] == "build"


def test_health_is_false_for_unhealthy_or_non_dict():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"data": {"healthy": False}})

    client = make_client(handler)
    assert asyncio.run(client.health()) is False


def test_session_lifecycle_payloads_and_responses():
    seen: list[tuple[str, str, dict | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content) if request.content else None
        seen.append((request.method, path, body))
        if request.method == "POST" and path == "/api/session":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "id": "ses_1",
                        "agent": "build",
                        "model": {"id": "m1"},
                        "title": "T",
                    }
                },
            )
        if request.method == "GET" and path == "/api/session/ses_1":
            return httpx.Response(
                200,
                json={"data": {"id": "ses_1", "agent": "a", "model": "m2", "title": "G"}},
            )
        if request.method in ("POST", "DELETE"):
            return httpx.Response(204)
        return httpx.Response(404)

    client = make_client(handler)

    async def run():
        info = await client.create_session(agent="build", model="m1", title="T")
        assert (info.id, info.agent, info.model, info.title) == ("ses_1", "build", "m1", "T")
        got = await client.get_session("ses_1")
        assert (got.id, got.agent, got.model, got.title) == ("ses_1", "a", "m2", "G")
        await client.set_agent("ses_1", "plan")
        await client.set_model("ses_1", {"id": "m1", "providerID": "p"})
        await client.set_title("ses_1", "new")
        await client.delete_session("ses_1")

    asyncio.run(run())
    assert seen == [
        ("POST", "/api/session", {"agent": "build", "model": "m1", "title": "T"}),
        ("GET", "/api/session/ses_1", None),
        ("POST", "/api/session/ses_1/agent", {"agent": "plan"}),
        ("POST", "/api/session/ses_1/model", {"id": "m1", "providerID": "p"}),
        ("POST", "/api/session/ses_1/title", {"title": "new"}),
        ("DELETE", "/api/session/ses_1", None),
    ]


def test_prompt_payload_minimal_and_full():
    payloads: list[dict] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "POST" and request.url.path == "/api/session/ses_1/prompt":
            payloads.append(json.loads(request.content))
            return httpx.Response(202, json={"data": {"queued": True}})
        return httpx.Response(404)

    client = make_client(handler)

    async def run():
        await client.prompt("ses_1", prompt="hi")
        await client.prompt(
            "ses_1",
            prompt="with files",
            files=[{"uri": "data:x", "mime": "image/png", "name": "x.png"}],
            id="turn-1",
            delivery="steer",
        )
        return await client.prompt("ses_1", prompt="ignored", files=[], id="")

    result = asyncio.run(run())
    assert result is None
    assert payloads == [
        {"prompt": "hi", "delivery": "queue"},
        {
            "prompt": "with files",
            "delivery": "steer",
            "id": "turn-1",
            "files": [{"uri": "data:x", "mime": "image/png", "name": "x.png"}],
        },
        {"prompt": "ignored", "delivery": "queue"},
    ]


def test_execution_endpoints():
    seen: dict[str, object] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/api/session/ses_1/interrupt":
            seen["interrupt"] = (request.method, path)
            return httpx.Response(204)
        if path == "/api/session/ses_1/compact":
            return httpx.Response(200, json={"data": {"compacted": True}})
        if path == "/api/session/ses_1/wait":
            seen["wait"] = dict(request.url.params)
            return httpx.Response(200, json={"data": {"idle": True}})
        return httpx.Response(404)

    client = make_client(handler)

    async def run():
        await client.interrupt("ses_1")
        assert await client.compact("ses_1") is True
        assert await client.wait("ses_1", 7.9) is True

    asyncio.run(run())
    assert seen["interrupt"] == ("POST", "/api/session/ses_1/interrupt")
    assert seen["wait"] == {"timeout": "7s"}


def test_messages_and_history_accept_list_and_wrapped_shapes():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/session/ses_1/message":
            assert request.url.params["limit"] == "5"
            return httpx.Response(200, json={"data": [{"type": "assistant"}]})
        if request.url.path == "/api/session/ses_1/history":
            assert request.url.params["after"] == "3"
            assert request.url.params["limit"] == "4"
            return httpx.Response(200, json={"data": {"events": [{"type": "text"}]}})
        return httpx.Response(404)

    client = make_client(handler)

    async def run():
        assert await client.messages("ses_1", limit=5) == [{"type": "assistant"}]
        assert await client.history("ses_1", after=3, limit=4) == [{"type": "text"}]

    asyncio.run(run())


def test_interaction_lists_and_replies():
    seen: list[tuple[str, str, dict | None]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        body = json.loads(request.content) if request.content else None
        seen.append((request.method, path, body))
        if path in ("/api/permission", "/api/session/ses_1/permission"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "p1",
                            "sessionID": "ses_1",
                            "action": "read",
                            "resources": ["a"],
                        }
                    ]
                },
            )
        if path in ("/api/question", "/api/session/ses_1/question"):
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "q1",
                            "sessionID": "ses_1",
                            "questions": [
                                {
                                    "question": "Q?",
                                    "header": "H",
                                    "options": [{"label": "A", "description": "a"}],
                                    "multiple": True,
                                    "custom": True,
                                }
                            ],
                        }
                    ]
                },
            )
        if request.method == "POST":
            return httpx.Response(204)
        return httpx.Response(404)

    client = make_client(handler)

    async def run():
        perms = await client.list_permissions()
        assert perms[0].id == "p1" and perms[0].action == "read"
        assert len(await client.session_permissions("ses_1")) == 1
        qs = await client.list_questions()
        assert qs[0].id == "q1" and qs[0].questions[0].multiple is True
        assert qs[0].questions[0].key == "H"
        assert qs[0].questions[0].options[0].value == "A"
        assert len(await client.session_questions("ses_1")) == 1
        await client.reply_permission("ses_1", "p1", reply="always", message="ok")
        await client.reply_question("ses_1", "q1", [["A", "B"]])
        await client.reject_question("ses_1", "q1")

    asyncio.run(run())
    assert seen[-3:] == [
        (
            "POST",
            "/api/session/ses_1/permission/p1/reply",
            {"reply": "always", "message": "ok"},
        ),
        ("POST", "/api/session/ses_1/question/q1/reply", {"answers": [["A", "B"]]}),
        ("POST", "/api/session/ses_1/question/q1/reject", None),
    ]


def test_error_mapping_uses_error_object_and_plain_body():
    def make(handler):
        return make_client(handler)

    def object_error(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            409,
            json={"error": {"code": "conflict", "message": "busy", "ref": "r1"}},
        )

    client = make(object_error)
    with pytest.raises(AgentError) as exc:
        asyncio.run(client.create_session(agent="build"))
    assert (exc.value.code, exc.value.message, exc.value.status, exc.value.ref) == (
        "conflict",
        "busy",
        409,
        "r1",
    )

    def string_error(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"error": "not_found", "message": "gone"})

    client = make(string_error)
    with pytest.raises(AgentError) as exc:
        asyncio.run(client.get_session("ses_1"))
    assert (exc.value.code, exc.value.message, exc.value.status) == ("not_found", "gone", 404)

    def plain_error(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="oops")

    client = make(plain_error)
    with pytest.raises(AgentError) as exc:
        asyncio.run(client.describe())
    assert (exc.value.code, exc.value.status) == ("internal", 500)


def test_events_support_durable_session_fallback_and_error_frame():
    body = (
        'event: message\ndata: {"id":"e1","type":"session.next.tool.progress",'
        '"data":{"x":1},"durable":{"aggregateID":"ses_durable"}}\n\n'
        'data: {"id":"e2","type":"server.connected","data":{}}\n\n'
        "data: not-json\n\n"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=body.encode()
        )

    client = make_client(handler)

    async def run():
        return [event async for event in client.events()]

    events = asyncio.run(run())
    assert [event.type for event in events] == [
        "tool.progress",
        "server.connected",
    ]
    assert events[0].session_id == "ses_durable"
    assert events[0].durable == {"aggregateID": "ses_durable"}


def test_events_error_frame_raises_agent_error():
    body = 'event: error\ndata: subscriber_overflow\n\n'

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200, headers={"content-type": "text/event-stream"}, content=body.encode()
        )

    client = make_client(handler)

    async def run():
        async for _ in client.events():
            pass

    with pytest.raises(AgentError) as exc:
        asyncio.run(run())
    assert exc.value.code == "unavailable"
    assert exc.value.message == "subscriber_overflow"


def test_events_http_error_raises_unavailable():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, json={"error": "unavailable"})

    client = make_client(handler)

    async def run():
        async for _ in client.events():
            pass

    with pytest.raises(AgentError) as exc:
        asyncio.run(run())
    assert exc.value.code == "unavailable"
    assert exc.value.status == 503


def test_session_replay_pages_durable_history_and_parses_events():
    pages: list[dict[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path != "/api/session/ses_1/history":
            return httpx.Response(404)
        after = int(request.url.params["after"])
        limit = int(request.url.params["limit"])
        pages.append({"after": str(after), "limit": str(limit)})
        if after <= 0:
            rows = [
                {"id": "e0", "type": "session.created", "data": {"sessionID": "ses_1"},
                 "durable": {"aggregateID": "ses_1", "seq": 0, "version": 1}},
                {"id": "e1", "type": "session.next.text.delta",
                 "data": {"sessionID": "ses_1", "delta": "a"},
                 "durable": {"aggregateID": "ses_1", "seq": 1, "version": 1}},
            ]
        else:
            rows = [
                {"id": "e2", "type": "session.next.text.ended",
                 "data": {"sessionID": "ses_1", "text": "ab"},
                 "durable": {"aggregateID": "ses_1", "seq": 2, "version": 1}},
            ]
        return httpx.Response(200, json={"data": rows})

    client = make_client(handler)
    events = asyncio.run(client.session_replay("ses_1", after_seq=-1, limit=2))
    assert [event.type for event in events] == [
        "session.created",
        "text.delta",
        "text.ended",
    ]
    assert pages == [
        {"after": "-1", "limit": "2"},
        {"after": "1", "limit": "2"},
    ]


def test_turn_snapshot_scopes_to_current_turn():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            200,
            json={
                "data": [
                    {"type": "user", "content": [{"type": "text", "text": "old"}]},
                    {"type": "assistant", "content": [{"type": "text", "text": "old answer"}]},
                    {"type": "user", "content": [{"type": "text", "text": "new"}]},
                    {
                        "type": "assistant",
                        "content": [
                            {"type": "text", "text": "new answer"},
                            {
                                "type": "tool",
                                "state": {
                                    "content": [
                                        {
                                            "type": "file",
                                            "uri": "data:image/png;base64,AA",
                                            "mime": "image/png",
                                            "name": "x.png",
                                        }
                                    ]
                                },
                            },
                        ],
                    },
                ]
            },
        )

    client = make_client(handler)
    snapshot = asyncio.run(client.turn_snapshot("ses_1"))
    assert snapshot.text == "new answer"
    assert [item.name for item in snapshot.media] == ["x.png"]


def test_backend_profile_and_registry():
    from tether.agent.registry import create_backend
    from tether.config import AuthConfig, ServerEndpoint

    endpoint = ServerEndpoint(
        id="main",
        name="main",
        backend="agentd",
        base_url="http://test",
        auth=AuthConfig(type="bearer", token="tok"),
        working_directory=None,
        default_agent=None,
        default_model=None,
    )
    backend = create_backend(endpoint)
    assert backend.profile.backend_id == "agentd"
    assert backend.profile.supports_session_replay is True
    assert backend.endpoint_id == "main"


def test_describe_and_config_summary():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/info":
            return httpx.Response(200, json={"data": {"version": "1", "pid": 2}})
        if request.url.path == "/api/config":
            return httpx.Response(
                200,
                json={"data": {"config": {"default_agent": "build", "default_model": "m"}}},
            )
        return httpx.Response(404)

    client = make_client(handler)

    async def run():
        description = await client.describe()
        summary = await client.config_summary()
        return description, summary

    description, summary = asyncio.run(run())
    assert (description.backend_id, description.version, description.pid) == (
        "agentd",
        "1",
        2,
    )
    assert (summary.default_agent, summary.default_model) == ("build", "m")

from __future__ import annotations

import asyncio
import base64
import json

import httpx
import pytest

from tether.agent.base import FormAnswer, PermissionRule, PromptFile, QuestionAnswer
from tether.agent.errors import AgentError
from tether.agent.events import (
    QuestionAskedData,
    TextData,
    ToolCalledData,
    TurnStatusData,
)
from tether.agent.opencode.client import OpenCodeBackend
from tether.agent.opencode.events import OpenCodeEventMapper
from tether.agent.opencode.models import format_model_ref, parse_model_ref
from tether.agent.registry import create_backend
from tether.config import AuthConfig, ServerEndpoint


def make_client(handler, *, location: str | None = None) -> OpenCodeBackend:
    transport = httpx.MockTransport(handler)
    http = httpx.AsyncClient(transport=transport, base_url="http://oc")
    return OpenCodeBackend(
        "http://oc",
        username="opencode",
        password="secret",
        endpoint_id="site",
        location=location,
        client=http,
    )


def test_model_ref_round_trip():
    assert parse_model_ref("anthropic/claude#high") == {
        "providerID": "anthropic",
        "id": "claude",
        "variant": "high",
    }
    assert format_model_ref({"providerID": "anthropic", "id": "claude", "variant": "high"}) == (
        "anthropic/claude#high"
    )
    assert format_model_ref({"providerID": "a", "id": "b"}) == "a/b"
    with pytest.raises(ValueError):
        parse_model_ref("bare-model")


def test_opencode_registry_builds_backend_from_endpoint():
    endpoint = ServerEndpoint(
        id="site",
        name="site",
        backend="opencode",
        base_url="http://oc",
        auth=AuthConfig(type="basic", username="opencode", password="p"),
        working_directory="/work",
        default_agent=None,
        default_model=None,
    )
    backend = create_backend(endpoint)
    assert isinstance(backend, OpenCodeBackend)
    assert backend.endpoint_id == "site"
    assert backend.location == "/work"


def test_discovery_uses_basic_auth_and_location_and_synthesizes_build():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.url.path == "/api/agent":
            return httpx.Response(200, json={"data": []})
        if request.url.path == "/api/model":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "providerID": "anthropic",
                            "modelID": "claude",
                            "capabilities": {"input": ["text", "image"]},
                            "limit": {"context": 200000, "output": 8192},
                            "variants": [{"id": "high"}],
                        }
                    ]
                },
            )
        return httpx.Response(404)

    client = make_client(handler, location="/work")

    async def run():
        agents = await client.list_agents()
        models = await client.list_models()
        return agents, models

    agents, models = asyncio.run(run())
    assert [(a.id, a.mode, a.hidden) for a in agents] == [("build", "primary", False)]
    assert [model.id for model in models] == [
        "anthropic/claude",
        "anthropic/claude#high",
    ]
    assert models[0].context_limit == 200000
    expected = "Basic " + base64.b64encode(b"opencode:secret").decode()
    assert all(request.headers["authorization"] == expected for request in seen)
    assert all(request.url.params["location[directory]"] == "/work" for request in seen)


def test_session_prompt_and_lifecycle_shapes():
    requests: list[tuple[str, str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/doc":
            return httpx.Response(404)
        body = json.loads(request.content or b"{}")
        requests.append((request.method, request.url.path, body))
        if request.url.path == "/api/session" and request.method == "POST":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "id": "ses_1",
                        "agent": "build",
                        "model": {"providerID": "anthropic", "id": "claude", "variant": "high"},
                        "title": "T",
                        "location": {"directory": "/work"},
                    }
                },
            )
        return httpx.Response(204)

    client = make_client(handler)

    async def run():
        info = await client.create_session(
            agent="build",
            model="anthropic/claude#high",
            title="T",
            location="/work",
            permissions=[PermissionRule(action="bash", resource="*", effect="ask")],
        )
        await client.prompt(
            "ses_1",
            prompt="hi",
            files=[PromptFile(uri="data:image/png;base64,AA", mime="image/png", name="a.png")],
            id="r1",
        )
        await client.set_title("ses_1", "New")
        await client.run_command("ses_1", "review", "check")
        await client.activate_skill("ses_1", "skill-1")
        return info

    info = asyncio.run(run())
    assert info.model == "anthropic/claude#high"
    assert info.location == "/work"

    create = requests[0][2]
    assert create["model"] == {"providerID": "anthropic", "id": "claude", "variant": "high"}
    assert create["location"] == {"directory": "/work"}
    assert create["permissions"] == [{"action": "bash", "resource": "*", "effect": "ask"}]

    prompt = requests[1][2]
    assert prompt == {
        "text": "hi",
        "delivery": "queue",
        "files": [{"uri": "data:image/png;base64,AA", "name": "a.png"}],
    }
    assert requests[2][:2] == ("PATCH", "/api/session/ses_1")
    assert requests[3] == (
        "POST",
        "/api/session/ses_1/command",
        {"name": "review", "text": "check"},
    )
    assert requests[4] == (
        "POST",
        "/api/experimental/session/ses_1/skill",
        {"id": "skill-1", "resume": True},
    )


def test_events_map_text_execution_tool_and_form():
    def frame(payload: dict) -> str:
        return f"data: {json.dumps(payload)}\n\n"

    body = "".join(
        [
            frame({"id": "e0", "type": "server.connected", "data": {}}),
            frame(
                {
                    "id": "e1",
                    "type": "session.text.delta",
                    "data": {
                        "sessionID": "ses_1",
                        "assistantMessageID": "msg_1",
                        "ordinal": 0,
                        "delta": "He",
                    },
                }
            ),
            frame(
                {
                    "id": "e2",
                    "type": "session.text.ended",
                    "data": {
                        "sessionID": "ses_1",
                        "assistantMessageID": "msg_1",
                        "ordinal": 0,
                        "text": "Hello",
                    },
                }
            ),
            frame(
                {
                    "id": "e3",
                    "type": "session.tool.input.started",
                    "data": {
                        "sessionID": "ses_1",
                        "assistantMessageID": "msg_1",
                        "id": "tool_1",
                        "name": "read",
                    },
                }
            ),
            frame(
                {
                    "id": "e4",
                    "type": "session.tool.called",
                    "data": {
                        "sessionID": "ses_1",
                        "assistantMessageID": "msg_1",
                        "id": "tool_1",
                        "input": {},
                    },
                }
            ),
            frame(
                {
                    "id": "e5",
                    "type": "session.execution.succeeded",
                    "data": {"sessionID": "ses_1"},
                }
            ),
            frame(
                {
                    "id": "e6",
                    "type": "form.created",
                    "data": {
                        "form": {
                            "id": "frm_1",
                            "sessionID": "ses_1",
                            "title": "Q",
                            "metadata": {"kind": "question"},
                            "fields": [
                                {
                                    "key": "q0",
                                    "title": "Pick",
                                    "type": "string",
                                    "options": [{"value": "a", "label": "A"}],
                                }
                            ],
                        }
                    },
                }
            ),
        ]
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
        "server.connected",
        "text.delta",
        "text.ended",
        "tool.called",
        "tool.called",
        "turn.status",
        "question.asked",
    ]
    assert isinstance(events[1].data, TextData) and events[1].data.delta == "He"
    assert isinstance(events[2].data, TextData) and events[2].data.text == "Hello"
    assert isinstance(events[3].data, ToolCalledData) and events[3].data.name == "read"
    assert isinstance(events[4].data, ToolCalledData) and events[4].data.name == "read"
    assert isinstance(events[5].data, TurnStatusData) and events[5].data.status.type == "idle"
    assert events[6].session_id == "ses_1"
    assert isinstance(events[6].data, QuestionAskedData)
    assert events[6].data.request.questions[0].options[0].value == "a"


def test_snapshot_current_turn_and_pagination():
    pages = {
        None: {
            "data": [
                {"id": "u0", "type": "user", "text": "old"},
                {"id": "a0", "type": "assistant", "content": [{"type": "text", "text": "old"}]},
            ],
            "cursor": {"next": "p2"},
        },
        "p2": {
            "data": [
                {"id": "u1", "type": "user", "text": "new"},
                {
                    "id": "a1",
                    "type": "assistant",
                    "content": [
                        {"type": "text", "text": "new "},
                        {"type": "text", "text": "answer"},
                        {
                            "type": "tool",
                            "state": {
                                "status": "completed",
                                "content": [
                                    {
                                        "type": "file",
                                        "uri": "data:image/png;base64,AA",
                                        "mime": "image/png",
                                        "name": "x.png",
                                    }
                                ],
                            },
                        },
                    ],
                },
                {"id": "u2", "type": "user", "text": "later"},
            ],
            "cursor": {},
        },
    }

    def handler(request: httpx.Request) -> httpx.Response:
        cursor = request.url.params.get("cursor")
        return httpx.Response(200, json=pages[cursor])

    client = make_client(handler)
    snapshot = asyncio.run(client.turn_snapshot("ses_1", after_message_id="u0"))
    assert snapshot.text == "new answer"
    assert [media.name for media in snapshot.media] == ["x.png"]

    snapshot = asyncio.run(client.turn_snapshot("ses_1", after_message_id="u2"))
    assert snapshot.text is None
    assert snapshot.media == []


def test_forms_permissions_and_config_summary():
    calls: list[tuple[str, str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        calls.append((request.method, request.url.path, body))
        path = request.url.path
        if path == "/api/form":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "frm_1",
                            "sessionID": "ses_1",
                            "title": "Q",
                            "metadata": {"kind": "question"},
                            "fields": [
                                {
                                    "key": "q0",
                                    "title": "Pick",
                                    "type": "multiselect",
                                    "options": [{"value": "a", "label": "A"}],
                                }
                            ],
                        },
                        {
                            "id": "frm_2",
                            "sessionID": "ses_1",
                            "title": "Auth",
                            "metadata": {"kind": "external"},
                            "fields": [],
                        },
                    ]
                },
            )
        if path == "/api/permission/request":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "per_1",
                            "sessionID": "ses_1",
                            "action": "bash",
                            "resources": ["echo"],
                        }
                    ]
                },
            )
        if path == "/api/session/ses_1/form/frm_1":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "fields": [
                            {
                                "key": "q0",
                                "type": "multiselect",
                                "options": [{"value": "a", "label": "A"}],
                            }
                        ]
                    }
                },
            )
        if path == "/api/session/ses_1/form/frm_label":
            return httpx.Response(
                200,
                json={
                    "data": {
                        "fields": [
                            {
                                "key": "q0",
                                "type": "string",
                                "options": [{"value": "yes", "label": "Yes"}],
                            }
                        ]
                    }
                },
            )
        if path == "/api/config":
            return httpx.Response(
                200,
                json=[
                    {
                        "type": "document",
                        "info": {
                            "default_agent": "build",
                            "model": {"providerID": "anthropic", "id": "claude"},
                            "providers": {"anthropic": {"headers": {"x-secret": "s"}}},
                            "agents": {"build": {}},
                        },
                    }
                ],
            )
        return httpx.Response(204)

    client = make_client(handler, location="/work")

    async def run():
        forms = await client.list_questions()
        empty_location_forms = await client.list_questions(locations=[])
        perms = await client.list_permissions()
        await client.reply_question(
            "ses_1", "frm_1", QuestionAnswer(values={"q0": ["a"]})
        )
        await client.reply_question("ses_1", "frm_label", [["Yes"]])
        await client.reply_permission("ses_1", "per_1", reply="reject")
        summary = await client.config_summary()
        return forms, empty_location_forms, perms, summary

    forms, empty_location_forms, perms, summary = asyncio.run(run())
    assert [item.id for item in forms] == ["frm_1"]
    assert [item.id for item in empty_location_forms] == ["frm_1"]
    assert forms[0].questions[0].multiple is True
    assert [item.id for item in perms] == ["per_1"]
    assert summary.default_agent == "build"
    assert summary.default_model == "anthropic/claude"
    assert summary.providers == ["anthropic"]
    assert ("POST", "/api/session/ses_1/form/frm_1/reply", {"answer": {"q0": ["a"]}}) in calls
    assert ("POST", "/api/session/ses_1/form/frm_label/reply", {"answer": {"q0": "yes"}}) in calls
    assert (
        "POST",
        "/api/session/ses_1/permission/per_1/reply",
        {"decision": "reject"},
    ) in calls


def test_error_tag_mapping():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"_tag": "SessionNotFoundError", "message": "gone"})

    client = make_client(handler)
    with pytest.raises(AgentError) as exc:
        asyncio.run(client.get_session("missing"))
    assert (exc.value.code, exc.value.status) == ("not_found", 404)


def test_active_sessions_health_and_describe():
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/session/active":
            return httpx.Response(
                200,
                json={"data": {"ses_1": {"type": "running"}, "ses_2": {"type": "running"}}},
            )
        if request.url.path == "/api/info":
            return httpx.Response(
                200,
                json={"data": {"version": "1.2.3", "pid": 42, "urls": ["http://oc"]}},
            )
        return httpx.Response(404)

    client = make_client(handler, location="/work")

    async def run():
        return (
            await client.active_sessions(),
            await client.health(),
            await client.describe(),
        )

    active, healthy, description = asyncio.run(run())
    assert active == {"ses_1", "ses_2"}
    assert healthy is True
    assert description.version == "1.2.3"
    assert description.pid == 42
    assert description.locations == ["/work"]


def test_rich_forms_and_title_events():
    calls: list[tuple[str, str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content or b"{}")
        calls.append((request.method, request.url.path, body))
        if request.url.path == "/api/form":
            return httpx.Response(
                200,
                json={
                    "data": [
                        {
                            "id": "frm_auth",
                            "sessionID": "ses_1",
                            "title": "Authorize",
                            "metadata": {"kind": "external"},
                            "fields": [
                                {
                                    "key": "password",
                                    "type": "string",
                                    "title": "Password",
                                    "required": True,
                                    "when": [{"key": "kind", "op": "eq", "value": "token"}],
                                },
                                {
                                    "key": "remember",
                                    "type": "boolean",
                                    "default": True,
                                },
                            ],
                        }
                    ]
                },
            )
        return httpx.Response(204)

    client = make_client(handler, location="/work")

    async def run():
        forms = await client.list_forms()
        await client.reply_form("ses_1", "frm_auth", FormAnswer(values={"password": "x"}))
        return forms

    forms = asyncio.run(run())
    assert forms[0].id == "frm_auth"
    assert forms[0].fields[0].key == "password"
    assert forms[0].fields[0].required is True
    assert forms[0].fields[0].when[0]["op"] == "eq"
    assert forms[0].fields[1].default is True
    assert calls[-1] == (
        "POST",
        "/api/session/ses_1/form/frm_auth/reply",
        {"answer": {"password": "x"}},
    )

    event = OpenCodeEventMapper().map(
        {
            "id": "e1",
            "type": "session.renamed",
            "data": {"sessionID": "ses_1", "title": "New title"},
        }
    )
    assert event is not None
    assert event.type == "title.updated"
    assert event.session_id == "ses_1"
    assert event.data.title == "New title"

    form_event = OpenCodeEventMapper().map(
        {
            "id": "e2",
            "type": "form.created",
            "data": {
                "form": {
                    "id": "frm_external",
                    "sessionID": "ses_1",
                    "title": "Authorize",
                    "metadata": {"kind": "external"},
                    "fields": [{"key": "token", "type": "string"}],
                }
            },
        }
    )
    assert form_event is not None
    assert form_event.type == "form.asked"
    assert form_event.session_id == "ses_1"
    assert form_event.data.form.id == "frm_external"


def test_v1_protocol_is_detected_from_openapi_and_uses_nested_prompt():
    calls: list[tuple[str, str, dict]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/doc":
            return httpx.Response(
                200,
                json={
                    "paths": {
                        "/api/session/{sessionID}/prompt": {
                            "post": {
                                "requestBody": {
                                    "content": {
                                        "application/json": {
                                            "schema": {
                                                "properties": {
                                                    "prompt": {"type": "object"},
                                                    "delivery": {"type": "string"},
                                                }
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                },
            )
        body = json.loads(request.content or b"{}")
        calls.append((request.method, request.url.path, body))
        return httpx.Response(204)

    client = make_client(handler)
    asyncio.run(
        client.prompt(
            "ses_1",
            prompt="hi",
            files=[PromptFile(uri="data:image/png;base64,AA", name="a.png")],
        )
    )
    assert calls == [
        (
            "POST",
            "/api/session/ses_1/prompt",
            {
                "prompt": {
                    "text": "hi",
                    "files": [{"uri": "data:image/png;base64,AA", "name": "a.png"}],
                },
                "delivery": "queue",
            },
        )
    ]

    calls.clear()
    asyncio.run(client.reply_permission("ses_1", "per_1", reply="reject"))
    assert calls == [
        ("POST", "/api/session/ses_1/permission/per_1/reply", {"reply": "reject"})
    ]


def test_v1_event_mapper():
    from tether.agent.opencode.events import OpenCodeV1EventMapper

    mapper = OpenCodeV1EventMapper()
    delta = mapper.map(
        {
            "id": "e1",
            "type": "session.next.text.delta",
            "data": {
                "sessionID": "ses_1",
                "assistantMessageID": "msg_1",
                "textID": "text-0",
                "delta": "hi",
            },
        }
    )
    assert delta is not None and delta.type == "text.delta"
    ended = mapper.map(
        {
            "id": "e2",
            "type": "session.next.text.ended",
            "data": {
                "sessionID": "ses_1",
                "assistantMessageID": "msg_1",
                "textID": "text-0",
                "text": "hi",
            },
        }
    )
    assert ended is not None and ended.type == "text.ended"
    assert ended.data.text == "hi"
    idle = mapper.map(
        {"id": "e3", "type": "session.idle", "data": {"sessionID": "ses_1"}}
    )
    assert idle is not None and idle.type == "turn.status"
    assert idle.data.status.type == "idle"

    stepped = mapper.map_many(
        {
            "id": "e4",
            "type": "session.next.step.ended",
            "data": {"sessionID": "ses_1", "finish": "stop", "tokens": {}},
        }
    )
    assert [event.type for event in stepped] == ["step.ended", "turn.status"]
    assert stepped[1].data.status.type == "idle"

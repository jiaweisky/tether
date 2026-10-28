"""Live contract tests against a running OpenCode v2 server.

These tests are skipped by default. Run them manually with:

    OPENCODE_BASE_URL=http://127.0.0.1:4099 \
    OPENCODE_PASSWORD=... \
    .venv/bin/python -m pytest tests/test_opencode_live_contract.py -q

They assume:
- OpenCode is reachable at OPENCODE_BASE_URL with Basic auth.
- The server can access the temporary project path created by the test.
- git is available.
"""

from __future__ import annotations

import asyncio
import base64
import json
import os
import subprocess
from pathlib import Path

import httpx
import pytest
from httpx_sse import aconnect_sse

BASE_URL = os.environ.get("OPENCODE_BASE_URL")
PASSWORD = os.environ.get("OPENCODE_PASSWORD")
USERNAME = os.environ.get("OPENCODE_USERNAME", "opencode")

pytestmark = pytest.mark.skipif(
    not (BASE_URL and PASSWORD),
    reason="set OPENCODE_BASE_URL and OPENCODE_PASSWORD to run live OpenCode tests",
)


def _init_repo(path: Path) -> None:
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.email", "tether@example.com"], cwd=path, check=True)
    subprocess.run(["git", "config", "user.name", "Tether"], cwd=path, check=True)
    (path / "README.md").write_text("hello tether\n")
    subprocess.run(["git", "add", "README.md"], cwd=path, check=True)
    subprocess.run(["git", "commit", "-qm", "init"], cwd=path, check=True)


@pytest.mark.asyncio
async def test_opencode_live_contract(tmp_path_factory):
    project = tmp_path_factory.mktemp("opencode-project")
    _init_repo(project)
    worktree_base = tmp_path_factory.mktemp("opencode-worktrees")
    name = "tether-live-contract"
    worktree_dir: str | None = None
    session_id: str | None = None

    auth = httpx.BasicAuth(USERNAME, PASSWORD or "")

    async with httpx.AsyncClient(base_url=BASE_URL or "", auth=auth, timeout=120.0) as client:
        # auth + info
        unauth = await httpx.AsyncClient(base_url=BASE_URL or "", timeout=10.0).get("/api/info")
        assert unauth.status_code == 401
        info = (await client.get("/api/info")).json()
        assert info.get("version")
        assert info.get("pid") is not None

        # location -> project
        location = (
            await client.get("/api/location", params={"location[directory]": str(project)})
        ).json()
        project_id = location["project"]["id"]
        canonical = location["project"]["canonical"]
        assert await asyncio.to_thread(
            lambda: Path(canonical).resolve() == project.resolve()
        )

        try:
            # worktree create/list/remove
            created = await client.post(
                "/api/worktree",
                json={
                    "projectID": project_id,
                    "from": canonical,
                    "branch": "HEAD",
                    "directory": str(worktree_base),
                    "name": name,
                },
            )
            assert created.status_code == 200, created.text
            worktree_dir = created.json()["directory"]
            assert await asyncio.to_thread(os.path.isdir, worktree_dir)

            listed = (await client.get("/api/worktree", params={"projectID": project_id})).json()
            assert any(item["directory"] == worktree_dir for item in listed)

            # session create with location + permissions
            session = await client.post(
                "/api/session",
                json={
                    "title": "tether-live",
                    "model": None,
                    "location": {"directory": worktree_dir},
                    "permissions": [{"action": "bash", "resource": "*", "effect": "ask"}],
                },
            )
            assert session.status_code == 200, session.text
            session_data = session.json()["data"]
            session_id = session_data["id"]
            assert session_data["permissions"] == [
                {"action": "bash", "resource": "*", "effect": "ask"}
            ]
            assert session_data["location"]["directory"] == worktree_dir

            got = (await client.get(f"/api/session/{session_id}")).json()["data"]
            assert got["id"] == session_id
            assert got["location"]["directory"] == worktree_dir

            # form lifecycle
            form = await client.post(
                f"/api/session/{session_id}/form",
                json={
                    "title": "Questions",
                    "metadata": {"kind": "question"},
                    "fields": [
                        {
                            "key": "q0",
                            "title": "Pick",
                            "description": "Choose",
                            "type": "string",
                            "options": [{"value": "a", "label": "A"}, {"value": "b", "label": "B"}],
                            "custom": True,
                        }
                    ],
                },
            )
            assert form.status_code == 200, form.text
            form_id = form.json()["data"]["id"]
            forms = (await client.get(f"/api/session/{session_id}/form")).json()["data"]
            assert any(item["id"] == form_id for item in forms)
            reply = await client.post(
                f"/api/session/{session_id}/form/{form_id}/reply",
                json={"answer": {"q0": "a"}},
            )
            assert reply.status_code == 204
            detail = (await client.get(f"/api/session/{session_id}/form/{form_id}")).json()["data"]
            assert detail["state"] == {"status": "answered", "answer": {"q0": "a"}}

            # permission lifecycle
            perm = await client.post(
                f"/api/session/{session_id}/permission",
                json={"action": "bash", "resources": ["echo tether"]},
            )
            assert perm.status_code == 200, perm.text
            perm_data = perm.json()["data"]
            assert perm_data["effect"] == "ask"
            perm_id = perm_data["id"]
            perms = (await client.get(f"/api/session/{session_id}/permission")).json()["data"]
            assert any(item["id"] == perm_id for item in perms)
            decision = await client.post(
                f"/api/session/{session_id}/permission/{perm_id}/reply",
                json={"decision": "reject"},
            )
            assert decision.status_code == 204

            # SSE event shape (form/permission events are ephemeral; trigger while listening)
            seen: list[str] = []

            async def listen() -> None:
                async with aconnect_sse(
                    client,
                    "GET",
                    "/api/event",
                    headers={"Accept": "text/event-stream"},
                    timeout=None,
                ) as source:
                    async for sse in source.aiter_sse():
                        if not sse.data:
                            continue
                        try:
                            event_type = httpx.Response(200, content=sse.data).json().get("type")
                        except ValueError:
                            continue
                        if event_type:
                            seen.append(str(event_type))
                        if "form.created" in seen and "permission.asked" in seen:
                            return

            task = asyncio.create_task(listen())
            await asyncio.sleep(1)
            await client.post(
                f"/api/session/{session_id}/form",
                json={
                    "title": "EventQuestion",
                    "metadata": {"kind": "question"},
                    "fields": [
                        {
                            "key": "q0",
                            "title": "Pick",
                            "type": "string",
                            "options": [{"value": "a", "label": "A"}],
                        }
                    ],
                },
            )
            await client.post(
                f"/api/session/{session_id}/permission",
                json={"action": "bash", "resources": ["echo event"]},
            )
            try:
                await asyncio.wait_for(task, timeout=15)
            finally:
                task.cancel()
            assert "server.connected" in seen
            assert "form.created" in seen
            assert "permission.asked" in seen

        finally:
            if session_id:
                await client.delete(f"/api/session/{session_id}")
            if worktree_dir:
                await client.request(
                    "DELETE",
                    "/api/worktree",
                    json={"projectID": project_id, "directory": worktree_dir, "force": True},
                )


@pytest.mark.asyncio
async def test_opencode_live_api_surface(tmp_path_factory):
    project = tmp_path_factory.mktemp("opencode-api-surface")
    _init_repo(project)
    auth = httpx.BasicAuth(USERNAME, PASSWORD or "")
    session_id: str | None = None

    async with httpx.AsyncClient(base_url=BASE_URL or "", auth=auth, timeout=120.0) as client:
        location_params = {"location[directory]": str(project)}
        location = (await client.get("/api/location", params=location_params)).json()
        project_id = location["project"]["id"]

        # default model / agent get / config
        default_model = (await client.get("/api/model/default", params=location_params)).json()
        assert default_model.get("location")
        assert "data" in default_model

        agents = (await client.get("/api/agent", params=location_params)).json()["data"]
        if agents:
            got_agent = await client.get(f"/api/agent/{agents[0]['id']}", params=location_params)
            assert got_agent.status_code == 200
            assert got_agent.json()["data"]["id"] == agents[0]["id"]

        config = await client.get("/api/config", params=location_params)
        assert config.status_code == 200
        assert isinstance(config.json(), list)
        shells = await client.get("/api/config/shell")
        assert shells.status_code == 200
        commands = await client.get("/api/command", params=location_params)
        assert commands.status_code == 200
        assert isinstance(commands.json()["data"], list)
        skills = await client.get("/api/skill", params=location_params)
        assert skills.status_code == 200
        assert isinstance(skills.json()["data"], list)

        # session list
        created = await client.post(
            "/api/session",
            json={
                "title": "surface",
                "location": {"directory": str(project)},
                "permissions": [{"action": "bash", "resource": "*", "effect": "ask"}],
            },
        )
        assert created.status_code == 200, created.text
        session_id = created.json()["data"]["id"]
        sessions = await client.get("/api/session", params={"directory": str(project)})
        assert sessions.status_code == 200
        assert any(item["id"] == session_id for item in sessions.json()["data"])

        # session patch title + agent/model no-op switches
        patch = await client.patch(f"/api/session/{session_id}", json={"title": "surface-updated"})
        assert patch.status_code == 204
        updated = (await client.get(f"/api/session/{session_id}")).json()["data"]
        assert updated["title"] == "surface-updated"
        switch = await client.post(f"/api/session/{session_id}/agent", json={"agent": "build"})
        assert switch.status_code == 204

        # prompt resume=false: durable inbox admission without execution
        prompt = await client.post(
            f"/api/session/{session_id}/prompt",
            json={"text": "queued surface prompt", "resume": False, "delivery": "queue"},
        )
        assert prompt.status_code == 200, prompt.text
        inbox_item = prompt.json()["data"]
        assert inbox_item["payload"]["text"] == "queued surface prompt"
        assert inbox_item["delivery"] == "queue"

        inbox = (await client.get(f"/api/session/{session_id}/inbox")).json()["data"]
        assert any(item["id"] == inbox_item["id"] for item in inbox)
        cancel = await client.delete(f"/api/session/{session_id}/inbox/{inbox_item['id']}")
        assert cancel.status_code == 204
        inbox_after = (await client.get(f"/api/session/{session_id}/inbox")).json()["data"]
        assert all(item["id"] != inbox_item["id"] for item in inbox_after)

        # synthetic resume=false: durable synthetic input, then cancel
        synthetic = await client.post(
            f"/api/session/{session_id}/synthetic",
            json={"text": "synthetic context", "resume": False, "description": "spike"},
        )
        assert synthetic.status_code == 200, synthetic.text
        synthetic_item = synthetic.json()["data"]
        assert synthetic_item["payload"]["text"] == "synthetic context"
        await client.delete(f"/api/session/{session_id}/inbox/{synthetic_item['id']}")

        # idle session introspection
        context = await client.get(f"/api/session/{session_id}/context")
        assert context.status_code == 200
        assert isinstance(context.json()["data"], list)
        active = await client.get("/api/session/active")
        assert active.status_code == 200
        assert session_id not in active.json()["data"]
        interrupt = await client.post(f"/api/session/{session_id}/interrupt")
        assert interrupt.status_code == 200
        assert interrupt.json() == {"interrupted": False}
        background = await client.post(f"/api/session/{session_id}/background")
        assert background.status_code == 204
        view = await client.post(f"/api/session/{session_id}/view", json={"idle": 0})
        assert view.status_code == 204
        environment = await client.put(
            f"/api/session/{session_id}/environment", json={"variables": {"TETHER_SPIKE": "1"}}
        )
        assert environment.status_code == 204

        pty_list = await client.get("/api/pty", params=location_params)
        assert pty_list.status_code == 200
        assert isinstance(pty_list.json()["data"], list)
        pty_create = await client.post(
            "/api/pty",
            params=location_params,
            json={"command": "/bin/sh", "args": ["-lc", "exit 0"], "title": "tether probe"},
        )
        assert pty_create.status_code == 200, pty_create.text
        pty_id = pty_create.json()["data"]["id"]
        pty_remove = await client.delete(f"/api/pty/{pty_id}", params=location_params)
        assert pty_remove.status_code == 204

        # unknown command/skill error shapes
        command = await client.post(
            f"/api/session/{session_id}/command", json={"name": "definitely_missing", "text": ""}
        )
        assert command.status_code == 404
        assert command.json().get("_tag") == "CommandNotFoundError"
        skill = await client.post(
            f"/api/experimental/session/{session_id}/skill", json={"id": "definitely-missing"}
        )
        assert skill.status_code == 404
        assert skill.json().get("_tag") == "SkillNotFoundError"

        # global form list by location
        forms = await client.get("/api/form", params=location_params)
        assert forms.status_code == 200
        assert isinstance(forms.json()["data"], list)

        # saved permission lifecycle: reply "always" creates a saved permission
        perm = await client.post(
            f"/api/session/{session_id}/permission",
            json={"action": "bash", "resources": ["echo saved"]},
        )
        assert perm.status_code == 200, perm.text
        perm_id = perm.json()["data"]["id"]
        reply = await client.post(
            f"/api/session/{session_id}/permission/{perm_id}/reply", json={"decision": "always"}
        )
        assert reply.status_code == 204
        saved = await client.get("/api/permission/saved")
        assert saved.status_code == 200
        saved_items = saved.json()["data"]
        if saved_items:
            removed = await client.delete(f"/api/permission/saved/{saved_items[-1]['id']}")
            assert removed.status_code == 204

        # permission.create is an evaluation endpoint: only effect=ask creates a pending request
        probe = await client.post(
            "/api/session",
            json={"title": "permission-probe", "location": {"directory": str(project)}},
        )
        probe_id = probe.json()["data"]["id"]
        try:
            evaluated = await client.post(
                f"/api/session/{probe_id}/permission",
                json={"action": "bash", "resources": ["echo probe"]},
            )
            assert evaluated.status_code == 200
            effect = evaluated.json()["data"]["effect"]
            assert effect in {"allow", "deny", "ask"}
            pending = (await client.get(f"/api/session/{probe_id}/permission")).json()["data"]
            if effect == "ask":
                assert any(item["id"] == evaluated.json()["data"]["id"] for item in pending)
            else:
                assert pending == []
                reply = await client.post(
                    f"/api/session/{probe_id}/permission/{evaluated.json()['data']['id']}/reply",
                    json={"decision": "once"},
                )
                assert reply.status_code == 404
                assert reply.json().get("_tag") == "PermissionNotFoundError"
        finally:
            await client.delete(f"/api/session/{probe_id}")

        # project list is available (do not patch canonical paths)
        projects = await client.get("/api/project")
        assert projects.status_code == 200
        assert any(item["id"] == project_id for item in projects.json())

    if session_id:
        async with httpx.AsyncClient(base_url=BASE_URL or "", auth=auth, timeout=30.0) as client:
            await client.delete(f"/api/session/{session_id}")


MODEL = os.environ.get("OPENCODE_MODEL")


@pytest.mark.skipif(not MODEL, reason="set OPENCODE_MODEL=provider/model to run model-backed tests")
@pytest.mark.asyncio
async def test_opencode_live_model_contract(tmp_path_factory):
    project = tmp_path_factory.mktemp("opencode-model-contract")
    _init_repo(project)
    (project / "image.png").write_bytes(
        base64.b64decode(
            "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNk"
            "+A8AAQUBAScY42YAAAAASUVORK5CYII="
        )
    )
    provider, model_id = (MODEL or "").split("/", 1)
    auth = httpx.BasicAuth(USERNAME, PASSWORD or "")
    session_id: str | None = None
    events: list[tuple[str, dict]] = []

    async with httpx.AsyncClient(base_url=BASE_URL or "", auth=auth, timeout=120.0) as client:
        created = await client.post(
            "/api/session",
            json={
                "title": "model-contract",
                "model": {"providerID": provider, "id": model_id},
                "location": {"directory": str(project)},
                "permissions": [{"action": "*", "resource": "*", "effect": "allow"}],
            },
        )
        assert created.status_code == 200, created.text
        session_id = created.json()["data"]["id"]

        async def listen() -> None:
            async with aconnect_sse(
                client,
                "GET",
                "/api/event",
                headers={"Accept": "text/event-stream"},
                timeout=None,
            ) as source:
                async for sse in source.aiter_sse():
                    if not sse.data:
                        continue
                    try:
                        data = json.loads(sse.data)
                    except ValueError:
                        continue
                    events.append((str(data.get("type")), data.get("data") or {}))

        task = asyncio.create_task(listen())
        await asyncio.sleep(0.5)

        async def wait_for(kind: str, start: int, limit_s: float = 90.0) -> dict:
            deadline = asyncio.get_running_loop().time() + limit_s
            while asyncio.get_running_loop().time() < deadline:
                for event_type, data in events[start:]:
                    if event_type == "session.execution.failed":
                        raise AssertionError(f"execution failed: {data}")
                    if event_type == kind:
                        return data
                await asyncio.sleep(0.2)
            seen = [event_type for event_type, _ in events[start:]]
            raise AssertionError(f"timed out waiting for {kind}; saw {seen}")

        try:
            start = len(events)
            response = await client.post(
                f"/api/session/{session_id}/prompt",
                json={"text": "Reply with exactly: tether-live-ok"},
            )
            assert response.status_code == 200
            ended = await wait_for("session.text.ended", start)
            assert "tether-live-ok" in ended["text"]
            await wait_for("session.execution.succeeded", start)

            start = len(events)
            response = await client.post(
                f"/api/session/{session_id}/prompt",
                json={"text": "Use the read tool to read README.md and tell me its content."},
            )
            assert response.status_code == 200
            tool = await wait_for("session.tool.success", start)
            assert any(
                "hello tether" in str(part.get("text", ""))
                for part in tool.get("content", [])
            )
            await wait_for("session.execution.succeeded", start)

            start = len(events)
            response = await client.post(
                f"/api/session/{session_id}/prompt",
                json={"text": "Use the read tool to read image.png and tell me what you see."},
            )
            assert response.status_code == 200
            image_tool = await wait_for("session.tool.success", start)
            image_parts = [
                part for part in image_tool.get("content", []) if part.get("type") == "file"
            ]
            assert image_parts, image_tool
            assert image_parts[0]["mime"].startswith("image/")
            assert image_parts[0]["uri"].startswith("data:image/")
            await wait_for("session.execution.succeeded", start)

            start = len(events)
            response = await client.post(
                f"/api/session/{session_id}/prompt",
                json={
                    "text": (
                        "Use the write tool to create tether-live.txt with content hello-live. "
                        "Then say done."
                    )
                },
            )
            assert response.status_code == 200
            step = await wait_for("session.step.ended", start)
            assert "tether-live.txt" in (step.get("files") or [])
            await wait_for("session.execution.succeeded", start)
            diff = await client.get(f"/api/session/{session_id}/diff")
            assert diff.status_code == 200
            assert any(item["file"] == "tether-live.txt" for item in diff.json()["data"])

            idle = await client.post(f"/api/experimental/session/{session_id}/wait")
            assert idle.status_code == 204

            messages = (
                await client.get(f"/api/session/{session_id}/message", params={"order": "asc"})
            ).json()["data"]
            user_messages = [item for item in messages if item.get("type") == "user"]
            assert user_messages
            last_user = user_messages[-1]["id"]

            fork = await client.post(f"/api/session/{session_id}/fork", json={})
            assert fork.status_code == 200, fork.text
            fork_id = fork.json()["data"]["id"]
            assert fork_id != session_id
            await client.delete(f"/api/session/{fork_id}")

            staged = await client.post(
                f"/api/session/{session_id}/revert/stage",
                json={"messageID": last_user, "files": False},
            )
            assert staged.status_code == 200, staged.text
            cleared = await client.delete(f"/api/session/{session_id}/revert")
            assert cleared.status_code == 204

            skill_response = await client.get(
                "/api/skill", params={"location[directory]": str(project)}
            )
            skills = skill_response.json()["data"]
            if skills:
                activated = await client.post(
                    f"/api/experimental/session/{session_id}/skill",
                    json={"id": skills[0]["id"], "resume": False},
                )
                assert activated.status_code == 204

            commands = (
                await client.get("/api/command", params={"location[directory]": str(project)})
            ).json()["data"]
            if any(item.get("id") == "review" or item.get("name") == "review" for item in commands):
                start = len(events)
                review = await client.post(
                    f"/api/session/{session_id}/command", json={"name": "review", "text": ""}
                )
                assert review.status_code == 204
                await wait_for("session.execution.succeeded", start)

            compact = await client.post(f"/api/session/{session_id}/compact", json={})
            assert compact.status_code == 200
            assert "data" in compact.json()
        finally:
            task.cancel()
            if session_id:
                await client.delete(f"/api/session/{session_id}")


REASONING_MODEL = os.environ.get("OPENCODE_REASONING_MODEL")


def _parse_model(value: str) -> dict:
    ref, _, variant = value.partition("#")
    provider, _, model_id = ref.partition("/")
    return {
        "providerID": provider,
        "id": model_id,
        **({"variant": variant} if variant else {}),
    }


@pytest.mark.skipif(
    not REASONING_MODEL,
    reason="set OPENCODE_REASONING_MODEL=provider/model#variant to run reasoning tests",
)
@pytest.mark.asyncio
async def test_opencode_live_reasoning_contract(tmp_path_factory):
    project = tmp_path_factory.mktemp("opencode-reasoning-contract")
    _init_repo(project)
    auth = httpx.BasicAuth(USERNAME, PASSWORD or "")
    session_id: str | None = None
    events: list[tuple[str, dict]] = []

    async with httpx.AsyncClient(base_url=BASE_URL or "", auth=auth, timeout=120.0) as client:
        created = await client.post(
            "/api/session",
            json={
                "title": "reasoning-contract",
                "model": _parse_model(REASONING_MODEL or ""),
                "location": {"directory": str(project)},
                "permissions": [{"action": "*", "resource": "*", "effect": "allow"}],
            },
        )
        assert created.status_code == 200, created.text
        session_id = created.json()["data"]["id"]

        async def listen() -> None:
            async with aconnect_sse(
                client,
                "GET",
                "/api/event",
                headers={"Accept": "text/event-stream"},
                timeout=None,
            ) as source:
                async for sse in source.aiter_sse():
                    if not sse.data:
                        continue
                    try:
                        data = json.loads(sse.data)
                    except ValueError:
                        continue
                    events.append((str(data.get("type")), data.get("data") or {}))

        task = asyncio.create_task(listen())
        await asyncio.sleep(0.5)
        try:
            response = await client.post(
                f"/api/session/{session_id}/prompt",
                json={"text": "Think briefly step by step, then reply exactly: reasoning-ok"},
            )
            assert response.status_code == 200, response.text

            deadline = asyncio.get_running_loop().time() + 90
            while asyncio.get_running_loop().time() < deadline:
                types = [event_type for event_type, _ in events]
                if "session.reasoning.ended" in types and "session.execution.succeeded" in types:
                    break
                if "session.execution.failed" in types:
                    raise AssertionError(events)
                await asyncio.sleep(0.2)
            else:
                raise AssertionError(f"reasoning did not complete: {[e[0] for e in events]}")

            reasoning = [
                data for event_type, data in events if event_type == "session.reasoning.ended"
            ]
            assert reasoning
            assert reasoning[-1].get("text")
            deltas = [
                data for event_type, data in events if event_type == "session.reasoning.delta"
            ]
            assert deltas
        finally:
            task.cancel()
            if session_id:
                await client.delete(f"/api/session/{session_id}")

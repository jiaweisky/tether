from __future__ import annotations

import sys

import pytest

from tether.config import Config
from tether.engine.projects import SupervisorProjectProvider, build_provider
from tether.models import Conversation

SUPERVISOR_SCRIPT = """
import json, sys
request = json.load(sys.stdin)
if request["action"] == "acquire":
    print(json.dumps({
        "project_id": request["project_id"],
        "server_base": "http://127.0.0.1:9999",
        "working_directory": "/wd",
        "ephemeral": True,
    }))
else:
    print(json.dumps({"ok": True}))
"""


def supervisor_config(command: str) -> Config:
    # "worktree" is a non-pool/non-shared provider, so build_provider selects the
    # supervisor-backed implementation.
    return Config.model_validate(
        {"projects": {"provider": "worktree", "supervisor_command": command}}
    )


def write_script(tmp_path, body: str) -> str:
    script = tmp_path / "supervisor.py"
    script.write_text(body)
    return f"{sys.executable} {script}"


@pytest.mark.asyncio
async def test_acquire_returns_lease(tmp_path):
    provider = SupervisorProjectProvider(
        supervisor_config(write_script(tmp_path, SUPERVISOR_SCRIPT))
    )
    conv = Conversation(channel="fake", kind="direct", id="d1")
    lease = await provider.acquire(conv, agent="build", readonly=False)
    assert lease.server_base == "http://127.0.0.1:9999"
    assert lease.working_directory == "/wd"
    assert lease.ephemeral is True
    assert lease.project_id == conv.key


@pytest.mark.asyncio
async def test_release_invokes_supervisor(tmp_path):
    provider = SupervisorProjectProvider(
        supervisor_config(write_script(tmp_path, SUPERVISOR_SCRIPT))
    )
    conv = Conversation(channel="fake", kind="direct", id="d1")
    lease = await provider.acquire(conv, agent="build", readonly=False)
    await provider.release(lease)  # must not raise


@pytest.mark.asyncio
async def test_acquire_without_command_raises():
    provider = SupervisorProjectProvider(Config())
    conv = Conversation(channel="fake", kind="direct", id="d1")
    with pytest.raises(RuntimeError):
        await provider.acquire(conv, agent="build", readonly=False)


@pytest.mark.asyncio
async def test_preflight_without_command_raises():
    with pytest.raises(RuntimeError):
        await SupervisorProjectProvider(Config()).preflight()


@pytest.mark.asyncio
async def test_failing_command_raises(tmp_path):
    command = f"{sys.executable} -c 'import sys; sys.exit(3)'"
    provider = SupervisorProjectProvider(supervisor_config(command))
    conv = Conversation(channel="fake", kind="direct", id="d1")
    with pytest.raises(RuntimeError):
        await provider.acquire(conv, agent="build", readonly=False)


@pytest.mark.asyncio
async def test_build_provider_selects_supervisor(tmp_path):
    provider = build_provider(supervisor_config(write_script(tmp_path, SUPERVISOR_SCRIPT)))
    assert isinstance(provider, SupervisorProjectProvider)

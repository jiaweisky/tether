"""Lease project instances for conversations.

A "project" is one agentd server unit bound to one working directory. The bridge
never starts agentd itself; it acquires and returns leases through a provider,
and tracks their lifetime.

Two modes (config ``projects.mode``):

- ``shared``: every conversation uses the same instance(s) — the configured
  ``server.pool`` if present, otherwise the single ``server.base_url``.
- ``isolated``: every conversation leases its own view of ``source_directory``
  through agentd's control API (``/admin/projects``).
"""

from __future__ import annotations

import asyncio
import hashlib
import itertools
import os
import re
import shutil
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from typing import Any, Protocol

import httpx

from ..config import Config
from ..models import Conversation
from ..util.logging import get_logger

log = get_logger("tether.projects")


@dataclass
class ProjectLease:
    project_id: str
    transport: str = "http"
    server_base: str = ""
    working_directory: str | None = None
    ephemeral: bool = False


class ProjectProvider(Protocol):
    async def acquire(
        self, conv: Conversation, *, agent: str, transport: str = "http"
    ) -> ProjectLease: ...

    async def release(self, lease: ProjectLease) -> None: ...

    async def preflight(self) -> None: ...


class SharedProjectProvider:
    """One instance shared by all conversations."""

    def __init__(
        self, server_base: str, *, working_directory: str | None = None, project_id: str = "shared"
    ) -> None:
        self._lease = ProjectLease(
            project_id=project_id, server_base=server_base, working_directory=working_directory
        )

    async def acquire(
        self, conv: Conversation, *, agent: str, transport: str = "http"
    ) -> ProjectLease:
        return self._lease

    async def release(self, lease: ProjectLease) -> None:
        return None

    async def preflight(self) -> None:
        return None


class PoolProjectProvider:
    """A fixed pool of instances shared round-robin across conversations."""

    def __init__(self, pool: Sequence[tuple[str, str, str | None]]) -> None:
        self._entries = list(pool)
        self._round_robin = itertools.cycle(range(len(pool))) if pool else None

    async def acquire(
        self, conv: Conversation, *, agent: str, transport: str = "http"
    ) -> ProjectLease:
        if not self._entries or self._round_robin is None:
            raise RuntimeError("the project pool is empty")
        name, base, working_directory = self._entries[next(self._round_robin)]
        return ProjectLease(project_id=name, server_base=base, working_directory=working_directory)

    async def release(self, lease: ProjectLease) -> None:
        return None

    async def preflight(self) -> None:
        if not self._entries:
            raise RuntimeError("the project pool is empty")


class AgentdControlProvider:
    """Lease per-conversation isolated views from agentd's control API.

    Each conversation gets its own view (``worktree``/``overlay``/``copy``) of
    ``source_directory``; the view is created on first use and released on idle.
    """

    def __init__(
        self, config: Config, *, transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.config = config
        self._transport = transport
        projects = config.projects
        self._base = (projects.control_url or "").rstrip("/")
        self._source = projects.source_directory
        self._base_dir = os.path.abspath(projects.base_dir)
        self._headers = (
            {"Authorization": f"Bearer {projects.control_token}"} if projects.control_token else {}
        )

    async def acquire(
        self, conv: Conversation, *, agent: str, transport: str = "http"
    ) -> ProjectLease:
        self._require_configured()
        name = _project_name(conv)
        request: dict[str, Any] = {
            "name": name,
            "kind": transport,
            # The view lives at <base_dir>/<name>; keep the state root outside it.
            "root": os.path.join(self._base_dir, ".state", name),
            "workingDirectory": self._source,
            "agents": [agent],
            "isolation": {
                "mode": self.config.projects.isolation,
                "baseDir": self._base_dir,
                "baseRef": self.config.projects.git_base_ref,
                "baseReadOnly": self.config.projects.cow.base_readonly,
                "cow": {"mode": self.config.projects.cow.mode},
            },
        }
        if self.config.projects.inbound_permissions:
            request["inboundPermissions"] = [
                rule.model_dump() for rule in self.config.projects.inbound_permissions
            ]
        sandbox = self.config.projects.sandbox
        if sandbox is not None and sandbox.process != "none":
            request["sandbox"] = {
                "process": sandbox.process,
                "failurePolicy": sandbox.failure_policy,
            }
        data = await self._create(request, retry=True)
        server_base = data.get("server_base")
        if not server_base:
            raise RuntimeError(f"control API returned no server_base: {data!r}")
        return ProjectLease(
            project_id=str(data.get("project_id", name)),
            transport=str(data.get("transport", transport)),
            server_base=str(server_base),
            working_directory=data.get("working_directory"),
            ephemeral=True,
        )

    async def release(self, lease: ProjectLease) -> None:
        if self._base:
            await self._delete(lease.project_id)

    async def preflight(self) -> None:
        self._require_configured()
        # A crash can leave views behind (agentd tears them down only on DELETE);
        # they are ephemeral, so wipe the workspace root on startup.
        await asyncio.to_thread(_wipe_dir, self._base_dir)
        if self.config.projects.isolation == "worktree":
            await _run("git", "-C", self._source or ".", "worktree", "prune")
        async with self._client() as client:
            resp = await client.get(f"{self._base}/admin/projects", headers=self._headers)
            if resp.status_code != 200:
                raise RuntimeError(f"control API not reachable ({resp.status_code})")

    async def _create(self, request: dict, *, retry: bool) -> dict:
        async with self._client() as client:
            resp = await client.post(
                f"{self._base}/admin/projects", json=request, headers=self._headers
            )
            if resp.status_code == 201:
                return dict(resp.json().get("data") or {})
            detail = resp.text.strip()
        # A same-named project may survive an agentd crash; drop it and retry once.
        if retry and "already exists" in detail:
            await self._delete(request["name"])
            return await self._create(request, retry=False)
        raise RuntimeError(f"control create failed ({resp.status_code}): {detail}")

    async def _delete(self, project_id: str) -> None:
        try:
            async with self._client() as client:
                await client.delete(
                    f"{self._base}/admin/projects/{project_id}", headers=self._headers
                )
        except httpx.HTTPError as exc:  # best-effort; the startup wipe is the backstop
            log.warning("control_delete_failed", project=project_id, error=str(exc))

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            timeout=self.config.server.request_timeout_s, transport=self._transport
        )

    def _require_configured(self) -> None:
        if not self._base or not self._source:
            raise RuntimeError(
                "projects.mode=isolated requires projects.control_url and projects.source_directory"
            )


def _sanitize(value: str) -> str:
    """Make a conversation key safe as one path element / project name."""
    safe = re.sub(r"[^A-Za-z0-9._-]", "_", value)
    return safe.strip(" .") or "project"


def _project_name(conv: Conversation) -> str:
    """A stable, collision-resistant instance name for a conversation."""
    return f"{_sanitize(conv.key)}_{hashlib.sha1(conv.key.encode()).hexdigest()[:8]}"


async def _run(*argv: str) -> None:
    proc = await asyncio.create_subprocess_exec(
        *argv, stdout=asyncio.subprocess.DEVNULL, stderr=asyncio.subprocess.DEVNULL
    )
    await proc.wait()


def _wipe_dir(path: str) -> None:
    if os.path.isdir(path):
        for entry in os.listdir(path):
            shutil.rmtree(os.path.join(path, entry), ignore_errors=True)


def build_provider(config: Config) -> ProjectProvider:
    if config.projects.mode == "isolated":
        return AgentdControlProvider(config)
    if config.server.pool:
        return PoolProjectProvider(config.server_bases())
    name, base, working_directory = config.server_bases()[0]
    return SharedProjectProvider(base, working_directory=working_directory, project_id=name)


class LeaseManager:
    """Track live leases and reclaim idle ephemeral views."""

    def __init__(
        self,
        provider: ProjectProvider,
        ttl_s: float,
        *,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        self._provider = provider
        self._ttl = ttl_s
        self._clock = clock
        self._leases: dict[str, tuple[ProjectLease, float]] = {}

    async def register(self, key: str, lease: ProjectLease) -> None:
        self._leases[key] = (lease, self._clock())

    def get(self, key: str) -> ProjectLease | None:
        entry = self._leases.get(key)
        return entry[0] if entry else None

    def bases(self) -> set[str]:
        """The distinct server bases currently leased."""
        return {
            lease.server_base.rstrip("/") for lease, _ in self._leases.values() if lease.server_base
        }

    def touch(self, key: str) -> None:
        entry = self._leases.get(key)
        if entry is not None:
            self._leases[key] = (entry[0], self._clock())

    async def release(self, key: str) -> None:
        entry = self._leases.pop(key, None)
        if entry is not None:
            await self._provider.release(entry[0])

    async def reclaim_idle(self) -> list[str]:
        if self._ttl <= 0:
            return []
        now = self._clock()
        reclaimed: list[str] = []
        for key, (lease, last_active) in list(self._leases.items()):
            if lease.ephemeral and now - last_active >= self._ttl:
                del self._leases[key]
                await self._provider.release(lease)
                reclaimed.append(key)
        return reclaimed

    async def release_all(self) -> None:
        for key in list(self._leases):
            await self.release(key)

    @property
    def count(self) -> int:
        return len(self._leases)

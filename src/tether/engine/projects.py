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
import base64
import hashlib
import itertools
import os
import re
import time
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Protocol

import httpx

from tether.config import Config, ServerEndpoint
from tether.metrics import metrics
from tether.models import Conversation
from tether.util.logging import get_logger

log = get_logger("tether.projects")


@dataclass
class ProjectLease:
    project_id: str
    endpoint_id: str = ""
    backend: str = "agentd"
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
        self,
        server_base: str,
        *,
        working_directory: str | None = None,
        project_id: str = "shared",
        endpoint_id: str = "",
        backend: str = "agentd",
    ) -> None:
        self._lease = ProjectLease(
            project_id=project_id,
            endpoint_id=endpoint_id or project_id,
            backend=backend,
            server_base=server_base,
            working_directory=working_directory,
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

    def __init__(self, pool: Sequence[tuple[Any, ...]]) -> None:
        self._entries = [self._normalize(entry) for entry in pool]
        self._round_robin = itertools.cycle(range(len(pool))) if pool else None

    @staticmethod
    def _normalize(entry: tuple[Any, ...]) -> tuple[str, str, str | None, str, str]:
        if len(entry) >= 5:
            name, base, working_directory, endpoint_id, backend = entry[:5]
            return (
                str(name),
                str(base),
                str(working_directory) if working_directory else None,
                str(endpoint_id),
                str(backend),
            )
        name, base, working_directory = entry
        return (
            str(name),
            str(base),
            str(working_directory) if working_directory else None,
            str(name),
            "agentd",
        )

    async def acquire(
        self, conv: Conversation, *, agent: str, transport: str = "http"
    ) -> ProjectLease:
        if not self._entries or self._round_robin is None:
            raise RuntimeError("the project pool is empty")

        name, base, working_directory, endpoint_id, backend = self._entries[
            next(self._round_robin)
        ]
        return ProjectLease(
            project_id=name,
            endpoint_id=endpoint_id,
            backend=backend,
            server_base=base,
            working_directory=working_directory,
        )

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
        self._known_projects: set[str] = set()

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

        project_id = str(data.get("project_id", name))
        self._known_projects.add(project_id)
        return ProjectLease(
            project_id=project_id,
            endpoint_id=f"agentd-lease:{project_id}",
            backend="agentd",
            transport=str(data.get("transport", transport)),
            server_base=str(server_base),
            working_directory=data.get("working_directory"),
            ephemeral=True,
        )

    async def release(self, lease: ProjectLease) -> None:
        if self._base:
            await self._delete(lease.project_id)
            self._known_projects.discard(lease.project_id)

    async def preflight(self) -> None:
        self._require_configured()
        await asyncio.to_thread(os.makedirs, self._base_dir, exist_ok=True)

        if self.config.projects.isolation == "worktree":
            await _run("git", "-C", self._source or ".", "worktree", "prune")

        async with self._client() as client:
            resp = await client.get(f"{self._base}/admin/projects", headers=self._headers)
            if resp.status_code != 200:
                raise RuntimeError(f"control API not reachable ({resp.status_code})")
            data = resp.json().get("data") if resp.content else []
            entries = data if isinstance(data, list) else []
            self._known_projects = {
                str(item.get("project_id") or item.get("id"))
                for item in entries
                if isinstance(item, dict) and (item.get("project_id") or item.get("id"))
            }

    async def cleanup_orphans(
        self, *, referenced: set[str], active: set[str]
    ) -> list[str]:
        removable = [
            project_id
            for project_id in self._known_projects
            if project_id not in referenced and project_id not in active
        ]
        for project_id in removable:
            await self._delete(project_id)
            self._known_projects.discard(project_id)
            metrics.inc("isolated_orphans_cleaned")
        return removable

    async def _create(self, request: dict, *, retry: bool) -> dict:
        async with self._client() as client:
            resp = await client.post(
                f"{self._base}/admin/projects", json=request, headers=self._headers
            )

            if resp.status_code == 201:
                metrics.inc("isolated_leases_created")
                return dict(resp.json().get("data") or {})

            detail = resp.text.strip()

        # A same-named project may survive an agentd crash; drop it and retry once.
        if retry and "already exists" in detail:
            await self._delete(request["name"])
            return await self._create(request, retry=False)

        metrics.inc("isolated_lease_failures")
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


class OpenCodeWorktreeProvider:
    """Lease per-conversation OpenCode worktrees on one endpoint."""

    def __init__(
        self,
        config: Config,
        endpoints: Sequence[ServerEndpoint],
        *,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        self.config = config
        self._transport = transport
        projects = config.projects
        self._endpoint = next(
            (item for item in endpoints if item.id == projects.endpoint), None
        )
        self._base = self._endpoint.base_url if self._endpoint else ""
        self._source = projects.source_directory or ""
        self._base_dir = projects.base_dir
        self._project_id: str | None = None
        self._project_root: str | None = None
        self._known_worktrees: set[str] = set()
        self._headers = self._auth_headers(self._endpoint)

    @staticmethod
    def _auth_headers(endpoint: ServerEndpoint | None) -> dict[str, str]:
        if endpoint is None or endpoint.auth is None:
            return {}
        auth = endpoint.auth
        if auth.type != "basic":
            return {}
        value = base64.b64encode(
            f"{auth.username or 'opencode'}:{auth.password or ''}".encode()
        ).decode()
        return {"Authorization": f"Basic {value}"}

    async def acquire(
        self, conv: Conversation, *, agent: str, transport: str = "http"
    ) -> ProjectLease:
        project_id, project_root = await self._ensure_project()
        await asyncio.to_thread(os.makedirs, self._base_dir, exist_ok=True)
        name = f"tether-{_sanitize(conv.key)}-{hashlib.sha1(conv.key.encode()).hexdigest()[:8]}"

        async with self._client() as client:
            resp = await client.post(
                "/api/worktree",
                json={
                    "projectID": project_id,
                    "from": project_root,
                    "branch": self.config.projects.git_base_ref,
                    "directory": self._base_dir,
                    "name": name,
                },
                headers=self._headers,
            )
        if resp.status_code >= 400:
            metrics.inc("isolated_lease_failures")
            raise RuntimeError(f"worktree create failed ({resp.status_code}): {resp.text}")
        data = _unwrap(resp)
        directory = data.get("directory") if isinstance(data, dict) else None
        if not directory:
            metrics.inc("isolated_lease_failures")
            raise RuntimeError(f"worktree create returned no directory: {data!r}")

        metrics.inc("isolated_leases_created")
        return ProjectLease(
            project_id=project_id,
            endpoint_id=self._endpoint.id if self._endpoint else "",
            backend="opencode",
            server_base=self._base,
            working_directory=str(directory),
            ephemeral=True,
        )

    async def release(self, lease: ProjectLease) -> None:
        try:
            async with self._client() as client:
                await client.request(
                    "DELETE",
                    "/api/worktree",
                    json={
                        "projectID": lease.project_id,
                        "directory": lease.working_directory,
                        "force": True,
                    },
                    headers=self._headers,
                )
        except httpx.HTTPError as exc:
            log.warning(
                "worktree_delete_failed",
                project=lease.project_id,
                directory=lease.working_directory,
                error=str(exc),
            )

    async def preflight(self) -> None:
        self._require_configured()
        await self._ensure_project()
        async with self._client() as client:
            resp = await client.get(
                "/api/worktree",
                params={"projectID": self._project_id or ""},
                headers=self._headers,
            )
        if resp.status_code != 200:
            raise RuntimeError(f"worktree API not reachable ({resp.status_code})")
        data = _unwrap(resp)
        entries = data if isinstance(data, list) else []
        self._known_worktrees = {
            str(item.get("directory"))
            for item in entries
            if isinstance(item, dict) and item.get("directory")
        }

    async def cleanup_orphans(
        self, *, referenced: set[str], active: set[str]
    ) -> list[str]:
        removable = [
            path
            for path in self._known_worktrees
            if Path(path).name.startswith("tether-")
            and path not in referenced
            and path not in active
        ]
        for path in removable:
            try:
                async with self._client() as client:
                    await client.request(
                        "DELETE",
                        "/api/worktree",
                        json={
                            "projectID": self._project_id or "",
                            "directory": path,
                            "force": True,
                        },
                        headers=self._headers,
                    )
            except httpx.HTTPError as exc:
                log.warning("orphan_worktree_delete_failed", directory=path, error=str(exc))
            else:
                self._known_worktrees.discard(path)
                metrics.inc("isolated_orphans_cleaned")
        return removable

    async def _ensure_project(self) -> tuple[str, str]:
        if self._project_id and self._project_root:
            return self._project_id, self._project_root

        self._require_configured()
        async with self._client() as client:
            resp = await client.get(
                "/api/location",
                params={"location[directory]": self._source},
                headers=self._headers,
            )
        if resp.status_code != 200:
            raise RuntimeError(
                f"opencode location not reachable ({resp.status_code}): {resp.text}"
            )
        data = _unwrap(resp)
        project = data.get("project") if isinstance(data, dict) else None
        if not isinstance(project, dict) or not project.get("id"):
            raise RuntimeError(f"opencode location returned no project: {data!r}")
        project_id = str(project["id"])
        project_root = str(project.get("canonical") or project.get("directory") or "")
        same_root = await asyncio.to_thread(
            lambda: bool(project_root)
            and Path(project_root).resolve() == Path(self._source).resolve()
        )
        if not same_root:
            raise RuntimeError(
                "projects.source_directory is not the OpenCode project root "
                f"({self._source!r} != {project_root!r})"
            )
        self._project_id = project_id
        self._project_root = project_root
        return project_id, project_root

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base,
            timeout=self.config.server.request_timeout_s,
            transport=self._transport,
        )

    def _require_configured(self) -> None:
        if self.config.projects.backend != "opencode":
            raise RuntimeError("projects.backend=opencode is required")
        if self._endpoint is None or self._endpoint.backend != "opencode":
            raise RuntimeError("projects.endpoint must reference an opencode endpoint")
        if not self._source or not Path(self._source).is_absolute():
            raise RuntimeError("projects.source_directory must be an absolute path")

def _unwrap(resp: httpx.Response) -> Any:
    try:
        body = resp.json()
    except ValueError:
        return {}
    if isinstance(body, dict) and "data" in body:
        return body["data"]
    return body


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


def build_provider(
    config: Config, endpoints: Sequence[ServerEndpoint] | None = None
) -> ProjectProvider:
    endpoints = list(endpoints if endpoints is not None else config.server_endpoints())
    if config.projects.mode == "isolated":
        if config.projects.backend == "opencode":
            return OpenCodeWorktreeProvider(config, endpoints)
        return AgentdControlProvider(config)

    if config.server.pool:
        return PoolProjectProvider(
            [
                (
                    endpoint.name,
                    endpoint.base_url,
                    endpoint.working_directory,
                    endpoint.id,
                    endpoint.backend,
                )
                for endpoint in endpoints
            ]
        )

    endpoint = endpoints[0]
    return SharedProjectProvider(
        endpoint.base_url,
        working_directory=endpoint.working_directory,
        project_id=endpoint.name,
        endpoint_id=endpoint.id,
        backend=endpoint.backend,
    )


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

    def working_directories(self) -> set[str]:
        return {
            lease.working_directory
            for lease, _ in self._leases.values()
            if lease.working_directory
        }

    def project_ids(self) -> set[str]:
        return {lease.project_id for lease, _ in self._leases.values() if lease.project_id}

    def ephemeral_keys(self) -> list[str]:
        """Ephemeral lease keys, least-recently-used first."""
        return [
            key
            for _, key in sorted(
                (last_active, key)
                for key, (lease, last_active) in self._leases.items()
                if lease.ephemeral
            )
        ]

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

    def expired_keys(self) -> list[str]:
        if self._ttl <= 0:
            return []
        now = self._clock()
        return [
            key
            for key, (lease, last_active) in self._leases.items()
            if lease.ephemeral and now - last_active >= self._ttl
        ]

    def forget_all(self) -> None:
        self._leases.clear()

    async def reclaim_oldest(self) -> list[str]:
        ephemeral = [
            (last_active, key)
            for key, (lease, last_active) in self._leases.items()
            if lease.ephemeral
        ]
        if not ephemeral:
            return []

        _, key = min(ephemeral)
        await self.release(key)
        return [key]

    async def release_all(self) -> None:
        for key in list(self._leases):
            await self.release(key)

    @property
    def count(self) -> int:
        return len(self._leases)

"""Lease isolated agent-project instances for writable conversations.

A project instance is one agent-service process bound to one working directory.
The bridge never starts such processes itself; it acquires and returns leases
through a provider, and tracks their lifetime.
"""

from __future__ import annotations

import itertools
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from ..config import Config
from ..models import Conversation


@dataclass
class ProjectLease:
    project_id: str
    transport: str = "http"
    server_base: str = ""
    working_directory: str | None = None
    ephemeral: bool = False


class ProjectProvider(Protocol):
    async def acquire(
        self, conv: Conversation, *, agent: str, readonly: bool, transport: str = "http"
    ) -> ProjectLease: ...

    async def release(self, lease: ProjectLease) -> None: ...

    async def health(self, lease: ProjectLease) -> bool: ...

    async def preflight(self) -> None: ...


class SharedProjectProvider:
    """One instance reused by all conversations; safe only for read-only agents."""

    def __init__(
        self, server_base: str, *, working_directory: str | None = None, project_id: str = "shared"
    ) -> None:
        self._lease = ProjectLease(
            project_id=project_id, server_base=server_base, working_directory=working_directory
        )

    async def acquire(
        self, conv: Conversation, *, agent: str, readonly: bool, transport: str = "http"
    ) -> ProjectLease:
        if not readonly:
            raise RuntimeError("a shared project cannot host a writable agent")
        return self._lease

    async def release(self, lease: ProjectLease) -> None:
        return None

    async def health(self, lease: ProjectLease) -> bool:
        return True

    async def preflight(self) -> None:
        return None


class PoolProjectProvider:
    """A fixed pool of instances: read-only conversations share, writable ones
    hold an instance exclusively until released."""

    def __init__(
        self,
        pool: list[tuple[str, str, str | None]],
        *,
        max_leases: int = 32,
        allow_writable_share: bool = False,
    ) -> None:
        self._entries = pool
        self._max = max_leases
        self._allow_writable_share = allow_writable_share
        self._round_robin = itertools.cycle(range(len(pool)))
        self._owners: dict[str, str] = {}  # project id -> owning conversation key

    async def acquire(
        self, conv: Conversation, *, agent: str, readonly: bool, transport: str = "http"
    ) -> ProjectLease:
        if not self._entries:
            raise RuntimeError("the project pool is empty")
        if readonly or self._allow_writable_share:
            return self._lease_for(self._entries[next(self._round_robin)])
        existing = self._owned_by(conv.key)
        if existing is not None:
            return existing
        if len(self._owners) >= self._max:
            raise RuntimeError(f"project lease limit reached ({self._max})")
        return self._claim_free(conv.key)

    def _owned_by(self, conversation_key: str) -> ProjectLease | None:
        for project_id, owner in self._owners.items():
            if owner == conversation_key:
                return self._lease_for(next(e for e in self._entries if e[0] == project_id))
        return None

    def _claim_free(self, conversation_key: str) -> ProjectLease:
        for entry in self._entries:
            if entry[0] not in self._owners:
                self._owners[entry[0]] = conversation_key
                return self._lease_for(entry)
        raise RuntimeError("no free project instance in the pool")

    @staticmethod
    def _lease_for(entry: tuple[str, str, str | None]) -> ProjectLease:
        name, base, working_directory = entry
        return ProjectLease(project_id=name, server_base=base, working_directory=working_directory)

    async def release(self, lease: ProjectLease) -> None:
        self._owners.pop(lease.project_id, None)

    async def health(self, lease: ProjectLease) -> bool:
        return True

    async def preflight(self) -> None:
        if not self._entries:
            raise RuntimeError("the pool provider requires at least one server")


class SupervisorProjectProvider:
    """A placeholder for host-managed provision of project instances.

    Until a supervisor integration exists this refuses to acquire, so operators
    must configure a static pool instead.
    """

    def __init__(self, config: Config) -> None:
        self.config = config

    async def acquire(
        self, conv: Conversation, *, agent: str, readonly: bool, transport: str = "http"
    ) -> ProjectLease:
        raise RuntimeError("no project supervisor is configured; use a static server pool instead")

    async def release(self, lease: ProjectLease) -> None:
        return None

    async def health(self, lease: ProjectLease) -> bool:
        return False

    async def preflight(self) -> None:
        raise RuntimeError("the supervisor provider is not configured")


def build_provider(config: Config) -> ProjectProvider:
    if config.projects.provider == "shared":
        name, base, working_directory = config.server_bases()[0]
        return SharedProjectProvider(base, working_directory=working_directory, project_id=name)
    if config.projects.provider == "pool":
        return PoolProjectProvider(
            config.server_bases(),
            max_leases=config.projects.max_leases,
            allow_writable_share=config.projects.isolation == "shared",
        )
    return SupervisorProjectProvider(config)


class LeaseManager:
    """Track live leases and reclaim idle ephemeral views.

    Only ephemeral isolated views (a worktree, overlay or container created for a
    single conversation) are reclaimed on idle; fixed pool instances stay bound
    to their conversation.
    """

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

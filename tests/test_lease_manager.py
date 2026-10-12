from __future__ import annotations

import pytest

from tether.engine.projects import LeaseManager, ProjectLease


class FakeProvider:
    def __init__(self) -> None:
        self.released: list[str] = []

    async def release(self, lease: ProjectLease) -> None:
        self.released.append(lease.project_id)


class Clock:
    def __init__(self) -> None:
        self.t = 0.0

    def __call__(self) -> float:
        return self.t


@pytest.mark.asyncio
async def test_reclaims_only_idle_ephemeral_leases():
    provider = FakeProvider()
    clock = Clock()
    leases = LeaseManager(provider, ttl_s=10, clock=clock)
    await leases.register("k1", ProjectLease("p1", ephemeral=True))
    await leases.register("k2", ProjectLease("p2", ephemeral=False))

    clock.t = 5
    assert await leases.reclaim_idle() == []

    clock.t = 11
    assert await leases.reclaim_idle() == ["k1"]
    assert provider.released == ["p1"]
    assert leases.count == 1


@pytest.mark.asyncio
async def test_touch_prevents_reclaim():
    provider = FakeProvider()
    clock = Clock()
    leases = LeaseManager(provider, ttl_s=10, clock=clock)
    await leases.register("k1", ProjectLease("p1", ephemeral=True))

    clock.t = 8
    leases.touch("k1")
    clock.t = 15
    assert await leases.reclaim_idle() == []
    assert leases.count == 1


@pytest.mark.asyncio
async def test_release_all_on_shutdown():
    provider = FakeProvider()
    leases = LeaseManager(provider, ttl_s=10, clock=Clock())
    await leases.register("k1", ProjectLease("p1", ephemeral=True))
    await leases.register("k2", ProjectLease("p2"))
    await leases.release_all()
    assert sorted(provider.released) == ["p1", "p2"]
    assert leases.count == 0

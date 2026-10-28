from __future__ import annotations

import pytest

from tether.models import Conversation, PendingInteraction, Route
from tether.store.sqlite import RouteStore


async def make_store(tmp_path) -> RouteStore:
    store = RouteStore(str(tmp_path / "state.db"))
    await store.connect()
    return store


@pytest.mark.asyncio
async def test_route_round_trips_all_persisted_fields(tmp_path):
    store = await make_store(tmp_path)
    conv = Conversation(
        channel="wechat",
        kind="group",
        id="g1",
        name="Group",
        thread="t1",
        tenant="tenant",
        account="bot1",
    )
    route = Route(
        conversation=conv,
        session_id="ses_1",
        server_base="http://agentd",
        agent="build",
        model={"id": "m1", "providerID": "p"},
        context_limit=4096,
        project_id="project-1",
        participants={"u1": "Alice"},
        active_turn_sender="u1",
        queue_depth=2,
        last_seq=7,
        bot_name="Bot",
        bot_description="Desc",
        context_dirty=True,
        identity_injected=True,
        created_at=1.5,
        last_active=2.5,
        pending_interactions={
            "p1": PendingInteraction(
                kind="permission",
                owner="u1",
                scope="initiator",
                options=["Allow", "Deny"],
                request_id="p1",
            ),
            "q1": PendingInteraction(
                kind="question",
                owner=None,
                scope="participants",
                options=["A"],
                request_id="q1",
            ),
        },
        stream_ref={"id": "msg-1", "conversation": "x"},
    )
    assert route.model == "m1"

    await store.put(route)
    loaded = await store.get(conv.key)

    assert loaded is not None
    assert loaded.conversation == conv
    assert loaded.session_id == "ses_1"
    assert loaded.server_base == "http://agentd"
    assert loaded.agent == "build"
    assert loaded.model == "m1"
    assert loaded.context_limit == 4096
    assert loaded.project_id == "project-1"
    assert loaded.participants == {"u1": "Alice"}
    assert loaded.active_turn_sender == "u1"
    assert loaded.queue_depth == 2
    assert loaded.last_seq == 7
    assert loaded.bot_name == "Bot"
    assert loaded.bot_description == "Desc"
    assert loaded.context_dirty is True
    assert loaded.identity_injected is True
    assert loaded.created_at == 1.5
    assert loaded.last_active == 2.5
    assert set(loaded.pending_interactions) == {"p1", "q1"}
    assert loaded.pending_interactions["p1"].owner == "u1"
    assert loaded.pending_interactions["q1"].scope == "participants"
    assert loaded.stream_ref == {"id": "msg-1", "conversation": "x"}

    assert await store.get_by_session("ses_1") is not None
    assert [r.key for r in await store.all()] == [conv.key]

    await store.close()


@pytest.mark.asyncio
async def test_route_delete_and_count(tmp_path):
    store = await make_store(tmp_path)
    conv = Conversation(channel="wecom", kind="direct", id="c1")
    route = Route(conversation=conv, session_id="ses_1", server_base="http://a", agent="a")
    await store.put(route)
    assert await store.count() == 1
    await store.delete(conv.key)
    assert await store.count() == 0
    assert await store.get(conv.key) is None
    await store.close()


@pytest.mark.asyncio
async def test_put_updates_existing_route_by_key(tmp_path):
    store = await make_store(tmp_path)
    conv = Conversation(channel="wecom", kind="direct", id="c1")
    route = Route(conversation=conv, session_id="ses_1", server_base="http://a", agent="a")
    await store.put(route)
    route.session_id = "ses_2"
    route.queue_depth = 3
    await store.put(route)

    loaded = await store.get(conv.key)
    assert loaded is not None
    assert loaded.session_id == "ses_2"
    assert loaded.queue_depth == 3
    assert await store.count() == 1
    await store.close()

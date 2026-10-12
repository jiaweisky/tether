"""Persist conversation routes in SQLite.

Routes are keyed by the conversation key, with a unique index on the session id
so an event or an interaction can be looked up by session as well as by
conversation. This lets sessions survive a bridge restart.
"""

from __future__ import annotations

import json
from pathlib import Path

import aiosqlite

from ..models import Conversation, PendingInteraction, Route

_SCHEMA = """
CREATE TABLE IF NOT EXISTS routes (
    key TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    data TEXT NOT NULL,
    updated_at REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_routes_session ON routes(session_id);
"""


def _route_to_json(route: Route) -> str:
    payload = {
        "conversation": {
            "channel": route.conversation.channel,
            "kind": route.conversation.kind,
            "id": route.conversation.id,
            "name": route.conversation.name,
            "thread": route.conversation.thread,
            "tenant": route.conversation.tenant,
        },
        "session_id": route.session_id,
        "server_base": route.server_base,
        "agent": route.agent,
        "model": route.model,
        "context_limit": route.context_limit,
        "project_id": route.project_id,
        "participants": route.participants,
        "active_turn_sender": route.active_turn_sender,
        "queue_depth": route.queue_depth,
        "bot_name": route.bot_name,
        "bot_description": route.bot_description,
        "context_dirty": route.context_dirty,
        "identity_injected": route.identity_injected,
        "created_at": route.created_at,
        "last_active": route.last_active,
        "pending_interactions": {
            rid: {
                "kind": p.kind,
                "owner": p.owner,
                "scope": p.scope,
                "options": p.options,
                "request_id": p.request_id,
            }
            for rid, p in route.pending_interactions.items()
        },
        "stream_ref": route.stream_ref,
    }
    return json.dumps(payload)


def _route_from_json(raw: str) -> Route:
    d = json.loads(raw)
    conv = Conversation(**d["conversation"])
    pending = {
        rid: PendingInteraction(**p) for rid, p in (d.get("pending_interactions") or {}).items()
    }
    return Route(
        conversation=conv,
        session_id=d["session_id"],
        server_base=d["server_base"],
        agent=d["agent"],
        model=d.get("model"),
        context_limit=d.get("context_limit"),
        project_id=d.get("project_id"),
        participants=dict(d.get("participants") or {}),
        active_turn_sender=d.get("active_turn_sender"),
        queue_depth=int(d.get("queue_depth", 0)),
        bot_name=d.get("bot_name"),
        bot_description=d.get("bot_description"),
        context_dirty=bool(d.get("context_dirty", False)),
        identity_injected=bool(d.get("identity_injected", False)),
        created_at=float(d.get("created_at", 0.0)),
        last_active=float(d.get("last_active", 0.0)),
        pending_interactions=pending,
        stream_ref=d.get("stream_ref"),
    )


class RouteStore:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._db: aiosqlite.Connection | None = None

    async def connect(self) -> None:
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(_SCHEMA)
        await self._db.commit()

    async def close(self) -> None:
        if self._db is not None:
            await self._db.close()
            self._db = None

    def _conn(self) -> aiosqlite.Connection:
        if self._db is None:
            raise RuntimeError("RouteStore.connect() was not awaited")
        return self._db

    async def get(self, key: str) -> Route | None:
        async with self._conn().execute("SELECT data FROM routes WHERE key = ?", (key,)) as cur:
            row = await cur.fetchone()
        return _route_from_json(row["data"]) if row else None

    async def get_by_session(self, session_id: str) -> Route | None:
        async with self._conn().execute(
            "SELECT data FROM routes WHERE session_id = ?", (session_id,)
        ) as cur:
            row = await cur.fetchone()
        return _route_from_json(row["data"]) if row else None

    async def put(self, route: Route) -> None:
        await self._conn().execute(
            "INSERT INTO routes(key, session_id, data, updated_at) VALUES(?,?,?,?) "
            "ON CONFLICT(key) DO UPDATE SET session_id=excluded.session_id, "
            "data=excluded.data, updated_at=excluded.updated_at",
            (route.key, route.session_id, _route_to_json(route), route.last_active),
        )
        await self._conn().commit()

    async def delete(self, key: str) -> None:
        await self._conn().execute("DELETE FROM routes WHERE key = ?", (key,))
        await self._conn().commit()

    async def all(self) -> list[Route]:
        async with self._conn().execute("SELECT data FROM routes") as cur:
            rows = await cur.fetchall()
        return [_route_from_json(r["data"]) for r in rows]

    async def count(self) -> int:
        async with self._conn().execute("SELECT COUNT(*) AS n FROM routes") as cur:
            row = await cur.fetchone()
        return int(row["n"]) if row else 0

    async def flush(self) -> None:
        await self._conn().commit()

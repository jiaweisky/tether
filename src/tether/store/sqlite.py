"""SQLite state store.

It holds the conversation→agent-session routes (with a reverse lookup by
session id) plus the WeChat runtime state: account binding/token, long-poll
cursor and per-peer reply tokens. This lets both routes and WeChat login state
survive a bridge restart.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path

import aiosqlite

from ..models import Conversation, PendingInteraction, Route

_DB_FILE_MODE = 0o600
_DB_DIR_MODE = 0o700

_WECHAT_ACCOUNTS_DDL = """
CREATE TABLE IF NOT EXISTS wechat_accounts (
    slot TEXT PRIMARY KEY,
    ilink_bot_id TEXT UNIQUE,
    token TEXT,
    base_url TEXT,
    user_id TEXT,
    bound_at REAL,
    token_saved_at REAL
);
"""

_SCHEMA = f"""
CREATE TABLE IF NOT EXISTS routes (
    key TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    data TEXT NOT NULL,
    updated_at REAL NOT NULL
);
CREATE UNIQUE INDEX IF NOT EXISTS idx_routes_session ON routes(session_id);
{_WECHAT_ACCOUNTS_DDL}
CREATE TABLE IF NOT EXISTS wechat_state (
    slot TEXT PRIMARY KEY,
    cursor TEXT NOT NULL DEFAULT '',
    updated_at REAL NOT NULL
);
CREATE TABLE IF NOT EXISTS wechat_context_tokens (
    slot TEXT NOT NULL,
    peer_id TEXT NOT NULL,
    token TEXT NOT NULL,
    updated_at REAL NOT NULL,
    PRIMARY KEY (slot, peer_id)
);
"""


class WeChatBindingConflict(Exception):
    """The scanned platform id is already bound to another bot."""

    def __init__(self, other_slot: str) -> None:
        super().__init__(other_slot)
        self.other_slot = other_slot


class WeChatRebindRequired(Exception):
    """The bot is already bound to a different platform id."""

    def __init__(self, current_bot_id: str) -> None:
        super().__init__(current_bot_id)
        self.current_bot_id = current_bot_id


def _route_to_json(route: Route) -> str:
    payload = {
        "conversation": {
            "channel": route.conversation.channel,
            "kind": route.conversation.kind,
            "id": route.conversation.id,
            "name": route.conversation.name,
            "thread": route.conversation.thread,
            "tenant": route.conversation.tenant,
            "account": route.conversation.account,
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
        self.path = str(Path(path).expanduser())
        self._db: aiosqlite.Connection | None = None

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

    # -- WeChat account state ---------------------------------------------
    async def connect(self) -> None:
        if self.path != ":memory:":
            parent = Path(self.path).parent
            created = not parent.exists()
            parent.mkdir(parents=True, exist_ok=True)
            if created or parent == Path.home() / ".tether":
                try:
                    parent.chmod(_DB_DIR_MODE)
                except OSError:
                    pass
        self._db = await aiosqlite.connect(self.path)
        self._db.row_factory = aiosqlite.Row
        await self._db.executescript(_SCHEMA)
        await self._db.commit()
        await self._ensure_wechat_schema()
        _chmod_private(self.path)

    async def _ensure_wechat_schema(self) -> None:
        """Migrate the pre-token wechat_accounts table in place."""
        async with self._conn().execute("PRAGMA table_info(wechat_accounts)") as cur:
            columns = {str(row["name"]) for row in await cur.fetchall()}
        if not columns:
            return
        if "token" not in columns:
            await self._rebuild_wechat_accounts()
            return
        await self._add_missing_wechat_columns(columns)

    async def _rebuild_wechat_accounts(self) -> None:
        """Rebuild the old binding-only table with the new nullable columns."""
        await self._conn().executescript(
            f"""
            ALTER TABLE wechat_accounts RENAME TO wechat_accounts_old;
            {_WECHAT_ACCOUNTS_DDL}
            INSERT INTO wechat_accounts(slot, ilink_bot_id, bound_at)
                SELECT slot, ilink_bot_id, bound_at FROM wechat_accounts_old;
            DROP TABLE wechat_accounts_old;
            """
        )
        await self._conn().commit()

    async def _add_missing_wechat_columns(self, columns: set[str]) -> None:
        """Complete a partially migrated table without recreating it."""
        for column, decl in (
            ("base_url", "TEXT"),
            ("user_id", "TEXT"),
            ("bound_at", "REAL"),
            ("token_saved_at", "REAL"),
        ):
            if column not in columns:
                await self._conn().execute(
                    f"ALTER TABLE wechat_accounts ADD COLUMN {column} {decl}"
                )
        await self._conn().commit()

    async def wechat_account(self, slot: str) -> dict[str, object] | None:
        async with self._conn().execute(
            "SELECT slot, ilink_bot_id, token, base_url, user_id, "
            "bound_at, token_saved_at FROM wechat_accounts WHERE slot = ?",
            (slot,),
        ) as cur:
            row = await cur.fetchone()
        return dict(row) if row else None

    async def wechat_binding(self, slot: str) -> str | None:
        """The platform ``ilink_bot_id`` bound to a local slot, if any."""
        async with self._conn().execute(
            "SELECT ilink_bot_id FROM wechat_accounts WHERE slot = ?", (slot,)
        ) as cur:
            row = await cur.fetchone()
        return str(row["ilink_bot_id"]) if row and row["ilink_bot_id"] else None

    async def wechat_binding_by_bot_id(self, bot_id: str) -> str | None:
        """The local slot bound to a platform id, if any."""
        async with self._conn().execute(
            "SELECT slot FROM wechat_accounts WHERE ilink_bot_id = ?", (bot_id,)
        ) as cur:
            row = await cur.fetchone()
        return str(row["slot"]) if row else None

    async def wechat_bindings(self) -> dict[str, str]:
        async with self._conn().execute(
            "SELECT slot, ilink_bot_id FROM wechat_accounts WHERE ilink_bot_id IS NOT NULL"
        ) as cur:
            rows = await cur.fetchall()
        return {str(r["slot"]): str(r["ilink_bot_id"]) for r in rows}

    async def save_wechat_login(
        self,
        slot: str,
        bot_id: str,
        token: str,
        base_url: str,
        user_id: str | None,
    ) -> None:
        """Atomically check the binding and store the token.

        Raises :class:`WeChatBindingConflict` if the platform id belongs to
        another bot, or :class:`WeChatRebindRequired` if this bot is already
        bound to a different id.
        """
        now = time.time()
        db = self._conn()
        await db.execute("BEGIN IMMEDIATE")
        try:
            async with db.execute(
                "SELECT ilink_bot_id FROM wechat_accounts WHERE slot = ?", (slot,)
            ) as cur:
                current_row = await cur.fetchone()
            current = (
                str(current_row["ilink_bot_id"])
                if current_row and current_row["ilink_bot_id"]
                else None
            )
            async with db.execute(
                "SELECT slot FROM wechat_accounts WHERE ilink_bot_id = ? AND slot <> ?",
                (bot_id, slot),
            ) as cur:
                other = await cur.fetchone()
            if other is not None:
                raise WeChatBindingConflict(str(other["slot"]))
            if current is not None and current != bot_id:
                raise WeChatRebindRequired(current)
            await db.execute(
                "INSERT INTO wechat_accounts("
                "slot, ilink_bot_id, token, base_url, user_id, bound_at, token_saved_at"
                ") VALUES(?,?,?,?,?,?,?) "
                "ON CONFLICT(slot) DO UPDATE SET ilink_bot_id=excluded.ilink_bot_id, "
                "token=excluded.token, base_url=excluded.base_url, "
                "user_id=excluded.user_id, bound_at=excluded.bound_at, "
                "token_saved_at=excluded.token_saved_at",
                (slot, bot_id, token, base_url, user_id, now, now),
            )
            await db.commit()
        except Exception:
            await db.rollback()
            raise

    async def save_wechat_token(
        self,
        slot: str,
        token: str,
        base_url: str,
        user_id: str | None,
    ) -> None:
        """Store a token without a binding (legacy import only)."""
        now = time.time()
        await self._conn().execute(
            "INSERT INTO wechat_accounts("
            "slot, ilink_bot_id, token, base_url, user_id, bound_at, token_saved_at"
            ") VALUES(?,?,?,?,?,?,?) "
            "ON CONFLICT(slot) DO UPDATE SET token=excluded.token, "
            "base_url=excluded.base_url, user_id=excluded.user_id, "
            "token_saved_at=excluded.token_saved_at",
            (slot, None, token, base_url, user_id, None, now),
        )
        await self._conn().commit()

    async def bind_wechat(self, slot: str, bot_id: str) -> None:
        """Test/legacy helper: bind a slot without a token."""
        await self._conn().execute(
            "INSERT INTO wechat_accounts(slot, ilink_bot_id, bound_at) VALUES(?,?,?) "
            "ON CONFLICT(slot) DO UPDATE SET ilink_bot_id=excluded.ilink_bot_id, "
            "bound_at=excluded.bound_at",
            (slot, bot_id, time.time()),
        )
        await self._conn().commit()

    async def wechat_state(self, slot: str) -> tuple[str, dict[str, str]]:
        async with self._conn().execute(
            "SELECT cursor FROM wechat_state WHERE slot = ?", (slot,)
        ) as cur:
            row = await cur.fetchone()
        cursor = str(row["cursor"]) if row else ""
        async with self._conn().execute(
            "SELECT peer_id, token FROM wechat_context_tokens WHERE slot = ?", (slot,)
        ) as cur:
            rows = await cur.fetchall()
        tokens = {str(r["peer_id"]): str(r["token"]) for r in rows}
        return cursor, tokens

    async def save_wechat_cursor(self, slot: str, cursor: str) -> None:
        await self._conn().execute(
            "INSERT INTO wechat_state(slot, cursor, updated_at) VALUES(?,?,?) "
            "ON CONFLICT(slot) DO UPDATE SET cursor=excluded.cursor, "
            "updated_at=excluded.updated_at",
            (slot, cursor, time.time()),
        )
        await self._conn().commit()

    async def save_wechat_context_token(
        self, slot: str, peer_id: str, token: str
    ) -> None:
        await self._conn().execute(
            "INSERT INTO wechat_context_tokens(slot, peer_id, token, updated_at) "
            "VALUES(?,?,?,?) ON CONFLICT(slot, peer_id) DO UPDATE SET "
            "token=excluded.token, updated_at=excluded.updated_at",
            (slot, peer_id, token, time.time()),
        )
        await self._conn().commit()

    async def unbind_wechat(self, slot: str) -> None:
        db = self._conn()
        await db.execute("BEGIN IMMEDIATE")
        try:
            await db.execute("DELETE FROM wechat_accounts WHERE slot = ?", (slot,))
            await db.execute("DELETE FROM wechat_state WHERE slot = ?", (slot,))
            await db.execute("DELETE FROM wechat_context_tokens WHERE slot = ?", (slot,))
            await db.commit()
        except Exception:
            await db.rollback()
            raise


def _chmod_private(path: str) -> None:
    try:
        if path != ":memory:":
            os.chmod(path, _DB_FILE_MODE)
    except OSError:
        pass

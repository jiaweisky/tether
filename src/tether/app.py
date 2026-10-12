"""Wire the pieces together and drive message flow in both directions.

The app starts the enabled connectors, consumes the agent's global event stream,
routes each event to the turn that owns its session, handles command clicks and
numbered replies, and periodically restores pending interactions and reclaims
idle project leases.
"""

from __future__ import annotations

import asyncio
import contextlib
import hashlib
from typing import Literal

from .agent.client import HttpAgentClient
from .agent.errors import AgentError, user_message
from .agent.events import (
    PERMISSION_ASKED,
    PERMISSION_REPLIED,
    QUESTION_ASKED,
    QUESTION_REJECTED,
    QUESTION_REPLIED,
    SESSION_STATUS,
    Event,
)
from .config import Config, validate_startup
from .connector import IMConnector, build_connectors
from .engine import hitl
from .engine.media_egress import MediaEgress
from .engine.media_ingest import MediaIngest
from .engine.projects import build_provider
from .engine.prompt import PromptComposer
from .engine.router import ClientFactory, Router
from .engine.turn import TurnEngine
from .models import (
    ConnectorEvent,
    Conversation,
    InboundMessage,
    IncomingInteraction,
    IncomingItem,
    OutboundPlan,
    RichMedia,
    Route,
    TextSegment,
)
from .render.renderer import DefaultRenderer
from .store.sqlite import RouteStore
from .util.dedup import DedupCache
from .util.logging import get_logger

log = get_logger("tether.app")


class TetherApp:
    def __init__(
        self,
        config: Config,
        *,
        db_path: str = "tether.sqlite3",
        connectors: list[IMConnector] | None = None,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self.config = config
        self.store = RouteStore(db_path)
        self._connectors_override = connectors
        self.provider = build_provider(config)
        self.router = Router(config, self.store, self.provider, client_factory=client_factory)
        self.composer = PromptComposer(config)
        self.renderer = DefaultRenderer(
            show_usage=config.streaming.show_usage,
            context_limit=config.model.context_limit,
            reasoning_style=config.streaming.reasoning_style,
            max_chars_override=config.streaming.max_chars_override,
        )
        self.dedup = DedupCache(config.dedup.ttl_s)
        self.connectors: dict[str, IMConnector] = {}
        self._turns: dict[str, TurnEngine] = {}
        self._turn_queue: dict[str, list[TurnEngine]] = {}
        self._sse_tasks: list[asyncio.Task[None]] = []
        self._clients: list[tuple[str, HttpAgentClient]] = []
        self._janitor_task: asyncio.Task[None] | None = None
        self._running = False
        self._stopped = False
        self._stop_event: asyncio.Event | None = None
        self.metrics: dict[str, int] = {}

    # -- lifecycle ---------------------------------------------------------
    async def start(self) -> None:
        validate_startup(self.config)
        await self.store.connect()
        built = self._connectors_override
        if built is None:
            built = build_connectors(self.config)
        for connector in built:
            self.connectors[connector.name] = connector
        if not self.connectors:
            log.warning("no_connectors_enabled")
        for connector in self.connectors.values():
            await connector.start(self._on_item)
        self._running = True
        for base_url, _token_env in self._bases():
            client = self.router.client_for_base(base_url)
            self._clients.append((base_url, client))
            self._sse_tasks.append(asyncio.ensure_future(self._consume_events(base_url, client)))
        self._janitor_task = asyncio.ensure_future(self._janitor())
        log.info("tether_started", connectors=list(self.connectors))

    async def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self._running = False
        if self._stop_event is not None:
            self._stop_event.set()
        for task in self._sse_tasks:
            task.cancel()
        if self._janitor_task is not None:
            self._janitor_task.cancel()
        for task in self._sse_tasks:
            with contextlib.suppress(asyncio.CancelledError):
                await task
        if self._janitor_task is not None:
            with contextlib.suppress(asyncio.CancelledError):
                await self._janitor_task
        for engine in list(self._turns.values()):
            await engine.cancel()
        for connector in self.connectors.values():
            with contextlib.suppress(Exception):
                await connector.stop()
        await self.store.flush()
        await self.router.close()
        await self.store.close()
        log.info("tether_stopped")

    async def serve_forever(self) -> None:
        await self.start()
        self._stop_event = asyncio.Event()
        try:
            await self._stop_event.wait()
        finally:
            await self.stop()

    def _bases(self) -> list[tuple[str, str]]:
        return [(e.base_url, e.token_env) for e in self.config.server.pool] or [
            (self.config.server.base_url, self.config.server.token_env)
        ]

    # -- inbound -----------------------------------------------------------
    async def _on_item(self, item: IncomingItem) -> None:
        try:
            if isinstance(item, InboundMessage):
                await self._on_message(item)
            elif isinstance(item, IncomingInteraction):
                await self._on_interaction(item)
            elif isinstance(item, ConnectorEvent):
                await self._on_event(item)
        except Exception:  # noqa: BLE001 - never kill the connector loop
            log.exception("inbound_failed", item=type(item).__name__)

    async def _on_message(self, msg: InboundMessage) -> None:
        if not self._access_allowed(msg):
            log.info("access_denied", conversation=msg.conversation.key, sender=msg.sender.id)
            return
        key = f"{msg.conversation.key}:{msg.message_id}"
        if self.dedup.is_duplicate(key):
            log.info("duplicate_message", key=key)
            return
        connector = self.connectors.get(msg.channel)
        if connector is None:
            return
        command = _command(msg.text, self.config.commands.prefix)
        if command == "stop":
            await self._handle_stop(msg, connector)
            return
        route = await self.router.get_or_create(msg.conversation, title=_title(msg))
        if await self._maybe_answer_pending(route, msg, connector):
            return
        await self._start_turn(route, msg, connector)

    async def _on_interaction(self, item: IncomingInteraction) -> None:
        connector = self.connectors.get(item.conversation.channel)
        if connector is None:
            return
        value = hitl.decode_value(item.value)
        if value is None:
            log.info("interaction_unparsed", value=item.value)
            return
        sid = str(value.get("sid", ""))
        rid = str(value.get("rid", ""))
        engine = self._turns.get(sid)
        route = engine.route if engine is not None else await self.router.get_by_session(sid)
        if route is None:
            return
        pending = route.pending_interactions.get(rid)
        if pending is None:
            log.info("interaction_stale", rid=rid)
            return
        if not hitl.is_authorized(
            pending,
            item.sender,
            route.conversation,
            self.config,
            active_turn_sender=route.active_turn_sender,
        ):
            await self._notice(
                connector, route.conversation, "Only the requester may answer this interaction."
            )
            return
        client = self.router.client_for(route)
        if value.get("kind") == "permission":
            await client.reply_permission(sid, rid, reply=str(value.get("reply", "reject")))
        elif value.get("kind") == "question":
            if value.get("reject"):
                await client.reject_question(sid, rid)
            else:
                answer = value.get("answer") or []
                await client.reply_question(sid, rid, [list(answer)])
        route.pending_interactions.pop(rid, None)
        await self.router.save(route)

    async def _on_event(self, event: ConnectorEvent) -> None:
        log.info("connector_event", kind=event.kind, conversation=event.conversation.key)

    # -- turn lifecycle ----------------------------------------------------
    async def _start_turn(self, route: Route, msg: InboundMessage, connector: IMConnector) -> None:
        identity = await self.router.refresh_identity(route, connector)
        ingest = MediaIngest(
            self.config,
            connector,
            self.router.client_for(route),
            working_dir=_working_dir(self.config, route),
        )
        model_inputs = await self._model_inputs(route)
        result = await ingest.ingest(route.session_id, msg.attachments, model_inputs=model_inputs)
        prompt = self.composer.compose(
            route=route,
            inbound=msg,
            identity=identity,
            agent_description=route.bot_description,
        )
        if result.notes:
            prompt = f"{result.note_text()}\n\n{prompt}"

        engine = TurnEngine(
            route=route,
            inbound=msg,
            connector=connector,
            client=self.router.client_for(route),
            config=self.config,
            renderer=self.renderer,
            media_egress=MediaEgress(self.config, connector),
            on_finish=self._on_turn_finished,
        )
        sid = route.session_id
        had_active = sid in self._turns
        queue = self._turn_queue.setdefault(sid, [])
        queue.append(engine)
        route.queue_depth += 1
        route.participants[msg.sender.id] = msg.sender.name or msg.sender.id
        route.context_dirty = False
        route.identity_injected = True
        if not had_active:
            await self._activate(engine)
        await self.router.save(route)

        delivery = self._delivery_for(route, msg, had_active=had_active)
        try:
            await self.router.client_for(route).prompt(
                sid,
                prompt=prompt,
                files=result.files,
                id=f"{route.key}:{msg.message_id}",
                delivery=delivery,
            )
            self._bump("prompts")
        except AgentError as exc:
            log.warning("prompt_failed", error=exc.code)
            await self._notice(connector, route.conversation, user_message(exc.code))
            await self._discard(engine)

    async def _activate(self, engine: TurnEngine) -> None:
        sid = engine.route.session_id
        self._turns[sid] = engine
        engine.route.active_turn_sender = engine.inbound.sender.id
        await engine.start()

    async def _discard(self, engine: TurnEngine) -> None:
        """Remove a turn whose prompt could not be admitted."""
        queue = self._remove_engine(engine)
        if queue and engine.route.session_id not in self._turns:
            await self._activate(queue[0])

    async def _on_turn_finished(self, engine: TurnEngine) -> None:
        queue = self._remove_engine(engine)
        if queue and engine.route.session_id not in self._turns:
            await self._activate(queue[0])
        await self.router.save(engine.route)
        self._bump("turns")

    def _remove_engine(self, engine: TurnEngine) -> list[TurnEngine]:
        """Detach ``engine`` from its session's queue and return what remains."""
        sid = engine.route.session_id
        queue = self._turn_queue.get(sid) or []
        if engine in queue:
            queue.remove(engine)
        engine.route.queue_depth = max(0, engine.route.queue_depth - 1)
        if self._turns.get(sid) is engine:
            self._turns.pop(sid, None)
        if not queue:
            self._turn_queue.pop(sid, None)
        return queue
        self._bump("turns")

    async def _handle_stop(self, msg: InboundMessage, connector: IMConnector) -> None:
        route = await self.router.get(msg.conversation)
        if route is None:
            return
        if not hitl.command_authorized(
            msg.sender,
            route.conversation,
            self.config,
            active_turn_sender=route.active_turn_sender,
        ):
            await self._notice(
                connector, route.conversation, "Only the requester may stop this turn."
            )
            return
        engine = self._turns.get(route.session_id)
        if engine is not None:
            await engine.cancel()
        await self._notice(connector, route.conversation, "🛑 Stopped.")

    async def _maybe_answer_pending(
        self, route: Route, msg: InboundMessage, connector: IMConnector
    ) -> bool:
        if not route.pending_interactions:
            return False
        text = msg.text.strip()
        if not text.isdigit():
            return False
        index = int(text) - 1
        client = self.router.client_for(route)
        for rid, pending in list(route.pending_interactions.items()):
            if not hitl.is_authorized(
                pending,
                msg.sender,
                route.conversation,
                self.config,
                active_turn_sender=route.active_turn_sender,
            ):
                continue
            if pending.kind == "permission":
                replies = ["once", "always", "reject"]
                if 0 <= index < len(replies):
                    await client.reply_permission(route.session_id, rid, reply=replies[index])
                    route.pending_interactions.pop(rid, None)
                    await self.router.save(route)
                    return True
            else:
                if 0 <= index < len(pending.options):
                    await client.reply_question(route.session_id, rid, [[pending.options[index]]])
                    route.pending_interactions.pop(rid, None)
                    await self.router.save(route)
                    return True
        return False

    # -- SSE consumption + reconciliation ----------------------------------
    async def _consume_events(self, base_url: str, client: HttpAgentClient) -> None:
        backoff = self.config.server.sse_reconnect_ms / 1000.0
        while self._running:
            try:
                async for event in client.events():
                    await self._route_event(event)
                backoff = self.config.server.sse_reconnect_ms / 1000.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("sse_disconnected", base=base_url, error=str(exc))
            if not self._running:
                break
            await asyncio.sleep(backoff)
            backoff = min(backoff * 2, 30.0)
            await self._reconcile(base_url, client)

    async def _route_event(self, event: Event) -> None:
        sid = event.session_id
        if not sid:
            return
        engine = self._turns.get(sid)
        if engine is not None:
            await engine.handle_event(event)
            if event.type in (
                PERMISSION_ASKED,
                PERMISSION_REPLIED,
                QUESTION_ASKED,
                QUESTION_REPLIED,
                QUESTION_REJECTED,
            ):
                await self.router.save(engine.route)
            return
        if event.type == SESSION_STATUS:
            status = (event.data or {}).get("status") or {}
            log.debug("status_without_turn", session=sid, status=status)

    async def _reconcile(self, base_url: str, client: HttpAgentClient) -> None:
        """Recover live state after the event stream reconnects."""
        try:
            active = await client.active_sessions()
        except AgentError as exc:
            log.warning("reconcile_active_failed", error=exc.code)
            return
        for sid in active:
            route = await self.router.get_by_session(sid)
            if route is None:
                continue
            await self._recover_active(client, sid, route)
        await self._restore_hitl(client)

    async def _recover_active(self, client: HttpAgentClient, sid: str, route: Route) -> None:
        """Recover text/media of an in-flight turn (live deltas were lost)."""
        try:
            messages = await client.messages(sid)
        except AgentError as exc:
            log.warning("reconcile_message_failed", session=sid, error=exc.code)
            return
        text = assistant_text(messages)
        media = tool_media(messages)
        engine = self._turns.get(sid)
        if engine is not None:
            # Replace the possibly-incomplete live buffer with the durable text so
            # the final flush is complete.
            if text:
                engine.controller.text = text
            known = {_media_key(item) for item in engine.media}
            for item in media:
                if _media_key(item) not in known:
                    engine.media.append(item)
                    known.add(_media_key(item))
            log.info("reconcile_turn_seeded", session=sid, chars=len(text or ""))
            return
        # No live engine (e.g. bridge restarted mid-turn): surface what we have.
        connector = self.connectors.get(route.conversation.channel)
        if connector is not None and text:
            await self._notice(connector, route.conversation, text)

    async def _restore_hitl(self, client: HttpAgentClient) -> None:
        """Restore pending interactions and surface any we never saw."""
        perms, questions = [], []
        try:
            perms = await client.list_permissions()
            questions = await client.list_questions()
        except AgentError as exc:
            log.warning("reconcile_hitl_failed", error=exc.code)
            return
        for perm in perms:
            route = await self.router.get_by_session(perm.session_id)
            if route is None or perm.id in route.pending_interactions:
                continue
            await self._register_pending(
                route,
                "permission",
                perm.id,
                options=["once", "always", "reject"],
            )
            connector = self.connectors.get(route.conversation.channel)
            if connector is not None:
                card = hitl.permission_card(perm)
                if connector.capabilities.buttons:
                    await connector.send_card(route.conversation, card)
                else:
                    lines = [card.body, ""] + [
                        f"{i + 1}. {b.text}" for i, b in enumerate(card.buttons)
                    ]
                    await self._notice(connector, route.conversation, "\n".join(lines))
        for question in questions:
            route = await self.router.get_by_session(question.session_id)
            if route is None or question.id in route.pending_interactions:
                continue
            text, options = hitl.question_numbered_text(question)
            await self._register_pending(route, "question", question.id, options=options)
            connector = self.connectors.get(route.conversation.channel)
            if connector is not None:
                qcard = hitl.question_card(question)
                if qcard is not None and connector.capabilities.buttons:
                    await connector.send_card(route.conversation, qcard)
                else:
                    await self._notice(connector, route.conversation, text)

    async def _register_pending(
        self, route: Route, kind: Literal["permission", "question"], rid: str, *, options: list[str]
    ) -> None:
        route.pending_interactions[rid] = hitl.make_pending(
            kind,
            owner=route.active_turn_sender,
            scope=self.config.group.hitl_scope if route.conversation.is_group else "initiator",
            request_id=rid,
            options=options,
        )
        await self.router.save(route)

    async def _janitor(self) -> None:
        """Periodically restore pending interactions and reclaim idle leases."""
        interval = max(5, min(self.config.permissions.poll_interval_s, 30))
        try:
            while self._running:
                await asyncio.sleep(interval)
                for _base, client in self._clients:
                    try:
                        await self._restore_hitl(client)
                    except Exception:  # noqa: BLE001
                        log.exception("hitl_poll_failed")
                try:
                    reclaimed = await self.router.reclaim_idle()
                    if reclaimed:
                        log.info("leases_reclaimed", count=len(reclaimed))
                except Exception:  # noqa: BLE001
                    log.exception("lease_reclaim_failed")
        except asyncio.CancelledError:  # pragma: no cover - shutdown
            raise

    # -- helpers -----------------------------------------------------------
    def _delivery_for(self, route: Route, msg: InboundMessage, *, had_active: bool) -> str:
        if not had_active:
            return "queue"
        if not route.conversation.is_group:
            return "steer" if self.config.sessions.busy_delivery == "steer" else "queue"
        if self.config.group.cross_user_delivery == "steer_same_user":
            if route.active_turn_sender == msg.sender.id:
                return "steer"
        return "queue"

    async def _model_inputs(self, route: Route) -> set[str]:
        client = self.router.client_for(route)
        try:
            models = await client.list_models()
        except AgentError:
            return {"text", "image"}
        for model in models:
            if route.model and model.id == route.model:
                return set(model.inputs) | {"text"}
        if models:
            return set(models[0].inputs) | {"text"}
        return {"text", "image"}

    def _access_allowed(self, msg: InboundMessage) -> bool:
        access = self.config.access
        if access.allow_users and msg.sender.id not in access.allow_users:
            return False
        if msg.conversation.is_group:
            if access.allow_groups and msg.conversation.id not in access.allow_groups:
                return False
        return True

    async def _notice(self, connector: IMConnector, conv: Conversation, text: str) -> None:
        with contextlib.suppress(Exception):
            await connector.send(conv, OutboundPlan(segments=[TextSegment(text=text)]))

    def _bump(self, name: str, amount: int = 1) -> None:
        self.metrics[name] = self.metrics.get(name, 0) + amount


def _command(text: str, prefix: str) -> str | None:
    from .engine.commands import parse_command

    command = parse_command(text, prefix)
    return command.kind if command else None


def _media_key(media: RichMedia) -> tuple:
    """A content signature used to avoid re-adding recovered media."""
    return (
        media.kind,
        media.mime,
        media.name,
        media.url,
        len(media.data or b""),
        hashlib.sha1(media.data).hexdigest() if media.data else None,
    )


def assistant_text(messages: list[dict]) -> str | None:
    """Final text of the latest assistant message in a transcript."""
    for message in reversed(messages):
        if message.get("type") != "assistant":
            continue
        parts = [
            str(part.get("text", ""))
            for part in (message.get("content") or [])
            if part.get("type") == "text"
        ]
        text = "".join(parts)
        if text:
            return text
    return None


def tool_media(messages: list[dict]) -> list[RichMedia]:
    """File parts produced by tool calls within a transcript."""
    from .engine.media_egress import extract_file_parts

    out: list[RichMedia] = []
    for message in messages:
        if message.get("type") != "assistant":
            continue
        for part in message.get("content") or []:
            if part.get("type") != "tool":
                continue
            state = part.get("state") or {}
            out.extend(extract_file_parts(state.get("content")))
            out.extend(extract_file_parts(state.get("attachments")))
    return out


def _title(msg: InboundMessage) -> str | None:
    name = msg.conversation.name
    return f"{msg.conversation.kind}: {name}" if name else None


def _working_dir(config: Config, route: Route) -> str | None:
    for entry in config.server.pool:
        if entry.base_url.rstrip("/") == route.server_base.rstrip("/"):
            return entry.working_directory
    return None

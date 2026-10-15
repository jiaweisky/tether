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
import json
import os
import time
from collections.abc import Awaitable
from dataclasses import replace
from typing import Any, Literal

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
from .config import Config, load_config, validate_startup
from .connector import IMConnector, build_connectors
from .engine import hitl
from .engine.commands import Command, help_text, parse_command, unescape_command
from .engine.media_egress import MediaEgress, read_path_media, record_blocked
from .engine.media_ingest import MediaIngest
from .engine.projects import build_provider
from .engine.prompt import PromptComposer
from .engine.router import ClientFactory, Router
from .engine.turn import TurnEngine
from .metrics import metrics
from .models import (
    ConnectorEvent,
    Conversation,
    InboundMessage,
    IncomingInteraction,
    IncomingItem,
    OutboundPlan,
    RichMedia,
    Route,
    Sender,
    TextSegment,
)
from .render.markdown import render_markdown
from .render.renderer import DefaultRenderer
from .store.sqlite import RouteStore
from .util.dedup import DedupCache
from .util.logging import get_logger
from .util.path_policy import PathPolicy, resolve_under
from .util.redact import redact_secrets

log = get_logger("tether.app")

# A turn is only considered stale (by the watchdog) after it has been active for
# at least this long, so a just-started turn whose prompt has not yet reached
# agentd is not mistaken for a dead one.
_WATCHDOG_GRACE_S = 10.0

# Consecutive failed SSE reconnects (no event received) before raising a
# prolonged-disconnection alert.
_SSE_PROLONGED_AFTER = 3


class TetherApp:
    def __init__(
        self,
        config: Config,
        *,
        db_path: str = "tether.sqlite3",
        connectors: list[IMConnector] | None = None,
        client_factory: ClientFactory | None = None,
        config_path: str | None = None,
    ) -> None:
        self.config = config
        self._config_path = config_path
        self._config_mtime = 0.0
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
        self._sse_tasks: dict[str, asyncio.Task[None]] = {}
        self._clients: dict[str, HttpAgentClient] = {}
        self._janitor_task: asyncio.Task[None] | None = None
        self._watchdog_task: asyncio.Task[None] | None = None
        self._metrics_task: asyncio.Task[None] | None = None
        self._config_task: asyncio.Task[None] | None = None
        self._metrics_server: asyncio.AbstractServer | None = None
        self.metrics_port: int | None = None
        self._running = False
        self._stopped = False
        self._accepting = True
        self._stop_event: asyncio.Event | None = None
        self.metrics: dict[str, int] = metrics.counters

    # -- lifecycle ---------------------------------------------------------
    async def start(self) -> None:
        validate_startup(self.config)
        await self.provider.preflight()
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
        for base_url in self._base_urls():
            try:
                await self.router.warm_base(base_url)
            except Exception as exc:  # noqa: BLE001 - discovery retries on first message
                log.warning("agent_discovery_failed", base=base_url, error=str(exc))
        for base_url in self._base_urls():
            await self._ensure_sse(base_url)
        self._janitor_task = asyncio.ensure_future(self._janitor())
        self._watchdog_task = asyncio.ensure_future(self._watchdog_loop())
        if self.config.reload and self._config_path:
            self._config_mtime = _mtime(self._config_path)
            self._config_task = asyncio.ensure_future(self._watch_config())
        await self._start_metrics()
        log.info("tether_started", connectors=list(self.connectors))

    async def stop(self) -> None:
        if self._stopped:
            return
        self._stopped = True
        self._running = False
        self._accepting = False  # stop admitting new inbound messages
        if self._stop_event is not None:
            self._stop_event.set()
        started = time.monotonic()
        for task in self._sse_tasks.values():
            task.cancel()
        if self._janitor_task is not None:
            self._janitor_task.cancel()
        if self._watchdog_task is not None:
            self._watchdog_task.cancel()
        if self._config_task is not None:
            self._config_task.cancel()
        with contextlib.suppress(Exception):
            await self._stop_metrics()
        for task in self._sse_tasks.values():
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task
        if self._janitor_task is not None:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._janitor_task
        if self._watchdog_task is not None:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._watchdog_task
        if self._config_task is not None:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._config_task
        log.info("stop_streams_closed", elapsed_ms=_ms_since(started))
        for engine in list(self._turns.values()):
            # Default: just stop streaming and leave the turn on agentd so a
            # restart can resume it. `interrupt_on_shutdown` opts into stopping
            # it (interrupt + reject pending interactions).
            with contextlib.suppress(Exception):
                if self.config.sessions.interrupt_on_shutdown:
                    await asyncio.wait_for(engine.shutdown(), timeout=2)
                else:
                    await engine.pause()
        log.info("stop_turns_closed", elapsed_ms=_ms_since(started))
        for connector in self.connectors.values():
            with contextlib.suppress(Exception):
                await connector.stop()
        log.info("stop_connectors_closed", elapsed_ms=_ms_since(started))
        with contextlib.suppress(Exception):
            await self.store.flush()
        with contextlib.suppress(Exception):
            await self.router.close()
        with contextlib.suppress(Exception):
            await self.store.close()
        log.info("tether_stopped", elapsed_ms=_ms_since(started))

    async def serve_forever(self) -> None:
        await self.start()
        self._stop_event = asyncio.Event()
        try:
            await self._stop_event.wait()
        finally:
            await self.stop()

    def _base_urls(self) -> list[str]:
        pool = self.config.server.pool
        if pool:
            return [entry.base_url for entry in pool]
        return [self.config.server.base_url]

    async def _ensure_sse(self, base_url: str) -> None:
        """Start an event-stream consumer for a base if it has none.

        Isolated projects run on their own dynamic listener (not a configured
        base), so their events only arrive once we subscribe to that base too.
        """
        base = base_url.rstrip("/")
        if base in self._sse_tasks:
            return
        client = self.router.client_for_base(base)
        self._clients[base] = client
        self._sse_tasks[base] = asyncio.ensure_future(self._consume_events(base, client))

    async def _stop_sse(self, base: str) -> None:
        task = self._sse_tasks.pop(base, None)
        self._clients.pop(base, None)
        if task is not None:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await task

    async def _sync_sse(self) -> None:
        """Keep the consumer set equal to the configured bases + active leases."""
        desired = {base.rstrip("/") for base in self._base_urls()} | self.router.leases.bases()
        for base in list(self._sse_tasks):
            if base not in desired:
                await self._stop_sse(base)

    # -- inbound -----------------------------------------------------------
    async def _on_item(self, item: IncomingItem) -> None:
        if not self._accepting:
            return
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
        metrics.inc("inbound_messages")
        connector = self.connectors.get(msg.channel)
        if connector is None:
            return
        await connector.transcribe_voice(msg)
        text, escaped = unescape_command(msg.text, self.config.commands.prefix)
        if escaped:
            msg = replace(msg, text=text)
        elif await self._handle_command(msg, connector):
            return
        try:
            route = await self.router.get_or_create(msg.conversation, title=_title(msg))
        except Exception as exc:  # noqa: BLE001 - e.g. an isolated lease could not be allocated
            log.warning("route_unavailable", conversation=msg.conversation.key, error=str(exc))
            await self._notice(
                connector,
                msg.conversation,
                "⚠️ Could not allocate a project for this message; please retry.",
            )
            return
        if await self._maybe_answer_pending(route, msg, connector):
            return
        await self._start_turn(route, msg, connector)

    async def _handle_command(self, msg: InboundMessage, connector: IMConnector) -> bool:
        """Handle a local command; return whether the message was consumed."""
        command = parse_command(msg.text, self.config.commands.prefix)
        if command is None:
            return False
        try:
            await self._run_command(command, msg, connector)
        except Exception:  # noqa: BLE001 - a command must never fail silently
            log.exception("command_failed", command=command.kind)
            await self._notice(
                connector,
                msg.conversation,
                "⚠️ Something went wrong running that command; please try again.",
            )
        return True

    async def _run_command(
        self, command: Command, msg: InboundMessage, connector: IMConnector
    ) -> None:
        if command.kind == "stop":
            await self._handle_stop(msg, connector)
        elif command.kind == "new":
            await self._handle_new(msg, connector)
        elif command.kind == "whoami":
            await self._notice(
                connector,
                msg.conversation,
                f"🆔 your id: `{msg.sender.id}`\nconversation: `{msg.conversation.key}`",
            )
        elif command.kind == "status":
            await self._handle_status(msg, connector)
        elif command.kind == "send":
            await self._handle_send(msg, connector, command.args)
        elif command.kind == "config":
            await self._handle_config(msg, connector, command.args)
        elif command.kind == "help":
            await self._notice(
                connector, msg.conversation, help_text(self.config.commands.prefix)
            )

    async def _handle_status(self, msg: InboundMessage, connector: IMConnector) -> None:
        """`/status`: a read-only snapshot of the conversation and the bridge.

        The reply is visible to the whole conversation, so it is redacted by
        conversation type — a group shows only session/turn basics (no context,
        project or server details) and shortens the session id.
        """
        conv = msg.conversation
        group = conv.is_group
        route = await self.router.get(conv)
        lines = [f"📊 Status · {connector.name}{' · group' if group else ''}"]
        if route is None:
            lines.append("session: (none yet)")
        else:
            engine = self._turns.get(route.session_id)
            sid = _short_id(route.session_id) if group else route.session_id
            lines.append(f"session: {sid}   agent={route.agent}   model={route.model or '?'}")
            if group:
                lines.append(f"participants: {len(route.participants)}")
            else:
                lines.append(f"conversation: {conv.key}")
                info = await self._agentd_info(route.server_base)
                lines.extend(self._direct_status_lines(route, engine, info))
            state = "parked" if route.pending_interactions else ("running" if engine else "idle")
            lines.append(f"turn: {state}   waiting: {self._waiting(route)}")
            pending = _pending_summary(route.pending_interactions)
            if pending:
                lines.append(f"waiting on: {pending}")
        lines.append(
            f"uptime: {_human_duration(metrics.uptime_s())}"
            f"   active_turns={int(metrics.gauges.get('active_turns', 0))}"
        )
        await self._notice(connector, conv, "\n".join(lines))

    async def _agentd_info(self, base_url: str) -> dict[str, Any] | None:
        """agentd `GET /api/info` (version/pid), or ``None`` when unreachable.

        Bounded by a short timeout so a hung agentd never stalls `/status`.
        """
        try:
            call = self.router.client_for_base(base_url).get_info()
            return await asyncio.wait_for(call, timeout=2.0)
        except (AgentError, TimeoutError):
            return None

    def _direct_status_lines(
        self, route: Route, engine: TurnEngine | None, info: dict[str, Any] | None
    ) -> list[str]:
        """Detail shown only in a direct chat (never visible to a group)."""
        limit = route.context_limit or self.config.model.context_limit
        used = engine.usage.context_tokens if engine is not None else None
        context = f"context: {_human_tokens(used)} / {_human_tokens(limit)}"
        if engine is not None and (engine.usage.input_tokens or engine.usage.output_tokens):
            usage = engine.usage
            context += (
                f"   last: {_human_tokens(usage.input_tokens)} in /"
                f" {_human_tokens(usage.output_tokens)} out /"
                f" {_human_tokens(usage.cached_tokens)} cached"
            )
        lines = [context]
        workdir = self.router.working_directory(route)
        if workdir:
            lines.append(f"workdir: {workdir}")
        if self.config.projects.mode == "isolated":
            lines.append(
                f"project: {route.project_id or '?'} (isolated/{self.config.projects.isolation})"
            )
        lines.append(_agentd_line(route.server_base, info))
        if route.bot_name:
            lines.append(f"identity: {route.bot_name}")
        return lines

    def _waiting(self, route: Route) -> int:
        """Turns queued behind the one currently running, if any."""
        queue = self._turn_queue.get(route.session_id) or []
        running = 1 if self._turns.get(route.session_id) is not None else 0
        return max(0, len(queue) - running)

    async def _on_interaction(self, item: IncomingInteraction) -> None:
        connector = self.connectors.get(item.conversation.channel)
        if connector is None:
            return
        value = hitl.decode_value(item.value)
        if value is None:
            log.info("interaction_unparsed", value=item.value)
            return
        if value.get("specs") is not None:
            # A question form submit: turn the widgets into one answer per question.
            value["answers"] = _form_answers(value["specs"], item.form)
            if not any(value["answers"]):
                value["reject"] = True
        sid = str(value.get("sid", ""))
        rid = str(value.get("rid", ""))
        engine = self._turns.get(sid)
        route = engine.route if engine is not None else await self.router.get_by_session(sid)
        if route is None:
            log.info("interaction_no_route", rid=rid, session=sid)
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
        if engine is None:
            # The turn is running on agentd but this process has no engine for it
            # (e.g. the bridge restarted mid-turn). Attach one so the resumed turn
            # renders; answering the interaction resumes it.
            self._attach_resumed_engine(sid, route)
        label = _interaction_label(value)
        try:
            await self._reply_interaction(client, sid, rid, value)
        except AgentError as exc:
            if exc.code == "not_found":  # already answered/expired on agentd
                log.info("interaction_stale", rid=rid, session=sid)
                label = "⌛ Already handled"
            else:
                log.warning("interaction_reply_failed", rid=rid, error=exc.code)
                label = "⚠️ Could not process"
        route.pending_interactions.pop(rid, None)
        await self.router.save(route)
        with contextlib.suppress(Exception):
            await connector.acknowledge(item, label)

    async def _reply_interaction(
        self, client: HttpAgentClient, sid: str, rid: str, value: dict[str, Any]
    ) -> None:
        kind = value.get("kind")
        if kind == "permission":
            await client.reply_permission(sid, rid, reply=str(value.get("reply", "reject")))
        elif kind == "question":
            if value.get("reject"):
                await client.reject_question(sid, rid)
            elif value.get("answers") is not None:
                await client.reply_question(sid, rid, value["answers"])
            else:
                await client.reply_question(sid, rid, [list(value.get("answer") or [])])

    def _attach_resumed_engine(self, sid: str, route: Route) -> None:
        connector = self.connectors.get(route.conversation.channel)
        if connector is None:
            return
        inbound = InboundMessage(
            channel=route.conversation.channel,
            message_id="",
            conversation=route.conversation,
            sender=Sender(id=route.active_turn_sender or "unknown"),
            text="",
        )
        engine = TurnEngine(
            route=route,
            inbound=inbound,
            connector=connector,
            client=self.router.client_for(route),
            config=self.config,
            renderer=self.renderer,
            media_egress=MediaEgress(self.config, connector),
            on_finish=self._on_turn_finished,
            working_dir=self.router.working_directory(route),
        )
        self._turns[sid] = engine
        self._turn_queue[sid] = [engine]
        log.info("turn_resumed", session=sid, conversation=route.key)

    async def _on_event(self, event: ConnectorEvent) -> None:
        log.info("connector_event", kind=event.kind, conversation=event.conversation.key)

    # -- turn lifecycle ----------------------------------------------------
    async def _start_turn(self, route: Route, msg: InboundMessage, connector: IMConnector) -> None:
        working_dir = self.router.working_directory(route)
        identity = await self.router.refresh_identity(route, connector)
        ingest = MediaIngest(
            self.config,
            connector,
            self.router.client_for(route),
            working_dir=working_dir,
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

        # Two attempts: if the agent session was deleted (e.g. agentd restarted
        # with a fresh root), recreate it once and retry.
        for attempt in range(2):
            engine = TurnEngine(
                route=route,
                inbound=msg,
                connector=connector,
                client=self.router.client_for(route),
                config=self.config,
                renderer=self.renderer,
                media_egress=MediaEgress(self.config, connector),
                on_finish=self._on_turn_finished,
                working_dir=working_dir,
            )
            sid = route.session_id
            had_active = sid in self._turns
            self._turn_queue.setdefault(sid, []).append(engine)
            route.queue_depth += 1
            route.participants[msg.sender.id] = msg.sender.name or msg.sender.id
            route.context_dirty = False
            route.identity_injected = True
            if not had_active:
                await self._activate(engine)
            await self.router.save(route)

            try:
                await self.router.client_for(route).prompt(
                    sid,
                    prompt=prompt,
                    files=result.files,
                    id=f"{route.key}:{msg.message_id}",
                    delivery=self._delivery_for(route, msg, had_active=had_active),
                )
                self._bump("prompts")
                return
            except AgentError as exc:
                if exc.code == "not_found" and attempt == 0:
                    log.warning("session_missing", session=sid, conversation=route.key)
                    await self._discard(engine)
                    await self.router.recreate_session(route)
                    continue
                log.warning("prompt_failed", error=exc.code)
                await self._notice(connector, route.conversation, user_message(exc.code))
                await self._discard(engine)
                return

    async def _activate(self, engine: TurnEngine) -> None:
        sid = engine.route.session_id
        self._turns[sid] = engine
        engine.route.active_turn_sender = engine.inbound.sender.id
        engine.activated_at = time.monotonic()
        # An isolated project lives on its own dynamic base; subscribe before the
        # prompt so none of this turn's events are missed.
        await self._ensure_sse(engine.route.server_base)
        await engine.start()

    async def _discard(self, engine: TurnEngine) -> None:
        """Remove a turn whose prompt could not be admitted."""
        queue = self._remove_engine(engine)
        if queue and engine.route.session_id not in self._turns:
            await self._activate(queue[0])

    async def _on_turn_finished(self, engine: TurnEngine) -> None:
        # A finished turn has no answerable interactions: any still-pending entry
        # (an interrupted/expired ask) is stale and must not shadow later ones.
        engine.route.pending_interactions.clear()
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
        conv = msg.conversation
        route = await self.router.get(conv)
        if route is None:
            await self._notice(connector, conv, "ℹ️ Nothing to stop — this conversation is idle.")
            return
        if not hitl.command_authorized(
            msg.sender,
            route.conversation,
            self.config,
            active_turn_sender=route.active_turn_sender,
        ):
            await self._notice(
                connector,
                route.conversation,
                "🔒 Only the person who started this turn, or an admin, can stop it.",
            )
            return
        engine = self._turns.get(route.session_id)
        if engine is None:
            await self._notice(
                connector, route.conversation, "ℹ️ Nothing to stop — this turn already finished."
            )
            return
        await engine.cancel()
        await self._notice(connector, route.conversation, "🛑 Stopped the current turn.")

    async def _handle_new(self, msg: InboundMessage, connector: IMConnector) -> None:
        """`/new`: start a fresh agent session for this conversation.

        Only configured admins may run it; the project/view is left untouched.
        """
        conv = msg.conversation
        if msg.sender.id not in self.config.group.admins:
            await self._notice(
                connector, conv, "🔒 Only admins can start a new conversation."
            )
            return
        route = await self.router.get(conv)
        if route is None:
            await self._notice(
                connector, conv, "ℹ️ Nothing to reset yet — just send a message to start."
            )
            return
        old = route.session_id
        engine = self._turns.get(old)
        if engine is not None:
            await engine.cancel()
        self._turns.pop(old, None)
        self._turn_queue.pop(old, None)
        try:
            await self.router.client_for(route).delete_session(old)
        except AgentError as exc:
            log.warning("session_delete_failed", session=old, error=exc.code)
        try:
            await self.router.recreate_session(route)
        except Exception as exc:  # noqa: BLE001 - surface a failed reset to the user
            log.warning("session_recreate_failed", session=old, error=str(exc))
            await self._notice(
                connector,
                route.conversation,
                "⚠️ Could not start a new conversation; please try again.",
            )
            return
        await self._notice(connector, route.conversation, "🆕 Started a new conversation.")

    async def _handle_send(
        self, msg: InboundMessage, connector: IMConnector, args: str
    ) -> None:
        """`/send <path>`: deliver a project file to this conversation.

        The path is joined to the project directory when relative, resolved, and
        checked against ``media.outbound.patterns`` — the same egress policy that
        gates auto-forwarded files. A missing or blocked file is reported, not sent.
        """
        conv = msg.conversation
        route = await self.router.get(conv)
        if route is None:
            await self._notice(connector, conv, "ℹ️ No project here yet — send a message first.")
            return
        workdir = self.router.working_directory(route)
        result = _resolve_outbound_file(args, workdir, self.config)
        if isinstance(result, str):
            await self._notice(connector, conv, result)
            return
        await MediaEgress(self.config, connector).send(conv, result)

    async def _handle_config(self, msg: InboundMessage, connector: IMConnector, args: str) -> None:
        """`/config [--all]`: show configuration (admins, direct chat).

        Default: just the agentd server the conversation is using. `--all`: the
        (redacted) bridge config plus the full agentd config.
        """
        conv = msg.conversation
        if conv.is_group:
            await self._notice(connector, conv, "🔒 `/config` is available in a direct chat only.")
            return
        if msg.sender.id not in self.config.group.admins:
            await self._notice(connector, conv, "🔒 Only admins can view the configuration.")
            return
        option = args.strip()
        if option not in ("", "--all"):
            await self._notice(connector, conv, f"⚠️ Unknown option: `{option}` (use `--all`).")
            return
        route = await self.router.get(conv)
        base = route.server_base if route is not None else self.config.server.base_url
        payload: dict[str, Any] = {
            "agentd": await self._agentd_config(base, all_=(option == "--all"))
        }
        if option == "--all":
            payload = {"tether": redact_secrets(self.config.model_dump(mode="json")), **payload}
        await self._send_config(connector, conv, payload)

    async def _send_config(
        self, connector: IMConnector, conv: Conversation, payload: dict[str, Any]
    ) -> None:
        """Send ``payload`` as one or more ```json code blocks (markdown-rendered)."""
        dump = json.dumps(payload, indent=2, ensure_ascii=False, default=str)
        for chunk in _config_chunks(dump, connector.capabilities.max_text_chars):
            body, _ = render_markdown(chunk, connector.capabilities.markdown)
            await self._notice(connector, conv, body)

    async def _agentd_config(self, base_url: str, *, all_: bool) -> dict[str, Any]:
        """The agentd server this conversation uses, or its full config with ``all_``.

        Bounded by a timeout so a hung agentd cannot stall the reply.
        """
        client = self.router.client_for_base(base_url)
        try:
            info = await asyncio.wait_for(client.get_info(), timeout=5.0)
            if all_:
                config = await asyncio.wait_for(client.get_config(), timeout=5.0)
                return {"base_url": base_url, "info": info, "config": config}
            name = _current_server_name(info)
            config = await asyncio.wait_for(
                client.get_config(section="servers", server=name), timeout=5.0
            )
            servers = config.get("config", {}).get("servers") or []
            return {"base_url": base_url, "info": info, "servers": servers}
        except (AgentError, TimeoutError) as exc:
            code = exc.code if isinstance(exc, AgentError) else "timeout"
            return {"base_url": base_url, "error": str(code)}

    # -- config hot-reload -------------------------------------------------
    async def _watch_config(self) -> None:
        """Apply runtime-safe config changes when ``config.yaml`` changes."""
        path = self._config_path
        if path is None:
            return
        while self._running:
            await asyncio.sleep(2.0)
            mtime = _mtime(path)
            if mtime > self._config_mtime:
                self._config_mtime = mtime
                self._reload_config()

    def _reload_config(self) -> None:
        path = self._config_path
        if path is None:
            return
        try:
            updated = load_config(path)
        except Exception:  # noqa: BLE001 - keep running on a broken file
            log.warning("config_reload_failed", exc_info=True)
            return
        for name in _RUNTIME_SECTIONS:
            setattr(self.config, name, getattr(updated, name))
        log.info("config_reloaded")

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
                    reply = client.reply_permission(route.session_id, rid, reply=replies[index])
                    if await self._answer_pending(route, rid, reply):
                        return True
                    continue
            else:
                if 0 <= index < len(pending.options):
                    reply = client.reply_question(route.session_id, rid, [[pending.options[index]]])
                    if await self._answer_pending(route, rid, reply):
                        return True
                    continue
        return False

    async def _answer_pending(self, route: Route, rid: str, reply: Awaitable[None]) -> bool:
        """Send a pending-interaction reply; drop it on success or when stale.

        Returns True if agentd accepted the reply; False if it no longer has the
        interaction (already answered / expired), in which case the stale entry is
        dropped so it cannot shadow later ones.
        """
        try:
            await reply
            accepted = True
        except AgentError as exc:  # already answered/expired on agentd
            log.warning("stale_interaction_dropped", request=rid, error=exc.code)
            accepted = False
        route.pending_interactions.pop(rid, None)
        await self.router.save(route)
        return accepted

    # -- SSE consumption + reconciliation ----------------------------------
    async def _consume_events(self, base_url: str, client: HttpAgentClient) -> None:
        backoff = self.config.server.sse_reconnect_ms / 1000.0
        failures = 0
        while self._running:
            received = False
            try:
                async for event in client.events():
                    received = True
                    await self._route_event(event)
                backoff = self.config.server.sse_reconnect_ms / 1000.0
            except asyncio.CancelledError:
                raise
            except Exception as exc:  # noqa: BLE001
                log.warning("sse_disconnected", base=base_url, error=str(exc))
            if not self._running:
                break
            if received:
                failures = 0
                metrics.set("sse_disconnected", 0.0)
            else:
                failures += 1
                if failures == _SSE_PROLONGED_AFTER:
                    metrics.inc("sse_prolonged_disconnects")
                    metrics.set("sse_disconnected", 1.0)
                    log.error("sse_disconnected_prolonged", base=base_url, reconnects=failures)
            metrics.inc("sse_reconnects")
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

    async def _watchdog_loop(self) -> None:
        interval = self.config.sessions.turn_watchdog_s
        if interval <= 0:
            return
        while self._running:
            await asyncio.sleep(interval)
            try:
                await self._recover_stale_turns()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - the watchdog must never die
                log.exception("turn_watchdog_failed")

    async def _recover_stale_turns(self) -> None:
        """Finish turns the bridge thinks are running but agentd no longer has.

        A turn ends only on the live ``session.status idle`` event, which the
        global SSE does not replay. If that event is lost (a reconnect gap, an
        agentd restart, or a second bridge instance taking the connection) the
        turn would otherwise stay active and block the conversation's queue
        forever. Here we cross-check each active turn against agentd and finish
        the ones whose session is no longer running.
        """
        now = time.monotonic()
        by_base: dict[str, list[TurnEngine]] = {}
        for engine in self._turns.values():
            # Too new to judge: the prompt may not have started on agentd yet.
            if not engine.activated_at or now - engine.activated_at < _WATCHDOG_GRACE_S:
                continue
            by_base.setdefault(engine.route.server_base, []).append(engine)
        for base, engines in by_base.items():
            try:
                active = await self.router.client_for_base(base).active_sessions()
            except AgentError as exc:
                log.warning("turn_watchdog_probe_failed", base=base, error=exc.code)
                continue
            for engine in engines:
                if engine.route.session_id in active:
                    continue
                log.warning(
                    "stale_turn_recovered",
                    session=engine.route.session_id,
                    conversation=engine.route.key,
                )
                try:
                    await engine.finish()
                except Exception:  # noqa: BLE001 - one bad turn must not kill the watchdog
                    log.exception("stale_turn_finish_failed", session=engine.route.session_id)

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
                for _base, client in self._clients.items():
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
                with contextlib.suppress(Exception):
                    await self._sync_sse()
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
        metrics.inc(name, amount)

    # -- observability -----------------------------------------------------
    async def _start_metrics(self) -> None:
        cfg = self.config.metrics
        if cfg.log_interval_s > 0:
            self._metrics_task = asyncio.ensure_future(self._metrics_log_loop())
        if cfg.listen:
            host, _, port = cfg.listen.rpartition(":")
            server = await asyncio.start_server(
                self._handle_http, host or "127.0.0.1", int(port or "0")
            )
            self._metrics_server = server
            self.metrics_port = server.sockets[0].getsockname()[1]
            log.info("metrics_listening", address=cfg.listen)

    async def _stop_metrics(self) -> None:
        if self._metrics_task is not None:
            self._metrics_task.cancel()
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await self._metrics_task
        if self._metrics_server is not None:
            self._metrics_server.close()
            with contextlib.suppress(Exception):
                await self._metrics_server.wait_closed()

    def _refresh_gauges(self) -> None:
        metrics.set("active_turns", float(len(self._turns)))
        metrics.set("leases", float(self.router.leases.count))
        metrics.set("queue_depth", float(sum(e.route.queue_depth for e in self._turns.values())))

    async def _metrics_log_loop(self) -> None:
        while self._running:
            await asyncio.sleep(self.config.metrics.log_interval_s)
            try:
                self._refresh_gauges()
                log.info("metrics", **metrics.snapshot())
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - the log loop must never die
                log.exception("metrics_log_failed")

    async def _handle_http(
        self, reader: asyncio.StreamReader, writer: asyncio.StreamWriter
    ) -> None:
        try:
            request = (await asyncio.wait_for(reader.readline(), timeout=5)).decode("latin-1")
            path = request.split(" ")[1] if len(request.split(" ")) >= 2 else "/"
            while True:  # drain headers
                header = await asyncio.wait_for(reader.readline(), timeout=5)
                if header in (b"\r\n", b"\n", b""):
                    break
            self._refresh_gauges()
            if path == "/healthz":
                body = await self._health_payload()
                ok = body["status"] == "ok"
                status = "200 OK" if ok else "503 Service Unavailable"
                content, ctype = json.dumps(body), "application/json"
            elif path == "/metrics":
                status, content, ctype = "200 OK", metrics.prometheus(), "text/plain; version=0.0.4"
            else:
                status, content, ctype = "404 Not Found", "not found", "text/plain"
            payload = content.encode()
            writer.write(
                f"HTTP/1.1 {status}\r\nContent-Type: {ctype}\r\n"
                f"Content-Length: {len(payload)}\r\nConnection: close\r\n\r\n".encode()
                + payload
            )
            await writer.drain()
        except Exception:  # noqa: BLE001 - a probe must never crash the bridge
            log.debug("metrics_probe_failed", exc_info=True)
        finally:
            writer.close()
            with contextlib.suppress(Exception):
                await writer.wait_closed()

    async def _health_payload(self) -> dict[str, Any]:
        agentd = {}
        for base in self._base_urls():
            try:
                agentd[base] = await self.router.client_for_base(base).health()
            except Exception:  # noqa: BLE001
                agentd[base] = False
        ok = bool(self.connectors) and all(agentd.values())
        return {
            "status": "ok" if ok else "degraded",
            "uptime_s": round(metrics.uptime_s(), 1),
            "connectors": sorted(self.connectors),
            "agentd": agentd,
            "active_turns": len(self._turns),
            "leases": self.router.leases.count,
        }


def _ms_since(started: float) -> int:
    return int((time.monotonic() - started) * 1000)


def _interaction_label(value: dict[str, Any]) -> str:
    """A short outcome label to write back onto a clicked card."""
    kind = value.get("kind")
    if kind == "permission":
        return {
            "once": "✅ Allow once",
            "always": "✅ Always allow",
            "reject": "⛔ Deny",
        }.get(str(value.get("reply")), "✅ Handled")
    if kind == "question":
        if value.get("reject"):
            return "⛔ Cancelled"
        if value.get("answers") is not None:
            picked = ["，".join(answer) for answer in value["answers"] if answer]
            return "✅ " + ("；".join(picked) if picked else "Answered")
        answer = value.get("answer") or []
        return "✅ " + (", ".join(str(a) for a in answer) if answer else "Answered")
    return "✅ Handled"


def _short_id(sid: str) -> str:
    return f"{sid[:8]}…" if len(sid) > 8 else sid


def _human_tokens(count: int | None) -> str:
    if not count:
        return "-"
    if count >= 1_000_000:
        return f"{count / 1_000_000:.1f}M"
    if count >= 1000:
        return f"{count / 1000:.1f}k"
    return str(count)


def _human_duration(seconds: float) -> str:
    hours, rem = divmod(int(seconds), 3600)
    minutes, secs = divmod(rem, 60)
    if hours:
        return f"{hours}h{minutes}m"
    if minutes:
        return f"{minutes}m{secs}s"
    return f"{secs}s"


def _pending_summary(pending: dict[str, Any]) -> str:
    counts: dict[str, int] = {}
    for item in pending.values():
        kind = getattr(item, "kind", "?")
        counts[kind] = counts.get(kind, 0) + 1
    return ", ".join(kind if n == 1 else f"{kind} ×{n}" for kind, n in counts.items())


def _form_answers(specs: list[dict[str, Any]], form: dict[str, Any]) -> list[list[str]]:
    """Turn submitted form widgets into one answer list per question.

    A single-choice question is a ``select_static`` named ``q{i}``; a
    multi-choice question is one ``checker`` named ``q{i}_{j}`` per option.
    """
    answers: list[list[str]] = []
    for q_index, spec in enumerate(specs):
        options = spec.get("options") or []
        if spec.get("multiple"):
            answers.append(
                [
                    options[o_index]
                    for o_index in range(len(options))
                    if form.get(f"q{q_index}_{o_index}")
                ]
            )
        else:
            chosen = form.get(f"q{q_index}")
            answers.append([str(chosen)] if chosen else [])
    return answers


# Config sections safe to hot-reload (read at call time). channels/credentials/
# server/agent are not, so those still require a restart.
_RUNTIME_SECTIONS = (
    "group",
    "access",
    "permissions",
    "commands",
    "identity",
    "sessions",
    "media",
)


def _mtime(path: str) -> float:
    try:
        return os.path.getmtime(path)
    except OSError:
        return 0.0


def _current_server_name(info: dict[str, Any]) -> str | None:
    """The single agentd server name reported for this listener, if unambiguous."""
    names = info.get("servers") or []
    return names[0] if len(names) == 1 else None


def _config_chunks(dump: str, limit: int) -> list[str]:
    """Wrap a JSON dump into one or more fenced code blocks within ``limit`` chars.

    Splitting before fencing keeps each message a valid, self-contained code block
    (a raw char-split by the connector would break the fence).
    """
    if limit <= 0:  # the channel imposes no length limit
        return [f"```json\n{dump}\n```"]
    body_limit = max(1, limit - len("```json\n") - len("\n```"))
    pieces: list[str] = []
    current = ""
    for line in dump.splitlines(keepends=True):
        while len(line) > body_limit:
            if current:
                pieces.append(current)
                current = ""
            pieces.append(line[:body_limit])
            line = line[body_limit:]
        if len(current) + len(line) > body_limit:
            pieces.append(current)
            current = line
        else:
            current += line
    if current or not pieces:
        pieces.append(current)
    return [f"```json\n{piece}\n```" for piece in pieces]


def _agentd_line(base: str, info: dict[str, Any] | None) -> str:
    """The `/status` ``agentd:`` line, with version/pid when reachable."""
    if info is None:
        return f"agentd: {base} (unreachable)"
    bits: list[str] = []
    if info.get("version"):
        bits.append(f"v{info['version']}")
    if info.get("pid"):
        bits.append(f"pid {info['pid']}")
    suffix = f" · {' · '.join(bits)}" if bits else ""
    return f"agentd: {base}{suffix}"


def _strip_quotes(text: str) -> str:
    """Drop one pair of matching surrounding quotes (``"/a b.md"`` → ``/a b.md``)."""
    if len(text) >= 2 and text[0] == text[-1] and text[0] in ("'", '"'):
        return text[1:-1]
    return text


def _resolve_outbound_file(args: str, workdir: str | None, config: Config) -> RichMedia | str:
    """Resolve and policy-check a `/send` target.

    Returns the media to deliver, or a user-facing error string. A plain helper so
    the resolve/check/read steps stay out of the async handler.
    """
    path = resolve_under(_strip_quotes(args), workdir)
    name = path.name
    if not path.is_file():
        return f"⚠️ No such file: `{name}`."
    if not PathPolicy(config.media.outbound.patterns).allowed(path, working_dir=workdir):
        record_blocked(str(path))
        return f"⚠️ Not sent: `{name}` — outside the allowed send paths."
    media = read_path_media(path, config.media.max_bytes)
    if media is None:
        return f"⚠️ `{name}` is too large or could not be read."
    return media


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

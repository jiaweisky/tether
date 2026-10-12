"""Danger: drive a single conversation turn from the agent event stream.

A turn aggregates text, reasoning and tool activity, streams snapshots to the
channel, raises permission and question prompts, collects any media the tools
produced, and finalises when the session returns to idle.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any, Literal

from ..agent.client import HttpAgentClient
from ..agent.errors import AgentError
from ..agent.events import (
    ATTACHMENT_OMITTED,
    COMPACTION_ENDED,
    COMPACTION_STARTED,
    PERMISSION_ASKED,
    PERMISSION_REPLIED,
    QUESTION_ASKED,
    QUESTION_REJECTED,
    QUESTION_REPLIED,
    REASONING_DELTA,
    REASONING_ENDED,
    SESSION_STATUS,
    STEP_ENDED,
    STEP_FAILED,
    TEXT_DELTA,
    TEXT_ENDED,
    TOOL_CALLED,
    TOOL_FAILED,
    TOOL_PROGRESS,
    TOOL_SUCCESS,
    Event,
    PendingPermission,
    PendingQuestion,
)
from ..config import Config
from ..connector import IMConnector, Unsupported
from ..models import (
    InboundMessage,
    OutboundPlan,
    RichDoc,
    RichMedia,
    Route,
    Segment,
    SentRef,
    TextSegment,
    Usage,
)
from ..render.renderer import DefaultRenderer
from ..util.logging import get_logger
from . import hitl
from .media_egress import MediaEgress, extract_file_parts
from .streaming import RateLimited, StreamingController

log = get_logger("tether.turn")

FinishCb = Callable[["TurnEngine"], Awaitable[None]]
EventHandler = Callable[[dict[str, Any]], Awaitable[None]]


class TurnEngine:
    def __init__(
        self,
        *,
        route: Route,
        inbound: InboundMessage,
        connector: IMConnector,
        client: HttpAgentClient,
        config: Config,
        renderer: DefaultRenderer,
        media_egress: MediaEgress,
        on_finish: FinishCb,
    ) -> None:
        self.route = route
        self.inbound = inbound
        self.connector = connector
        self.client = client
        self.config = config
        self.renderer = renderer
        self.media_egress = media_egress
        self.on_finish = on_finish

        self.conv = route.conversation
        self.usage = Usage(context_limit=config.model.context_limit)
        self.media: list[RichMedia] = []
        self._sent_ref: SentRef | None = None
        self._placeholder_sent = False
        self._ended = False
        self._can_stream = bool(
            connector.capabilities.native_stream or connector.capabilities.edit_message
        )
        self.controller = StreamingController(
            self._emit,
            interval_s=config.streaming.min_interval_ms / 1000.0,
            boundary_flush=config.streaming.boundary_flush,
            max_live_chars=config.streaming.max_live_chars,
            rate_limit_backoff=config.streaming.rate_limit_backoff,
        )
        self._handlers: dict[str, EventHandler] = {
            TEXT_DELTA: self._on_text_delta,
            TEXT_ENDED: self._on_text_ended,
            REASONING_DELTA: self._on_reasoning_delta,
            REASONING_ENDED: self._on_reasoning_ended,
            TOOL_CALLED: self._on_tool_called,
            TOOL_PROGRESS: self._on_tool_progress,
            TOOL_SUCCESS: self._on_tool_success,
            TOOL_FAILED: self._on_tool_failed,
            STEP_ENDED: self._on_step_ended,
            STEP_FAILED: self._on_step_failed,
            ATTACHMENT_OMITTED: self._on_attachment_omitted,
            COMPACTION_STARTED: self._on_compaction_started,
            COMPACTION_ENDED: self._on_compaction_ended,
            SESSION_STATUS: self._on_status,
            PERMISSION_ASKED: self._on_permission,
            QUESTION_ASKED: self._on_question,
            PERMISSION_REPLIED: self._on_interaction_closed,
            QUESTION_REPLIED: self._on_interaction_closed,
            QUESTION_REJECTED: self._on_interaction_closed,
        }

    # -- lifecycle ---------------------------------------------------------
    async def start(self) -> None:
        if self.connector.capabilities.typing:
            try:
                await self.connector.send_typing(self.conv)
            except Exception:  # noqa: BLE001 - typing is best-effort
                pass

    async def handle_event(self, event: Event) -> None:
        handler = self._handlers.get(event.type)
        if handler is not None:
            await handler(event.data or {})

    async def finish(self) -> None:
        if self._ended:
            return
        self._ended = True
        try:
            await self.controller.finalize()
        except Exception:  # noqa: BLE001 - a send failure must not stop event consumption
            log.exception("final_flush_failed")
        await self._drain_media()
        if self.connector.capabilities.reactions and self._sent_ref is not None:
            try:
                await self.connector.react(self._sent_ref, "✅")
            except Exception:  # noqa: BLE001
                pass
        await self.on_finish(self)

    async def cancel(self) -> None:
        try:
            await self.client.interrupt(self.route.session_id)
        except AgentError as exc:
            log.warning("interrupt_failed", error=exc.code)
        await self._reject_pending_permissions()
        await self.controller.close()

    async def _drain_media(self) -> None:
        for media in self.media:
            try:
                await self.media_egress.send(self.conv, media)
            except Exception:  # noqa: BLE001
                log.warning("media_egress_failed", kind=media.kind)
        self.media.clear()

    async def _reject_pending_permissions(self) -> None:
        for request_id, pending in list(self.route.pending_interactions.items()):
            if pending.kind != "permission":
                continue
            try:
                await self.client.reply_permission(
                    self.route.session_id, request_id, reply="reject"
                )
            except AgentError:
                pass

    # -- event handlers ----------------------------------------------------
    async def _on_text_delta(self, data: dict[str, Any]) -> None:
        self.controller.push_text(str(data.get("delta", "")))

    async def _on_text_ended(self, data: dict[str, Any]) -> None:
        if data.get("text") is not None:
            self.controller.text = str(data["text"])

    async def _on_reasoning_delta(self, data: dict[str, Any]) -> None:
        if self.config.streaming.show_reasoning:
            self.controller.push_reasoning(str(data.get("delta", "")))

    async def _on_reasoning_ended(self, data: dict[str, Any]) -> None:
        if self.config.streaming.show_reasoning and data.get("text"):
            self.controller.reasoning = str(data["text"])

    async def _on_tool_called(self, data: dict[str, Any]) -> None:
        name = _tool_name(data)
        if name and self.config.streaming.show_tools:
            self.controller.note_tool(name)

    async def _on_tool_progress(self, data: dict[str, Any]) -> None:
        self.media.extend(extract_file_parts(data.get("content")))

    async def _on_tool_success(self, data: dict[str, Any]) -> None:
        self.media.extend(extract_file_parts(data.get("content")))
        if self.config.streaming.show_tools:
            self.controller.clear_tool()

    async def _on_tool_failed(self, data: dict[str, Any]) -> None:
        self.controller.push_text(f"\n\n⚠️ A tool failed: {_short(data.get('error'))}\n")

    async def _on_step_ended(self, data: dict[str, Any]) -> None:
        self._record_usage(data)

    async def _on_step_failed(self, data: dict[str, Any]) -> None:
        error = data.get("error") or {}
        message = error.get("message") if isinstance(error, dict) else str(error)
        self.controller.push_text(f"\n\n⚠️ {message or 'The step failed.'}\n")

    async def _on_attachment_omitted(self, data: dict[str, Any]) -> None:
        name = data.get("name", "attachment")
        reason = data.get("reason", "unsupported")
        await self._send_notice(f"⚠️ `{name}` was not sent to the model ({reason}).")

    async def _on_compaction_started(self, data: dict[str, Any]) -> None:
        await self._send_notice("🧹 Organizing context…")

    async def _on_compaction_ended(self, data: dict[str, Any]) -> None:
        # A summary can drop the identity preamble, so refresh it next turn.
        self.route.context_dirty = True

    async def _on_status(self, data: dict[str, Any]) -> None:
        status = data.get("status") or {}
        stype = status.get("type") if isinstance(status, dict) else None
        if stype == "idle":
            await self.finish()
        elif stype == "retry":
            attempt = status.get("attempt") or status.get("next") or 1
            await self._send_notice(f"⏳ Model busy, retrying (#{attempt})…")

    async def _on_permission(self, data: dict[str, Any]) -> None:
        perm = PendingPermission.from_json(data)
        action = self.config.permissions.action_for(perm.action)
        if action in ("once", "always", "reject"):
            await self._reply_permission(perm, action)
            return
        self._register_pending("permission", perm.id)
        card = hitl.permission_card(perm)
        if self.connector.capabilities.buttons:
            await self.connector.send_card(self.conv, card)
        else:
            options = [button.text for button in card.buttons]
            self.route.pending_interactions[perm.id].options = options
            await self._send_notice(_numbered_text(card.body, options))

    async def _on_question(self, data: dict[str, Any]) -> None:
        question = PendingQuestion.from_json(data)
        text, options = hitl.question_numbered_text(question)
        self._register_pending("question", question.id, options=options)
        card = hitl.question_card(question)
        if card is not None and self.connector.capabilities.buttons:
            await self.connector.send_card(self.conv, card)
        else:
            await self._send_notice(text)

    async def _on_interaction_closed(self, data: dict[str, Any]) -> None:
        self.route.pending_interactions.pop(str(data.get("requestID", "")), None)

    async def _reply_permission(self, perm: PendingPermission, reply: str) -> None:
        try:
            await self.client.reply_permission(perm.session_id, perm.id, reply=reply)
        except AgentError as exc:
            log.warning("auto_permission_failed", error=exc.code)

    def _register_pending(
        self,
        kind: Literal["permission", "question"],
        request_id: str,
        *,
        options: list[str] | None = None,
    ) -> None:
        scope = self.config.group.hitl_scope if self.conv.is_group else "initiator"
        self.route.pending_interactions[request_id] = hitl.make_pending(
            kind,
            owner=self.route.active_turn_sender,
            scope=scope,
            request_id=request_id,
            options=options,
        )

    # -- emit / rendering --------------------------------------------------
    async def _emit(self, final: bool, snapshot: str) -> None:
        if not final and await self._maybe_placeholder(snapshot):
            return
        plan = self._render(final)
        if self._sent_ref is None:
            self._sent_ref = await self.connector.send(self.conv, plan)
        else:
            await self._update_or_send(plan)

    async def _maybe_placeholder(self, snapshot: str) -> bool:
        """Send a thinking placeholder for interim frames when nothing can stream."""
        if not self._can_stream:
            if not self._placeholder_sent:
                await self._send_notice("🤔 Thinking…")
                self._placeholder_sent = True
            return True
        if not snapshot.strip() and self._sent_ref is None:
            await self._send_notice("🤔 Thinking…")
            self._placeholder_sent = True
            return True
        return False

    def _render(self, final: bool) -> OutboundPlan:
        doc = RichDoc(
            markdown=self.controller.text,
            reasoning=self.controller.reasoning if self.config.streaming.show_reasoning else None,
            usage=self.usage if final and self.config.streaming.show_usage else None,
        )
        plan = self.renderer.render(doc, self.connector.capabilities)
        if self.conv.is_group and self.config.group.reply_with_mention:
            plan.reply_to = self.inbound.message_id
        return plan

    async def _update_or_send(self, plan: OutboundPlan) -> None:
        """Replace the streamed text and emit any non-text segments separately."""
        text_segments: list[Segment] = [s for s in plan.segments if isinstance(s, TextSegment)]
        other_segments: list[Segment] = [s for s in plan.segments if not isinstance(s, TextSegment)]
        if text_segments:
            await self._replace_text(OutboundPlan(segments=text_segments))
        for segment in other_segments:
            await self.connector.send(self.conv, OutboundPlan(segments=[segment]))

    async def _replace_text(self, plan: OutboundPlan) -> None:
        assert self._sent_ref is not None
        try:
            await self.connector.update(self._sent_ref, plan)
        except (Unsupported, AgentError):
            self._sent_ref = await self.connector.send(self.conv, plan)
        except RateLimited:
            raise

    async def _send_notice(self, text: str) -> None:
        await self.connector.send(self.conv, OutboundPlan(segments=[TextSegment(text=text)]))

    # -- usage -------------------------------------------------------------
    def _record_usage(self, data: dict[str, Any]) -> None:
        tokens = data.get("tokens")
        if isinstance(tokens, dict):
            self._record_tokens(tokens)
        cost = data.get("cost")
        if cost is not None:
            try:
                self.usage.cost = float(cost)
            except (TypeError, ValueError):
                pass

    def _record_tokens(self, tokens: dict[str, Any]) -> None:
        self.usage.input_tokens = _as_int(tokens.get("input"), self.usage.input_tokens)
        self.usage.output_tokens = _as_int(tokens.get("output"), self.usage.output_tokens)
        self.usage.reasoning_tokens = _as_int(tokens.get("reasoning"), 0)
        self.usage.cached_tokens = _as_int(tokens.get("cache"), 0)
        if tokens.get("input") is not None:
            self.usage.context_tokens = _as_int(tokens["input"], 0)


def _numbered_text(body: str, options: list[str]) -> str:
    lines = [body, ""]
    lines.extend(f"{index + 1}. {text}" for index, text in enumerate(options))
    return "\n".join(lines)


def _as_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _tool_name(data: dict[str, Any]) -> str | None:
    for key in ("tool", "name"):
        if data.get(key):
            return str(data[key])
    return None


def _short(err: Any) -> str:
    if isinstance(err, dict):
        return str(err.get("message") or err.get("type") or "error")
    return str(err)


__all__ = ["TurnEngine"]

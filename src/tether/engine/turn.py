"""Danger: drive a single conversation turn from the agent event stream.

A turn aggregates text, reasoning and tool activity, streams snapshots to the
channel, raises permission and question prompts, collects any media the tools
produced, and finalises when the session returns to idle.
"""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from typing import Any, Literal

from tether.agent.base import AgentBackend
from tether.agent.errors import AgentError
from tether.agent.events import (
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
    REASONING_STARTED,
    SESSION_STATUS,
    STEP_ENDED,
    STEP_FAILED,
    STEP_STARTED,
    TEXT_DELTA,
    TEXT_ENDED,
    TEXT_STARTED,
    TOOL_CALLED,
    TOOL_FAILED,
    TOOL_PROGRESS,
    TOOL_SUCCESS,
    AttachmentOmittedData,
    EmptyData,
    ErrorData,
    Event,
    FilePart,
    PendingPermission,
    PermissionAskedData,
    PermissionRepliedData,
    QuestionAskedData,
    QuestionClosedData,
    StepEndedData,
    TextData,
    ToolCalledData,
    ToolData,
    TurnStatusData,
)
from tether.agent.usage import UsageTokens, parse_usage
from tether.config import Config
from tether.connector import IMConnector
from tether.engine import hitl
from tether.engine.media_egress import (
    MediaEgress,
    file_part_to_media,
    files_from_paths,
    record_blocked,
)
from tether.engine.streaming import RateLimited, StreamingController
from tether.metrics import metrics
from tether.models import (
    Card,
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
from tether.render.renderer import DefaultRenderer
from tether.util.logging import get_logger
from tether.util.path_policy import PathPolicy, resolve_under

log = get_logger("tether.turn")

# agentd policy denials are expected sometimes; surface one friendly notice instead
# of raw tool errors. Tether cannot infer the deployment's read-only/read-write
# mode from this error, so the wording must stay generic.
_DENIED_HINTS = (
    "permission blocked",
    "permission denied",
    "not permitted",
    "read-only",
    "read only",
)

# Why agentd left an inbound attachment out of the model prompt (readable wording).
_OMIT_REASONS = {
    "too_large": "it exceeds the size limit",
    "unsupported_modality": "the model does not accept this media type",
    "unsupported_type": "the media type is unsupported",
    "unsupported_source": "the media source is unsupported",
    "unsupported_role": "the media role is unsupported",
    "invalid_payload": "the payload is invalid",
    "url_not_allowed": "a caller-supplied url is not allowed",
}

FinishCb = Callable[["TurnEngine"], Awaitable[None]]
EventHandler = Callable[[Any], Awaitable[None]]


class TurnEngine:
    def __init__(
        self,
        *,
        route: Route,
        inbound: InboundMessage,
        connector: IMConnector,
        client: AgentBackend,
        config: Config,
        renderer: DefaultRenderer,
        media_egress: MediaEgress,
        on_finish: FinishCb,
        working_dir: str | None = None,
    ) -> None:
        self.route = route
        self.inbound = inbound
        self.connector = connector
        self.client = client
        self.config = config
        self.renderer = renderer
        self.media_egress = media_egress
        self.on_finish = on_finish
        self.working_dir = working_dir

        self.conv = route.conversation
        self.usage = Usage(context_limit=route.context_limit or config.model.context_limit)
        self.media: list[RichMedia] = []
        self._media_paths: dict[str, None] = {}
        self._media_seen: set[str] = set()
        self._sent_ref: SentRef | None = None
        self._placeholder_sent = False
        self._denied_notice_sent = False
        self._ended = False
        # Last durable aggregate sequence observed for this session. Used to
        # replay only the events missed across an SSE reconnect. It is kept on
        # the Route as well so a new turn does not replay earlier turns.
        self.last_seq: int = route.last_seq
        self.cursor_dirty = False
        # Set by the app when the engine becomes the conversation's active turn;
        # used by the watchdog to tell a genuinely running turn from a stale one.
        self.activated_at: float = 0.0
        self._timers: dict[str, asyncio.Task[None]] = {}
        self._can_stream = connector.supports_streaming(route.conversation)
        self.controller = StreamingController(
            self._emit,
            interval_s=config.streaming.min_interval_ms / 1000.0,
            boundary_flush=config.streaming.boundary_flush,
            max_live_chars=config.streaming.max_live_chars,
            rate_limit_backoff=config.streaming.rate_limit_backoff,
            idle_progress_s=config.streaming.idle_progress_ms / 1000.0,
        )
        self._handlers: dict[str, EventHandler] = {
            TEXT_STARTED: self._on_activity,
            TEXT_DELTA: self._on_text_delta,
            TEXT_ENDED: self._on_text_ended,
            REASONING_STARTED: self._on_activity,
            REASONING_DELTA: self._on_reasoning_delta,
            REASONING_ENDED: self._on_reasoning_ended,
            STEP_STARTED: self._on_activity,
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
        cap = self.connector.capabilities
        if self._can_stream:
            # Open the stream with a placeholder only when the channel wants one;
            # a channel that streams real content from the first token opens it
            # with that content instead.
            if cap.progress_placeholder:
                try:
                    self._sent_ref = await self.connector.send(
                        self.conv,
                        OutboundPlan(segments=[TextSegment(text="🤔 Thinking…")], final=False),
                    )
                    self._placeholder_sent = True
                except Exception:  # noqa: BLE001 - placeholder is best-effort
                    log.warning("placeholder_failed", exc_info=True)
        elif cap.typing:
            try:
                await self.connector.send_typing(self.conv)
            except Exception:  # noqa: BLE001 - typing is best-effort
                pass
        elif cap.progress_placeholder:
            try:
                await self._send_notice("🤔 Thinking…")
            except Exception:  # noqa: BLE001 - placeholder is best-effort
                log.warning("placeholder_failed", exc_info=True)
            self._placeholder_sent = True

    async def handle_event(self, event: Event) -> None:
        handler = self._handlers.get(event.type)
        if handler is not None:
            await handler(event.data)

    async def finish(self) -> None:
        if self._ended:
            return

        self._ended = True
        self._cancel_timers()

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
        """Stop the turn (``/stop``): interrupt, reject pending, drop the stream."""
        self._cancel_timers()
        await self._interrupt()
        await self.controller.close()

    async def shutdown(self) -> None:
        """Graceful shutdown: interrupt and flush the current snapshot as final."""
        if self._ended:
            return

        self._ended = True
        self._cancel_timers()
        await self._interrupt()

        if self._sent_ref is not None or self.controller.snapshot().strip():
            try:
                await self.controller.finalize()
            except Exception:  # noqa: BLE001 - shutdown must not raise
                log.exception("shutdown_flush_failed")
        else:
            await self.controller.close()

    async def pause(self) -> None:
        """Stop streaming without disturbing the agent (used on bridge shutdown).

        The turn keeps running on agentd; a parked permission stays parked, so a
        restart does not consume it and the conversation can resume.
        """
        await self.controller.close()

    async def _interrupt(self) -> None:
        try:
            await self.client.interrupt(self.route.session_id)
        except AgentError as exc:
            log.warning("interrupt_failed", error=exc.code)
        await self._reject_pending_permissions()

    async def _drain_media(self) -> None:
        produced = list(self.media)  # explicit tool media: always forwarded
        produced += self._auto_path_files()
        seen: set[str] = set()

        for media in produced:
            key = media.name or media.url or ""
            if key and key in seen:
                continue
            if key:
                seen.add(key)
            try:
                await self.media_egress.send(self.conv, media)
            except Exception:  # noqa: BLE001
                log.warning("media_egress_failed", kind=media.kind)

        self.media.clear()
        self._media_paths.clear()
        self._media_seen.clear()

    def _auto_path_files(self) -> list[RichMedia]:
        """Files named by tools on disk, when auto-forwarding is enabled.

        Path-based files are opt-in (``media.outbound.auto_files``) and must match
        ``media.outbound.patterns``. A disallowed candidate is skipped **silently**
        (auto-forwarding is the bridge's own action, not a user request) but logged
        and counted for the operator.
        """
        if not self.config.media.outbound.auto_files:
            return []

        policy = PathPolicy(self.config.media.outbound.patterns)
        allowed: list[str] = []

        for raw in self._media_paths:
            real = resolve_under(raw, self.working_dir)
            if policy.allowed(real, working_dir=self.working_dir):
                allowed.append(str(real))
            else:
                record_blocked(str(real))

        return files_from_paths(
            allowed, base_dir=self.working_dir, max_bytes=self.config.media.max_bytes
        )

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
    async def _on_activity(self, data: EmptyData) -> None:
        """A step or message part started: the agent is actively working."""
        self.controller.mark_working()

    async def _on_text_delta(self, data: TextData) -> None:
        self.controller.push_text(data.delta)

    async def _on_text_ended(self, data: TextData) -> None:
        if data.text is not None:
            self.controller.text = data.text

    async def _on_reasoning_delta(self, data: TextData) -> None:
        if self.config.streaming.show_reasoning:
            self.controller.push_reasoning(data.delta)

    async def _on_reasoning_ended(self, data: TextData) -> None:
        if self.config.streaming.show_reasoning and data.text:
            self.controller.reasoning = data.text

    async def _on_tool_called(self, data: ToolCalledData) -> None:
        if data.name and self.config.streaming.show_tools:
            self.controller.note_tool(data.name)

    async def _on_tool_progress(self, data: ToolData) -> None:
        self._collect_media(data)

    async def _on_tool_success(self, data: ToolData) -> None:
        self._collect_media(data)
        if self.config.streaming.show_tools:
            self.controller.clear_tool()

    def _collect_media(self, data: ToolData) -> None:
        """Collect media a tool produced.

        Inline file parts are snapshotted now; files named on disk are only
        *recorded* and read at drain time, so a file edited several times in one
        turn is sent once, with its final content.
        """
        for part in data.content:
            if not isinstance(part, FilePart):
                continue
            media = file_part_to_media(part)
            key = media.name or media.url or ""
            if key and key in self._media_seen:
                continue

            if key:
                self._media_seen.add(key)

            self.media.append(media)

        for path in data.structured.files:
            self._media_paths[path] = None

    async def _on_tool_failed(self, data: ErrorData) -> None:
        message = data.error
        if any(hint in message.lower() for hint in _DENIED_HINTS):
            if not self._denied_notice_sent:
                self._denied_notice_sent = True
                await self._send_notice("🔒 当前策略不允许该操作。")
            return

        self.controller.push_text(f"\n\n⚠️ A tool failed: {message}\n")

    async def _on_step_ended(self, data: StepEndedData) -> None:
        self._record_usage(data)
        for path in data.files:
            self._media_paths[path] = None

    async def _on_step_failed(self, data: ErrorData) -> None:
        self.controller.push_text(f"\n\n⚠️ {data.error or 'The step failed.'}\n")

    async def _on_attachment_omitted(self, data: AttachmentOmittedData) -> None:
        note = _OMIT_REASONS.get(data.reason, f"not accepted ({data.reason})")
        suffix = f" — {data.detail}" if data.detail else ""
        await self._send_notice(
            f"⚠️ `{data.name}` was not sent to the model: {note}{suffix}."
        )

    async def _on_compaction_started(self, data: EmptyData) -> None:
        await self._send_notice("🧹 Organizing context…")

    async def _on_compaction_ended(self, data: EmptyData) -> None:
        # A summary can drop the identity preamble, so refresh it next turn.
        self.route.context_dirty = True

    async def _on_status(self, data: TurnStatusData) -> None:
        status = data.status
        if status.type == "idle":
            await self.finish()
        elif status.type == "busy":
            self.controller.mark_working()
        elif status.type == "retry":
            attempt = status.attempt or status.next or 1
            await self._send_notice(f"⏳ Model busy, retrying (#{attempt})…")

    async def _on_permission(self, data: PermissionAskedData) -> None:
        perm = data.request
        metrics.inc("hitl_asks")
        action = self.config.permissions.action_for(perm.action)
        log.info("permission_asked", action=perm.action, auto=action)

        if action in ("once", "always", "reject"):
            await self._reply_permission(perm, action)
            return

        self._register_pending("permission", perm.id)
        card = hitl.permission_card(perm)

        if self.connector.capabilities.buttons:
            try:
                await self._send_card(card)
                await self._start_new_message()
                return
            except Exception:  # noqa: BLE001 - fall back to a numbered text prompt
                log.warning("permission_card_send_failed", exc_info=True)

        options = [button.text for button in card.buttons]
        self.route.pending_interactions[perm.id].options = options
        await self._send_notice(_numbered_text(card.body, options))
        await self._start_new_message()

    async def _on_question(self, data: QuestionAskedData) -> None:
        question = data.request
        metrics.inc("hitl_asks")
        first = question.questions[0] if question.questions else None
        log.info(
            "question_asked",
            questions=len(question.questions),
            options=len(first.options) if first else 0,
            multiple=bool(first and first.multiple),
        )

        text, options = hitl.question_numbered_text(question)
        self._register_pending("question", question.id, options=options)

        card = hitl.question_card(question)
        if card is not None and self._question_card_renderable(card):
            try:
                await self._send_card(card)
                await self._start_new_message()
                return
            except Exception:  # noqa: BLE001 - fall back to a numbered text prompt
                log.warning("question_card_send_failed", exc_info=True)

        await self._send_notice(text)
        await self._start_new_message()

    def _question_card_renderable(self, card: Card) -> bool:
        """Whether the channel can render this question as a card.

        A multi-choice question needs the channel to render checkboxes; a channel
        that cannot falls back to the numbered text prompt.
        """
        caps = self.connector.capabilities
        if not caps.buttons:
            return False
        return not card.questions or caps.question_form

    async def _send_card(self, card: Card) -> None:
        """Send an interaction card, attached to the active stream when possible.

        On streaming channels the card shares the answer's message, so the reply
        and the card are not reordered as two separate messages.
        """
        ref = await self.connector.send_card(
            self.conv,
            card,
            stream_id=self._sent_ref.id if self._sent_ref else None,
            text=self.controller.snapshot(),
        )

        if self._sent_ref is None and ref.id and self._can_stream:
            self._sent_ref = ref

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
        self._schedule_timeout(kind, request_id)

    def drop_pending(self, request_id: str) -> None:
        """Forget one pending interaction and cancel its timeout timer."""
        self.route.pending_interactions.pop(request_id, None)
        task = self._timers.pop(request_id, None)
        if task is not None:
            task.cancel()

    def _schedule_timeout(self, kind: Literal["permission", "question"], request_id: str) -> None:
        """Never let an unanswered interaction park the turn forever.

        After ``permissions.timeout_s`` the bridge gives up by policy (``fallback``)
        and tells the user, so queued messages are served instead of stalling.
        """
        timeout_s = self.config.permissions.timeout_s
        if timeout_s <= 0 or request_id in self._timers:
            return

        self._timers[request_id] = asyncio.create_task(self._expire(kind, request_id, timeout_s))

    async def _expire(
        self, kind: Literal["permission", "question"], request_id: str, timeout_s: int
    ) -> None:
        try:
            await asyncio.sleep(timeout_s)
        except asyncio.CancelledError:
            return

        self._timers.pop(request_id, None)
        if self.route.pending_interactions.pop(request_id, None) is None:
            return

        metrics.inc("hitl_timeouts")
        if kind == "permission":
            fallback = self.config.permissions.fallback

            try:
                await self.client.reply_permission(
                    self.route.session_id, request_id, reply=fallback
                )
            except AgentError as exc:
                log.warning("permission_timeout_reply_failed", error=exc.code)

            await self._send_notice(
                f"⌛ 等待授权超时（{timeout_s}s），已按策略"
                f"{'放行' if fallback == 'allow' else '拒绝'}。"
            )
        else:
            try:
                await self.client.reply_question(self.route.session_id, request_id, [[]])
            except AgentError as exc:
                log.warning("question_timeout_reply_failed", error=exc.code)
            await self._send_notice(f"⌛ 等待回答超时（{timeout_s}s），已自动跳过。")

    def _cancel_timers(self) -> None:
        for task in self._timers.values():
            task.cancel()
        self._timers.clear()

    async def _on_interaction_closed(
        self, data: PermissionRepliedData | QuestionClosedData
    ) -> None:
        request_id = data.request_id
        self.route.pending_interactions.pop(request_id, None)

        task = self._timers.pop(request_id, None)
        if task is not None:
            task.cancel()

    async def _start_new_message(self) -> None:
        """Continue in a new message after a user is asked to choose.

        The streamed message was opened before the user's reply, so continuing
        there would show the agent's answer above that reply. Seal whatever has
        accumulated into the current message, then open a fresh one for the rest.
        Only channels whose interaction cards are separate messages need this;
        where the card shares the streamed message (e.g. WeCom) the answer simply
        continues in place.
        """
        if not self._can_stream or self.connector.capabilities.card_in_stream:
            return

        text = self.controller.text
        if self._sent_ref is not None and text.strip():
            try:
                await self.connector.update(
                    self._sent_ref, OutboundPlan(segments=[TextSegment(text=text)], final=True)
                )
            except Exception:  # noqa: BLE001 - sealing is best-effort
                log.warning("segment_seal_failed", exc_info=True)

        self._sent_ref = None
        self.controller.begin_segment()

    async def _emit(self, final: bool, snapshot: str) -> None:
        if not final and await self._maybe_placeholder(snapshot):
            return

        plan = self._render(final)
        if final and not any(isinstance(segment, TextSegment) for segment in plan.segments):
            # Never leave the "Thinking…" placeholder hanging: a final frame with
            # no text still replaces it (with the last progress, or a check mark).
            plan.segments.insert(0, TextSegment(text=self.controller.snapshot().strip() or "✅"))

        if self._sent_ref is None:
            self._sent_ref = await self.connector.send(self.conv, plan)
        else:
            await self._update_or_send(plan)

    async def _maybe_placeholder(self, snapshot: str) -> bool:
        """Open a message for interim frames when the text is still empty.

        On streaming channels the placeholder becomes the message later updates
        replace; on non-streaming channels it is simply the initial frame.
        """
        if not self._can_stream:
            if not self._placeholder_sent and self.connector.capabilities.progress_placeholder:
                await self._send_notice("🤔 Thinking…")
                self._placeholder_sent = True
            return True

        if not snapshot.strip() and self._sent_ref is None:
            # Nothing to stream yet: open with a placeholder only if the channel
            # wants one, else wait for the first real content.
            if self.connector.capabilities.progress_placeholder:
                self._sent_ref = await self.connector.send(
                    self.conv,
                    OutboundPlan(segments=[TextSegment(text="🤔 Thinking…")], final=False),
                )
                self._placeholder_sent = True

            return True

        return False

    def _render(self, final: bool) -> OutboundPlan:
        markdown = self.controller.text
        if not final:
            status = self.controller.live_status()
            if status:
                markdown = f"{markdown}\n\n{status}" if markdown else status

        doc = RichDoc(
            markdown=markdown,
            reasoning=self.controller.reasoning if self.config.streaming.show_reasoning else None,
            usage=self.usage if final and self.config.streaming.show_usage else None,
        )
        plan = self.renderer.render(doc, self.connector.capabilities)
        plan.final = final

        if self.conv.is_group and self.config.group.reply_with_mention:
            plan.reply_to = self.inbound.message_id

        return plan

    async def _update_or_send(self, plan: OutboundPlan) -> None:
        """Replace the streamed text and emit any non-text segments separately."""
        text_segments: list[Segment] = [s for s in plan.segments if isinstance(s, TextSegment)]
        other_segments: list[Segment] = [s for s in plan.segments if not isinstance(s, TextSegment)]
        if text_segments:
            await self._replace_text(
                OutboundPlan(segments=text_segments, reply_to=plan.reply_to, final=plan.final)
            )

        for segment in other_segments:
            await self.connector.send(self.conv, OutboundPlan(segments=[segment], final=True))

    async def _replace_text(self, plan: OutboundPlan) -> None:
        assert self._sent_ref is not None

        try:
            await self.connector.update(self._sent_ref, plan)
        except RateLimited:
            raise
        except Exception:  # noqa: BLE001 - any update failure: send a fresh message
            log.warning("stream_update_failed", exc_info=True)
            self._sent_ref = await self.connector.send(self.conv, plan)

    async def _send_notice(self, text: str) -> None:
        await self.connector.send(
            self.conv, OutboundPlan(segments=[TextSegment(text=text)], final=True)
        )

    # -- usage -------------------------------------------------------------
    def _record_usage(self, data: StepEndedData) -> None:
        if data.tokens is not None:
            self._record_tokens(data.tokens)

        if data.cost is not None:
            self.usage.cost = data.cost

    def _record_tokens(self, tokens: dict[str, Any]) -> None:
        # agentd forwards the provider's usage verbatim, so interpret the
        # provider-specific format here; fall back to agentd's normalized fields.
        parsed = parse_usage(tokens.get("providerMetadata")) or UsageTokens.from_normalized(tokens)
        self.usage.input_tokens = (self.usage.input_tokens or 0) + parsed.new_input
        self.usage.output_tokens = (self.usage.output_tokens or 0) + parsed.visible_output
        self.usage.reasoning_tokens = (self.usage.reasoning_tokens or 0) + parsed.reasoning
        self.usage.cached_tokens = (
            (self.usage.cached_tokens or 0) + parsed.cache_read + parsed.cache_write
        )

        if parsed.full_input:
            self.usage.context_tokens = parsed.full_input


def _numbered_text(body: str, options: list[str]) -> str:
    lines = [body, ""]
    lines.extend(f"{index + 1}. {text}" for index, text in enumerate(options))

    return "\n".join(lines)


__all__ = ["TurnEngine"]

# Tether — go-agent-sdk IM bridge service design

> Project name: **Tether** (independent repository; Python 3.12+ / uv). This document is its design doc.
> Status: **implemented** (the bridge lives in `src/tether/`, Python 3.12+/uv); this document is its design reference.
> Scope: an independent Python service that bridges the bots of IM platforms such as WeCom / Feishu / QQ / WeChat with
> the **HTTP/SSE (and A2A) API** of `go-agent-sdk` (`cmd/agentd`, see `docs/DESIGN-HTTP.md`),
> letting users converse with the Agent in IM conversations (direct chat / group chat).
> Relationship: this document is the downstream consumer design for `docs/DESIGN.md` / `docs/DESIGN-HTTP.md`. The Go-side contract is defined by
> `docs/DESIGN-HTTP.md` and `pkg/server/*`; this document does not modify it; it only describes how the Python side consumes it.
> Convention: the Python code in this document is **illustrative**, expressing type boundaries and contracts, and is not the final signature.

## Table of Contents

- 1. Motivation and Goals
- 2. Terms and Overall Architecture (2.5 Direct chat/Group chat · 2.6 Identity sync · 2.7 Mapping quick reference · 2.8 Project isolation · 2.9 Isolation implementation · 2.9.1 Product comparison [reference] · 2.9.2 Sandbox vs isolation)
- 3. Core abstractions (3.1 Connector · 3.2 Message model · 3.3 Capabilities · 3.4 AgentClient · 3.5 Renderer · 3.6 Router · 3.7 ProjectProvider)
- 4. Agent-side integration (4.1 Endpoints · 4.3 SSE · 4.4/4.5 Media · 4.6 HITL · 4.8 Identity injection)
- 5. IM-side adaptation · 6. User experience design · 7. Files and media · 8. Reliability and concurrency
- 9. Configuration · 10. Security · 11. Observability · 12. Project structure and uv project · 13. Testing strategy
- 14. MVP scope and roadmap · 15. Decision list
- 16. Appendix SSE event mapping · 17. Appendix Sandbox/isolation responsibility boundary and the two designs · 18. Appendix Core type glossary · 19. Appendix SDK dependencies and prerequisites

## Change log

| Date | Change |
|---|---|
| 2026-10-10 | First version: motivation, overall architecture, extensible connector abstraction, Agent client, unified message model, rendering and streaming (UX focus), media send/receive (file focus), HITL, reliability, configuration, security, uv project, MVP/roadmap, decision list, event mapping appendix |
| 2026-10-10 | Made the two conversation forms "direct chat / multi-user group chat" explicit first-class citizens: trigger strategy, conversation granularity, speaker identity injection, cross-user concurrency and ownership, in-group HITL/command authorization (added §2.5, updated §3.6 / §4.2 / §4.6 / §6.8 / §8.1 / §9 / §15, decisions D16–D18) |
| 2026-10-10 | Added **bot identity sync** (injecting the bot's display name / @ mention in the group into the agent context) and the **mapping invariant** (each IM group = one agent session) (added §2.6, §4.8, updated §3.1 / §3.2 / §3.6 / §9 / §14 / §15, decisions D19–D20) |
| 2026-10-10 | Extended identity sync to **name + description/persona**, and added an **alignment strategy** with the agent's own `description` (`identity.source: im/agent/config`), making the bot's external identity consistent with the agent's self-perception (updated §2.6 / §3.2 / §3.6 / §4.2 / §4.8 / §9 / §15, decision D19) |
| 2026-10-10 | Added **project isolation strategy**: when one bot serves multiple groups, **read-only agents may share a project, while writable agents must isolate projects per group**; read/write capability is determined by the real tool set (`GET /api/tool?agent=`) (added §2.8, updated §3.4 / §3.6 / §9 / §14 / §15, decision D21) |
| 2026-10-10 | Expanded **isolation implementation methods**: sharing / git worktree / containers / copy·CoW·namespaces·remote, etc., and introduced the `ProjectProvider` abstraction (added §2.9, §3.7, updated §9 / §14 / §15, decision D22) |
| 2026-10-10 | Added §2.9.1: comparison with the sandbox implementations of Claude Code / Codex CLI / opencode / CodeBuddy (kernel primitives + network + language/broker layer) and their mapping to the bridge's isolation strategy |
| 2026-10-10 | Added §17 appendix: sandbox responsibility boundary with the upstream SDK (discussion draft) — policy/abstraction goes in the SDK, OS enforcement goes in the host/deployment, the heaviest isolation goes out-of-process (pending upstream confirmation) |
| 2026-10-10 | Added §2.9.2 "Sandbox vs project isolation: orthogonal and convergence" — the two are not interchangeable, converging to "one sandbox instance per group" |
| 2026-10-10 | §2.9(4) detailed low-cost isolation: prefer kernel-level CoW (overlayfs/reflink/clonefile/subvolume snapshots), documented the **write-through** and tool semantics pitfalls of symbolic/hardlink farms; added the `overlay` provider and `projects.cow` configuration (§3.7 / §9) |
| 2026-10-10 | Added §2.9.3 "How isolation is shared between agentserve / a2aserve": transport-agnostic `cmd/` project runner (extending `serveconfig`), single owner for writable projects, `ProjectLease.transport`; §17 expanded to "Sandbox and isolation responsibility boundary" (decision D23) |
| 2026-10-10 | Added §17 appendix: writing the two designs separately and clearly — the `Sandbox` hook (SDK, single-process execution boundary) and the Project runner (`cmd/`, project/process isolation), including a comparison table and the red line "isolation must not be made into an SDK hook" |
| 2026-10-10 | Named the project **Tether** (independent repository, Python 3.12+ / uv): unified the title, preface, architecture diagram, package/CLI/dist names (`tether`), project structure and example paths |
| 2026-10-10 | Revised per review: clarified **deny vs HITL** (§9.2 two stances), spool lands inside the working directory (§4.4/§7.5/§10.4), supervisor belongs to the host side (§2.9/§3.7/§8.5/§2.9.3), group mapping changed to "default mapping" (§2.5/§2.7), `Route.scope`/`queue_depth` semantics, removed `last_seq`; completed §9 configuration keys, §4.1/§3.4 endpoints, TOC, type glossary (§19) |
| 2026-10-10 | Second review revision: `server.token_env`, `idle_progress_ms`, `Sandbox` hook reference redirected to §17.2, `identity()` comment includes description, media wording ("reject and give a link"), QQ `channel` isomorphic to `group`, `worktree` provider wording; `Project` term added to the table |
| 2026-10-10 | §2.4 clarified media sources: `inline` (small) / `url` (public network) / `file` (**large media**, requires `MediaUploader`) pick one of three + spool fallback; `MediaUploader` is the "large-media transfer channel", not a precondition for modality support |
| 2026-10-10 | Clarified the platform **delivery model**: `Capabilities` adds `direct_delivery`/`group_delivery` (always/mention_only/on_session/unknown); §2.5 explains that `respond_on` can only **narrow**, not widen; §3.3 capability table adds a delivery column, unconfirmed items marked **pending integration testing**; §5 adds delivery semantics for each platform; added **§13.1 capability integration-testing checklist** (to be backfilled after on-device verification) |
| 2026-10-10 | **Removed `respond_on` (trigger strategy) and `scope.group` (conversation granularity)**: changed to "**platform delivers, i.e. forward** (no secondary filtering), **one IM conversation = one agent session** (key includes thread)"; commands are still intercepted locally by the bridge. Synced §2.5/§2.7/§3.3/§3.6/§4.2/§6.6/§6.8/§8.1/§9/§13 and decisions D5/D16/D17 (`direct_delivery`/`group_delivery` retained as **facts**, used only for documentation/integration testing) |
| 2026-10-10 | Clarified **in-group authorization data**: `Capabilities` adds `callback_actor_identity` (whether callbacks carry the clicker's identity) and `member_roles` (whether the platform exposes group roles); §2.5(3) explains that `initiator`/`participants` are implementable, and `admins` falls back to the configured `group.admins` (platforms mostly don't provide roles); §3.3 adds an authorization data table; §9 adds `group.admins`; §13.1 adds integration-testing item 9 |
| 2026-10-10 | Streamlined the command layer: **keep only `/stop`** (cancel the current turn); removed `/new` `/reset` `/compact` `/agent` `/model` `/status` `/help` (in IM "one conversation = one session", context is managed by automatic compaction, and switching agent/model is an operational concern). Synced §1.3/§2.3/§2.5(3)/§4.2/§6.6/§6.8/§9/§12/§13/§14 and D18 |
| 2026-10-10 | Detailed **streaming throttling** (§6.2): trailing-edge + drop-if-busy + boundary/trailing flush + adaptive backoff + single snapshot, including pseudocode; added **§6.7 Runtime status and usage display** (reasoning collapse, usage line, channel feasibility/degradation); configuration adds `boundary_flush`/`max_live_chars`/`rate_limit_backoff`/`reasoning_style`/`show_usage` |
| 2026-10-10 | **Merged** §2.9.3 "cross-transport shared isolation" **into §17.3** (its content duplicated the responsibility-boundary appendix, and placing it under "isolation mechanism" was semantically misaligned): §2.9 leaves only a one-line pointer at the end; corrected all references to §2.9.3 throughout to §17.3 |
| 2026-10-10 | §4.4 clarified the **three "transfers/fetches"** (① IM download `download` / ② Provider upload `POST …/file` / ③ IM upload `upload`) and added a "fetch bytes" step; added **§7.7 per-IM download/upload capabilities** table (including pending integration-testing items) |
| 2026-10-10 | §4.6 opening added "what an IM card is / why use it" + permission-card/question-card examples + click-loop closure and two uses (interactive/updatable) |
| 2026-10-10 | Review §1: §1.1 "three things" → "four things" (+ conversation mapping/HITL); §1.3 added supporting-design guidance; §1.4 rewrote the "multi-tenant SaaS" wording, simplified non-goals, added "no multi-agent orchestration/routing"; §2.1 added the `Tenant` term |
| 2026-10-10 | Review §2: fixed residual `/agent` command references (§2.6/§2.8 → operations via `POST …/agent`); unified "multi-tenant/SaaS" to "multi-source/strong isolation" (§2.9, decision tree, §3.2 `tenant` comment); configuration key prefixes (`group.cross_user_delivery` / `sessions.idle_reset_s`); §2.2 architecture diagram redrawn for alignment; §2.1/§2.3/§2.5/§2.7 details |
| 2026-10-10 | Review §3: added the **inbound interaction/event channel** — added `IncomingItem`/`IncomingInteraction`/`ConnectorEvent`, changed `IMConnector.start(emit)` to accept a union (previously HITL card clicks/welcome messages had no path); `RichDoc` adds `reasoning`/`usage` (+`Usage` type); `AgentClient.prompt` parameter `msg_id`→`id`; §3.2 added a §19 glossary pointer and a note on `Attachment.kind`; §3.7 `ProjectSpec`/`IsolationSpec` noted as §17.3 types |
| 2026-10-10 | Review §4: §4.1 added `GET /api/tool?agent=` (read-only determination) and per-session `GET …/permission\|question`; §4.3 clarified reconnection (only per-session `?after=` offers replay, this design uses global + reconciliation); §4.6 unified button `value` encoding as `{kind,sid,rid,…}`, `"Stop"`→`/stop` |
| 2026-10-10 | Review §5: each platform added **inbound event → §3.2 mapping** (WeCom `template_card_event→IncomingInteraction`, `enter_chat/feedback→ConnectorEvent`; Feishu `card.action.trigger→IncomingInteraction`; QQ keyboard; WeChat personal has no cards→text fallback); §5.1 added `body.voice.aeskey`; §5 opening added an overview of "facts → Capabilities/identity" |
| 2026-10-10 | Review §6: corrected the `contextLimit` source (`/api/model` doesn't include this field → changed to configuration, and noted the SDK alignment item); §6.3 added `RichDoc`'s `reasoning`/`usage`; §6.2/§6.5 pointed out the relationship between `max_live_chars` (snapshot) and `max_text_chars` (message); §6.7 wording, §6.1 line labels |
| 2026-10-10 | Review §7: §7.1 capability intersection added `Connector.media_in` (bidirectional inbound); §7.2 added `url` source; §7.5 clarified that the TTL starts at creation and is readable within the current session, and added optional content-hash upload dedup |
| 2026-10-10 | Review §8: dedup key changed to `Conversation.key + message_id` (§8.2); reconciliation added a "finish half-done messages" step (§8.3); backpressure linked to §6.2 (§8.4); "persist Route" → "flush unwritten state" (§8.5) |
| 2026-10-10 | Review §9–§12: D10 idempotency key changed to `Conversation.key:message_id`; §10.1 "group chat triggers only on @" changed to the platform-delivery framing; §9.1 completed enums / §2.8 fail-fast / `agent.writable` validation; D2 added `RichDoc`'s reasoning/usage; D17 wording |
| 2026-10-10 | Review §13: expanded the test checklist (inbound interaction, identity injection/anti-spoofing, in-group authorization, reconciliation finish-up, idempotency key, streaming backoff, reasoning/usage, configuration validation, timing/concurrency); §13.1 inbound media per actual platform types |
| 2026-10-10 | Review §14: M0 added inbound items and the `/stop`/identity-preamble skeleton; M2 added the `url` source and §6.7 display; each platform's M added a "§13.1 integration-testing backfill" exit; M6 mentions that isolation instances can be wrapped in a sandbox |
| 2026-10-10 | Added **§20 appendix "SDK dependencies and prerequisites"** (ready / to be added / non-blocking proposals + M0 prerequisite actions); §19 glossary added `IncomingItem`/`IncomingInteraction`/`ConnectorEvent`/`Usage` |
| 2026-10-10 | Review §15: merged the duplicate D20 into D5 (mapping invariant, including "no `per_user`/`shared_by_thread`"); the former D21–D23 shifted to D20–D22; the former D23 noted the `Sandbox` hook as a **recommendation, pending upstream confirmation** |
| 2026-10-10 | Review §16: added `reasoning.started` / `compaction.delta` / `session.status.retry.next`; added a catch-all row for "other `session.next.*`" |
| 2026-10-10 | Merged appendices: §17 (responsibility boundary) and §18 (the two designs) combined into **§17 "Sandbox/isolation responsibility boundary and the two designs"** (17.1 stance / 17.2 `Sandbox` hook / 17.3 Project runner / 17.4 comparison); former §19 glossary → §18, former §20 SDK dependencies → §19; synced and updated references throughout |
| 2026-10-10 | §17 removed the title "（discussion draft）": clarified that 17.1 is a **finalized stance** and the 17.2/17.3 interfaces are **finalized**, with the only pending item being "whether upstream adopts them"; the two proposal subsections relabeled "Proposal · pending upstream adoption" |
| 2026-10-10 | §17 added a comparison table "17.2 and 17.3 **are not either-or**" (different layers, orthogonal, stackable), using "which room / how tight the limbs" to clarify what each proposal governs (in-process vs process·project level) |
| 2026-10-10 | §17.2/§17.3 rewritten into the three-part form "**problem to solve / how to do it / what not to do**": added concrete scenarios (injection-induced `bash` lacking an OS-enforced seam; multiple groups sharing one working directory polluting each other) and implementation mechanisms (`bash` goes through `Sandbox.Run`; the transport-agnostic `Runner` in `cmd/serveconfig`) |
| 2026-10-10 | §17.2 corrected based on facts: the SDK **already has** a `core.AppProcess` seam (shared by `bash`/`ripgrep`/`git`), but `pkg/agent` hardcodes it and `ClientOptions` cannot override it; the proposal changed to "promote `AppProcess` to `ClientOptions` (a `Process` field)" rather than inventing a new interface; the `Sandbox` hook is retained as an alias |
| 2026-10-10 | §17.2 added "what a sandbox is": added 4 restriction dimensions (filesystem view/network/permissions/resources) + notes on `bwrap`/`seatbelt`/`cgroup` and a `bwrap` example command, avoiding a mere list of nouns |
| 2026-10-10 | §17.2 added the **Windows** sandbox (AppContainer + restricted token/low IL + Job Object + WFP; VM-level uses Windows Sandbox/Hyper-V containers), changed the dimension table to list three platforms side by side; and noted that Windows is the most fragmented and that putting the whole process in a container is often easier |
| 2026-10-10 | §17.2/§17.3 removed "Proposal · pending upstream adoption" and instead labeled by **implementation layer**: 17.2 = go-agent-sdk **SDK layer** (`pkg/`), 17.3 = **command layer** (`cmd/`, not the SDK); synced §17 title/intro, 17.1 "impact on the bridge", D22, and the §19 dependency table, changing "upstream" wording to "SDK/command layer" |
| 2026-10-10 | Full review revision: #1 `Route.pending_interaction` (single value) → **ordered map** `pending_interactions` (permissions can be concurrent and can coexist with question; added `PendingInteraction`, §3.6/§4.6/§18); #2 added configuration `model.context_limit` (§9, §6.7, §19); #3 §3.6 `routes` added a unique index on `session_id`; #4 `/stop` within a group defaults uniformly to `command_scope: initiator` (configurable `admins`) (§2.5/§6.6/§6.8/D18); #5 §17.1 removed the "needs prior discussion and confirmation" wording; #6 §3.4 discovery/interaction DTOs named; #7 §4.1 labeled operations/not-yet-used endpoints; #8 §2.7 labeled "quick reference" and added to the TOC; #9 `permissions.auto` added `apply_patch`; #10–#12 naming/comment nits (`connector.update`, `prompt` parameter, `max_cards`) |
| 2026-10-10 | Second full review: #1 added `PendingInteraction.scope` (initiator/participants/admins) and synced §4.6 authorization rules; disambiguated `model.context_limit` (bridge, display only) vs agentserve compaction `ContextLimit` (host) (§2.5(4)); §6.7 punctuation fixes; §19 M0 prerequisite "`contextLimit` source" marked as settled |
| 2026-10-10 | Wrap-up minor items: `model.context_limit` noted to take the conservative value for a single value (§9); `ProjectLease.transport` noted that Tether is always http (§3.7); added configuration `dedup.ttl_s` (§9) and referenced it in §8.2 |
| 2026-10-10 | §1.2 added "why use HTTP/SSE instead of A2A": abstraction-layer comparison + six trade-offs (live-only events / queue·steer / global multiplexing / host control plane / trust model / idempotency·reconciliation) + counterexamples where A2A is right + the two are not mutually exclusive |
| 2026-10-10 | §17.5 added "Command-layer convergence (refactoring goal, prioritized after finalization)": merging `cmd/agentserve`+`cmd/a2aserve`, one `Client` per transport, `buildClient` drift as the rationale |
| 2026-10-11 | Added `docs/DESIGN-AGENTD.md` (English): the complete design for merging `cmd/agentserve`+`cmd/a2aserve` into the multi-transport command **`agentd`** (one process/one config/N listeners, one `Client` per transport); §17.5 converged to a **pointer** |
| 2026-10-11 | Title/terminology consistency pass: title line → sentence case; `Status:` unified to `draft (design only, not implemented)` (incl. `DESIGN-AGENTD.md`); `Project runner` → `project runner` (prose); `isolation view` → `isolated view`; `to be integration-tested` → `pending integration testing`; `## Change Log` → `## Change log` |
| 2026-10-11 | §17.5 clarified: the `buildClient` drift is only the `ClientOptions` **config plumbing** (MCP/references/auto-title/`SubagentDepth` limit) — agents/subagents/skills still load from `configDirs` in both commands; not an A2A limitation. |
| 2026-10-11 | §17.5 pointer updated to name the agentd config list **`servers[]`** (each entry = one `Client` + adapter; may share a `listen`). |
| 2026-10-12 | §8.3 session recovery: the IM↔session mapping is persisted by the bridge keyed by `Conversation.key` (agentd knows only session ids); added `sessions.validate_session` (verify a loaded route's session on first use, recreate if gone) plus reactive recovery on `prompt not_found`; config §9 updated |
| 2026-10-12 | §8.5 shutdown: default is now to **leave in-progress turns/parked interactions on agentd** (`sessions.interrupt_on_shutdown: false`) so a restart resumes them; `true` restores interrupt+reject. Stale card clicks (already answered/expired) are ignored; answering an interaction after a restart attaches a resumed turn engine. §9 updated |
| 2026-10-13 | §2.6/§5.1/§9 identity: the bot name/description come from the platform **only where the API exposes them** (Feishu `GET /open-apis/bot/v3/info` → `app_name` + application `description`; QQ `botpy` `robot.name`; personal WeChat nickname). **WeCom provides neither** — its callback carries only `aibotid` (confirmed against the official callback schema and captured frames) — so `identity.display_name`/`description` are **required** for WeCom and **optional overrides** elsewhere (configured wins, else the platform's). Inferring the name from an inline `@name` in message text was rejected as fragile. |
| 2026-10-13 | Added **§8.6 Message Recall** and decision **D23**: recall is best-effort and platform-dependent — where a platform emits a recall event (Feishu `im.message.recalled_v1`) the Connector maps it to `ConnectorEvent(kind="recall")` and the core drops a queued turn / interrupts an in-flight one (never unsends an already-sent reply); a platform without the event (WeCom long connection) is a no-op. §3.2 `ConnectorEvent.kind` gained `recall`; §14 M7 lists it. |

---

## 1. Motivation and Goals

### 1.1 Motivation

The starting point of `docs/DESIGN-HTTP.md` is precisely this document: Go cannot be directly imported by Python/Node, and the bot SDKs of the major IM platforms
only provide Python/Node implementations, with no Go version. Therefore the correct seam is **HTTP/SSE**:

```
WeCom / Feishu / QQ / WeChat platforms
        │  (platform -> connector)
        ▼
   Tether (Python)   ──HTTP/SSE──►  cmd/agentd (go-agent-sdk agent loop)
        ▲                                   │
        └──────────── outbound message / media ◄──────┘
```

The bridge service itself **does not implement the agent loop**, nor does it copy the SDK's session/tool/permission logic; it does only four things:

1. **Protocol translation**: IM platform messages ⇄ go-agent-sdk's prompt/event/attachment.
2. **Conversation mapping**: map an IM conversation to an Agent Session (**one IM conversation = one session**), and close the loop on permissions/questions
   (HITL).
3. **Experience polishing**: render the model's streaming Markdown output into a form each IM platform can display gracefully.
4. **Media transport**: transport images, audio, video, files, etc. in both directions, and degrade gracefully for unsupported forms.

> Session lifecycle/context (compaction) is managed by the SDK; cross-session **project isolation and orchestration** belong to the host side (§2.8/§2.9).

### 1.2 Relationship with A2A and the HTTP server

- This document **is not A2A**: A2A (`docs/DESIGN-A2A.md`) is "agent calling agent"; this document is "IM user ↔ a
  hosted agent".
- This document is the **trusted host** of `cmd/agentd`: the bridge service calls it with a Bearer token,
  while the IM end users are **untrusted**. Therefore agentd must run with **restricted** `inboundPermissions`
  (dangerous tools `ask` or `deny`, see §9.2), and dangerous permission requests are exposed to IM users through HITL (human-in-the-loop confirmation)
  (see §4.6, §10).
- The bridge service **only integrates IM Python SDKs** (a user requirement); the Agent loop is always on the Go side.

**Why use HTTP/SSE instead of A2A**

The two are different abstraction layers: the HTTP API is the control plane for "**a trusted host driving its own SDK instance**"; A2A is the interoperability protocol for "peer, mutually opaque
agents calling each other" (`DESIGN-A2A.md` §0.1, whose design goal is to **hide internal state/tools**). Tether
is the former — it wants to render the agent's **real-time behavior** into IM, which requires exactly the SDK's internal events.

| What would be lost if A2A were used | Notes |
|---|---|
| **live-only events** | `text.delta`/`session.status`/`permission\|question.v2.asked` are only in the live stream, and are the core of streaming (§6.2) and HITL (§4.6); A2A gives Task status/Artifact increments, `input-required` is coarse-grained, and the mapping is lossy |
| **queue / steer** | `prompt {id, delivery}` + `202 queued` (per-session worker) has no A2A equivalent |
| **global multiplexing** | Tether is one process with many sessions, using **a single** `/api/event` routed by `sessionID` (§4.3); A2A is per-task, with no cross-session global stream |
| **host control plane** | `/api/agent`, `/api/model`, `/api/tool?agent=` (§2.8 read/write determination), `interrupt/compact/wait/active`; A2A's `AgentCard.skills` are **descriptive labels** handwritten by operations, not a tool inventory |
| **trust model** | HTTP: "caller+transport trusted, end user untrusted" (`DESIGN-HTTP.md` §1.2); A2A targets cross-vendor scenarios, with AgentCard/task store/push/securitySchemes, which is overhead for a single trusted host, and its "opaque" goal runs counter to Tether |
| **idempotency / reconciliation** | `id` idempotent admission, `/history`, `/message`, `/active` (§8.3); A2A's `GetTask/ListTasks` key is **task**, not this SDK's session/turn/event |

- **Counterexample (where A2A is right)**: if Tether wanted to **be called by other agents**, to drive any A2A agent **implementation-agnostically**, or to expose
  an agent as a **standard public service** — that would be another product (Tether is **a host for this SDK**, already defined in §8).
- **Not mutually exclusive**: the SDK's same core provides `cmd/agentd` (HTTP and A2A); the runner of §17.3 parameterizes
  `Transport`. The choice is just "**which face this consumer needs**".

### 1.3 Two design priorities (explicitly required by the user)

1. **Connect IM and the Agent (including bidirectional media)**: both **direct chat (1 user ↔ bot) and group chat (N users ↔ bot)** can be reliably
   mapped to an Agent session; text, images, audio, video, and files can all flow in both directions; permissions/questions (HITL) can be closed loop within IM.
   For the multi-user semantics of conversation forms, see §2.5.
2. **The best possible user experience**: streaming output, Markdown rendering with graceful degradation, tool progress visualization,
   long-text chunking, interactive cards, typing status, a cancel command (`/stop`), **runtime status/usage/reasoning display**, and human-readable error messages.

These two goals are elaborated in §6 (UX) and §7 (media), and it is not allowed to sacrifice "experience" for the sake of "connectivity", or vice versa.
There are also several requirement-driven **supporting designs**: bot identity sync (§2.6), project isolation (§2.8/§2.9).

### 1.4 Non-goals

- Does not implement the agent loop, tools, the permission engine, or model invocation (all on the Go side).
- Does not implement connection/authentication/encryption for each IM platform (left to each IM SDK).
- Does not do multi-agent orchestration/routing strategy: one bot corresponds to one agent; switching is an **operational** concern (deployment configuration), not switched in chat.
- Does not do schema-first / code generation (consistent with `DESIGN-HTTP.md` §11).
- The MVP does not include a Web admin console (listed as optional in §14 M7).
- **No multi-tenant SaaS** (no per-organization renting/billing); but a single instance serves multiple IMs and multiple groups — **isolation is needed between conversations and groups**
  (§2.8/§2.9).

---

## 2. Terminology and Overall Architecture

### 2.1 Terminology

| Term | Meaning |
|---|---|
| **Connector** | An adapter that integrates with one IM platform, encapsulating that platform SDK's connection, send/receive, media, and card capabilities. |
| **Conversation** | A message context in an IM, `kind ∈ {direct, group, channel}` (`channel` is treated the same as `group`) + `id` (direct/group/channel ID). |
| **Tenant** | A dimension marker for a deployment/source (`Conversation.tenant`, nullable). Tether **does not do SaaS tenancy**, but uses it to distinguish different sources under the same instance; for **isolation between conversations/groups**, see §2.8/§2.9 (§1.4). |
| **Agent Session** | go-agent-sdk's `session`, created by `POST /api/session`, with an `id` (`ses_…`). |
| **Turn** | The complete process of one prompt → model/tool execution → idle. |
| **Route** | The mapping of Conversation ↔ Agent Session, maintained and persisted by the `Router`. |
| **Project (project instance)** | One agentd instance = one `agent.Client` = one working directory; the unit of isolation (§2.8/§2.9). |
| **ProjectProvider / Lease** | The abstraction and lease for acquiring/returning a project instance (isolation) (§3.7). |
| **Capabilities** | The platform capabilities declared by a connector (degree of Markdown support, whether messages are editable, buttons, emoji, media types, message length limit, ...), which drive rendering and degradation. |
| **Renderer** | Renders the canonical payload (Markdown + media + interactions) into a given Connector's native outbound message. |
| **Inbound / Outbound** | Messages entering the Agent direction / leaving the Agent direction. |

### 2.2 Overall Architecture

```
  WeCom / Feishu / QQ / WeChat platform
        │  Platform SDK events
        ▼
  [Connector] ─► [Router] ─► [TurnEngine] ─► [AgentClient] ─HTTP/SSE─► cmd/agentd
    §3.1          §3.6          §4             §4.1                     (go-agent-sdk)
      ▲                                                                  │
      └── [Renderer] ◄── [StreamingController] ◄── event stream (global SSE) ◄────┘
           §3.5              §6.2
```

### 2.3 Data Flow

**Inbound (IM → Agent)**

```
Platform callback/SDK event
  → Connector normalization → InboundMessage{text, attachments, mentions, conversation, sender}
  → Router: does the conversation have an Agent Session? No → create /api/session
  → Command parsing (only `/stop`) → if matched, handle locally; otherwise:
  → MediaIngest: attachment download → choose transport (inline/file/url/spool) → files[]
  → AgentClient.prompt(sessionID, {prompt, id, delivery, files})
  → 202 {queued:true} (turn executes asynchronously)
```

**Outbound (Agent → IM)**

```
AgentClient's global SSE (/api/event)
  → Route by sessionID to TurnEngine (one aggregator per route)
  → Event classification: text.delta / reasoning / tool.* / status / permission / question / attachment.omitted
  → StreamingController throttles and aggregates → Renderer renders to OutboundPlan
  → Connector.send / update / send_media / send_card
  → turn ends (session.status=idle) → flush the final text, and send any media not yet sent
```

### 2.4 Deployment Form

- Process: a single bridge process can enable multiple Connectors at the same time; each Connector corresponds to one upstream platform connection.
- Relationship with agentd: the bridge service calls one (or more)
  agentd instances via `server.base_url` + `server.token`. **One agentd instance = one `agent.Client` = one project/working directory**.
- When the bridge needs "different IM/different groups use different agent projects", use `server.pool` (multiple base_urls),
  selected by the Router (§3.6).
- **Three media source options + spool fallback**: small media uses `inline` (data URL); media with a publicly reachable URL uses `url`; **large media
  (video/audio/large images) uses `file`**. The `file` source requires Go-side configuration of `MediaUploader` (`cmd/agentd`)
  to enable its upload endpoint `POST /api/session/{id}/file` (see `pkg/server/media.go`); if none of the three is suitable, then
  spool into the working directory and note the path in the prompt (§4.4).

### 2.5 Conversation Forms: Direct Chat and Multi-user Group Chat

Both forms are driven by **platform delivery**: which messages the platform pushes to the bot is decided by the platform (the `direct_delivery` /
`group_delivery` fact in §3.3), and **the bridge forwards a message to the agent as soon as it receives it, without a second trigger filter**; commands (only `/stop`) are intercepted locally by the bridge
(not forwarded). The mapping is uniformly **one IM conversation = one agent session** (the key includes topic/thread).

**Direct chat (direct) — 1 user ↔ bot**

```
User A ──direct chat──► bot
```
- No @ needed; the platform pushes A's messages to the bot, and the bridge forwards them.
- The context is just the conversation between A and the bot; there is no third-party speech, so there is no identity confusion.
- Direct chat can naturally `steer` (the user adds a sentence, injected into the current turn).

**Group chat (group) — N users + bot in the same conversation**

```
User A ┐
User B ┼─group─► bot (one group = one conversation context)
User C ┘
```

**One IM conversation (group) = one agent session**: the mapping key = `Conversation.key`
(channel+kind+tenant+id+thread). Multiple users share the same context, so group chat needs to handle four semantics:

**(1) Speaker identity injection**

In group chat, **the bridge can obtain the speaker from the platform event** (`sender`, including id/name); but **the agent only receives a piece of text**,
and by default does not know who said it. The bridge therefore injects a speaker label before the prompt text (`group.inject_speaker: true`):

```
[{name}]: {text}          # speaker_format, e.g. "[Alice]: help me look at this error"
```

- The label is generated by the bridge based on the platform `sender`, and **does not trust** forged prefixes in user input — before injection, sanitize lines in the body that look like
  a line-leading pattern `[xxx]:` to prevent "Bob impersonating Alice".
- Optional `mention_others: true`: keep other @-mentioned members as the text `@{name}`, so the agent can understand the reference.

**(2) Concurrency, ordering, and message attribution**

- The SDK is **serial per session**; messages from different users in a group are queued **FIFO by arrival order** (`delivery: queue`).
- **By default, no cross-user steer** (`group.cross_user_delivery: queue`): user B's new message will not steer into user A's
  in-progress turn — otherwise it would derail A's intent and create the impression that "the bot is answering off-topic".
  Optional `steer_same_user`: allow steer only when the new message is from the same person as the initiator of the current turn.
- Each turn records `active_turn_sender`; when replying (if capabilities allow), **@ the initiator** in the group, so that "who the bot is answering
  is clear at a glance". When a message is referenced, reply to that message (quote/reply).

**(3) HITL and command authorization (boundaries must be set in groups)**

- **Depends on platform data** (§3.3): authorization decisions need "**who clicked / who said it**" (`callback_actor_identity`, which mainstream platforms
  all provide) ⇒ `initiator` / `participants` can be implemented; "**is a group admin**" is **not provided** by most platforms
  (`member_roles`) ⇒ the `admins` tier falls back to the configured `group.admins` allowlist (or degrades to `initiator`).
- **HITL `group.hitl_scope`**: `initiator` (default, only that turn's initiator) / `participants` (any group member) /
  `admins` (**configured admins**, not a platform role). A click by an unauthorized person is **ignored with a reply hint**, and produces no side effect
  (to prevent others from approving dangerous operations on the initiator's behalf).
- **`/stop` `group.command_scope`**: the only bridge command is `/stop` (cancel the current turn); in a group, by default **only that turn's
  initiator** (`initiator`); only when set to `admins` are the configured admins (`group.admins`) allowed. In direct chat it is the person themselves; unauthorized persons are ignored with a hint.

**(4) Context and cost**

- Group conversations grow fast: it is recommended to enable auto-compaction on the agentd side (its `ContextLimit` config, which belongs to the **host**) and configure the bridge's
  `sessions.idle_reset_s`; note that this is different from the bridge's `model.context_limit` in §6.7 (**used only for usage display**).
- When multiple people in a group ask at the same time, they queue serially, and response latency grows with the queue; when the queue backs up, the bridge gives a "N messages ahead" hint.

**Comparison of the two forms**

| Dimension | Direct chat direct | Group chat group |
|---|---|---|
| Participants | 1 user + bot | N users + bot |
| Trigger | Forward on platform delivery (no second filter) | Same as left |
| Conversation mapping | One conversation (including thread) = one session | Same as left |
| Speaker injection | Not needed | Needed |
| Concurrency | Single person, steerable | FIFO by arrival; no cross-user steer by default |
| Reply attribution | Direct reply | @ the initiator / quote their message |
| HITL authorization | The user themselves | `initiator` (default) |
| `/stop` authorization | Themselves | `initiator` (default) / `admins` (configurable) |

**Platform specifics**

- WeCom: direct chat by `userid`; group chat by `chatid` (in a group, usually only messages that @ the bot arrive).
- Feishu: p2p / group; a topic group's thread is part of the conversation key.
- QQ: three entry points c2c (friend) / group (group) / channel (channel), mapping to `direct` / `group` respectively.
- Personal WeChat: mainly direct chat; group capabilities are limited, so it degrades according to `Capabilities`.

### 2.6 Bot Identity Synchronization (name + description → agent)

**Problem**: when the agent is @-mentioned in a group, the bridge strips `@bot` from the text; the agent only sees "help me take a look",
and **does not know who it is** nor **that this sentence is calling it**. In a shared group conversation, this causes errors when the agent refers to itself,
references context, or judges "whether it is being spoken to".

**Requirement**: synchronize the bot's **display name** and **description/persona** (and the aliases that can be @-mentioned) in each conversation into the agent
context, so that **the bot's external identity and the agent's self-perception are consistent**; re-synchronize when the name or description changes.

**Identity source (implemented per Connector by `Connector.identity(conv)`)**:

| Platform | Name | Description | Config |
|---|---|---|---|
| WeCom | not provided (the callback carries only `aibotid`) | not provided | **required** |
| Feishu | `GET /open-apis/bot/v3/info` → `app_name` | application info `description` | optional |
| QQ (`botpy`) | `robot.name` (from the `on_ready` event) | not provided | optional |
| Personal WeChat | logged-in account nickname (`whoami`) | signature (best-effort) | optional |

**Rule**: if `identity.display_name` / `identity.description` are configured, they take precedence; otherwise the
platform's own values are used. **WeCom exposes neither the name nor the description, so both are mandatory when
WeCom is enabled** (startup validation fails if they are missing). The name is **never** inferred from message
text (e.g. an inline `@name`) — that is fragile and was explicitly rejected.

**Alignment with the agent's own identity**: `GET /api/agent` returns each agent's `description` (from the agent's
markdown's `description` frontmatter). The bridge puts both the "IM bot identity" and the "current agent identity" into the context,
and decides which one takes precedence based on `identity.source`:

- `im` (default): the IM bot's name/description takes precedence; the agent's `description` is supplementary, and when the two are inconsistent, log a
  warning (an operational signal: the bot profile in the IM backend should be set to match the target agent).
- `agent`: the current agent's `description` takes precedence; the IM name is still used for "how it is addressed".
- `config`: `identity.display_name` / `identity.description` take precedence (overriding the platform values); for WeCom, where the platform provides neither, these configured values are **required**.

> Operational advice: **set the bot name/intro in the IM backend to match the target agent**, and the bridge is then naturally aligned;
> the alignment/injection on the bridge side is a fallback and a runtime synchronization mechanism.

**Synchronization method**: the agent's only entry point is the prompt text (`POST /api/session/{id}/prompt`, there is no "set
system prompt" endpoint), so identity is injected into the prompt text as a **structured context preamble**:

```
<bridge-context>
channel: wecom
bot_name: Assistant
bot_aliases: [Assistant]
bot_description: Enterprise R&D assistant: read code, run commands, answer questions.
agent: build
conversation: group:dev-team
participants: Alice, Bob            # optional, only when sync_participants
</bridge-context>
[Alice]: help me look at this bug
```

- Together with the speaker label in §2.5(1), it belongs to the "bridge-managed context", is generated by the bridge, and **has a unique wrapper marker**
  (`<bridge-context>…</bridge-context>`), by which the agent can distinguish "system context" from "user content".
- **Anti-forgery**: before injection, sanitize the `bridge-context` marker and the line-leading `[xxx]:` prefix that appear in the user's body text, to prevent users from
  forging system context or impersonating others (§2.5(1)).
- **Default description**: when the IM does not provide a description, fall back to the current agent's `description`, ensuring the agent still knows its own identity.
- Injection timing (`identity.inject`): `once` / `always` / `on_change` (default). **After compaction**
  (`session.next.compaction.ended`) or **after an operator switches the agent** (`POST …/agent`), it is recommended to inject at least once more,
  because the summary may discard the preamble and the identity may have changed.
- Name/description changes: when the Connector detects a change in the bot profile within a group, it updates `Route.bot_name` /
  `Route.bot_description` and sets `Route.context_dirty = true`, re-injecting on the next message; it does not rebuild the conversation
  (keeping the context continuous).

### 2.7 Mapping Quick Reference (§2.5 Summary)

(Quick-reference table; for fine-grained semantics, refer to §2.5.)

| IM scenario | Maps to agent | Identity injection |
|---|---|---|
| Direct message (1 user ↔ bot) | One DM = one session | bot name + description (optional) |
| Group chat (N users ↔ bot) | **One conversation** (key = conversation identifier, including thread) = one session | bot name + description + per-speaker label |

### 2.8 Project isolation: shared read-only, isolated writable

**Background**: For `go-agent-sdk`, **one `Client` (one agentd instance) = one project/working directory**
(`ClientOptions.WorkingDirectory` / `Root`). The HTTP API **does not provide per-session directory or location routing**
(`DESIGN-HTTP.md` §5.5 explicitly discards the location scope); a session's inline `directory` is fixed to the instance's
workingDirectory. One bot can join **multiple IM groups**, each group corresponding to one agent session (§2.5); whether these sessions share
**the same project (filesystem)** depends on the agent's **read/write capability**:

- **Read-only agent** (only read-only tools allowed; `write`/`edit`/`apply_patch`/`bash` all rejected): multiple groups sharing the same
  project has **no side effects**—each group's session context remains isolated (one session per group), they merely read the same code/files.
  **No project isolation needed.**
- **Writable agent** (allowed `write`/`edit`/`apply_patch`/`bash`, or can spawn writable sub-agents): multiple groups sharing one
  project will **modify each other's files and contaminate each other**. **Projects must be isolated per group**—each group binds to an independent agentd project instance
  (an independent working directory).

**Determination: based on the actual tool set, not the agent name**

`GET /api/tool?agent=<name>` (the server side has already materialized per `Options.InboundPermissions`) returns the tool set
actually available to that agent. If it contains **no mutation tools**, it is treated as read-only:

- Direct mutation: `write`, `edit`, `apply_patch`
- Indirect mutation: `bash` (can write files)
- Derivation: `task` (sub-agents may be writable)—unless all sub-agents are read-only

If any one is present ⇒ writable. **Unknown (query failed/ambiguous) ⇒ conservatively treat as writable (isolated)**. `agent.writable.<name>` can be used to
override the automatic determination.

**Isolation policy and implementation**

| `projects.isolation` | behavior |
|---|---|
| `auto` (default) | read-only agent → shared project; writable agent → per-session isolated project |
| `shared` | force sharing (only read-only agents allowed; a writable agent is rejected outright) |
| `per_conversation` | always one project per conversation (even if read-only) |

Isolation = **leasing an independent project instance** from `server.pool` (each instance has one `working_directory`):

```
read-only agent:  group A ─┐
                  group B ─┼─► same agentd project (shared files, safe for reading; each group still has its own session)
                  group C ─┘
writable agent:   group A ──► agentd project P_A (working directory A)
                  group B ──► agentd project P_B (working directory B)
                  group C ──► agentd project P_C (working directory C)
```

- **Startup validation**: `isolation: shared` and a writable agent detected → **fail-fast**.
- **Runtime conflict** (a writable agent lands on a shared project) → `projects.on_conflict: reject | isolate` (default `isolate`,
  lease an isolated project from the pool).
- **Agent switching** (operations via `POST …/agent`): when going read-only→writable while currently on a shared project, `agent.switch_guard: reject | migrate`
  (`migrate` = create a new session on an isolated project, the old context is not carried over automatically; default `reject` with a prompt).
- **Providers**: `pool` has independent instances pre-provisioned by the host; `worktree` (`git worktree` per group into an independent directory) requires the host to pair it with an
  agentd process supervisor; the bridge is only responsible for acquiring/releasing (clear boundary, the bridge does not spawn Go processes itself).
- **Snapshots/revert**: a writable project should enable snapshots if undo is needed; a read-only shared project needs no snapshots.

### 2.9 Implementation approaches to isolation (shared / worktree / container / others)

**Premise**: an agentd instance is permanently bound to one directory (no per-session location routing; `session.next.moved`
is defined but has no producer/public API), so "isolated project" = **multiple instances**. Isolation has multiple dimensions:

| Dimension | Description |
|---|---|
| Filesystem | project files, artifacts, temporary files are mutually invisible |
| SDK state | `Root` (session DB, snapshots/revert) do not interfere with each other |
| Process/runtime | the host process in which `bash`/tools execute |
| Network/egress | outbound connections such as `webfetch` (SSRF, data exfiltration) |
| Resources | CPU/memory/disk/PID/concurrency |
| Session context | already one session per group (§2.5), not an isolation dimension |

Four (and more) implementations, in increasing order of isolation strength and cost:

**(1) Shared (none / shared)**
- one agentd instance, one directory, reused by multiple groups.
- **Safe only for read-only agents** (§2.8 determination). Lowest cost, zero orchestration.

**(2) git worktree (suitable for git repositories)**
- Each writable group `git worktree add <dir> [<commit>|im/<group>]`, each working tree independent, **sharing the `.git` object store**.
- Each worktree needs one agentd instance (working directory = worktree).
- Advantages: saves disk (shared object store), fast (checkout-level), naturally allows independent commit/rollback per group.
- Usage: `detached` (start from a baseline commit, no branch, simplest) or `im/<group>` branch (traceable).
- Limitations/risks:
  - git repositories only; submodules/LFS/`.git` locks need handling.
  - **A `bash` agent can access the shared object store** (`git checkout` another branch/object)—strong isolation requires switching to containers or per-group clones.
  - The worktree directory should be placed outside the project or added to exclusions, to avoid being scanned by the agent's `glob/grep` (`reference` also needs exclusion).
- Cleanup: `git worktree remove` when a group is idle/offline.

**(3) Container isolation (containers)**

> Containers provide **both** a **sandbox** (agent → host: FS/process/network/resources) and **isolation** (session ↔ session: separate mounts/
> state)—see §2.9.2 for the difference between the two and their "convergence".

- One container per group, running agentd inside the container + mounting that group's worktree/directory; the container provides filesystem, process, user,
  network, and resource (cgroup) isolation.
- The bridge requests/destroys via a container orchestration interface (Docker/Podman/K8s); the in-container agentd exposes HTTP and registers as a project instance.
- Advantages: strongest isolation (including egress allowlists, resource quotas), suitable for mixing multiple sources / executing untrusted code.
- Cost: heavy (images, startup latency, orchestration complexity). Hardening: non-root, read-only root + writable mounts, minimal capabilities,
  `tmpfs`, no network or allowlisted egress, CPU/mem/pids quotas; image pre-provisioned with the agentd binary, credentials injected via secrets.
- Variant: one container, one agentd + one project (recommended); sandboxing only `bash` in containers requires the SDK to support out-of-process tools (currently tools and
  the agent loop are in the same process, so the entire agentd must be wrapped).

**(4) Others**
- **Directory copy (copy/rsync)**: a general approach for non-git; simple but consumes space linearly with repository size.
- **CoW / overlay (recommended low-cost isolation)**: the core is "**shared read-only base + copy-on-write materialization**", avoiding a full repository copy:

  | Platform / filesystem | Mechanism |
  |---|---|
  | Linux (generic, recommended) | **overlayfs**: `lowerdir`=base (read-only), `upperdir`=per-group writable layer, merged view; the kernel **correctly forwards in-place writes**; discarding the upper layer rolls back |
  | Linux (btrfs/XFS) | **reflink**: `cp -a --reflink=auto` (near-zero-copy within the same filesystem) |
  | macOS (APFS) | **clonefile / `cp -c`**: native APFS CoW |
  | Windows (ReFS/Dev Drive) | **block cloning** (`FSCTL_DUPLICATE_EXTENTS`) or VHD differencing disks |
  | Snapshot-type FS | ZFS / Btrfs subvolume snapshots |

- **Symlink / hardlink "farm" (`ln -s` / `cp -al`)—use with caution**: the idea is to place only links for each file, copying only on write,
  seemingly saving space, but there are two pitfalls:
  1. **Write-through (most dangerous)**: a tool's `open(O_WRONLY|O_TRUNC)` on a link path will **write directly to the base** → cross-group contamination;
     hardlinks are worse (shared inode, in-place writes directly modify the base). Must be paired with "**read-only base + write interception/redirection**"
     (overlayfs, or a CodeBuddy-like fs broker/shim that break-links before writing), otherwise it is **unsafe**.
  2. **Tool semantics breakage**: links change `realpath`, inode identity, `nlink`, mtime; `git`, package managers, build systems
     (make/ninja stat by inode/mtime), `find -L`, etc. are error-prone; directory links need an overlay to be partially overridden.
  - Conclusion: **prefer kernel-level CoW (overlayfs / reflink / clonefile)**; the link farm is only a fallback for "no CoW filesystem +
    write interception", and it must guarantee "materialize before write".
- **Relationship to git worktree**: worktree is git's "**object-store reference sharing**" version of CoW—the least hassle, but requires a git repository.
- **Namespace sandbox (bubblewrap/nsjail/chroot)**: lighter than containers, isolates filesystem/process/network; still requires one instance per group.
- **Separate machine/VM/remote instance**: one remote agentd per group (cross-host), physical-level isolation, suitable for the strongest isolation needs.
- **Orchestrator-managed (systemd-run/Nomad/K8s Job)**: hand the "per-group instance" lifecycle to an orchestrator.

> Combination recommendation (echoing §2.9.2): **per group = one isolated view (overlay/reflink/clonefile) + one layer of namespace/container sandbox**,
> i.e., a CoW view of "shared read-only base + per-group writable layer" running inside bwrap/a container, saving disk while obtaining both isolation and sandbox.

**Selection decision tree**

```
agent read-only? ──yes──► (1) shared
   │no
git repository? ──yes──► (2) worktree; need strong isolation/untrusted code? ──yes──► (2)+(3) worktree in container
   │no
support CoW/snapshots? ──yes──► (4) overlay / reflink / clonefile / subvolume snapshots
   │no
need strong isolation? ──yes──► (3) container + directory
   └──────────────► (4) directory copy
```

**Boundary with the bridge**: the bridge **does not fork Go processes itself**; multiple instances are created by a **host-side `supervisor`/orchestrator**,
and the bridge acquires/returns "project instances" (worktree/overlay/container) via `ProjectProvider` (§3.7). The static
`server.pool` and dynamic provisioning can coexist (a pool hit is reused, otherwise provision).

**Lifecycle and quotas**: leases are reclaimed with the group's idle TTL (release = `git worktree remove`/destroy container);
`projects.max_leases` limits concurrent leases (disk/memory protection); instance/working-directory naming and spool directory are isolated.

### 2.9.1 Comparison of sandbox implementations in mature coding agents (reference, skippable)

The "sandbox mode" of mainstream coding agents is all **two orthogonal layers of control**: **permission/approval (application layer, allow/ask/deny)** +
**sandbox (kernel layer, enforced boundary)**. The sandbox grants "autonomy within the boundary"; approval grants an "exit for crossing the boundary". The underlying primitives are consistent:

- macOS: **Seatbelt / `sandbox-exec`** (SBPL profile)
- Linux/WSL2: **bubblewrap** (unprivileged user+mount ns), **Landlock**, **seccomp**, namespaces, cgroup
- Windows: AppContainer / filter driver (native sandbox)
- Heavyweight: container (OCI)/devcontainer/VM (whole-process isolation)

| Product | Kernel mechanism | Network | Application/language layer | Features |
|---|---|---|---|---|
| **Claude Code** | `@anthropic-ai/sandbox-runtime`; macOS Seatbelt, Linux/WSL2 `bubblewrap`+`socat`(+seccomp) | no direct connection by default, allowed through a **local proxy** by domain allowlist (Linux netns, macOS Seatbelt) | wraps only **shell commands**; built-in Read/Edit/WebFetch, MCP, hooks go through permissions outside the sandbox | strong **credential protection**: env scrub, file mask, proxy TLS termination injection, AWS SigV4 re-signing; can run in devcontainer/VM |
| **Codex CLI** | macOS Seatbelt; Linux/WSL2 bubblewrap (falls back to a built-in helper when bwrap is missing, requires userns; includes Landlock/seccomp); Windows native sandbox | `workspace-write` **network off by default** | the boundary applies to spawned commands and their child processes | modes `read-only`/`workspace-write`/`danger-full-access`, `writable_roots`; approval policy is orthogonal; provides a git worktree environment; Cloud runs containers |
| **opencode** | **no OS sandbox** | none (relies on tool permissions) | pure **permission engine**: `allow/ask/deny` + wildcard/object rules (last match wins), `external_directory` guards outside the working directory, `.env` denied by default | lightest; hard isolation requires wrapping in a container yourself |
| **CodeBuddy** (tsbx, measured locally with `@tencent-ai/codebuddy-code`) | **central daemon `sandbox-center`** + `sandbox-cli`; macOS `sandbox-exec` + **generated Seatbelt profile**, PTY execution, `sandbox_extension_*` dynamic authorization; Windows native file/registry/process rules + browser allowlist | **dual engine**: DNS hook domain interception + **Rust LocalProxy** (injects `HTTP(S)_PROXY`, decides by rules) | **user-space broker** (IPC program blacklist, `BASH_ENV`/PATH prepended with command shims such as toybox) + **Node `--require` fs hook** + **Python `sitecustomize`** + native addon; `rm` redirected to the **trash** | most in-depth and heaviest; rules in `tsbx_rules.json` (file/registry/process/network rules); this build is darwin/win only |

**Common implementation patterns**:

1. Filesystem **deny-by-default + allowlist**: only writing to the working directory/temp directory is allowed; reads are permissive by default but sensitive directories can be denied
   (`~/.ssh`, `~/.aws`, `.env`).
2. Network **off by default + proxy allowlist**; non-HTTP protocols (ssh/DB/UDP) are simply unreachable.
3. The boundary applies to **executed commands and their child processes** (inherited along the process tree).
4. **Protected paths**: modification of the agent's own configuration / shell rc / hooks / `.git/config` is forbidden (prevents self-privilege-escalation).
5. **Credential protection**: env scrub, file mask, proxy replacement/re-signing.
6. **Approval as the boundary-crossing exit** (unsandboxed retry / on-request / `--auto`).
7. Use a **container/VM** when whole-process isolation is needed.

**Mapping to the bridge (§2.8/§2.9/§3.7)**:

- These products are "**single-machine, single-session, in-process**" sandboxes; the bridge faces "**multi-user, multi-group, multi-session**" and wants
  **process-level/project-level** isolation (one agentd instance per group, §2.8), but can **reuse the same set of primitives**.
- `sandbox-center` (centralized policy/leases) ≈ the bridge's `ProjectProvider` + policy service (§3.7).
- Wrapping **each agentd instance** in `bubblewrap`/Landlock+netns or an OCI container (§2.9(3)/(4)) =
  `sandbox-cli`+Seatbelt for CodeBuddy.
- "read-only agent" = a filesystem **read-only sandbox** (exactly realizing the safe premise for shared projects in §2.8).
- LocalProxy/egress allowlist = **SSRF protection** for `webfetch`; env scrub/read-only mounts = **credential isolation**;
  protected paths = preventing agent self-privilege-escalation; approval exit = the bridge's **HITL** (§4.6).
- Conclusion: the "container/namespace" of §2.9 is not an alternative but the **primary recommended direction**, consistent with mature products; the bridge's isolation policy
  should default to "shared read-only, isolated writable" and enforce the above boundaries on the writable path.

### 2.9.2 Sandbox vs project isolation: orthogonal and convergent

The two solve problems at **different layers** and cannot substitute for each other; but in their strongest form they **converge into one**.

| Dimension | Sandbox | Project isolation (§2.8/§2.9) |
|---|---|---|
| Guards against | **agent → host** (unauthorized writes, egress, credential theft, privilege escalation) | **session A ↔ session B** (modifying each other's files, cross-tenant peeking, state/snapshot cross-contamination, resource contention) |
| Scope | the boundary of one agent process | separation between multiple tenants/groups |
| Means | Seatbelt/bwrap/Landlock/seccomp/network proxy | worktree / separate directory / separate instance / separate `Root` |

- **Not interchangeable**: two writable groups in the same directory, even if both are wrapped in sandboxes, will still **overwrite each other** (the sandbox allows writing to the workspace), and neither can reach
  the sessions/snapshots of a shared `Root`; worktree isolation alone still cannot block reading `~/.ssh` or egress exfiltration.
- **Convergence (recommended)**: **one process-level sandbox instance per group (container / bwrap + separate directory)** = isolation + sandbox **unified**—
  a container simultaneously provides fs/process/network/resource isolation and separate mounts, **without** stacking two separate mechanisms of worktree and fs sandbox
  (i.e., the form in §2.9(3)).
- Conversely: a sandbox that **shares one process** still needs isolation; **file isolation only** (worktree) without a kernel sandbox still needs a sandbox.
- The "**read-only sharing**" optimization (§2.8) degenerates into a **resource optimization** under a sandbox: it is safe only when the shared directory is **truly read-only (sealed/read-only mount)**;
  if workspace write permission is opened up to let a read-only agent write temporary files, then sharing is no longer safe.
- The SDK's `Sandbox` hook (§17.2) only constrains tool execution **within a single process** and does not produce "one directory per group", so the isolation decision remains in the bridge.
- **Landing point**: `ProjectProvider` (§3.7) is the combination point of the two; the recommended providers converge to `container` / `worktree`
  (one sandbox instance per group), rather than the two-part assembly of "shared instance + separate file/network sandbox".

> **Cross-transport shared isolation** (`agentd`'s HTTP ↔ A2A transports): the "mechanism" of isolation goes in the command layer, shared across transports;
> "policy/hook" goes in the SDK; "decision/lease" goes in the host. The constraint is to **share the mechanism, not the instance** (a writable project has a single owner).
> This is a discussion of responsibility boundaries, see **§17.3** for details.

---

## 3. Core abstractions (extensibility design)

> Design principle: **adding a new IM platform = adding one Connector + one capability declaration + possibly a render profile**,
> the core engine (Router/TurnEngine/Streaming/Renderer/AgentClient) does not change.

### 3.1 Connector interface `IMConnector`

```python
class IMConnector(Protocol):
    name: str  # "wecom" | "feishu" | "qq" | "wechat"
    capabilities: Capabilities  # §3.3, drives rendering and degradation

    # Lifecycle: the connector "emits" inbound items to the upstream (messages / card interactions / platform events, see §3.2)
    async def start(self, emit: Callable[[IncomingItem], Awaitable[None]]) -> None: ...
    async def stop(self) -> None: ...

    # Outbound primitives (implement when capabilities allow, otherwise raise Unsupported)
    async def send(self, conv: Conversation, plan: OutboundPlan) -> SentRef: ...
    async def update(self, ref: SentRef, plan: OutboundPlan) -> None: ...  # optional
    async def reply(self, in_reply_to: InboundMessage, plan: OutboundPlan) -> SentRef: ...
    async def send_typing(self, conv: Conversation) -> None: ...  # optional
    async def react(self, ref: SentRef, emoji: str) -> None: ...  # optional
    async def send_card(self, conv: Conversation, card: Card) -> SentRef: ...  # HITL interaction

    # Media
    async def download(self, att: Attachment) -> MediaBytes: ...  # fetch bytes for inbound
    async def upload(
        self, data: MediaBytes, *, kind: str
    ) -> MediaHandle: ...  # upload needed for outbound

    # Platform facts (§2.6 identity sync / group info)
    async def identity(
        self, conv: Conversation
    ) -> BotIdentity: ...  # bot display name/description/aliases
    async def conversation_info(
        self, conv: Conversation
    ) -> ConversationInfo: ...  # group name/members (optional)
```

- The connector is responsible only for **platform SDK details**: connection/reconnection/heartbeat, event parsing, AES decryption, media upload,
  card structures, rate limiting.
- The connector does **not** do session mapping, prompt assembly, Markdown rendering, or HITL decisions (all in the core layer).
- Connector exceptions propagate upward; the core layer handles unified retry/alerting (§8).

### 3.2 Unified message model

```python
@dataclass(frozen=True)
class Conversation:
    channel: str  # connector name
    kind: Literal["direct", "group", "channel"]
    id: str  # chatid / open_chat_id / group_openid / channel_id
    name: str | None = None  # group/conversation display name (§2.6, nullable)
    thread: str | None = None  # optional: topic/sub-thread
    tenant: str | None = None  # optional: origin/deployment dimension (§2.1 Tenant)

    @property
    def key(self) -> str: ...  # stable unique key: f"{channel}:{kind}:{tenant}:{id}:{thread}"


@dataclass(frozen=True)
class BotIdentity:
    name: str  # bot's display name in this conversation (§2.6)
    description: str | None = None  # bot bio/persona (§2.6)
    aliases: tuple[str, ...] = ()  # aliases that can be @-mentioned
    avatar_url: str | None = None  # optional, for display only


@dataclass(frozen=True)
class ConversationInfo:
    name: str | None = None  # group name
    members: tuple[
        Sender, ...
    ] = ()  # members (optional, privacy-sensitive, not injected by default)


@dataclass
class Sender:
    id: str
    name: str | None = None
    is_bot: bool = False


@dataclass
class Attachment:
    kind: Literal[
        "image", "audio", "video", "file", "voice"
    ]  # voice is categorized as audio (§7.1)
    mime: str | None
    name: str | None
    size: int | None
    # all information needed to fetch bytes from the platform (url + aes key + resource token…), opaque to the core layer
    handle: Any
    width: int | None = None
    height: int | None = None
    duration_ms: int | None = None


@dataclass
class InboundMessage:
    channel: str
    message_id: str  # platform message id
    conversation: Conversation
    sender: Sender
    text: str  # rich text/image placeholders already normalized to text
    mentions: list[Sender] = field(default_factory=list)
    attachments: list[Attachment] = field(default_factory=list)
    quoted: "InboundMessage | None" = None
    timestamp: float = 0.0
    raw: Any = None  # raw frame, kept for extension/debugging


# the three kinds of inbound items a connector emits upward (the argument of `emit`, see §3.1)
IncomingItem = InboundMessage | IncomingInteraction | ConnectorEvent


@dataclass
class IncomingInteraction:  # card/button callback (HITL click)
    conversation: Conversation
    message_id: str  # id of the clicked card message
    sender: Sender  # clicker (used for authorization decision, §2.5(3))
    value: str  # button value (the action encoded by the core layer, §4.6)
    raw: Any = None


@dataclass
class ConnectorEvent:  # platform events such as enter_chat / feedback / recall
    kind: Literal["enter_chat", "feedback", "recall", "other"]
    conversation: Conversation
    sender: Sender | None = None
    raw: Any = None


@dataclass
class Usage:  # usage/context (§6.7)
    input_tokens: int = 0
    output_tokens: int = 0
    reasoning_tokens: int = 0
    cached_tokens: int = 0
    cost: float = 0.0
    context_tokens: int | None = None  # latest step input size (context occupancy)
    context_limit: int | None = None  # model context window


# outbound: canonical carrier = Markdown text + media + interactive cards, see §6.3
@dataclass
class OutboundPlan:
    segments: list[Segment]  # ordered segments: text segment / media segment / card segment
    reply_to: str | None = None  # which platform message to reply to
    final: bool = False  # whether this is the stream end frame


@dataclass
class Card:  # interactive card used for HITL / command results
    title: str | None
    body: str  # Markdown
    buttons: list[Button]  # callback payload generated by the core layer
    fields: dict[str, str] = field(default_factory=dict)


@dataclass
class Button:
    text: str
    value: str  # the action encoded by the core layer (§4.6)
    style: str | None = None
```

> For the remaining types (`Segment` / `RichMedia` / `SentRef` / `MediaBytes` / `MediaHandle` / `Event`), see the §18 glossary.

### 3.3 Capability declaration `Capabilities` (**most critical**)

Rendering and degradation are entirely capability-driven; the connector only **declares facts** and writes no rendering branches.

```python
# Platform "delivery model": which messages the platform pushes to the bot (**facts**, for documentation/integration reference; the bridge forwards on receipt,
# without secondary filtering — see §2.5).
DeliveryModel = Literal["always", "mention_only", "on_session", "unknown"]
#   always: every message of this form is pushed
#   mention_only: only messages @-mentioning the bot are pushed
#   on_session: pushed only after the user first enters/opens a conversation with the bot (e.g. WeCom requires enter_chat first)
#   unknown: not yet confirmed by integration testing (see §13 capability integration; handled most conservatively at runtime)


@dataclass(frozen=True)
class Capabilities:
    markdown: MarkdownLevel  # NONE | BASIC | STANDARD | RICH
    #   NONE: plain text; BASIC: bold/italic/links/code; STANDARD: + lists/quotes/code blocks; RICH: + tables/heading levels
    code_block: bool
    tables: bool
    headings: bool
    images_inline: bool  # whether Markdown images can be inlined (usually false → sent as a separate image message)
    edit_message: bool  # whether sent messages can be edited (determines the streaming method)
    native_stream: (
        bool  # whether "streaming refresh of the same message" is natively supported (WeCom bot)
    )
    buttons: bool  # interactive cards/buttons
    reactions: bool
    typing: bool
    proactive: bool  # can push proactively without a callback
    groups: bool
    mention: bool  # whether the platform supports @-mentioning the bot
    # authorization data (determines which tier §2.5(3)'s hitl_scope / command_scope can land in)
    callback_actor_identity: bool  # whether card/button callbacks carry the clicker's identity (prerequisite for HITL authorization)
    member_roles: bool  # whether the platform exposes group member roles (owner/admin) — determines the `admins` tier
    direct_delivery: DeliveryModel  # the platform's delivery behavior for **direct** messages
    group_delivery: DeliveryModel  # the platform's delivery behavior for **group** messages
    max_text_chars: int  # max text length per message
    max_cards: int  # max number of cards per message (for declaration)
    media_in: frozenset[str]  # inbound media accepted: image/audio/video/file
    media_out: frozenset[str]  # outbound media supported
    rate_limit_per_min: int | None  # platform rate limit (used for token bucket)
```

> **Delivery is a platform fact, not filtering**. The bridge **forwards on receipt** and does no secondary trigger filtering; `direct_delivery` /
> `group_delivery` are used only for documentation and the §13.1 integration reference — for example, when a WeCom group chat is `mention_only`, non-@ messages
> are simply never received, and the agent naturally handles only @ messages.

> **Authorization data availability** (determines the `hitl_scope` / `command_scope` tier of §2.5(3)): **clicker/sender identity**
> is provided by mainstream platforms (`callback_actor_identity: true`), enabling `initiator` / `participants`;
> **group member roles (owner/admin)** are **not provided** by most platforms (`member_roles: false`), so the `admins` tier falls back to the configured
> `group.admins` allow-list (or is downgraded to `initiator`). Whether Feishu can obtain roles via an extra API is **pending integration testing**.

**Authorization data (preliminary assessment; `pending integration testing` items are back-filled after verification per §13.1):**

| Platform | callback_actor_identity | member_roles (owner/admin) |
|---|---|---|
| WeCom Smart Robot | Yes (`event.template_card_event` carries the clicker, **fields pending integration testing**) | **No** |
| Feishu | Yes (`card.action.trigger` carries `operator`, **pending integration testing**) | **?** (possibly via chat API, **pending integration testing**) |
| QQ (botpy) | Yes (interaction callbacks carry the user, **pending integration testing**) | **No** |
| WeChat Personal | N/A (no buttons; text messages carry `sender`) | **No** |

Preliminary assessment per platform (**starting from documentation, unconfirmed items marked `pending integration testing`, back-filled after §13 measurement**):

| Platform | markdown | edit | native_stream | buttons | media_out | direct_delivery | group_delivery | Status |
|---|---|---|---|---|---|---|---|---|
| WeCom Smart Robot | RICH (bot markdown) | No* | **Yes** (`reply_stream`) | Yes (template card) | image/file/voice/video | `always` | `mention_only` | Docs (long connection) |
| Feishu | RICH (interactive card markdown) | Yes (patch card) | No (simulated with edit) | Yes (card buttons) | image/file/audio/video | **pending integration testing** | **pending integration testing** | pending integration testing |
| QQ (botpy) | BASIC (markdown message) | No | No | Yes (keyboard) | image/video/audio | **pending integration testing** | **pending integration testing** | pending integration testing |
| WeChat Personal (wechatbot.dev) | NONE | No | No | No | image/voice/file/video | **pending integration testing** | **pending integration testing** | pending integration testing |

> *WeCom implements "pseudo-editing" by pushing multiple times via `reply_stream`; no real edit API is needed.
> A `pending integration testing` cell means **not "unsupported"** but "not yet confirmed on a real device"; after verification with the §13 integration checklist it is back-filled with
> definite values such as `always`/`mention_only`/`on_session`, and the marker is removed.

### 3.4 Agent client interface `AgentClient`

Exposes only the subset the bridge needs (for the remaining endpoints see the §4.1 table):

```python
class AgentClient(Protocol):
    # discovery (§2.6 identity alignment / §2.8 read-write determination) — DTO fields see §4.1
    async def list_agents(
        self,
    ) -> list[AgentInfo]: ...  # GET /api/agent: {id,description,mode,hidden,model,backend}
    async def list_models(
        self,
    ) -> list[ModelInfo]: ...  # GET /api/model: {id,protocol,input,sources}
    async def agent_tools(
        self, agent: str
    ) -> list[ToolInfo]: ...  # GET /api/tool?agent=: {name,description}
    async def active_sessions(
        self,
    ) -> dict[str, ActiveSession]: ...  # GET /api/session/active: {sid:{type:"running"}}

    # session
    async def create_session(
        self, *, agent: str, model: str | None = None, title: str | None = None
    ) -> SessionInfo: ...
    async def get_session(self, sid: str) -> SessionInfo: ...
    async def set_agent(self, sid: str, agent: str) -> None: ...
    async def set_model(self, sid: str, model_ref: dict) -> None: ...
    async def set_title(self, sid: str, title: str) -> None: ...
    async def delete_session(self, sid: str) -> None: ...

    # execution
    async def prompt(
        self,
        sid: str,
        *,
        prompt: str,
        files: list[dict],  # files=PromptFileAttachment[] (§4.4)
        id: str | None = None,
        delivery: str = "queue",
    ) -> None: ...
    async def interrupt(self, sid: str) -> None: ...
    async def compact(self, sid: str) -> bool: ...
    async def wait(self, sid: str, timeout_s: float) -> bool: ...

    # read
    async def messages(self, sid: str) -> list[dict]: ...  # full /message
    async def upload_file(
        self, sid: str, *, data: bytes, mime: str, name: str | None, provider_id: str | None = None
    ) -> dict: ...

    # interaction
    async def reply_permission(
        self, sid: str, rid: str, *, reply: str, message: str | None = None
    ) -> None: ...
    async def reply_question(self, sid: str, rid: str, answers: list[list[str]]) -> None: ...
    async def reject_question(self, sid: str, rid: str) -> None: ...
    async def list_permissions(self) -> list[PendingPermission]: ...
    async def list_questions(self) -> list[PendingQuestion]: ...

    # events (global SSE, see §4.3)
    def events(self) -> AsyncIterator[Event]: ...
```

### 3.5 Renderer interface `Renderer`

```python
class Renderer(Protocol):
    def render(self, doc: RichDoc, caps: Capabilities) -> OutboundPlan: ...
    def render_card(self, card: Card, caps: Capabilities) -> OutboundPlan: ...


@dataclass
class RichDoc:
    markdown: str  # canonical carrier: body Markdown
    reasoning: str | None = None  # reasoning process (§6.7; rendered/collapsed per reasoning_style)
    usage: Usage | None = None  # this turn's/context usage (§6.7)
    media: list[RichMedia] = field(default_factory=list)
    interactive: list[Button] = field(default_factory=list)
```

The canonical carrier is simply **Markdown** (models naturally produce Markdown), with media and interactions as side-attached structures.
The renderer parses it into a token stream with `markdown-it-py`, then degrades it according to `MarkdownLevel` (§6.4).

### 3.6 Session routing `Router` / mapping store `RouteStore`

```python
@dataclass
class Route:
    conversation: Conversation
    session_id: str
    server_base: str  # from the server pool
    project_id: str | None = (
        None  # owning project instance (§2.8; the landing point of isolation decisions)
    )
    agent: str
    model: str | None
    # group chat/multi-user semantics (§2.5)
    participants: dict[str, str] = field(default_factory=dict)  # sender id -> display name
    active_turn_sender: str | None = None  # initiator of the current turn
    queue_depth: int = (
        0  # number of prompts submitted on the bridge side but whose turn has not ended (§8.1)
    )
    # bot identity sync (§2.6)
    bot_name: str | None = None  # bot display name in this conversation
    bot_description: str | None = None  # bot bio/persona
    context_dirty: bool = False  # after name/description change, agent switch, or compaction, the context needs re-injection
    created_at: float = 0.0
    last_active: float = 0.0
    # in-conversation state required for HITL/streaming (persisted)
    # pending interactions are an **ordered map**: multiple permissions can be concurrent, and can coexist with questions.
    #   rid -> PendingInteraction(kind, owner, options)
    # The "numbered fallback" on channels without buttons is numbered in insertion order; authorization decisions go by owner (§2.5/§4.6).
    pending_interactions: dict[str, "PendingInteraction"] = field(default_factory=dict)
    stream_ref: dict | None = None
```

@dataclass
class PendingInteraction:
    kind: Literal["permission", "question"]
    owner: str | None = None      # initiator (the turn's sender); the only one who can answer when scope=initiator
    scope: str = "initiator"      # initiator | participants | admins (§2.5(3) / group.hitl_scope)
    options: list[str] = field(default_factory=list)  # numbered fallback for channels without buttons (§4.6)

- **Mapping key** = `Conversation.key` (channel+kind+tenant+id+thread). **One IM conversation = one Route =
  one agent session**; direct chat is likewise one conversation one session (no per-user splitting).
- Storage: SQLite (`aiosqlite`), table `routes` (primary key `Conversation.key`), with a **unique index** on `session_id`
  — SSE events and HITL reconciliation are both looked up in reverse by `sessionID` (§4.3/§8.3); this guarantees conversations are not lost after a bridge restart.
- One Route corresponds to one agentd session; on the SDK side this is naturally "serial within the same conversation" — this is exactly the basis for queueing
  multi-user messages in a group chat in arrival order (§2.5(2)).
- **Project ownership** (§2.8): `project_id`/`server_base` are assigned by the Router according to the agent's read-write capability — a read-only agent can
  reuse the same project; a writable agent exclusively holds one project instance leased from `server.pool` per group.

### 3.7 Project provider `ProjectProvider` (isolation implementation abstraction)

The bridge does not `fork` Go processes itself; instead it requests/returns "project instances" through `ProjectProvider` (constructor injection,
consistent with "the SDK does not own infrastructure"). This makes the various isolation methods of §2.9 pluggable implementations.

```python
@dataclass
class ProjectLease:
    project_id: str
    transport: str = "http"  # "http" | "a2a" — one instance serves one transport (§17.3). Tether always uses "http"
    server_base: str  # address of this instance (HTTP or A2A endpoint)
    working_directory: str | None = None  # for audit/logging only
    ephemeral: bool = False  # whether it is ephemeral (needs release)


class ProjectProvider(Protocol):
    async def acquire(
        self, conv: Conversation, *, agent: str, readonly: bool, transport: str = "http"
    ) -> ProjectLease: ...  # reuse on a pool hit, otherwise create
    async def release(
        self, lease: ProjectLease
    ) -> None: ...  # return the lease (destroy worktree/container)
    async def health(self, lease: ProjectLease) -> bool: ...
    async def preflight(self) -> None: ...  # startup validation (§2.8 fail-fast)
```

Built-in implementations (selected by the `projects.provider` config):

| provider | Corresponding §2.9 | Description |
|---|---|---|
| `shared` | (1) | Single-instance reuse (read-only) |
| `pool` | — | Static `server.pool` leasing |
| `worktree` | (2) | `git worktree` + host supervisor launches the corresponding agentd (§17.3) |
| `overlay` | (4) | **CoW isolated view**: overlayfs / reflink / clonefile generates a per-group writable layer (§2.9(4)) |
| `container` | (3) | Docker/Podman/K8s API requests a containerized agentd |
| `remote` | (4) | An existing remote instance |

- The `readonly` of `acquire` comes from the §2.8 determination; `shared`/`pool` reject `readonly=False` by default (unless
  `isolation: per_conversation` and the pool is sufficient).
- **`supervisor` is a host-side component** (Tether does not execute it): the provider hands `(project identifier, isolation strategy, transport)`
  (corresponding to §17.3's `ProjectSpec`/`IsolationSpec`) to the host supervisor (or first checks the static `server.pool`),
  which calls the transport-agnostic project runner under `cmd/` to launch the instance and return `server_base`; **a writable project at any one time
  is leased to only one `(project, transport)`**, while read-only can be shared (§17).
- `supervisor.command` is the entry point in the **host configuration** for "launching agentd per project" (interpreted and executed by the host); **if unconfigured
  it degrades to an external registry mode** (the host pre-provisions instances and the bridge only looks up the table to lease).
- Leases are released with the group's idle TTL (§2.9), with `projects.max_leases` as the limit.

---

## 4. Agent-side integration (go-agent-sdk HTTP API)

> All facts are governed by `pkg/server/*` and `docs/DESIGN-HTTP.md`. The following lists only the endpoints actually used by the bridge.

### 4.1 Endpoint list (bridge perspective)

| Purpose | Endpoint |
|---|---|
| Health probe | `GET /api/health` → `{"healthy":true}` |
| Available agents | `GET /api/agent` → `{data:[{id,description,mode,hidden,model,backend}]}` |
| Model capabilities | `GET /api/model` → `{data:[{id,protocol,input,sources}]}` |
| Tool set | `GET /api/tool?agent=<name>` → `{data:[{name,description}]}` (read-only determination, §2.8) |
| Create session | `POST /api/session` `{agent,model,title}` → `{data:{id,…}}` |
| Session info | `GET /api/session/{sid}` |
| Active sessions | `GET /api/session/active` → `{data:{sid:{type:"running"}}}` |
| Switch (ops) | `POST /api/session/{sid}/agent`, `/model`, `/title` → `204` (non-conversation-stream) |
| Prompt | `POST /api/session/{sid}/prompt` `{prompt,id,delivery,files}` → `202 {queued:true}` |
| Interrupt | `POST /api/session/{sid}/interrupt` → `204` |
| Compact | `POST /api/session/{sid}/compact` → `{data:{compacted}}` |
| Wait | `POST /api/session/{sid}/wait?timeout=30s` → `{data:{idle}}` |
| Full messages | `GET /api/session/{sid}/message` (paginated) |
| Active context (not yet used) | `GET /api/session/{sid}/context` |
| durable event page | `GET /api/session/{sid}/history?after=&limit=` |
| Upload file | `POST /api/session/{sid}/file` `{providerID,mime,name,data(base64)}` |
| Delete session | `DELETE /api/session/{sid}` → `204` |
| Permission list/reply | `GET /api/permission`, `GET /api/session/{sid}/permission`, `POST /api/session/{sid}/permission/{rid}/reply` |
| Question list/reply | `GET /api/question`, `GET /api/session/{sid}/question`, `POST …/question/{rid}/reply`, `…/reject` |
| Global events | `GET /api/event` (SSE, all sessions, includes live-only delta and HITL) |

Responses are uniformly `{"data": …}`; errors are uniformly `{"error":code,"message":…}` (§10).

### 4.2 Session lifecycle and mapping strategy

- On first receipt of a message for some conversation: `POST /api/session` (include model if configured),
  persist `Route`, then prompt.
- Subsequent messages reuse the same `session_id`.
- Idle reclamation (optional): after `sessions.idle_reset_s` seconds without activity, you may call `POST …/compact` or simply switch to a new session
  (to avoid excessive context length and accumulating cost); by default there is no automatic reset (there is no user command to reset; see §6.6).
- **Session mapping** (see §2.5 for details): **one IM conversation = one agent session**, with the key being `Conversation.key`
  (including thread). Created on first contact with a conversation, reused thereafter.
- **Speaker injection**: when a group chat shares a session, inject a `[{name}]: ` label before the `prompt` text, and sanitize
  the same kind of prefix from the body (to prevent impersonation); this sanitization happens in the prompt-assembly stage before `AgentClient.prompt`.
- **bot identity injection**: when a session is created, use `Connector.identity(conv)` to get the bot display name and description and write them into
  `Route.bot_name` / `Route.bot_description`; according to the `identity.inject` strategy, prefix-inject `<bridge-context>`
  into the prompt text (see §2.6, §4.8 for details); after a name/description change, agent switch, or compaction, set
  `context_dirty` and re-inject.
- **Attribution**: the user a turn belongs to is recorded in `Route.active_turn_sender`, for @-mentioning when replying and for HITL authorization decisions.

### 4.3 Event consumption: **one global SSE + routing**

Choose **one** persistent SSE connection to `/api/event` (one per agentd base), for the following reasons:

- `/api/event` is the SDK's **main push-stream channel**, carrying **all** events, including the live-only
  `session.next.text.delta`, `session.status`, and all HITL events (`permission.v2.asked`
  / `question.v2.asked`) — none of these are present in durable replay.
- The bridge service is single-process, multi-session; a global subscription + `sessionID → Route` routing table is sufficient, avoiding one connection per session.

SSE frame format (`docs/DESIGN-HTTP.md` §6.3):

```
event: message
data: {"id":"evt_…","type":"session.next.text.delta","data":{…}}
<blank line>
: heartbeat
<blank line>
```

- The first frame is always `server.connected`.
- Parsing: accumulate line by line until a blank line to obtain one event; `event: error` is a stream-error frame (`subscriber_overflow`, etc.).
- **Reconnect**: when durable replay is needed, use the **per-session** `/api/session/{id}/event?after=<seq>`; this design uses
  the **global** `/api/event` (no replay). Therefore after a disconnect the bridge performs **reconciliation** (§8.3): `GET /api/session/active`
  to find running sessions, and for each session `GET /api/session/{sid}/message` to recover the final text and tool media, and
  `GET /api/permission` / `GET /api/question` to recover pending HITL.
- **HITL fallback polling**: since HITL is live-only, the bridge polls `/api/permission` and `/api/question` once after (re)connection and
  every `permissions.poll_interval_s`, to avoid missing interactions produced within the disconnection window.

Event classification (see appendix §16 for details):

| Category | Event | Purpose |
|---|---|---|
| Text stream | `session.next.text.started/delta/ended` | Streaming display; `ended` is the final text |
| Reasoning stream | `session.next.reasoning.*` | Optionally display "thinking" |
| Tools | `session.next.tool.input.*`, `tool.called`, `tool.progress`, `tool.success`, `tool.failed` | Progress visualization, collect media produced by tools |
| Step | `session.next.step.started/ended/failed` | `step.ended.files` are the changed files, `step.failed.error` is the error |
| Status | `session.status` (live-only) `{sessionID,status:{type:idle\|busy\|retry,…}}` | Determine turn end / busy / retry |
| Attachment | `session.next.attachment.omitted` (durable) `{messageID,name,mime,reason}` | Inform the user why an attachment was dropped by the model/protocol |
| HITL | `permission.v2.asked`, `question.v2.asked` (live-only) | Render interaction cards (§4.6) |
| Title | `session.next.title.updated` | Optionally sync the session title |
| Compaction | `session.next.compaction.*` | Display "compacting context" |

> Determining turn end: receiving `session.status` for that `sessionID` with `status.type == "idle"`.
> Other statuses: `busy`; `retry` (contains `attempt/message/action`, can prompt "retry #N").

### 4.4 Attachment uplink (IM → Agent) — PromptFileAttachment fields

> **Three "transfer/retrieve" operations must be distinguished**: ① **IM download** `Connector.download(att)` — fetch bytes from the IM platform (needed for the inbound of this section);
> ② **Provider upload** `POST /api/session/{id}/file` (Go-side `MediaUploader`) — send the bytes to the **LLM provider**'s
> Files API to obtain a `fileId` (needed when the inbound uses the `file` source, **unrelated to the IM SDK**); ③ **IM upload**
> `Connector.upload(data)` — send the bytes to the IM platform (needed for **outbound §4.5**). The three have different caching/expiration strategies.
> See §7.7 for the download/upload capabilities of each IM SDK.

**Fetching bytes**: the Connector obtains attachment info from a platform event (WeCom `aeskey`/`url`, Feishu `file_key`, QQ/WeChat `url`),
normalizes it into `Attachment{kind,mime,name,size,handle}`; `MediaIngest` calls `Connector.download(att)` to fetch bytes
(the platform SDK handles authentication/decryption), then follows the decision tree below.

The `files[]` elements of `POST …/prompt` are `schema.PromptFileAttachment` (`pkg/schema/prompt.go`),
and the **actual JSON fields** are as follows (note `source` is PromptSource, and the media source field is `mediaSource`):

```jsonc
{
  "uri": "data:image/png;base64,…",   // when inline it is a data URL; when url it is an http(s) URL
  "mime": "image/png",
  "name": "shot.png",
  "description": null,
  "mediaSource": "inline",            // can be omitted; when omitted, inferred from the uri prefix (data:→inline, http(s)→url)
  "fileId": "file-api-…",             // provider reference when mediaSource=file
  "detail": "auto"                    // optional: low|high|original|auto (only some protocols support it)
}
```

Upload decision (`MediaIngest`):

```
download bytes → obtain (mime, size, bytes/or URL only)
  ├─ target model modality unsupported (the input of GET /api/model)? → do not put into files[],
  │     instead spool into the working directory and note the path in the prompt text (the agent can read it with the read tool)
  ├─ size ≤ inline_limit and modality supported → files[{uri:"data:<mime>;base64,…", mediaSource:"inline"}]
  ├─ agentd is configured with a MediaUploader and the source supports file
  │     → POST /api/session/{sid}/file → files[{mediaSource:"file", fileId}]
  ├─ the bridge can provide a publicly reachable URL (a public download address is configured) → files[{uri, mediaSource:"url"}]
  └─ otherwise → spool into the working directory + note the path in the prompt (the agent reads it with a tool), and notify the user
```

- The **spool fallback** is not "sent into the model" but "handed to the agent's tool to read". So that `read` can access it (and without depending on
  an `external_directory` allowance), **spool into a controlled subdirectory inside the working directory** (default `<working_dir>/.tether/spool/`),
  with the filename sanitized (§10.4), to avoid path traversal.
- When the model does not support it, also give the user a one-line notice; the SDK side additionally re-sends
  the `session.next.attachment.omitted` event (the bridge also renders it, double insurance).

### 4.5 Attachment downlink (Agent → IM) — media produced by tools

The Agent has two sources of produced media:

1. **File parts in tool results**: the `data.content` of `session.next.tool.success`/`tool.progress`
   is `ToolContents` (`pkg/schema/llm.go`), possibly containing `{type:"file", uri, mime, name, mediaSource, fileId}`; when `uri` is inline it is a data URL.
2. **Full messages after the turn ends**: the assistant tool state of `GET /api/session/{sid}/message`
   `SessionMessageToolStateCompleted.Attachments` (`PromptFileAttachment`) and `Content`.

Downlink flow:

```
collect file parts
  ├─ mediaSource=inline → decode the base64 data URL → obtain bytes
  ├─ mediaSource=url    → optional: fetched by the bridge (requires SSRF protection) and then forwarded; or send the link directly
  ├─ mediaSource=file   → the provider reference cannot be downloaded directly; if the bridge is configured with provider download
  │                        then pull it, otherwise send a text note with the reference
  → classify by mime into image/audio/video/file, compare against Connector.capabilities.media_out
  → convert if necessary (image compression/transcoding, split when over limit)
  → Connector.upload + send_media
```

- Only send files that "the tool explicitly produced as media"; by default do **not** send out all changed files of `step.ended.files`
  (to avoid spamming); if needed, configure `media.outbound.sources: [tool_media, changed_files]` and add filtering.
- When sending media, preserve the Markdown "image/link" semantics in the text or add a brief note, to improve readability.

### 4.6 HITL: permission / question → IM card

**What is an "IM card"**: each platform's **interactive message with buttons / structured content** (WeCom template card, Feishu interactive card,
QQ keyboard). HITL uses it to turn the agent's "allow or not / which one to choose" into **one-click buttons**, closing the loop in IM for a turn
that would otherwise park.

```
Permission card: ⚠️ Tool bash requests to execute: rm -rf build/
         [ Allow once ]  [ Always allow ]  [ Deny ]

Question card: Please select a deployment environment:
         [ Dev ]  [ Staging ]  [ Prod ]      (if multiple, allow multi-select)
```

- Click → the platform's **card callback** → the Connector throws it to the core layer → `…/permission/{rid}/reply` or
  `…/question/{rid}/reply` (the button `value` encodes `{kind, sid, rid, …}`; the clicker's identity is carried by the callback).
- Two uses of cards: **interaction** (this section: buttons) and **updatable** (§6.1/§6.7: stream-refresh the same card).
- Channels without cards (WeChat personal) degrade to **numbered options + text** (see "channels without button capability" below).

agentd is in hold mode (`server.New` calls `HoldInteractions(true)`), and dangerous tools park waiting for a
reply. The bridge must close the loop, otherwise the turn blocks forever (`docs/DESIGN-HTTP.md` §9).

**Permission `permission.v2.asked`** (live-only) data:
`{id, sessionID, action, resources, save, metadata, source}`.

**Question `question.v2.asked`** (live-only) data:
`{id, sessionID, questions:[{question,header,options:[{label,description}],multiple,custom}], tool}`.

Bridge flow:

```
permission.v2.asked
  → look up Route(sessionID) → Conversation
  → first pass the bridge-side policy (permissions.auto):
       auto=once/always → POST /reply directly, without disturbing the user
       auto=reject      → POST /reply reject directly
       auto=ask         → render the card, wait for the user to click
  → the card button value encodes {kind:"permission", sid, rid, reply:"once|always|reject"}
  → the user clicks → platform card callback event → Connector throws IncomingInteraction
      → core layer POST /api/session/{sid}/permission/{rid}/reply
```

- **Channels without button capability (e.g. WeChat personal)**: render as numbered options + text interaction; write the request into
  `Route.pending_interactions` (§3.6), and when the user sends their next message, parse it by **insertion-order numbering** and reply; handle timeouts by policy.
- **Question reply**: `POST …/question/{rid}/reply` body `{"answers": [[label,…], …]}` (one list of labels per question,
  in the order of `questions`); or `…/reject`. Multi-select (`multiple`) uses multi-button/multi-select cards.
- **In-group authorization (§2.5(3))**: the card takes effect only when the **authorization rule** of `pending_interactions[rid]` allows it —
  `scope=initiator`→only `owner`; `participants`→group members; `admins`→`group.admins`. Clicks by other members are
  **ignored with a one-line notice**, and never release a dangerous operation on behalf of the initiator. Direct chats are always the person themself.
- **Timeout**: agentd's `interactionTimeout`/`interactionFallback` is the last line of defense; the bridge itself also sets
  `permissions.timeout_s`, and on timeout gives up by default (reject) and notifies the user.
- **Interrupt coordination**: `/interrupt` does not release an already-parked permission (it can only release a question), so
  `/stop` on the bridge side should: `POST /interrupt` **and**, for each pending permission,
  `POST …/permission/{rid}/reply {reply:"reject"}` (the README side corresponds to `rejectPending`).

### 4.7 Errors and interrupts

- HTTP errors are dispatched by `error` code: `bad_request(400)`, `unauthorized(401)`, `forbidden(403)`,
  `not_found(404)`, `conflict(409)` (e.g. compact while a turn is running), `unavailable(503)` (
  coordinator stopped / snapshot unavailable), `internal(500)` (contains `ref`; show the user "internal error, please retry later").
- `session.next.step.failed` (durable) → render as an error prompt; if `error.type=="provider"`,
  agentd's default `dropErroredTurns:true` removes that turn from the subsequent context (to avoid getting stuck).
- `session.status.retry` → prompt "model retrying (#N)", without exposing provider details.

### 4.8 Bot identity and group context injection (implementation of §2.6)

The agent only has the prompt-text entry point; identity/group info is injected into the prompt text as a **context preamble** (not a system
message). Assembly order (`PromptComposer`):

```
<bridge-context>
channel: wecom
bot_name: Assistant
bot_aliases: [Assistant]
bot_description: Enterprise R&D assistant: read code, run commands, answer questions.
agent: build                     # current agent id
conversation: group:dev-team
participants: Alice, Bob          # optional, only when sync_participants
</bridge-context>
[Alice]: help me look at this bug # group chat injects a speaker label; direct chat omits the label and is just the user text
```

- **Identity alignment (§2.6)**: `bot_name`/`bot_description` take the side specified by `identity.source`
  (`im` default / `agent` / `config`); when the description is absent, fall back to the current agent's `description` (from
  `GET /api/agent`). When the IM profile and the agent `description` are inconsistent, log a warning (an operational signal).
- **Anti-forgery**: sanitize the `<bridge-context>` marker and the line-leading `[{name}]:` prefix from user text (§2.5(1)).
- **Injection strategy** `identity.inject`:
  - `once`: inject once in the session's first prompt;
  - `on_change` (default): inject in the next message when `context_dirty` (name/description change, agent switch, after compaction);
  - `always`: inject in every message (most robust, slightly more tokens).
- **prompt idempotency**: injection does not change `prompt.id` (still `channel:message_id`), and does not produce an extra turn.
- **Group members**: `participants` is **not injected** by default (privacy and size); include it only when `sync_participants: true`
  and the platform supports it.
- **After compaction/switching**: compaction summarizes the preamble away, and switching agent changes the identity; both set `context_dirty`,
  and the next injection refreshes it, ensuring the identity remains valid.

---

## 5. IM-side adaptation

> Each section describes platform **facts** (connection/send-receive/media/card APIs). These facts land in `Capabilities` (§3.3) and
> `Connector.identity()` (§2.6); inbound events map to §3.2's `InboundMessage` / `IncomingInteraction`
> / `ConnectorEvent`. Unconfirmed items are marked **pending integration testing** (§13.1).

### 5.1 WeCom smart robot (MVP) — long connection

Based on `wecom-aibot-python-sdk` (`aibot`) and the official "Smart Robot Long Connection" documentation:

- Client: `WSClient(WSClientOptions(bot_id, secret))`; events `message.text/image/mixed/voice/file`,
  `event.enter_chat`, `event.template_card_event`, `event.feedback_event`; connection events
  `authenticated/connected/disconnected/reconnecting/error`.
- Outbound:
  - Streaming text: `await reply_stream(frame, stream_id, content, finish=False, msg_item=None,
    feedback=None)`; **multiple calls** push updates, the last with `finish=True`. Markdown is rendered by the bot.
  - Mixed text and images: `msg_item` (only effective when `finish=True`).
  - Cards: `reply_template_card(frame, card, feedback=None)`, `update_template_card(...)`,
    `reply_stream_with_card(...)` (streaming + card combination).
  - Proactive push: `send_message(chatid, body)`, `body.msgtype ∈ {markdown, template_card,
    file, image, voice, video}` — no callback frame needed, suitable for async task notifications.
  - Welcome message: `reply_welcome(frame, body)` (within 5s of the enter-session event).
- Inbound media: `await download_file(url, aes_key)` (built-in AES-256-CBC decryption) → `(bytes, filename)`;
  `aeskey` is taken from `body.image.aeskey` / `body.file.aeskey` / `body.voice.aeskey`.
- Outbound media: materials need **chunked upload** (upload init → upload chunk → upload finish); send by type using
  image/file/voice/video messages.
- Reply queue: replies to the same `req_id` are sent serially, naturally avoiding out-of-order.
- **Bot identity (platform limitation)**: the long-connection callback carries only `aibotid` (the BotID); the
  platform never sends the bot's name or description (confirmed from the official callback schema and captured
  frames). So `identity.display_name` / `identity.description` are **required** when WeCom is enabled (§2.6); the
  name is not inferred from an inline `@name` in the message text.
- **Delivery semantics (documented)**: direct-chat messages are always called back; **group-chat messages are called back only when the bot is @-mentioned** (`group_delivery:
  mention_only`, `direct_delivery: always`). Entering a session requires `reply_welcome` within 5s. The
  specific API signatures for streaming/cards and the material chunked-upload flow are **pending integration testing**.
- **Inbound events → §3.2**: `message.*` → `InboundMessage`; `event.template_card_event` →
  `IncomingInteraction`; `event.enter_chat` / `event.feedback_event` → `ConnectorEvent`
  (`enter_chat` triggers `reply_welcome`).

**WeCom streaming timing (bridge perspective)**:

```
user @-mentions the bot ──► on('message.text')
  bridge: Router→session; MediaIngest; prompt()
  bridge: stream_id = generate_req_id('stream')
  loop (every flush interval): reply_stream(frame, stream_id, current Markdown, finish=False)
  turn idle: reply_stream(frame, stream_id, full Markdown, finish=True, msg_item=[media…])
  if there is a permission mid-turn: reply_stream_with_card(frame, stream_id, text, False, template_card=permission card)
```

**Passive-reply window (integration item)**: `reply_stream` / `reply_template_card` are *passive
replies* bound to the callback's `req_id`. `reply_welcome` / `update_template_card` are documented
as 5-second windows; whether `reply_stream` stays valid for the whole streamed turn (which may
exceed 5s) must be confirmed on a real device (see §13.1). If a late `finish=True` frame is
rejected, the bridge falls back to sending the answer as a new message (no turn is left stuck).
A conversation with no inbound frame (a purely proactive push) cannot stream: the connector
reports it as non-streamable (`IMConnector.supports_streaming`) and the bridge sends a single
complete message instead.

### 5.2 Feishu

Based on `feishu-bot-sdk`:

- Connection: `FeishuBotServer(app_id, app_secret)` long connection; `@server.on_im_message_receive`.
- Outbound: `MessageService.send_text/send_image/send_markdown`, interactive cards; cards can be
  `patch`ed (edited) → mapped to `Capabilities.edit_message=True`, with streaming simulated by "send the card first, then patch"
  (`native_stream=False`).
- Media: `MediaService.upload_image` / file upload and download; rich-text `post` structure.
- **Inbound interaction**: card button callback (`card.action.trigger`, with `operator`) → `IncomingInteraction`
  (§3.2/§4.6); `on_im_message_receive` → `InboundMessage`.
- Note: when multiple instances are online at the same time, events are **randomly delivered** to one of them (not broadcast) — the bridge should be as single-instance as possible, or de-duplicate
  the same event (`message_id`).
- **Delivery semantics**: the push rules for p2p and group chat (whether group chat is @-only, whether it is affected by the `im.message.receive_v1` permission/settings
  ) are **pending integration testing confirmation**; before confirmation, handle per the most conservative `group_delivery: mention_only`.

### 5.3 QQ (botpy)

Based on `qq-botpy` and the QQ Bot Open Platform API v2:

- Client: inherit `botpy.Client`, implement `on_at_message_create` (channel),
  `on_group_at_message_create` (group), `on_c2c_message_create` (direct message); `Intents` declares the channels.
- Outbound: `message.reply(...)`, `self.api.post_message(channel_id/group_openid, content,
  msg_type, media, msg_id, msg_seq)`; Markdown needs `msg_type=2` etc. (HTML/Markdown capability is limited by the platform).
- Media: first upload the rich media (image/video/audio/file), then `post_message` references `file_info`.
- Auth: `AppID + AppSecret`.
- **Inbound events → §3.2**: `on_*_message_create` → `InboundMessage`; keyboard/interaction callback →
  `IncomingInteraction` (event name pending integration testing).
- **Delivery semantics (inferred from event names)**: group/channel @-only (`on_group_at_message_create` / `on_at_message_create`
  ⇒ `group_delivery: mention_only`), direct message `on_c2c_message_create` (`direct_delivery: always`);
  **event names, parameters, and `msg_type` values are pending integration testing confirmation**.

### 5.4 WeChat personal (wechatbot.dev)

Based on `wechatbot-sdk`:

- `WeChatBot` + `@bot.on_message`; `msg.type ∈ {text,image,voice,file,video}`;
  `msg.images/voices/files/videos`; `reply/send/send_typing`; AES-128-ECB encryption.
- No Markdown, no buttons, no editing → `Capabilities` fully degraded: text purification, cards become numbered options,
  streaming degrades to "one-shot send".
- This channel has poor compliance risk and stability, and is listed as the last to integrate.
- **Inbound interaction**: no buttons → **no `IncomingInteraction`**; HITL uses "numbered options + text fallback" (§4.6).
- **Delivery semantics**: messages visible to the logged-in account; the specific delivery scope of `on_message`, group-chat behavior, and rate limiting are **pending integration testing confirmation**
  (before confirmation, handle per the most conservative setting; use in groups must have the compliance risk assessed).

### 5.5 New platform checklist (extensibility acceptance)

Adding a new platform only requires:

1. `connectors/<name>/connector.py` implementing `IMConnector` (connection/send-receive/media/card).
2. `connectors/<name>/capabilities.py` declaring capabilities.
3. If a special Markdown form is needed, add a `render/profiles/<name>.py` (otherwise reuse the default profile).
4. `pyproject.toml` adds an optional extra depending on that platform SDK.
5. Register into the `connector registry` (entry point or explicit table).

Core engine zero changes.

---

## 6. User Experience Design (Focus I)

### 6.1 Streaming Strategy (automatically selected by capability)

When `streaming.mode: auto`, the decision is made based on `Capabilities`:

| Capability | Strategy |
|---|---|
| `native_stream` (WeCom) | Use the platform streaming API to update the same message until `finish` |
| `edit_message` (Feishu card) | Create a message/card and patch it on the throttling cycle |
| Only `typing` + not editable | Send a typing status, and send **all at once** after the turn ends |
| Cannot native_stream/edit (WeChat personal) | Send → end; use only typing (if supported) |

### 6.2 Throttling and Aggregation `StreamingController`

**Premise**: IM's "streaming" is not sending deltas, but **repeatedly updating the same message (sending a full snapshot)** — WeCom `reply_stream`
passes the full content each time, and Feishu card patch replaces the content. So throttling = controlling **the frequency and merging of snapshot updates**.

**Algorithm** (one controller per route: trailing-edge + drop-if-busy + boundary/final flush):

- `buf` accumulates all received deltas; each frame sends only the **current full snapshot** (not an increment).
- **Minimum interval** `streaming.min_interval_ms` (default 700ms): two updates are at least this far apart; multiple
  deltas within the interval are merged into one.
- **drop-if-busy**: when the previous update is still in flight, do not queue and do not run concurrently; just set `dirty`, and send one more frame after it returns ⇒ the send
  rate is naturally ≤ `1/interval`, so nothing piles up on slow networks.
- **Early boundary flush** (`streaming.boundary_flush`): paragraph/sentence/code-block boundaries (`\n\n`, period, ``` closing)
  can be sent immediately, giving a more natural feel.
- **Final flush**: on `text.ended` / `session.status=idle` / error / interruption, cancel the timer and send the final snapshot
  (`finish=true`).
- **Adaptive backoff**: on a 429 / rate limit hit → interval ×`streaming.rate_limit_backoff` (cap e.g. 5s); revert after consecutive successes.
- **Single snapshot**: the text stream and the reasoning stream **share the same snapshot** (reasoning block + body), updating together in one frame, avoiding two
  sends in the same tick.
- **Non-editable channels** (QQ/WeChat personal) do not stream: they send only an initial placeholder frame + the final frame.

```python
class StreamingController:
    def push(self, delta: str):
        self.buf += delta
        self.dirty = True
        if self.timer is None:  # trailing-edge
            self.timer = schedule(max(0, self.interval - (now - self.last)), self._flush)

    async def _flush(self):
        self.timer = None
        if self.inflight or not self.dirty:
            return  # drop-if-busy
        self.dirty = False
        self.inflight = True
        try:
            await self.connector.update(self.ref, self.render(self.buf))  # full snapshot
            self.last = now
        finally:
            self.inflight = False
        if self.dirty:
            self.timer = schedule(self.interval, self._flush)  # make-up send
```

- Silent window of a long turn: when there is no new delta for `streaming.idle_progress_ms` (e.g. 2s) and the turn has not ended → send a progress hint
  (e.g. "running `read`…"), so the user does not think it is stuck.
- The per-**snapshot** limit is `streaming.max_live_chars`; once reached, chunking begins (§6.5), and each final message is still bound by
  `Capabilities.max_text_chars`.

### 6.3 Canonical Carrier and Outbound Plan

- Canonical carrier = `RichDoc`: **Markdown** (`markdown`) + reasoning (`reasoning`) + usage (`usage`) + media
  (`media`) + interaction (`interactive`) (§3.5).
- `Renderer` produces `OutboundPlan.segments`: text segments / media segments / card segments sent in order.
- The output of one turn may be split into multiple messages (see §6.5), but the order and the reply relationship must be preserved.

### 6.4 Markdown Normalization and Degradation

Parse into a token stream with `markdown-it-py`, then degrade level by level according to `MarkdownLevel`:

| Element | RICH | STANDARD | BASIC | NONE |
|---|---|---|---|---|
| Heading | `#` heading | `**bold**` on its own line | bold | uppercase/prefix |
| Table | as-is | convert to monospace text (aligned columns) | convert to a "column: value" list | plain text |
| Code block | ``` code block | ``` code block | ``` or `inline` | indented plain text |
| List | as-is | as-is | `-`/`1.` as-is or plain text | `-`/number |
| Quote | `>` | `>` | wrapped in 「」 | none |
| Link | `[text](url)` | as-is | as-is | `text (url)` |
| Image | standalone image message | standalone image message | standalone image message | send image after download/give a link |
| Inline formatting | as-is | as-is | as-is | removed |

Key points:

- **Images are generally not inlined in Markdown** (most IMs cannot render remote images); they are uniformly extracted into **standalone media segments**.
- **Tables** are the most common degradation point: on non-RICH channels they are converted to aligned plain text to avoid garbling.
- Code blocks must be closed and must not cross the IM's message length limit.
- All degradation performs only "information-preserving" transformations and deletes no content.

### 6.5 Long Text / Long Card Chunking

- The per-message limit is `Capabilities.max_text_chars` (e.g. 4000/4096). When exceeded, split at **semantic boundaries**:
  paragraphs first → code-block boundaries → sentences → hard split, and add a `(1/3)` sequence number.
- WeCom `reply_stream`'s final frame carries `msg_item` media; if the total length exceeds the limit, stream the body first, then send the media message afterward.
- Chunks preserve the reply relationship to avoid cross-thread confusion.

### 6.6 Interactive Controls and Commands

- **HITL card**: see §4.6.
- **The only command `/stop`** (prefix configurable via `commands.prefix`, default `/`): cancels the currently executing Turn
  (`POST …/interrupt` + reject pending permissions), intercepted **locally** by the bridge and not forwarded to the model. Within a group, by default only
  **the initiator of that Turn** (`command_scope: initiator`) is allowed; only when set to `admins` does it also include the configured admins
  (`group.admins`). A one-on-one chat means the person themself.
  In a group chat, if the platform only delivers @ messages, `/stop` naturally also requires an @ trigger (see §2.5).
- **No Conversation lifecycle commands are provided**: there is no `/new`, `/reset`, `/compact`, `/agent`, `/model`, `/status`,
  `/help` — in IM, "one Conversation is one agent session"; context growth is left to agentd's automatic compaction; switching
  agent/model is **operations** work handled through deployment configuration, not switched in the chat.

### 6.7 Runtime Status and Usage Display

**Goal**: give a real-time feel of "reasoning / progress / usage" like chat, but restrained for group chats (rate limits, screen flooding, CoT leakage).

**Within a Turn**:
- On receiving a message, immediately reply with a placeholder "🤔 Thinking…" (or typing/👀, depending on capability) — to avoid a feeling of waiting.
- Tool execution: when `show_tools: true`, merge consecutive calls into a lightweight line "🔧 Using `<tool>`", without flooding the screen.
- Retry: `session.status.retry` → "Model busy, retrying (N)".
- Compaction: `compaction.started/ended` → "Organizing context…".
- Long silence: no output for more than `idle_progress_ms` → progress hint (see §6.2).

**Reasoning process (`streaming.show_reasoning`, default `false`)**:
- Source: `session.next.reasoning.started/delta/ended` (delta is **live-only** and cannot be replayed after a disconnect).
- Form `streaming.reasoning_style`: `collapsible` (default; Feishu card collapsible panel; WeCom first sends a refreshable
  "thinking" message, then freezes/collapses it after it ends) / `separate` (a standalone "thinking" message, collapsed after it ends) / `inline`.
- **Throttling is the same as §6.2**; **off by default for group chats** (rate limits + discourage exposing the raw chain of thought); one-on-one chats may be relaxed to direct display.

**Usage/context (`streaming.show_usage`, default `true`)**:
- Source: `session.next.step.ended`'s `tokens{input,output,reasoning,cache}` and `cost`; context ≈
  the latest step's `tokens.input` compared against the context window reported by `GET /api/model`
  (`contextLimit`; the `model.context_limit` setting in §9 is an optional override, see §19).
- At the end of a Turn, append **one line** at the end: `📊 context 12.3k/128k (10%) · this turn in 1.2k/out 456 · $0.003`.
- In a group Conversation, usage is the **cumulative total of the whole Conversation** (not of an individual).

**Channel feasibility**:

| Capability | WeCom | Feishu | QQ | WeChat personal |
|---|---|---|---|---|
| Usage line (append one line at the end) | ✔ | ✔ | ✔ | ✔ |
| Live refresh of the same message | ✔ `reply_stream` | ✔ card patch | ✖ | ✖ |
| Live reasoning process | ✔ (throttled) | ✔ | only a "Thinking…" placeholder | placeholder only |

**Channel degradation** (QQ/WeChat personal, which do not support refresh):
```
you  @bot …
bot  🤔 Thinking…                       ← placeholder only, cannot update
bot  <final answer + 📊 usage line>           ← sent all at once after it ends; does not show the reasoning process
```
- End: clear typing, and send a `✅` emoji when necessary.

### 6.8 Group Chat Etiquette (Multi-user)

(For the semantic definition see §2.5; here are the experience-oriented details.)

- Parse and **strip** the @ mention of the bot from `mentions`, to avoid treating "@bot" as part of the prompt; **other members**
  who are @-mentioned are preserved as `@{name}` according to configuration, to help the agent understand the reference.
- **Make clear "who is being answered"**: when replying, @ the initiator (if capability allows) or quote their message; this matters especially when multiple users ask in succession.
- **No cross-user steer** (§2.5(2)): B's messages are not injected into A's Turn; when the queue backs up, hint "there are N more ahead".
- **Permission/command boundaries**: by default only the initiator can click the HITL card (`group.hitl_scope: initiator`); the only `/stop`
  command is by default limited to that Turn's **initiator** (`group.command_scope: initiator`; configurable to `admins`), see §6.6.
- **Speaker-tag anti-forgery**: the `[{name}]:` tag injected into a group shared Conversation is generated by the bridge, which also cleans up forged
  prefixes of the same kind in the body, to prevent users from impersonating others' instructions.

---

## 7. Files and Media (Focus II)

### 7.1 Unified Media Pipeline

```
inbound:  Connector.download(att) ──► MediaBytes ──► MediaIngest(§4.4) ──► prompt.files[]
outbound: the file part of event/message ──► MediaCollector(§4.5) ──► convert ──► Connector.upload + send
```

- Media type normalization: `image / audio / video / file` (voice is normalized to audio).
- **Capability intersection**: inbound = `Connector.media_in` (what the platform can provide) ∩ the target model's `input` (what the model can receive);
  outbound = `Connector.media_out` (what the platform can send) ∩ the media types produced by the agent.
- **When a capability is missing on either side**: degrade gracefully (convert to a link/filename/spool path), never silently drop; inbound loss is also notified by
  the `session.next.attachment.omitted` event.

### 7.2 Inbound (IM → Agent)

See the §4.4 decision tree. Core points:

- Prefer `inline` (small files, modality supported); large files go via `file` (requires the agentd `MediaUploader`); when a publicly reachable
  URL exists use `url`; if none fits, spool to a **controlled subdirectory inside the working directory** and note it in the prompt text (details in §4.4).
- Make `mime` as precise as possible (as given by the platform or sniffed by extension/magic); sanitize `name`.
- Voice: if the model does not support audio, it can be spooled first; a speech-to-text subagent could also be connected in the future (not MVP).

### 7.3 Outbound (Agent → IM)

See §4.5. Core points:

- Send only media **explicitly produced by the agent** (tool file parts); by default do not send all changed files.
- `file` (a provider reference) cannot be downloaded directly → by default send an explanation; a provider downloader can optionally be configured.
- Image exceeds the IM limit: compress/scale with Pillow; video/audio over the limit: reject and give a link (optional ffmpeg transcoding).
- Attach a human-readable description to each piece of media when possible.

### 7.4 Format / Size / Transcoding Strategy

| Item | Strategy |
|---|---|
| Image | Keep the original; compress when over the limit (JPEG/WebP); transparent PNG depends on channel support |
| Audio | Prefer the platform-native format (e.g. amr/silk/mp3); give a link if unsupported |
| Video | Upload directly; no transcoding when over the limit (unless ffmpeg is configured) |
| Text file | Send as a file; if the content is short and the channel supports it, an inline code block is allowed |
| MIME sniffing | Prefer platform metadata, then `filetype`/extension |

### 7.5 Storage and Lifecycle

- The spool directory is by default **inside the working directory** (`<working_dir>/.tether/spool`), and filenames are `<sha256 first 8>_<safe_name>`.
- Inbound temporary files are cleaned up according to a **TTL (counted from creation, fairly long by default and configurable)**, and are guaranteed to be **readable within the current Conversation** (the spool path
  is written into the prompt for the agent to `read`, and cleaning up too early would make the read fail); a longer retention period also helps replay/debugging.
- The IM asset handle for outbound uploads (`MediaHandle`) is discarded after use and is not cached long-term.
- **Dedup cache (optional)**: provider uploads / IM assets can be reused via a short-term cache keyed by **content hash** (the same file sent multiple times is uploaded
  only once); it has an expiry and expires together with the media TTL.
- Local disk is not used as a cryptographic boundary; sensitive media follows §10.

### 7.6 Media Security

- **Path traversal**: spool filenames are strictly sanitized; `..`/absolute paths/separator injection are forbidden.
- **SSRF**: when the bridge fetches an outbound `url` source, restrict the protocol to http(s), guard against private-network/DNS rebinding, and
  limit size and timeout (optional switch; "bridge-proxied fetch" is off by default).
- **Size limit**: both inbound download and outbound fetch have `max_bytes` (default e.g. 50MB); over the limit they are rejected with a notice.
- **Content type**: do not trust the MIME declared by the platform; sniff when necessary; do not send executable files outbound (configurable extension blacklist).

### 7.7 Download/Upload Capabilities of Each IM (preliminary; `pending integration testing` items backfilled per §13.1)

| Platform | Download (IM→bridge) | Upload (bridge→IM) | Notes |
|---|---|---|---|
| WeCom intelligent bot | ✔ `download_file(url, aes_key)` (built-in AES-256-CBC decryption) | ✔ asset **chunked upload** (init/chunk/finish) + image/file/voice/video messages | aeskey is independent per media; the chunked flow is **pending integration testing** |
| Feishu | ✔ message resource download API (requires auth, `image_key`/`file_key`) | ✔ `MediaService.upload_image` / file upload | goes through `im/v1/...`, requires a permission scope; fields **pending integration testing** |
| QQ (botpy) | △ the event gives a **URL**; the bridge fetches it itself (may have a time limit/require auth) | ✔ rich media upload (image/video/audio/file) → `post_message` references `file_info` | URL validity period/auth **pending integration testing** |
| WeChat personal | △ the event gives a media URL; the bridge fetches it | ✔ `send` / media send | no official API; stability/compliance **pending integration testing** |

- All four platforms provide both "download + upload", in different forms: WeCom/Feishu have official methods (including decryption/auth), while QQ/WeChat personal
  are mostly "given a URL to fetch yourself + a rich media upload interface".
- The differences are **encapsulated** by `IMConnector.download` / `IMConnector.upload` (§3.1), and the core layer is unaware of them.
- **Do not confuse**: the `fileId` of a `file` source belongs to the **model provider** (§4.4's ②), while sending media outbound uses an **IM asset handle** (③).
- **Download security**: prefer the SDK's built-in methods; when fetching yourself, apply SSRF/size/timeout protection (§7.6).

---

## 8. Reliability and Concurrency

### 8.1 Serial per Conversation, Concurrent Across Conversations

- One Route → one Agent Session; the SDK is naturally serial for the same session, so the bridge needs no extra lock.
- Turns of different Routes are processed concurrently (asyncio tasks).
- Two consecutive messages on the same Route: `queue` by default (the second is queued and executed in order on the SDK side).
- **One-on-one chat**: `sessions.busy_delivery: steer` can be configured (inject supplementary info from the same user into the current Turn).
- **Group chat multi-user** (§2.5(2)): `group.cross_user_delivery: queue` by default — **no cross-user steer**,
  otherwise B's messages would pollute A's Turn. Within a group Route, all users' messages are queued FIFO;
  steer only happens when it is `steer_same_user` and the sender equals `active_turn_sender`.
- `Route.queue_depth` is a **bridge-side measure** (the number of prompts submitted to the server whose Turn has not ended; the server's internal
  queue is not visible), used to give the "there are N more ahead" hint.

### 8.2 Idempotency and Deduplication

- **Inbound dedup**: deduplicate by `(Conversation.key, message_id)` in the `dedup.ttl_s` (§9) cache (platform redelivery) — use the Conversation key rather than
  only `channel`, to avoid message-id collisions across Conversations.
- **Prompt idempotency**: set `id` to `f"{Conversation.key}:{message_id}"`; agentd silently
  deduplicates repeated `id`s, avoiding a retry causing a second Turn.
- **Card callback dedup**: the button value carries `rid`, making repeated clicks idempotent (after one successful reply, subsequent ones are ignored).

### 8.3 Reconnection, SSE Resumption, State Recovery

- The Connector layer handles reconnection to the IM platform (most SDKs have built-in exponential backoff).
- AgentClient's SSE: reconnect with exponential backoff after a disconnect; on reconnect perform **reconciliation**:
  1. `GET /api/session/active` → find the Conversations still running;
  2. For each active Route: fetch the final text and tool media via `GET /api/session/{sid}/message`, and resend when necessary;
  3. **Finish half-done work**: if that route's streaming message stopped midway, send it a `finish` snapshot with the final text from step 2;
  4. `GET /api/permission` / `GET /api/question` → restore pending HITL.
- SSE overflow (`event: error` + `subscriber_overflow`) → log it and run the reconciliation flow.
- **Session recovery (lost agentd state)**: the IM↔session mapping is persisted by the bridge (`routes`), keyed by `Conversation.key`; agentd holds only session ids. If agentd is restarted with a **fresh state directory**, a persisted `session_id` no longer exists. On the **first use of a loaded route** (`sessions.validate_session`), the bridge verifies it with `GET /api/session/{id}` and, on `not_found`, creates a new session for the same `Conversation.key` and updates the route (re-injecting identity). A `not_found` on `prompt` is also recovered reactively, covering a session lost mid-run. This keeps a conversation working instead of failing permanently.

### 8.4 Backpressure and Rate Limiting

- One token bucket per Conversation; the rate is the smaller of `Capabilities.rate_limit_per_min` and the local configuration.
- The send queue is bounded; send throttling and backpressure are implemented by §6.2's drop-if-busy (keep only the latest snapshot, keep the final frame), never
  blocking event consumption.
- In the event loop shared by multiple Connectors, any blocking call (the SDK's internal HTTP) should be executed in a thread pool or native async
  to avoid dragging down event consumption.

### 8.5 Graceful Shutdown

- On receiving SIGINT/SIGTERM: stop accepting new messages → for in-progress Turns, **by default leave them running on agentd** (stop streaming only) so a restart can resume them; with `sessions.interrupt_on_shutdown: true` instead interrupt and reject their pending permissions
  → flush unsent final messages (only in interrupt mode) → close the SSE and Connector connections → flush `Route` state not yet persisted to disk. A parked interaction is **not** consumed by default, so clicking its card after a restart still works (the resumed turn is re-attached).
- Decoupled from agentd's lifecycle: the bridge **does not fork/manage** agentd processes; when multiple instances are needed, the **host side's
  `supervisor`/orchestrator** creates and reclaims them (the bridge calls through `ProjectProvider`, §3.7); agentd shuts down gracefully on its own
  (`docs/DESIGN-HTTP.md` §12.5).

### 8.6 Message Recall (best-effort, platform-dependent)

Recalling/withdrawing a message is **not** a normal inbound item, and whether the bridge learns about it is entirely up to the platform:

- **Where the platform emits a recall event** (e.g. Feishu `im.message.recalled_v1`), the Connector maps it to
  `ConnectorEvent(kind="recall")` carrying the recalled `message_id`. The core then resolves the prompt id
  `f"{Conversation.key}:{message_id}"` (§8.2) and:
  - Turn still **queued** (not started) → drop it from the queue;
  - Turn **in flight** → best-effort `POST /api/session/{sid}/interrupt` (policy-configurable; default interrupt);
  - Turn **already answered** → no-op (a reply already sent cannot be retracted on most platforms — no "unsend" is attempted).
- **Where the platform emits no recall event** — notably the WeCom smart-robot long connection (its callback only delivers
  `message.text/image/mixed/voice/file` plus `enter_chat`/`template_card_event`/`feedback_event`) — recalling a message is a
  **no-op**: the bridge never sees it, so an in-flight turn keeps running and any reply already produced stands.

Rationale: recall is inherently best-effort; the bridge cannot delete its own outbound messages, so it only cancels work that has not yet been committed.

---

## 9. Configuration

Use `pydantic-settings` + YAML (`config.yaml`; `config.example.yaml` is provided with the repository).
Secrets are injected only from environment variables / `.env`, and **are not written in plaintext into YAML** (unlike `DESIGN-HTTP.md`'s "no env, secrets only in files":
here it is a Python host, adopting 12-factor env injection, and YAML holds only non-secret configuration).

```yaml
server:
  base_url: http://127.0.0.1:8787
  token: ${AGENTSERVE_TOKEN:-}       # ${VAR} / ${VAR:-default} expanded from the environment
  request_timeout_s: 30
  sse_reconnect_ms: 1000
  # Multiple backends (optional): one instance = one project; writable agents need to be assigned to different instances per group (§2.8)
  pool: []                            # [{name, base_url, token, working_directory, default_agent}]

agent:
  default_agent: null                 # optional override; unset = first agent exposed by GET /api/agent (agentd's default)
  default_model: null                 # optional override; unset = agentd defaultModel (discovered, not restated)
  writable:                           # optional override of the tool-set read/write determination (§2.8)
    plan: false                       # e.g. read-only agent

model:
  context_limit: null                 # optional override; by default the window comes from GET /api/model (`contextLimit`)

# Project isolation (§2.8 / §2.9)
projects:
  isolation: auto                     # auto | shared | per_conversation
  provider: pool                      # shared | pool | worktree | overlay | container | remote (§3.7)
  on_conflict: isolate                # isolate | reject — when a writable agent lands on a shared project
  base_dir: /var/lib/tether/workspaces
  ttl_s: 3600                         # idle lease reclamation
  max_leases: 32                      # concurrent lease limit (disk/memory protection)
  # worktree provider (§2.9(2))
  git_base_ref: origin/HEAD           # starting point: detached or im/<group> branch
  supervisor_command: null            # command to launch agentd per project; unset = external registry mode
  # overlay / CoW provider (§2.9(4))
  cow:
    mode: auto                        # auto | overlayfs | reflink | clonefile
    base_readonly: true               # base read-only (prevents write-through; prerequisite of the link-farm approach)
  # container provider (§2.9(3))
  container:
    runtime: docker                   # docker | podman | k8s
    image: ghcr.io/jiaweisky/agentd:latest
    network: none                     # none | allowlist:<name>
    cpus: "2"
    memory: 2g
    read_only_root: true

sessions:
  idle_reset_s: 0                     # when >0, automatically reset the Conversation when idle
  busy_delivery: queue                # queue | steer — when supplementary messages arrive while the same user's Turn is running (§8.1)
  max_active_routes: 1000
  validate_session: true              # on the first message after a restart, verify a loaded route's session still exists; recreate it if gone (§8.3)
  interrupt_on_shutdown: false        # false = leave in-progress turns/parked interactions to agentd (restart-resumable, §8.5)

dedup:
  ttl_s: 600                          # TTL of the inbound message / card callback dedup cache (§8.2)

group:                                # group chat multi-user semantics (§2.5)
  inject_speaker: true                # inject the "[name]: " speaker tag in a group shared Conversation
  speaker_format: "[{name}]: {text}"
  mention_others: true                # keep other @-mentioned members as @{name}
  reply_with_mention: true            # @ the initiator when replying
  cross_user_delivery: queue          # queue | steer_same_user
  admins: []                          # allowlist of group admin user ids (platforms mostly do not provide roles, §2.5(3))
  hitl_scope: initiator               # initiator | participants | admins (admins = the list above)
  command_scope: initiator            # initiator | admins — who may execute /stop (§6.6)
  queue_backup_hint: true             # hint "there are N more ahead" when the queue backs up

# Bot identity synchronization (§2.6 / §4.8)
identity:
  inject: on_change                   # once | always | on_change
  source: im                          # im (IM profile takes priority) | agent | config
  display_name: null                  # bot name: REQUIRED when WeCom is enabled; optional override elsewhere
  description: null                   # bot description: REQUIRED when WeCom is enabled; optional override elsewhere
  warn_on_mismatch: true              # warn when the IM profile and the agent description disagree
  sync_participants: false            # whether to also inject group members (privacy/size)
  preamble_tag: bridge-context        # context wrapping tag (for anti-forgery cleaning)

streaming:
  mode: auto                          # auto|native|edit|chunk|final
  min_interval_ms: 700                # minimum interval between two snapshot updates (§6.2)
  idle_progress_ms: 2000              # how long to stay silent before sending a progress hint
  boundary_flush: true                # flush early at paragraph/code-block boundaries
  max_live_chars: 4000                # per-snapshot limit (chunk when exceeded, §6.5)
  rate_limit_backoff: 2.0             # interval multiplier under rate limiting (§6.2)
  show_tools: true
  show_reasoning: false               # off by default for group chats (rate limits + discourage exposing the chain of thought)
  reasoning_style: collapsible        # collapsible | separate | inline
  show_usage: true                    # append one line of "context / this turn's tokens / cost" at the end
  max_chars_override: null            # override max_text_chars from Capabilities

media:
  inline_limit_bytes: 10485760        # 10MB
  max_bytes: 52428800                 # inbound download / outbound fetch limit (50MB, §7.6)
  spool_dir: "{working_dir}/.tether/spool"   # inside the working directory by default (reachable by agent read, §4.4/§10.4)
  fetch_url_outbound: false           # whether to allow the bridge to proxy-fetch url sources (includes SSRF protection)
  outbound:
    sources: [tool_media]             # tool_media | changed_files
    image_max_bytes: 10485760

permissions:
  # How *Tether* handles the agent's "allow tool? once|always|reject" ask, per
  # action (this is the bridge's answer on the user's behalf, not the user's):
  #   ask=forward to the user; once/always/reject=auto-answer on their behalf.
  # The agent asks on every call, so `once` auto-answers "allow once" each time.
  auto:                               # action -> once|always|reject|ask
    read: once
    glob: once
    grep: once
    webfetch: ask
    bash: ask
    write: ask
    edit: ask
    apply_patch: ask
  default: ask
  timeout_s: 300
  fallback: reject                    # reject|allow
  poll_interval_s: 30                 # HITL fallback polling (§4.3)

commands:
  prefix: "/"                         # command prefix (only /stop, §6.6)

access:                               # inbound allowlist (§10.1)
  allow_users: []                     # allowed user ids (empty = unrestricted)
  allow_groups: []                    # allowed group ids (empty = unrestricted)

channels:
  wecom:
    enabled: true
    bot_id: ${WECOM_BOT_ID}
    secret: ${WECOM_BOT_SECRET}
  feishu:
    enabled: false
    app_id: ${FEISHU_APP_ID:-}
    app_secret: ${FEISHU_APP_SECRET:-}
  qq:
    enabled: false
    appid: ${QQ_BOT_APPID:-}
    secret: ${QQ_BOT_SECRET:-}
  wechat:
    enabled: false
    cred_path: ~/.wechatbot/credentials.json

logging:
  level: INFO
  json: true
```

### 9.1 Validation

Fail at startup (fail-fast):

- A connector is enabled but lacks a secret/manifest; `server.base_url` is unreachable (optional: retry with delay instead of failing);
- Invalid enum: `streaming.mode`/`reasoning_style`, `identity.inject`/`source`, `group.hitl_scope`/
  `command_scope`/`cross_user_delivery`, `permissions.fallback`, `projects.isolation`/`provider`/
  `on_conflict`/`cow.mode`, `container.runtime`;
- `spool_dir` is not writable; `min_interval_ms ≤ 0`; `inline_limit_bytes` is too large, causing a base64 memory risk;
- `isolation: shared` and a **writable agent** exists (§2.8, fail-fast);
- The names listed in `agent.writable` must be known agents;
- If `model.context_limit` is set, it must be > 0.

### 9.2 Recommendations to Accompany the agentd Configuration

**Key rule**: a `deny` rule **rejects immediately and does not produce `permission.asked`**; only `ask` (including "the default ask
when no rule matches") will park and cause the bridge's HITL card to appear. Therefore **"dangerous actions confirmed by a human via HITL" and "dangerous tools
deny-by-default" are mutually exclusive**, and you must choose one:

- **Posture A — With HITL (recommended, attended groups)**: do not deny dangerous tools; keep them as `ask`, and let the bridge's
  `permissions.auto` (§4.6) decide automatic allow/reject/escalate-to-human. Deny only items that must **never be opened up** (e.g.
  `external_directory`).
- **Posture B — Unattended/stricter (deny)**: deny dangerous tools directly; in that case HITL **only takes effect on the remaining `ask` tools**;
  dangerous operations are unavailable to the model (not "awaiting approval" but "nonexistent").

```yaml
# Posture A (recommended, together with the bridge HITL):
#   do not write deny; keep the default ask, and dangerous actions are confirmed by the bridge card
inboundPermissions: []               # or deny only those that must never be opened:
#  - { action: external_directory, resource: "*", effect: deny }
interactionTimeout: 5m               # fallback, avoids a Turn parking forever (when the bridge is down)
interactionFallback: reject
inputModalities: [text, image]       # the endpoint model's actual capabilities
# MediaUploader (if a file source is needed) is configured by the host; for the HTTP upload endpoint see /api/session/{id}/file

# Posture B (unattended):
# inboundPermissions:
#   - { action: bash, resource: "*", effect: deny }
#   - { action: write, resource: "*", effect: deny }
#   - { action: edit, resource: "*", effect: deny }
#   - { action: apply_patch, resource: "*", effect: deny }
#   - { action: external_directory, resource: "*", effect: deny }
```

> Note: `inboundPermissions` **replaces** rather than stacks (`DESIGN-HTTP.md` §12.1); **an empty rule set does not mean allow** —
> when no rule matches, the default is still `ask`; to silently allow read-only tools you must explicitly allow. This is exactly the basis of Posture A.

---

## 10. Security

### 10.1 Inbound (IM user) authentication / allowlist

- Platform side: verify callback signatures / use long-connection credentials (each Connector is responsible).
- Business-side allowlist: a configurable list of allowed user/group IDs (`access.allow_users`/`allow_groups`); unauthorized ones are simply ignored.
- Group chats are usually delivered by the **platform side** only when the bot is @-mentioned (`group_delivery`, §3.3), which naturally reduces false triggers; the bridge **performs no
  secondary filtering** (§2.5).

### 10.2 Agent execution permissions

- Choose a posture per §9.2: **posture A** (dangerous tools stay `ask`, confirmed via HITL) or **posture B** (deny, dangerous operations
  unavailable to the model). HITL only takes effect for `ask`.
- The bridge-side `permissions.auto` auto-allows only **deterministically safe** read-only actions; everything else is `ask`.
- Explicitly recorded: `webfetch` is an SSRF/exfiltration vector; defaults to `ask` (or deny).

### 10.3 Secrets

- Bearer tokens and every IM secret are all injected from env via `${VAR}` references; redacted in logs (token, aes_key, bot secret).
- `.env` is not committed (`.gitignore`); `.env.example` lists only key names.

### 10.4 File security

- See §7.6: path traversal, SSRF, size limits, type sniffing, outbound denylist.
- spool defaults to a controlled subdirectory **inside the working directory** (ensuring the agent's `read` can reach it); if configured outside the working directory, it must be explicitly
  allowed via `external_directory`. Writing is permitted only within the controlled root.

### 10.5 Output security

- Do not echo provider error details, internal `ref`s, or the verbatim system prompt back to users.
- Markdown rendering injects no executable content (renders only against a token allowlist).

---

## 11. Observability

- Structured logs (`structlog`, JSON): `trace_id` (per inbound message), `channel`, `conversation.key`,
  `session_id`, `message_id`, `turn_id`, event type, duration, result.
- Metrics (Prometheus text or in-memory counters): inbound/outbound message counts, turn duration, SSE reconnect count,
  HITL count/timeout count, media bytes sent/received, send failures and rate-limit hits, render-downgrade count (by element type).
- Per-route debug view: recent event sequence, last flushed text, pending interactions—for troubleshooting.
- Isolation-related: active project lease count, isolated-view (worktree/overlay/container) create/fail count, project switch count.
- Key alerts: agentd unreachable, prolonged SSE disconnection, Connector authentication failure, rising HITL timeout rate.

---

## 12. Project structure and uv project

This project is named **Tether** and is recommended as an **independent repository** (decoupled from the Go repository, conforming to `DESIGN-HTTP.md` §11
"clients belong to the consumer's repository"); if developed within this repository, place it under `tether/` (with its own `pyproject.toml`, independent of the Go build).

```
tether/                             # independent uv project (Tether)
├── pyproject.toml                  # name = "tether"; requires-python = ">=3.12"; dependencies + optional extras
├── uv.lock
├── README.md
├── .env.example
├── config.example.yaml
├── src/tether/
│   ├── __init__.py
│   ├── __main__.py                 # python -m tether / tether entry point
│   ├── app.py                      # assembly: config → connectors → agentclient → engine
│   ├── config.py                   # pydantic-settings models + validation
│   ├── models.py                   # Conversation/InboundMessage/OutboundPlan/Card…
│   ├── capabilities.py             # Capabilities / MarkdownLevel
│   ├── connector.py                # IMConnector Protocol + registry
│   ├── render/
│   │   ├── ast.py                  # RichDoc / Segment / Card
│   │   ├── markdown.py             # markdown-it-py parsing + downgrade
│   │   ├── renderer.py             # Renderer implementation
│   │   └── profiles/               # per-channel profiles (wecom/feishu/qq/wechat)
│   ├── agent/
│   │   ├── client.py               # httpx + sse: AgentClient implementation
│   │   ├── events.py               # event DTOs / classification
│   │   └── errors.py               # error code mapping
│   ├── engine/
│   │   ├── router.py               # Router + session mapping
│   │   ├── route_store.py          # SQLite persistence
│   │   ├── turn.py                 # TurnEngine: SSE consumption + aggregation + completion detection
│   │   ├── streaming.py            # StreamingController (throttle/aggregate/chunk)
│   │   ├── hitl.py                 # permission/question → card / text fallback
│   │   ├── media_ingest.py         # inbound media decision (§4.4)
│   │   ├── media_egress.py         # outbound media collection and sending (§4.5)
│   │   └── commands.py             # /stop (the only command)
│   ├── connectors/
│   │   ├── wecom/connector.py      # MVP
│   │   ├── feishu/connector.py
│   │   ├── qq/connector.py
│   │   └── wechat/connector.py
│   ├── store/sqlite.py
│   └── util/
│       ├── throttle.py
│       ├── dedup.py
│       ├── media.py                # mime sniffing / image compression
│       └── logging.py
└── tests/
```

Dependency layering (`pyproject.toml`):

```toml
[project]
name = "tether"
requires-python = ">=3.12"
dependencies = [
  "httpx>=0.27",
  "httpx-sse>=0.4",
  "pydantic>=2.7",
  "pydantic-settings>=2.3",
  "PyYAML>=6",
  "markdown-it-py>=3",
  "aiosqlite>=0.20",
  "tenacity>=8",
  "structlog>=24",
  "filetype>=1.2",
]

[project.optional-dependencies]
wecom  = ["wecom-aibot-python-sdk>=1.0.2"]
feishu = ["feishu-bot-sdk>=0.13"]
qq     = ["qq-botpy>=1.2"]
wechat = ["wechatbot-sdk"]
media  = ["Pillow>=10"]           # image compression; optional
dev    = ["pytest>=8", "pytest-asyncio>=0.23", "respx>=0.21", "ruff>=0.5", "mypy>=1.10"]

[project.scripts]
tether = "tether.__main__:main"
```

Common commands: `uv sync --extra wecom`, `uv run tether --config config.yaml`,
`uv run pytest`, `uv run ruff check .`, `uv run mypy src`.

---

## 13. Testing strategy

- **Unit**:
  - Rendering: Markdown downgrade (each profile × each element), reasoning/usage rendering (§6.7).
  - Streaming: `StreamingController`'s trailing-edge / drop-if-busy / boundary and final flush / rate-limit backoff /
    `max_live_chars` chunking (§6.2/§6.5, using a frozen clock).
  - Mapping and idempotency: session mapping, dedup key `Conversation.key:message_id` (§8.2).
  - Media: decision tree (modality/size/source, §4.4).
  - Identity: `<bridge-context>` assembly + anti-forgery sanitization (`bridge-context` markers / `[xxx]:` prefixes),
    `identity.source`/`inject` (§2.6/§4.8).
  - Interaction/command: `/stop` parsing, HITL payload encoding, in-group authorization (`hitl_scope`/`command_scope`+`admins`,
    §2.5(3)).
  - Config: §9.1 invalid values for each enum, `isolation: shared`+writable fail-fast, `agent.writable` unknown agent.
- **Contract (fake backend)**: use `respx`/a self-built stub HTTP+SSE service to simulate agentd, verifying: session creation, prompt,
  event aggregation, turn completion detection, HITL round-trip, `attachment.omitted` rendering, error code mapping, SSE disconnect **reconciliation +
  half-finished finalization** (§8.3).
- **Connector (fake SDK)**: wrap the IM SDK behind an injectable protocol, and use a fake implementation to drive assertions on the Connector's **outbound calls**
  (message structure / cards / media upload), as well as **inbound injection** (`InboundMessage` / `IncomingInteraction` /
  `ConnectorEvent` → core layer).
- **Integration (optional, requires real credentials)**: real agentd + real platform sandbox, running one **complete turn** (direct-chat text → streaming →
  @group → permission card click → stop → media send/receive).
- **Timing/concurrency**: use `pytest-asyncio` + a frozen clock to verify the stability of throttling / backoff / reconciliation.
- CI is offline by default (does not depend on real platforms/models).

### 13.1 Capability integration checklist (real-device verification after development, backfill §3.3)

Platform capabilities **cannot rely on documentation alone**; for each platform integrated, verify item by item with a real device + sandbox, and backfill the results into the capability table in §3.3
(replace `pending integration testing`/`unknown` with determined values). Unified scripts/fixtures go in `tests/live/<platform>/`, not run in CI by default.

Confirm item by item for each platform:

1. **Delivery**: In direct chat, is it pushed without @-mention? In group chat, is it pushed only on @, and **is it pushed on non-@**? (determines `direct_delivery` /
   `group_delivery`) Is it necessary to first "enter the session / send a welcome message" (`on_session`)?
2. **Inbound media**: verify against the **inbound types the platform actually supports** (e.g. WeCom inbound has no video, only
   text/image/mixed/voice/file): can it be received and successfully downloaded/decrypted (`aeskey`)? Size limit?
3. **Outbound rendering**: the actual rendering of Markdown (headings/lists/tables/code blocks), @, quotes, links.
4. **Outbound media**: can each type (image/voice/video/file) be sent? Size/format limits?
5. **Streaming/editing**: does `native_stream` really refresh the same message? Is `edit_message` (card patch) available? For a passive-reply stream (WeCom), how long does the callback's `req_id` stay valid — does the `finish=True` frame still land after a multi-second turn? (see §5.1)
6. **Interaction**: can button/card callbacks be received and relayed back? (HITL)
7. **Rate limiting**: actual rate cap (backfill `rate_limit_per_min`).
8. **Proactive push**: is `proactive` available when there is no callback (e.g. WeCom `send_message`)?
9. **Authorization data**: do card/button callbacks carry the **clicker's identity** (`callback_actor_identity`)? Does the platform expose
   **group member roles** (`member_roles`, which determines the `admins` tier)? Most platforms are expected to have "roles unavailable"; Feishu is TBD.

> Before integration testing is complete, the Connector declares the **most conservative** settings (group `mention_only`, `unknown` treated as assuming no delivery),
> to avoid missed responses caused by "assuming non-@ messages can be received".

---

## 14. MVP scope and roadmap

| Phase | Content |
|---|---|
| **M0 skeleton** | uv project, config/validation, unified message model (including inbound items `InboundMessage`/`IncomingInteraction`/`ConnectorEvent`), Connector protocol+registry, AgentClient (HTTP/SSE), Router+SQLite, StreamingController, Renderer (plain-text profile), `/stop`, identity-lead skeleton, structured logging |
| **M1 (MVP) WeCom direct chat + group chat text** | WeCom long-connection Connector; **direct chat and group chat (one session per conversation; bot name/description and speaker identity injected)**; `reply_stream` streaming Markdown; no cross-user steer within a group, reply @-mentions the initiator; turn completion/error notices; `/stop`. **Exit: §13.1 integration testing and backfill §3.3** |
| **M2 WeCom full experience** | Markdown RICH profile (table/code-block downgrade); **run status/usage/thinking display (§6.7)**; template-card HITL (permission/question); inbound media (`download_file` decryption → inline/file/url/spool); outbound media (tool media → chunked upload → image/file/voice/video); `attachment.omitted` notice. **Exit: §13.1 backfill** |
| **M3 Feishu** | Long-connection Connector; card streaming (patch); card interaction callbacks → HITL; media. **Exit: §13.1 backfill** |
| **M4 QQ** | botpy Connector; group/channel/DM; markdown+keyboard; rich media. **Exit: §13.1 backfill** |
| **M5 WeChat personal** | wechatbot-sdk Connector; extreme downgrade; compliance notices. **Exit: §13.1 backfill** |
| **M6 hardening** | **Project isolation (read-only shared / writable isolated per group; `ProjectProvider`: pool/worktree/overlay/container, §2.8/§2.9/§3.7; isolated instances can be wrapped with bwrap/container sandbox, §17)**; SSRF protection; metrics/alerts; adaptive rate limiting; reconciliation improvements; migration/replay |
| **M7 enhancements** | Voice transcription subagent, image OCR, long-term file archiving, Web admin console (optional), **message recall handling** (best-effort, §8.6: Feishu `im.message.recalled_v1` / QQ; WeCom has no event) |

> Each phase should include corresponding unit/contract tests; starting from M1, "conversing with the agent within a group" can be demonstrated end-to-end.

---

## 15. Decision list

| # | Decision | Rationale |
|---|---|---|
| D1 | The bridge is an **independent Python project**, consuming only agentd's HTTP/SSE | Go is not importable; IM SDKs exist only in Python; `DESIGN-HTTP.md` §11 |
| D2 | **Canonical carrier = `RichDoc`** (Markdown + thinking + usage + media + interaction); rendering downgrades per `Capabilities` | Models naturally produce Markdown; capability-driven and extensible |
| D3 | Adding a platform = Connector + capability declaration (+ optional profile); the core engine is unchanged | Extensibility requirement |
| D4 | Agent events use **one global `/api/event` SSE** + routing by sessionID | The global stream contains all live-only deltas and HITL; a single connection is easy to scale |
| D5 | **One IM conversation = one Agent Session** (key = `Conversation.key`, including thread); **no `per_user`/`shared_by_thread` splitting** (§2.5, §3.6) | The SDK is serial within a session; the mapping is unique and consistent with platform delivery |
| D6 | Inbound media goes by modality support→inline/file/url → otherwise **spool + text path** | Covers large files and unsupported modalities; no silent drops |
| D7 | Outbound media sends only **media explicitly produced by tools**; by default does not send all changed files | Avoids spamming; UX first |
| D8 | HITL renders as **card buttons**; channels without buttons degrade to **numbered-text interaction** | Closes the loop on permission/question, avoiding a turn parked forever |
| D9 | Streaming automatically selects native_stream / edit / typing+final / none per capability | Platforms differ greatly; unified throttling and aggregation |
| D10 | `prompt.id = Conversation.key:message_id` achieves idempotency; inbound dedups on the same key | Platform re-delivery/bridge retries do not produce a second turn |
| D11 | Dangerous tools are **restricted** (`ask` via HITL or `deny`, the two postures of §9.2) + bridge-side auto policy | IM users are untrusted; HITL as a fallback |
| D12 | Secrets injected via env, logs redacted; spool controlled directory + SSRF/size protection | Security |
| D13 | Managed with uv, connector dependencies via optional extras | Install on demand, lightweight core |
| D14 | **Reconciliation** after disconnection (active + message + permission/question) | The global SSE has no replay; recovers the final state and pending interactions |
| D15 | MVP does only WeCom (M1 text, M2 full experience) | User-specified; WeCom has the most complete long-connection/streaming/card capabilities |
| D16 | **No trigger filtering**: forward whatever the platform delivers (remove `respond_on`); commands are intercepted locally by the bridge and not forwarded (§2.5) | Tether does not duplicate IM bot policy; the platform is the authority on delivery |
| D17 | Group conversations **inject speaker labels** and sanitize forged prefixes; within a group, **no cross-user steer by default**, replies @-mention the initiator (§2.5(1)(2), §8.1) | Preserves "who is speaking" when multiple people share context, avoiding crosstalk and irrelevant answers |
| D18 | Within a group, **HITL by default allows only the initiator to answer**; the only command, `/stop`, is by default limited to the turn's **initiator** (`command_scope: initiator`, configurable `admins`) (§2.5(3), §4.6, §6.6) | Prevents others from approving dangerous operations on the initiator's behalf or interrupting their turn |
| D19 | **The bot name + description are synced into the agent context** (`<bridge-context>` lead + anti-forgery sanitization; aligned with the agent `description` per `identity.source`; re-injected after name/description changes, agent switches, compaction) (§2.6, §4.8) | Keeps the bot's external identity consistent with the agent's self-perception |
| D20 | **Project isolation is driven by the agent's read/write capability**: a read-only agent can share a project across groups; a writable agent must isolate the project per group (multiple agentd instances); determined by the actual tool set (`GET /api/tool?agent=`); if unknown, isolate conservatively (§2.8) | Read-only sharing has no side effects; writable sharing pollutes files for one another |
| D21 | **Isolation implementation is pluggable**: shared / git worktree / container / copy·CoW·namespace·remote, etc., abstracted via `ProjectProvider`; the bridge does not fork Go processes itself (uses a supervisor/orchestrator) (§2.9, §3.7) | Different deployments have different isolation-strength/cost needs; keeps boundaries clear |
| D22 | **Isolation is shared across `agentd`'s transports via a transport-agnostic project runner in `cmd/`** (`Transport` is a parameter); **a writable project has a single owner `(project, transport)`**, read-only can be shared; the SDK provides only policy (**+ the `Sandbox` hook (SDK layer), §17.2**) (§17.3, §3.7) | Isomorphic to the sandbox: share the mechanism, not the instance; avoids writing one per transport |
| D23 | **Message recall is best-effort and platform-dependent** (§8.6): handled only where the platform emits a recall event (Feishu `im.message.recalled_v1`); cancels queued/in-flight turns, never "unsends" an already-sent reply; a platform without the event (WeCom long connection) is a no-op | The bridge cannot delete its own outbound messages; recall can only cancel uncommitted work |

---

## 16. Appendix: SSE event → rendering mapping

| Event (type) | durable | Key data fields | Rendering action |
|---|---|---|---|
| `server.connected` | No | — | Ignore (connection established) |
| `session.next.text.started` | Yes | assistantMessageID, textID | Start a text segment |
| `session.next.text.delta` | **No** | delta, textID | Aggregate + throttled streaming display |
| `session.next.text.ended` | Yes | text, textID | Final text (rendering baseline) |
| `session.next.reasoning.started/delta/ended` | started/ended yes, delta no | delta/text | Collapsed display when `show_reasoning` |
| `session.next.tool.input.started/delta/ended` | started/ended yes | name, callID, text | May show "preparing to call tool" |
| `session.next.tool.called` | Yes | tool, input, callID | "🔧 Using `<tool>`" |
| `session.next.tool.progress` | Yes | structured, content | Progress; **collect the file parts of content** |
| `session.next.tool.success` | Yes | content, outputPaths, result | **Collect file parts** (outbound media) |
| `session.next.tool.failed` | Yes | error | Error notice |
| `session.next.step.started` | Yes | agent, model | Ignorable/debug |
| `session.next.step.ended` | Yes | finish, cost, tokens, files | Record changed files (optional outbound) |
| `session.next.step.failed` | Yes | error{type,message} | Error notice; provider error explanation |
| `session.next.attachment.omitted` | Yes | name, mime, reason | "Attachment `<name>` not sent to the model due to `<reason>`" |
| `session.next.prompt.admitted` | Yes | messageID, prompt | Ignorable (admission confirmation) |
| `session.next.title.updated` | Yes | title | Optionally sync the session title |
| `session.next.compaction.started/ended` (+ `delta` live-only) | Yes | reason/text | "Organizing context…" |
| `session.status` | **No** | status{type: idle/busy/retry, attempt, message, action, next} | idle→turn ends, flush; retry→retry notice |
| `permission.v2.asked` | **No** | id, sessionID, action, resources, save, metadata, source | Card/numbered options → reply to `…/permission/{id}/reply` |
| `permission.v2.replied` | No | requestID, reply | Close the interaction state |
| `question.v2.asked` | **No** | id, sessionID, questions[], tool | Card/numbered options → reply to `…/question/{id}/reply` |
| `question.v2.replied/rejected` | No | requestID | Close the interaction state |
| Other `session.next.*` (`agent/model.switched`, `moved`, `prompted`, `context.updated`, `synthetic`, `shell.*`, `retried`) | Mostly yes | — | Ignorable / internal state (e.g. `model.switched` can refresh the Route) |
| `mcp.*` | Depends on definition | — | Ignorable or debug display |

> Note: durable events can be recovered via `GET /api/session/{sid}/history?after=` or (on reconnect)
> `GET /api/session/{sid}/message`; live-only events (delta, status, HITL), once lost, are recovered per §8.3
> reconciliation (final text + pending interactions). Replay frames contain only `{id,type,data,durable}` (no location/metadata).

---

## 17. Appendix: go-agent-sdk's sandbox/isolation responsibility boundary and two designs

> **One-sentence distinction**: **the `Sandbox` hook lives in the SDK and governs "how a command executes within a process"; the project runner lives in `cmd/` and
> governs "project and process isolation across sessions / across transports". Do not make isolation into an SDK hook.**
> Structure: 17.1 responsibility boundary and stance → 17.2 `Sandbox` hook → 17.3 project runner → 17.4 comparison → 17.5 command-layer convergence (`agentd`).
> **Ownership**: 17.1 is this document's **decided** stance (decisions D20–D22); 17.2 is implemented by **go-agent-sdk's SDK layer (`pkg/`)**
> ; 17.3 is implemented by **go-agent-sdk's command layer (`cmd/`)** (**not the SDK**). Both live inside the go-agent-sdk repository and
> are not part of Tether—Tether only consumes them: use them directly if present, otherwise fall back on its own (§2.9).

**17.2 and 17.3 are not an either/or**—the two are at **different layers and orthogonal**, and you can use only one or stack them:

| Design | What it governs | In one sentence |
|---|---|---|
| 17.2 `Sandbox` hook | **In-process**: how a command executes and how much it is restricted (SDK) | "How tightly your hands and feet are bound in the room" |
| 17.3 project runner | **Process/project level**: which project each session uses, which service process to start (command layer `cmd/`) | "Which room you work in" |

- **Project isolation only (17.3)**: different groups use different `worktree`/container directories; in-process commands run as usual.
- **Sandbox only (17.2)**: confine `bash` to seatbelt/bwrap within the same process.
- **Stacking is the most robust**: one isolated project per group (17.3) **and** that project's `bash` further sandboxed (17.2)—recommended for this bridge.

### 17.1 Responsibility boundary and stance

> Conclusion (settled in this document): **put policy/abstraction in the SDK, OS enforcement in the host/deployment layer, and the heaviest isolation outside the process.**
> Based on `AGENTS.md` (the SDK does not own infrastructure; it aligns with opencode v2 core) and the comparison in §2.9.1.

**Layer ownership**

| Layer | Owner | Content |
|---|---|---|
| Policy (existing) | SDK | Permission rules allow/ask/deny, `external_directory`, HITL (§4.6) |
| Execution seam (SDK layer, optional) | SDK | `Sandbox` / `CommandRunner` hook (constructor injection, same as `MediaUploader` / `Credentials`), pass-through by default |
| Isolated view / lifecycle | Command layer `cmd/` (extend `serveconfig`) | **transport-agnostic project runner** (§17.3): worktree/overlay/container preparation + building the `Client` + starting the service; shared across `agentd`'s transports |
| OS enforcement | Host / deployment | seatbelt / bwrap / Landlock / seccomp / containers; wrapped outside **each** `agentd` process |
| Orchestration / leasing | Host / bridge | One instance per group for project isolation (§2.8 / §2.9) and lifecycle (§3.7) |

**Suggested minimal increment to the SDK** (without breaking the alignment principle)

- One `Sandbox` (or `CommandRunner`) hook: `bash` executes through it, file changes optional; **no-op by default** (preserves the status quo and embeddability).
- Reference implementations (Linux `bwrap`, macOS `seatbelt`) are **optional, build-tag-isolated, best-effort**; core makes no promise.
- **Not doing**: maintaining three-platform profiles, container orchestration, or network proxying inside core—these belong to specialized tools/deployment.

**Why not put it in core**

- The strongest isolation (containers/VMs) **cannot be done inside the library**; it belongs to the process boundary; process-level isolation is naturally reused by all transports.
- The cross-platform security surface (three-platform profiles) is long-term CVE/compatibility debt and is better left to specialized sandbox tools.
- The threat model is "protect the host from being harmed by the agent"; scenarios needing hard isolation require the **process/project level**, and an in-library best-effort gives a false sense of security.
- The embedding experience (in-process reuse for tests/CLI/service) should not be complicated by sandbox-availability probing.
- Precedent: opencode v2 has no OS sandbox (permissions only); Codex/Claude sandboxes are all at the product/CLI layer.

**Sharing point of isolation (isomorphic to the sandbox)**

The unit of isolation is **`(process, project, transport)`**, not the transport itself—one `Client` binds one project, one
process serves one project; `agentd`'s HTTP / A2A transports are just two adapters of the same runner.
See the "Layer ownership" table above for the three-way division of labor, and §17.3 for the interface draft.

- **Share the runner, not the instance**: `agentd`'s transports are adapters of the same **transport-agnostic project runner**
  (located in `cmd/`, extending the already-shared `cmd/serveconfig`); `Transport ∈ {http, a2a}` is just a parameter.
- **A writable project has a single owner**: the same `Client` cannot be given to both HTTP and A2A (`HoldInteractions` is global,
  `DESIGN-HTTP.md` §9); serving the same writable project concurrently would interfere; therefore it is leased to only one `(project, transport)` at a time,
  and read-only can be shared.
- **Conclusion**: isolation and the sandbox follow the same division of labor—**the SDK manages policy and hooks, the command layer manages lifecycle and isolated views, and the host manages decisions and leases**.

**Impact on the bridge**

- **Do not wait for the SDK/command layer**: implement process/project-level isolation now via `ProjectProvider` per §2.9.
- If go-agent-sdk provides the `Sandbox` hook (17.2) and the `cmd/` project runner (17.3), the bridge's `container` /
  `worktree` / `overlay` providers can be changed to call them, reducing custom code; `ProjectLease` gains `transport`.
- 17.2/17.3 are **go-agent-sdk-side designs** (not in the Tether repository); this document records them **for alignment** and **does not modify
  `docs/DESIGN.md`** (the latter is the SDK's authoritative design).

---

### 17.2 SDK layer (go-agent-sdk `pkg/`): `Sandbox` hook (command execution seam)

**The problem to solve**

- The `bash` tool executes arbitrary shell **inside the host process**, with the caller's identity (its tool description explicitly says "with the host user's
  filesystem, process, and network authority"). The SDK's existing `permission` (allow/ask/deny, `external_directory`)
  is only a policy judgment of "**whether to allow**", **not** OS enforcement at execution time; once allowed, the command runs with the host's full privileges.
- The SDK **actually already has an execution seam internally**: `core.AppProcess` (an interface with `Run`/`RunStream`), through which `bash`, `ripgrep`, and `git`
  all execute (`pkg/agent/builtins.go`). But `pkg/agent` **hard-codes** `core.NewAppProcess()`, and **`ClientOptions`
  has no field that can override it**—so an embedder using `agent.Client` **cannot** swap commands for a seatbelt/bwrap/AppContainer-wrapped executor
  unless it forks.
- Scenario: a `bash` induced by prompt injection or model misjudgment might read `~/.ssh`, corrupt the project, or reach out to the network; the host wants to add an OS-level
  guardrail but has nowhere to hook in.

**How to do it**

- **Promote the existing** `core.AppProcess` seam **to `ClientOptions`**: add an optional field (e.g.
  `Process core.AppProcess`, or a narrower `CommandRunner`); when `nil`, fall back to the current `core.NewAppProcess()` (= pass-through,
  preserving the status quo and embeddability).
- The host's sandbox = an `AppProcess` wrapper: in `Run`, wrap the command with bwrap/seatbelt/AppContainer/cgroup/Job Object
  etc. before exec. Because `bash`/`ripgrep`/`git` **share the same seam**, **one injection applies everywhere** (consistent across embedding / `agentd`'s transports).
- The SDK **only defines/exposes this seam** and does not bundle three-platform profiles; reference implementations are optional, build-tag-isolated, best-effort, with no promise from core.
  The failure policy is configurable as fail-open (fall back to pass-through) or fail-closed; `agentd` defaults to **fail-closed** (a named sandbox that cannot be built refuses to start).
- **Optional, secondary**: a guard for file-write tools (write/edit/apply_patch)—`AppProcess` does not cover file writes, so a separate
  `Allow(ctx, path, op)` hook is needed.

**(The "sandbox" here = adding execution-time OS restrictions to this one command)** Typical dimensions and representative three-platform implementations:

| Dimension | What it blocks | Linux | macOS | Windows |
|---|---|---|---|---|
| Filesystem view | The command sees only the project directory (+ necessary read-only), not `~/.ssh`, `/etc`, etc. | `bwrap` | `seatbelt` | AppContainer (+ low IL) |
| Network | Block network / allowlist only | `bwrap --unshare-net` | `seatbelt` profile | WFP / AppContainer has no network by default |
| Privileges | Drop privileges, drop capabilities | user namespaces | drop uid | restricted token / low integrity (low IL) |
| Resources | CPU / memory / process-count limits | `cgroup` | `ulimit` / `launchd` | Job Object |

- **Linux**:
  - **bwrap (bubblewrap)**: a userspace tool that uses user namespaces to give the command a restricted mount/namespace view (used by Flatpak).
    Example: `bwrap --ro-bind /usr /usr --bind ./proj /work --tmpfs /home --unshare-net -- sh -c '<command>'`—the command
    thinks it is in `/work`, cannot modify anything outside, and cannot reach the network.
  - **cgroup**: a kernel resource controller (limits CPU/memory/PID), often paired with namespace / bwrap.
- **macOS**: **seatbelt** (`sandbox-exec -f profile.sb cmd`) restricts the command's file / network / syscall access per an SBPL profile;
  resource limits use `ulimit` / `launchd`.
- **Windows**: **there is no single CLI like `bwrap`; you must assemble one**—
  **AppContainer** (`CreateAppContainerProfile` + `STARTUPINFOEX`'s `PROC_THREAD_ATTRIBUTE_SECURITY_CAPABILITIES`)
  gives the process a restricted identity, with no network and no access to most files/registry by default; then use a **restricted token / low integrity level (low IL)** to drop privileges;
  a **Job Object** limits CPU/memory/process count (≈ `cgroup`); network egress is allowed via **WFP**. For VM-level isolation, use **Windows Sandbox**
  (Hyper-V, a disposable environment) or **Hyper-V container isolation**.

> All of the above are **execution-time** enforcement, complementing `permission` (the allow **decision**, §4.6). **The SDK does not implement them**; it only provides an injection seam;
> implementations are provided by the host/third parties. Among the three platforms, Windows is the most fragmented (you must assemble AppContainer + Job Object + WFP yourself), so in practice
> **"putting the entire service process into a container / Windows Sandbox" is often less trouble than wrapping command by command**—this design supports both approaches
> (for the runner side, see 17.3).

**Interface** (Go, illustrative):

```go
// Reuse the existing core.AppProcess seam; just let ClientOptions inject it:
type ClientOptions struct {
    // …existing fields…
    Process core.AppProcess // nil → core.NewAppProcess() (pass-through, preserves the status quo)
}

// Optional: file-write guard (AppProcess does not cover file writes, hence listed separately).
type FileWriteGuard interface { Allow(ctx context.Context, path string, op FileOp) error }
```

**What it does not do** (= 17.3's domain): create projects/directories, start processes/containers, proxy the network, isolate across sessions. This section only covers **how a single command
is restricted within the current process**.

### 17.3 Command layer (go-agent-sdk `cmd/`, not the SDK): project runner (isolation / process·project boundary)

**The problem to solve**

- The SDK's mental model is **one `Client` bound to one project / one `WorkingDirectory`** (`ClientOptions.Root` /
  `WorkingDirectory`). But a single `agentd` process serves **multiple sessions/multiple groups**—if they all land in the same working directory,
  they **pollute one another**: group A sees/modifies group B's files, concurrent writes overwrite each other, one group's `rm` affects another group.
- The correct approach is **one isolated view + one service process per project** (worktree / overlay / container / independent instance). But the code that "prepares the isolated view
  and starts the corresponding service" is currently **written once on each** of the HTTP and A2A paths (or simply missing), and is also disconnected from the
  sharing logic already in `serveconfig`.

**How to do it**

- In `cmd/`, extending the already-shared `cmd/serveconfig`, add a **transport-agnostic** `Runner` (the two methods in the table below).
  - `Prepare`: per `IsolationSpec.Mode` (none/worktree/overlay/container/bwrap), produce an isolated view (copy/mount/clone
    to `BaseDir`) and return an `IsolatedProject`.
  - `Serve`: build a `Client` for that view (setting the view path as `Root`/`WorkingDirectory`), and per `Transport ∈ {http,a2a}`
    start the corresponding service.
- `cmd/agentd` thus degrades to: parse config + choose `Transport` + call `Runner`; isolation code has **zero duplication**.
- Lifecycle is orchestrated by the **host side** (Tether itself does not fork Go processes, §3.7): `ProjectProvider.acquire(...)` → the host
  supervisor calls `Runner` → returns `ProjectLease{project_id, transport, server_base}`.
- **Owner rule**: a writable project is leased to only one `(project, transport)` at a time; read-only can be shared (§17.1).

**Interface** (Go, illustrative):

```go
type Transport string // "http" | "a2a"

type ProjectSpec struct { ProjectID, Root, WorkingDirectory string; ConfigDirs []string; /* … */ }
type IsolationSpec struct { Mode string; BaseDir string; BaseReadOnly bool; Container ContainerSpec }
type IsolatedProject struct { Spec ProjectSpec; View string; Teardown func(context.Context) error }

type Runner interface {
    Prepare(ctx context.Context, p ProjectSpec, iso IsolationSpec) (IsolatedProject, error) // none/worktree/overlay/container/bwrap
    Serve(ctx context.Context, p IsolatedProject, t Transport, opts ServerOpts) error        // build Client + start transport
}
```

**The SDK only contributes**: `ClientOptions.Root` / `WorkingDirectory` (one Client per project) and the permission policy—**not** the `Runner` itself.

**What it does not do** (= 17.2's domain): confine a single command in a sandbox; that is the in-process execution boundary.

### 17.4 Comparison (to avoid confusion)

| | `Sandbox` hook | project runner |
|---|---|---|
| Layer | **SDK** (`pkg/agent`) | **Command layer** (`cmd/`) |
| Problem solved | The **command execution** boundary within a single process | **Project/process isolation** across sessions/transports |
| Injection | `ClientOptions.Process` (reuse the existing `AppProcess` seam) | runner parameters / supervisor |
| Unit | One command | One `(process, project, transport)` |
| Sharers | All `agent.Client` consumers | `agentd` |
| Ownership decision | Host chooses/implements | Host decides + leases |
| Typical implementation | seatbelt / bwrap / AppContainer (single command) | worktree / overlay / container / independent instance |

> **Red line**: do **not** make isolation into an SDK hook—it belongs to the command layer and the host; the SDK only provides the "one `Client`, one project"
> primitive and policy for isolation.

### 17.5 Command-layer convergence: `agentd` (single-process multi-transport) — implemented

> Status: **implemented** (go-agent-sdk `cmd/agentd`). Belongs to go-agent-sdk's **command layer** (not SDK core).
> **See `docs/DESIGN-AGENTD.md` for the full design.**

`cmd/agentd` is the single multi-transport process that **replaced** the former `cmd/agentserve` (HTTP) and
`cmd/a2aserve` (A2A) — one process, one config (a list named **`servers[]`**; each entry is one `Client` + one
adapter, and several entries may share a `listen` via host/path routing), N listeners. The former
`buildClient` duplication/drift (the A2A command's config wired fewer `ClientOptions` — MCP / references /
auto-title / `SubagentDepth`) is resolved by one shared builder feeding both transports; it was a
**config-plumbing gap, not an A2A limitation**.

Three hard constraints (details in `DESIGN-AGENTD.md` §7):

1. **Each `servers[]` entry has its own `Root`/session store**: sessions/snapshots/context are **not shared across entries**.
2. **The same project across entries = one isolated view per `(project, transport)`** (`worktree`/`overlay`/`copy`,
   §2.9(4)/§3.7); **read-only** can be shared, **writable sharing without a copy is forbidden**.
3. **Forbidden**: attaching one `Client` to two listeners (`HoldInteractions` is global + ambiguous interaction ownership).

**Retain the distinction**: the two sets of **adapters** `pkg/server` and `pkg/a2a/server` (different wire protocols)—only the **command/assembly layer** was merged.

---

## 18. Appendix: core type glossary

| Type | Definition | Where it appears |
|---|---|---|
| `Conversation` | IM conversation context (channel/kind/id/name/thread/tenant), with `key` as a stable unique key | §3.2 |
| `Sender` | Sender (id/name/is_bot) | §3.2 |
| `Attachment` | Inbound attachment (kind/mime/name/size/handle…) | §3.2 |
| `InboundMessage` | Normalized inbound message (text/mentions/attachments/conversation/sender/quoted) | §3.2 |
| `IncomingItem` / `IncomingInteraction` / `ConnectorEvent` | The connector's three kinds of inbound items (message / card callback / platform event) | §3.1, §3.2 |
| `BotIdentity` / `ConversationInfo` | Bot identity (name/description/alias) / group info (name/members) | §3.2 |
| `Capabilities` / `MarkdownLevel` | Platform capability declaration (markdown level / edit / streaming / buttons / media / limits…) | §3.3 |
| `Segment` | An ordered segment in `OutboundPlan`: text segment / media segment / card segment | §3.2, §6.3 |
| `OutboundPlan` | Outbound plan (`segments` + `reply_to` + `final`) | §3.2 |
| `Card` / `Button` | HITL interaction cards and buttons (`value` encodes the action) | §3.2, §4.6 |
| `SentRef` | A reference to a sent message (for `update` editing) | §3.1 |
| `MediaBytes` / `MediaHandle` | Media bytes / handle to an uploaded asset | §3.1, §7 |
| `RichDoc` / `RichMedia` / `Usage` | Canonical carrier (Markdown + thinking + usage + media + interaction) | §3.5 |
| `Route` | Conversation ↔ Agent Session mapping + in-session state | §3.6 |
| `PendingInteraction` | A pending HITL interaction (kind/owner/options), an element of `Route.pending_interactions` | §3.6, §4.6 |
| `ProjectLease` / `ProjectProvider` | Project instance lease and provider (isolation) | §3.7 |
| `Command` / `Result` / `FileOp` | The SDK `Sandbox` hook's command / result / file operation | §17.2 |
| `Transport` / `ProjectSpec` / `IsolationSpec` / `IsolatedProject` / `Runner` | Command-layer project runner | §17.3 |
| `Event` | AgentClient SSE event DTO (discriminated by `type`) | §3.4, §16 |
| `AgentInfo` / `ModelInfo` / `ToolInfo` / `ActiveSession` | DTO mirrors of discovery endpoints (§4.1 lists the fields) | §3.4 |
| `PendingPermission` / `PendingQuestion` | DTO mirrors of the interaction list | §3.4, §4.6 |

> All types in this document are **design illustrations** (a Python/Go mix); the final implementation in the independent repository prevails.

---

## 19. Appendix: SDK dependencies and prerequisites (check before starting M0)

> Conclusion: Tether depends on the HTTP/SSE contract that `cmd/agentd` has **already implemented** (`DESIGN-HTTP.md` Phases 0–5
> are complete); **there is no hard blocker for M0**. The table below is categorized as "ready / to be added / non-SDK dependency".

**Ready** (no SDK changes needed; actually called by Tether and already verified, §4):

| Category | Content |
|---|---|
| Session | `POST/GET/DELETE /api/session`, `/active`, `/agent`/`/model`/`/title`, `/prompt`, `/interrupt`, `/compact`, `/wait` |
| Read | `/message` (full pagination), `/context`, `/history?after=&limit=` |
| Media | `POST /api/session/{id}/file` (provider upload), prompt `files[]` (inline/url/file/detail) |
| Interaction | `GET /api/permission|question` (including per-session), `…/reply` / `…/reject` |
| Discovery | `/api/agent` (including `description`), `/api/model` (including `contextLimit` / `outputLimit` / `default`), `/api/tool?agent=` |
| Events | `/api/event` (SSE, including live-only deltas and HITL), `session.next.*`, `session.status`, `permission/question.v2.asked`, `attachment.omitted` (including `reason`) |

**To be added** (cheap items, **not M0 blockers**):

_None._ The single item previously listed here — `GET /api/model` lacking `contextLimit` — is now
**satisfied**: the SDK returns `contextLimit` (plus `outputLimit` / `default`) from `/api/model`
(`ModelInfo.Limit.Context`), and Tether consumes it (`agent/client.py` → `resolve_context_limit` →
`Usage`) for the §6.7 usage line.

**Non-SDK dependencies** (implemented on the go-agent-sdk side; Tether does **not wait**):

| Item | Implemented in | Does Tether depend on it |
|---|---|---|
| `Sandbox` hook (command execution seam, §17.2) | go-agent-sdk · SDK layer (`pkg/`) | **No**—the sandbox is done by the host/container (§2.9/§17) |
| `cmd/` transport-agnostic project runner (§17.3) | go-agent-sdk · command layer (`cmd/`) | **No**—Tether manages isolation itself via `ProjectProvider` + `server.pool` |

**M0 prerequisite actions** (small checks, not major development):

1. **Freeze the SDK contract**: take the endpoints/events/fields of §4 as v1; changes go through §13.1 / discussion on the go-agent-sdk side.
2. **Source of `contextLimit`**: satisfied—`GET /api/model` now returns `contextLimit`; `model.context_limit` (§9) is an optional override.
3. **Deployment check**: M0 uses one `cmd/agentd` instance; per §9.2, configure `inboundPermissions` /
   `interactionTimeout|Fallback` / `MediaUploader` (if a `file` source is needed).

# IM Connector Feature Specification and Capability Matrix

## 0. Purpose

This document defines a **single feature specification for IM connectors**. It serves two purposes:

- **Acceptance standard**: what "complete" means for an IM connector. Every feature is marked
  **MUST / SHOULD / MAY** and mapped to a machine-readable `Capabilities` field or connector primitive,
  so it can be reviewed and accepted.
- **Capability evaluation**: score each platform against the same feature set to produce a
  horizontally comparable capability matrix.

> The machine-readable form is `Capabilities` (`src/tether/capabilities.py`); this file is its
> human-readable, reviewable source of truth. The connector contract is in `DESIGN-IM-BRIDGE.md`
> §3.1, the message model in §3.2, and per-platform device verification in §13.1 /
> `VERIFY-CAPABILITIES.md`. The checklist for adding a platform is in §5.5.

**Levels**
- **MUST**: every integration must handle it, or **explicitly declare it unsupported and degrade gracefully**.
- **SHOULD**: implement it when the platform supports it.
- **MAY**: platform-specific or optional.

---

## 1. Feature checklist (normative)

### A. Transport and lifecycle

| # | Feature | Description | Values / level | Field / primitive | Level |
|---|---|---|---|---|---|
| A1 | Connection model | Long connection / webhook / polling | WS / webhook / poll | Connector implementation | Fact |
| A2 | Reconnect | Automatic reconnect with exponential backoff and unlimited retries | Yes / no | Connector implementation | MUST |
| A3 | Heartbeat | WS heartbeat and ACK | Yes / no | Connector implementation | SHOULD |
| A4 | Single-instance constraint | One bot may have only one connection, otherwise events are split | Yes / no | Documentation + runtime constraint | MUST (declare) |
| A5 | Health reporting | Expose whether the transport is online | `bool` / `None` | `IMConnector.connected` | MUST |
| A6 | Multiple accounts | Run multiple bot accounts for one platform in parallel (currently personal WeChat only) | Supported / single account | One connector instance per account; `Conversation.account` + `IMConnector.instance_id` | MAY |

### B. Conversation shapes

| # | Feature | Description | Values / level | Field / primitive | Level |
|---|---|---|---|---|---|
| B1 | Direct chat | One-to-one with a user | Supported / unsupported | `Conversation.kind="direct"` | MUST |
| B2 | Group chat | Multiple users | Supported / unsupported | `kind="group"` | SHOULD |
| B3 | Group delivery model | When the platform delivers group messages to the bot | `mention_only` / `always` / `on_session` | `group_delivery` | MUST (declare) |
| B4 | Direct delivery model | Whether direct messages are always delivered | `always` / `on_session` | `direct_delivery` | MUST (declare) |
| B5 | Channel / sub-channel | Guild/channel scenarios | Supported / unsupported | `kind="channel"` | MAY |
| B6 | Thread / topic | Threaded conversations | Supported / unsupported | `Conversation.thread` | MAY |

### C. Inbound

| # | Feature | Description | Values / level | Field / primitive | Level |
|---|---|---|---|---|---|
| C1 | Text | Text messages | Supported | `InboundMessage.text` | MUST |
| C2 | Mentions | Parse mentioned users | Supported / unsupported | `InboundMessage.mentions`, `mention` | SHOULD |
| C3 | Quote / forward | Quoted messages / merged forwards | Supported / unsupported | `InboundMessage.quoted` | MAY |
| C4 | Inbound media | Image / voice / video / file | Set of types | `media_in`, `Attachment` | SHOULD |
| C5 | Native voice transcript | The platform supplies text (no bridge-side ASR) | Native / ASR required / none | Populate inbound text | MAY |
| C6 | Interaction callback | Button / form click returns to the bridge | Supported / unsupported | `IncomingInteraction` | SHOULD (when buttons exist) |
| C7 | Recall event | The platform notifies the bot of a recall | Supported / none | `ConnectorEvent(kind="recall")` | MAY |
| C8 | Conversation / member events | Enter chat, join group, member changes | Supported / none | `ConnectorEvent` | MAY |
| C9 | Deduplication semantics | Deduplicate by id / sequence | Declared | Connector implementation + `dedup` | MUST |

### D. Outbound rendering

| # | Feature | Description | Values / level | Field / primitive | Level |
|---|---|---|---|---|---|
| D1 | Markdown level | Markdown support for text | NONE / BASIC / STANDARD / RICH | `markdown` | SHOULD |
| D2 | Rich elements | Code blocks / tables / headings / inline images | Supported / unsupported each | `code_block` / `tables` / `headings` / `images_inline` | MAY |
| D3 | Long-text splitting | Split over the platform limit | Max characters | `max_text_chars` + `_chunk` | MUST |
| D4 | Card rendering | Structured card (the HITL carrier) | Supported / unsupported | `_send_card` / `Card` | SHOULD (when HITL exists) |

### E. Streaming and editing

| # | Feature | Description | Values / level | Field / primitive | Level |
|---|---|---|---|---|---|
| E1 | Native streaming | The platform can refresh the same message | Supported / unsupported | `native_stream` | MAY |
| E2 | Message editing | Edit an already-sent message | Supported / unsupported | `edit_message` / `_update_text` | MAY |
| E3 | Degradation: placeholder + final | Fallback when refresh is unavailable | Must implement | `supports_streaming` | MUST |
| E4 | Progress placeholder | Send a text placeholder (`🤔 Thinking…`) when a turn starts | Yes / no | `progress_placeholder` | MAY |

### F. Interaction / HITL

| # | Feature | Description | Values / level | Field / primitive | Level |
|---|---|---|---|---|---|
| F1 | Buttons | Clickable buttons | Supported / unsupported | `buttons` / `Button` | SHOULD |
| F2 | Forms / multiple questions | Multiple questions / multi-choice cards | Supported / numbered fallback | `question_form` / `CardQuestion` | MAY |
| F3 | Callback identity | The callback carries the actor's identity | Supported / none | `callback_actor_identity` | SHOULD |
| F4 | Group roles | Owner/admin roles usable for authorization | Supported / none | `member_roles` | MAY |
| F5 | Acknowledgement / card update | Update the card in place after handling | Supported / unsupported | `acknowledge` | SHOULD |
| F6 | Click deduplication | Repeated clicks are idempotent | Declared | `rid` / connector implementation | MUST |

### G. Outbound media

| # | Feature | Description | Values / level | Field / primitive | Level |
|---|---|---|---|---|---|
| G1 | Media types | Image / voice / video / file | Set of types | `media_out` / `RichMedia` | SHOULD |
| G2 | Upload model | Chunked / URL handoff | Platform-specific | `upload` / `MediaHandle` | Fact |
| G3 | Oversize handling | Compress / transcode / link fallback | Declared | Connector implementation | SHOULD |

### H. Identity

| # | Feature | Description | Values / level | Field / primitive | Level |
|---|---|---|---|---|---|
| H1 | Name / description source | Exposed by the platform or configured | Platform / config / both | `identity` + startup validation | MUST |
| H2 | Avatar | The platform exposes an avatar URL | Yes / no | `BotIdentity.avatar_url` | MAY |

### I. Proactive push

| # | Feature | Description | Values / level | Field / primitive | Level |
|---|---|---|---|---|---|
| I1 | Proactive messages | Push without an inbound message + quota | Capability + limits | `proactive` + connector implementation | SHOULD |

### J. Rate limiting

| # | Feature | Description | Values / level | Field / primitive | Level |
|---|---|---|---|---|---|
| J1 | Local rate limit | Per-conversation outbound ceiling. **Discrete-send** channels use a token bucket; **streaming** channels are limited by the streaming controller (throttle/aggregate) | Per minute or — | `rate_limit_per_min` + `TokenBucket` | SHOULD |

### K. Experience details

| # | Feature | Description | Values / level | Field / primitive | Level |
|---|---|---|---|---|---|
| K1 | Typing indicator | Typing status | Supported / unsupported | `typing` / `_typing` | MAY |
| K2 | Reactions | Emoji reactions | Supported / unsupported | `reactions` / `_react` | MAY |
| K3 | Recall own message | The bot recalls a sent message | Supported / unsupported | Connector implementation | MAY |

### L. Authentication and configuration

| # | Feature | Description | Values / level | Field / primitive | Level |
|---|---|---|---|---|---|
| L1 | Credentials / token refresh / scopes | Authentication, token renewal, scopes/intents | Implemented | Connector implementation | MUST |
| L2 | Startup validation | Validate required fields before enabling | Implemented | `validate_startup` | MUST |

### M. Verification

| # | Feature | Description | Values / level | Field / primitive | Level |
|---|---|---|---|---|---|
| M1 | Device backfill | Confirm each item on a real device and backfill | Confirmed / pending | §13.1 / `VERIFY-CAPABILITIES.md` | MUST |

---

## 2. Platform capability matrix

Legend: ✔ supported · △ partial / limited · ✖ unsupported · ? pending device confirmation (§13.1). This section expands the `Capabilities` described in §3.3.

| Feature | WeCom | Feishu | QQ (api-v2) | Personal WeChat |
|---|---|---|---|---|
| A1 Connection | WS long connection | WS long connection | WS gateway + REST | HTTP long-poll (iLink Bot, thin client) |
| A2 Reconnect | ✔ unlimited retries | ✔ unlimited reconnect + thread supervision | ✔ backoff + resume | ✔ per-account exponential backoff (except `-14`) |
| A3 Heartbeat | ✔ SDK | ✔ SDK | ✔ op1/op11 | ✖ (the long poll returns on timeout) |
| A4 Single instance | ✔ | ✔ (one delivery target) | ✔ | ✔ (one slot per `ilink_bot_id`) |
| A5 Health | ✔ | ✔ | ✔ | ✔ (per account instance) |
| A6 Multiple accounts | ✖ single account | ✖ single account | ✖ single account | ✔ (independent connector/credentials/long-poll per account) |
| B1 Direct chat | ✔ always | ✔ | ✔ always | ✔ always |
| B2 Group chat | ✔ mention_only | ✔ mention_only | ✔ mention_only | ✖ (direct-only, hard-coded) |
| B5 Channel | ✖ | ✖ | ✔ (guild channel) | ✖ |
| B6 Thread | ✖ | ✔ | ? | ✖ |
| C1 Text | ✔ | ✔ | ✔ | ✔ |
| C2 Mentions | ✔ | ✔ | ✔ | ✖ |
| C3 Quote | ✔ | △ | ✔ (`msg_elements`) | ✔ (`ref_msg`) |
| C4 Inbound media | ✔ (some direct-only) | ✔ | ✔ | ✔ |
| C5 Voice transcript | ✔ native | ✖ (client-side only; no voice-bubble transcript) | ✔ native (`asr_refer_text`) | ✔ native (`voice_item.text`) |
| C6 Interaction callback | ✔ | ✔ | ✔ | ✖ |
| C7 Recall event | ✖ | ✔ | ? | ✖ (`delete_time_ms` exists, unhandled) |
| C8 Conversation events | ✔ enter_chat/feedback | ✔ | ✔ group/friend added | ✖ |
| C9 Deduplication | ✔ | ✔ | ✔ (`msg_id` + `msg_seq`) | ? |
| D1 Markdown | RICH | STANDARD | STANDARD (`msg_type=2`) | NONE |
| D2 Rich elements | code blocks/tables/headings | code blocks | code blocks | ✖ |
| D3 Splitting | ✔ 4096 | ✔ 8000 | ✔ | ✔ |
| D4 Cards | ✔ template card | ✔ interactive card | ✔ keyboard | ✖ |
| E1 Native streaming | ✔ `reply_stream` | ✖ (editing instead) | ✖ (the client does not render `stream_messages`) | ✖ |
| E2 Editing | ✖ (pseudo-streaming) | ✔ patch card | ✖ | ✖ |
| E3 Placeholder + final | ✔ | ✔ | ✔ | ✔ |
| E4 Progress placeholder | ✔ | ✔ | ✖ (the first body frame opens the stream) | ✔ |
| F1 Buttons | ✔ | ✔ | ✔ keyboard | ✖ |
| F2 Forms | ✔ | ✔ | ✖ (numbered fallback) | ✖ |
| F3 Callback identity | ✔ | ✔ | ✔ | ✖ |
| F4 Group roles | ✖ | ? | △ the platform exposes `member_role` (not used for gating yet) | ✖ |
| F5 Acknowledgement / card update | ✔ | ✔ | △ acknowledge | ✖ |
| F6 Click deduplication | ✔ | ✔ | ✔ | ✖ |
| G1 Outbound media | image/file/voice/video | image/file/audio/video | image/file/voice/video | image/video/file (no voice) |
| G2 Upload | chunked | API | URL / multipart | CDN (AES-128-ECB) |
| G3 Oversize / fallback | ✔ link fallback | ✔ link fallback | ✔ (soft limit degrades to file) | ? |
| H1 Identity source | must be configured | platform `bot/v3/info` | platform `READY d.user.username` | not exposed (remark/nickname are client-local; configure `identity.display_name`) |
| I1 Proactive push | ✔ | ✔ | ✔ (quota/switch) | △ (sends without `context_token`; unverified) |
| J1 Local rate limit | streaming throttle | streaming throttle | ✔ token bucket 30/min | ? |
| K1 Typing | ✖ | ✖ | △ the platform has `msg_type=6` (direct; not wired, placeholder is used) | ✔ |
| K2 Reactions | ✖ | ✖ | ✖ | ✖ |
| K3 Recall own message | ? | ? | ✔ ≤2 min | ✖ |

---

## 3. Usage

- **New-connector acceptance**: cover every **MUST** item first; implement every **SHOULD** item the platform supports; **MAY** items are optional. Every item needs a unit test (against a fake SDK) and a device check per §13.1, then backfill §2 and §3.3.
- **Coverage**: `implemented and applicable / applicable total` (items the platform cannot support count as "not applicable" and are excluded from the denominator).
- **Capability evaluation**: read the §2 matrix directly; the machine-readable form is each connector's `Capabilities`.
- **Maintenance**: when a platform's `Capabilities` fields change, update §1 and §2 together.

# Real-device capability verification checklist (§13.1)

Purpose: confirm each integrated platform's `Capabilities` against a real device and **backfill**
the tables in `docs/DESIGN-IM-BRIDGE.md` (§3.3, §5.1/§5.2, §7.7), replacing every
`pending integration testing` / `unknown` cell with a determined value.

## Prerequisites
- agentd up; the bridge up with a **single instance** (§5.1/§5.2: one long connection per bot —
  a second instance may steal events).
- A p2p chat and a test group with the bot; the bot @-mentioned for group messages.
- Watch `/tmp/tether-feishu.log` (bridge), `/tmp/agentd.log`, and ask the agent to produce media
  on demand (e.g. "make me a tiny png/mp3/mp4 and save it").

## Legend
- ✅ already verified on a real device — skip.
- ⬜ to verify (write the determined value next to **→ backfill**).
- 🔎 where to observe: IM rendering / a bridge log event / the connector source capability.

If a declared value turns out wrong, also update `connectors/<platform>/connector.py` and add a
change-log row in `DESIGN-IM-BRIDGE.md`.

---

## WeCom (`channels.wecom`)

### 1. Delivery
- ✅ p2p is pushed without @ → `direct_delivery: always`
- ✅ group is pushed only on @ → `group_delivery: mention_only`
- ✅ group **non-@** is dropped (verified 2026-10-15: a non-@ group "hi" produced no
  `Received push message`) → `group_delivery: mention_only` confirmed.

### 2. Inbound media
- ✅ image (AES `download_file`) and file received + decrypted; ✅ voice (`message.voice.content`
  is the transcript); ✅ quoted file/text path.
- ℹ️ Delivery is **agentd-owned** now: Tether hands each attachment over as an inline data URL and
  agentd's `servers[].media` decides inline / file / url / downsample / spool. This agentd has **no
  media uploader** (`GET /api/config` → `mediaUpload: null`; `POST /api/session/{sid}/file` → 501),
  so an over-limit image needs `media.downsample: true` (images shrink in-process; audio/video need
  the host `ffmpeg` hook) — otherwise it **spools** (invisible to the model) or, past `maxBytes`, is
  omitted (`attachment.omitted`, `reason: too_large`).
- ⚠️ **Context poisoning** (historical, pre-agentd-ownership): a multi-MB inlined image could exceed
  the model context and then *every* later prompt 400s
  (`maximum context length … requested N tokens`); recover with **`/new`** (admin). Now agentd's
  `media:` policy (downsample / provider file / spool) owns this.
- ⬜ platform size cap for a delivered image/file — largest accepted?
  - 🔎 send progressively larger files; find the rejection point.
  - → backfill §7.7 inbound + §5.1.

### 3. Outbound rendering
- ✅ a code block renders (markdown RICH).
- ⬜ headings / lists / tables / bold / links render as intended.
  - 🔎 ask the agent for a message with `# H`, `- item`, a markdown table, `**bold**`, a link.
  - → backfill §3.3 markdown level.

### 4. Outbound media
- ✅ image (chunked upload) and file send.
- ⬜ **voice** sends (accepted format/size?).
- ⬜ **video** sends.
  - 🔎 ask the agent for a small `.amr/.mp3` and `.mp4`, then `/send` them.
  - → backfill §7.7 outbound.

### 5. Streaming / editing
- ✅ `native_stream` (`reply_stream` refreshes the same message); ✅ `edit_message: false`.
- ⬜ `reply_stream` `req_id` lifetime across a **long** turn (we once saw
  `stream message update expired (>10 minutes)`).
  - 🔎 run a multi-second/minute turn; watch for `stream_update_failed` and the fallback to a
    fresh message.
  - → backfill §5.1 note.

### 6. Interaction
- ✅ permission / question cards (buttons, multi-question) receive callbacks and relay them.
  - → §3.3 buttons + authorization table.

### 7. Rate limiting
- ⬜ real outbound rate cap → `rate_limit_per_min`.
  - 🔎 drive a burst of sends; note 4xxxx rate errors.

### 8. Proactive push
- ⬜ `send_message` with **no** inbound frame (out-of-frame reply) works, and its cap.
  - → backfill §3.3 `proactive`.

### 9. Authorization data
- ✅ card callback carries the **clicker** (group HITL works) → `callback_actor_identity: true`.
- ✅ group roles are **not** exposed → `member_roles: false`.

---

## Feishu (`channels.feishu`)

### 1. Delivery
- ✅ p2p is pushed.
- ⬜ `direct_delivery` (currently `unknown`) — confirm p2p is always pushed.
- ⬜ group @-only; and does a group **non-@** message arrive (needs the "receive all group
  messages" permission)?
  - 🔎 p2p msg; group @ msg; group non-@ msg; watch the handler / logs.
  - → backfill §3.3 delivery + §5.2 (`direct_delivery`).

### 2. Inbound media
- ✅ image received + downloaded.
- ⬜ **file** received + downloaded (`file_key`, `file_name`).
- ⬜ **voice bubble** (`message_type: audio`, `{file_key, duration}`) received and delivered as a
  raw attachment (no transcription, D24).
- ⬜ sticker.
  - → §7.7 inbound + §5.2.

### 3. Outbound rendering
- ⬜ card `markdown` component: bold/italic/strike/links/inline code/**lists**/**code blocks**/`---`.
- ⬜ headings degrade to bold; tables degrade to columns.
  - 🔎 ask the agent for a rich-markdown message; inspect the card.
  - → backfill §3.3 markdown level.

### 4. Outbound media
- ✅ image sends.
- ⬜ **file** sends (non-image is currently sent as `file`).
- ⬜ **audio / video** native bubbles (a follow-up; note whether `file` works meanwhile).
  - → §7.7 outbound + §5.2.

### 5. Streaming / editing
- ✅ text edit strategy (`update` via `PUT`).
- ⬜ `PATCH` breadth — which `msg_type`s patch cleanly (cards vs text).
  - → §5.2 outbound/streaming.

### 6. Interaction (HITL)
- ⬜ `card.action.trigger` is received; the button `value` decodes; the single-question and
  **multi-question** forms render and submit.
  - 🔎 trigger a permission ask and a multi-question `question`; click submit; watch the log.
  - → §3.3 buttons + §4.6.

### 7. Rate limiting
- ⬜ cap → `rate_limit_per_min`.

### 8. Proactive push
- ⬜ `proactive: true` — send with no callback pending.

### 9. Authorization data
- ⬜ `operator` present in `card.action.trigger` → `callback_actor_identity`.
- ⬜ `member_roles` — can roles be read via an extra API (→ the `admins` tier)?
  - → §3.3 authorization table.

---

## QQ (`channels.qq`)

Built directly on the api-v2 spec (no SDK); confirm the gateway, then the messaging surface.

### 1. Gateway / connection
- ✅ (2026-10-16) `getAppAccessToken`, gateway Hello → Identify → **Ready**, heartbeats acknowledged;
  the bot stays connected and answers C2C messages.
- ⬜ Force a drop (network) → it reconnects and **Resumes** (`op 6`, `session_id`+`seq`, missed events
  replayed).
- ⬜ `4914` (sandbox-only) / `4915` (banned) **stop** retrying instead of looping.
  - 🔎 watch `qq_gateway_connecting` / reconnect logs.

### 2. Delivery
- ✅ (2026-10-16) C2C is pushed without conditions → `direct_delivery: always`.
- ✅ (2026-10-16) group @ delivers and the reply works (a **passive reply**; the client shows it as a quote of the @-message). ⬜ confirm a group **non-@** is dropped.
  - → backfill §3.3 delivery + §5.3.

### 3. Inbound
- ✅ (2026-10-16) text; ✅ image; ✅ **voice** (platform transcript used); ✅ **file** (PDF/PPTX). ⬜ @mentions;
  quoted (`message_type: 103`, `msg_elements`); video.
  - → §7.7 inbound + §5.3.

### 4. Outbound rendering
- ✅ (2026-10-16) `msg_type=2` markdown **is permitted and renders** (bold/lists/code) in **C2C** — no fallback was
  triggered. ✅ groups **reject** `msg_type=2` (400) and fall back to plain text → markdown is **C2C-only**. ⬜ the exact markdown subset.
- ✅ (2026-10-16) a group bot **cannot send proactive messages** (`40034105`); every group reply must be a passive reply carrying `msg_id`.
- ⬜ long-text chunking at `max_text_chars`.
  - → backfill §3.3 markdown level.

### 5. Streaming / editing
- ✅ (2026-10-16) a turn is a **single final message** (no `🤔 Thinking…`): the bridge sets `progress_placeholder: false` for QQ. `stream_messages` is **not used** — the client renders it as *"This message type is not supported for viewing yet"* and it is append-only; groups have no stream endpoint either. ⬜ (optional) revisit if the client ever renders streamed messages.
  - → §5.3 streaming note.

### 6. Interaction (HITL)
- (2026-10-16) **not exercised**: the bridge auto-approves the configured permission actions
  (`auto: once`), so no keyboard card appeared.
- ⬜ a permission card is a message with an inline **keyboard**; clicking a button returns
  `INTERACTION_CREATE` whose `data.resolved.button_data` equals the button `value`.
- ⬜ does `keyboard` work alongside **`msg_type=0`** (the connector sends text + keyboard)? and how many
  buttons per row / rows are allowed (error `304029`)?
- ⬜ `PUT /interactions/{id}` acknowledgement clears the client's loading state.
  - → §3.3 buttons + §4.6.

### 7. Outbound media
- ✅ (2026-10-16) upload via the **direct base64 `file_data`** path is accepted (returns `file_info`), and
  `msg_type=7` + `media.file_info` sends; the agent sent files back to **C2C** (5×) and a **group** (1×).
  ⬜ URL upload; the byte cap; the **multipart** flow (not implemented — over the direct cap currently fails).
- ✅ (2026-10-16) single- and group-scoped endpoints both used (`/v2/users/{openid}/files` vs
  `/v2/groups/{group_openid}/files`). ⬜ `file_info` TTL.
  - → §7.7 outbound + §5.3.

### 8. Rate limiting / quotas
- ⬜ passive-reply window + count (C2C 60 min / ≤4, group 5 min / ≤5) → the `msg_id`+`msg_seq` handling
  and the proactive fallback.
- ⬜ proactive quotas (per-Bot / per-relation QPS + daily caps) and the user's "allow proactive sending" toggle.
  - → `rate_limit_per_min`, §5.3.

### 9. Recall / authorization
- ⬜ recall own message within 2 min → `ConnectorEvent(kind="recall")`.
- ⬜ `INTERACTION_CREATE` carries the clicker; group messages carry `author.member_role`
  (member/admin/owner) — surface it **before** setting `member_roles`.
  - → §3.3 authorization table.

---

## §7.7 media download/upload (all platforms)

Confirm, per platform: required permission scopes; URL validity; size limits; the exact response
fields.

- WeCom: ✅ `download_file(url, aes_key)`; ✅ asset chunked upload; ⬜ size caps.
- Feishu: ✅ resource download (`image_key`/`file_key`); ✅ image/file upload; ⬜ scopes + size caps.
- QQ: ⬜ `attachments[].url` inbound (+ `voice_wav_url`); ⬜ `.../files` upload (URL / multipart) →
  `file_info`; ⬜ scopes + size caps.
  - → backfill the §7.7 table.

---

## After a pass
1. Backfill §3.3, §5.1/§5.2, §7.7 (replace `pending integration testing` / `unknown`).
2. If a connector's declared `Capabilities` differ from reality, update
   `connectors/<platform>/connector.py` and add a change-log row.
3. Put any repeatable scripts/fixtures under `tests/live/<platform>/` (not run in CI).

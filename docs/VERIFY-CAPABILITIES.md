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
- ✅ a ~4.9 MB screenshot is delivered by the platform and (2026-10-15) **downsampled** to fit the
  inline limit → inlined (`media_downsampled`, 4.9 MB → 163 KB). Note: this agentd has **no media
  uploader** (`GET /api/config` → `mediaUpload: null`; `POST /api/session/{sid}/file` → 501), so an
  over-limit image goes *uploader (none) → downsample → inline*.
- ⚠️ **Context poisoning**: if a multi-MB image is inlined (e.g. under a large `inline_limit_bytes`),
  the turn can blow past the model's context and then *every* later prompt 400s
  (`maximum context length … requested N tokens`). Recover with **`/new`** (admin) to reset the
  session. `media.downsample` (default on) prevents it — the same 4.9 MB image otherwise reached
  `media_inlined` (bad), `media_spooled` (agent-blind), then `media_downsampled` (correct).
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
- ⬜ **voice bubble** (`message_type: audio`, `{file_key, duration}`) received; ASR path needs a
  paid tenant + `ffmpeg` (deferred, D24).
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

## §7.7 media download/upload (both platforms)

Confirm, per platform: required permission scopes; URL validity; size limits; the exact response
fields.

- WeCom: ✅ `download_file(url, aes_key)`; ✅ asset chunked upload; ⬜ size caps.
- Feishu: ✅ resource download (`image_key`/`file_key`); ✅ image/file upload; ⬜ scopes + size caps.
  - → backfill the §7.7 table.

---

## After a pass
1. Backfill §3.3, §5.1/§5.2, §7.7 (replace `pending integration testing` / `unknown`).
2. If a connector's declared `Capabilities` differ from reality, update
   `connectors/<platform>/connector.py` and add a change-log row.
3. Put any repeatable scripts/fixtures under `tests/live/<platform>/` (not run in CI).

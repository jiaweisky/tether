# Tether — outbound file delivery design

> Status: **implemented** — `media.outbound.auto_files`/`patterns`, the `PathPolicy` (`util/path_policy.py`),
> the drain-time gate in `engine/turn.py`, and the explicit `/send <path>` command (`engine/commands.py` + `app.py`);
> enforced command matching became format-aware to accept the `/send` argument.
> Scope: how the bridge (Tether) decides **whether** and **when** to deliver a file produced by
> the agent to the IM conversation it is serving.
> Relationship: this is a focused companion to `DESIGN-IM-BRIDGE.md` (which covers media in
> general, §7). It does not change that document; it specifies the outbound-file policy that
> `DESIGN-IM-BRIDGE.md` currently leaves open.
> Convention: code in this document is **illustrative** — it expresses the contract, not the final
> signature.

## Table of Contents

- 1. Problem
- 2. Two independent layers
- 3. Configuration
- 4. Pattern semantics
- 5. Evaluation
- 6. Scope and enforcement point
- 7. When a file is sent (auto vs explicit)
- 8. The `/send` command
- 9. Blocked-file behaviour
- 10. Startup validation
- 11. Interaction with project isolation
- 12. Non-goals
- 13. Test plan
- 14. Decision list

## 1. Problem

The bridge reads files the agent produced (the `write`, `edit` and `apply_patch` tools report
them via `structured.resource` / `structured.files[].file`, and via `outputPaths`) and uploads
them to the IM channel. Today it does so **without any path check**, so whatever a tool names can
be read and sent (`/etc/…`, `~/.ssh/…` — the bridge runs on the same host as `agentd`; agentd's
tool permissions gate the agent's *reads/writes*, not the bridge's *read-and-send*).

A second, independent problem is **noise**: while developing a feature a single turn may create
and edit many files; auto-forwarding every one of them to a group is a poor experience. "The file
was edited" does not mean "send it now".

## 2. Two independent layers

| Layer | Owner | Decides |
|---|---|---|
| May the agent write/edit a file | **agentd** `inboundPermissions` (`resource` / `effect`) | whether the agent can touch the path |
| May the file be delivered to IM | **Tether** (`media.outbound.*`, this design) | whether the bridge reads + uploads it |

The layers are independent: a `write`/`edit` can succeed (the file exists on disk) while the
bridge refuses to deliver it because the path is not allowed, or because delivery is not
requested.

## 3. Configuration

```yaml
media:
  outbound:
    # WHEN: auto-forward files the agent writes/edits. Off by default — during
    # development, edits are usually incidental, not something to push to the chat.
    auto_files: false
    # WHETHER: ordered glob patterns matched against the file's absolute, resolved
    # path. Default-deny (whitelist): a file is sent only if the last matching
    # pattern is a positive one. Empty = deny every file.
    patterns: []
```

- **Defaults: `auto_files: false`, `patterns: []`** — i.e. by default **no file is auto-sent**
  and **no path is allowed**; delivery happens only via the explicit `/send` command (§8).
- Both are workspace-wide; `{working_dir}` expands per conversation (§11).
- `media.outbound` already carries `image_max_bytes`; `auto_files` and `patterns` are added
  alongside it.

### Examples

Deny everything (default):
```yaml
    auto_files: false
    patterns: []
```

Auto-forward everything inside the project/view:
```yaml
    auto_files: true
    patterns: ["{working_dir}/**"]
```

Only explicit `/send`, restricted to a couple of directories:
```yaml
    auto_files: false
    patterns:
      - "{working_dir}/docs/**"
      - "{working_dir}/reports/**"
```

Allow the project but never secrets (order matters; `!` last):
```yaml
    auto_files: true
    patterns:
      - "{working_dir}/**"
      - "!**/.env"
      - "!**/*.key"
      - "!**/id_rsa"
```

Allow one external file (outside the working directory):
```yaml
    patterns:
      - "/Users/alice/work/activity-center/docs/requirements/spec.md"
```

## 4. Pattern semantics

- **Match base**: the file's **`Path.resolve()` absolute path** (collapses `..`, follows symlinks).
  A symlink or `..` that escapes a root therefore does **not** match the whitelist and is blocked.
- **Anchoring**: a pattern is matched against that **absolute path from its start** (`re.match`),
  never against the basename — so a bare `a.txt` matches nothing. Write `{working_dir}/a.txt` for a
  project-relative file, or `**/a.txt` for "anywhere at any depth".
- **`{working_dir}`**: expands, per conversation, to that project/view's **resolved** absolute path
  (the same value file paths are resolved against), so `{working_dir}/**` matches every file under
  the project/view.
- **Ordered, last match wins** (gitignore-style):
  - start `allowed = False`;
  - a positive match sets `allowed = True`; a `!` (negation) match sets `allowed = False`;
  - after the whole list, the file is sent only if `allowed` is `True`.
  - Negations must therefore appear **after** the positive pattern they carve out of.
- **Glob subset**:
  - `**` matches across `/` (`**/` may appear anywhere, e.g. `**/*/a.txt`, `**/.env`);
  - `*` matches within one path segment (not `/`); `?` matches one non-`/` character;
  - `[...]` is a character class; other regex metacharacters are escaped;
  - a trailing `/` means "the directory and its contents" (`{working_dir}/secrets/` ≡
    `{working_dir}/secrets/**`).
- **Case-sensitive** matching (uniform and predictable, even on a case-insensitive filesystem).
- No third-party dependency: a small `glob -> regex` translation suffices.

## 5. Evaluation

```python
# Patterns are validated at startup; a pattern using {working_dir} is finalized
# per conversation (and cached). `rules` is that conversation's compiled list.
def outbound_allowed(path: str, rules: list[tuple[bool, re.Pattern]]) -> bool:
    real = str(Path(path).resolve())
    allowed = False
    for negate, regex in rules:
        if regex.match(real):
            allowed = not negate
    return allowed
```

## 6. Scope and enforcement point

- **Applies to path-based files only**: `structured.resource` / `target`,
  `structured.files[].file`, and `outputPaths`. These are the paths the bridge itself reads from
  disk.
- **Inline file parts** (a tool result `content` entry that inlines bytes / a `data:` URL / an
  `http(s)` URL) are **not** subject to `patterns` — there is no local path, and the tool has
  already chosen to emit those bytes (this is the "media explicitly produced by tools" case).
- Enforcement happens **before reading bytes** (before `files_from_paths`), at drain time; the
  existing `media.max_bytes` cap still applies, and a path that is not an existing file (e.g. a
  directory) is ignored.
- **Home**: a small `PathPolicy` in Tether's media egress; the turn applies it at drain and the
  `/send` command reuses the same policy (one place decides).

## 7. When a file is sent (auto vs explicit)

- **Path-based files** (write/edit/apply_patch/`outputPaths`) are sent only when **both** hold:
  1. delivery is requested — either `auto_files: true`, or the user ran `/send` for that file; and
  2. the path is allowed by `patterns`.
- **Inline file parts** are explicit media and are forwarded as today (size permitting), regardless
  of `auto_files`/`patterns`.
- With the defaults (`auto_files: false`, `patterns: []`) **nothing path-based is ever sent** until
  the operator opens paths in `patterns` and the user runs `/send`.

## 8. The `/send` command

`/send <path>` — the user explicitly asks the bridge to deliver a file.

- `<path>` is joined to `{working_dir}` when relative (so `docs/requirements/x.md` works) and is
  then `resolve()`d and policy-checked — so a relative `../../etc/passwd` resolves outside the
  project and is blocked; absolute paths are accepted but must still match `patterns`.
- If the conversation has no working directory yet (e.g. `/send` is the first message, before any
  route/lease exists), it replies with an error notice instead of failing silently.
- A path that is not an existing regular file (missing, or a directory) is reported as an error.
- The bridge intercepts it locally (never forwarded to the agent), applies `patterns`, and on
  success uploads the file to the conversation (native `image` for images, `file` otherwise).
- Authorization: any participant of the conversation may run it; the `patterns` policy is the
  gate (so a group cannot `/send` a path the operator has not opened).
- Failure is reported (§9): not found, too large, or not allowed.

## 9. Blocked-file behaviour

- **Skip**: the file is not read and not uploaded.
- **Operator visibility** (both paths): `log.warning("media_outbound_blocked", path=<absolute path>)`
  and a `media_outbound_blocked` counter.
- **User notice — only for the explicit `/send`**: the user asked for *that* file, so a refusal must be
  visible:
  ```
  ⚠️ Not sent: `国风皮肤抽奖需求梳理.md` — outside the allowed send paths
  ```
  - only the **file name** (basename) is shown, never the full path (a group reply is public; the
    full path stays in the log);
  - wording is neutral ("outside the allowed send paths"), not "permission" — the block is the
    bridge's egress policy, not an agentd tool-permission error.
- **Auto-forwarded files are silent**: under `auto_files: true`, a path-based file the tools name is
  the bridge's *own* action, not a user request, so a disallowed one is skipped **without** a chat
  notice (log + counter only) — no nagging the conversation about files nobody asked for.
- `/send` replies immediately; auto-forwarded media is emitted at **drain**, so an interrupted turn
  drains nothing (and a blocked auto-forwarded file produces no notice either way).

## 10. Startup validation

`patterns` are validated/compiled at startup; an invalid pattern fails startup fast. A pattern that
uses `{working_dir}` is expanded and finalized per conversation (cached); patterns without it are
compiled once.

## 11. Interaction with project isolation

`{working_dir}` is the route's project directory: for `mode: isolated` it is the leased view, for
`mode: shared` it is `server.working_directory` / `projects.source_directory`. The policy follows
automatically; no per-mode configuration.

## 12. Non-goals

- Inline-part modality/size policy (e.g. "only `image/*`, ≤ N bytes") — possible later.
- A domain allow-list for **outbound remote URLs** (`media.fetch_url_outbound` already has its own
  switch).
- Per-user or per-message quotas.

## 13. Test plan

1. `/send` an allowed path → delivered; a disallowed path → blocked + notice.
2. `patterns: ["{working_dir}/**", "!**/.env"]` → `…/proj/.env` blocked, `…/proj/a.txt` allowed
   (order/negation).
3. `**/*/a.txt` and `/etc/*.config` forms match as expected.
4. **Escape**: `<wd>/../../etc/passwd` and a symlink pointing outside → blocked after `resolve()`.
5. Inline file parts are unaffected by `patterns`.
6. Blocked `/send` → `media_outbound_blocked` (log + counter) and a user notice; a blocked
   auto-forwarded file → **log + counter only, no notice**.
7. Invalid pattern → startup error.
8. `auto_files: false` (default) → an edited file is **not** auto-sent; `auto_files: true` with a
   matching pattern → sent, and only once per turn with the final content.
9. `/send` with no working directory yet (first message) → error notice; `/send` a directory or a
   missing file → error notice.
10. Anchoring: `{working_dir}/a.txt` matches that file; a bare `a.txt` matches nothing;
    `**/a.txt` matches it at any depth.

## 14. Decision list

| # | Decision | Rationale |
|---|---|---|
| DOF-1 | **Outbound files are default-deny**: `patterns: []` allows nothing | The bridge reads files on the same host as agentd; a whitelist is the safe default |
| DOF-2 | **No auto-forward by default** (`auto_files: false`); delivery is explicit via `/send` | During development, edits are incidental; auto-pushing every created/edited file is noisy |
| DOF-3 | `patterns` are **glob + `!`**, ordered, last-match-wins, matched against the **resolved absolute path**, with a `{working_dir}` template | Expressive (files or directories, allow + deny) yet predictable; `resolve()` closes `..`/symlink escapes |
| DOF-4 | The rule governs **path-based** files only; **inline file parts** are explicit media and always forwarded | Paths are the bridge's own filesystem access; inline bytes were already chosen by the tool |
| DOF-5 | A blocked file is **skipped** and logged/metriced; a **name-only notice** is sent **only for an explicit `/send`** (auto-forwarded files are silent) | The user must know an explicit request did not happen, without leaking server paths into a group; auto-forwarding is the bridge's own action and should not nag the chat |
| DOF-6 | The policy is a Tether concern, **independent of** agentd's tool permissions | Writing a file and delivering it are different decisions, owned by different layers |

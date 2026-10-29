# Tether

Tether bridges IM platforms (WeCom / Feishu / QQ / WeChat) with **pluggable
agent backends** over HTTP/SSE:

- `agentd` from
  [`jiaweisky/go-agent-sdk`](https://github.com/jiaweisky/go-agent-sdk) — the
  Go agent loop, sessions, tools and permissions;
- [`opencode serve`](https://opencode.ai) — OpenCode sessions, tools,
  permissions and forms (the v1.19.x and v2 HTTP shapes are auto-detected).

It lets users converse with an Agent in IM conversations — direct chat and
multi-user group chat — with capability-aware streaming/rendering, HITL
permission/question/form cards, and bidirectional media where the platform and
model support it.

Tether does **not** implement the agent loop: sessions, tools, permissions and
compaction live in the backend process. Tether does four things:

1. Protocol translation (IM message ⇄ prompt/event/attachment).
2. Conversation mapping (**one IM conversation = one agent session**) + HITL.
3. Experience polishing (streaming, Markdown degradation, tool progress, usage).
4. Media transfer between IM platforms and the backend in both directions:
   connector-side download/upload, with link/notice fallbacks when a platform
   or model cannot handle a type. Tether only downloads inbound media and
   passes byte-backed inline file parts; delivery policy (inline / provider
   file / url / downsample / spool) is owned by `agentd`'s
   `servers[].media`.

## Agent backends

Backends are selected per `ServerEndpoint`; the bridge core only consumes the
backend-neutral `Event` / `TurnSnapshot` / `PendingPermission` / `PendingQuestion`
model, so the two adapters are interchangeable.

| backend | transport / auth | shared projects | isolated projects |
|---|---|---|---|
| `agentd` | HTTP/SSE, Bearer | one endpoint = one project / working directory | agentd control API (`none` / `copy` / `worktree` / `overlay`) |
| `opencode` | HTTP/SSE, Basic | one endpoint = one location; several locations may share a `base_url` | per-conversation OpenCode worktrees |

Set `server.backend` for the single-base form, or list `server.pool` entries with
their own `backend`, `auth`, `working_directory`, `default_agent` and
`default_model`. Legacy `server.base_url` / `server.token` configurations keep
working (and default to `agentd`). See
[`docs/DESIGN-OPENCODE-BACKEND.md`](./docs/DESIGN-OPENCODE-BACKEND.md) for the
full design.

OpenCode notes: the adapter synthesises the `build` agent when `/api/agent`
returns an empty list, maps OpenCode forms/permissions onto the same HITL
cards, and keeps caches per `(endpoint, location)`. Stock `opencode serve` does
not persist events, so reconnect recovery falls back to projection resync; a
backend restart also loses in-memory pending forms/permissions — Tether clears
the stale cards and notifies the chat. Cold-starting a location can take tens of
seconds.

## Runtime dependency

Tether is only the IM bridge: it **requires a running backend** — an `agentd`
server from
[`jiaweisky/go-agent-sdk`](https://github.com/jiaweisky/go-agent-sdk), an
`opencode serve` process, or both. Neither is embedded in Tether nor installed
by `uv sync`.

Start the backend first, then point Tether at it:

```yaml
server:
  backend: agentd
  base_url: http://127.0.0.1:8787
  token: ${AGENTSERVE_TOKEN:-}
```

or use a pool:

```yaml
server:
  pool:
    - id: local-opencode
      name: local-opencode
      backend: opencode
      base_url: http://127.0.0.1:4096
      auth:
        type: basic
        username: opencode
        password: ${OPENCODE_PASSWORD:-}
      working_directory: /workspace/project   # OpenCode location; must be absolute
      default_agent: build
      default_model: anthropic/claude-sonnet-4-5
```

Without a reachable backend Tether can connect to IM platforms but cannot answer
messages. `agentd` owns its project/working directory; OpenCode locations are
discovered per endpoint. The full IM-bridge design lives in
[`docs/DESIGN-IM-BRIDGE.md`](./docs/DESIGN-IM-BRIDGE.md).

## Status

Implemented: the M0 core engine plus WeCom, Feishu and QQ (with the paths
verified on a real device so far), and the personal-WeChat (iLink Bot)
connector — direct chat only, with multi-bot QR login. On the agent side the
bridge has a pluggable backend port with `agentd` and OpenCode adapters, shared
and isolated/worktree project modes, a multi-endpoint pool and multi-location
OpenCode endpoints. OpenCode is covered by offline HTTP contract tests and a
live contract suite (`tests/test_opencode_live_contract.py`, skipped unless
`OPENCODE_BASE_URL` / `OPENCODE_PASSWORD` are set). For WeChat, QR login,
inbound text/image and outbound text are device-verified. Still pending device
checks: inbound file/video/voice, outbound video/file, typing, `-14` recovery,
two-bot concurrency, and the bare `login_via` command. WeChat group chat is not
supported by the platform/protocol. WeCom/Feishu/QQ verification details live in
[`docs/VERIFY-CAPABILITIES.md`](./docs/VERIFY-CAPABILITIES.md).

## TODO

- Future: add Discord and Slack connectors.

## Quick start

Prerequisite: a running backend (see above).

```sh
uv sync --all-extras          # includes the WeCom/Feishu/QQ extras and dev tools
cp .env.example .env          # fill in AGENTSERVE_TOKEN and platform secrets
cp config.example.yaml config.yaml   # config.yaml is gitignored
uv run tether --config config.yaml
```

Tether's state DB defaults to `<config dir>/.tether/<config name>/state.sqlite3`
(for example `.tether/config/state.sqlite3`); override it with `--db`. It holds
session routes **and WeChat bot tokens**, so keep it `0600` in a private
directory (backups are sensitive). An exclusive `<db>.lock` prevents two bridge
processes from sharing one state DB.

For personal WeChat, enable the channel and add a bot with
`identity.display_name` and `login_via` in `config.yaml` (see
`config.example.yaml` and design §5.4). Then send the bare `/login wechat` from
one of the mapped direct chats. At least one mapped channel
must be enabled, and there is no CLI login fallback: a bot whose mapped channels
are all offline cannot be logged in.

Run the checks:

```sh
uv run pytest
uv run ruff check .
uv run mypy src
```

`make build` produces a standalone PyInstaller binary, `make release` runs the
checks and bundles a versioned tarball, and `make wheel` builds the wheel/sdist.

## Configuration

YAML (`config.yaml`) holds non-secret configuration only. Platform credentials
are injected from the environment (12-factor); the personal-WeChat token is the
exception: it is obtained by QR login and stored in the SQLite state DB (not in
YAML or the environment). Strings support `${VAR}`, `${VAR:-default}` and `$$`
literals; `.env` is loaded at startup. See `config.example.yaml` for the common
IM/permissions keys and the OpenCode design doc for backend-specific keys.

`server.backend` / `server.pool[].backend` choose `agentd` or `opencode`. Each
endpoint is one backend connection: an `agentd` endpoint is one project and
working directory, while OpenCode may expose several locations behind one
`base_url` (use distinct endpoint `id`s). `projects.mode: isolated` leases a
per-conversation view — through the `agentd` control API or an OpenCode
worktree, depending on `projects.backend`. `reload: true` hot-applies the safe
subset (`group` / `access` / `permissions` / `commands` / `identity` /
`sessions` / `media`) without a restart.

## Project layout

```
src/tether/
  app.py            # assembly: config → connectors → agent backends → engine
  config.py         # pydantic models + YAML validation
  models.py         # Conversation / InboundMessage / OutboundPlan / Card …
  capabilities.py   # Capabilities / MarkdownLevel
  connector.py      # IMConnector Protocol + registry
  render/           # markdown-it parsing + capability-driven downgrade
  agent/            # AgentBackend port, registry, normalized events/DTOs
    agentd/         # go-agent-sdk HTTP/SSE adapter
    opencode/       # OpenCode v1/v2 HTTP/SSE adapter
  engine/           # router, streaming, turn, hitl, media, projects, commands
  store/            # SQLite routes + WeChat runtime state
  connectors/       # wecom / feishu / qq / wechat
tests/              # unit + contract tests (offline, fake agentd + fake OpenCode)
```

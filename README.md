# Tether

Tether bridges IM platforms (WeCom / Feishu / QQ / WeChat) with the
[go-agent-sdk](https://github.com/jiaweisky/go-agent-sdk) **HTTP/SSE API**
served by `cmd/agentd`. It lets users converse with
an Agent in IM conversations — direct chat and multi-user group chat — with
capability-aware streaming/rendering, HITL permission/question cards, and
bidirectional media where the platform and model support it.

Tether does **not** implement the agent loop: sessions, tools, permissions and
compaction live in the Go process. Tether does four things:

1. Protocol translation (IM message ⇄ prompt/event/attachment).
2. Conversation mapping (**one IM conversation = one agent session**) + HITL.
3. Experience polishing (streaming, Markdown degradation, tool progress, usage).
4. Media transfer between IM platforms and `agentd` in both directions:
   connector-side download/upload, with link/notice fallbacks when a platform
   or model cannot handle a type (inbound delivery policy is owned by `agentd`).

## Runtime dependency

Tether is only the IM bridge: it **requires a running `agentd` server from
[`jiaweisky/go-agent-sdk`](https://github.com/jiaweisky/go-agent-sdk)**.
`agentd` owns the agent loop, sessions, tools, permissions and project working
directory. It is not embedded in Tether and is not installed by `uv sync`.

Start `agentd` first (see that repository for its build/run instructions), then
point Tether at it with `server.base_url` (default `http://127.0.0.1:8787`) and
`server.token` (usually from `AGENTSERVE_TOKEN`). Without a reachable `agentd`,
Tether can connect to IM platforms but cannot answer messages.

The full design lives in [`docs/DESIGN-IM-BRIDGE.md`](./docs/DESIGN-IM-BRIDGE.md).

## Status

Implemented: the M0 core engine plus WeCom, Feishu and QQ (with the paths
verified on a real device so far), and the personal-WeChat (iLink Bot)
connector — direct chat only, with multi-bot QR login. For WeChat, QR login,
inbound text/image and outbound text are device-verified. Still pending device
checks: inbound file/video/voice, outbound video/file, typing, `-14` recovery,
two-bot concurrency, and the bare `login_via` command. WeChat group chat is not
supported by the platform/protocol. WeCom/Feishu/QQ verification details live in
[`docs/VERIFY-CAPABILITIES.md`](./docs/VERIFY-CAPABILITIES.md).

## TODO

- Future: add Discord and Slack connectors.

## Quick start

Prerequisite: a running `agentd` from
[`jiaweisky/go-agent-sdk`](https://github.com/jiaweisky/go-agent-sdk).

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

## Configuration

YAML (`config.yaml`) holds non-secret configuration only. Platform credentials
are injected from the environment (12-factor); the personal-WeChat token is the
exception: it is obtained by QR login and stored in the SQLite state DB (not in
YAML or the environment). See `config.example.yaml` for the full set of keys with
defaults.

The bridge talks to one or more `agentd` HTTP instances. **One instance = one
`Client` = one project/working directory**; writable agents can be isolated per
conversation (see §2.8/§2.9 of the design).

## Project layout

```
src/tether/
  app.py            # assembly: config → connectors → agentclient → engine
  config.py         # pydantic models + YAML validation
  models.py         # Conversation / InboundMessage / OutboundPlan / Card …
  capabilities.py   # Capabilities / MarkdownLevel
  connector.py      # IMConnector Protocol + registry
  render/           # markdown-it parsing + capability-driven downgrade
  agent/            # httpx + SSE AgentClient, event DTOs, error mapping
  engine/           # router, streaming, turn, hitl, media, commands
  store/            # SQLite routes + WeChat runtime state
  connectors/       # wecom / feishu / qq / wechat
tests/              # unit + contract tests (offline, fake agentd + fake SDK)
```

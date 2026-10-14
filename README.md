# Tether

Tether bridges IM platforms (WeCom / Feishu / QQ / WeChat) with the
[go-agent-sdk](https://github.com/jiaweisky/go-agent-sdk) **HTTP/SSE API**
served by `cmd/agentd` (formerly `cmd/agentserve`). It lets users converse with
an Agent in IM conversations — direct chat and multi-user group chat — with
streaming Markdown, HITL permission/question cards, and bidirectional media.

Tether does **not** implement the agent loop: sessions, tools, permissions and
compaction live in the Go process. Tether does four things:

1. Protocol translation (IM message ⇄ prompt/event/attachment).
2. Conversation mapping (**one IM conversation = one agent session**) + HITL.
3. Experience polishing (streaming, Markdown degradation, tool progress, usage).
4. Media transport in both directions with graceful degradation.

The full design lives in [`docs/DESIGN-IM-BRIDGE.md`](./docs/DESIGN-IM-BRIDGE.md).

## Status

Draft implementation of the M0 skeleton + M1 (WeCom direct/group text) plus the
full core engine. Feishu / QQ / WeChat connectors are scaffolded with declared
capabilities.

## Quick start

```sh
uv sync --extra wecom --extra dev
cp .env.example .env          # fill in AGENTSERVE_TOKEN and platform secrets
cp config.example.yaml config.yaml
uv run tether --config config.yaml
```

Run the checks:

```sh
uv run pytest
uv run ruff check .
uv run mypy src
```

## Configuration

YAML (`config.yaml`) holds non-secret configuration only; every secret is
injected from the environment (12-factor). See `config.example.yaml` for the
full set of keys with defaults.

The bridge talks to one or more `agentd` HTTP instances. **One instance = one
`Client` = one project/working directory**; writable agents are isolated per
group (see §2.8/§2.9 of the design).

## Project layout

```
src/tether/
  app.py            # assembly: config → connectors → agentclient → engine
  config.py         # pydantic-settings models + validation
  models.py         # Conversation / InboundMessage / OutboundPlan / Card …
  capabilities.py   # Capabilities / MarkdownLevel
  connector.py      # IMConnector Protocol + registry
  render/           # markdown-it parsing + capability-driven downgrade
  agent/            # httpx + SSE AgentClient, event DTOs, error mapping
  engine/           # router, route store, streaming, turn, hitl, media, commands
  connectors/       # wecom / feishu / qq / wechat
tests/              # unit + contract tests (offline, fake agentserve + fake SDK)
```

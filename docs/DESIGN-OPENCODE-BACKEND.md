# Tether 接入 OpenCode HTTP API 的扩展设计

- 状态：提案（Proposed，已按 review 修订）
- 日期：2026-10-28
- 修订要点：endpoint/location 标识、client/cache 键、location-aware 接口、配置脱敏、Form key/value 映射、事件缓存键、Route 迁移校验、事件名一步到位改为中性常量；`agentd` 明确特指 go-agent-sdk/cmd/agentd；核心抽象改为显式 `session_id` + typed event payload + `QuestionAnswer` + turn 边界；isolated/worktree 已给出完整 provider、配置和 Router 设计；已用真实 OpenCode + DeepSeek 官方 API（以及早期 mock provider）完成 spike，并与 opencode 源码/测试交叉验证，修正 `session.execution.*`、空 agent、pending 丢失、冷启动、snapshots/diff 路径一致性和文件路径等行为。
- 参考实现：`~/Documents/opencode`（opencode v2 HTTP API；落地时需记录具体 commit/version）
- HTTP API 参考与实测矩阵：[`docs/REF-OPENCODE-HTTP-API.md`](./REF-OPENCODE-HTTP-API.md)
- 相关代码：
  - `src/tether/agent/client.py`
  - `src/tether/agent/events.py`
  - `src/tether/engine/router.py`
  - `src/tether/engine/turn.py`
  - `src/tether/app.py`
  - `src/tether/config.py`
  - `src/tether/models.py`
  - `src/tether/store/sqlite.py`

## 1. 结论

推荐采用 **“后端端口 + 适配器（Ports & Adapters）”**，而不是在 `HttpAgentClient` 中按 URL、版本号或响应形状写分支：

```text
Connector -> App / Router / TurnEngine
                 |
                 v
          AgentBackend (Protocol)          # 后端无关的稳定接口
            /                \
   AgentdBackend         OpenCodeBackend
        |                     |
  agentd HTTP/SSE      opencode serve HTTP/SSE
```

核心原则：

1. **适配器负责所有后端差异**：认证、路径、错误格式、请求/响应字段、事件名、HITL 语义、消息快照解析。
2. **Tether 内核只消费规范化后的对象**：`Event`、`PendingPermission`、`PendingQuestion`、`TurnSnapshot` 等。
3. **后端能力用 `BackendProfile` 声明**，不要让内核到处判断 `if backend == "opencode"`。
4. **配置显式选择后端**，并把后端、endpoint 标识和 session 位置持久化到 `Route`。
5. **先支持 shared 模式**，isolated 项目隔离作为第二阶段能力。

Tether 仍然只做 IM 桥接，不启动、不管理后端进程。两个后端都作为外部 HTTP 服务运行。

### 术语约定

- **`agentd`**：本文中的 `agentd` 特指 **go-agent-sdk** 仓库中的 `cmd/agentd`。
- **`opencode`**：指 OpenCode 的 `opencode serve` v2 HTTP API。
- **backend id**：`"agentd"` 是 go-agent-sdk/cmd/agentd 的专用 backend id，`"opencode"` 对应 OpenCode；配置中的 `backend` 字段填这两个值。
- 若将来接入另一个也叫 agentd 的实现，必须使用新的 backend id，不能复用这里的 `"agentd"`。

## 2. 当前代码与 agentd 的耦合点

现有实现虽然已经有 `AgentClient` 这个名字，但实际仍然是一个具体实现：

- `src/tether/agent/client.py:29`：`HttpAgentClient` 直接实现所有 agentd API。
- `src/tether/engine/router.py:25`：`ClientFactory` 固定返回 `HttpAgentClient`。
- `src/tether/app.py:1131`、`src/tether/engine/turn.py:146`：直接依赖 agentd 事件名，例如 `session.next.text.delta`、`permission.v2.asked`。
- `src/tether/app.py:1790`：`assistant_text()` / `tool_media()` 直接解析 agentd 的消息结构。
- `src/tether/app.py:984`：`/config` 直接读取 agentd 的 `/api/config?section=servers`。
- `src/tether/app.py:1533`：健康检查直接按 agentd 的 `/api/health` 组织。
- `src/tether/engine/projects.py`：isolated 模式依赖 agentd 的 `/admin/projects` control API。
- `src/tether/config.py:39`：`ServerPoolEntry` 只有 `base_url/token`，没有 backend、认证方式、目录等概念。
- `src/tether/models.py:267`：`Route` 没有 `backend` 和 OpenCode 的 `location/directory`。
- `src/tether/agent/usage.py`：默认按 agentd 的 provider metadata 格式解析 usage。

因此不能只写一个 `OpenCodeClient` 然后替换类名，否则这些差异会散落到 `app.py`、`turn.py`、`router.py` 中。

## 3. 目标模块结构

建议重构为：

```text
src/tether/agent/
  base.py              # AgentBackend Protocol、BackendProfile、BackendDescription、TurnSnapshot
  events.py            # 规范化 Event 与 DTO
  registry.py          # 根据 ServerEndpoint.backend 创建适配器
  http.py              # 共用 HTTP/SSE、错误解包、认证策略
  agentd/              # go-agent-sdk/cmd/agentd adapter
    __init__.py
    client.py          # 现有 HttpAgentClient -> AgentdBackend
    events.py          # agentd 原生事件 -> 规范事件
    messages.py        # agentd 消息 -> TurnSnapshot
    errors.py
  opencode/
    __init__.py
    client.py          # OpenCodeBackend
    events.py          # session.text.* / tool.* / form.* -> 规范事件
    forms.py           # OpenCode Form <-> PendingQuestion
    models.py          # Model.Ref 的解析/格式化
    messages.py        # OpenCode messages -> TurnSnapshot
    config.py          # describe() / config_summary() 与强制脱敏
    errors.py
```

保留 `src/tether/agent/client.py` 作为兼容别名：

```python
AgentClient = AgentdBackend
HttpAgentClient = AgentdBackend
```

## 4. 核心抽象

### 4.1 `AgentBackend` Protocol

在 `agent/base.py` 中定义后端无关的稳定接口。标识符必须唯一且明确：

- `profile.backend_id`：`"agentd"`（go-agent-sdk/cmd/agentd）或 `"opencode"`；
- `endpoint_id`：`ServerEndpoint.id`，由构造 backend 时注入；
- 不再使用含义模糊的 `AgentBackend.name`。

```python
class AgentBackend(Protocol):
    endpoint_id: str                 # ServerEndpoint.id
    profile: BackendProfile          # profile.backend_id 是后端类型

    async def aclose(self) -> None: ...

    # discovery / metadata
    async def health(self) -> bool: ...
    async def describe(self) -> BackendDescription: ...
    async def config_summary(self, *, location: str | None = None) -> ConfigSummary: ...
    async def list_agents(self, *, location: str | None = None) -> list[AgentInfo]: ...
    async def list_models(self, *, location: str | None = None) -> list[ModelInfo]: ...
    async def agent_tools(
        self, agent: str, *, location: str | None = None
    ) -> list[ToolInfo]: ...
    async def active_sessions(self) -> set[str]: ...

    # session
    async def create_session(
        self,
        *,
        agent: str,
        model: str | None = None,
        title: str | None = None,
        location: str | None = None,
        permissions: list[PermissionRule] | None = None,
    ) -> SessionInfo: ...
    async def get_session(self, sid: str) -> SessionInfo: ...
    async def set_agent(self, sid: str, agent: str) -> None: ...
    async def set_model(self, sid: str, model: str) -> None: ...
    async def set_title(self, sid: str, title: str) -> None: ...
    async def delete_session(self, sid: str) -> None: ...

    # execution
    async def prompt(
        self,
        sid: str,
        *,
        prompt: str,
        files: list[PromptFile] | None = None,
        id: str | None = None,
        delivery: str = "queue",
    ) -> None: ...
    async def interrupt(self, sid: str) -> None: ...
    async def compact(self, sid: str) -> bool: ...
    async def wait(self, sid: str, timeout_s: float) -> bool: ...

    # read / recovery
    async def turn_snapshot(
        self, sid: str, *, after_message_id: str | None = None
    ) -> TurnSnapshot: ...
    async def session_replay(
        self, sid: str, *, after_seq: int = -1
    ) -> list[Event]: ...

    # interaction
    async def reply_permission(
        self, sid: str, rid: str, *, reply: str, message: str | None = None
    ) -> None: ...
    async def reply_question(
        self, sid: str, rid: str, answer: QuestionAnswer
    ) -> None: ...
    async def reject_question(
        self, sid: str, rid: str, *, message: str | None = None
    ) -> None: ...
    async def list_permissions(
        self, *, locations: Sequence[str] | None = None
    ) -> list[PendingPermission]: ...
    async def list_questions(
        self, *, locations: Sequence[str] | None = None
    ) -> list[PendingQuestion]: ...

    # events
    def events(self) -> AsyncIterator[Event]: ...
```

返回语义：

- `active_sessions() -> set[str]`：当前处于运行状态的 session id 集合。
- `compact() -> bool`：`True` 表示后端已接受/入队压缩，不表示压缩已完成。
- `wait() -> bool`：`True` 表示在 timeout 内变为 idle；`False` 表示超时；传输/协议错误抛 `AgentError`。
- `turn_snapshot(after_message_id=...)`：只返回该消息之后的当前 turn；`after_message_id=None` 表示 last turn。
- `events()`：best-effort live 流；断线时抛异常，由 `app._consume_events()` 负责重连和 reconcile。
- `session_replay(sid, after_seq=-1) -> list[Event]`：按 session 的**有限** durable replay，用于补断线缺口；不要求 follow。OpenCode 有 persist 时用 `/log`，默认 CLI 返回空，由 projection resync 兜底。

`location` 语义：

- `agentd`：每个 endpoint 固定绑定一个 working directory；`location` 必须为 `None` 或与 endpoint 的 `working_directory` 一致。
- `opencode`：`location` 是 `location.directory`。
- `location=None` 只允许用于 shared 模式；一旦 `Route.location` 存在，Router 必须显式传入，不能静默回退到 endpoint 默认目录。
- `list_permissions()` / `list_questions()` 的 `locations` 由 Router 根据已知 route 聚合；未传时只查询 endpoint 的默认 location。

`PromptFile` 是统一的附件 DTO：

```python
@dataclass
class PromptFile:
    uri: str
    name: str | None = None
    mime: str | None = None
    description: str | None = None

@dataclass(frozen=True)
class PermissionRule:
    action: str
    resource: str = "*"
    effect: str = "ask"      # allow | deny | ask
```

`create_session(permissions=...)` 的语义：

- OpenCode：映射到 `session.create.permissions`（`Permission.Ruleset`），用于 isolated 会话的工具策略；
- agentd：忽略该参数，工具策略由 agentd 的 server/control 配置决定；
- `permissions=None` 表示使用后端默认策略。

`SessionInfo` 必须包含实际 location，便于 Router 写入 `Route.location`：

```python
@dataclass
class SessionInfo:
    id: str
    agent: str | None = None
    model: str | None = None
    title: str | None = None
    location: str | None = None
```

`turn_snapshot()` 用来替代 `app.py` 中的 `assistant_text()` 和 `tool_media()`：

```python
@dataclass
class TurnSnapshot:
    turn_id: str | None = None
    text: str | None = None
    media: list[RichMedia] = field(default_factory=list)
```

语义：

- `text`：当前 turn 最后一条 assistant 消息的 text；
- `media`：当前 turn 内所有 assistant tool content 的 file parts 与 `ToolStructured.files`；`metadata.files` 不是通用来源，不得包含上一轮；
- `turn_id`：后端能提供时填写，否则为 `None`；
- `after_message_id=None` 时，按后端可用的 turn 边界取最后 turn；OpenCode 使用最后一条 user 消息；`turn_id` 可以为 `None`。

这样 `_recover_active()`、`_reconcile()` 不再知道 agentd 或 OpenCode 的消息结构。

`QuestionAnswer` 取代 label 列表，避免 label 反查：

```python
@dataclass
class QuestionAnswer:
    # key: QuestionItem.key；values: 选中的 QuestionOption.value 或自由文本
    values: dict[str, list[str]] = field(default_factory=dict)
```

`QuestionItem` / `QuestionOption` 必须携带 key/value：

```python
@dataclass
class QuestionOption:
    label: str
    value: str
    description: str = ""

@dataclass
class QuestionItem:
    key: str
    question: str
    header: str = ""
    options: list[QuestionOption] = field(default_factory=list)
    multiple: bool = False
    custom: bool = False
```

`reply_question()` 直接接收 `QuestionAnswer`；adapter 不得依赖 label 到 value 的隐式映射。agentd 的 question 可使用问题序号作为 key、label 作为 value；OpenCode 使用 Form field key 和 option.value。

后端描述 `BackendDescription` 用于 `/status` / `/config`，只包含可安全展示的字段：

```python
@dataclass
class BackendDescription:
    backend_id: str              # "agentd" | "opencode"
    endpoint_id: str             # ServerEndpoint.id
    version: str | None = None
    pid: int | None = None
    urls: list[str] = field(default_factory=list)
    locations: list[str] = field(default_factory=list)
    detail: ConfigSummary | None = None   # 类型化的安全摘要，不是原始配置

@dataclass
class ConfigSummary:
    default_agent: str | None = None
    default_model: str | None = None
    providers: list[str] = field(default_factory=list)
    agents: int = 0
    models: int = 0
    locations: list[str] = field(default_factory=list)
```

`get_info()` 不再是公开协议方法；`describe()` 是唯一的元信息入口。`config_summary()` 只返回 `ConfigSummary` 或同等的 white-list 字段，不能直接返回后端原始配置。

### 4.2 `BackendProfile`

避免和 IM 的 `Capabilities` 混淆，后端能力命名为 `BackendProfile`。所有字段都必须由 adapter 显式设置，不依赖默认值：

```python
@dataclass(frozen=True)
class BackendProfile:
    backend_id: str                  # "agentd"（go-agent-sdk/cmd/agentd）| "opencode"
    display_name: str
    supports_tool_discovery: bool
    supports_session_replay: bool
    supports_cross_session_permissions: bool
    supports_cross_session_questions: bool
    supports_rich_forms: bool
    supports_session_wait: bool
    supports_session_title: bool
    supports_isolated_projects: bool
    supports_multi_location: bool
    supports_changed_files: bool
    supports_pending_interaction_recovery: bool
    event_protocol: str
```

| 字段 | 含义 | 消费方 | agentd | opencode |
|---|---|---|---|---|
| `backend_id` | 后端类型，不是 endpoint 标识 | registry / Route / 日志 | `"agentd"` | `"opencode"` |
| `supports_tool_discovery` | 是否有独立的 tool 列表端点 | `router.warm_base()`、诊断 | true | false |
| `supports_session_replay` | 是否能按 session + after seq 做 durable replay | `_reconcile()` | true | 默认 false；persist 开启时 true |
| `supports_cross_session_permissions` | 能否按 location 列出所有 pending permission | `_restore_hitl()` | true | true（per location） |
| `supports_cross_session_questions` | 能否按 location 列出所有 pending question/form | `_restore_hitl()` | true | true（per location） |
| `supports_rich_forms` | 是否能返回 choice 之外的 Form 字段 | `opencode/forms.py`、HITL 能力判断 | false | true |
| `supports_session_wait` | 是否有 wait 端点 | 未来的主动等待逻辑 | true | true（客户端超时） |
| `supports_session_title` | 是否能设置标题 | `/new`、标题同步 | true | true |
| `supports_isolated_projects` | 是否支持 isolated/worktree | `validate_startup()` | true | false（Phase 1）；Phase 3 后 true |
| `supports_multi_location` | 是否允许同一 `base_url` 配多个 endpoint | `validate_startup()` | false | true |
| `supports_changed_files` | 后端是否具备变更文件路径能力（不是 per-session 保证） | `media.outbound.auto_files` | true | 有该能力；实际可用取决于 location 的 git、snapshots、canonical path |
| `supports_pending_interaction_recovery` | 后端重启后相同 pending form/permission 是否仍可查询 | `_restore_hitl()` | false（未验证；agentd pending 也是内存态，重启可能重新 ask 而非保留原 id） | false（spike 确认重启后丢失） |
| `event_protocol` | adapter 原生事件协议版本 | 诊断、契约测试 | `"go-agent-sdk.agentd.v2"` | `"opencode.v2"` |

内核只根据这些字段决定行为，不再根据 `backend_id == "opencode"` 写分支。

### 4.3 规范化事件

事件名必须**一步到位**改为后端中性名称，不再保留 agentd 事件名作为内部规范事件。`src/tether/agent/events.py` 中的常量直接使用中性值，例如：

```python
TEXT_DELTA = "text.delta"
TOOL_SUCCESS = "tool.success"
PERMISSION_ASKED = "permission.asked"
QUESTION_ASKED = "question.asked"
TURN_STATUS = "turn.status"
```

规范事件名：

```text
server.connected
turn.status
text.started / text.delta / text.ended
reasoning.started / reasoning.delta / reasoning.ended
step.started / step.ended / step.failed
tool.called / tool.progress / tool.success / tool.failed
compaction.started / compaction.delta / compaction.ended
permission.asked / permission.replied
question.asked / question.replied / question.rejected
attachment.omitted          # 可选事件；OpenCode 不产生
title.updated               # 可选事件
```

`Event` 必须显式携带 `session_id`，不允许再从后端 `data` 字段推导：

```python
EventType = Literal[
    "server.connected", "turn.status",
    "text.started", "text.delta", "text.ended",
    "reasoning.started", "reasoning.delta", "reasoning.ended",
    "step.started", "step.ended", "step.failed",
    "tool.called", "tool.progress", "tool.success", "tool.failed",
    "compaction.started", "compaction.delta", "compaction.ended",
    "permission.asked", "permission.replied",
    "question.asked", "question.replied", "question.rejected",
    "attachment.omitted", "title.updated",
]

@dataclass(frozen=True)
class Event:
    id: str
    type: EventType
    session_id: str | None
    data: EventData          # 下面表格定义的 typed union
    durable: DurableRef | None = None
```

`DurableRef` 携带 aggregateID/seq/version，用于 replay cursor、去重和恢复；不用于业务语义。

`EventData` 是 tagged union，每种事件使用独立 dataclass，不再使用未约束的 `dict[str, Any]`。关键 payload 契约：

| 事件 | payload 字段 | 说明 |
|---|---|---|
| `server.connected` | `{}` | 无 session |
| `turn.status` | `status: StatusInfo` | `StatusInfo.type = idle / busy / retry`；retry 带 `attempt/message/next` |
| `text.started` | `ordinal: int \| None` | 可选 per-part 序号 |
| `text.delta` | `delta: str` | 增量文本 |
| `text.ended` | `text: str` | **当前 turn 的完整文本**，不是单个 part |
| `reasoning.*` | 同 text | 是否展示由 IM 配置决定 |
| `step.started` | `{}` | |
| `step.ended` | `tokens: UsageTokens \| None`, `cost: float \| None`, `files: list[str]` | files 为相对/绝对路径 |
| `step.failed` | `error: str` | 已简化为可展示文本 |
| `tool.called` | `name: str`, `tool_id: str \| None` | |
| `tool.progress` | `content: list[ToolPart]`, `structured: ToolStructured \| None` | |
| `tool.success` | `content: list[ToolPart]`, `structured: ToolStructured \| None` | 文件 part 复用现有提取逻辑 |
| `tool.failed` | `error: str` | |
| `compaction.started` | `{}` | |
| `compaction.delta` | `text: str` | 当前内核可忽略 |
| `compaction.ended` | `{}` | |
| `permission.asked` | `request: PendingPermission` | |
| `permission.replied` | `request_id: str`, `reply: str` | |
| `question.asked` | `request: PendingQuestion` | `QuestionItem/QuestionOption` 必须带 key/value |
| `question.replied` | `request_id: str` | |
| `question.rejected` | `request_id: str` | |
| `attachment.omitted` | `name: str`, `reason: str`, `detail: str \| None` | 可选 |
| `title.updated` | `title: str` | 可选 |

`ToolPart` 至少支持：

```python
@dataclass(frozen=True)
class StatusInfo:
    type: Literal["idle", "busy", "retry"]
    attempt: int | None = None
    message: str | None = None
    next: int | None = None

@dataclass(frozen=True)
class TextPart:
    text: str

@dataclass(frozen=True)
class FilePart:
    uri: str
    mime: str | None = None
    name: str | None = None

ToolPart = TextPart | FilePart

@dataclass(frozen=True)
class ToolStructured:
    files: list[str] = field(default_factory=list)
```

`TurnEngine` 的媒体提取改为消费 `FilePart` / `ToolStructured.files`，不再对未约束的 dict 做递归 `extract_file_parts()`。

投递语义：

- **全局 SSE 是 best-effort live**，断线后不能只依赖它；
- `durable.seq` 用于 per-session replay cursor、去重和恢复，不是只用于诊断；
- 后端必须提供“按 session + after seq 的 durable replay”能力（agentd: `/api/session/{sid}/event?after=` 或 `/history?after=`；OpenCode: `/api/experimental/session/{sid}/log?after=`，follow 可选）；
- 断线后统一走 `session replay + turn_snapshot + pending 列表`；只做 `active_sessions` 恢复会漏掉在断线期间已经结束的 turn；
- `log.synced` / durable watermark 用于标记 replay 与 live 的边界；
- adapter 不得伪造 `attachment.omitted` / `title.updated`；后端没有对应事件时就不发。

职责划分：

- `agentd/events.py` 负责把 `session.next.*`、`permission.v2.*` 等 agentd 原生事件映射为上述中性事件；
- `opencode/events.py` 负责把 `session.text.*`、`session.tool.*`、`permission.asked`、`form.*` 等 OpenCode 原生事件映射为同一套中性事件；
- `TurnEngine`、`app._route_event()` 只引用中性常量，不再出现 `session.next.*` 或 `permission.v2.*`。

这是一次性重构，不分两个阶段：

- Phase 0 同步修改 `agent/events.py` 常量值、`Event` 数据结构和 `TurnEngine` handler 键；
- `agentd/events.py` 提供原生到中性的映射；
- 现有 `tests/test_client_contract.py` 的断言改为中性事件名和 typed payload；
- 新增 agentd 原生事件 fixture，验证映射结果；
- 不保留“旧 agentd 事件名 + 新中性事件名”双轨制，避免内核长期兼容两套词汇。

**事件规范化必须发生在适配器内部**，`TurnEngine` 和 `app._route_event()` 不应看到任何后端的原生事件名。

## 5. OpenCode 适配器设计

### 5.1 传输、认证、基础路径

OpenCode v2 API 和 agentd 一样位于 `/api/*`，这是有利条件，但仍有关键差异：

| 项目 | agentd | OpenCode |
|---|---|---|
| 健康检查 | `GET /api/health` | 无独立健康端点，用 `GET /api/info` 或 `/api/model` 探活 |
| 认证 | `Authorization: Bearer <token>` | HTTP Basic：`Authorization: Basic base64("opencode:<password>")`；也支持 `auth_token` 查询参数 |
| 目录 | 每个进程绑定一个 working directory | 每个请求可带 `location[directory]` 或 `x-opencode-directory`，session 自身也带 location |
| 错误体 | `{"error":"code","message":"..."}` | `{"_tag":"SessionNotFoundError","message":"..."}` 等 |
| SSE frame | `event: message\ndata: {...}` | 通常 `data: {...}\n\n`，无 event 字段 |

参考：

- `packages/server/src/auth.ts`
- `packages/server/src/middleware/authorization.ts`
- `packages/server/src/location.ts`
- `packages/server/src/event-feed.ts`

适配器职责：

- 统一认证头由 `OpenCodeBackend` 构造，`AgentdBackend` 保持 Bearer。
- 统一错误映射到现有 `AgentError`：

```text
SessionNotFoundError / PermissionNotFoundError / FormNotFoundError / MessageNotFoundError -> not_found
UnauthorizedError -> unauthorized
ConflictError / SessionBusyError / FormAlreadySettledError -> conflict
InvalidRequestError / SchemaError -> bad_request
ServiceUnavailableError -> unavailable
其他 -> internal，并保留 message/status
```

- 对需要 location 的端点统一注入 `location`：
  - `create_session` 在 payload 里传 `location: {directory}`；
  - 其他 location 作用域端点优先用 query `location[directory]`，交给 httpx 做 URL 编码；
  - `x-opencode-directory` 作为兼容方案保留，但需要注意该 header 会被服务端 `decodeURIComponent`，路径中的非 ASCII / `%` 需要测试。
- `working_directory` 必须是绝对路径，并在配置校验阶段验证；OpenCode 侧的 location 也必须存在且可访问。

### 5.2 Discovery 与模型引用

OpenCode 的响应通常包在 `Location.response` 中：

```json
{ "location": {...}, "data": [...] }
```

现有 `_data_from_response()` 已经会解包 `data`，可以复用。

| Tether 方法 | OpenCode 端点 | 字段映射 |
|---|---|---|
| `list_agents` | `GET /api/agent` | `id/description/mode/hidden/model`；`model` 是 `Model.Ref`，适配器格式化为 `provider/id#variant` |
| `list_models` | `GET /api/model` | `id` 格式化为 `providerID/modelID`；`inputs = capabilities.input`；`context_limit = limit.context`；`output_limit = limit.output`；`protocol = providerID` |
| `agent_tools` | 无对应端点 | 返回 `[]`，并设置 `supports_tool_discovery=False` |
| `active_sessions` | `GET /api/session/active` | 响应 `{"data": {sid: {"type": "running"}}}` 由 adapter 转为 `set[str]` |

OpenCode 的 discovery 结果按 **location** 作用域，因此 Router 的 `_agent_cache` / `_models_cache` 不能只按 `base_url` 建键，必须按 `(endpoint_id, location)` 建键。

**Spike 结果：OpenCode 冷启动一个 location 约需 19–31 秒。** 因此：

- `server.request_timeout_s` 默认 30 秒对 OpenCode 太短，部署时应设为 60–120 秒；
- `router.warm_base()` 必须用 endpoint 的 working_directory 预热 location；
- 首次 `list_agents/list_models/create_session` 遇到超时要按 `unavailable` 重试，不能直接判定配置错误。

Agent 选择不能沿用「第一个非 hidden」的简单规则。OpenCode 的 `Agent.Info` 包含：

```ts
mode: "subagent" | "primary" | "all"
```

语义：

- `primary`：可作为会话主 agent；
- `subagent`：只能被 task 工具调用，不能作为主 agent；
- `all`：两者都可。

`build` 是 OpenCode 的默认 agent ID（`Agent.defaultID`），但 **bare server 的 `/api/agent` 可以是空数组**；session 未指定 agent 时仍会以 `build` 运行（spike 已确认 `session.step.started.agent == "build"`）。因此：

- OpenCode adapter 的 `list_agents()` 在 API 返回空数组时，应返回一个合成的 `AgentInfo(id="build", mode="primary", hidden=False)`；
- 有真实 agent 列表时，优先选择配置的 `default_agent`，其次 `mode in ("primary", "all")` 且非 hidden；
- 不允许静默选择 `subagent`。

参考：

- `packages/protocol/src/groups/agent.ts`
- `packages/protocol/src/groups/model.ts`
- `packages/schema/src/agent.ts`
- `packages/schema/src/model.ts`

OpenCode 模型是结构化引用：

```ts
Model.Ref = { id, providerID, variant? }
```

Tether 的 `Route.model` 和 `ModelInfo.id` 是字符串，因此统一采用：

```text
providerID/id
providerID/id#variant
```

适配器内部提供：

```python
parse_model_ref("anthropic/claude-sonnet-4-5") -> {"providerID": "anthropic", "id": "...", ...}
format_model_ref({"providerID": "anthropic", "id": "..."}) -> "anthropic/..."
```

如果配置里只写了裸 model id，适配器可以先在 `GET /api/model` 结果中匹配唯一 id，匹配不到则给出明确错误。

`context_limit` / `output_limit` 查找必须忽略 `#variant`，因为 `Model.Info` 通常只按 `providerID/modelID` 暴露；带 variant 的 `Route.model` 不应导致 usage 行丢失上下文窗口。

### 5.3 Session 生命周期

| 操作 | OpenCode 端点 | 注意 |
|---|---|---|
| 创建 | `POST /api/session` | payload 可含 `agent`、`model: Model.Ref`、`title`、`location: {directory}` |
| 获取 | `GET /api/session/:sid` | 返回 `{data: Session.Info}` |
| 删除 | `DELETE /api/session/:sid` | 204 |
| 切换 agent | `POST /api/session/:sid/agent` | payload `{agent}` |
| 切换 model | `POST /api/session/:sid/model` | payload `{model: Model.Ref}` |
| 改标题 | `PATCH /api/session/:sid` | **不是** agentd 的 `/title` |
| 中断 | `POST /api/session/:sid/interrupt` | OpenCode 返回 `{interrupted: bool}`，支持 `?resume=true`；adapter 可忽略返回值 |
| 压缩 | `POST /api/session/:sid/compact` | 返回 inbox 数据，适配器转成 `bool` |
| 等待 | `POST /api/experimental/session/:sid/wait` | 无 timeout 参数；适配器用客户端超时或标记 `supports_session_wait` |

参考：`packages/protocol/src/groups/session.ts`。

`create_session(permissions=...)` 映射为 payload 的 `permissions`（`Permission.Ruleset`），用于 isolated 会话的工具策略；`None` 时省略。

`SessionInfo` 适配：

```python
SessionInfo(
    id=data["id"],
    agent=data.get("agent"),
    model=format_model_ref(data.get("model")),
    title=data.get("title"),
    location=_location_directory(data.get("location")),
)
```

### 5.4 Prompt 与附件

OpenCode prompt payload：

```json
{
  "text": "hello",
  "files": [{"uri": "data:image/png;base64,...", "name": "a.png"}],
  "id": "...",
  "delivery": "queue"
}
```

与 Tether 当前请求的差异：

- `prompt` -> `text`；
- OpenCode `FileAttachment` 只有 `uri/name/description`，没有 `mime`；mime 从 data URL 推断。适配器应把 `{uri,mime,name}` 规范化为 OpenCode 形状，避免 schema 拒绝未知字段。
- `delivery` 取值同样是 `queue | steer`，可直接复用。
- `id` 可直接传现有 `route.key:message_id`。

参考：

- `packages/schema/src/prompt-input.ts`
- `packages/schema/src/session-inbox.ts`

适配器中的 `prompt()` 只负责转换，不改变 `TurnEngine` 的调用方式。

### 5.5 事件映射

OpenCode 事件定义见：

- `packages/schema/src/session-event.ts`
- `packages/schema/src/session-status-event.ts`
- `packages/schema/src/permission.ts`
- `packages/schema/src/form.ts`

建议映射表：

| OpenCode 原生事件 | Tether 规范事件（中性常量） | 数据映射 |
|---|---|---|
| `server.connected` | `SERVER_CONNECTED` | `session_id=None`，`data={}` |
| `session.text.started` | `TEXT_STARTED` | `session_id` 显式填写；缓存键 `(sessionID, assistantMessageID, ordinal)` |
| `session.text.delta` | `TEXT_DELTA` | `data=TextDelta(delta)`；缓存键同上 |
| `session.text.ended` | `TEXT_ENDED` | `data=TextEnded(当前 turn 完整文本)`；缓存键同上 |
| `session.reasoning.started/delta/ended` | `REASONING_*` | 同 text |
| `session.step.started` | `STEP_STARTED` | `data={}` |
| `session.step.ended` | `STEP_ENDED` | `data=StepEnded(tokens, cost, files)`；`tokens` 已是规范化格式 |
| `session.step.failed` | `STEP_FAILED` | `data=StepFailed(error)` |
| `session.tool.input.started` | `TOOL_CALLED` | `data=ToolCalled(name, tool_id)`；缓存 `{(sessionID, assistantMessageID, id) -> name}` |
| `session.tool.called` | 可选 `TOOL_CALLED` | 若没有 name，用缓存补全 |
| `session.tool.progress` | `TOOL_PROGRESS` | `data=ToolProgress(content, structured)` |
| `session.tool.success` | `TOOL_SUCCESS` | `data=ToolSuccess(content, structured)` |
| `session.tool.failed` | `TOOL_FAILED` | `data=ToolFailed(error)` |
| `session.execution.started` | `TURN_STATUS` | `data=TurnStatus(busy)`；也作为 activity |
| `session.execution.succeeded` | `TURN_STATUS` | `data=TurnStatus(idle)`；**turn 结束的权威事件** |
| `session.execution.failed` | `TURN_STATUS` | `data=TurnStatus(idle)`；错误已由 `step.failed` 展示 |
| `session.execution.interrupted` | `TURN_STATUS` | `data=TurnStatus(idle)` |
| `session.status`（可选） | `TURN_STATUS` | `data=TurnStatus(status)`；`status.type=idle/busy/retry` |
| `session.idle`（旧事件，可选） | `TURN_STATUS` | `data=TurnStatus(idle)`，兼容旧版本 |
| `session.retry.scheduled` | `TURN_STATUS` | `data=TurnStatus(retry, attempt, next)` |
| `session.compaction.started/ended` | `COMPACTION_*` | typed payload |
| `session.compaction.delta` | `COMPACTION_DELTA` | 目前内核不消费，可忽略 |
| `permission.asked` | `PERMISSION_ASKED` | `data=PermissionAsked(request)` |
| `permission.replied` | `PERMISSION_REPLIED` | `data=PermissionReplied(request_id, reply)` |
| `form.created` | `QUESTION_ASKED` | `session_id=form.sessionID`，`data=QuestionAsked(request)`；仅映射 `metadata.kind == "question"` 或可安全转换的表单 |
| `form.replied` | `QUESTION_REPLIED` | `session_id` 显式填写，`data=QuestionReplied(request_id=id)` |
| `form.cancelled` | `QUESTION_REJECTED` | `session_id` 显式填写，`data=QuestionRejected(request_id=id)` |

注意：`Event.session_id` 是规范事件的显式字段，adapter 必须直接设置它；OpenCode 的 `form.created` 从 `form.sessionID` 读取，不再要求把 sessionID 塞进 `data`。

**Spike 结果（2026-10-28，当前工作树）**：实际 `/api/event` 观察到 `session.execution.started/failed`、`step.*`、`form.*`、`permission.asked`，当前 server 没有发布 `session.status`；但 event manifest 定义了它，其他版本/部署可能发送。因此：`session.execution.succeeded/failed/interrupted` 必须映射为 `TURN_STATUS idle`，同时保留 `session.status` / `session.idle` 的兼容映射，不能只押其中一种。

`session.step.ended.tokens` 已经是 `{input, output, reasoning, cache: {read, write}}`，与 Tether `UsageTokens.from_normalized()` 期望的格式一致，不需要 provider metadata 解析；仍建议加一条回归测试，防止 OpenCode 改变语义。

#### 文本事件的额外注意点


OpenCode 的 `session.text.ended` 是“按 ordinal 的单个文本片段”，而 Tether 当前 `_on_text_ended()` 会直接替换整个 `controller.text`：

```python
# src/tether/engine/turn.py:329（当前实现；目标是 TextEnded.text）
if data.get("text") is not None:
    self.controller.text = str(data["text"])
```

目标接口中 `TextEnded.text` 表示当前 turn 的完整文本；adapter 负责把 OpenCode 的分段事件聚合成这个值。

如果一次 assistant 消息有多个 text part，直接映射可能覆盖前一段。建议在 `OpenCodeBackend` 内按 `(sessionID, assistantMessageID, ordinal)` 维护文本片段：

- `session.text.delta` 正常推送增量；
- `session.text.ended` 记录该 ordinal 的最终文本；
- 向 Tether 发 `TEXT_ENDED` 时发送“本 turn 所有已结束 text part 的拼接文本”；
- 在规范事件 `turn.status` 为 idle 时清空该 turn 的缓存，来源可以是 `session.status`、`session.idle` 或 `session.execution.*`。

需要区分“单个 text part 的结束”和“整个 turn 的文本”：adapter 只在需要交给 Tether 的边界发送拼接后的 `TEXT_ENDED`，避免多 step / 多 text part 时倒退。

#### 工具媒体

OpenCode tool success 的 `content` 是：

```json
[{"type":"file","uri":"data:...","mime":"image/png","name":"x.png"}]
```

adapter 把 `type=file` 转成规范 `FilePart`，`TurnEngine` 直接从 typed `ToolPart` 提取媒体，不再依赖弱类型 dict 遍历。

**Spike + 源码交叉验证**：

- `write` 的 `session.tool.success` 只有文本 content 和 `metadata.truncated`，没有文件路径；
- `edit`/`patch` 源码会返回 `metadata.files`，但 `write` 不会，因此不能依赖 tool success 统一获取文件；
- 变更文件应从 `session.step.ended.files` 获取：spike 中 `write` 后该事件返回 `files: ["out.txt"]`，前提是项目是 git 仓库、snapshots 开启、且 location 路径与 `project.canonical` 一致；
- `GET /api/session/:sid/diff` 同样返回 `FileDiff[]`，spike 已验证；
- 之前 diff 为空是测试路径 `/var` 与 canonical `/private/var` 不一致导致 snapshot `Location is outside the project`，不是功能缺失；
- Tether 应把 `STEP_ENDED.files` 映射到 `ToolStructured.files` / `outputPaths`；tool success 只是补充，不是唯一来源。


### 5.6 Permission

字段几乎兼容：

```json
{
  "id": "per_...",
  "sessionID": "ses_...",
  "action": "edit",
  "resources": ["src/a.ts"],
  "save": ["*"],
  "metadata": {},
  "source": {"type":"tool","messageID":"...","id":"..."}
}
```

差异：

- `POST /api/session/:sid/permission` 是**评估**权限：返回 `effect=allow/deny/ask`；只有 `ask` 才会创建 pending request，`allow/deny` 时对返回的 id 调 reply 会 404。Tether 不应把它当作“创建 pending”接口。
- 回复字段是 `decision`，不是 `reply`：

```json
POST /api/session/:sid/permission/:rid/reply
{"decision": "once" | "always" | "reject", "message": "..."}
```

- 全局待处理列表是 `GET /api/permission/request?location[directory]=...`；
- 按 session 查询是 `GET /api/session/:sid/permission`。

参考：`packages/protocol/src/groups/permission.ts`。

`AgentdBackend.reply_permission()` 使用 `{"reply": ...}`，`OpenCodeBackend` 使用 `{"decision": ...}`，这个差异完全封装在适配器内。

`decision=reject` 会拒绝同一 session 的整批 pending permission；`decision=always` 只有在 request 带 `save` 时才会写 saved permission。Tether 若需要逐条拒绝，必须自行控制请求粒度。

### 5.7 Question 与 Form

OpenCode 的 `question` 工具实际通过 `Form` 实现：

- `packages/core/src/tool/plugin/question.ts` 把每个 question 转成字段 `q0`、`q1`；
- 单选字段 `type: "string"` + `options`；
- 多选字段 `type: "multiselect"`；
- 事件是 `form.created` / `form.replied` / `form.cancelled`；
- API：
  - `GET /api/session/:sid/form`
  - `POST /api/session/:sid/form/:fid/reply`，body `{"answer": {"q0": "value", "q1": ["a","b"]}}`
  - `DELETE /api/session/:sid/form/:fid?message=...`

参考：

- `packages/schema/src/form.ts`
- `packages/protocol/src/groups/session.ts`
- `packages/protocol/src/groups/form.ts`

#### 短期方案：Form -> PendingQuestion

可以把常见的 question 表单转换为现有 `PendingQuestion`：

```python
QuestionItem(
    question=field.description or field.title,
    header=field.title or field.key,
    options=[QuestionOption(label=o.label, value=o.value) ...],
    multiple=(field.type == "multiselect"),
    custom=field.custom,
    key=field.key,
)
```

需要给 `QuestionOption` 增加 `value`，给 `QuestionItem` 增加 `key`，并作为必填字段。旧持久化数据读取时补默认值（`key` 用序号，`value` 用 label），避免破坏已有 route。

`reply_question(sid, rid, answer: QuestionAnswer)` 直接携带 `key -> values`，不再传 label 列表，也**不再依赖 adapter 缓存做 label 反查**：

```json
{"answer": {"q0": ["option-value"], "q1": ["a", "b"]}}
```

映射规则：

- `QuestionAnswer.values` 的 key 直接对应 `QuestionItem.key`；
- value 列表对应 `QuestionOption.value`；
- 用户自定义输入直接作为 string 值；
- adapter 只负责把 `QuestionAnswer` 转成后端格式；
- agentd 的 question 使用问题序号作为 key；
- OpenCode 的 Form 使用 field key。

`reject_question` 的语义需要固定：

- 默认发送 `DELETE /api/session/:sid/form/:fid?message=The user dismissed this question`；
- 这样 OpenCode `question` 工具会得到 `ToolFailure`，模型可以继续处理，而不是以 defect 结束当前 step；
- 如果将来需要“直接中止 turn”，再增加显式选项，不要复用同一个取消动作。

优点：

- 复用现有 HITL 卡片、编号回退、授权逻辑；
- 对 `question` 工具生成的表单可以完整工作。

限制：

- OpenCode Form 还支持 `number/boolean/external` 字段、复杂可见性条件等；这些无法完全表达为 Tether 现有 question 模型。
- 对非 `metadata.kind == "question"` 的表单（例如 provider 授权、MCP elicitation），建议默认不推送为聊天问题，或只在明确配置后支持，避免把系统表单误发到群里。

#### 中期方案：引入通用 Form 交互

如果希望完整支持 OpenCode Form，建议在 Phase 2：

- 在 `models.py` 增加中性 `FormSpec/FormField/FormOption`；
- `PendingInteraction.kind` 增加 `"form"`；
- `hitl.py` 增加 form 渲染；
- `reply_question` 之外增加 `reply_form(sid, rid, answer: dict)`。

这样不再把 OpenCode 的通用能力硬塞进 question 模型。首期可以先走 Form -> PendingQuestion 映射。

### 5.8 断线恢复与快照

Tether 现有实现依赖：

- `active_sessions()`；
- `messages(sid)` 后由 `assistant_text()` / `tool_media()` 解析；
- `list_permissions()` / `list_questions()`。

目标接口改为 `active_sessions() -> set[str]` + `turn_snapshot(after_message_id=...)` + pending 列表，不再暴露 `messages(sid)`。

OpenCode 适配器应提供：

1. `active_sessions() -> set[str]`：复用 `/api/session/active`，只保留 session id。
2. `turn_snapshot(sid, *, after_message_id=None)`：
   - 调 `GET /api/session/:sid/message?order=asc&limit=200`；
   - 需要时按 `cursor.next` 继续分页，或使用 `/api/experimental/session/:sid/export` 一次取完整 transcript；
   - 解析 `data[]` 中的 `assistant` 消息；
   - 以 `after_message_id` 为界；未提供时取最后一条 user 消息之后的当前 turn；
   - `text` 取当前 turn **最后一条** assistant 消息的 text content；
   - `media` 遍历当前 turn 内**所有** assistant 消息的 tool `content` 中的 file parts；不要把 `metadata.files` 当作通用来源（spike 未提供）；
   - 返回 `TurnSnapshot(turn_id, text, media)`。
3. `list_permissions(locations=...)`：
   - 未传 locations 时只查询 endpoint 的默认 location；
   - shared 之外的模式必须由 Router 传入已知 route 的 location 集合，不能静默回退；
   - 对每个 location 调 `GET /api/permission/request`。
4. `list_questions(locations=...)`：
   - 同样按 location 调 `GET /api/form`，或按已知 route 调 `GET /api/session/:sid/form`；
   - 过滤 `metadata.kind == "question"` 的表单；
   - 转换为 `PendingQuestion`，`QuestionItem.key` 使用 Form field key。

OpenCode 没有稳定的 turn id；`TurnSnapshot.turn_id` 可以为 `None`。边界统一使用 `after_message_id` 或最后一条 user message；同一 busy turn 内多次 steer 时，仍以该边界后的 assistant content 为准。

参考：

- `packages/protocol/src/groups/message.ts`
- `packages/schema/src/session-message.ts`

**Spike 结果：OpenCode 重启后 session 和 message 仍在，但 pending form/permission 丢失。** 因此 `_restore_hitl()` 必须：

- 双向 reconcile：后端返回的 pending 加入 Route；Route 里有、后端没有的 pending 从 Route 删除；
- 对 `supports_pending_interaction_recovery=false` 的后端，重启后清空该 Route 的 pending，并给用户发送“之前的确认/问题已失效，请重新发起”的 notice；
- 不能继续展示已经失效的旧卡片。

这样 `app._recover_active()` 和 `app._restore_hitl()` 无需知道 OpenCode 消息/表单结构。

#### 5.8.1 断线重连与事件不丢失

OpenCode 的实现分两层：

- `Bus.subscribe()` / `/api/event`：**volatile live**，明确不跨断线；OpenCode 源码注释是 “nothing before or across a disconnect”。
- `Bus.log()` / `/api/experimental/session/:sid/log?after=&follow=`：按 aggregate 的 durable replay，先读历史，再发 `log.synced` 标记，之后继续 live；`after` 是 exclusive seq，必须 >= 0。

关键 caveat：**默认 `opencode serve` CLI 没有启用 `events.persist`**。`packages/server/src/routes.ts` 使用 `Bus.configured({persist: options.events?.persist})`，而 CLI 没有设置 `events.persist`，所以 `/log` 只有 `log.synced` marker，没有历史事件（已实测）。OpenCode 自身的 TUI 在重连后主要靠 **projection resync**：重新同步 session/messages、permissions、forms，而不是依赖全局事件 replay。

agentd 则不同：`/api/session/{sid}/event?after=<seq>` 会把 durable replay 与 live 合并，并按 event ID 去重；agentd 源码 `pkg/server/event.go` 和 `TestSessionReplay` 已覆盖。Tether 当前只用了全局 `/api/event`，没有用这个能力。

Tether 的目标策略：

1. `AgentBackend` 增加有限 replay：`session_replay(sid, after_seq=-1) -> list[Event]`；`BackendProfile` 增加 `supports_session_replay`。
2. 每个活跃 turn/Route 记录 `last_seq`（可持久化）；durable event 的 `durable.seq` 更新 cursor。
3. 重连顺序：
   - 先保持/恢复 live 流；
   - 再对每个本地活跃 turn 调 `session_replay(after=last_seq)`；
   - 按 event ID / `(aggregateID, seq)` 去重；
   - 读取完成后由 live 流继续。OpenCode `/log` 的 `log.synced` 只用于确认 durable watermark，不作为核心接口的一部分。
4. 对“断线期间已经结束”的 turn：
   - 不能只看 `active_sessions()`；本地 `_turns` 里仍在的 engine 都要拉 `turn_snapshot()`；
   - 用最终 messages/diff 填充 text/media，再 `finish()`；
   - 否则 watchdog 会把 turn 结束在空/半截文本上。
5. HITL：
   - 重连后 `list_permissions/list_questions` 做双向 reconcile；
   - 后端列表里不存在的 Route pending 必须删除、取消 timeout timer，并通知用户“已失效”；
   - 后端不支持 pending recovery（OpenCode 重启）时同样清空并通知。
6. 如果后端没有可用 replay（OpenCode 默认 CLI）：
   - 必须做 projection resync（messages/permissions/forms）；
   - 全局 SSE 只用于 live 增量，不能作为恢复依据。

**实施顺序**：

1. **先在当前 agentd 代码落地**：`HttpAgentClient.session_replay()` 通过 `GET /api/session/{sid}/history?after=&limit=` 读取有限 durable 历史；`Route.last_seq` 持久化跨 turn 的 cursor，`TurnEngine` 从 Route 初始化；`_reconcile()` 在重连后先 replay `after=last_seq`（跳过 <= last_seq 的事件），再对 active session 做 snapshot、对已完成 turn 做最终快照后 finish。
2. **重构时上移**：把 `session_replay` 提升为 `AgentBackend` 能力；`AgentdBackend` 实现 `/history`，或根据部署使用 `/event?after=`（合并 durable+live、按 event ID 去重）。
3. **OpenCode 接入时**：默认 CLI 无 persist -> `supports_session_replay=False`，走 projection resync；启用 `events.persist` -> adapter 用 `/api/experimental/session/:sid/log?after=` 实现有限 replay，`log.synced` 仅确认 watermark。注意 OpenCode `after` 必须是 `>= 0`；adapter 收到 `after_seq=-1` 时必须省略 `after` 或传 `0`，不能直接传 `-1`。

**已修复的当前代码缺口**：

- `_consume_events()` 只重连全局 SSE；`_reconcile()` 现在会对本地 turn 先 `session_replay(after=last_seq)`，再恢复 snapshot；
- `_recover_stale_turns()` / `_reconcile()` 在 finish 前拉最终 text/media，避免断线期间 turn 结束时丢失最终回答；
- `Route.last_seq` 跨 turn 持久化；新 turn 开始前如果 session 不 active，`_prime_route_cursor()` 推进到最新 seq；如果 session 仍 active，先 attach/recover 上一轮，不能直接丢弃其事件；
- queued turn 在 `_activate()` 时重新对齐 `route.last_seq`，避免构造时捕获的 cursor 过期；
- janitor 周期把 active engine 的 dirty cursor flush 到 Route，shutdown 前再强制保存；
- `_restore_hitl()` 双向 reconcile：只在 reconnect/startup 的显式 reconcile 中做 destructive clear，普通 poll 不清理；删除时使用 Router 的 canonical Route，取消 timer 并 best-effort 通知用户；
- 最终快照只取“最后一条 user message 之后”的当前 turn，避免重发上一轮 text/media；
- replay handler 和整个 `_reconcile()` 都做异常隔离，单个坏事件/turn 不能杀死 SSE 消费循环；
- active probe 后若 session 在 attach 前已经结束，立即 finish resumed engine，避免僵尸 engine 阻塞新 turn；
- `TurnEngine.last_seq` 记录 durable aggregate seq。新增测试覆盖 replay、跨 turn cursor、最终快照和 stale pending。

### 5.9 `/status` 与 `/config`

当前 `/status` 和 `/config` 直接假设 agentd：

- `_agentd_info()` 直接调 `GET /api/info`；
- `_agentd_config()` 调 `GET /api/config?section=servers&server=...`，OpenCode 的 `GET /api/config` 返回的是配置文档数组 `Config.Entry[]`，没有 `servers[]` 结构；
- 健康检查 `/healthz` 的 payload 键名是 `agentd`。

建议：

- 删除对 `get_info()` 的公开依赖；`/status` 统一使用 `AgentBackend.describe()`，由 adapter 内部决定调用 `/api/info` 还是其他端点；
- 把 `_agentd_info` / `_agentd_config` 改名为 `_backend_info` / `_backend_config`；
- `/status` 显示 `backend_id`、`endpoint_id`、`version/pid`、`locations`；
- `/config` 使用 `AgentBackend.config_summary()`，**默认只返回安全摘要**，不返回原始 `Config.Entry[]`。

### 安全要求：OpenCode 配置必须强制脱敏

OpenCode 的 `Config.Info` 包含 `providers`，provider 配置里可能有 `headers`（例如 `Authorization`）或其他凭据。Tether 现有的 `redact_secrets()` 只按 key 名匹配 `token/secret/password/...`，不会递归脱敏 `headers` 中的值，因此**不能直接展示原始配置**。

具体要求：

- `config_summary()` 只返回 white-list 字段：默认 agent/model、provider 名称、agent 数量、model 数量、location、版本等；
- 如果确实要展示完整配置，必须由 OpenCode 适配器递归脱敏 `providers.*.headers`、`providers.*.options` 等敏感字段；
- `/config --all` 也必须经过同一脱敏路径，不能直接 dump `Config.Entry[]`；
- 单元测试必须覆盖 `Authorization` header、API key 类的脱敏。

健康检查返回：

```json
{
  "agentd": {
    "http://127.0.0.1:8787": true
  },
  "backends": {
    "local-opencode": {
      "backend_id": "opencode",
      "endpoint_id": "local-opencode",
      "base_url": "http://127.0.0.1:4096",
      "healthy": true
    }
  }
}
```

`agentd` 键在过渡期保留，避免破坏已有监控脚本。

### 5.10 API 选择与误用防护

完整端点、payload、响应字段和实测结果见 [`docs/REF-OPENCODE-HTTP-API.md`](./REF-OPENCODE-HTTP-API.md)。关键选择：

| 需求 | 正确 API | 不要使用 |
|---|---|---|
| 用户消息 | `POST /prompt` | `/synthetic`（bridge/internal） |
| bridge context | 当前：prompt 前缀；可选替代：`POST /synthetic` | 无 |
| 队列管理 | `/prompt` + `/inbox` | 依赖本地猜测 |
| slash command | `/session/:sid/command` | 当普通文本 prompt |
| skill | `/session/:sid/skill` / prompt `skills` | 误以为不支持 |
| turn 结束 | `session.execution.*` | 等 `session.status` |
| 变更文件 | `step.ended.files` / `/diff` | `tool.success.metadata.files` |
| pending permission | `permission.asked` / `GET permission` | 把 `POST permission` 当创建 |
| 标题 | `PATCH /session/:sid` | `/title` |
| 默认模型 | `/api/model/default` | 猜第一个 model |
| worktree 源 | `project.canonical` | 原始 symlink path |

## 6. 配置设计

### 6.1 推荐配置

不要在 `AgentBackend` 内部读取全局 `Config`。先把配置解析成后端无关的 `ServerEndpoint`：

```python
@dataclass(frozen=True)
class ServerEndpoint:
    id: str                      # 稳定标识，Route 持久化使用；省略时默认取 name
    name: str
    backend: Literal["agentd", "opencode"]  # "agentd" = go-agent-sdk/cmd/agentd
    base_url: str
    auth: AuthConfig
    working_directory: str | None
    default_agent: str | None
    default_model: str | None
```

**endpoint 标识与多 location 约束：**

- client、agent cache、model cache、`Route` 都必须按 `endpoint.id` 关联，不能只按 `base_url`；
- 同一个 `base_url` 可以出现在多个 endpoint 中（OpenCode 单进程多 location 的典型形态），只要 `id` 不同；
- SSE 仍按 `base_url` 去重：同一 OpenCode 服务只订阅一次 `/api/event`；
- `agentd` 模式下每个 endpoint 仍对应一个独立服务/working directory，不允许同一 `base_url` 多个 endpoint（agentd 无法区分）。

YAML 示例：

```yaml
server:
  backend: agentd          # go-agent-sdk/cmd/agentd；全局默认，未写时兼容旧配置
  base_url: http://127.0.0.1:8787
  auth:
    type: bearer
    token: ${AGENTSERVE_TOKEN:-}
  working_directory: null
  pool:
    - id: local-opencode
      name: local-opencode
      backend: opencode
      base_url: http://127.0.0.1:4096
      auth:
        type: basic
        username: opencode
        password: ${OPENCODE_PASSWORD:-}
      working_directory: /workspace/project
      default_agent: build
      default_model: anthropic/claude-sonnet-4-5
    # 同一个 OpenCode 进程的第二个 location：base_url 相同、id 不同
    - id: local-opencode-docs
      name: local-opencode-docs
      backend: opencode
      base_url: http://127.0.0.1:4096
      auth:
        type: basic
        username: opencode
        password: ${OPENCODE_PASSWORD:-}
      working_directory: /workspace/docs
      default_agent: build
      default_model: anthropic/claude-sonnet-4-5
```

为了兼容旧配置：

- 未写 `server.backend` -> `agentd`；
- 未写 `server.auth` -> 使用旧 `token` 作为 Bearer；
- pool entry 未写 `backend` -> 继承顶层 `server.backend`；
- pool entry 未写 `auth/token` -> **当前实现不继承顶层 token**（`pool[].token=None` 即无 token）；Phase 0 保持该行为，若要改为继承需作为显式行为变更并更新测试；
- pool entry 未写 `id` -> 默认取 `name`；
- 旧 `server.token` / `pool[].token` 继续可用。

启动校验：

- `id` 必须唯一；
- `working_directory` 必须是绝对路径；
- 同一 `base_url` 的多个 endpoint 只允许 `backend == "opencode"`；
- `agentd` 模式下同一 `base_url` 只允许一个 endpoint。

如果不想引入 `auth` 结构，也可以最小化处理为：

```yaml
backend: opencode
token: ${OPENCODE_PASSWORD}   # opencode 适配器解释为 Basic password
```

但推荐显式 `auth`，否则 “token 到底是 Bearer 还是 Basic password” 会长期含糊。

### 6.2 `Route` 持久化

在 `Route` 增加：

```python
endpoint: str | None = None   # ServerEndpoint.id；旧 route 为 None
backend: str = "agentd"       # "agentd" = go-agent-sdk/cmd/agentd
location: str | None = None   # OpenCode 的 session directory；agentd 为 None
last_seq: int = -1            # 最近一次 durable aggregate seq；旧 route / 新 session 为 -1
```

`last_seq` 是 replay cursor 的核心状态：

- `_prime_route_cursor()`、`_reconcile()`、`_flush_cursors()`、shutdown 都依赖它；
- `recreate_session()` 必须重置为 `-1`；
- 旧 route 读取时默认 `-1`。

`src/tether/store/sqlite.py` 的 route JSON 是自描述结构，新增字段向后兼容。

加载 route 时必须做一致性校验：

- 若 `endpoint` 为空，按旧 `server_base` 回退到唯一匹配的 endpoint；
- 若 `endpoint` 不存在，或 `backend` 与当前配置不一致，不能直接继续使用旧 session；
- 处理方式：记录 warning，丢弃旧 route 并重建 session；或启动失败并给出明确配置错误；
- 不允许多个 endpoint 通过同一个旧 `base_url` 产生歧义时静默选择第一个。

这样即使配置中同一个 `base_url` 被改了 backend，或同一个 OpenCode 服务新增了 location，已存在的 route 也不会被错误路由。

### 6.3 `projects.mode=isolated`

`isolated` 不是“以后再说”的能力，设计如下，两个后端都完整实现：

- `agentd`：继续使用 control API 为每个会话创建独立实例；
- `opencode`：使用 OpenCode worktree + per-session `location.directory`；
- 两者共用 `LeaseManager`、TTL 回收、Route 持久化和 `working_directory(route)` 语义。

#### 6.3.1 配置

```yaml
projects:
  mode: isolated
  backend: agentd              # agentd | opencode；默认 agentd，兼容旧配置
  endpoint: null               # backend=opencode 时必填：ServerEndpoint.id
  isolation: worktree          # agentd: none|copy|worktree|overlay；opencode: 仅 worktree
  base_dir: /var/lib/tether/workspaces
  ttl_s: 3600
  max_leases: 32
  git_base_ref: HEAD
  source_directory: /workspace/project
  inbound_permissions:
    - action: bash
      resource: "*"
      effect: ask
  sandbox: null                # agentd only；opencode 不支持
  # agentd only:
  control_url: http://127.0.0.1:9090
  control_token: ${CONTROL_TOKEN:-}
```

`projects.backend` 只在 `mode=isolated` 生效；shared 模式的后端由 `ServerEndpoint.backend` 决定。

| 配置 | agentd | opencode |
|---|---|---|
| `projects.backend` | 默认 `agentd` | 必须显式 `opencode` |
| `projects.endpoint` | 忽略；实例由 control API 返回 | 必填，指向一个 `backend=opencode` 的 endpoint |
| `isolation` | `none/copy/worktree/overlay` | 仅 `worktree` |
| `source_directory` | 必填，作为 view 源 | 必填，用于解析 OpenCode `projectID` |
| `control_url/token` | 必填 | 忽略；若设置则启动 warning |
| `inbound_permissions` | 传给 control API | 传给 `create_session(permissions=...)` |
| `sandbox` | 传给 control API | 不支持；`process != none` 时启动失败 |
| `base_dir` | view/state 根目录 | worktree 父目录，必须是 Tether 专用目录 |
| `git_base_ref` | worktree `baseRef` | 映射为 worktree 的 `branch` |

启动校验必须明确失败，不能静默降级：

- `isolated + opencode` 缺少 `projects.endpoint` 或 endpoint 不是 `opencode` -> 启动失败；
- `isolated + opencode` 且 `isolation != worktree` -> 启动失败；
- `isolated + opencode` 且 `sandbox.process != none` -> 启动失败；
- `source_directory` 或 `base_dir` 不是绝对路径 -> 启动失败；
- `source_directory` 位于 `base_dir` 内、`base_dir` 位于 `source_directory` 内、或 `base_dir` 指向源项目 -> 启动失败；
- `max_leases > 0` 时必须实际生效：达到上限时先回收最久空闲的 ephemeral lease，仍不够则拒绝新会话。

#### 6.3.2 `ProjectLease` 与 provider

`ProjectLease` 增加 endpoint/backend/location 语义：

```python
@dataclass
class ProjectLease:
    project_id: str
    endpoint_id: str
    backend: str                 # "agentd" | "opencode"
    server_base: str
    working_directory: str | None  # opencode: worktree directory；agentd: view dir
    ephemeral: bool = False
```

`build_provider(config, endpoints)` 根据 `projects.backend` 选择：

- `agentd` -> `AgentdControlProvider`；
- `opencode` -> `OpenCodeWorktreeProvider`；
- `shared` 仍使用 `SharedProjectProvider` / `PoolProjectProvider`。

#### 6.3.3 `AgentdControlProvider`

保持现有行为，只补齐 lease 字段：

- `acquire()` 调 `POST /admin/projects`，返回动态 `server_base`；
- `endpoint_id = f"agentd-lease:{project_id}"`，`backend="agentd"`；
- `release()` 调 `DELETE /admin/projects/{project_id}`，并关闭该动态 endpoint 的 client / SSE；
- `preflight()` 检查 control API 和 `base_dir`，列出已有 project；不无条件清空 `base_dir`；
- orphan project 由 §6.3.6 的 `cleanup_orphans()` 在 Route/active session 探测后清理；
- Router 为该动态 endpoint 建立独立 client，并订阅该 base 的 `/api/event`。

#### 6.3.4 `OpenCodeWorktreeProvider`

所有请求都通过 `projects.endpoint` 对应的 `ServerEndpoint` / client 发出，使用其 Basic auth 和 base_url。

**解析项目**

1. 用 `projects.source_directory` 调：

   ```text
   GET /api/location?location[directory]=<source_directory>
   ```

2. 取 `project.id` 和 `project.canonical`，缓存为 `projectID` / `projectRoot`；
3. 要求 `realpath(source_directory) == realpath(projectRoot)`（OpenCode 的 worktree source 必须是一个已知 worktree/root）；注意 OpenCode 会把 `/var` 规范化为 `/private/var`，比较前必须 `Path.resolve()`；若 404、目录不存在或不在该项目 -> 启动失败。

**preflight**

1. 校验 endpoint 是 OpenCode、source/base 目录合法；
2. 解析 `projectID`；
3. 调 `GET /api/worktree?projectID=<projectID>` 确认 worktree API 可用，并记录现有 worktree；
4. **不删除**任何 worktree；orphan 清理在加载 Route 并探测 active sessions 之后由 `cleanup_orphans()` 执行（见 §6.3.6）。

**acquire**

```text
POST /api/worktree
{
  "projectID": "<source project id>",
  "from": "<projectRoot>",
  "branch": "<git_base_ref>",
  "directory": "<base_dir>",
  "name": "tether-<sanitized conversation key>-<hash8>"
}
```

- 成功返回 `{directory}`，将其作为 lease 的 `working_directory`；
- `endpoint_id` 使用配置的 `projects.endpoint`，`backend="opencode"`；
- `project_id` 保存 **source projectID**，因为删除 worktree 需要它；
- 创建失败（超时、git 错误、目录冲突）直接抛错，不创建 Route；
- worktree 的 setup/start script 由 OpenCode 执行，Tether 只受 `request_timeout_s` 约束。

**release**

```text
DELETE /api/worktree
{"projectID": "<source project id>", "directory": "<worktree directory>", "force": true}
```

- best-effort；失败只记录日志，由 preflight 清理兜底；
- `LeaseManager.reclaim_idle()` 和 `release_all()` 都必须调用它。

**SSE**

- OpenCode isolated 与 shared 使用同一个 `server_base`，因此**不需要**为每个 lease 新建 SSE 连接；
- `_ensure_sse()` 继续按 `base_url` 去重即可。

#### 6.3.5 Router 集成

`get_or_create()` 的顺序改为：

1. `provider.acquire()` 得到 lease；
2. `lease.endpoint_id` 解析出 endpoint/client；
3. 以 `(endpoint_id, lease.working_directory)` 执行 `resolve_agent` / `resolve_model`；
4. `create_session(agent, model, location=lease.working_directory, permissions=projects.inbound_permissions)`；
5. 写 `Route(endpoint=lease.endpoint_id, backend=lease.backend, location=lease.working_directory, project_id=lease.project_id)`；
6. 为 agentd 动态 base 建立 SSE；OpenCode 复用已有 SSE。

`_ensure_lease()` 在重启后：

- 重新 `acquire()` 一个 lease；
- 更新 `route.endpoint/location/project_id/server_base`；
- 重新创建 session；
- 旧 worktree 在 TTL / preflight 中清理。

`working_directory(route)` 的优先级固定为：

```text
lease.working_directory
  > route.location
  > endpoint.working_directory
```

`reclaim_idle()` 删除 Route 时同步释放 lease；`max_leases` 在 acquire 前检查并回收最久空闲的 ephemeral lease。

参考：`packages/protocol/src/groups/worktree.ts`、`packages/schema/src/worktree.ts`、`packages/protocol/src/groups/location.ts`。

#### 6.3.6 清理安全性

清理必须避免破坏仍被持久化 Route 或运行中 session 使用的 worktree/view：

- `preflight()` 只做连通性和配置校验，**不删除**任何 worktree/view；
- 启动加载 Route 后，先探测各 endpoint 的 `active_sessions()`，再执行 `cleanup_orphans()`；
- `cleanup_orphans()` 只删除同时满足以下条件的 lease：
  - 没有对应 `Route.location` / `Route.project_id`；
  - 不属于 `active_sessions()`；
  - 超过 `projects.ttl_s` 或明确标记为 orphan；
- OpenCode：只删除 `base_dir` 下以 `tether-` 开头、且不在 `{route.location}` 集合中的 worktree；
- agentd：只删除 control API 返回的、未被任何 Route 引用的 project，不再无条件 `wipe_dir(base_dir)`；
- `sessions.interrupt_on_shutdown=false` 时，shutdown 不删除 ephemeral lease；只停止 SSE，保留 Route，下次启动按 `_ensure_lease()` 重新关联或重建；
- `interrupt_on_shutdown=true` 或 TTL 回收时，先确认 session 不在 `active_sessions()`，再 release；
- 长 turn 期间必须在 prompt/event/finish 时 touch lease，避免 TTL 在 turn 运行中回收 worktree。

#### 6.3.7 测试

- `OpenCodeWorktreeProvider`：project 解析、create/remove payload、preflight 不删除、cleanup_orphans 只清理 `tether-*`；
- setup script 失败/超时、git 错误、目录冲突时不创建 Route，且不留下可被误复用的 lease；
- isolated 端到端：会话创建后被放入 worktree，`Route.location` 持久化，重启后重新 lease 并重建 session；
- `inbound_permissions` 正确进入 `create_session.permissions`；
- `sandbox != none`、`isolation != worktree`、缺少 endpoint、source/base 路径非法时启动失败；
- TTL / shutdown / max_leases 的清理不会删除 Route 引用或 active session 的 worktree；
- agentd isolated 回归测试保持通过。

## 7. 代码改造清单

### Phase 0：抽取端口，外部 IM 行为不变

Phase 0 的“行为不变”指 **外部 IM 行为不变**；内部事件词汇、`active_sessions` 返回类型、`TurnSnapshot` 边界会按本文迁移。

1. 新增 `agent/base.py`：`AgentBackend`、`BackendProfile`、`BackendDescription`、`ConfigSummary`、`TurnSnapshot`、`PromptFile`、`QuestionAnswer`。
2. 把现有 `HttpAgentClient` 移到 `agent/agentd/client.py`，重命名 `AgentdBackend`。
3. 新增 `agent/registry.py`：`create_backend(endpoint) -> AgentBackend`。
4. `config.py` 增加 `ServerEndpoint` 解析、稳定 `id`、`backend`、`auth`、pool `backend` 继承和显式 token 语义、启动校验。
5. `models.py` 的 `Route` 增加 `endpoint/backend/location`；`SessionInfo` 增加 `location`。
6. `router.py` 的 `ClientFactory` 改为接收 `ServerEndpoint`；`_clients`、`_agent_cache`、`_models_cache`、`_pool_entry` 改为按 endpoint id 建键；SSE 仍按 base_url 去重。
7. `agent/events.py` 常量改为中性事件名；`Event` 改为显式 `session_id` + typed `EventData`；新增 `agent/agentd/events.py` 做 agentd 原生事件到中性事件的映射；`TurnEngine` handler 键同步更新。
8. `app.py`、`turn.py` 的类型从 `HttpAgentClient` 改为 `AgentBackend`；`active_sessions()` 改为 `set[str]`。
9. 新增 `turn_snapshot(after_message_id=...)`，把 `assistant_text()` / `tool_media()` 的调用移入适配器，并保证不跨 turn。
10. 删除公开 `get_info()`；`/status` / `/config` 改用 `describe()` / `config_summary()`；健康检查保留 `agentd` 兼容键并新增 `backends`。
11. `reply_question()` 改为接收 `QuestionAnswer`；`QuestionItem.key` / `QuestionOption.value` 变为必填。
12. route 加载增加 endpoint/backend 一致性校验和重建策略。
13. 现有测试改为断言中性事件名和 typed payload；新增 agentd 原生事件 fixture 验证映射。
14. `MediaIngest` 改为返回 `PromptFile`；agentd/opencode adapter 各自转换成后端文件格式。
15. `TurnEngine` 的媒体提取改为消费 `FilePart` / `ToolStructured`，删除对弱类型 dict 的递归扫描。
16. 把已落地的 `HttpAgentClient.session_replay()` 上移到 `AgentBackend`；`AgentdBackend` 使用 `/api/session/{sid}/history`，保留 `last_seq` replay、event 去重和“finish 前拉最终快照”的行为。
17. 保留 `tests/test_client_contract.py` 的 replay 分页测试和 `tests/test_reconcile.py` 的断线恢复回归测试，重构后必须全绿。

### Phase 1：OpenCode shared 模式

1. 新增 `agent/opencode/client.py`：
   - Basic auth；
   - location 注入（query `location[directory]` 优先，header 兼容）；
   - 错误 `_tag` 映射；
   - agent/model/session/prompt/interrupt/delete/active；
   - agent 列表为空时合成默认 `build`；非空时优先 `primary/all` 且非 hidden；
   - 冷启动 timeout 60–120s，启动预热 location；
   - `events()`。
2. 新增 `agent/opencode/events.py`：事件映射表；`session.execution.*` -> idle/busy；`form.created` 直接设置 `Event.session_id=form.sessionID`；文本/工具缓存使用完整键。
3. 新增 `agent/opencode/messages.py`：`turn_snapshot()`，以 `after_message_id` 或最后一条 user 消息为界，文本取最后一条 assistant，媒体只遍历当前 turn 的 tool file parts，处理分页。
4. 新增 `agent/opencode/models.py`：Model.Ref 解析/格式化；context limit 查找忽略 variant。
5. 新增 `agent/opencode/forms.py`：Form -> PendingQuestion、`QuestionAnswer` key/value 回复、取消消息语义。
6. 新增 `agent/opencode/config.py`：`describe()` / `config_summary()`，强制脱敏 provider headers/options；不暴露 `get_info()`。
7. 接入权限：`decision` 字段、按 location 的跨 session 待处理列表；重启后 pending 丢失时清空 Route 并通知用户。
8. `/status`、`/config`、健康检查改为 backend 无关展示。
9. 增加 OpenCode mock HTTP 契约测试，包括多 location、空 agent 列表、`session.execution.*` turn 结束、配置脱敏、snapshot turn 边界、重启 pending 丢失；同时保留可选的 live contract tests（`tests/test_opencode_live_contract.py`）。

### Phase 2：Form 完整语义与可选能力对齐

Phase 2 的“高级能力”是明确列出的，不是泛泛的 TODO：

1. **通用 Form 交互模型**：
   - `FormSpec/FormField/FormOption`；
   - `PendingInteraction.kind="form"`；
   - `reply_form(sid, rid, answer: dict)`；
   - 支持 `string/number/integer/boolean/multiselect/external` 字段；
   - 支持 `when` 可见性条件、`custom`、多字段和默认值。
2. **非 question 表单**：
   - provider 授权、MCP elicitation 等 `form.created`；
   - 默认只在管理员直聊或显式配置下推送，避免群聊收到系统表单。
3. **标题同步**：
   - `session.renamed` / `PATCH /api/session/:sid` 与 Route/IM 会话标题同步。
4. **模型与 agent 选择**：
   - OpenCode model variant；
   - `default_model` / `default_agent` 的发现与展示；
   - 不在 Phase 2 做自动 agent 路由。
5. **可选 OpenCode command/skill 转发**：
   - `POST /api/session/:sid/command`；
   - `POST /api/experimental/session/:sid/skill`；
   - 仅在明确需要时接入，不能与 Tether 本地 `/stop`、`/new` 等命令冲突。

明确不在范围：

- PTY / persistent PTY / 终端 UI；
- session fork/revert/export/import；
- desktop/web UI；
- OpenCode 内部 subagent UI。

### Phase 3：隔离项目实现

1. `ProjectLease` 增加 `endpoint_id/backend/working_directory`，`build_provider(config, endpoints)` 按 `projects.backend` 选择 provider。
2. 配置增加 `projects.backend` / `projects.endpoint`，实现 §6.3.1 的全部启动校验。
3. `AgentdControlProvider` 补齐动态 endpoint/lease 字段，保持现有 control API 行为。
4. 实现 `OpenCodeWorktreeProvider`：project 解析、preflight 清理、create/remove、lease 生命周期。
5. Router 按 lease.endpoint + lease.working_directory 发现 agent/model、创建 session，并写入 `Route.endpoint/backend/location/project_id`。
6. `create_session(permissions=...)` 接入 `projects.inbound_permissions`；OpenCode 映射到 session permissions，agentd 忽略。
7. `working_directory(route)` 使用 `lease.working_directory > route.location > endpoint.working_directory`。
8. SSE 复用：agentd 动态 base 单独订阅；OpenCode lease 复用同一 base 的 SSE。
9. 实现 `max_leases`、TTL、重启后 lease 重获、worktree 清理和 preflight 兜底。
10. 完成 §6.3.7 的 provider/端到端/失败路径测试。

## 8. 测试策略

建议新增一个 **Backend Contract Test Suite**，对 `AgentdBackend` 和 `OpenCodeBackend` 都跑同一套行为测试：

1. 认证头正确；
2. `list_agents/list_models` 字段映射与 endpoint+location 缓存隔离；
3. `create_session` 的 agent/model/title/location 转换，`SessionInfo.location` 回填；
4. `prompt` 的 `PromptFile` 转换后的 payload 形状；
5. 错误体 -> `AgentError` 映射；
6. SSE fixture -> 中性 typed `Event`；显式 `session_id`；agentd 原生 `session.next.*` / `permission.v2.*` 的映射；OpenCode `session.execution.*` / `session.idle` -> idle/busy 的映射（即使没有 `session.status` 也能结束 turn）；文本/工具缓存键；
7. permission 请求/回复；
8. question/form 请求/回复/取消，包括 `QuestionAnswer` key/value 和取消 message；
9. `turn_snapshot(after_message_id=...)` 的 turn 边界、最后一条文本、当前 turn 媒体和分页；
10. `active_sessions` 返回 `set[str]`，与 watchdog/reconcile 兼容；
11. OpenCode agent 选择优先 `primary/all`，不选 subagent；空列表合成 `build`；
12. `/config` 对 provider headers/Authorization 的脱敏；
13. 多 endpoint / 多 location 的 Route 一致性与重建；
14. isolated provider：OpenCode worktree create/remove、agentd 动态 endpoint、TTL/max_leases/重启恢复；
15. 多 location 并发 prompt，`active_sessions` 同时返回两个 running session；
16. 重启后 session/message 可恢复、prompt 可继续、pending form/permission 被清空并通知；
17. `session.wait` 运行中阻塞到 idle、idle 时立即返回；
18. 冷启动超过 30s 时按 unavailable 重试，不误判配置错误；
19. `session_replay(after_seq)` 分页、去重、`after` 边界，以及无 replay 时 projection resync 的 fallback；
20. agentd 重启后 pending permission/question 的真实语义（原 id 是否保留，还是 resumed turn 重新 ask），据此确认 `supports_pending_interaction_recovery`。

另外：

- 用 `packages/protocol/openapi.json` 做一次 CI 检查，检测 OpenCode API 漂移；
- 保留现有 `tests/test_client_contract.py` 的 agentd 用例，但断言改为中性事件名，并额外验证 agentd 原生事件映射；
- 新增 `tests/test_client_contract_opencode.py`，使用 `httpx.MockTransport` 模拟 OpenCode 响应；
- 在文档和测试中记录设计所基于的 OpenCode version/commit。

## 9. 风险与取舍

本节只列“即使采取了设计措施，仍然需要接受或持续监控”的残余风险。能够通过实现或配置完全消除的项，列在 §9.1，不作为风险。

### 9.1 设计约束与已决定事项（不是残余风险）

- **部署形态**：默认 `opencode serve` 不启用 `events.persist`，Tether 因此使用 projection resync；如果要求精确逐事件 replay，部署必须使用 embedder/sidecar 设置 `events.persist=true`，并按 `docs/REF-OPENCODE-HTTP-API.md` §12.1 验证 `/log?after=0`。
- **`/log` 只包含 durable events**：global SSE 负责 live delta/HITL/status，`/log` 只补 durable 缺口。
- **`session.status` 版本差异**：同时处理 `session.status` / `session.idle` 和 `session.execution.*`。
- **`session.wait` 无 timeout**：adapter 使用客户端超时。
- **`POST /permission` 是评估接口**：Tether 只消费 `permission.asked` 或 `effect=ask`。
- **空 `/api/agent`**：adapter 合成默认 `build` agent。
- **replay/live 重叠**：按 durable seq / event ID 去重。
- **跨 turn replay**：`Route.last_seq`、prime cursor、dirty cursor flush、当前 turn 快照。
- **turn 边界**：以最后一条 user message / `after_message_id` 为界，不重发上一轮。
- **replay 异常**：per-engine 和 `_reconcile()` 双层异常隔离。
- **cold start**：`request_timeout_s` 配 60–120s、预热 location、按 unavailable 重试；这是部署参数，不是不可消除的正确性风险。
- **变更文件**：`step.ended.files` / `session.diff` 可用时启用 `auto_files`，否则 `/send` 和显式 tool file parts 兜底；属于能力边界，不是数据正确性风险。
- **通用 Form 字段**：`number/boolean/external` 和复杂 `when` 属于 Phase 2 明确范围，Phase 1 只支持 question 类表单。
- **路径 / 多 location / model ref / tool name / config 形状 / 旧 Route**：分别由 realpath、endpoint+location 键、字符串 model ref、tool name 缓存、规范化 config summary、endpoint/backend 校验解决。

### 9.2 残余风险

| 残余风险 | 为什么仍然存在 | 处置决策 |
|---|---|---|
| OpenCode v2 API 持续演进 | 即使锁定版本，未来升级仍可能改变字段/事件，无法由 Tether 单方面消除 | 固定版本/commit；升级必须重跑 live contract tests、OpenAPI diff；启动时做能力探测，不匹配则 fail fast |
| OpenCode 重启丢失 pending form/permission | `form.ts` 用内存 Cache、`permission.ts` 用内存 Map；shutdown 会 cancel/close，崩溃直接丢失；Tether 按 session id 查询也只能得到空列表 | 接受为后端限制；清除旧 Route pending 并通知用户重新发起；不伪造一个已经断开的 tool 继续执行 |
| agentd 重启后的 pending 身份不保证 | agentd pending 同样在内存 `pendingRegistry`；resume 可能重新 ask，而不是保留原 request id | 保守设 `supports_pending_interaction_recovery=false`；用测试确认“重新 ask”行为，按新 request 处理 |
| startup/旧 pending 清理可能误删 | 后端短暂返回空列表时，Tether 无法区分“已失效”和“尚未加载”；一次空结果就可能清掉仍有效的 pending | 只在 reconnect/startup 做 destructive clear；普通 poll 不清理；后续可增加连续确认窗口；这是低概率但不可完全消除的风险 |
| worktree cleanup 依赖 `active_sessions` | 若 OpenCode 漏报 active，cleanup 可能删除仍被使用的 worktree；Tether 没有比 active_sessions 更强的运行态真相 | preflight 不删除；只清理未被 Route 引用且 TTL 过期的 tether-*；接受“后端漏报 active”的极端残余风险 |
| config 脱敏依赖已知 provider schema | OpenCode 未来新增 provider header/option 字段时，whitelist 或递归脱敏可能漏掉新 secret 字段 | 不展示原始 Config.Entry；只返回 whitelist summary；新增 provider 字段必须补脱敏测试；残余风险由升级评审控制 |
| replay / 历史读取的额外开销 | 大量 active turn 或长 session 在重连/新 turn 时会产生额外历史请求，无法完全避免 | 只在 reconnect/新 turn 触发；分页读取；必要时增加 cursor 缓存和并发限流 |

## 10. 最终建议

采用如下落地顺序：

1. **先做 Phase 0**：把 `HttpAgentClient` 抽象成 `AgentBackend`，保持外部 IM 行为不变；同时引入 `ServerEndpoint.id`、按 endpoint 建缓存、`Route.endpoint/backend/location/last_seq`。已提前落地的 `session_replay`、cursor 和最终快照修复保留为重构基线，不属于 Phase 0 新引入的行为。
2. **再做 Phase 1**：实现 `OpenCodeBackend`，先落地 shared 模式，事件、权限、文本、工具媒体、恢复全部在适配器内规范化；`/config` 只展示脱敏后的摘要。
3. **Phase 2** 按 §“Phase 2：Form 完整语义与可选能力对齐”实现通用 Form、标题同步、model variant 和可选的 command/skill 转发。
4. **Phase 3** 按 §6.3 完整实现 isolated/worktree：`OpenCodeWorktreeProvider`、agentd control provider 的 lease 改造、Router location 路由、permissions、TTL/重启清理和测试，不留待定项。

关键设计决策一句话总结：

> Tether 内核只认 `AgentBackend` + 显式 `session_id` 的 typed `Event` + `TurnSnapshot` + `QuestionAnswer`/`PendingInteraction`；agentd 和 OpenCode 是两个可替换的适配器，配置按 `ServerEndpoint.id` 标识、`Route` 记录 endpoint/backend/location，所有后端差异（包括多 location、Form、配置脱敏）都不进入 `TurnEngine`。

## 11. Spike 验证结果

- 环境：`~/Documents/opencode` commit `4617210822`，`bun run --cwd packages/cli src/index.ts serve`，Basic auth，临时 XDG 目录，临时 git 项目。先用本地 OpenAI-compatible mock provider 验证协议，再用 DeepSeek 官方 API 验证：`baseURL=https://api.deepseek.com`、`model=deepseek-flash`、key 仅通过 `DEEPSEEK_API_KEY` 环境变量注入，未写入配置或日志。
- 已验证：
  - `GET /api/info` 需要 Basic auth；无认证返回 401。
  - `GET /api/location?location[directory]=...` 解析出 `project.id` 和 `project.canonical`。
  - `GET /api/worktree?projectID=...`、`POST /api/worktree`、`DELETE /api/worktree`（JSON body + `force=true`）均可用。
  - `POST /api/session` 使用 `location.directory=worktree` 创建 session；`permissions` 规则原样保存。
  - Form 创建、列表、按 key/value 回复、取消；Permission 创建、列表、`decision` 回复。
  - `POST /api/session/:sid/prompt` 触发 text 事件：`session.text.started/delta/ended`、`session.step.ended`、`session.execution.succeeded`。
  - 扩展 API surface 实测：`/model/default`、`/agent/:id`、`/config`、`/config/shell`、session list/PATCH、inbox list/cancel、synthetic、context、interrupt、background、view、environment、command/skill 错误体、global form、permission saved、project list。
  - `POST /session/:sid/permission` 实测是评估接口：`effect=allow/deny` 时没有 pending，reply 会 404；只有 `effect=ask` 才能 reply。
  - 真实 DeepSeek `deepseek-flash`：文本回复返回 `tether-deepseek-ok`；`read` 工具读取 README；`write` 创建 `out-deepseek.txt`，`step.ended.files` 返回该文件，`session.diff` 返回 added。
  - 工具调用触发：`session.tool.input.started/ended`、`session.tool.called`、`session.tool.success`；`tool.called` 没有 name，必须用 `input.started` 缓存。
  - `/api/event` 推送 `server.connected`、`form.*`、`permission.asked`、`session.execution.*`、`session.step.*`、`session.text.*`、`session.tool.*`。
  - 多 location 并发：两个 session 同时 `prompt`，事件按 `sessionID` 正确分流；慢请求期间 `/api/session/active` 同时返回两个 running session。
  - 重启恢复：session、message、prompt 后继续工作均正常；`/api/session/active` 在 idle 时为空。
  - `POST /api/experimental/session/:sid/wait`：运行中阻塞到 idle（spike 约 4.2s），idle 时立即返回 204。
- 重要发现：
  - 当前 commit `4617210822` 的 server 没有发布 `session.status`（schema/event manifest 中存在，client 由 `session.execution.*` 推导）；但其他版本/部署可能发送。Tether 必须同时兼容 `session.status` / `session.idle` 和 `session.execution.*`，不能只依赖其中一种。
  - `/api/agent` 在 bare server 返回空数组，但默认 agent ID 仍是 `build`；session 未指定 agent 时仍以 `build` 运行。adapter 应在空列表时合成 `build`，不能直接失败。
  - OpenCode 会把 `/var/...` 规范化为 `/private/var/...`；`source_directory` 与 `project.canonical` 比较前必须 `realpath`。
  - 冷启动一个 location 约 19–31 秒；`request_timeout_s` 默认 30 秒不够，OpenCode 部署应设 60–120 秒并预热 location。
  - 重启后 session/message 仍在，但 **pending form/permission 丢失**；必须清空 Route 的旧 pending 并通知用户，不能继续展示旧卡片。
  - `write` 的 tool success 只有文本 content 和 `metadata.truncated`，没有文件路径；但 `session.step.ended.files` 在 git + snapshots + canonical path 下返回 `["out.txt"]`，`session.diff` 也返回对应 `FileDiff`。
  - 前一次 diff 为空是测试使用 `/var` 路径、OpenCode canonical 为 `/private/var`，snapshot 报 `Location is outside the project`；改用 `/private/var` 后通过。
  - 真实 DeepSeek `deepseek-v4-pro#high` 返回 `session.reasoning.started/delta/ended`。
  - 有效 PNG 的 `read` tool success 返回 `{type:"file", uri:"data:image/...", mime}`，不是 omitted text。
  - `session.command`（`review`）、`session.skill`（`resume=false`）、fork、revert stage/clear、PTY list/create/delete 均已实测。
- 源码与测试交叉验证：
  - `session.status` 在 schema/event manifest/client 中存在；当前 commit 的 server 没有 publisher，client 由 `session.execution.*` 推导。其他版本/部署可能发布，Tether 必须同时兼容。
  - `form.ts` 用内存 `Cache`，`permission.ts` 用内存 `Map` 保存 pending；与“重启后 pending 丢失”的运行时结果一致。
  - `packages/core/src/session/runner/step.ts` 在 snapshot 存在时发布 `Step.Ended.files`；运行时 `/private/var` 路径下得到 `["out.txt"]`。
  - `packages/core/test/session-diff.test.ts` 覆盖 diff 逻辑；本机运行该测试因 location/plugin 冷启动超过 30s 超时，`packages/server/test/session-diff.test.ts` 通过，运行时在 canonical path 下 diff 通过。超时本身与冷启动慢的结论一致。
  - `packages/core/src/agent.ts` 定义 `defaultID = "build"`；运行时 `/api/agent` 为空但 step 使用 `build`，与源码一致。
  - `packages/core/src/worktree.ts` 要求 `from` 是已登记 worktree/root；运行时用 `project.canonical` 创建成功，用非 canonical 路径会失败。
  - `packages/core/src/snapshot.ts` 的 `scope()` 用 `FSUtil.contains(worktree, location.directory)` 校验；这解释了 `/var` 与 `/private/var` 不一致时 diff 为空。
  - `packages/core/src/bus.ts` 注明全局 subscribe 是 volatile；durable replay 是 `Bus.log` / `/api/experimental/session/:sid/log`，需要 `events.persist`。默认 CLI 未开启 persist，实测 `/log` 只有 `log.synced`；OpenCode TUI 重连后靠 `message.sync` / permission / form projection resync。
  - agentd `/api/session/{sid}/event?after=` 合并 durable replay + live 并按 event ID 去重；`go test ./pkg/server -run TestSessionReplay` 通过。
  - Tether 已为 agentd 增加 `HttpAgentClient.session_replay()`（`/history` 分页）并在 `_reconcile()` 中 replay `after=last_seq`；`_recover_stale_turns()` / `_reconcile()` 在 finish 前拉最终快照。新增 replay + 断线完成测试通过。
- 未验证 / 明确范围外：
  - PTY websocket connect / persistent PTY 交互（Tether 不使用；仅验证了 list/create/delete）。
  - fork/revert 的完整语义边界（仅验证基本调用和 clear，不把 fork/revert 作为 Tether 首期能力）。

# OpenCode HTTP API 参考与实测矩阵

- 状态：已验证
- 日期：2026-10-28
- OpenCode 源码：`~/Documents/opencode` commit `4617210822`
- 运行方式：`bun run --cwd packages/cli src/index.ts serve`
- 实测模型：DeepSeek `deepseek-flash`，`baseURL=https://api.deepseek.com`
- 实测测试：`tests/test_opencode_live_contract.py`（默认 skip，设置 `OPENCODE_BASE_URL` / `OPENCODE_PASSWORD` 后运行）

本文只覆盖 Tether 需要或可能误用的接口，目的是防止两类错误：

1. 用错 HTTP API（路径、方法、payload、响应字段）；
2. 误以为 OpenCode 不支持某能力，实际是 API 选择错误。

## 1. 认证与基础

| 方法 | 路径 | 说明 | Tether 用法 |
|---|---|---|---|
| GET | `/api/info` | 版本、pid、urls、paths、capabilities | `/status`、健康检查 |
| GET | `/api/location?location[directory]=...` | 解析 location 与 project | isolated 解析 projectID/canonical |
| GET | `/api/project` | 列出已知 project | 可选；不要用 PATCH 改 canonical |
| PATCH | `/api/project/:projectID` | 修改 project canonical/元数据 | 不使用 |
| GET | `/api/config?location[directory]=...` | 返回配置文档数组 `Config.Entry[]` | `/config` 摘要；不要直接暴露 raw |
| GET | `/api/config/shell` | 可用 shell 列表 | 不使用 |
| GET | `/api/command` | 当前 location 的 command 列表 | command 转发 |
| GET | `/api/skill` | 当前 location 的 skill 列表 | skill 转发 |

认证是 HTTP Basic，用户名固定 `opencode`，密码来自 `OPENCODE_PASSWORD` / `OPENCODE_SERVER_PASSWORD`。SSE 同样需要认证。

## 2. Worktree

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/worktree?projectID=...` | 列出 project 的 worktree |
| POST | `/api/worktree` | `{projectID, from, branch?, directory?, name?}` -> `{directory}` |
| DELETE | `/api/worktree` | `{projectID, directory, force}`，DELETE 带 JSON body |
| POST | `/api/worktree/refresh` | 重新发现 worktree |

实测要点：

- `from` 必须是已登记 worktree/root，使用 `/api/location` 返回的 `project.canonical`。
- OpenCode 会把 `/var/...` 规范化为 `/private/var/...`；所有路径比较必须先 `realpath`。
- worktree create 会执行 project 的 setup/start script。
- `DELETE /api/worktree` 的 JSON body 和 `force=true` 实测可用。

## 3. Agent / Model

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/agent` | 当前 location 的 agent 列表；bare server 可以是 `[]` |
| GET | `/api/agent/:agentID` | 单个 agent；不存在返回 404 |
| GET | `/api/model` | 当前 location 的 model 列表 |
| GET | `/api/model/default` | 默认 model，可能为 `null` |

实测要点：

- `build` 是默认 agent ID（`Agent.defaultID`），但 `/api/agent` 可以为空；session 未指定 agent 时仍以 `build` 运行。
- Tether adapter 不应因空数组而失败；应合成 `build` 或省略 agent。
- `mode`: `primary` 可作主 agent，`subagent` 只能被 task 工具调用，`all` 两者都可。
- Model 引用是 `{providerID, id, variant?}`；Tether 用 `provider/id#variant` 字符串表示。

## 4. Session 生命周期

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/session` | 列表，支持 `directory` / `project` / cursor |
| POST | `/api/session` | `{agent?, model?, title?, location?, permissions?, parentID?}` |
| GET | `/api/session/:sid` | 单个 session |
| PATCH | `/api/session/:sid` | 改 `title/metadata/permissions`；**不是** `/title` |
| DELETE | `/api/session/:sid` | 删除 session |
| GET | `/api/session/active` | `{data: {sid: {type: "running"}}}`，idle 时为 `{}` |
| POST | `/api/session/:sid/agent` | `{agent}` -> 204 |
| POST | `/api/session/:sid/model` | `{model: Model.Ref}` -> 204 |
| POST | `/api/session/:sid/interrupt` | 返回 `{interrupted: bool}`；支持 `?resume=true` |
| POST | `/api/session/:sid/compact` | 入队压缩，返回 inbox item；成功率不等于完成 |
| POST | `/api/experimental/session/:sid/wait` | 阻塞到 idle；无 timeout 参数；idle 时立即 204 |
| POST | `/api/session/:sid/background` | 把可后台的阻塞工具移入后台；idle no-op |
| POST | `/api/session/:sid/view` | `{idle: ms}` 标记已查看 |
| PUT | `/api/session/:sid/environment` | `{variables}` 替换 session shell 环境 |
| POST | `/api/session/:sid/move` | 移动 session location；Tether 暂不使用 |

实测要点：

- 冷启动 location 约 19–31 秒；`request_timeout_s` 应设 60–120 秒。
- 重启后 session/message 保留，可继续 prompt。
- 重启后 pending form/permission 丢失（内存态）。
- `interrupt` idle 返回 `{"interrupted": false}`；不要只判断 HTTP 200。
- `wait` 运行中阻塞到 idle，idle 立即返回。

## 5. Prompt / inbox / synthetic

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/session/:sid/prompt` | `{text, files?, agents?, skills?, id?, delivery?, resume?}` |
| POST | `/api/session/:sid/synthetic` | 追加 synthetic 输入；`resume=false` 只入队不执行 |
| GET | `/api/session/:sid/inbox` | 未投递的 user/synthetic/compaction/move |
| DELETE | `/api/session/:sid/inbox/:inboxID` | 取消未投递项 |
| PATCH | `/api/session/:sid/inbox/:inboxID` | `{delivery: "queue"|"steer"}` |
| POST | `/api/session/:sid/command` | 执行 OpenCode command，`{name, text?, ...}` |
| POST | `/api/experimental/session/:sid/skill` | 激活 skill，`{id, resume?}` |
| POST | `/api/session/:sid/generate` | 基于当前上下文生成 transient text（不写历史） |

实测要点：

- `prompt` 的字段是 `text`，不是 `prompt`；`files` 是 `{uri,name?,description?}`，mime 由 data URL 推断。
- `delivery` 是 `queue` / `steer`；`resume=false` 可以只入队，不触发执行。
- inbox 是准确的“未投递输入”来源；Tether 的本地队列可按需与 inbox 对齐。
- `synthetic` 是 bridge context 的原生入口；当前 Tether 仍用 prompt 前缀注入，后续可评估切换。
- `command`/`skill` 是 Tether 误以为“不支持”的能力；未知 command/skill 分别返回 `CommandNotFoundError` / `SkillNotFoundError`。

## 6. 读取与恢复

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/api/session/:sid/message` | 分页 messages，`order`/`limit`/`cursor`/`type` |
| GET | `/api/session/:sid/message/:mid` | 单条 message |
| GET | `/api/session/:sid/context` | 当前 active context（最后一次 compaction 之后） |
| GET | `/api/session/:sid/diff` | `from?`/`to?`/`context?`，返回 `FileDiff[]` |
| GET | `/api/experimental/session/:sid/log` | durable event log，可 follow |
| GET | `/api/experimental/session/:sid/export` | 导出完整 transcript |

实测要点：

- `step.ended.files` 在 git + snapshots + canonical path 下返回变更文件；`session.diff` 返回对应 patch。
- `write` 的 tool success 没有文件路径；不要依赖 `metadata.files`。
- 有效图片的 `read` tool success 会包含 `{type:"file", uri:"data:image/...", mime}`；测试必须用有效图片，损坏图片会被渲染为 omitted text。
- `context` 可用于恢复 active context；它不是“当前 turn 快照”，当前 turn 仍需 message 边界。

## 7. HITL：Permission 与 Form

### Permission

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/session/:sid/permission` | **评估**权限，返回 `{id, effect}`；只有 `effect=ask` 才创建 pending request |
| GET | `/api/session/:sid/permission` | session 的 pending requests |
| GET | `/api/session/:sid/permission/:rid` | 单个 pending request |
| POST | `/api/session/:sid/permission/:rid/reply` | `{decision: "once"|"always"|"reject", message?}` |
| GET | `/api/permission/request?location[directory]=...` | location 范围 pending requests |
| GET | `/api/permission/saved` | saved permissions |
| DELETE | `/api/permission/saved/:id` | 删除 saved permission |

关键实测结论：

- `POST /session/:sid/permission` **不是**“创建 pending”接口；effect 可能是 `allow`/`deny`，此时没有 pending，reply 会 404。
- 真实 pending 应由 tool 执行产生 `permission.asked`，或评估结果 `effect=ask`。
- `reply` 的字段是 `decision`，不是 `reply`。
- `decision=always` 且 request 有 `save` 时才会写 saved permission。
- `decision=reject` 会拒绝同 session 的整批 pending permission。

### Form（question 工具的底层）

| 方法 | 路径 | 说明 |
|---|---|---|
| POST | `/api/session/:sid/form` | `{title, metadata?, fields}` -> form |
| GET | `/api/session/:sid/form` | session 的 pending forms |
| GET | `/api/session/:sid/form/:fid` | form + `state` |
| POST | `/api/session/:sid/form/:fid/reply` | `{answer: {key: value}}` |
| DELETE | `/api/session/:sid/form/:fid?message=...` | 取消 |
| GET | `/api/form?location[directory]=...` | location 范围 pending forms |

实测要点：

- `question` 工具生成 `q0/q1...` fields，option 是 `{value,label}`；回复用 key/value，不用 label。
- `DELETE` 带 `message` 时 question 工具得到 `ToolFailure`；不带 message 时走 defect，可能结束 step。
- Form 是**内存态**：`packages/core/src/form.ts` 使用内存 `Cache`，pending form 不写数据库；`packages/core/src/location-lifecycle.ts` 在 location shutdown 时直接 `forms.close`/`permission.close`。
- Permission pending 也是**内存态**：`packages/core/src/permission.ts` 用 `Map`，shutdown 时 reject/clear。
- 因此进程崩溃/重启后，`GET /api/session/{sid}/form` 和 `/permission` 会返回空；这不是 Tether 查询方式错误，而是 OpenCode 没有持久化这些 pending 交互。重启只能由用户重新发起，Tether 无法通过 session id 恢复。

## 8. 事件

| 事件 | 用途 |
|---|---|
| `server.connected` | 连接建立 |
| `session.execution.started/succeeded/failed/interrupted` | turn 状态权威来源 |
| `session.text.started/delta/ended` | 文本流 |
| `session.reasoning.*` | reasoning |
| `session.step.started/ended/failed` | step、usage、files |
| `session.tool.input.*` / `tool.called` / `tool.progress` / `tool.success` / `tool.failed` | 工具生命周期 |
| `permission.asked/replied` | HITL |
| `form.created/replied/cancelled` | question/form |
| `session.compaction.*` | 压缩 |
| `session.retry.scheduled` | 重试 |

关键实测结论：

- 当前 commit 的 server 未发布 `session.status`（schema/event manifest 中存在，client 由 `session.execution.*` 推导）；其他版本/部署可能发布。Tether 必须同时兼容 `session.status` / `session.idle` 和 `session.execution.*`。
- SSE frame 只有 `data: {...}`，没有 `event:` 字段；`httpx-sse` 可解析。
- 事件是 live-only，不保证全局 replay；断线后必须 reconcile。
- `form.created` 的 sessionID 在 `data.form.sessionID`，adapter 必须显式设置规范 `Event.session_id`。
- `tool.called` 没有 name；用 `tool.input.started.name` 缓存。

## 9. OpenCode 能力选择建议

| 需求 | 应使用 | 不要使用 |
|---|---|---|
| 发送用户消息 | `POST /prompt` | `/synthetic`（bridge/internal） |
| bridge context | `POST /synthetic`（`resume=false` 或 metadata） | 无 |
| 队列管理 | `/prompt` + `/inbox` | 猜测 queue depth |
| 通用 slash command | `/session/:sid/command` | 当普通 prompt 文本 |
| Skill | `/session/:sid/skill` 或 prompt `skills` | 误以为只能 prompt |
| turn 结束 | `session.execution.*` + `session.status`/`session.idle` 兼容 | 只等其中一种 |
| 恢复文本/媒体 | `/message` + turn 边界 + `/diff` | 只看全局 SSE |
| 变更文件 | `step.ended.files` / `/diff` | `tool.success.metadata.files` |
| 权限 pending | `permission.asked` / `GET permission` | `POST permission` 当作创建 |
| question/form | `/form` + key/value | 只用 label |
| 标题 | `PATCH /session/:sid` | `/title` |
| 默认模型 | `/api/model/default` | 猜测第一个 model |
| worktree 源 | `project.canonical` | 原始 symlink path |

## 10. 实测覆盖

`tests/test_opencode_live_contract.py` 覆盖：

- Basic auth、`/api/info`
- location -> projectID/canonical
- worktree create/list/remove
- session create/list/patch/delete、location、permissions
- prompt `resume=false` -> inbox list/cancel
- synthetic `resume=false` -> inbox list/cancel
- context、active、interrupt、background、view、environment
- command/skill 列表与错误体；`command` 执行、`skill` 激活
- fork、revert stage/clear
- PTY list/create/delete
- form global/session/reply/cancel
- permission evaluate/pending/reply、saved permission
- SSE `server.connected` / `form.created` / `permission.asked`
- 可选 model 测试：`OPENCODE_MODEL=deepseek/deepseek-flash`
  - text、reasoning（`deepseek-v4-pro#high`）、tool read、图片 file part、tool write、`step.ended.files`、`session.diff`、`wait`、`compact`、fork、revert、command、skill

运行：

```sh
OPENCODE_BASE_URL=http://127.0.0.1:4099 \
OPENCODE_PASSWORD=... \
.venv/bin/python -m pytest tests/test_opencode_live_contract.py -q

# 带真实模型
OPENCODE_BASE_URL=http://127.0.0.1:4099 \
OPENCODE_PASSWORD=... \
OPENCODE_MODEL=deepseek/deepseek-flash \
.venv/bin/python -m pytest tests/test_opencode_live_contract.py -q
```

## 11. 已验证的边界

- 真实 DeepSeek `deepseek-flash` 已验证 text/tool/图片 file part/write/diff。
- 真实 DeepSeek `deepseek-v4-pro#high` 已验证 `session.reasoning.started/delta/ended`。
- `session.command` 的 `review` 已执行并结束 turn。
- `session.skill` 已用 `resume=false` 验证激活。
- fork 和 revert stage/clear 已验证。
- PTY list/create/delete 已验证；PTY websocket connect 不在 Tether 范围内，未测。

## 12. 断线重连与 durable replay

OpenCode 有两套事件通道：

- `GET /api/event`：volatile live，源码明确说明不跨断线，断开期间的事件不会补发。
- `GET /api/experimental/session/:sid/log?after=<seq>&follow=<bool>`：按 session aggregate 的 durable replay。
  - `after` 是 exclusive sequence，必须 >= 0。
  - 先回放历史 durable events，再发 `log.synced` marker，再继续 live。
  - 需要服务端启用 `events.persist`；默认 `opencode serve` CLI 没有设置该选项，实测 `/log` 只返回 `log.synced`，没有历史事件。
  - 源码测试：`packages/core/test/session-log.test.ts` 使用 `Bus.configured({ persist: true })`。

OpenCode 自身的 TUI 在重连后主要重新同步 projections（session/messages/permissions/forms），而不是依赖全局事件 replay。

Tether 不能只依赖 `/api/event`：

- agentd 应使用 `/api/session/{sid}/event?after=<seq>`（源码会合并 durable replay + live 并按 event ID 去重，`go test ./pkg/server -run TestSessionReplay` 通过）。
- OpenCode 默认 CLI 没有 durable replay 时，必须做 projection resync；启用 persist 时才使用 `/log`。OpenCode TUI 的恢复方式就是 `data.session.message.sync` + permission/form sync，而不是重放全局 SSE。
- 对断线期间已经结束的 turn，必须拉取最终 message/diff 快照再 finish；不能只检查 `active_sessions()`。

### 12.1 推荐部署基线

如果 Tether 只需要“断线后恢复到最终正确状态”，默认部署：

1. 使用 `opencode serve`；CLI 默认使用 data 目录下的持久数据库。若改用 embedder/SDK，必须显式设置持久化的 `database.path`（SDK 默认可能是内存库）。
2. Tether 使用 projection resync：`/message` + `/permission` + `/form` + `active_sessions`。
3. 不要承诺逐事件 replay；`/log` 在默认 CLI 下只有 marker。

如果 Tether 需要**精确的 durable event replay**，部署必须满足：

1. OpenCode 由 embedder/sidecar 启动，并显式设置：

   ```ts
   events: { persist: true }
   ```

   例如 `@opencode/sdk` / `@opencode/server` 的嵌入启动路径，或 workerd 部署（`packages/server/src/workerd.ts` 已设置 `events: { persist: true }`）。

2. 使用持久化数据库路径。
3. 把 OpenCode 的 HTTP router 暴露给 Tether；stock `opencode serve` CLI 当前不提供 `events.persist` 开关。
4. 启动后必须验证：

   ```text
   GET /api/experimental/session/<sid>/log?after=0
   ```

   返回 durable events，而不是只有 `log.synced`。

5. 接受 durable event 表带来的存储增长和备份成本；日志保留/清理策略属于部署方责任。

如果部署环境无法设置 `events.persist`，正确选择是 projection resync，而不是假设 `/log` 可用。

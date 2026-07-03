# Claude Agent SDK 接入与 SSE 流式推理展示 Spec

## 1. 背景

当前 `ClaudeCodeService` 仍是最小 mock 封装，项目/会话/消息链路已经跑通，但还没有真正调用 Claude Code Agent SDK。下一步要把后端会话发送接口升级为真实 Agent SDK 调用，并像 Codex app 一样把 agent 执行过程实时展示到前端。

本 spec 基于 Claude Code Agent SDK 官方文档：

- Python pip 安装包名：`claude-agent-sdk`
- Python 入口：`query()`
- 配置对象：`ClaudeAgentOptions`
- 流式输出：`include_partial_messages=True`
- 流式事件：`StreamEvent`

重要约束：这里的“推理详情”指用户可见的 agent 过程信息，包括文本增量、工具调用开始/结束、工具输入摘要、最终结果、错误状态；不展示或伪造模型隐藏 chain-of-thought。

## 2. 目标

1. 接入 Claude Agent SDK Python 版，替换当前 mock `ClaudeCodeService`。
2. 新增 SSE 接口，实时输出 agent 运行过程。
3. 前端消息区按 Codex app 风格展示：
   - assistant 文本增量；
   - 正在使用的工具；
   - 工具调用完成状态；
   - 最终完成 / 失败状态。
4. 后端保存用户消息与最终 assistant 消息。
5. 环境变量支持：
   - 优先使用 `ANTHROPIC_API_KEY`；
   - 若缺失，则把 `ZHIPU_API_KEY` 映射为 `ANTHROPIC_API_KEY` 供 demo 使用。
6. API key 不写入 git、SQL、日志、响应或前端代码。
7. 开放 Claude Code SDK 全部能力，包括命令行工具、文件读写、MCP、子代理、skills/plugins 等 SDK 可用能力。

## 3. 非目标

本阶段不做：

- 不做多人协作；
- 不做 worktree 隔离；
- 不做真实桌面目录绝对路径桥接；
- 不做隐藏推理链输出；
- 不做 WebSocket，先使用 SSE；
- 不做复杂任务取消队列，MVP 只做连接断开检测与 session 状态落库。

## 4. 关键设计判断

### 4.1 为什么用 SSE

当前交互是“用户发一条 prompt，后端持续推送 agent 进度”，数据方向主要是服务端到客户端。SSE 比 WebSocket 更轻，浏览器原生支持 `EventSource`；若后续需要双向交互、审批、取消、补充输入，再升级 WebSocket。

### 4.2 Python SDK 调用形态

官方 quickstart 使用：

```python
from claude_agent_sdk import query, ClaudeAgentOptions

async for message in query(prompt=prompt, options=options):
    ...
```

开启流式 token / 工具事件：

```python
options = ClaudeAgentOptions(
    tools={"type": "preset", "preset": "claude_code"},
    include_partial_messages=True,
    permission_mode="bypassPermissions",
)
```

当 `include_partial_messages=True` 时，SDK 会在完整 `AssistantMessage` / `ResultMessage` 外额外产出 `StreamEvent`，其中 `event.type` 可能是：

- `message_start`
- `content_block_start`
- `content_block_delta`
- `content_block_stop`
- `message_delta`
- `message_stop`

文本增量来自 `content_block_delta` 且 `delta.type == "text_delta"`；工具输入增量来自 `delta.type == "input_json_delta"`。

### 4.3 全功能开放策略

本任务要求开放 Claude Code SDK 全部功能，因此 MVP 不再限制为 `Read/Grep/Glob`。默认策略：

- `permission_mode="bypassPermissions"`：允许 SDK 按任务需要执行可用工具；
- `tools={"type": "preset", "preset": "claude_code"}`：使用 Claude Code 默认工具预设；
- 不设置 `allowed_tools` 作为工具裁剪手段：官方语义中 `allowed_tools` 更接近“自动批准这些工具”，不是安全白名单；
- 命令行能力：允许 Bash / 命令执行类工具；
- 文件能力：允许 Read / Write / Edit / Glob / Grep 等文件系统工具；
- MCP 能力：允许 SDK 使用配置内的 MCP servers；
- 扩展能力：不屏蔽 SDK 支持的 subagents、skills、plugins 等能力。

安全边界从“工具白名单”转为“运行环境边界 + 可见性 + 记录”：

- SSE 必须实时展示正在使用的工具、命令和状态；
- 后端必须记录最终消息、工具摘要和失败状态；
- API key 仍不可泄露；
- 未来真实项目绝对路径接入时，cwd 必须经 `path_guard` 与 allowlist 校验。

### 4.4 “推理详情”的展示边界

前端展示 Codex app 风格的过程流：

- `assistant_delta`：可见文本片段；
- `tool_start`：工具开始，例如 Read / Grep / Bash；
- `tool_delta`：工具输入 JSON 片段的安全摘要；
- `tool_done`：工具完成；
- `agent_done`：任务完成；
- `agent_error`：任务失败；
- `usage`：如果 SDK 结果提供 usage，则记录与展示。

不展示隐藏 chain-of-thought；如果 SDK 文本块包含普通说明文本，则按 assistant 文本显示。

## 5. 后端 API 设计

### 5.1 保留现有非流式接口

`POST /v1/sessions/{session_id}/messages`

用途：

- 兼容当前前端；
- 可用于不需要实时展示的场景；
- 内部可以复用同一 `ClaudeCodeService`，但收集完整结果后一次返回。

### 5.2 新增 SSE 流式接口

`POST /v1/sessions/{session_id}/messages/stream`

说明：SSE 标准 `EventSource` 只支持 GET。为了保留 JSON body，推荐前端使用 `fetch()` 读取 `ReadableStream`，协议仍按 `text/event-stream` 输出；不使用原生 `EventSource`。

请求：

```json
{
  "user_id": 1,
  "content": "解释这个项目的启动链路"
}
```

响应头：

```text
Content-Type: text/event-stream
Cache-Control: no-cache
Connection: keep-alive
```

事件格式：

```text
event: assistant_delta
data: {"content":"这里是增量文本"}

event: tool_start
data: {"tool":"Read","summary":"正在读取文件"}

event: tool_done
data: {"tool":"Read"}

event: agent_done
data: {"message_id":123,"session_id":9}
```

## 6. SSE 事件契约

### 6.1 统一 Envelope

```json
{
  "type": "assistant_delta",
  "session_id": 9,
  "message_id": null,
  "sequence": 12,
  "data": {},
  "created_at": "2026-07-03T09:00:00Z"
}
```

字段：

- `type`：事件类型；
- `session_id`：本地会话 id；
- `message_id`：落库后才有；流式中可为 `null`；
- `sequence`：单次请求内递增序号，前端用于排序；
- `data`：事件载荷；
- `created_at`：服务端时间。

### 6.2 事件类型

| type | data | 说明 |
| --- | --- | --- |
| `user_message_saved` | `{ "message_id": 1 }` | 用户消息已落库 |
| `agent_started` | `{ "session_id": 9 }` | SDK 开始运行 |
| `assistant_delta` | `{ "content": "..." }` | assistant 文本增量 |
| `tool_start` | `{ "tool": "Read" }` | 工具调用开始 |
| `tool_delta` | `{ "tool": "Bash", "partial": "..." }` | 工具输入片段或摘要 |
| `tool_done` | `{ "tool": "Read" }` | 工具调用结束 |
| `assistant_message_saved` | `{ "message_id": 2 }` | assistant 最终消息已落库 |
| `agent_done` | `{ "status": "idle" }` | 任务完成 |
| `agent_error` | `{ "message": "..." }` | 任务失败 |
| `heartbeat` | `{}` | 长任务保活 |

## 7. 后端模块设计

### 7.1 依赖

`requirements.txt` 新增：

```text
claude-agent-sdk
```

### 7.2 配置与环境变量

新增配置段或扩展 `ProjectSettings`：

```yaml
claude_agent:
  enabled: true
  permission_mode: "bypassPermissions"
  include_partial_messages: true
  command_timeout: 300
  default_cwd: "."
  strict_mcp_config: false
  mcp_servers: {}
```

环境变量：

```text
ANTHROPIC_API_KEY=<真实 key>
ZHIPU_API_KEY=<demo key>
```

启动或调用前执行映射：

```python
if not os.getenv("ANTHROPIC_API_KEY") and os.getenv("ZHIPU_API_KEY"):
    os.environ["ANTHROPIC_API_KEY"] = os.environ["ZHIPU_API_KEY"]
```

注意：

- 不把 key 写进 yaml；
- 不把 key 写进 `CLAUDE.md`；
- 不在日志打印 key；
- `.env` 可本地保存，必须保持 git ignored。

### 7.3 服务层

修改 `app/services/claude_code_service.py`：

```python
class ClaudeCodeService:
    async def stream_session(
        self,
        *,
        cwd: str | None,
        prompt: str,
        session_history: list[SessionMessageOut],
    ) -> AsyncIterator[ClaudeCodeStreamEvent]:
        ...
```

输出内部事件模型：

```python
class ClaudeCodeStreamEvent(BaseModel):
    type: str
    data: dict
```

内部职责：

1. 准备环境变量；
2. 构造 `ClaudeAgentOptions(tools={"type":"preset","preset":"claude_code"}, include_partial_messages=True, permission_mode="bypassPermissions", mcp_servers=...)`；
3. 调用 `query(prompt=..., options=...)`；
4. 把 SDK message 映射为内部事件；
5. 累积 assistant 文本用于最终落库；
6. 捕获 SDK 异常并转为 `BizException` 或 `agent_error`。

### 7.4 API 层

新增：

`app/api/v1/sessions_router.py`

```text
POST /v1/sessions/{session_id}/messages/stream
```

实现方式：

- 使用 FastAPI `StreamingResponse`；
- media type 为 `text/event-stream`；
- generator 内调用 `SessionService.stream_message()`；
- 每个事件序列化为 SSE frame。

### 7.5 SessionService

新增：

```python
async def stream_message(
    self,
    session_id: int,
    payload: SessionMessageCreateIn,
) -> AsyncIterator[SessionSseEvent]:
    ...
```

流程：

1. 校验用户和会话归属；
2. 如果 session `running`，立即输出 `agent_error` 后结束；
3. 写入 user message；
4. session 标记 `running`；
5. yield `user_message_saved`；
6. yield `agent_started`;
7. 遍历 `ClaudeCodeService.stream_session()`；
8. 每个 SDK 事件实时 yield 给路由；
9. 累积最终 assistant 内容；
10. 写入 assistant message；
11. session 标记 `idle`；
12. yield `assistant_message_saved` 与 `agent_done`。

失败路径：

1. 写入 failed assistant message；
2. session 标记 `failed`；
3. yield `agent_error`；
4. 不把异常堆栈直接发给前端。

## 8. 前端设计

### 8.1 API 调用

新增 `sendStreamingMessage()`：

```ts
async function sendStreamingMessage(sessionId: number, body: SendBody, onEvent: (event: SseEvent) => void) {
  const response = await fetch(`/v1/sessions/${sessionId}/messages/stream`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  // 读取 response.body，按 SSE frame 分割
}
```

### 8.2 UI 展示

Codex app 风格：

- 用户消息立即追加；
- assistant 消息占位，文本流式 append；
- 工具调用显示为轻量状态行，例如：
  - `Using Read...`
  - `Using Grep...`
  - `Bash done`
- 完成后状态从 `running` 改为 `idle`；
- 失败后 assistant 气泡显示错误摘要。

### 8.3 状态结构

```ts
type StreamEvent =
  | { type: "assistant_delta"; data: { content: string } }
  | { type: "tool_start"; data: { tool: string } }
  | { type: "tool_done"; data: { tool: string } }
  | { type: "agent_done"; data: { status: string } }
  | { type: "agent_error"; data: { message: string } };
```

## 9. 安全设计

1. API key 只从环境变量读取。
2. SSE 不输出 key、环境变量、完整异常栈。
3. 本阶段按用户要求开放全部工具，包括 Bash/Edit/MCP；风险控制不靠工具白名单。
4. SSE 必须展示命令行工具与 MCP 工具的开始、参数摘要、结束和失败状态。
5. 若 `root_path` 为空，SDK 运行在后端安全默认目录，不能声称已进入用户选择目录。
6. 后续真实目录桥接必须走 `path_guard` 和 allowlist。
7. 生产环境需要额外补审批流、沙箱、审计和取消能力；但 MVP 先按全功能开放实现。

## 10. 数据库设计

不新增表。

沿用：

- `session_message.content` 保存最终 assistant 文本；
- `session_message.tool_summary` 保存工具调用摘要；
- `session_message.diff_summary` 保存文件改动摘要；
- `project_session.status` 保存 `idle/running/failed`。

SSE 增量事件默认不逐条入库，避免消息表膨胀。若后续需要断线恢复中间过程，再新增 `session_event` 表。

## 11. 验收标准

1. `pip install -r requirements.txt` 后可 import `claude_agent_sdk`。
2. 未设置 `ANTHROPIC_API_KEY` 但设置 `ZHIPU_API_KEY` 时，后端可完成 demo 映射。
3. `POST /v1/sessions/{session_id}/messages/stream` 返回 `text/event-stream`。
4. 前端能实时显示 assistant 文本增量。
5. 前端能显示工具调用开始/结束状态。
6. Bash / 文件编辑 / MCP 等 SDK 工具事件能通过 SSE 展示为过程卡片或状态行。
7. SDK 完成后 assistant 最终消息入库。
8. 失败时 session 标记 `failed`，前端收到 `agent_error`。
9. 不在日志、响应、前端 bundle、文档中泄露 API key 明文。
10. `python -m compileall -q app` 通过。
11. `pnpm run build` 通过。

## 12. 实施顺序

1. 新增依赖 `claude-agent-sdk`；
2. 新增 `ClaudeAgentSettings` 配置段，默认全能力开放；
3. 实现环境变量映射工具；
4. 重写 `ClaudeCodeService.stream_session()`；
5. 新增 `SessionService.stream_message()`；
6. 新增 SSE 路由；
7. 前端实现 fetch + SSE parser；
8. 前端消息区接入流式状态；
9. 联调用 `ZHIPU_API_KEY -> ANTHROPIC_API_KEY` demo；
10. 同步 `CLAUDE.md`；
11. 跑后端编译、前端构建和 HTTP/SSE 烟囱。

## 13. 待确认问题

1. 如果 Web 端没有真实 `root_path`，SDK 运行目录先用仓库根目录还是后端配置的安全目录？
2. MCP servers 初始接哪些：沿用项目现有 `mcp.client.servers`，还是单独给 Claude Agent SDK 一套配置？
3. SSE 中工具输入是否只展示工具名和简短摘要，避免把长 JSON 刷满界面？
4. 是否需要“停止生成”按钮；如果需要，下一阶段要做任务取消与连接管理。

# 仿 Codex App 的项目创建、本地导入与多会话 Spec

## 1. 背景

当前工作台页面已经有 Codex app 风格的前端骨架，但项目与会话仍来自 `mockProjectGroups`。用户目标不是普通 Web 文件上传，而是仿 Codex app 的本地项目体验：

- 用户通过系统目录选择弹窗导入本地项目；
- 项目名称取所选本地目录名；
- 一个项目下可以有多个会话；
- Web MVP 会话先绑定项目身份；真实工作区路径由后续桌面壳或后端桥接提供；
- 底层由后端调用 Claude Code SDK 作为 agent 执行基座，按需读取文件、生成响应、修改代码、产生 diff。

这意味着设计重点从“上传文件夹元信息”改为“保存项目身份，后续在具体会话需求中由 Claude Code SDK 按需读取文件”。Web MVP 不保存文件列表，也不要求用户手填路径。

## 2. 目标

1. 左侧项目列表从后端接口加载，替换前端 mock。
2. 支持创建项目：用户不填写项目名称和路径，点击“使用现有文件夹”选择目录，项目名称取目录名。
3. 创建项目时不扫描和入库文件清单；文件内容在具体会话需求中按需读取。
4. 支持项目下多个会话：创建、列表、切换、恢复上下文。
5. 会话执行层通过 `ClaudeCodeService` 封装，后续接入真实 Claude Code SDK。
6. 前端实现参考截图的“创建项目”弹窗与基础联调。
7. 后端提供项目、会话、会话消息的最小闭环接口。

## 3. 非目标

本阶段先不做：

- 不做完整终端模拟器；
- 不做云端运行环境；
- 不做 Git worktree 隔离；
- 不做复杂权限系统，先沿用当前登录用户；
- 不做多人协作；
- 不做前端直接读取任意本机路径；
- 不承诺 Claude Code SDK 的完整工具能力，先封装最小会话调用接口。

## 4. 核心设计判断

### 4.1 Codex App 风格不是“上传整个文件夹”

目标体验更接近：

```text
project.name = 选择的目录名
project.root_path = 仅在桌面壳或后端桥接拿到受控绝对路径时保存
Claude Code SDK 在具体会话需求中按需读取文件、执行命令、产出回复和改动
```

创建项目时不需要把整个文件夹内容上传或扫描进后端数据库；后端只保存项目身份。会话过程中，SDK 根据具体需求再按需读取相关文件。

### 4.2 普通 Web 前端拿不到真实绝对路径

浏览器里的 React 页面不能可靠获取 `/Users/...` 这种真实路径。因此要仿 Codex app，有三种路径入口：

1. **浏览器目录选择**：只能拿目录名，不能拿 macOS 绝对路径。MVP 采用这个方式，不要求用户手填。
2. **服务端预设根目录浏览**：后端只允许浏览配置白名单下的目录，前端展示目录树。更安全，体验也接近桌面应用。
3. **桌面壳桥接选择目录**：如果未来有 Electron/Tauri/原生桌面壳，可以调用系统目录选择器拿真实路径。

本阶段使用浏览器目录选择：优先 `showDirectoryPicker()`，降级到 `webkitdirectory` 文件夹选择；两者都只用来识别目录名，不上传文件内容，不保存文件清单。

### 4.3 后端必须做路径边界控制

如果未来通过桌面壳或后端桥接拿到真实绝对路径，后端不能接受任意路径后直接读取。必须引入 allowlist：

```text
PROJECT_ALLOWED_ROOTS=/Users/zhili.deng/dzl-py,/Users/zhili.deng/codex
```

未来拿到真实路径后，所有文件读取和 Claude Code SDK cwd 都必须在 `root_path` 之内。

## 5. 推荐方案

### 方案 A：浏览器目录选择 + 项目身份入库（当前 MVP）

流程：

1. 用户点击左侧项目区创建按钮；
2. 打开“创建项目”弹窗；
3. 默认项目类型为 `本地`；
4. 用户点击“使用现有文件夹”；
5. 前端打开系统目录选择弹窗；
6. 前端从目录选择结果提取目录名；
7. 后端创建 project 与默认 session；
8. 前端刷新项目列表并选中新项目；
9. 用户在会话输入消息；
10. 后端调用 `ClaudeCodeService` 最小封装。

优点：

- 创建项目体验接近 Codex app；
- 不要求用户手填名称或路径；
- 不在创建项目时扫描文件；
- 后续可用桌面壳或后端桥接升级为真实 cwd。

风险：

- Web MVP 拿不到绝对路径，真实 cwd 绑定需要桌面壳或后端桥接；
- Claude Code SDK 调用需要做并发、超时、取消、日志与错误处理；
- 当前登录体系还不完整，MVP 需要临时 `user_id` 传递。

### 方案 B：桌面壳或后端桥接真实路径（后续）

如果需要 Claude Code SDK 真正以用户选择目录为 `cwd`，需要 Electron/Tauri/原生壳或后端受控目录选择能力，把真实绝对路径交给后端，并经 allowlist 校验后保存 `root_path`。

## 6. 产品交互设计

### 6.1 左侧项目区

左侧项目区保持当前风格：

- 标题：`项目`
- 右侧按钮：
  - 收起 / 展开；
  - 更多；
  - 创建项目；
- 项目下展示多个会话；
- 点击项目名：选中该项目最近会话；
- 点击会话：切换中间内容；
- 项目没有会话时显示空状态和“新建会话”。

### 6.2 创建项目弹窗

第一步：项目类型。

- 标题：`创建项目`
- 项目类型：`本地`
- 描述：`在你的电脑上编辑、运行和测试文件`
- 按钮：
  - `使用现有文件夹`
  - `下一步`

第二步：本地文件夹。

- 不展示项目名称输入框；
- 不展示本地路径输入框；
- 点击 `使用现有文件夹` 后打开系统目录选择弹窗；
- 项目名称自动取选择的目录名；
- 不展示文件数量、文件夹数量、Git 状态或文件样例。

### 6.3 会话体验

项目创建后自动创建默认会话：

- 空项目：`新会话`
- 导入项目：`导入 <project_name>`

会话主区域：

- 顶部显示当前会话标题；
- 中间显示消息流；
- 底部输入框发送 prompt；
- 发送后前端创建一条用户消息；
- 后端调用 Claude Code SDK；
- 返回 assistant 消息、按需读取到的文件引用、diff 摘要；
- 前端更新消息列表。

MVP 可以先用普通 HTTP 请求等待完整响应；后续再升级 SSE / WebSocket 流式输出。

## 7. 后端设计

### 7.1 新增模块

```text
app/api/v1/projects_router.py
app/api/v1/sessions_router.py
app/schemas/project.py
app/schemas/session.py
app/services/project_service.py
app/services/session_service.py
app/services/claude_code_service.py
app/repositories/models/project.py
app/repositories/models/session.py
app/repositories/models/session_message.py
app/repositories/dao/project.py
app/repositories/dao/session.py
app/repositories/dao/session_message.py
app/utils/path_guard.py
scripts/sql/20260703_create_project_session_tables.sql
```

路由注册：

- `app/api/routes.py` 注册 project/session 路由；
- API 前缀保持 `/v1`。

### 7.2 配置

新增配置段 `ProjectSettings`：

```yaml
projects:
  allowed_roots:
    - /Users/zhili.deng/dzl-py
    - /Users/zhili.deng/codex
  max_scan_files: 2000
  max_sample_files: 20
  command_timeout: 300
```

环境变量覆盖：

```text
PROJECTS__ALLOWED_ROOTS=["/Users/zhili.deng/dzl-py"]
PROJECTS__MAX_SCAN_FILES=2000
```

### 7.3 数据模型

#### project

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | integer | 自增主键 |
| user_id | integer | 所属用户 |
| name | varchar(255) | 项目名 |
| root_path | varchar(2048), nullable | 可选本地项目根路径；Web MVP 为空 |
| source_type | varchar(32) | `local_path` |
| is_git_repo | boolean | 未来真实路径桥接后可按需更新 |
| created_at | timestamp | 创建时间 |
| updated_at | timestamp | 更新时间 |

约束：

- Web MVP 中 `root_path` 为空；
- 若未来能拿到真实路径，`root_path` 归一化后保存；
- 不在响应里暴露敏感路径时，可额外返回 `display_path`。

#### project_session

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | integer | 自增主键 |
| project_id | integer | 所属项目 |
| title | varchar(255) | 会话标题 |
| status | varchar(32) | `idle` / `running` / `failed` |
| last_message | text | 最近消息摘要 |
| created_at | timestamp | 创建时间 |
| updated_at | timestamp | 更新时间 |

#### session_message

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| id | integer | 自增主键 |
| session_id | integer | 所属会话 |
| role | varchar(32) | `user` / `assistant` / `system` |
| content | text | 消息正文 |
| status | varchar(32) | `done` / `failed` |
| tool_summary | json/text | SDK 工具调用摘要 |
| diff_summary | json/text | 文件改动摘要 |
| created_at | timestamp | 创建时间 |

## 8. 路径安全设计

### 8.1 path_guard

`app/utils/path_guard.py` 作为后续真实路径桥接时的边界工具，提供：

```python
resolve_project_path(input_path: str) -> Path
ensure_allowed_root(path: Path, allowed_roots: list[str]) -> None
ensure_relative_path(root: Path, relative_path: str) -> Path
```

规则：

- 使用 `Path.resolve()` 归一化；
- 禁止空路径；
- 禁止不存在路径；
- 禁止非目录路径作为项目根；
- 禁止路径逃逸 allowlist；
- 文件读取只能通过 `root_path + relative_path`，并再次确认结果仍在 root 下。

### 8.2 权限与审批

真实 SDK 接入后若触发写文件或命令执行，需要设计审批流；第一阶段可以先只允许只读问答，或在配置里关闭危险工具。

## 9. Claude Code SDK 集成设计

### 9.1 封装边界

新增 `ClaudeCodeService`，业务层不直接散落 SDK 调用：

```python
class ClaudeCodeService:
    async def run_session(
        self,
        *,
        cwd: str | None,
        prompt: str,
        session_history: list[SessionMessage],
    ) -> ClaudeCodeRunResult:
        ...
```

返回结构：

```python
class ClaudeCodeRunResult(BaseModel):
    content: str
    tool_summary: list[dict]
    changed_files: list[str]
    diff_summary: list[dict]
```

### 9.2 会话调用流程

1. API 收到用户 prompt；
2. 校验 `project_id/session_id/user_id`；
3. 写入 user message；
4. 标记 session `running`；
5. 调 Claude Code SDK：
   - `cwd = project.root_path`；Web MVP 为空，真实路径桥接后再传入
   - prompt = 用户输入 + 必要系统约束
   - history = 当前会话历史摘要
6. 写入 assistant message；
7. 更新 session `idle` 与 `last_message`；
8. 返回 assistant message。

### 9.3 失败处理

- SDK 超时：session 标记 `failed`，返回可读错误；
- SDK 异常：写入 failed assistant message；
- 路径失效：返回 `BizValidationError`；
- 并发冲突：同一 session 已 running 时拒绝新 prompt，返回“会话正在运行”。

## 10. API 设计

所有响应继续使用 `ApiResponse.ok(data).to_payload()`。

### GET /v1/projects

请求参数：

```text
user_id=1
```

返回当前用户项目与会话列表。

### POST /v1/projects/import-local-path

导入浏览器选择的本地目录。

请求：

```json
{
  "user_id": 1,
  "directory_name": "claude-sdk"
}
```

行为：

- 创建 project；
- 创建默认 session；
- 返回项目详情。

### POST /v1/projects

与导入现有文件夹共用当前目录名创建逻辑。

请求：

```json
{
  "user_id": 1,
  "directory_name": "new-project"
}
```

### GET /v1/projects/{project_id}/scan

返回项目路径摘要；Web MVP 不扫描文件清单。

### POST /v1/projects/{project_id}/sessions

创建新会话。

请求：

```json
{
  "user_id": 1,
  "title": "新的会话"
}
```

### GET /v1/projects/{project_id}/sessions

列出项目下会话。

### GET /v1/sessions/{session_id}/messages

获取会话消息。

### POST /v1/sessions/{session_id}/messages

发送用户消息并调用 Claude Code SDK。

请求：

```json
{
  "user_id": 1,
  "content": "帮我解释这个项目的启动链路"
}
```

响应：

```json
{
  "message": {
    "id": 10,
    "role": "assistant",
    "content": "这个项目从 main.py 进入...",
    "tool_summary": [],
    "diff_summary": []
  },
  "session": {
    "id": 1,
    "status": "idle"
  }
}
```

## 11. 前端设计

### 11.1 状态结构

```ts
type Project = {
  id: number;
  name: string;
  root_path: string | null;
  display_path: string | null;
  is_git_repo: boolean;
  sessions: ProjectSession[];
};

type ProjectSession = {
  id: number;
  project_id: number;
  title: string;
  status: "idle" | "running" | "failed";
  updated_at: string;
};

type SessionMessage = {
  id: number;
  role: "user" | "assistant" | "system";
  content: string;
  status: "done" | "failed";
};
```

### 11.2 组件拆分

当前 `App.tsx` 已经偏大，建议拆：

```text
web/src/app/api.ts
web/src/app/types.ts
web/src/app/components/AuthPanel.tsx
web/src/app/components/WorkspacePage.tsx
web/src/app/components/ProjectSidebar.tsx
web/src/app/components/CreateProjectModal.tsx
web/src/app/components/ConversationPane.tsx
```

### 11.3 创建项目弹窗交互

- 点击项目区创建按钮打开 modal；
- 默认选中 `本地`；
- 点击 `使用现有文件夹` 打开系统目录选择弹窗；
- 前端从选择结果取目录名；
- 前端调用 `POST /v1/projects/import-local-path`；
- 成功后关闭弹窗、刷新项目列表、选中新项目默认会话。

### 11.4 会话交互

- 点击项目下会话：加载 `GET /v1/sessions/{session_id}/messages`；
- 点击“新会话”：创建 session；
- 底部输入：调用 `POST /v1/sessions/{session_id}/messages`；
- session `running` 时禁用发送按钮；
- assistant 返回后追加消息；
- 若返回 `diff_summary`，显示变更卡片。

## 12. 验收标准

1. 登录后项目列表来自后端。
2. 点击创建按钮弹出截图风格 modal。
3. 点击“使用现有文件夹”可打开目录选择，并以目录名创建项目。
4. 导入成功后左侧出现项目和默认会话。
5. 同一项目下可以创建多个会话并切换。
6. 发送消息后，后端调用 Claude Code SDK，并把 assistant 消息保存到数据库。
7. 创建项目时不保存文件清单；真实路径桥接后后端拒绝 allowlist 外路径。
8. 1280×720、1440×900、390×844 下无横向溢出，左下角个人信息可见。
9. `python -m compileall -q app` 通过。
10. `pnpm run build` 通过。

## 13. 实施顺序

1. 新增 `ProjectSettings` 与 allowlist 配置；
2. 新增 `path_guard.py`；
3. 新增 SQL 初始化脚本；
4. 新增 Project/Session/SessionMessage ORM；
5. 新增 DAO / Service / Schema / Router；
6. 新增 `ClaudeCodeService` 封装，先接最小 SDK 调用；
7. 前端拆 `api.ts/types.ts`；
8. 前端项目列表改接口数据；
9. 实现创建项目 modal 与目录选择；
10. 实现按目录名导入项目；
11. 实现创建会话与切换；
12. 实现发送消息调用 SDK；
13. 做浏览器与接口联调；
14. 同步 `CLAUDE.md`。

## 14. 待确认问题

1. 是否引入 Electron/Tauri/原生壳来获取真实目录绝对路径？
2. 第一阶段 Claude Code SDK 是否允许写文件，还是只做只读问答？
3. 会话响应是否需要流式输出，还是先 HTTP 完整返回？
4. 是否需要支持 worktree 隔离？

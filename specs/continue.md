# 仿 Codex App：刷新页面 / 新开会话任务不中断需求文档

## 1. 需求背景

当前系统中，用户向 AI 提交问题后，任务可能需要较长时间执行，例如：

* 代码分析
* 项目结构扫描
* 文档生成
* 多轮推理
* 工具调用
* 文件读取与修改
* 测试执行

如果任务执行依赖当前浏览器页面连接，那么用户刷新页面、关闭页面、新开会话或网络断开时，任务容易中断。

本需求的核心目标是：
**用户提交任务后，任务在服务端后台持续执行，前端刷新页面或新开会话不会中断任务。**

---

## 2. 本期目标

本期只实现核心能力：

```text
用户提交任务
  ↓
后端创建 task_id
  ↓
任务进入后台执行
  ↓
任务过程持续落库
  ↓
前端订阅任务进度
  ↓
刷新页面 / 新开会话后重新加载任务
  ↓
任务继续展示，不中断
```

---

## 3. 本期不做内容

为了快速打通第一版，以下内容暂不实现：

* 用户权限校验
* 多用户安全隔离
* 沙箱隔离
* 本地目录权限控制
* Worker 崩溃后的精准断点续跑
* 多机器任务迁移
* 复杂任务调度系统
* PR / Diff 审批流程
* 多人协作任务

第一版只解决：

```text
刷新页面不中断
关闭页面不中断
新开会话可恢复
任务过程可重新展示
```

---

## 4. 核心设计原则

## 4.1 页面连接不等于任务生命周期

错误方式：

```text
浏览器请求一直挂着
  ↓
后端一直执行
  ↓
浏览器刷新后任务中断
```

正确方式：

```text
浏览器只负责创建任务和订阅任务
  ↓
任务由服务端后台 Worker 执行
  ↓
任务过程写入数据库
  ↓
前端随时可以重新连接
```

---

## 4.2 刷新页面不等于取消任务

需要区分两个动作：

```text
刷新页面 / 关闭页面 / 网络断开
  = 前端连接断开
  ≠ 任务取消
```

只有用户点击“停止任务”时，才取消任务。

---

## 4.3 所有任务过程必须落库

任务执行过程不能只存在内存里，需要保存到数据库。

至少保存：

* 任务状态
* AI 输出内容
* 工具调用过程
* 执行日志
* 错误信息
* 最终结果

---

## 5. 整体架构

```text
前端页面
  │
  │ 1. 创建任务
  ▼
后端 API
  │
  │ 2. 写入任务表
  │ 3. 投递任务到队列
  ▼
任务队列 Redis / 内存队列
  │
  │ 4. Worker 消费任务
  ▼
后台 Worker
  │
  │ 5. 执行 AI / Agent / 工具调用
  │ 6. 持续写入任务事件
  ▼
数据库
  │
  ├─ agent_task
  └─ agent_task_event
  ▲
  │
  │ 7. 前端通过 task_id 查询和订阅
  │
前端刷新 / 新开会话后重新恢复任务
```

---

## 6. 核心流程

## 6.1 创建任务流程

```text
用户输入问题
  ↓
前端调用 POST /api/tasks
  ↓
后端创建 agent_task 记录
  ↓
生成 task_id
  ↓
写入第一条 task_event
  ↓
投递任务到后台队列
  ↓
返回 task_id
  ↓
前端开始订阅任务事件
```

---

## 6.2 后台执行流程

```text
Worker 获取 task_id
  ↓
查询任务信息
  ↓
更新任务状态为 running
  ↓
写入 task_started 事件
  ↓
执行 AI 任务
  ↓
每一步输出都写入 task_event
  ↓
任务完成后写入 result
  ↓
更新任务状态为 completed
```

---

## 6.3 页面刷新恢复流程

```text
用户刷新页面
  ↓
前端从 URL 或 localStorage 获取 task_id
  ↓
调用 GET /api/tasks/{task_id}
  ↓
获取任务当前状态
  ↓
调用 GET /api/tasks/{task_id}/events?after_seq=0
  ↓
恢复历史输出
  ↓
如果任务仍在 running
  ↓
继续建立 SSE 连接
  ↓
继续接收后续事件
```

---

## 6.4 新开会话恢复流程

新开会话时，前端可以先请求当前运行中的任务：

```text
用户打开新会话页面
  ↓
前端调用 GET /api/tasks/running
  ↓
后端返回当前未完成任务
  ↓
前端展示“正在运行的任务”
  ↓
用户点击任务
  ↓
进入任务详情页
  ↓
重新订阅任务进度
```

第一版可以不做复杂会话绑定，只要能查到运行中的任务即可。

---

## 7. 任务状态设计

任务状态只保留第一版需要的几个：

```text
created      已创建
queued       等待执行
running      正在执行
completed    已完成
failed       执行失败
cancelling   正在取消
cancelled    已取消
```

状态流转：

```text
created
  ↓
queued
  ↓
running
  ↓
completed
```

异常流转：

```text
running
  ↓
failed
```

取消流转：

```text
running
  ↓
cancelling
  ↓
cancelled
```

---

## 8. 数据库设计

## 8.1 agent_task 表

用于保存任务主信息。

```sql
CREATE TABLE agent_task (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,

    task_id VARCHAR(64) NOT NULL UNIQUE,

    conversation_id VARCHAR(64) NULL,
    title VARCHAR(255) NULL,
    prompt TEXT NOT NULL,

    status VARCHAR(32) NOT NULL,

    result LONGTEXT NULL,
    error_message TEXT NULL,

    cancel_requested TINYINT DEFAULT 0,

    created_at DATETIME NOT NULL,
    updated_at DATETIME NOT NULL,
    started_at DATETIME NULL,
    finished_at DATETIME NULL,

    INDEX idx_task_id (task_id),
    INDEX idx_status (status),
    INDEX idx_conversation_id (conversation_id),
    INDEX idx_created_at (created_at)
);
```

说明：

| 字段               | 说明            |
| ---------------- | ------------- |
| task_id          | 任务唯一 ID       |
| conversation_id  | 会话 ID，第一版可以为空 |
| title            | 任务标题          |
| prompt           | 用户原始问题        |
| status           | 任务状态          |
| result           | 最终结果          |
| error_message    | 错误信息          |
| cancel_requested | 是否请求取消        |
| created_at       | 创建时间          |
| started_at       | 开始执行时间        |
| finished_at      | 结束时间          |

---

## 8.2 agent_task_event 表

用于保存任务过程事件。

```sql
CREATE TABLE agent_task_event (
    id BIGINT PRIMARY KEY AUTO_INCREMENT,

    task_id VARCHAR(64) NOT NULL,
    seq BIGINT NOT NULL,

    event_type VARCHAR(64) NOT NULL,
    content LONGTEXT NULL,
    metadata_json JSON NULL,

    created_at DATETIME NOT NULL,

    UNIQUE KEY uk_task_seq (task_id, seq),
    INDEX idx_task_id (task_id),
    INDEX idx_created_at (created_at)
);
```

说明：

| 字段            | 说明         |
| ------------- | ---------- |
| task_id       | 对应任务 ID    |
| seq           | 当前任务内的事件序号 |
| event_type    | 事件类型       |
| content       | 事件内容       |
| metadata_json | 扩展字段       |
| created_at    | 事件创建时间     |

`seq` 非常重要，用于刷新页面和 SSE 断线重连。

---

## 9. 事件类型设计

第一版事件类型不需要太复杂，建议保留这些：

| event_type      | 说明      |
| --------------- | ------- |
| task_created    | 任务已创建   |
| task_queued     | 任务已进入队列 |
| task_started    | 任务开始执行  |
| agent_message   | AI 输出内容 |
| agent_step      | AI 执行步骤 |
| tool_call       | 工具调用    |
| command_output  | 命令输出    |
| task_completed  | 任务完成    |
| task_failed     | 任务失败    |
| task_cancelling | 正在取消    |
| task_cancelled  | 任务已取消   |

事件示例：

```json
{
  "seq": 5,
  "event_type": "agent_step",
  "content": "正在分析项目目录结构...",
  "metadata": {},
  "created_at": "2026-07-05 10:00:00"
}
```

---

## 10. 后端接口设计

## 10.1 创建任务

```text
POST /api/tasks
```

请求：

```json
{
  "conversation_id": "conv_001",
  "prompt": "帮我分析这个项目的业务流程"
}
```

响应：

```json
{
  "task_id": "task_abc123",
  "status": "queued"
}
```

处理逻辑：

```text
1. 生成 task_id
2. 写入 agent_task
3. 写入 task_created 事件
4. 投递到后台队列
5. 更新状态为 queued
6. 返回 task_id
```

---

## 10.2 查询任务详情

```text
GET /api/tasks/{task_id}
```

响应：

```json
{
  "task_id": "task_abc123",
  "conversation_id": "conv_001",
  "prompt": "帮我分析这个项目的业务流程",
  "status": "running",
  "result": null,
  "error_message": null,
  "created_at": "2026-07-05 10:00:00",
  "started_at": "2026-07-05 10:00:01",
  "finished_at": null
}
```

---

## 10.3 查询任务事件

```text
GET /api/tasks/{task_id}/events?after_seq=0
```

响应：

```json
{
  "items": [
    {
      "seq": 1,
      "event_type": "task_created",
      "content": "任务已创建",
      "metadata": {},
      "created_at": "2026-07-05 10:00:00"
    },
    {
      "seq": 2,
      "event_type": "task_started",
      "content": "任务开始执行",
      "metadata": {},
      "created_at": "2026-07-05 10:00:01"
    }
  ]
}
```

规则：

```text
只返回 seq > after_seq 的事件
按照 seq 升序返回
前端根据 seq 去重
```

---

## 10.4 SSE 订阅任务事件

```text
GET /api/tasks/{task_id}/stream?after_seq=0
```

返回格式：

```text
event: task_event
data: {"seq":1,"event_type":"task_created","content":"任务已创建"}

event: task_event
data: {"seq":2,"event_type":"task_started","content":"任务开始执行"}

event: task_event
data: {"seq":3,"event_type":"agent_message","content":"我正在分析项目结构..."}
```

规则：

```text
1. SSE 只负责推送事件，不负责执行任务
2. SSE 断开不取消任务
3. 前端重连时带上 last_seq
4. 后端先补发历史事件，再继续推送新事件
5. 任务 completed / failed / cancelled 后可以关闭 SSE
```

---

## 10.5 查询运行中任务

```text
GET /api/tasks/running
```

响应：

```json
{
  "items": [
    {
      "task_id": "task_abc123",
      "conversation_id": "conv_001",
      "title": "分析项目业务流程",
      "status": "running",
      "created_at": "2026-07-05 10:00:00",
      "updated_at": "2026-07-05 10:01:00"
    }
  ]
}
```

用途：

```text
新开会话
  ↓
查询是否有运行中任务
  ↓
展示任务入口
```

---

## 10.6 取消任务

```text
POST /api/tasks/{task_id}/cancel
```

响应：

```json
{
  "task_id": "task_abc123",
  "status": "cancelling"
}
```

处理逻辑：

```text
1. 设置 cancel_requested = 1
2. 更新状态为 cancelling
3. 写入 task_cancelling 事件
4. Worker 检测到取消标记后停止执行
5. 更新状态为 cancelled
6. 写入 task_cancelled 事件
```

---

## 11. 前端实现需求

## 11.1 创建任务后保存 task_id

用户提交问题后：

```text
POST /api/tasks
  ↓
拿到 task_id
  ↓
保存到当前页面状态
  ↓
保存到 localStorage
  ↓
URL 中最好带上 task_id
```

推荐 URL：

```text
/chat?task_id=task_abc123
```

或者：

```text
/tasks/task_abc123
```

---

## 11.2 页面刷新恢复

页面初始化时：

```text
1. 从 URL 获取 task_id
2. 如果 URL 没有，从 localStorage 获取最近运行中的 task_id
3. 调用 GET /api/tasks/{task_id}
4. 调用 GET /api/tasks/{task_id}/events?after_seq=0
5. 渲染历史事件
6. 如果任务状态是 running / queued / cancelling，建立 SSE
```

---

## 11.3 新开会话恢复

新开会话页面加载时：

```text
1. 调用 GET /api/tasks/running
2. 如果存在运行中任务，展示提示
3. 用户点击后进入任务详情
4. 加载历史事件
5. 建立 SSE 继续订阅
```

提示文案：

```text
有任务正在后台运行，点击查看进度
```

---

## 11.4 SSE 重连机制

前端需要维护：

```text
last_seq
connection_status
reconnect_count
```

每收到一个事件：

```text
1. 判断 seq 是否大于 last_seq
2. 如果大于，则渲染事件
3. 更新 last_seq
4. 如果小于等于 last_seq，则丢弃，避免重复展示
```

SSE 断开后：

```text
1 秒后重连
3 秒后重连
5 秒后重连
10 秒后重连
```

重连地址：

```text
/api/tasks/{task_id}/stream?after_seq={last_seq}
```

---

## 11.5 停止任务按钮

以下状态展示停止按钮：

```text
queued
running
```

点击后：

```text
1. 调用 POST /api/tasks/{task_id}/cancel
2. 按钮变灰
3. 文案显示“正在停止...”
4. 等待 SSE 返回 task_cancelled
5. 状态显示“已停止”
```

---

## 12. Worker 实现需求

## 12.1 Worker 职责

Worker 负责后台执行任务：

```text
1. 从队列拿到 task_id
2. 查询 agent_task
3. 更新状态为 running
4. 写入 task_started 事件
5. 执行 AI 任务
6. 持续写入 task_event
7. 完成后更新 result
8. 更新状态为 completed
9. 异常时更新 failed
10. 检查 cancel_requested
```

---

## 12.2 Worker 执行伪代码

```python
def run_task(task_id):
    task = get_task(task_id)

    if task.status in ["completed", "failed", "cancelled"]:
        return

    update_task_status(task_id, "running")
    append_event(task_id, "task_started", "任务开始执行")

    try:
        for step in agent_run(task.prompt):
            if is_cancel_requested(task_id):
                update_task_status(task_id, "cancelled")
                append_event(task_id, "task_cancelled", "任务已取消")
                return

            append_event(
                task_id=task_id,
                event_type=step.event_type,
                content=step.content,
                metadata=step.metadata
            )

        update_task_result(task_id, final_result)
        update_task_status(task_id, "completed")
        append_event(task_id, "task_completed", "任务执行完成")

    except Exception as e:
        update_task_status(task_id, "failed")
        update_task_error(task_id, str(e))
        append_event(task_id, "task_failed", str(e))
```

---

## 13. 队列实现建议

第一版可以用简单方案，不需要太重。

推荐优先级：

```text
方案一：Redis List / Redis Stream + 自定义 Worker
方案二：Celery + Redis
方案三：数据库轮询任务表
```

如果只是快速打通，可以先用数据库轮询：

```text
Worker 每隔 1 秒扫描 status = queued 的任务
  ↓
取出任务
  ↓
改为 running
  ↓
执行任务
```

数据库轮询版本最简单，缺点是性能一般，但第一版足够。

后续再升级为：

```text
Redis Queue / Celery / Dramatiq
```

---

## 14. 推荐第一版最小实现

第一版最小链路：

```text
agent_task 表
agent_task_event 表

POST /api/tasks
GET /api/tasks/{task_id}
GET /api/tasks/{task_id}/events
GET /api/tasks/{task_id}/stream
GET /api/tasks/running
POST /api/tasks/{task_id}/cancel

后台 Worker
前端 SSE 重连
页面刷新恢复
```

---

## 15. 关键实现点

## 15.1 不要把任务绑定到 HTTP 请求

不要这样：

```python
@app.post("/chat")
async def chat():
    result = await agent.run(prompt)
    return result
```

要这样：

```python
@app.post("/tasks")
async def create_task():
    task_id = create_task_record(prompt)
    enqueue_task(task_id)
    return {"task_id": task_id}
```

---

## 15.2 SSE 断开时不要取消任务

不要这样：

```python
if client_disconnected:
    cancel_task(task_id)
```

要这样：

```python
if client_disconnected:
    close_stream_only()
```

任务是否取消只看：

```text
cancel_requested
```

---

## 15.3 事件必须先写库，再推送

不要只推送到前端：

```text
Worker -> SSE -> 前端
```

要先落库：

```text
Worker -> agent_task_event -> SSE -> 前端
```

这样页面刷新后才能恢复。

---

## 15.4 last_seq 是恢复关键

每条事件都必须有递增序号：

```json
{
  "seq": 12,
  "event_type": "agent_message",
  "content": "正在分析依赖关系..."
}
```

前端刷新后请求：

```text
GET /api/tasks/{task_id}/events?after_seq=12
```

这样就不会重复，也不会丢失。

---

## 16. 验收标准

## 16.1 刷新页面不中断

测试步骤：

```text
1. 创建一个执行时间超过 60 秒的任务
2. 任务 running 后刷新页面
3. 页面重新加载
4. 页面展示之前的执行记录
5. 任务继续执行
6. 最终正常完成
```

通过标准：

```text
任务没有变成 failed
任务没有被取消
历史事件可以恢复
新事件可以继续接收
```

---

## 16.2 关闭页面不中断

测试步骤：

```text
1. 创建任务
2. 关闭浏览器页面
3. 等待一段时间
4. 重新打开系统
5. 进入运行中任务
6. 查看任务结果
```

通过标准：

```text
任务后台继续执行
重新打开后可以看到完整过程和结果
```

---

## 16.3 新开会话可恢复

测试步骤：

```text
1. 创建任务
2. 新开一个会话页面
3. 页面请求 GET /api/tasks/running
4. 展示正在运行任务
5. 点击任务进入详情
6. 继续接收任务进度
```

通过标准：

```text
新页面可以看到同一个任务
任务没有被重新创建
任务没有中断
事件不重复、不丢失
```

---

## 16.4 SSE 断线重连

测试步骤：

```text
1. 创建任务
2. 中途断开网络
3. 恢复网络
4. 前端自动重连
5. 使用 last_seq 继续接收事件
```

通过标准：

```text
不会重复展示大量旧消息
不会丢失中间事件
任务继续执行
```

---

## 16.5 用户主动停止任务

测试步骤：

```text
1. 创建任务
2. 任务 running 后点击停止
3. 后端状态变为 cancelling
4. Worker 停止执行
5. 最终状态变为 cancelled
```

通过标准：

```text
只有点击停止才取消任务
刷新页面不会取消任务
关闭页面不会取消任务
```

---

## 17. MVP 开发顺序

建议按这个顺序开发：

```text
第一步：建表 agent_task、agent_task_event

第二步：实现 POST /api/tasks

第三步：实现简单 Worker，可以先数据库轮询 queued 任务

第四步：Worker 执行过程中持续写入 task_event

第五步：实现 GET /api/tasks/{task_id}

第六步：实现 GET /api/tasks/{task_id}/events

第七步：实现 SSE /api/tasks/{task_id}/stream

第八步：前端支持刷新后根据 task_id 恢复

第九步：实现 GET /api/tasks/running

第十步：实现取消任务
```

---

## 18. 最终效果

完成后，系统应该支持：

```text
用户提交任务后：
  - 刷新页面，任务不中断
  - 关闭页面，任务不中断
  - 新开会话，可以看到运行中任务
  - 重新进入任务，可以恢复历史过程
  - SSE 断线后可以重连
  - 只有主动点击停止，任务才会取消
```

第一版的核心不是复杂 Agent 能力，而是先把任务生命周期从页面连接中解耦出来。

核心架构可以总结为：

```text
任务持久化
  +
后台 Worker
  +
事件日志
  +
SSE 订阅
  +
last_seq 重连恢复
```

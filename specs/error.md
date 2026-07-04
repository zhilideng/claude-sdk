# Codex App AI 异常提示与耗时反馈功能开发文档

## 1. 功能背景

Codex App 在 AI 回复、代码生成、项目分析、Agent 执行等场景中，可能出现以下问题：

* AI 推理失败
* 连接失败
* API Key 调用失败
* 请求超时
* 响应耗时过长
* 服务繁忙
* 网络中断
* 用户主动取消
* 工具调用失败
* 已生成部分内容后异常中断

目前如果只展示“请求失败”或“生成失败”，用户无法判断失败原因，也无法把有效信息反馈给开发者排查。因此需要设计一套统一的异常提示与耗时反馈机制。

---

## 2. 功能目标

本功能目标是为 Codex App 提供一套统一的 AI 请求状态展示能力。

需要实现：

1. AI 请求全流程状态展示
2. 异常类型识别与分类提示
3. 长耗时任务提示
4. 请求耗时展示
5. 首包耗时记录
6. 推理失败提示
7. 连接失败提示
8. API Key 失败提示
9. 请求超时提示
10. 用户取消状态提示
11. 部分内容生成后的异常保留
12. 一键复制错误信息
13. 一键复制诊断详情
14. 统一错误码与前后端字段映射
15. 为后续日志排查和埋点预留字段

---

## 3. 适用场景

本功能适用于 Codex App 中所有 AI 调用场景。

包括：

* Chat AI 回复
* 代码生成
* 代码解释
* 代码修改
* 项目结构分析
* 文件总结
* Agent 多步任务
* 工具调用任务
* 命令执行建议
* 长文本处理
* 多轮流式输出

---

## 4. 核心设计原则

### 4.1 用户侧原则

用户看到的提示应该简单、明确、可操作。

不要直接展示复杂技术错误，例如：

```text
Upstream provider response error.
```

应该转换为：

```text
AI 服务暂时不可用，请稍后重试。
```

---

### 4.2 开发侧原则

开发者复制到的诊断信息必须足够完整。

需要包含：

* request_id
* trace_id
* model
* provider
* error_code
* error_type
* stage
* duration_ms
* first_token_latency_ms
* retryable
* created_at

---

### 4.3 交互侧原则

不同异常需要有不同操作入口。

例如：

* 连接失败：重试连接
* API Key 失败：去配置
* 推理失败：重新生成
* 超时失败：重新生成 / 缩短输入
* 网络中断：复制已生成内容 / 继续生成
* 用户取消：重新生成

---

## 5. 请求生命周期状态机

### 5.1 状态定义

```ts
type AiRequestStatus =
  | 'idle'
  | 'preparing'
  | 'connecting'
  | 'queued'
  | 'reasoning'
  | 'streaming'
  | 'tool_calling'
  | 'slow'
  | 'success'
  | 'failed'
  | 'timeout'
  | 'cancelled';
```

### 5.2 状态说明

| 状态           | 说明          | 是否展示给用户 |
| ------------ | ----------- | ------- |
| idle         | 空闲状态        | 否       |
| preparing    | 请求准备中       | 可选      |
| connecting   | 建立连接中       | 是       |
| queued       | 排队中         | 是       |
| reasoning    | 模型推理中       | 是       |
| streaming    | 流式输出中       | 是       |
| tool_calling | Agent 工具调用中 | 是       |
| slow         | 耗时较长        | 是       |
| success      | 请求成功        | 否       |
| failed       | 请求失败        | 是       |
| timeout      | 请求超时        | 是       |
| cancelled    | 用户取消        | 是       |

---

## 6. 状态流转规则

### 6.1 正常流转

```text
idle
  ↓
preparing
  ↓
connecting
  ↓
reasoning
  ↓
streaming
  ↓
success
```

### 6.2 Agent 任务流转

```text
idle
  ↓
preparing
  ↓
connecting
  ↓
reasoning
  ↓
tool_calling
  ↓
reasoning
  ↓
streaming
  ↓
success
```

### 6.3 异常流转

```text
connecting → failed
reasoning → failed
reasoning → timeout
streaming → failed
streaming → timeout
tool_calling → failed
reasoning → cancelled
streaming → cancelled
tool_calling → cancelled
```

### 6.4 长耗时流转

```text
reasoning → slow
streaming → slow
tool_calling → slow
queued → slow
```

注意：

`slow` 不代表失败，只代表当前任务耗时较长。

---

## 7. 异常类型设计

### 7.1 错误类型枚举

```ts
type AiErrorType =
  | 'connection_failed'
  | 'network_interrupted'
  | 'api_key_missing'
  | 'api_key_invalid'
  | 'api_key_quota_exceeded'
  | 'model_not_found'
  | 'model_inference_failed'
  | 'model_timeout'
  | 'model_busy'
  | 'context_too_long'
  | 'tool_call_failed'
  | 'user_cancelled'
  | 'unknown_error';
```

---

## 8. 错误码设计

```ts
type AiErrorCode =
  | 'CONNECTION_FAILED'
  | 'NETWORK_INTERRUPTED'
  | 'API_KEY_MISSING'
  | 'API_KEY_INVALID'
  | 'API_KEY_QUOTA_EXCEEDED'
  | 'MODEL_NOT_FOUND'
  | 'MODEL_INFERENCE_FAILED'
  | 'MODEL_TIMEOUT'
  | 'MODEL_BUSY'
  | 'CONTEXT_TOO_LONG'
  | 'TOOL_CALL_FAILED'
  | 'USER_CANCELLED'
  | 'UNKNOWN_ERROR';
```

---

## 9. 错误码与提示文案映射

### 9.1 连接失败

```ts
{
  errorCode: 'CONNECTION_FAILED',
  title: '连接失败',
  message: '无法连接到 AI 服务，请检查网络或稍后重试。',
  detail: '当前请求未能成功建立连接，可能是网络异常、服务不可用或连接被中断。',
  primaryAction: 'retry_connection'
}
```

---

### 9.2 网络中断

```ts
{
  errorCode: 'NETWORK_INTERRUPTED',
  title: '网络连接中断',
  message: '当前 AI 响应被中断，请检查网络后重试。',
  detail: '请求执行过程中连接被断开，可能导致回复内容不完整。',
  primaryAction: 'retry'
}
```

---

### 9.3 API Key 缺失

```ts
{
  errorCode: 'API_KEY_MISSING',
  title: 'API Key 未配置',
  message: '当前模型服务缺少 API Key，请先完成配置。',
  detail: '系统未检测到可用的 API Key，无法发起模型调用。',
  primaryAction: 'open_settings'
}
```

---

### 9.4 API Key 无效

```ts
{
  errorCode: 'API_KEY_INVALID',
  title: 'API Key 调用失败',
  message: '当前密钥不可用，请检查配置后重试。',
  detail: 'AI 服务鉴权失败，可能是 API Key 无效、过期或没有当前模型的调用权限。',
  primaryAction: 'open_settings'
}
```

---

### 9.5 API Key 额度不足

```ts
{
  errorCode: 'API_KEY_QUOTA_EXCEEDED',
  title: 'API Key 额度不足',
  message: '当前密钥额度不足，请更换密钥或稍后重试。',
  detail: '模型服务返回额度不足，当前请求无法继续完成。',
  primaryAction: 'open_settings'
}
```

---

### 9.6 模型不存在

```ts
{
  errorCode: 'MODEL_NOT_FOUND',
  title: '模型不可用',
  message: '当前模型不存在或暂不可用，请切换模型后重试。',
  detail: '模型服务未找到当前配置的模型，可能是模型名称错误、权限不足或 Provider 配置不正确。',
  primaryAction: 'switch_model'
}
```

---

### 9.7 推理失败

```ts
{
  errorCode: 'MODEL_INFERENCE_FAILED',
  title: 'AI 推理失败',
  message: '模型在生成结果时遇到问题，请稍后重试。',
  detail: '请求已成功连接到模型服务，但模型在推理过程中发生异常。',
  primaryAction: 'retry'
}
```

---

### 9.8 请求超时

```ts
{
  errorCode: 'MODEL_TIMEOUT',
  title: '请求超时',
  message: 'AI 服务响应时间过长，本次请求已停止。',
  detail: '当前请求等待时间超过系统限制，可能是模型服务繁忙、网络不稳定或输入内容过长。',
  primaryAction: 'retry'
}
```

---

### 9.9 服务繁忙

```ts
{
  errorCode: 'MODEL_BUSY',
  title: 'AI 服务繁忙',
  message: '当前请求排队时间较长，请稍后重试。',
  detail: '当前模型服务负载较高，任务可能需要更长时间才能完成。',
  primaryAction: 'retry_later'
}
```

---

### 9.10 上下文过长

```ts
{
  errorCode: 'CONTEXT_TOO_LONG',
  title: '输入内容过长',
  message: '当前内容超过模型可处理范围，请减少输入内容后重试。',
  detail: '请求上下文长度超过当前模型限制，建议减少输入内容、清理历史上下文或切换更大上下文模型。',
  primaryAction: 'shorten_input'
}
```

---

### 9.11 工具调用失败

```ts
{
  errorCode: 'TOOL_CALL_FAILED',
  title: '工具调用失败',
  message: 'AI 在执行工具时遇到问题，任务已中断。',
  detail: 'Agent 执行工具调用过程中发生异常，可能是工具参数错误、权限不足或工具服务不可用。',
  primaryAction: 'retry'
}
```

---

### 9.12 用户取消

```ts
{
  errorCode: 'USER_CANCELLED',
  title: '任务已取消',
  message: '你已停止本次 AI 生成。',
  detail: '本次任务由用户主动取消，未继续生成后续内容。',
  primaryAction: 'regenerate'
}
```

---

### 9.13 未知错误

```ts
{
  errorCode: 'UNKNOWN_ERROR',
  title: '请求失败',
  message: 'AI 服务出现未知异常，请稍后重试。',
  detail: '当前错误未能被系统识别，请复制诊断信息反馈给开发者。',
  primaryAction: 'retry'
}
```

---

## 10. 耗时提示规则

### 10.1 耗时阶段

每次 AI 请求需要记录以下时间点：

```ts
interface AiRequestTiming {
  requestStartAt: number;
  connectionStartAt?: number;
  connectionEndAt?: number;
  firstTokenAt?: number;
  requestEndAt?: number;
}
```

需要计算：

```ts
interface AiDurationMetrics {
  durationMs: number;
  connectionDurationMs?: number;
  firstTokenLatencyMs?: number;
  reasoningDurationMs?: number;
}
```

---

### 10.2 耗时等级

|        耗时 | 状态   | 前端展示                 |
| --------: | ---- | -------------------- |
|   0 - 3 秒 | 正常   | 不额外提示                |
|  3 - 10 秒 | 等待中  | AI 正在思考...           |
| 10 - 30 秒 | 较慢   | 处理时间较长，请稍候...        |
| 30 - 60 秒 | 明显较慢 | 展示当前阶段与已耗时           |
|    60 秒以上 | 异常耗时 | 展示继续等待 / 停止生成 / 查看详情 |
|   超过总超时阈值 | 超时失败 | 展示请求超时               |

---

### 10.3 不同任务推荐阈值

```ts
const AI_TIMEOUT_CONFIG = {
  chat: {
    slowHintMs: 10000,
    longSlowHintMs: 30000,
    timeoutMs: 60000
  },
  codeGeneration: {
    slowHintMs: 15000,
    longSlowHintMs: 30000,
    timeoutMs: 120000
  },
  projectAnalysis: {
    slowHintMs: 30000,
    longSlowHintMs: 60000,
    timeoutMs: 300000
  },
  agentTask: {
    slowHintMs: 30000,
    longSlowHintMs: 60000,
    timeoutMs: 600000
  },
  fileParse: {
    slowHintMs: 20000,
    longSlowHintMs: 30000,
    timeoutMs: 180000
  }
};
```

---

## 11. 前端数据结构

### 11.1 AI 请求状态对象

```ts
interface AiRequestState {
  status: AiRequestStatus;
  stage: AiRequestStage;
  error?: AiRequestError;
  timing: AiRequestTiming;
  metrics?: AiDurationMetrics;
  partialContent?: string;
  generatedPartial: boolean;
  retryable: boolean;
}
```

---

### 11.2 请求阶段枚举

```ts
type AiRequestStage =
  | 'preparing'
  | 'connecting'
  | 'queued'
  | 'reasoning'
  | 'streaming'
  | 'tool_calling'
  | 'saving'
  | 'done';
```

---

### 11.3 错误对象

```ts
interface AiRequestError {
  errorCode: AiErrorCode;
  errorType: AiErrorType;
  title: string;
  message: string;
  detail?: string;
  stage?: AiRequestStage;
  requestId?: string;
  traceId?: string;
  model?: string;
  provider?: string;
  durationMs?: number;
  firstTokenLatencyMs?: number;
  retryable: boolean;
  rawError?: unknown;
}
```

---

## 12. 后端响应结构

### 12.1 普通异常响应

```json
{
  "success": false,
  "error_code": "MODEL_INFERENCE_FAILED",
  "error_type": "model_inference_failed",
  "message": "模型在生成结果时遇到问题",
  "detail": "模型推理过程中发生异常",
  "stage": "reasoning",
  "request_id": "req_xxxxx",
  "trace_id": "trace_xxxxx",
  "model": "gpt-xxx",
  "provider": "openai",
  "duration_ms": 42800,
  "first_token_latency_ms": 15600,
  "generated_partial": true,
  "partial_content": "已经生成的部分内容",
  "retryable": true,
  "suggested_action": "retry"
}
```

---

### 12.2 流式响应异常事件

SSE / WebSocket 流式响应中，建议统一增加 error event。

```json
{
  "event": "error",
  "data": {
    "error_code": "NETWORK_INTERRUPTED",
    "error_type": "network_interrupted",
    "message": "网络连接中断",
    "detail": "请求执行过程中连接被断开",
    "stage": "streaming",
    "request_id": "req_xxxxx",
    "trace_id": "trace_xxxxx",
    "duration_ms": 32000,
    "generated_partial": true,
    "retryable": true
  }
}
```

---

### 12.3 流式响应阶段事件

建议后端在关键阶段返回 stage event。

```json
{
  "event": "stage",
  "data": {
    "stage": "reasoning",
    "message": "AI 正在推理..."
  }
}
```

```json
{
  "event": "stage",
  "data": {
    "stage": "tool_calling",
    "message": "AI 正在调用工具..."
  }
}
```

---

## 13. 前端组件设计

### 13.1 组件拆分

建议拆分为以下组件：

```text
AiResponseContainer
  ├── AiLoadingIndicator
  ├── AiSlowHint
  ├── AiErrorCard
  ├── AiErrorDetailPanel
  ├── AiRetryButton
  ├── AiCopyErrorButton
  ├── AiCopyDiagnosticButton
  └── AiPartialContentNotice
```

---

### 13.2 AiLoadingIndicator

用于展示正常等待状态。

展示内容：

```text
AI 正在思考...
```

或：

```text
AI 正在分析项目结构...
已耗时 18 秒
```

Props：

```ts
interface AiLoadingIndicatorProps {
  stage: AiRequestStage;
  durationMs: number;
  canCancel: boolean;
  onCancel?: () => void;
}
```

---

### 13.3 AiSlowHint

用于展示长耗时状态。

展示内容：

```text
AI 正在处理中，耗时较长
当前任务仍在执行，已耗时 46 秒。
```

Props：

```ts
interface AiSlowHintProps {
  stage: AiRequestStage;
  durationMs: number;
  onContinue?: () => void;
  onCancel?: () => void;
  onViewDetail?: () => void;
}
```

---

### 13.4 AiErrorCard

用于展示异常卡片。

Props：

```ts
interface AiErrorCardProps {
  error: AiRequestError;
  generatedPartial?: boolean;
  partialContent?: string;
  onRetry?: () => void;
  onRetryConnection?: () => void;
  onSwitchModel?: () => void;
  onOpenSettings?: () => void;
  onCopyError?: () => void;
  onCopyDiagnostic?: () => void;
  onViewDetail?: () => void;
}
```

---

### 13.5 AiErrorDetailPanel

用于展示错误详情。

Props：

```ts
interface AiErrorDetailPanelProps {
  error: AiRequestError;
  metrics?: AiDurationMetrics;
  requestContext?: AiRequestContext;
}
```

---

## 14. 复制功能设计

### 14.1 复制错误信息

所有异常都必须支持复制错误信息。

复制内容格式：

```text
错误类型：AI 推理失败
错误说明：模型在生成结果时遇到问题
请求阶段：模型推理
已耗时：42.8 秒
错误码：MODEL_INFERENCE_FAILED
Request ID：req_xxxxx
Trace ID：trace_xxxxx
模型：gpt-xxx
服务商：openai
时间：2026-07-04 10:30:21
```

---

### 14.2 复制诊断详情

复制内容格式：

```text
【Codex App AI 异常诊断信息】

错误信息：
- 错误类型：AI 推理失败
- 错误码：MODEL_INFERENCE_FAILED
- 错误说明：模型在生成结果时遇到问题
- 错误详情：模型推理过程中发生异常

请求信息：
- Request ID：req_xxxxx
- Trace ID：trace_xxxxx
- Model：gpt-xxx
- Provider：openai
- Stage：reasoning
- Stream：true

耗时信息：
- 总耗时：42.8 秒
- 首包耗时：15.6 秒
- 建立连接耗时：0.8 秒

生成信息：
- 是否已生成部分内容：是
- 已生成字符数：1280

客户端信息：
- App Version：x.x.x
- Platform：macOS
- Time：2026-07-04 10:30:21
```

---

### 14.3 复制已生成内容

当 `generatedPartial = true` 时，需要展示：

```text
复制已生成内容
```

适用场景：

* 流式输出中断
* 网络中断
* 用户取消
* 推理中途失败

---

## 15. 操作按钮规则

### 15.1 按钮枚举

```ts
type AiErrorAction =
  | 'retry'
  | 'retry_connection'
  | 'switch_model'
  | 'open_settings'
  | 'shorten_input'
  | 'cancel'
  | 'copy_error'
  | 'copy_diagnostic'
  | 'copy_partial_content'
  | 'view_detail';
```

---

### 15.2 按钮展示规则

| 错误码                    | 主按钮  | 次按钮              |
| ---------------------- | ---- | ---------------- |
| CONNECTION_FAILED      | 重试连接 | 复制错误信息 / 查看详情    |
| NETWORK_INTERRUPTED    | 重试   | 复制已生成内容 / 复制错误信息 |
| API_KEY_MISSING        | 去配置  | 复制错误信息 / 查看详情    |
| API_KEY_INVALID        | 去配置  | 切换模型 / 复制错误信息    |
| API_KEY_QUOTA_EXCEEDED | 去配置  | 切换模型 / 复制错误信息    |
| MODEL_NOT_FOUND        | 切换模型 | 复制错误信息 / 查看详情    |
| MODEL_INFERENCE_FAILED | 重新生成 | 切换模型 / 复制错误信息    |
| MODEL_TIMEOUT          | 重新生成 | 缩短输入 / 查看详情      |
| MODEL_BUSY             | 稍后重试 | 切换模型 / 复制错误信息    |
| CONTEXT_TOO_LONG       | 缩短输入 | 切换模型 / 复制错误信息    |
| TOOL_CALL_FAILED       | 重新执行 | 复制错误信息 / 查看详情    |
| USER_CANCELLED         | 重新生成 | 复制已生成内容          |
| UNKNOWN_ERROR          | 重新生成 | 复制错误信息 / 查看详情    |

---

## 16. 异常优先级

如果多个异常同时出现，前端按以下优先级展示：

```text
USER_CANCELLED
  >
API_KEY_MISSING / API_KEY_INVALID / API_KEY_QUOTA_EXCEEDED
  >
CONNECTION_FAILED
  >
NETWORK_INTERRUPTED
  >
MODEL_TIMEOUT
  >
CONTEXT_TOO_LONG
  >
MODEL_NOT_FOUND
  >
MODEL_INFERENCE_FAILED
  >
TOOL_CALL_FAILED
  >
MODEL_BUSY
  >
UNKNOWN_ERROR
```

说明：

* 用户主动取消不应被展示为错误
* API Key 问题必须优先提示配置
* 连接失败优先于推理失败
* 超时失败优先于普通推理失败
* 未知错误只作为兜底

---

## 17. 自动重试策略

### 17.1 可自动重试的错误

```ts
const AUTO_RETRY_ERROR_CODES = [
  'CONNECTION_FAILED',
  'NETWORK_INTERRUPTED',
  'MODEL_BUSY'
];
```

---

### 17.2 不可自动重试的错误

```ts
const NON_AUTO_RETRY_ERROR_CODES = [
  'API_KEY_MISSING',
  'API_KEY_INVALID',
  'API_KEY_QUOTA_EXCEEDED',
  'MODEL_NOT_FOUND',
  'CONTEXT_TOO_LONG',
  'USER_CANCELLED'
];
```

---

### 17.3 重试次数

```ts
const MAX_AUTO_RETRY_COUNT = 2;
```

提示文案：

```text
连接不稳定，正在自动重试...
第 1/2 次
```

自动重试失败后：

```text
多次重试后仍然失败，请检查网络或稍后再试。
```

---

## 18. 关键交互细节

### 18.1 长耗时不等于失败

当请求超过 30 秒但连接仍然存在时，不要直接展示失败。

应该展示：

```text
AI 正在处理中，耗时较长
当前任务仍在执行，已耗时 32 秒。
```

---

### 18.2 流式中断需要保留已生成内容

如果已经有部分内容生成，连接中断后不要清空内容。

应该展示：

```text
连接中断，以下内容可能不完整。
```

按钮：

```text
继续生成
重新生成
复制已生成内容
复制错误信息
```

---

### 18.3 用户取消不使用红色错误样式

用户点击“停止生成”后，展示中性状态。

```text
任务已取消
你已停止本次 AI 生成。
```

---

### 18.4 API Key 异常优先引导配置

API Key 异常不要只展示“请求失败”。

应该展示：

```text
API Key 调用失败
当前密钥不可用，请检查配置后重试。
```

按钮优先级：

```text
去配置 > 切换模型 > 复制错误信息 > 查看详情
```

---

## 19. 日志字段设计

前端和后端都建议记录以下字段。

```ts
interface AiRequestLog {
  requestId: string;
  traceId?: string;
  sessionId?: string;
  conversationId?: string;
  model?: string;
  provider?: string;
  status: AiRequestStatus;
  stage: AiRequestStage;
  errorCode?: AiErrorCode;
  errorType?: AiErrorType;
  errorMessage?: string;
  durationMs?: number;
  firstTokenLatencyMs?: number;
  retryCount?: number;
  generatedPartial?: boolean;
  partialContentLength?: number;
  createdAt: string;
}
```

---

## 20. 埋点事件设计

```ts
type AiTelemetryEvent =
  | 'ai_request_start'
  | 'ai_connection_start'
  | 'ai_connection_success'
  | 'ai_connection_failed'
  | 'ai_first_token_received'
  | 'ai_response_slow'
  | 'ai_request_timeout'
  | 'ai_inference_failed'
  | 'ai_api_key_failed'
  | 'ai_tool_call_failed'
  | 'ai_user_cancelled'
  | 'ai_retry_clicked'
  | 'ai_error_copied'
  | 'ai_diagnostic_copied'
  | 'ai_detail_opened';
```

---

## 21. 推荐目录结构

如果是前端项目，建议新增以下目录：

```text
src/
  features/
    ai-request-status/
      components/
        AiErrorCard.tsx
        AiErrorDetailPanel.tsx
        AiLoadingIndicator.tsx
        AiSlowHint.tsx
        AiPartialContentNotice.tsx
      hooks/
        useAiRequestState.ts
        useAiRequestTiming.ts
        useAiErrorCopy.ts
      constants/
        aiErrorCodes.ts
        aiErrorMessages.ts
        aiTimeoutConfig.ts
      types/
        aiRequestTypes.ts
      utils/
        formatDuration.ts
        normalizeAiError.ts
        buildDiagnosticText.ts
        resolveAiErrorActions.ts
```

---

## 22. 核心工具函数设计

### 22.1 normalizeAiError

用于把后端异常、网络异常、前端异常统一转换为 `AiRequestError`。

```ts
function normalizeAiError(error: unknown): AiRequestError {
  // TODO:
  // 1. 判断是否是后端标准错误
  // 2. 判断是否是网络错误
  // 3. 判断是否是超时错误
  // 4. 判断是否是用户取消
  // 5. 兜底为 UNKNOWN_ERROR
}
```

---

### 22.2 resolveAiErrorActions

用于根据错误码返回按钮列表。

```ts
function resolveAiErrorActions(errorCode: AiErrorCode): AiErrorAction[] {
  // TODO:
  // 根据错误码返回对应操作按钮
}
```

---

### 22.3 buildDiagnosticText

用于生成复制诊断详情文本。

```ts
function buildDiagnosticText(params: {
  error: AiRequestError;
  metrics?: AiDurationMetrics;
  context?: AiRequestContext;
}): string {
  // TODO:
  // 拼接完整诊断信息
}
```

---

### 22.4 formatDuration

用于格式化耗时。

```ts
function formatDuration(durationMs: number): string {
  if (durationMs < 1000) {
    return `${durationMs} ms`;
  }

  return `${(durationMs / 1000).toFixed(1)} 秒`;
}
```

---

## 23. 开发任务拆分

### 23.1 第一阶段：基础异常展示

需要完成：

* 定义错误码
* 定义错误类型
* 定义请求状态
* 实现 `AiErrorCard`
* 实现错误文案映射
* 实现重新生成按钮
* 实现复制错误信息按钮

验收标准：

* 推理失败可以展示明确提示
* 连接失败可以展示明确提示
* API Key 失败可以展示明确提示
* 所有异常都能复制错误信息

---

### 23.2 第二阶段：耗时提示

需要完成：

* 记录请求开始时间
* 记录连接开始和结束时间
* 记录首包时间
* 计算总耗时
* 实现 `AiLoadingIndicator`
* 实现 `AiSlowHint`
* 不同任务类型支持不同超时配置

验收标准：

* 10 秒无响应展示轻提示
* 30 秒无响应展示长耗时提示
* 超过超时阈值展示请求超时
* 能看到已耗时秒数

---

### 23.3 第三阶段：流式中断与部分内容保留

需要完成：

* 识别流式输出中断
* 保留已生成内容
* 展示部分内容不完整提示
* 支持复制已生成内容
* 支持重新生成

验收标准：

* 已生成内容不会因为异常被清空
* 用户可以复制部分内容
* 用户能看到“内容可能不完整”的提示

---

### 23.4 第四阶段：诊断详情

需要完成：

* 实现 `AiErrorDetailPanel`
* 实现 `buildDiagnosticText`
* 支持复制完整诊断详情
* 展示 request_id / trace_id / model / provider / stage / duration

验收标准：

* 用户可以展开查看详情
* 用户可以一键复制完整诊断信息
* 复制内容能用于开发者排查日志

---

### 23.5 第五阶段：自动重试

需要完成：

* 定义自动重试错误码
* 实现最多 2 次自动重试
* 展示当前重试次数
* 不可重试错误不触发自动重试

验收标准：

* 网络短暂异常可以自动重试
* API Key 错误不会自动重试
* 用户能看到自动重试次数

---

## 24. Codex 开发 Prompt 建议

后续可以直接让 Codex 按下面任务执行。

### 24.1 第一步 Prompt

```text
请根据本文档实现 Codex App 的 AI 异常提示基础能力。

优先完成：
1. 定义 AI 请求状态类型
2. 定义 AI 错误码类型
3. 定义 AI 错误文案映射
4. 实现 normalizeAiError
5. 实现 AiErrorCard 组件
6. 实现复制错误信息功能

要求：
- 不要修改现有 AI 请求主流程的业务逻辑
- 先以最小侵入方式接入
- 所有错误都必须兜底为 UNKNOWN_ERROR
- 所有异常卡片都必须支持复制错误信息
```

---

### 24.2 第二步 Prompt

```text
请继续实现 AI 请求耗时提示能力。

需要完成：
1. 记录 requestStartAt
2. 记录 connectionStartAt 和 connectionEndAt
3. 记录 firstTokenAt
4. 计算 durationMs 和 firstTokenLatencyMs
5. 超过 slowHintMs 展示轻提示
6. 超过 longSlowHintMs 展示长耗时提示
7. 超过 timeoutMs 展示请求超时

要求：
- 长耗时状态不能直接判定为失败
- 超时后需要停止当前请求
- 不同任务类型使用不同 timeout 配置
```

---

### 24.3 第三步 Prompt

```text
请继续实现流式输出中断后的部分内容保留能力。

需要完成：
1. 当 streaming 阶段发生异常时保留 partialContent
2. 展示“连接中断，以下内容可能不完整”
3. 支持复制已生成内容
4. 支持重新生成
5. 支持复制错误信息

要求：
- 不允许清空已经生成的内容
- 用户主动取消时不要展示为红色错误
- 网络中断和用户取消需要区分
```

---

### 24.4 第四步 Prompt

```text
请继续实现 AI 异常诊断详情能力。

需要完成：
1. 实现 AiErrorDetailPanel
2. 展示 request_id、trace_id、model、provider、stage、duration_ms、first_token_latency_ms
3. 实现 buildDiagnosticText
4. 支持一键复制完整诊断详情

要求：
- 诊断详情面向开发者排查
- 默认折叠
- 不影响普通用户阅读
```

---

## 25. 验收标准

### 25.1 功能验收

* 连接失败时展示“连接失败”
* API Key 缺失时展示“API Key 未配置”
* API Key 无效时展示“API Key 调用失败”
* 推理失败时展示“AI 推理失败”
* 请求超时时展示“请求超时”
* 长耗时时展示“AI 正在处理中，耗时较长”
* 用户取消时展示“任务已取消”
* 工具调用失败时展示“工具调用失败”
* 上下文过长时展示“输入内容过长”
* 未知异常时展示“请求失败”
* 所有异常支持复制错误信息
* 重要异常支持查看详情
* 流式中断时保留已生成内容

---

### 25.2 体验验收

* 用户能看懂发生了什么
* 用户知道下一步该点什么
* 用户不会被原始报错信息干扰
* 长耗时任务不会像页面卡死
* 用户取消不会被误判为系统错误
* 部分生成内容不会丢失

---

### 25.3 开发验收

* 错误码统一
* 错误文案统一
* 状态机统一
* 复制内容格式统一
* 超时时间可配置
* 自动重试次数可配置
* 所有未知异常有兜底
* 后续可以接入埋点和日志系统

---

## 26. 最终推荐交互流程

```text
用户发起 AI 请求
  ↓
进入 preparing
  ↓
进入 connecting
  ↓
连接成功
  ↓
进入 reasoning
  ↓
10 秒无首包
  ↓
展示“AI 正在思考...”
  ↓
30 秒无首包
  ↓
展示“AI 正在处理中，耗时较长”
  ↓
如果收到首包
  ↓
进入 streaming
  ↓
持续输出内容
  ↓
如果完成
  ↓
success
```

异常流程：

```text
连接失败
  ↓
展示连接失败卡片
  ↓
用户点击重试连接
```

```text
API Key 失败
  ↓
展示 API Key 调用失败卡片
  ↓
用户点击去配置
```

```text
推理失败
  ↓
展示 AI 推理失败卡片
  ↓
用户点击重新生成
```

```text
流式中断
  ↓
保留已生成内容
  ↓
展示内容可能不完整
  ↓
用户可复制已生成内容或重新生成
```

---

## 27. 总结

本功能不是单纯做一个错误弹窗，而是为 Codex App 建立一套完整的 AI 请求状态管理能力。

核心能力包括：

```text
状态可感知
异常可分类
耗时可展示
失败可恢复
信息可复制
问题可排查
```

最终目标：

```text
普通用户看得懂，开发人员查得快，后续功能接得住。
```

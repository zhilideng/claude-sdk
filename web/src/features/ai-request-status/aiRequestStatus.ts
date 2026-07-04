export type AiRequestStatus =
  | "idle"
  | "preparing"
  | "connecting"
  | "queued"
  | "reasoning"
  | "streaming"
  | "tool_calling"
  | "slow"
  | "success"
  | "failed"
  | "timeout"
  | "cancelled";

export type AiRequestStage =
  | "preparing"
  | "connecting"
  | "queued"
  | "reasoning"
  | "streaming"
  | "tool_calling"
  | "saving"
  | "done";

export type AiErrorType =
  | "connection_failed"
  | "network_interrupted"
  | "api_key_missing"
  | "api_key_invalid"
  | "api_key_quota_exceeded"
  | "model_not_found"
  | "model_inference_failed"
  | "model_timeout"
  | "model_busy"
  | "context_too_long"
  | "tool_call_failed"
  | "user_cancelled"
  | "unknown_error";

export type AiErrorCode =
  | "CONNECTION_FAILED"
  | "NETWORK_INTERRUPTED"
  | "API_KEY_MISSING"
  | "API_KEY_INVALID"
  | "API_KEY_QUOTA_EXCEEDED"
  | "MODEL_NOT_FOUND"
  | "MODEL_INFERENCE_FAILED"
  | "MODEL_TIMEOUT"
  | "MODEL_BUSY"
  | "CONTEXT_TOO_LONG"
  | "TOOL_CALL_FAILED"
  | "USER_CANCELLED"
  | "UNKNOWN_ERROR";

export type AiErrorAction =
  | "retry"
  | "retry_connection"
  | "switch_model"
  | "open_settings"
  | "shorten_input"
  | "cancel"
  | "copy_error"
  | "copy_diagnostic"
  | "copy_partial_content"
  | "view_detail";

export type AiRequestTiming = {
  requestStartAt: number;
  connectionStartAt?: number;
  connectionEndAt?: number;
  firstTokenAt?: number;
  requestEndAt?: number;
};

export type AiDurationMetrics = {
  durationMs: number;
  connectionDurationMs?: number;
  firstTokenLatencyMs?: number;
  reasoningDurationMs?: number;
};

export type AiRequestError = {
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
  createdAt: string;
};

export type AiRequestContext = {
  stage?: AiRequestStage;
  requestId?: string;
  traceId?: string;
  model?: string;
  provider?: string;
  timing?: AiRequestTiming;
  metrics?: AiDurationMetrics;
  generatedPartial?: boolean;
  partialContent?: string;
  stream?: boolean;
  appVersion?: string;
  platform?: string;
};

export type AiRequestState = {
  status: AiRequestStatus;
  stage: AiRequestStage;
  error?: AiRequestError;
  timing: AiRequestTiming;
  metrics?: AiDurationMetrics;
  partialContent?: string;
  generatedPartial: boolean;
  retryable: boolean;
};

type AiErrorMessage = {
  errorCode: AiErrorCode;
  errorType: AiErrorType;
  title: string;
  message: string;
  detail: string;
  primaryAction: AiErrorAction;
  retryable: boolean;
};

type BackendAiError = {
  error_code?: unknown;
  errorCode?: unknown;
  code?: unknown;
  error_type?: unknown;
  errorType?: unknown;
  title?: unknown;
  message?: unknown;
  detail?: unknown;
  stage?: unknown;
  request_id?: unknown;
  requestId?: unknown;
  trace_id?: unknown;
  traceId?: unknown;
  model?: unknown;
  provider?: unknown;
  duration_ms?: unknown;
  durationMs?: unknown;
  first_token_latency_ms?: unknown;
  firstTokenLatencyMs?: unknown;
  generated_partial?: unknown;
  partial_content?: unknown;
  retryable?: unknown;
};

export const AI_ERROR_MESSAGES: Record<AiErrorCode, AiErrorMessage> = {
  CONNECTION_FAILED: {
    errorCode: "CONNECTION_FAILED",
    errorType: "connection_failed",
    title: "连接失败",
    message: "无法连接到 AI 服务，请检查网络或稍后重试。",
    detail: "当前请求未能成功建立连接，可能是网络异常、服务不可用或连接被中断。",
    primaryAction: "retry_connection",
    retryable: true,
  },
  NETWORK_INTERRUPTED: {
    errorCode: "NETWORK_INTERRUPTED",
    errorType: "network_interrupted",
    title: "网络连接中断",
    message: "当前 AI 响应被中断，请检查网络后重试。",
    detail: "请求执行过程中连接被断开，可能导致回复内容不完整。",
    primaryAction: "retry",
    retryable: true,
  },
  API_KEY_MISSING: {
    errorCode: "API_KEY_MISSING",
    errorType: "api_key_missing",
    title: "API Key 未配置",
    message: "当前模型服务缺少 API Key，请先完成配置。",
    detail: "系统未检测到可用的 API Key，无法发起模型调用。",
    primaryAction: "open_settings",
    retryable: false,
  },
  API_KEY_INVALID: {
    errorCode: "API_KEY_INVALID",
    errorType: "api_key_invalid",
    title: "API Key 调用失败",
    message: "当前密钥不可用，请检查配置后重试。",
    detail: "AI 服务鉴权失败，可能是 API Key 无效、过期或没有当前模型的调用权限。",
    primaryAction: "open_settings",
    retryable: false,
  },
  API_KEY_QUOTA_EXCEEDED: {
    errorCode: "API_KEY_QUOTA_EXCEEDED",
    errorType: "api_key_quota_exceeded",
    title: "API Key 额度不足",
    message: "当前密钥额度不足，请更换密钥或稍后重试。",
    detail: "模型服务返回额度不足，当前请求无法继续完成。",
    primaryAction: "open_settings",
    retryable: false,
  },
  MODEL_NOT_FOUND: {
    errorCode: "MODEL_NOT_FOUND",
    errorType: "model_not_found",
    title: "模型不可用",
    message: "当前模型不存在或暂不可用，请切换模型后重试。",
    detail: "模型服务未找到当前配置的模型，可能是模型名称错误、权限不足或 Provider 配置不正确。",
    primaryAction: "switch_model",
    retryable: false,
  },
  MODEL_INFERENCE_FAILED: {
    errorCode: "MODEL_INFERENCE_FAILED",
    errorType: "model_inference_failed",
    title: "AI 推理失败",
    message: "模型在生成结果时遇到问题，请稍后重试。",
    detail: "请求已成功连接到模型服务，但模型在推理过程中发生异常。",
    primaryAction: "retry",
    retryable: true,
  },
  MODEL_TIMEOUT: {
    errorCode: "MODEL_TIMEOUT",
    errorType: "model_timeout",
    title: "请求超时",
    message: "AI 服务响应时间过长，本次请求已停止。",
    detail: "当前请求等待时间超过系统限制，可能是模型服务繁忙、网络不稳定或输入内容过长。",
    primaryAction: "retry",
    retryable: true,
  },
  MODEL_BUSY: {
    errorCode: "MODEL_BUSY",
    errorType: "model_busy",
    title: "AI 服务繁忙",
    message: "当前请求排队时间较长，请稍后重试。",
    detail: "当前模型服务负载较高，任务可能需要更长时间才能完成。",
    primaryAction: "retry",
    retryable: true,
  },
  CONTEXT_TOO_LONG: {
    errorCode: "CONTEXT_TOO_LONG",
    errorType: "context_too_long",
    title: "输入内容过长",
    message: "当前内容超过模型可处理范围，请减少输入内容后重试。",
    detail: "请求上下文长度超过当前模型限制，建议减少输入内容、清理历史上下文或切换更大上下文模型。",
    primaryAction: "shorten_input",
    retryable: false,
  },
  TOOL_CALL_FAILED: {
    errorCode: "TOOL_CALL_FAILED",
    errorType: "tool_call_failed",
    title: "工具调用失败",
    message: "AI 在执行工具时遇到问题，任务已中断。",
    detail: "Agent 执行工具调用过程中发生异常，可能是工具参数错误、权限不足或工具服务不可用。",
    primaryAction: "retry",
    retryable: true,
  },
  USER_CANCELLED: {
    errorCode: "USER_CANCELLED",
    errorType: "user_cancelled",
    title: "任务已取消",
    message: "你已停止本次 AI 生成。",
    detail: "本次任务由用户主动取消，未继续生成后续内容。",
    primaryAction: "retry",
    retryable: true,
  },
  UNKNOWN_ERROR: {
    errorCode: "UNKNOWN_ERROR",
    errorType: "unknown_error",
    title: "请求失败",
    message: "AI 服务出现未知异常，请稍后重试。",
    detail: "当前错误未能被系统识别，请复制诊断信息反馈给开发者。",
    primaryAction: "retry",
    retryable: true,
  },
};

export const AI_TIMEOUT_CONFIG = {
  chat: {
    slowHintMs: 10000,
    longSlowHintMs: 30000,
    timeoutMs: 60000,
  },
  agentTask: {
    slowHintMs: 30000,
    longSlowHintMs: 60000,
    timeoutMs: 600000,
  },
} as const;

export function createAiRequestState(now = Date.now()): AiRequestState {
  return {
    status: "preparing",
    stage: "preparing",
    timing: {
      requestStartAt: now,
    },
    generatedPartial: false,
    retryable: false,
  };
}

export function calculateAiDurationMetrics(
  timing: AiRequestTiming,
  now = Date.now(),
): AiDurationMetrics {
  const requestEndAt = timing.requestEndAt ?? now;
  const durationMs = Math.max(0, requestEndAt - timing.requestStartAt);
  const connectionDurationMs =
    timing.connectionStartAt !== undefined && timing.connectionEndAt !== undefined
      ? Math.max(0, timing.connectionEndAt - timing.connectionStartAt)
      : undefined;
  const firstTokenLatencyMs =
    timing.firstTokenAt !== undefined
      ? Math.max(0, timing.firstTokenAt - timing.requestStartAt)
      : undefined;
  const reasoningDurationMs =
    timing.connectionEndAt !== undefined
      ? Math.max(0, (timing.firstTokenAt ?? requestEndAt) - timing.connectionEndAt)
      : undefined;

  return {
    durationMs,
    connectionDurationMs,
    firstTokenLatencyMs,
    reasoningDurationMs,
  };
}

export function formatAiDuration(durationMs: number): string {
  if (durationMs < 1000) {
    return `${Math.max(0, Math.round(durationMs))} ms`;
  }
  return `${(Math.max(0, durationMs) / 1000).toFixed(1)} 秒`;
}

export function normalizeAiError(error: unknown, context: AiRequestContext = {}): AiRequestError {
  const backend = getBackendError(error);
  const rawMessage = getString(backend?.message) ?? getErrorMessage(error);
  const rawDetail = getString(backend?.detail);
  const searchableText = `${rawMessage ?? ""} ${rawDetail ?? ""}`.toLowerCase();
  const detectedCode = getAiErrorCode(backend) ?? inferAiErrorCode(error, searchableText);
  const template = AI_ERROR_MESSAGES[detectedCode];
  const durationMs =
    getNumber(backend?.duration_ms) ??
    getNumber(backend?.durationMs) ??
    context.metrics?.durationMs;
  const firstTokenLatencyMs =
    getNumber(backend?.first_token_latency_ms) ??
    getNumber(backend?.firstTokenLatencyMs) ??
    context.metrics?.firstTokenLatencyMs;
  const retryable =
    typeof backend?.retryable === "boolean" ? backend.retryable : template.retryable;

  return {
    errorCode: template.errorCode,
    errorType: getAiErrorType(backend) ?? template.errorType,
    title: getString(backend?.title) ?? template.title,
    message: template.message,
    detail: rawDetail ?? template.detail,
    stage: getAiStage(backend?.stage) ?? context.stage,
    requestId: getString(backend?.request_id) ?? getString(backend?.requestId) ?? context.requestId,
    traceId: getString(backend?.trace_id) ?? getString(backend?.traceId) ?? context.traceId,
    model: getString(backend?.model) ?? context.model,
    provider: getString(backend?.provider) ?? context.provider,
    durationMs,
    firstTokenLatencyMs,
    retryable,
    rawError: error,
    createdAt: new Date().toISOString(),
  };
}

export function resolveAiErrorActions(error: AiRequestError | AiErrorCode): AiErrorAction[] {
  const errorCode = typeof error === "string" ? error : error.errorCode;
  const actionsByCode: Record<AiErrorCode, AiErrorAction[]> = {
    CONNECTION_FAILED: ["retry_connection", "copy_error", "view_detail"],
    NETWORK_INTERRUPTED: ["retry", "copy_partial_content", "copy_error", "view_detail"],
    API_KEY_MISSING: ["open_settings", "copy_error", "view_detail"],
    API_KEY_INVALID: ["open_settings", "switch_model", "copy_error", "view_detail"],
    API_KEY_QUOTA_EXCEEDED: ["open_settings", "switch_model", "copy_error", "view_detail"],
    MODEL_NOT_FOUND: ["switch_model", "copy_error", "view_detail"],
    MODEL_INFERENCE_FAILED: ["retry", "switch_model", "copy_error", "view_detail"],
    MODEL_TIMEOUT: ["retry", "shorten_input", "view_detail", "copy_error"],
    MODEL_BUSY: ["retry", "switch_model", "copy_error", "view_detail"],
    CONTEXT_TOO_LONG: ["shorten_input", "switch_model", "copy_error", "view_detail"],
    TOOL_CALL_FAILED: ["retry", "copy_error", "view_detail"],
    USER_CANCELLED: ["retry", "copy_partial_content"],
    UNKNOWN_ERROR: ["retry", "copy_error", "view_detail"],
  };
  return actionsByCode[errorCode];
}

export function buildAiErrorSummaryText(error: AiRequestError): string {
  return redactSensitiveText(
    [
      `错误类型：${error.title}`,
      `错误说明：${error.message}`,
      error.stage ? `请求阶段：${formatAiStage(error.stage)}` : undefined,
      error.durationMs !== undefined ? `已耗时：${formatAiDuration(error.durationMs)}` : undefined,
      `错误码：${error.errorCode}`,
      error.requestId ? `Request ID：${error.requestId}` : undefined,
      error.traceId ? `Trace ID：${error.traceId}` : undefined,
      error.model ? `模型：${error.model}` : undefined,
      error.provider ? `服务商：${error.provider}` : undefined,
      `时间：${formatAiTimestamp(error.createdAt)}`,
    ]
      .filter(Boolean)
      .join("\n"),
  );
}

export function buildAiDiagnosticText({
  error,
  metrics,
  context = {},
}: {
  error: AiRequestError;
  metrics?: AiDurationMetrics;
  context?: AiRequestContext;
}): string {
  const finalMetrics = metrics ?? {
    durationMs: error.durationMs ?? 0,
    firstTokenLatencyMs: error.firstTokenLatencyMs,
  };
  const partialContent = context.partialContent ?? "";
  const lines = [
    "【Codex App AI 异常诊断信息】",
    "",
    "错误信息：",
    `- 错误类型：${error.title}`,
    `- 错误码：${error.errorCode}`,
    `- 错误说明：${error.message}`,
    `- 错误详情：${error.detail ?? "-"}`,
    "",
    "请求信息：",
    `- Request ID：${error.requestId ?? "-"}`,
    `- Trace ID：${error.traceId ?? "-"}`,
    `- Model：${error.model ?? "-"}`,
    `- Provider：${error.provider ?? "-"}`,
    `- Stage：${error.stage ?? context.stage ?? "-"}`,
    `- Stream：${context.stream ? "true" : "false"}`,
    "",
    "耗时信息：",
    `- 总耗时：${formatAiDuration(finalMetrics.durationMs)}`,
    `- 首包耗时：${formatOptionalDuration(
      finalMetrics.firstTokenLatencyMs ?? error.firstTokenLatencyMs,
    )}`,
    `- 建立连接耗时：${formatOptionalDuration(finalMetrics.connectionDurationMs)}`,
    "",
    "生成信息：",
    `- 是否已生成部分内容：${context.generatedPartial ? "是" : "否"}`,
    `- 已生成字符数：${partialContent.length}`,
    "",
    "客户端信息：",
    `- App Version：${context.appVersion ?? "-"}`,
    `- Platform：${context.platform ?? getDefaultPlatform()}`,
    `- Time：${formatAiTimestamp(error.createdAt)}`,
  ];
  return redactSensitiveText(lines.join("\n"));
}

export function formatAiStage(stage: AiRequestStage): string {
  const labels: Record<AiRequestStage, string> = {
    preparing: "请求准备",
    connecting: "连接服务",
    queued: "排队等待",
    reasoning: "模型推理",
    streaming: "流式输出",
    tool_calling: "工具调用",
    saving: "保存结果",
    done: "完成",
  };
  return labels[stage];
}

export function redactSensitiveText(content: string): string {
  return content
    .replace(
      /\b(authorization)(\s*[:=]\s*)(["']?)Bearer\s+([^\s"',;]+)(["']?)/gi,
      (_match, name: string, separator: string, quote: string, value: string, endQuote: string) =>
        `${name}${separator}${quote}Bearer ${maskSecretValue(value)}${endQuote}`,
    )
    .replace(
      /\b(api[_-]?key|token|cookie|password|secret|ssh[_-]?key)(\s*[:=]\s*)(["']?)([^\s"',;]+)/gi,
      (_match, name: string, separator: string, quote: string, value: string) =>
        `${name}${separator}${quote}${maskSecretValue(value)}`,
    )
    .replace(/\bBearer\s+([A-Za-z0-9._~+/-]{12,})/g, (_match, value: string) => {
      return `Bearer ${maskSecretValue(value)}`;
    })
    .replace(/\b(sk|ak|pk|rk)-[A-Za-z0-9_-]{8,}/g, (value) => maskSecretValue(value));
}

function getBackendError(error: unknown): BackendAiError | undefined {
  if (error && typeof error === "object") {
    if ("data" in error && error.data && typeof error.data === "object") {
      return error.data as BackendAiError;
    }
    return error as BackendAiError;
  }
  return undefined;
}

function getAiErrorCode(error: BackendAiError | undefined): AiErrorCode | undefined {
  const value = getString(error?.error_code) ?? getString(error?.errorCode) ?? getString(error?.code);
  return isAiErrorCode(value) ? value : undefined;
}

function getAiErrorType(error: BackendAiError | undefined): AiErrorType | undefined {
  const value = getString(error?.error_type) ?? getString(error?.errorType);
  return isAiErrorType(value) ? value : undefined;
}

function inferAiErrorCode(error: unknown, searchableText: string): AiErrorCode {
  if (isAbortError(error)) {
    return "USER_CANCELLED";
  }
  if (isTimeoutError(error) || /timeout|timed out|超时/.test(searchableText)) {
    return "MODEL_TIMEOUT";
  }
  if (/api key|apikey|unauthorized|forbidden|401|403|鉴权|密钥/.test(searchableText)) {
    if (/missing|not configured|未配置|缺少/.test(searchableText)) {
      return "API_KEY_MISSING";
    }
    if (/quota|balance|额度|insufficient/.test(searchableText)) {
      return "API_KEY_QUOTA_EXCEEDED";
    }
    return "API_KEY_INVALID";
  }
  if (/context|token limit|too long|上下文|输入内容过长/.test(searchableText)) {
    return "CONTEXT_TOO_LONG";
  }
  if (/model.*not found|model_not_found|模型不存在|模型不可用/.test(searchableText)) {
    return "MODEL_NOT_FOUND";
  }
  if (/busy|rate limit|429|排队|繁忙/.test(searchableText)) {
    return "MODEL_BUSY";
  }
  if (/tool|工具/.test(searchableText)) {
    return "TOOL_CALL_FAILED";
  }
  if (
    error instanceof TypeError ||
    /failed to fetch|networkerror|connection|connect|网络|连接|spawn/.test(searchableText)
  ) {
    return "CONNECTION_FAILED";
  }
  if (/interrupted|中断|断开/.test(searchableText)) {
    return "NETWORK_INTERRUPTED";
  }
  if (/推理|inference|generation/.test(searchableText)) {
    return "MODEL_INFERENCE_FAILED";
  }
  return "UNKNOWN_ERROR";
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError";
}

function isTimeoutError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "TimeoutError";
}

function getAiStage(value: unknown): AiRequestStage | undefined {
  const stage = getString(value);
  const stages: AiRequestStage[] = [
    "preparing",
    "connecting",
    "queued",
    "reasoning",
    "streaming",
    "tool_calling",
    "saving",
    "done",
  ];
  return stage && stages.includes(stage as AiRequestStage)
    ? (stage as AiRequestStage)
    : undefined;
}

function isAiErrorCode(value: string | undefined): value is AiErrorCode {
  return Boolean(value && value in AI_ERROR_MESSAGES);
}

function isAiErrorType(value: string | undefined): value is AiErrorType {
  return Boolean(
    value &&
      [
        "connection_failed",
        "network_interrupted",
        "api_key_missing",
        "api_key_invalid",
        "api_key_quota_exceeded",
        "model_not_found",
        "model_inference_failed",
        "model_timeout",
        "model_busy",
        "context_too_long",
        "tool_call_failed",
        "user_cancelled",
        "unknown_error",
      ].includes(value),
  );
}

function getString(value: unknown): string | undefined {
  return typeof value === "string" && value.trim() ? value.trim() : undefined;
}

function getNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function getErrorMessage(error: unknown): string | undefined {
  if (error instanceof Error) {
    return error.message;
  }
  return getString(error);
}

function formatOptionalDuration(value: number | undefined): string {
  return value === undefined ? "-" : formatAiDuration(value);
}

function formatAiTimestamp(value: string): string {
  return new Date(value).toLocaleString();
}

function getDefaultPlatform(): string {
  if (typeof navigator === "undefined") {
    return "unknown";
  }
  return navigator.userAgent;
}

function maskSecretValue(value: string): string {
  if (value.length <= 8) {
    return "****";
  }
  return `${value.slice(0, 4)}****${value.slice(-4)}`;
}

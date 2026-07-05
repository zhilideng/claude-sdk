import {
  FormEvent,
  KeyboardEvent,
  RefObject,
  useEffect,
  useMemo,
  useRef,
  useState,
} from "react";
import {
  AI_TIMEOUT_CONFIG,
  buildAiDiagnosticText,
  buildAiErrorSummaryText,
  calculateAiDurationMetrics,
  createAiRequestState,
  formatAiDuration,
  formatAiStage,
  normalizeAiError,
  resolveAiErrorActions,
  type AiDurationMetrics,
  type AiErrorAction,
  type AiRequestError,
  type AiRequestStage,
  type AiRequestState,
} from "../features/ai-request-status/aiRequestStatus";
import {
  clearBrowserAuthUser,
  readBrowserAuthUser,
  saveBrowserAuthUser,
  type AuthUser,
} from "./authSession";
import {
  buildRunningTaskMarkers,
  isActiveTaskStatus,
  parseConversationSessionId,
  removeRunningTaskMarker,
  upsertRunningTaskMarker,
  type AgentTaskRunningItem,
  type AgentTaskStatus,
  type RunningTaskMarkers,
} from "./agentTaskState";

type AuthMode = "login" | "register";

type ApiResponse<T> = {
  code: number;
  message: string;
  data: T | null;
  errno?: number;
};

type AuthData = {
  user: AuthUser;
};

type FormState = {
  userName: string;
  password: string;
};

type ProjectSession = {
  id: number;
  project_id: number;
  title: string;
  status: "idle" | "running" | "failed";
  last_message: string | null;
  updated_at: string | null;
};

type Project = {
  id: number;
  user_id: number;
  name: string;
  root_path: string | null;
  display_path: string | null;
  source_type: string;
  is_git_repo: boolean;
  sessions: ProjectSession[];
};

type ProjectListData = {
  items: Project[];
};

type ProjectImportData = {
  project: Project;
  default_session: ProjectSession | null;
};

type WorkspaceSnapshot = {
  activeProjectId: number | null;
  activeSessionId: number | null;
  projectPaths: Record<string, string>;
};

type SessionMessage = {
  id: number;
  session_id: number;
  role: "user" | "assistant" | "system";
  content: string;
  status: "done" | "failed";
  tool_summary: Record<string, unknown>[];
  diff_summary: Record<string, unknown>[];
  created_at: string | null;
  ai_error?: AiRequestError;
  ai_metrics?: AiDurationMetrics;
  partial_content?: string;
  generated_partial?: boolean;
};

type SessionMessageListData = {
  items: SessionMessage[];
};

type StreamEventEnvelope = {
  type: string;
  sequence: number;
  session_id: number;
  message_id: number | null;
  data: Record<string, unknown>;
  created_at: string;
};

type AgentTask = {
  task_id: string;
  conversation_id: string | null;
  title: string | null;
  prompt: string;
  status: AgentTaskStatus;
  result: string | null;
  error_message: string | null;
  cancel_requested: boolean;
  created_at: string | null;
  updated_at: string | null;
  started_at: string | null;
  finished_at: string | null;
};

type AgentTaskEvent = {
  seq: number;
  event_type: string;
  content: string | null;
  metadata: Record<string, unknown>;
  created_at: string | null;
};

type AgentTaskCreateData = {
  task_id: string;
  status: AgentTaskStatus;
};

type AgentTaskEventListData = {
  items: AgentTaskEvent[];
};

type AgentTaskRunningListData = {
  items: AgentTaskRunningItem[];
};

type AgentTaskStreamOptions = {
  onConnected?: () => void;
  onReconnect?: (delayMs: number) => void;
  onError?: () => void;
};

type ToolStatus = {
  id: string;
  name: string;
  category: ToolCategory;
  status: "running" | "done";
  partial: string;
};

type ToolCategory = "thinking" | "terminal" | "file" | "search" | "mcp" | "tool";

type AssistantContentBlock =
  | {
      type: "text";
      content: string;
    }
  | {
      type: "code";
      language: string;
      content: string;
    };

type TextLineBlock =
  | {
      type: "paragraph";
      content: string;
    }
  | {
      type: "heading";
      level: number;
      content: string;
    }
  | {
      type: "quote";
      content: string;
    }
  | {
      type: "list";
      ordered: boolean;
      checklist: boolean;
      items: TextListItem[];
    }
  | {
      type: "table";
      headers: string[];
      rows: string[][];
    }
  | {
      type: "workflow";
      title: string;
      items: TextListItem[];
    };

type TextListItem = {
  content: string;
  checked?: boolean;
};

type CopyContentHandler = (content: string, label: string) => void;

type CreateProjectForm = {
  directoryName: string;
  rootPath: string;
};

type LoadProjectsOptions = {
  preferredProjectId?: number;
  preferredSessionId?: number | null;
  draftSession?: boolean;
};

const initialForm: FormState = {
  userName: "",
  password: "",
};

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "";
const appVersion = import.meta.env.VITE_APP_VERSION ?? "0.1.0";

type SendMessageStreamOptions = {
  signal?: AbortSignal;
  onConnected?: () => void;
  onFirstToken?: () => void;
};

class AiStreamRequestError extends Error {
  data?: Record<string, unknown>;

  constructor(message: string, data?: Record<string, unknown>) {
    super(message);
    this.name = "AiStreamRequestError";
    this.data = data;
  }
}

function getWorkspaceSnapshotKey(userId: number) {
  return `claude-sdk.workspace.${userId}`;
}

function getActiveTaskStorageKey(userId: number) {
  return `claude-sdk.activeTask.${userId}`;
}

function readActiveTaskId(userId: number): string | null {
  try {
    return window.localStorage.getItem(getActiveTaskStorageKey(userId));
  } catch {
    return null;
  }
}

function saveActiveTaskId(userId: number, taskId: string) {
  try {
    window.localStorage.setItem(getActiveTaskStorageKey(userId), taskId);
  } catch {
    // localStorage 失败不应阻断任务执行。
  }
}

function clearActiveTaskId(userId: number, taskId?: string) {
  try {
    const key = getActiveTaskStorageKey(userId);
    if (!taskId || window.localStorage.getItem(key) === taskId) {
      window.localStorage.removeItem(key);
    }
  } catch {
    // localStorage 失败不影响主流程。
  }
}

function readTaskIdFromUrl() {
  return new URLSearchParams(window.location.search).get("task_id");
}

function writeTaskIdToUrl(taskId: string | null) {
  const url = new URL(window.location.href);
  if (taskId) {
    url.searchParams.set("task_id", taskId);
  } else {
    url.searchParams.delete("task_id");
  }
  window.history.replaceState({}, "", url.toString());
}

function createEmptyWorkspaceSnapshot(): WorkspaceSnapshot {
  return {
    activeProjectId: null,
    activeSessionId: null,
    projectPaths: {},
  };
}

function readWorkspaceSnapshot(userId: number): WorkspaceSnapshot {
  try {
    const raw = window.localStorage.getItem(getWorkspaceSnapshotKey(userId));
    if (!raw) {
      return createEmptyWorkspaceSnapshot();
    }
    const parsed = JSON.parse(raw) as Partial<WorkspaceSnapshot>;
    return {
      activeProjectId:
        typeof parsed.activeProjectId === "number" ? parsed.activeProjectId : null,
      activeSessionId:
        typeof parsed.activeSessionId === "number" ? parsed.activeSessionId : null,
      projectPaths:
        parsed.projectPaths && typeof parsed.projectPaths === "object"
          ? Object.fromEntries(
              Object.entries(parsed.projectPaths).filter(
                (item): item is [string, string] => typeof item[1] === "string",
              ),
            )
          : {},
    };
  } catch {
    return createEmptyWorkspaceSnapshot();
  }
}

function saveWorkspaceSnapshot(userId: number, snapshot: WorkspaceSnapshot) {
  try {
    window.localStorage.setItem(getWorkspaceSnapshotKey(userId), JSON.stringify(snapshot));
  } catch {
    // localStorage 可能因隐私模式或配额失败；不阻断主流程。
  }
}

function collectProjectPaths(
  projects: Project[],
  previousPaths: Record<string, string> = {},
) {
  const nextPaths = { ...previousPaths };
  projects.forEach((project) => {
    const path = project.root_path ?? project.display_path;
    if (path) {
      nextPaths[String(project.id)] = path;
    }
  });
  return nextPaths;
}

function summarizeSessionTitle(content: string) {
  const normalized = content.replace(/\s+/g, " ").trim();
  const firstSentence = normalized.split(/[。！？!?]/)[0]?.trim() || normalized;
  const title = firstSentence || "新会话";
  return title.length > 32 ? `${title.slice(0, 32)}...` : title;
}

function createLocalFailedMessage(
  sessionId: number,
  content: string,
  aiError?: AiRequestError,
  partialContent?: string,
  metrics?: AiDurationMetrics,
): SessionMessage {
  return {
    id: -Date.now() - 1,
    session_id: sessionId,
    role: "assistant",
    content,
    status: "failed",
    tool_summary: [],
    diff_summary: [],
    created_at: new Date().toISOString(),
    ai_error: aiError,
    ai_metrics: metrics,
    partial_content: partialContent,
    generated_partial: Boolean(partialContent),
  };
}

function mergeLocalFailedMessage(
  items: SessionMessage[],
  userMessage: SessionMessage | null,
  failedMessage: SessionMessage,
) {
  const nextItems = [...items];
  if (
    userMessage &&
    !nextItems.some(
      (item) =>
        item.session_id === userMessage.session_id &&
        item.role === "user" &&
        item.content === userMessage.content,
    )
  ) {
    nextItems.push(userMessage);
  }
  if (
    !nextItems.some(
      (item) =>
        item.session_id === failedMessage.session_id &&
        item.role === "assistant" &&
        item.status === "failed" &&
        item.content === failedMessage.content,
    )
  ) {
    nextItems.push(failedMessage);
  }
  return nextItems;
}

async function requestJson<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    ...init,
    headers: {
      "Content-Type": "application/json",
      ...(init?.headers ?? {}),
    },
  });
  const result = (await response.json()) as ApiResponse<T>;
  if (!response.ok || result.code >= 400) {
    throw new Error(result.message || "请求失败");
  }
  if (result.data === null) {
    throw new Error("响应数据为空");
  }
  return result.data;
}

async function requestAuth(mode: AuthMode, form: FormState): Promise<AuthData> {
  const endpoint = mode === "register" ? "/v1/users/register" : "/v1/users/login";
  return requestJson<AuthData>(endpoint, {
    method: "POST",
    body: JSON.stringify({ user_name: form.userName.trim(), password: form.password }),
  });
}

async function requestProjects(userId: number): Promise<ProjectListData> {
  return requestJson<ProjectListData>(`/v1/projects?user_id=${userId}`);
}

async function requestPickLocalDirectory(): Promise<PickedDirectory> {
  return requestJson<PickedDirectory>("/v1/projects/pick-local-directory", {
    method: "POST",
  });
}

async function requestImportProject(
  userId: number,
  form: CreateProjectForm,
): Promise<ProjectImportData> {
  return requestJson<ProjectImportData>("/v1/projects/import-local-path", {
    method: "POST",
    body: JSON.stringify({
      user_id: userId,
      directory_name: form.directoryName.trim(),
      root_path: form.rootPath.trim(),
    }),
  });
}

async function requestCreateSession(
  userId: number,
  projectId: number,
  title = "新会话",
): Promise<ProjectSession> {
  return requestJson<ProjectSession>(`/v1/projects/${projectId}/sessions`, {
    method: "POST",
    body: JSON.stringify({ user_id: userId, title }),
  });
}

async function requestMessages(
  userId: number,
  sessionId: number,
): Promise<SessionMessageListData> {
  return requestJson<SessionMessageListData>(
    `/v1/sessions/${sessionId}/messages?user_id=${userId}`,
  );
}

async function requestCreateAgentTask(
  conversationId: string,
  prompt: string,
  title?: string,
): Promise<AgentTaskCreateData> {
  return requestJson<AgentTaskCreateData>("/v1/tasks", {
    method: "POST",
    body: JSON.stringify({
      conversation_id: conversationId,
      prompt,
      title,
    }),
  });
}

async function requestAgentTask(taskId: string): Promise<AgentTask> {
  return requestJson<AgentTask>(`/v1/tasks/${taskId}`);
}

async function requestAgentTaskEvents(
  taskId: string,
  afterSeq = 0,
): Promise<AgentTaskEventListData> {
  return requestJson<AgentTaskEventListData>(
    `/v1/tasks/${taskId}/events?after_seq=${afterSeq}`,
  );
}

async function requestRunningAgentTasks(): Promise<AgentTaskRunningListData> {
  return requestJson<AgentTaskRunningListData>("/v1/tasks/running");
}

async function requestCancelAgentTask(taskId: string): Promise<AgentTaskCreateData> {
  return requestJson<AgentTaskCreateData>(`/v1/tasks/${taskId}/cancel`, {
    method: "POST",
  });
}

function subscribeAgentTaskEvents(
  taskId: string,
  afterSeq: number,
  onEvent: (event: AgentTaskEvent) => void,
  options: AgentTaskStreamOptions = {},
) {
  const reconnectDelays = [1000, 3000, 5000, 10000];
  let closed = false;
  let finished = false;
  let retryIndex = 0;
  let lastSeq = afterSeq;
  let source: EventSource | null = null;
  let retryTimer: number | null = null;

  const closeSource = () => {
    source?.close();
    source = null;
  };

  const connect = () => {
    if (closed || finished) {
      return;
    }
    closeSource();
    source = new EventSource(
      `${apiBaseUrl}/v1/tasks/${taskId}/stream?after_seq=${lastSeq}`,
    );
    source.onopen = () => {
      retryIndex = 0;
      options.onConnected?.();
    };
    source.addEventListener("task_event", (message) => {
      const event = JSON.parse(message.data) as AgentTaskEvent;
      if (event.seq <= lastSeq) {
        return;
      }
      lastSeq = event.seq;
      onEvent(event);
      if (isTerminalTaskEvent(event.event_type)) {
        finished = true;
        closeSource();
      }
    });
    source.onerror = () => {
      options.onError?.();
      closeSource();
      if (closed || finished) {
        return;
      }
      const delay = reconnectDelays[Math.min(retryIndex, reconnectDelays.length - 1)];
      retryIndex += 1;
      options.onReconnect?.(delay);
      retryTimer = window.setTimeout(connect, delay);
    };
  };

  connect();

  return () => {
    closed = true;
    if (retryTimer !== null) {
      window.clearTimeout(retryTimer);
    }
    closeSource();
  };
}

async function requestSendMessageStream(
  userId: number,
  sessionId: number,
  content: string,
  onEvent: (event: StreamEventEnvelope) => void,
  options: SendMessageStreamOptions = {},
): Promise<void> {
  const response = await fetch(`${apiBaseUrl}/v1/sessions/${sessionId}/messages/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ user_id: userId, content }),
    signal: options.signal,
  }).catch((error) => {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw error;
    }
    const detail = error instanceof Error && error.message ? `：${error.message}` : "";
    throw new AiStreamRequestError(`推理连接中断，请检查后端服务状态${detail}`, {
      error_code: "CONNECTION_FAILED",
      error_type: "connection_failed",
      message: `推理连接中断，请检查后端服务状态${detail}`,
      stage: "connecting",
      retryable: true,
    });
  });

  if (!response.ok) {
    const result = (await response.json().catch(() => null)) as ApiResponse<
      Record<string, unknown>
    > | null;
    throw new AiStreamRequestError(result?.message || "消息发送失败", {
      ...(result?.data ?? {}),
      message: result?.message || "消息发送失败",
      stage: "connecting",
      retryable: response.status >= 500,
    });
  }
  if (!response.body) {
    throw new AiStreamRequestError("当前浏览器不支持流式响应", {
      error_code: "UNKNOWN_ERROR",
      message: "当前浏览器不支持流式响应",
      stage: "connecting",
      retryable: false,
    });
  }

  options.onConnected?.();
  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let hasFirstToken = false;

  while (true) {
    const { value, done } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
    const frames = buffer.split("\n\n");
    buffer = frames.pop() ?? "";

    for (const frame of frames) {
      const dataLines = frame
        .split("\n")
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).trimStart());
      if (dataLines.length === 0) {
        continue;
      }
      const event = JSON.parse(dataLines.join("\n")) as StreamEventEnvelope;
      if (event.type === "assistant_delta" && !hasFirstToken) {
        const contentValue = event.data.content;
        if (typeof contentValue === "string" && contentValue.length > 0) {
          hasFirstToken = true;
          options.onFirstToken?.();
        }
      }
      onEvent(event);
      if (event.type === "agent_error") {
        const message = event.data.message;
        throw new AiStreamRequestError(
          typeof message === "string" ? message : "推理失败，请稍后重试",
          event.data,
        );
      }
    }

    if (done) {
      break;
    }
  }
}

export default function App() {
  const [mode, setMode] = useState<AuthMode>("login");
  const [form, setForm] = useState<FormState>(initialForm);
  const [message, setMessage] = useState("");
  const [currentUser, setCurrentUser] = useState<AuthUser | null>(() => readBrowserAuthUser());
  const [isSubmitting, setIsSubmitting] = useState(false);

  const submitText = useMemo(() => (mode === "register" ? "注册账号" : "登录"), [mode]);

  const handleModeChange = (nextMode: AuthMode) => {
    setMode(nextMode);
    setMessage("");
    setCurrentUser(null);
  };

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    setIsSubmitting(true);
    setMessage("");
    setCurrentUser(null);

    try {
      const result = await requestAuth(mode, form);
      setCurrentUser(result.user);
      setMessage(mode === "register" ? "注册成功" : "登录成功");
      if (mode === "login") {
        saveBrowserAuthUser(result.user);
      }
      if (mode === "register") {
        setForm(initialForm);
      }
    } catch (error) {
      setMessage(error instanceof Error ? error.message : "请求失败");
    } finally {
      setIsSubmitting(false);
    }
  };

  if (currentUser && mode === "login") {
    return (
      <WorkspacePage
        user={currentUser}
        onLogout={() => {
          clearBrowserAuthUser();
          setCurrentUser(null);
          setMessage("");
          setForm(initialForm);
        }}
      />
    );
  }

  return (
    <main className="app-shell">
      <section className="auth-panel" aria-label="用户账号">
        <div className="auth-header">
          <p className="auth-eyebrow">Account</p>
          <h1>用户账号</h1>
        </div>

        <div className="auth-tabs" role="tablist" aria-label="账号操作">
          <button
            className={mode === "login" ? "active" : ""}
            type="button"
            role="tab"
            aria-selected={mode === "login"}
            onClick={() => handleModeChange("login")}
          >
            登录
          </button>
          <button
            className={mode === "register" ? "active" : ""}
            type="button"
            role="tab"
            aria-selected={mode === "register"}
            onClick={() => handleModeChange("register")}
          >
            注册
          </button>
        </div>

        <form className="auth-form" onSubmit={handleSubmit}>
          <label>
            <span>用户名</span>
            <input
              maxLength={255}
              required
              type="text"
              value={form.userName}
              onChange={(event) => setForm({ ...form, userName: event.target.value })}
            />
          </label>

          <label>
            <span>密码</span>
            <input
              maxLength={255}
              required
              type="password"
              value={form.password}
              onChange={(event) => setForm({ ...form, password: event.target.value })}
            />
          </label>

          <button className="auth-submit" disabled={isSubmitting} type="submit">
            {isSubmitting ? "提交中..." : submitText}
          </button>
        </form>

        {message ? (
          <p className={currentUser ? "auth-message success" : "auth-message"}>{message}</p>
        ) : null}

        {currentUser ? (
          <div className="auth-result" aria-label="当前用户">
            <span>ID: {currentUser.id}</span>
            <strong>{currentUser.user_name}</strong>
          </div>
        ) : null}
      </section>
    </main>
  );
}

function WorkspacePage({
  user,
  onLogout,
}: {
  user: AuthUser;
  onLogout: () => void;
}) {
  const [projects, setProjects] = useState<Project[]>([]);
  const [activeProjectId, setActiveProjectId] = useState<number | null>(null);
  const [activeSessionId, setActiveSessionId] = useState<number | null>(null);
  const [messages, setMessages] = useState<SessionMessage[]>([]);
  const [notice, setNotice] = useState("");
  const [composerText, setComposerText] = useState("");
  const [isMobileSidebarOpen, setIsMobileSidebarOpen] = useState(false);
  const [isCreateModalOpen, setIsCreateModalOpen] = useState(false);
  const [isLoadingProjects, setIsLoadingProjects] = useState(true);
  const [isSending, setIsSending] = useState(false);
  const [isDraftSession, setIsDraftSession] = useState(false);
  const [streamingText, setStreamingText] = useState("");
  const [streamTools, setStreamTools] = useState<ToolStatus[]>([]);
  const [streamStatus, setStreamStatus] = useState("");
  const [runningTasksBySessionId, setRunningTasksBySessionId] =
    useState<RunningTaskMarkers>({});
  const [aiRequestState, setAiRequestState] = useState<AiRequestState | null>(null);
  const [requestElapsedMs, setRequestElapsedMs] = useState(0);
  const composerTextareaRef = useRef<HTMLTextAreaElement>(null);
  const abortControllerRef = useRef<AbortController | null>(null);
  const activeTaskIdRef = useRef<string | null>(null);
  const activeTaskSessionIdRef = useRef<number | null>(null);
  const taskStreamCleanupRef = useRef<(() => void) | null>(null);
  const lastTaskSeqRef = useRef(0);
  const aiRequestStateRef = useRef<AiRequestState | null>(null);
  const streamingTextRef = useRef("");
  const pendingLocalFailedMessageRef = useRef<{
    userMessage: SessionMessage | null;
    failedMessage: SessionMessage;
  } | null>(null);

  const activeProject = projects.find((project) => project.id === activeProjectId) ?? null;
  const activeSession =
    activeProject?.sessions.find((session) => session.id === activeSessionId) ?? null;
  const canCompose = Boolean(activeSession || (activeProject && isDraftSession));
  const hasConversationContent =
    messages.length > 0 || isSending || Boolean(streamingText) || streamTools.length > 0;

  const updateAiRequestState = (
    updater: AiRequestState | ((current: AiRequestState | null) => AiRequestState | null) | null,
  ) => {
    setAiRequestState((current) => {
      const next = typeof updater === "function" ? updater(current) : updater;
      aiRequestStateRef.current = next;
      return next;
    });
  };

  useEffect(() => {
    streamingTextRef.current = streamingText;
  }, [streamingText]);

  useEffect(() => {
    if (!isSending || !aiRequestStateRef.current) {
      setRequestElapsedMs(0);
      return undefined;
    }

    const refreshElapsed = () => {
      const state = aiRequestStateRef.current;
      if (!state) {
        return;
      }
      const metrics = calculateAiDurationMetrics(state.timing);
      setRequestElapsedMs(metrics.durationMs);
      updateAiRequestState((current) => {
        if (!current) {
          return current;
        }
        const shouldShowSlow =
          metrics.durationMs >= AI_TIMEOUT_CONFIG.chat.slowHintMs &&
          current.status !== "streaming" &&
          current.status !== "tool_calling";
        return {
          ...current,
          status: shouldShowSlow ? "slow" : current.status,
          metrics,
        };
      });
    };

    refreshElapsed();
    const timer = window.setInterval(refreshElapsed, 1000);
    return () => window.clearInterval(timer);
  }, [isSending]);

  const loadProjects = async (options: number | LoadProjectsOptions = {}) => {
    setIsLoadingProjects(true);
    try {
      const data = await requestProjects(user.id);
      const snapshot = readWorkspaceSnapshot(user.id);
      const loadOptions =
        typeof options === "number" ? { preferredSessionId: options } : options;
      const preferredSessionId = loadOptions.preferredSessionId ?? undefined;
      const preferredProjectId =
        loadOptions.preferredProjectId ??
        (preferredSessionId ? null : snapshot.activeProjectId);
      const shouldUseDraftSession = loadOptions.draftSession === true;
      setProjects(data.items);
      const preferredSnapshotSessionId = shouldUseDraftSession
        ? undefined
        : (preferredSessionId ?? snapshot.activeSessionId ?? undefined);
      const nextProject =
        (preferredSnapshotSessionId
          ? data.items.find((project) =>
              project.sessions.some((session) => session.id === preferredSnapshotSessionId),
            )
          : null) ??
        data.items.find((project) => project.id === preferredProjectId) ??
        data.items[0] ??
        null;
      const nextSession =
        shouldUseDraftSession
          ? null
          : (nextProject?.sessions.find((session) => session.id === preferredSnapshotSessionId) ??
            nextProject?.sessions[0] ??
            null);
      const nextIsDraftSession = Boolean(nextProject && (shouldUseDraftSession || !nextSession));
      setActiveProjectId(nextProject?.id ?? null);
      setActiveSessionId(nextSession?.id ?? null);
      setIsDraftSession(nextIsDraftSession);
      saveWorkspaceSnapshot(user.id, {
        activeProjectId: nextProject?.id ?? null,
        activeSessionId: nextSession?.id ?? null,
        projectPaths: collectProjectPaths(data.items, snapshot.projectPaths),
      });
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "项目加载失败");
    } finally {
      setIsLoadingProjects(false);
    }
  };

  useEffect(() => {
    void loadProjects();
  }, [user.id]);

  useEffect(() => {
    void recoverLatestTask();
    return () => {
      taskStreamCleanupRef.current?.();
      taskStreamCleanupRef.current = null;
    };
  }, [user.id]);

  useEffect(() => {
    if (Object.keys(runningTasksBySessionId).length === 0) {
      return undefined;
    }
    const timer = window.setInterval(() => {
      void refreshRunningTaskMarkers().catch(() => {
        // 后台运行态同步失败不影响当前会话操作。
      });
    }, 5000);
    return () => window.clearInterval(timer);
  }, [runningTasksBySessionId]);

  useEffect(() => {
    if (!activeSessionId) {
      setMessages([]);
      return;
    }
    setStreamingText("");
    setStreamTools([]);
    setStreamStatus("");
    const loadMessages = async () => {
      try {
        const data = await requestMessages(user.id, activeSessionId);
        const pending = pendingLocalFailedMessageRef.current;
        setMessages(
          pending && pending.failedMessage.session_id === activeSessionId
            ? mergeLocalFailedMessage(data.items, pending.userMessage, pending.failedMessage)
            : data.items,
        );
      } catch (error) {
        setNotice(error instanceof Error ? error.message : "消息加载失败");
      }
    };
    void loadMessages();
  }, [activeSessionId, user.id]);

  const handleSelectSession = (projectId: number, sessionId: number) => {
    const runningTask = runningTasksBySessionId[sessionId];
    stopTaskStream();
    activeTaskIdRef.current = null;
    activeTaskSessionIdRef.current = null;
    setIsSending(false);
    setActiveProjectId(projectId);
    setActiveSessionId(sessionId);
    const snapshot = readWorkspaceSnapshot(user.id);
    saveWorkspaceSnapshot(user.id, {
      ...snapshot,
      activeProjectId: projectId,
      activeSessionId: sessionId,
      projectPaths: collectProjectPaths(projects, snapshot.projectPaths),
    });
    setNotice("");
    setIsMobileSidebarOpen(false);
    setIsDraftSession(false);
    pendingLocalFailedMessageRef.current = null;
    setStreamingText("");
    setStreamTools([]);
    setStreamStatus("");
    updateAiRequestState(null);
    if (runningTask) {
      void recoverTask(runningTask.taskId);
    }
  };

  const handleCreateProject = async (form: CreateProjectForm) => {
    stopTaskStream();
    activeTaskIdRef.current = null;
    activeTaskSessionIdRef.current = null;
    setIsSending(false);
    const data = await requestImportProject(user.id, form);
    saveWorkspaceSnapshot(user.id, {
      activeProjectId: data.project.id,
      activeSessionId: null,
      projectPaths: collectProjectPaths(
        [data.project],
        readWorkspaceSnapshot(user.id).projectPaths,
      ),
    });
    setIsCreateModalOpen(false);
    setIsDraftSession(true);
    setMessages([]);
    setComposerText("");
    setNotice("");
    pendingLocalFailedMessageRef.current = null;
    setStreamingText("");
    setStreamTools([]);
    setStreamStatus("");
    updateAiRequestState(null);
    await loadProjects({
      preferredProjectId: data.project.id,
      preferredSessionId: null,
      draftSession: true,
    });
  };

  const handleCreateSession = async () => {
    stopTaskStream();
    activeTaskIdRef.current = null;
    activeTaskSessionIdRef.current = null;
    setIsSending(false);
    if (!activeProjectId) {
      setIsCreateModalOpen(true);
      return;
    }
    setActiveSessionId(null);
    setMessages([]);
    setComposerText("");
    setNotice("");
    setIsDraftSession(true);
    pendingLocalFailedMessageRef.current = null;
    setStreamingText("");
    setStreamTools([]);
    setStreamStatus("");
    updateAiRequestState(null);
    setIsMobileSidebarOpen(false);
  };

  const stopTaskStream = () => {
    taskStreamCleanupRef.current?.();
    taskStreamCleanupRef.current = null;
  };

  const refreshSessionMessages = async (sessionId: number) => {
    const data = await requestMessages(user.id, sessionId);
    setMessages(data.items);
    await loadProjects(sessionId);
  };

  const finishRecoveredTask = async (
    taskId: string,
    sessionId: number | null,
    status: AgentTaskStatus,
    errorMessage?: string | null,
  ) => {
    stopTaskStream();
    if (status === "completed" || status === "failed" || status === "cancelled") {
      clearActiveTaskId(user.id, taskId);
      writeTaskIdToUrl(null);
    }
    activeTaskIdRef.current = null;
    activeTaskSessionIdRef.current = null;
    setIsSending(false);
    abortControllerRef.current = null;
    setStreamStatus("");
    setStreamTools((items) => items.map((item) => ({ ...item, status: "done" })));

    const currentAiState = aiRequestStateRef.current;
    const finalTiming = {
      ...(currentAiState?.timing ?? { requestStartAt: Date.now() }),
      requestEndAt: Date.now(),
    };
    if (status === "completed") {
      updateAiRequestState((current) =>
        current
          ? {
              ...current,
              status: "success",
              stage: "done",
              timing: finalTiming,
              metrics: calculateAiDurationMetrics(finalTiming),
            }
          : current,
      );
    }
    if (status === "cancelled" || status === "failed") {
      const aiError = normalizeAiError(
        status === "cancelled"
          ? { error_code: "USER_CANCELLED", message: "任务已停止" }
          : { message: errorMessage || "任务执行失败" },
        {
          stage: currentAiState?.stage ?? "reasoning",
          timing: finalTiming,
          metrics: calculateAiDurationMetrics(finalTiming),
          generatedPartial: Boolean(streamingTextRef.current),
          partialContent: streamingTextRef.current,
          stream: true,
          appVersion,
          platform: navigator.userAgent,
        },
      );
      updateAiRequestState({
        status: status === "cancelled" ? "cancelled" : "failed",
        stage: aiError.stage ?? currentAiState?.stage ?? "reasoning",
        error: aiError,
        timing: finalTiming,
        metrics: calculateAiDurationMetrics(finalTiming),
        partialContent: streamingTextRef.current,
        generatedPartial: Boolean(streamingTextRef.current),
        retryable: aiError.retryable,
      });
    }

    if (sessionId) {
      try {
        await refreshSessionMessages(sessionId);
        void refreshRunningTaskMarkers();
        setStreamingText("");
        setStreamTools([]);
      } catch (error) {
        setNotice(error instanceof Error ? error.message : "消息刷新失败");
      }
    }
  };

  const applyAgentTaskEvent = (
    event: AgentTaskEvent,
    sessionId: number | null,
    taskId: string,
  ) => {
    if (event.seq <= lastTaskSeqRef.current) {
      return;
    }
    lastTaskSeqRef.current = event.seq;

    if (event.event_type === "task_created" || event.event_type === "task_queued") {
      setStreamStatus("排队中");
      updateAiRequestState((current) =>
        current
          ? {
              ...current,
              status: "queued",
              stage: "queued",
            }
          : current,
      );
      return;
    }

    if (event.event_type === "task_started") {
      setStreamStatus("思考中");
      updateAiRequestState((current) =>
        current
          ? {
              ...current,
              status: "reasoning",
              stage: "reasoning",
            }
          : current,
      );
      return;
    }

    if (event.event_type === "agent_message") {
      setStreamStatus("推理中");
      const content = event.content ?? "";
      setStreamingText((value) => `${value}${content}`);
      updateAiRequestState((current) =>
        current
          ? {
              ...current,
              status: "streaming",
              stage: "streaming",
              generatedPartial: true,
              partialContent: `${streamingTextRef.current}${content}`,
            }
          : current,
      );
      return;
    }

    if (event.event_type === "tool_call") {
      setStreamStatus("执行工具");
      updateAiRequestState((current) =>
        current
          ? {
              ...current,
              status: "tool_calling",
              stage: "tool_calling",
            }
          : current,
      );
      applyToolCallEvent(event, setStreamTools);
      return;
    }

    if (event.event_type === "agent_step" || event.event_type === "command_output") {
      setStreamStatus(event.content ?? "处理中");
      setStreamTools((items) => [
        ...items,
        {
          id: `step-${event.seq}`,
          name: event.event_type === "command_output" ? "命令输出" : "执行步骤",
          category: event.event_type === "command_output" ? "terminal" : "thinking",
          status: "done",
          partial: event.content ?? "",
        },
      ]);
      return;
    }

    if (event.event_type === "task_completed") {
      void finishRecoveredTask(taskId, sessionId, "completed");
      return;
    }

    if (event.event_type === "task_failed") {
      void finishRecoveredTask(taskId, sessionId, "failed", event.content);
      return;
    }

    if (event.event_type === "task_cancelling") {
      setStreamStatus("正在停止");
      updateAiRequestState((current) =>
        current
          ? {
              ...current,
              status: "cancelled",
              stage: current.stage,
            }
          : current,
      );
      return;
    }

    if (event.event_type === "task_cancelled") {
      void finishRecoveredTask(taskId, sessionId, "cancelled", event.content);
    }
  };

  const startTaskStream = (taskId: string, sessionId: number | null) => {
    stopTaskStream();
    taskStreamCleanupRef.current = subscribeAgentTaskEvents(
      taskId,
      lastTaskSeqRef.current,
      (event) => applyAgentTaskEvent(event, sessionId, taskId),
      {
        onConnected: () => {
          updateAiRequestState((current) => {
            if (!current) {
              return current;
            }
            const timing = {
              ...current.timing,
              connectionEndAt: current.timing.connectionEndAt ?? Date.now(),
            };
            return {
              ...current,
              timing,
              metrics: calculateAiDurationMetrics(timing),
            };
          });
        },
        onReconnect: (delayMs) => {
          setStreamStatus(`连接断开，${Math.round(delayMs / 1000)} 秒后重连`);
        },
        onError: () => {
          setStreamStatus("连接恢复中");
        },
      },
    );
  };

  const recoverTask = async (taskId: string) => {
    const task = await requestAgentTask(taskId);
    const sessionId = parseConversationSessionId(task.conversation_id);
    activeTaskIdRef.current = task.task_id;
    activeTaskSessionIdRef.current = sessionId;
    lastTaskSeqRef.current = 0;
    saveActiveTaskId(user.id, task.task_id);
    writeTaskIdToUrl(task.task_id);
    setIsSending(isActiveTaskStatus(task.status));
    if (sessionId && isActiveTaskStatus(task.status)) {
      setRunningTasksBySessionId((current) =>
        upsertRunningTaskMarker(current, sessionId, {
          taskId: task.task_id,
          status: task.status,
          title: task.title,
        }),
      );
    }
    setStreamStatus(formatTaskStatus(task.status));
    setStreamingText("");
    setStreamTools([]);
    const requestStartAt = task.started_at ? Date.parse(task.started_at) : Date.now();
    updateAiRequestState({
      ...createAiRequestState(Number.isFinite(requestStartAt) ? requestStartAt : Date.now()),
      status: task.status === "queued" ? "queued" : "reasoning",
      stage: task.status === "queued" ? "queued" : "reasoning",
    });

    if (sessionId) {
      await loadProjects(sessionId);
      try {
        const data = await requestMessages(user.id, sessionId);
        setMessages(data.items);
      } catch {
        // 任务事件仍可恢复；消息列表刷新失败交给终态刷新再提示。
      }
    }

    const events = await requestAgentTaskEvents(task.task_id, 0);
    events.items.forEach((event) => applyAgentTaskEvent(event, sessionId, task.task_id));
    if (isActiveTaskStatus(task.status)) {
      startTaskStream(task.task_id, sessionId);
    } else if (
      task.status === "completed" ||
      task.status === "failed" ||
      task.status === "cancelled"
    ) {
      setRunningTasksBySessionId((current) =>
        removeRunningTaskMarker(current, sessionId, task.task_id),
      );
      clearActiveTaskId(user.id, task.task_id);
      writeTaskIdToUrl(null);
    }
  };

  const refreshRunningTaskMarkers = async () => {
    const running = await requestRunningAgentTasks();
    const markers = buildRunningTaskMarkers(running.items);
    setRunningTasksBySessionId(markers);
    return running;
  };

  const recoverLatestTask = async () => {
    const explicitTaskId = readTaskIdFromUrl() ?? readActiveTaskId(user.id);
    try {
      const running = await refreshRunningTaskMarkers();
      if (explicitTaskId) {
        await recoverTask(explicitTaskId);
        return;
      }
      const firstTask = running.items[0];
      if (firstTask) {
        setNotice("有任务正在后台运行，已为你恢复进度");
        await recoverTask(firstTask.task_id);
      }
    } catch {
      if (explicitTaskId) {
        clearActiveTaskId(user.id, explicitTaskId);
        writeTaskIdToUrl(null);
      }
    }
  };

  const handleCancelGeneration = () => {
    const taskId = activeTaskIdRef.current;
    if (taskId) {
      setStreamStatus("正在停止");
      void requestCancelAgentTask(taskId)
        .then((data) => {
          const sessionId = activeTaskSessionIdRef.current;
          if (sessionId && isActiveTaskStatus(data.status)) {
            setRunningTasksBySessionId((current) =>
              upsertRunningTaskMarker(current, sessionId, {
                taskId,
                status: data.status,
                title: runningTasksBySessionId[sessionId]?.title ?? null,
              }),
            );
          }
        })
        .catch((error) => {
          setNotice(error instanceof Error ? error.message : "停止任务失败");
        });
      return;
    }
    abortControllerRef.current?.abort();
    setStreamStatus("正在停止");
  };

  const handleSendMessage = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const nextMessage = composerText.trim();
    if (!nextMessage || isSending || (!activeSessionId && !activeProjectId)) {
      return;
    }

    setIsSending(true);
    setNotice("");
    setStreamingText("");
    setStreamTools([]);
    setStreamStatus("思考中");
    const requestStartAt = Date.now();
    updateAiRequestState({
      ...createAiRequestState(requestStartAt),
      status: "connecting",
      stage: "connecting",
      timing: {
        requestStartAt,
        connectionStartAt: requestStartAt,
      },
    });
    setRequestElapsedMs(0);
    let targetSessionId = activeSessionId;
    let optimisticUserMessage: SessionMessage | null = null;
    let taskStarted = false;
    try {
      if (!targetSessionId) {
        if (!activeProjectId) {
          return;
        }
        const session = await requestCreateSession(
          user.id,
          activeProjectId,
          summarizeSessionTitle(nextMessage),
        );
        targetSessionId = session.id;
      }
      if (!targetSessionId) {
        return;
      }
      const taskSessionId = targetSessionId;
      setComposerText("");
      const optimisticMessage: SessionMessage = {
        id: -Date.now(),
        session_id: taskSessionId,
        role: "user",
        content: nextMessage,
        status: "done",
        tool_summary: [],
        diff_summary: [],
        created_at: new Date().toISOString(),
      };
      optimisticUserMessage = optimisticMessage;
      setMessages((items) => [...items, optimisticMessage]);

      const task = await requestCreateAgentTask(
        String(taskSessionId),
        nextMessage,
        summarizeSessionTitle(nextMessage),
      );
      activeTaskIdRef.current = task.task_id;
      activeTaskSessionIdRef.current = taskSessionId;
      lastTaskSeqRef.current = 0;
      setRunningTasksBySessionId((current) =>
        upsertRunningTaskMarker(current, taskSessionId, {
          taskId: task.task_id,
          status: task.status,
          title: summarizeSessionTitle(nextMessage),
        }),
      );
      saveActiveTaskId(user.id, task.task_id);
      writeTaskIdToUrl(task.task_id);
      setStreamStatus("排队中");
      updateAiRequestState((current) =>
        current
          ? {
              ...current,
              status: "queued",
              stage: "queued",
            }
          : current,
      );

      const events = await requestAgentTaskEvents(task.task_id, 0);
      events.items.forEach((item) => applyAgentTaskEvent(item, taskSessionId, task.task_id));
      startTaskStream(task.task_id, taskSessionId);
      taskStarted = true;
      setIsDraftSession(false);
      pendingLocalFailedMessageRef.current = null;
      await loadProjects(taskSessionId);
    } catch (error) {
      const currentAiState = aiRequestStateRef.current;
      const finalTiming = {
        ...(currentAiState?.timing ?? { requestStartAt }),
        requestEndAt: Date.now(),
      };
      const metrics = calculateAiDurationMetrics(finalTiming);
      const partialContent = streamingTextRef.current;
      const aiError = normalizeAiError(error, {
        stage: currentAiState?.stage ?? "reasoning",
        timing: finalTiming,
        metrics,
        generatedPartial: Boolean(partialContent),
        partialContent,
        stream: true,
        appVersion,
        platform: navigator.userAgent,
      });
      const errorMessage = aiError.message;
      updateAiRequestState({
        status:
          aiError.errorCode === "USER_CANCELLED"
            ? "cancelled"
            : aiError.errorCode === "MODEL_TIMEOUT"
              ? "timeout"
              : "failed",
        stage: aiError.stage ?? currentAiState?.stage ?? "reasoning",
        error: aiError,
        timing: finalTiming,
        metrics,
        partialContent,
        generatedPartial: Boolean(partialContent),
        retryable: aiError.retryable,
      });
      setComposerText(nextMessage);
      if (targetSessionId) {
        const failedMessage = createLocalFailedMessage(
          targetSessionId,
          errorMessage,
          aiError,
          partialContent,
          metrics,
        );
        pendingLocalFailedMessageRef.current = {
          userMessage: optimisticUserMessage,
          failedMessage,
        };
        try {
          const data = await requestMessages(user.id, targetSessionId);
          setMessages(mergeLocalFailedMessage(data.items, optimisticUserMessage, failedMessage));
        } catch {
          setMessages((items) =>
            mergeLocalFailedMessage(items, optimisticUserMessage, failedMessage),
          );
        }
        await loadProjects(targetSessionId);
      } else {
        setNotice(errorMessage);
      }
    } finally {
      abortControllerRef.current = null;
      if (!taskStarted) {
        setIsSending(false);
        setStreamingText("");
        setStreamTools([]);
        setStreamStatus("");
      }
    }
  };

  const handleCopyQuestion = async (content: string) => {
    try {
      await copyText(content);
      setNotice("问题已复制");
    } catch {
      setNotice("复制失败，请手动选择文本复制");
    }
  };

  const handleEditQuestion = (content: string) => {
    setComposerText(content);
    setNotice("已将问题放回输入框");
    window.setTimeout(() => {
      composerTextareaRef.current?.focus();
      composerTextareaRef.current?.setSelectionRange(content.length, content.length);
    }, 0);
  };

  const handleCopyContent: CopyContentHandler = async (content, label) => {
    try {
      await copyText(redactSensitiveText(content));
      setNotice(`已复制${label}`);
    } catch {
      setNotice("复制失败，请手动选择文本复制");
    }
  };

  return (
    <main className="workspace-shell">
      <aside
        className={
          isMobileSidebarOpen ? "workspace-sidebar sidebar-open" : "workspace-sidebar"
        }
        aria-label="项目侧边栏"
      >
        <div className="window-controls" aria-hidden="true">
          <span className="control red" />
          <span className="control yellow" />
          <span className="control green" />
          <span className="control muted" />
        </div>

        <nav className="quick-nav" aria-label="快捷导航">
          <button type="button" onClick={handleCreateSession}>
            新对话
          </button>
          <button type="button" onClick={() => setNotice("搜索功能待接入")}>
            搜索
          </button>
          <button type="button" onClick={() => setNotice("暂未安排任务")}>
            已安排 <span>0</span>
          </button>
          <button type="button" onClick={() => setNotice("插件面板待接入")}>
            插件
          </button>
        </nav>

        <section className="project-section" aria-label="项目列表">
          <div className="project-list-heading">
            <p className="sidebar-label">项目</p>
            <button
              className="project-add-button"
              type="button"
              aria-label="创建项目"
              onClick={() => setIsCreateModalOpen(true)}
            >
              新增项目
            </button>
          </div>

          <div className="project-list">
            {isLoadingProjects ? <p className="sidebar-empty">项目加载中...</p> : null}
            {!isLoadingProjects && projects.length === 0 ? (
              <div className="sidebar-empty">
                <p>还没有项目</p>
                <button type="button" onClick={() => setIsCreateModalOpen(true)}>
                  创建项目
                </button>
              </div>
            ) : null}

            {projects.map((project) => (
              <section className="project-group" key={project.id}>
                <button
                  className="project-title-button"
                  type="button"
                  onClick={() => {
                    const nextSessionId = project.sessions[0]?.id ?? null;
                    const runningTask = nextSessionId
                      ? runningTasksBySessionId[nextSessionId]
                      : null;
                    setActiveProjectId(project.id);
                    setActiveSessionId(nextSessionId);
                    setIsDraftSession(!nextSessionId);
                    pendingLocalFailedMessageRef.current = null;
                    setStreamingText("");
                    setStreamTools([]);
                    setStreamStatus("");
                    updateAiRequestState(null);
                    const snapshot = readWorkspaceSnapshot(user.id);
                    saveWorkspaceSnapshot(user.id, {
                      ...snapshot,
                      activeProjectId: project.id,
                      activeSessionId: nextSessionId,
                      projectPaths: collectProjectPaths(projects, snapshot.projectPaths),
                    });
                    if (runningTask) {
                      void recoverTask(runningTask.taskId);
                    }
                  }}
                >
                  <h2>{project.name}</h2>
                  <small>{project.is_git_repo ? "Git" : "本地"}</small>
                </button>
                <div className="thread-list">
                  {project.sessions.map((item) => {
                    const runningTask = runningTasksBySessionId[item.id];
                    return (
                      <button
                        className={
                          item.id === activeSessionId ? "thread-item active" : "thread-item"
                        }
                        key={item.id}
                        type="button"
                        onClick={() => handleSelectSession(project.id, item.id)}
                      >
                        <span className="thread-title">{item.title}</span>
                        <span className="thread-meta">
                          {runningTask ? (
                            <span
                              className="thread-running-spinner"
                              aria-label="正在推理"
                              title="正在推理"
                            />
                          ) : (
                            <small>{formatSessionTime(item.updated_at)}</small>
                          )}
                        </span>
                      </button>
                    );
                  })}
                </div>
              </section>
            ))}
          </div>
        </section>

        <div className="sidebar-account">
          <div className="account-avatar">{getInitials(user.user_name)}</div>
          <div>
            <strong>{user.user_name}</strong>
            <span>ID {user.id}</span>
          </div>
        </div>
      </aside>

      <section className="workspace-main" aria-label="会话详情">
        <header className="workspace-topbar">
          <div className="conversation-title">
            <button
              className="sidebar-toggle"
              type="button"
              aria-label="切换侧边栏"
              onClick={() => setIsMobileSidebarOpen((value) => !value)}
            >
              ☰
            </button>
            <span className="title-icon">▣</span>
            <h1>
              {activeSession?.title ??
                (isDraftSession ? "新会话" : activeProject?.name) ??
                "项目工作台"}
            </h1>
            <button type="button" aria-label="创建项目" onClick={() => setIsCreateModalOpen(true)}>
              ···
            </button>
          </div>
          <div className="topbar-actions">
            <button
              type="button"
              onClick={() =>
                setNotice(activeProject?.display_path ?? "浏览器目录选择不会暴露绝对路径")
              }
            >
              打开位置
            </button>
            <button type="button" onClick={() => setNotice("视图切换待接入")}>
              ☷
            </button>
            <button type="button" onClick={onLogout}>
              退出
            </button>
          </div>
        </header>

        <div className="conversation-scroll">
          {activeProject && canCompose && !hasConversationContent ? (
            <EmptyProjectPrompt
              project={activeProject}
              activeSession={activeSession}
              canCompose={canCompose}
              composerText={composerText}
              isSending={isSending}
              onChange={setComposerText}
              onSubmit={handleSendMessage}
              textareaRef={composerTextareaRef}
              notice={notice}
              onModeClick={() => setNotice("审批模式待接入")}
            />
          ) : (
            <article className="assistant-message">
              {!activeProject ? <EmptyWorkspace onCreate={() => setIsCreateModalOpen(true)} /> : null}

              {notice ? <p className="mock-status">{notice}</p> : null}

              {messages.length > 0 ? (
                <div className="local-message-list">
                  {messages.map((item) => (
                    <MessageBubble
                      key={item.id}
                      message={item}
                      onCopyContent={handleCopyContent}
                      onCopyQuestion={handleCopyQuestion}
                      onEditQuestion={handleEditQuestion}
                      onShowNotice={setNotice}
                    />
                  ))}
                  {isSending || streamingText || streamTools.length > 0 ? (
                    <StreamingMessage
                      aiRequestState={aiRequestState}
                      content={streamingText}
                      elapsedMs={requestElapsedMs}
                      onCancel={handleCancelGeneration}
                      onCopyContent={handleCopyContent}
                      statusLabel={streamStatus}
                      tools={streamTools}
                    />
                  ) : null}
                </div>
              ) : activeProject && hasConversationContent ? (
                <div className="local-message-list">
                  <StreamingMessage
                    aiRequestState={aiRequestState}
                    content={streamingText}
                    elapsedMs={requestElapsedMs}
                    onCancel={handleCancelGeneration}
                    onCopyContent={handleCopyContent}
                    statusLabel={streamStatus}
                    tools={streamTools}
                  />
                </div>
              ) : null}
            </article>
          )}
        </div>

        {hasConversationContent ? (
          <footer className="composer-wrap">
            <div className="message-actions" aria-hidden="true">
              <span>□</span>
              <span>♡</span>
              <span>↗</span>
              <span>{new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
            </div>
            <PromptComposer
              activeSession={activeSession}
              canCompose={canCompose}
              composerText={composerText}
              isSending={isSending}
              placeholder={canCompose ? "要求后续变更" : "请先创建或选择项目会话"}
              onChange={setComposerText}
              onSubmit={handleSendMessage}
              textareaRef={composerTextareaRef}
              onModeClick={() => setNotice("审批模式待接入")}
            />
          </footer>
        ) : null}
      </section>

      {isCreateModalOpen ? (
        <CreateProjectModal
          onClose={() => setIsCreateModalOpen(false)}
          onCreate={handleCreateProject}
        />
      ) : null}

      <div className="window-corner-actions" aria-hidden="true">
        <span />
        <span />
      </div>
    </main>
  );
}

function EmptyProjectPrompt({
  project,
  activeSession,
  canCompose,
  composerText,
  isSending,
  notice,
  onChange,
  onSubmit,
  textareaRef,
  onModeClick,
}: {
  project: Project;
  activeSession: ProjectSession | null;
  canCompose: boolean;
  composerText: string;
  isSending: boolean;
  notice: string;
  onChange: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  textareaRef: RefObject<HTMLTextAreaElement>;
  onModeClick: () => void;
}) {
  return (
    <section className="empty-project-prompt" aria-label="新会话输入">
      <div className="empty-prompt-inner">
        <h2>我们应该在 {project.name} 中构建什么？</h2>
        <PromptComposer
          activeSession={activeSession}
          canCompose={canCompose}
          composerText={composerText}
          isSending={isSending}
          placeholder="随心输入"
          onChange={onChange}
          onSubmit={onSubmit}
          textareaRef={textareaRef}
          onModeClick={onModeClick}
        />
        <div className="project-context-bar" aria-label="项目上下文">
          <span>▦ {project.name}</span>
          <span>▱ 本地模式⌄</span>
          <span>⌘ main⌄</span>
        </div>
        {notice ? <p className="mock-status">{notice}</p> : null}
      </div>
    </section>
  );
}

function PromptComposer({
  activeSession,
  canCompose,
  composerText,
  isSending,
  placeholder,
  onChange,
  onSubmit,
  textareaRef,
  onModeClick,
}: {
  activeSession: ProjectSession | null;
  canCompose: boolean;
  composerText: string;
  isSending: boolean;
  placeholder: string;
  onChange: (value: string) => void;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
  textareaRef: RefObject<HTMLTextAreaElement>;
  onModeClick: () => void;
}) {
  const canUseComposer = Boolean(activeSession || canCompose);
  const handleKeyDown = (event: KeyboardEvent<HTMLTextAreaElement>) => {
    if (event.key !== "Enter" || event.shiftKey || event.nativeEvent.isComposing) {
      return;
    }
    event.preventDefault();
    event.currentTarget.form?.requestSubmit();
  };

  return (
    <form className="composer" onSubmit={onSubmit}>
      <textarea
        ref={textareaRef}
        placeholder={placeholder}
        rows={3}
        value={composerText}
        disabled={!canUseComposer}
        onChange={(event) => onChange(event.target.value)}
        onKeyDown={handleKeyDown}
      />
      <div className="composer-toolbar">
        <button type="button" onClick={() => onChange(`${composerText}+ `)}>
          ＋
        </button>
        <button type="button" onClick={onModeClick}>
          替我审批⌄
        </button>
        <span>5.5 中⌄</span>
        <button
          type="submit"
          aria-label="发送"
          disabled={!composerText.trim() || !canUseComposer || isSending}
        >
          {isSending ? "…" : "↑"}
        </button>
      </div>
    </form>
  );
}

function EmptyWorkspace({ onCreate }: { onCreate: () => void }) {
  return (
    <div className="empty-workspace">
      <h2>创建项目</h2>
      <p>导入一个本地文件夹后，就可以在项目下创建多个会话。</p>
      <button type="button" onClick={onCreate}>
        使用现有文件夹
      </button>
    </div>
  );
}

function getToolCategory(name: string): ToolCategory {
  const normalized = name.toLowerCase();
  if (normalized.includes("bash") || normalized.includes("shell") || normalized.includes("command")) {
    return "terminal";
  }
  if (
    normalized.includes("read") ||
    normalized.includes("write") ||
    normalized.includes("edit") ||
    normalized.includes("file") ||
    normalized.includes("patch")
  ) {
    return "file";
  }
  if (
    normalized.includes("grep") ||
    normalized.includes("glob") ||
    normalized.includes("search") ||
    normalized.includes("find")
  ) {
    return "search";
  }
  if (normalized.includes("mcp")) {
    return "mcp";
  }
  return "tool";
}

function isTerminalTaskEvent(eventType: string) {
  return eventType === "task_completed" || eventType === "task_failed" || eventType === "task_cancelled";
}

function formatTaskStatus(status: AgentTaskStatus) {
  const labels: Record<AgentTaskStatus, string> = {
    created: "已创建",
    queued: "排队中",
    running: "执行中",
    completed: "已完成",
    failed: "执行失败",
    cancelling: "正在停止",
    cancelled: "已停止",
  };
  return labels[status];
}

function applyToolCallEvent(
  event: AgentTaskEvent,
  setTools: (updater: (items: ToolStatus[]) => ToolStatus[]) => void,
) {
  const metadataType = String(event.metadata.type ?? "");
  const id = String(event.metadata.id ?? `tool-${event.seq}`);
  const name = String(event.metadata.name ?? "tool");

  if (metadataType === "tool_start") {
    setTools((items) => [
      ...items,
      {
        id,
        name,
        category: getToolCategory(name),
        status: "running",
        partial: summarizeToolPayload(event.metadata.input),
      },
    ]);
    return;
  }

  if (metadataType === "tool_delta") {
    const partial = String(event.metadata.partial ?? event.content ?? "");
    setTools((items) =>
      items.map((item) =>
        item.id === id ? { ...item, partial: `${item.partial}${partial}`.slice(-240) } : item,
      ),
    );
    return;
  }

  if (metadataType === "tool_done") {
    setTools((items) =>
      items.map((item) => (item.id === id ? { ...item, status: "done" } : item)),
    );
    return;
  }

  setTools((items) => [
    ...items,
    {
      id,
      name,
      category: getToolCategory(name),
      status: "done",
      partial: event.content ?? summarizeToolPayload(event.metadata),
    },
  ]);
}

function normalizeAiStage(value: unknown): AiRequestStage | null {
  if (typeof value !== "string") {
    return null;
  }
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
  return stages.includes(value as AiRequestStage) ? (value as AiRequestStage) : null;
}

function formatAiActionLabel(action: AiErrorAction, errorCode: string) {
  if (action === "retry_connection") {
    return "重试连接";
  }
  if (action === "retry") {
    if (errorCode === "TOOL_CALL_FAILED") {
      return "重新执行";
    }
    if (errorCode === "MODEL_BUSY") {
      return "稍后重试";
    }
    return "重新生成";
  }
  const labels: Record<Exclude<AiErrorAction, "retry_connection" | "retry">, string> = {
    switch_model: "切换模型",
    open_settings: "去配置",
    shorten_input: "缩短输入",
    cancel: "停止生成",
    copy_error: "复制错误",
    copy_diagnostic: "复制诊断",
    copy_partial_content: "复制已生成内容",
    view_detail: "查看详情",
  };
  return labels[action];
}

function resolveAiActionFallback(action: AiErrorAction) {
  const messages: Record<AiErrorAction, string> = {
    retry: "请确认输入内容后重新发送",
    retry_connection: "请确认输入内容后重新发送",
    switch_model: "模型切换入口待接入",
    open_settings: "配置入口待接入",
    shorten_input: "请缩短输入内容后重新发送",
    cancel: "任务停止入口待接入",
    copy_error: "错误信息已复制",
    copy_diagnostic: "诊断详情已复制",
    copy_partial_content: "已生成内容已复制",
    view_detail: "详情已展开",
  };
  return messages[action];
}

function normalizeToolSummary(items: Record<string, unknown>[]): ToolStatus[] {
  const ordered: ToolStatus[] = [];
  const byId = new Map<string, ToolStatus>();
  items.forEach((item, index) => {
    const name = String(item.name ?? item.tool ?? "tool");
    const id = String(item.id ?? `${name}-${index}`);
    const type = String(item.type ?? "");
    let current = byId.get(id);
    if (!current) {
      current = {
        id,
        name,
        category: getToolCategory(name),
        status: "done",
        partial: "",
      };
      byId.set(id, current);
      ordered.push(current);
    }

    if (type === "tool_start") {
      current.status = "running";
      current.partial = summarizeToolPayload(item.input) || current.partial;
    }
    if (type === "tool_delta") {
      current.partial = `${current.partial}${String(item.partial ?? "")}`.slice(-220);
    }
    if (type === "tool_done") {
      current.status = "done";
    }
    if (!type) {
      current.partial = summarizeToolPayload(item) || current.partial;
    }
  });
  return ordered.map((item) => ({ ...item, status: "done" }));
}

function summarizeToolPayload(value: unknown): string {
  if (!value) {
    return "";
  }
  const text = typeof value === "string" ? value : JSON.stringify(value);
  return text.length > 220 ? `${text.slice(0, 220)}...` : text;
}

function MessageBubble({
  message,
  onCopyContent,
  onCopyQuestion,
  onEditQuestion,
  onShowNotice,
}: {
  message: SessionMessage;
  onCopyContent: CopyContentHandler;
  onCopyQuestion: (content: string) => void;
  onEditQuestion: (content: string) => void;
  onShowNotice: (content: string) => void;
}) {
  const isAssistant = message.role === "assistant";
  const toolItems = normalizeToolSummary(message.tool_summary);
  const displayContent = normalizeMessageContent(message.content);
  const aiError =
    message.status === "failed"
      ? (message.ai_error ?? normalizeAiError({ message: displayContent, stage: "reasoning" }))
      : undefined;
  return (
    <div className={isAssistant ? "message-bubble assistant" : "message-bubble user"}>
      {isAssistant ? (
        <>
          {message.status === "failed" ? (
            <AiErrorCard
              error={aiError}
              generatedPartial={message.generated_partial}
              metrics={message.ai_metrics}
              onActionNotice={onShowNotice}
              onCopyContent={onCopyContent}
              onRetry={() => onShowNotice("请确认输入内容后重新发送")}
              partialContent={message.partial_content}
            />
          ) : null}
          {message.status === "failed" ? null : (
            <ProcessSummary
              copyContent={displayContent}
              copyLabel="回复正文"
              durationLabel={formatProcessDuration(message.diff_summary)}
              onCopyContent={onCopyContent}
              state="done"
              toolCount={toolItems.length}
            />
          )}
          {toolItems.length > 0 ? (
            <ToolStepList onCopyContent={onCopyContent} tools={toolItems} />
          ) : null}
          {message.status === "failed" ? null : (
            <AssistantContent content={displayContent} onCopyContent={onCopyContent} />
          )}
        </>
      ) : (
        <UserQuestionMessage
          message={message}
          onCopyQuestion={onCopyQuestion}
          onEditQuestion={onEditQuestion}
        />
      )}
    </div>
  );
}

function normalizeMessageContent(content: string) {
  if (content === "会话正在运行") {
    return "上次推理已中断，请重新发送。";
  }
  return content;
}

function AiErrorCard({
  error,
  generatedPartial,
  metrics,
  onActionNotice,
  onCopyContent,
  onRetry,
  partialContent,
}: {
  error?: AiRequestError;
  generatedPartial?: boolean;
  metrics?: AiDurationMetrics;
  onActionNotice: (content: string) => void;
  onCopyContent: CopyContentHandler;
  onRetry?: () => void;
  partialContent?: string;
}) {
  const [isDetailOpen, setIsDetailOpen] = useState(false);
  const resolvedError = error ?? normalizeAiError("推理失败，请稍后重试");
  const actions = resolveAiErrorActions(resolvedError);
  const context = {
    generatedPartial: Boolean(generatedPartial && partialContent),
    partialContent: partialContent ?? "",
    stream: true,
    appVersion,
    platform: navigator.userAgent,
  };

  const runAction = (action: AiErrorAction) => {
    if (action === "copy_error") {
      copyAssistantContent(
        onCopyContent,
        buildAiErrorSummaryText(resolvedError),
        "错误信息",
      );
      return;
    }
    if (action === "copy_diagnostic") {
      copyAssistantContent(
        onCopyContent,
        buildAiDiagnosticText({ error: resolvedError, metrics, context }),
        "诊断详情",
      );
      return;
    }
    if (action === "copy_partial_content" && partialContent) {
      copyAssistantContent(onCopyContent, partialContent, "已生成内容");
      return;
    }
    if (action === "copy_partial_content") {
      onActionNotice("暂无已生成内容可复制");
      return;
    }
    if (action === "view_detail") {
      setIsDetailOpen((value) => !value);
      return;
    }
    if ((action === "retry" || action === "retry_connection") && onRetry) {
      onRetry();
      return;
    }
    onActionNotice(resolveAiActionFallback(action));
  };

  return (
    <section
      className={
        resolvedError.errorCode === "USER_CANCELLED" ? "ai-error-card neutral" : "ai-error-card"
      }
      aria-label="AI 异常提示"
    >
      <header>
        <div>
          <strong>{resolvedError.title}</strong>
          <p>{resolvedError.message}</p>
        </div>
        {resolvedError.durationMs !== undefined ? (
          <span>{formatAiDuration(resolvedError.durationMs)}</span>
        ) : null}
      </header>

      {generatedPartial && partialContent ? (
        <p className="ai-partial-notice">连接中断，以下内容可能不完整。</p>
      ) : null}

      {generatedPartial && partialContent ? (
        <div className="ai-partial-content">
          <AssistantContent content={partialContent} onCopyContent={onCopyContent} />
        </div>
      ) : null}

      <div className="ai-error-actions">
        {actions.map((action) => (
          <button key={action} type="button" onClick={() => runAction(action)}>
            {formatAiActionLabel(action, resolvedError.errorCode)}
          </button>
        ))}
        <button type="button" onClick={() => runAction("copy_diagnostic")}>
          复制诊断
        </button>
      </div>

      {isDetailOpen ? (
        <pre className="ai-error-detail">
          {buildAiDiagnosticText({ error: resolvedError, metrics, context })}
        </pre>
      ) : null}
    </section>
  );
}

function UserQuestionMessage({
  message,
  onCopyQuestion,
  onEditQuestion,
}: {
  message: SessionMessage;
  onCopyQuestion: (content: string) => void;
  onEditQuestion: (content: string) => void;
}) {
  return (
    <>
      <div className="user-question">
        <p>{message.content}</p>
      </div>
      <div className="user-message-meta" aria-label="用户消息操作">
        <time dateTime={message.created_at ?? undefined}>
          {formatMessageTime(message.created_at)}
        </time>
        <button
          className="user-action-button"
          type="button"
          aria-label="复制问题"
          onClick={() => onCopyQuestion(message.content)}
        >
          <span className="user-action-icon copy" aria-hidden="true" />
        </button>
        <button
          className="user-action-button"
          type="button"
          aria-label="修改问题"
          onClick={() => onEditQuestion(message.content)}
        >
          <span className="user-action-icon edit" aria-hidden="true" />
        </button>
      </div>
    </>
  );
}

function StreamingMessage({
  aiRequestState,
  content,
  elapsedMs,
  onCancel,
  onCopyContent,
  statusLabel,
  tools,
}: {
  aiRequestState: AiRequestState | null;
  content: string;
  elapsedMs: number;
  onCancel: () => void;
  onCopyContent: CopyContentHandler;
  statusLabel: string;
  tools: ToolStatus[];
}) {
  const stage = aiRequestState?.stage ?? "connecting";
  const durationLabel = formatAiDuration(elapsedMs);
  const isSlow = elapsedMs >= AI_TIMEOUT_CONFIG.chat.slowHintMs;
  const isLongSlow = elapsedMs >= AI_TIMEOUT_CONFIG.chat.longSlowHintMs;
  const currentStatus =
    statusLabel || (stage === "connecting" ? "正在连接 AI 服务" : formatAiStage(stage));
  return (
    <div className="message-bubble assistant streaming">
      <ProcessSummary
        copyContent={content}
        copyLabel="回复正文"
        onCopyContent={content ? onCopyContent : undefined}
        statusLabel={`${currentStatus} · 已耗时 ${durationLabel}`}
        state="running"
        toolCount={tools.length}
      />
      {isSlow ? (
        <AiSlowHint
          durationLabel={durationLabel}
          isLongSlow={isLongSlow}
          stage={stage}
          onCancel={onCancel}
        />
      ) : (
        <AiLoadingIndicator
          durationLabel={durationLabel}
          stage={stage}
          onCancel={onCancel}
        />
      )}
      {tools.length > 0 ? <ToolStepList onCopyContent={onCopyContent} tools={tools} /> : null}
      {!content && tools.length === 0 ? (
        <p className="stream-hint">
          正在连接推理服务，后端会返回连接状态和执行结果。
        </p>
      ) : null}
      {content ? <AssistantContent content={content} onCopyContent={onCopyContent} /> : null}
    </div>
  );
}

function AiLoadingIndicator({
  durationLabel,
  onCancel,
  stage,
}: {
  durationLabel: string;
  onCancel: () => void;
  stage: AiRequestStage;
}) {
  return (
    <div className="ai-status-hint">
      <span>{formatAiStage(stage)}</span>
      <span>已耗时 {durationLabel}</span>
      <button type="button" onClick={onCancel}>
        停止生成
      </button>
    </div>
  );
}

function AiSlowHint({
  durationLabel,
  isLongSlow,
  onCancel,
  stage,
}: {
  durationLabel: string;
  isLongSlow: boolean;
  onCancel: () => void;
  stage: AiRequestStage;
}) {
  return (
    <div className="ai-slow-hint">
      <div>
        <strong>{isLongSlow ? "AI 正在处理中，耗时较长" : "AI 正在思考..."}</strong>
        <p>
          当前阶段：{formatAiStage(stage)}，已耗时 {durationLabel}。
        </p>
      </div>
      <button type="button" onClick={onCancel}>
        停止生成
      </button>
    </div>
  );
}

function ToolStepList({
  onCopyContent,
  tools,
}: {
  onCopyContent: CopyContentHandler;
  tools: ToolStatus[];
}) {
  const copyValue = tools.map(formatToolStepForCopy).join("\n\n");
  return (
    <div className="tool-step-list" aria-label="推理步骤">
      <div className="assistant-copy-row">
        <CopyButton
          label="复制步骤"
          onClick={() => copyAssistantContent(onCopyContent, copyValue, "步骤")}
        />
      </div>
      {tools.map((tool, index) => (
        <div className="tool-step-item" key={`${tool.id}-${index}`}>
          <span
            className={tool.status === "running" ? "tool-step-dot running" : "tool-step-dot"}
            aria-hidden="true"
          />
          <div>
            <header>
              <strong>{tool.name}</strong>
              <span className="tool-step-status">
                {tool.status === "running" ? "运行中" : "完成"}
              </span>
            </header>
            {tool.partial ? <p>{tool.partial}</p> : null}
          </div>
        </div>
      ))}
    </div>
  );
}

function ProcessSummary({
  copyContent,
  copyLabel,
  durationLabel,
  onCopyContent,
  statusLabel,
  state,
  toolCount,
}: {
  copyContent?: string;
  copyLabel?: string;
  durationLabel?: string;
  onCopyContent?: CopyContentHandler;
  statusLabel?: string;
  state: "running" | "done";
  toolCount: number;
}) {
  const label =
    state === "running"
      ? statusLabel || (toolCount > 0 ? `处理中 ${toolCount} 步` : "处理中")
      : durationLabel
        ? `已处理 ${durationLabel}`
        : "已处理";
  return (
    <div className="process-summary" aria-label="推理执行状态">
      <strong>{label}</strong>
      <span className="process-chevron" aria-hidden="true">›</span>
      {onCopyContent && copyContent ? (
        <CopyButton
          label="复制回复"
          onClick={() =>
            copyAssistantContent(onCopyContent, copyContent, copyLabel ?? "回复正文")
          }
        />
      ) : null}
    </div>
  );
}

function AssistantContent({
  content,
  onCopyContent,
}: {
  content: string;
  onCopyContent: CopyContentHandler;
}) {
  const blocks = parseAssistantContent(content);
  return (
    <div className="assistant-content">
      {blocks.map((block, index) =>
        block.type === "code" ? (
          <CodeResultBlock
            content={block.content}
            key={`code-${index}`}
            language={block.language}
            onCopyContent={onCopyContent}
          />
        ) : (
          <TextResultBlock
            content={block.content}
            key={`text-${index}`}
            onCopyContent={onCopyContent}
          />
        ),
      )}
    </div>
  );
}

function TextResultBlock({
  content,
  onCopyContent,
}: {
  content: string;
  onCopyContent: CopyContentHandler;
}) {
  const blocks = parseTextLineBlocks(content);
  return (
    <>
      {blocks.map((block, index) =>
        block.type === "heading" ? (
          <h3
            className={`assistant-heading level-${block.level}`}
            key={`heading-${index}`}
          >
            {renderInlineRichText(block.content, `${index}`, onCopyContent)}
          </h3>
        ) : block.type === "quote" ? (
          <blockquote className="assistant-quote" key={`quote-${index}`}>
            {renderInlineRichText(block.content, `${index}`, onCopyContent)}
          </blockquote>
        ) : block.type === "list" ? (
          <ListResultBlock block={block} index={index} onCopyContent={onCopyContent} />
        ) : block.type === "table" ? (
          <AssistantTableBlock
            block={block}
            key={`table-${index}`}
            onCopyContent={onCopyContent}
          />
        ) : block.type === "workflow" ? (
          <WorkflowCardBlock
            block={block}
            key={`workflow-${index}`}
            onCopyContent={onCopyContent}
          />
        ) : (
          <p className="assistant-paragraph" key={`paragraph-${index}`}>
            {renderInlineRichText(block.content, `${index}`, onCopyContent)}
          </p>
        ),
      )}
    </>
  );
}

function ListResultBlock({
  block,
  index,
  onCopyContent,
}: {
  block: Extract<TextLineBlock, { type: "list" }>;
  index: number;
  onCopyContent: CopyContentHandler;
}) {
  const ListTag = block.ordered ? "ol" : "ul";
  return (
    <ListTag
      className={block.checklist ? "assistant-list assistant-checklist" : "assistant-list"}
      key={`list-${index}`}
    >
      {block.items.map((item, itemIndex) => (
        <li key={`${index}-${itemIndex}`}>
          {block.checklist ? (
            <span
              className={item.checked ? "checkmark checked" : "checkmark"}
              aria-hidden="true"
            />
          ) : null}
          <span>{renderInlineRichText(item.content, `${index}-${itemIndex}`, onCopyContent)}</span>
        </li>
      ))}
    </ListTag>
  );
}

function AssistantTableBlock({
  block,
  onCopyContent,
}: {
  block: Extract<TextLineBlock, { type: "table" }>;
  onCopyContent: CopyContentHandler;
}) {
  return (
    <div className="assistant-table-wrap">
      <div className="assistant-copy-row">
        <CopyButton
          label="复制表格"
          onClick={() => copyAssistantContent(onCopyContent, formatTableForCopy(block), "表格")}
        />
      </div>
      <table className="assistant-table">
        <thead>
          <tr>
            {block.headers.map((header, index) => (
              <th key={index}>
                {renderInlineRichText(header, `head-${index}`, onCopyContent)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {block.rows.map((row, rowIndex) => (
            <tr key={rowIndex}>
              {block.headers.map((_, cellIndex) => (
                <td key={cellIndex}>
                  {renderInlineRichText(
                    row[cellIndex] ?? "",
                    `${rowIndex}-${cellIndex}`,
                    onCopyContent,
                  )}
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

function WorkflowCardBlock({
  block,
  onCopyContent,
}: {
  block: Extract<TextLineBlock, { type: "workflow" }>;
  onCopyContent: CopyContentHandler;
}) {
  return (
    <section className="workflow-card">
      <header>
        <span className="workflow-card-dot" aria-hidden="true" />
        <strong>{block.title}</strong>
        <CopyButton
          label="复制卡片"
          onClick={() => copyAssistantContent(onCopyContent, formatWorkflowForCopy(block), "卡片")}
        />
      </header>
      <ul>
        {block.items.map((item, index) => (
          <li key={index}>
            <span
              className={item.checked ? "checkmark checked" : "checkmark"}
              aria-hidden="true"
            />
            <span>{renderInlineRichText(item.content, `workflow-${index}`, onCopyContent)}</span>
          </li>
        ))}
      </ul>
    </section>
  );
}

function CodeResultBlock({
  content,
  language,
  onCopyContent,
}: {
  content: string;
  language: string;
  onCopyContent: CopyContentHandler;
}) {
  return (
    <figure className="result-code-block">
      <figcaption>
        <span>{language || "text"}</span>
        <CopyButton
          label="复制代码"
          onClick={() => copyAssistantContent(onCopyContent, content, "代码")}
        />
      </figcaption>
      <pre>{content}</pre>
    </figure>
  );
}

function parseAssistantContent(content: string): AssistantContentBlock[] {
  const blocks: AssistantContentBlock[] = [];
  const pattern = /```([^\n`]*)\n?([\s\S]*?)```/g;
  let cursor = 0;
  let match: RegExpExecArray | null;

  while ((match = pattern.exec(content)) !== null) {
    const text = content.slice(cursor, match.index);
    if (text.trim()) {
      blocks.push({ type: "text", content: text });
    }
    blocks.push({
      type: "code",
      language: match[1]?.trim() || "text",
      content: match[2].replace(/\n$/, ""),
    });
    cursor = match.index + match[0].length;
  }

  const rest = content.slice(cursor);
  if (rest.trim()) {
    blocks.push({ type: "text", content: rest });
  }

  return blocks.length > 0 ? blocks : [{ type: "text", content }];
}

function parseTextLineBlocks(content: string): TextLineBlock[] {
  const blocks: TextLineBlock[] = [];
  const paragraphLines: string[] = [];
  const listItems: TextListItem[] = [];
  let listOrdered = false;
  let listChecklist = false;
  let workflowTitle: string | null = null;
  let workflowItems: TextListItem[] = [];

  const flushParagraph = () => {
    const text = paragraphLines.join(" ").replace(/\s+/g, " ").trim();
    if (text) {
      blocks.push({ type: "paragraph", content: text });
    }
    paragraphLines.length = 0;
  };
  const flushList = () => {
    if (listItems.length > 0) {
      blocks.push({
        type: "list",
        ordered: listOrdered,
        checklist: listChecklist,
        items: [...listItems],
      });
    }
    listItems.length = 0;
    listOrdered = false;
    listChecklist = false;
  };
  const flushWorkflow = () => {
    if (workflowTitle) {
      blocks.push({
        type: "workflow",
        title: workflowTitle,
        items:
          workflowItems.length > 0
            ? [...workflowItems]
            : [{ content: "等待后续执行记录", checked: false }],
      });
    }
    workflowTitle = null;
    workflowItems = [];
  };
  const flushAll = () => {
    flushParagraph();
    flushList();
    flushWorkflow();
  };

  const lines = content.replace(/\r\n/g, "\n").split("\n");
  let lineIndex = 0;
  while (lineIndex < lines.length) {
    const line = lines[lineIndex];
    const trimmed = line.trim();

    if (!trimmed) {
      if (workflowTitle && workflowItems.length === 0) {
        lineIndex += 1;
        continue;
      }
      flushAll();
      lineIndex += 1;
      continue;
    }

    const workflow = trimmed.match(/^\[(.+(?:Card|卡片))\]$/i);
    if (workflow) {
      flushAll();
      workflowTitle = workflow[1].trim();
      lineIndex += 1;
      continue;
    }

    const tableRows: string[] = [];
    if (isMarkdownTableRow(trimmed) && isMarkdownTableSeparator(lines[lineIndex + 1]?.trim())) {
      flushAll();
      tableRows.push(trimmed);
      lineIndex += 2;
      while (lineIndex < lines.length && isMarkdownTableRow(lines[lineIndex].trim())) {
        tableRows.push(lines[lineIndex].trim());
        lineIndex += 1;
      }
      const [headerLine, ...bodyLines] = tableRows;
      blocks.push({
        type: "table",
        headers: parseMarkdownTableCells(headerLine),
        rows: bodyLines.map(parseMarkdownTableCells),
      });
      continue;
    }

    const heading = trimmed.match(/^(#{1,3})\s+(.+)$/);
    if (heading) {
      flushAll();
      blocks.push({
        type: "heading",
        level: heading[1].length,
        content: heading[2].trim(),
      });
      lineIndex += 1;
      continue;
    }

    const quote = trimmed.match(/^>\s+(.+)$/);
    if (quote) {
      flushAll();
      blocks.push({ type: "quote", content: quote[1].trim() });
      lineIndex += 1;
      continue;
    }

    const checklist = trimmed.match(/^[-*]\s+\[([ xX])\]\s+(.+)$/);
    if (checklist) {
      flushParagraph();
      if (workflowTitle) {
        workflowItems.push({
          content: checklist[2].trim(),
          checked: checklist[1].toLowerCase() === "x",
        });
      } else {
        listChecklist = true;
        listOrdered = false;
        listItems.push({
          content: checklist[2].trim(),
          checked: checklist[1].toLowerCase() === "x",
        });
      }
      lineIndex += 1;
      continue;
    }

    const bullet = trimmed.match(/^([-*•]|\d+[.)])\s+(.+)$/);
    if (bullet) {
      flushParagraph();
      const ordered = /^\d/.test(bullet[1]);
      if (workflowTitle) {
        workflowItems.push({ content: bullet[2].trim(), checked: true });
      } else {
        if (listItems.length > 0 && listOrdered !== ordered) {
          flushList();
        }
        listOrdered = ordered;
        listItems.push({ content: bullet[2].trim() });
      }
      lineIndex += 1;
      continue;
    }

    if (listItems.length > 0 && /^\s+/.test(line)) {
      listItems[listItems.length - 1].content = `${listItems[listItems.length - 1].content} ${trimmed}`;
      lineIndex += 1;
      continue;
    }

    if (workflowTitle && !/^\[.+\]$/.test(trimmed)) {
      workflowItems.push({ content: trimmed, checked: false });
      lineIndex += 1;
      continue;
    }

    flushList();
    paragraphLines.push(trimmed);
    lineIndex += 1;
  }

  flushAll();

  return blocks.length > 0 ? blocks : [{ type: "paragraph", content: content.trim() }];
}

function isMarkdownTableRow(line: string | undefined) {
  return Boolean(line && line.includes("|") && /^\|?.+\|.+\|?$/.test(line));
}

function isMarkdownTableSeparator(line: string | undefined) {
  return Boolean(line && /^\|?\s*:?-{3,}:?\s*(\|\s*:?-{3,}:?\s*)+\|?$/.test(line));
}

function parseMarkdownTableCells(line: string) {
  return line
    .replace(/^\|/, "")
    .replace(/\|$/, "")
    .split("|")
    .map((cell) => cell.trim());
}

function renderInlineRichText(
  text: string,
  keyPrefix: string,
  onCopyContent?: CopyContentHandler,
) {
  const parts = text
    .split(/(`[^`]+`|\*\*[^*]+\*\*|\[[^\]]+\]\([^)]+\)|(?:[\w.@-]+\/)+[\w.@-]+(?:\s+\(line\s+\d+\))?)/g)
    .filter(Boolean);
  return parts.map((part, index) => {
    if (part.startsWith("`") && part.endsWith("`")) {
      return (
        <code className="result-inline-code" key={`${keyPrefix}-${index}`}>
          {part.slice(1, -1)}
        </code>
      );
    }
    if (part.startsWith("**") && part.endsWith("**")) {
      return (
        <strong className="result-inline-strong" key={`${keyPrefix}-${index}`}>
          {part.slice(2, -2)}
        </strong>
      );
    }
    const markdownLink = part.match(/^\[([^\]]+)\]\(([^)]+)\)$/);
    if (markdownLink) {
      return (
        <span className="result-file-reference" key={`${keyPrefix}-${index}`}>
          <a
            className="result-file-link"
            href={markdownLink[2]}
            rel="noreferrer"
            target="_blank"
          >
            {markdownLink[1]}
          </a>
          {onCopyContent ? (
            <CopyButton
              label="复制引用"
              onClick={() =>
                copyAssistantContent(
                  onCopyContent,
                  formatMarkdownLinkForCopy(markdownLink[1], markdownLink[2]),
                  "引用",
                )
              }
            />
          ) : null}
        </span>
      );
    }
    if (/^(?:[\w.@-]+\/)+[\w.@-]+(?:\s+\(line\s+\d+\))?$/.test(part)) {
      return (
        <span className="result-file-reference" key={`${keyPrefix}-${index}`}>
          <span className="result-file-link">{part}</span>
          {onCopyContent ? (
            <CopyButton
              label="复制文件路径"
              onClick={() => copyAssistantContent(onCopyContent, part, "文件路径")}
            />
          ) : null}
        </span>
      );
    }
    return <span key={`${keyPrefix}-${index}`}>{part}</span>;
  });
}

function CopyButton({
  label,
  onClick,
}: {
  label: string;
  onClick: () => void;
}) {
  return (
    <button className="copy-action-button" type="button" onClick={onClick}>
      {label}
    </button>
  );
}

function copyAssistantContent(
  onCopyContent: CopyContentHandler,
  content: string,
  label: string,
) {
  onCopyContent(content, label);
}

function formatToolStepForCopy(tool: ToolStatus) {
  const lines = [`工具：${tool.name}`, `状态：${tool.status === "running" ? "运行中" : "完成"}`];
  if (tool.partial) {
    lines.push(`摘要：${tool.partial}`);
  }
  return lines.join("\n");
}

function formatTableForCopy(block: Extract<TextLineBlock, { type: "table" }>) {
  const divider = block.headers.map(() => "---");
  return [block.headers, divider, ...block.rows]
    .map((row) => `| ${row.join(" | ")} |`)
    .join("\n");
}

function formatWorkflowForCopy(block: Extract<TextLineBlock, { type: "workflow" }>) {
  const items = block.items.map((item) => {
    const marker = item.checked ? "[x]" : "[ ]";
    return `- ${marker} ${item.content}`;
  });
  return [`[${block.title}]`, ...items].join("\n");
}

function formatMarkdownLinkForCopy(label: string, href: string) {
  if (!label || label === href) {
    return href;
  }
  return `${label}\n${href}`;
}

function formatProcessDuration(items: Record<string, unknown>[]): string | undefined {
  const durationMs = items
    .map((item) => item.duration_ms)
    .find((value): value is number => typeof value === "number" && Number.isFinite(value));
  if (durationMs === undefined) {
    return undefined;
  }
  if (durationMs < 1000) {
    return `${Math.round(durationMs)}ms`;
  }
  const totalSeconds = Math.max(1, Math.round(durationMs / 1000));
  const minutes = Math.floor(totalSeconds / 60);
  const seconds = totalSeconds % 60;
  if (minutes > 0) {
    return `${minutes}m ${seconds}s`;
  }
  return `${seconds}s`;
}

function formatMessageTime(value: string | null) {
  const date = value ? new Date(value) : new Date();
  return date.toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
}

function redactSensitiveText(content: string) {
  return content
    .replace(
      /\b(authorization)(\s*[:=]\s*)(["']?)Bearer\s+([^\s"',;]+)(["']?)/gi,
      (
        _match,
        name: string,
        separator: string,
        quote: string,
        value: string,
        endQuote: string,
      ) => `${name}${separator}${quote}Bearer ${maskSecretValue(value)}${endQuote}`,
    )
    .replace(
      /\b(authorization)(\s*[:=]\s*)(["']?)(?!Bearer\s+)([^\n"',;]+)(["']?)/gi,
      (
        _match,
        name: string,
        separator: string,
        quote: string,
        value: string,
        endQuote: string,
      ) => `${name}${separator}${quote}${maskAuthorizationValue(value.trim())}${endQuote}`,
    )
    .replace(
      /\b(api[_-]?key|token|cookie|password|secret|ssh[_-]?key)(\s*[:=]\s*)(["']?)([^\s"',;]+)/gi,
      (_match, name: string, separator: string, quote: string, value: string) =>
        `${name}${separator}${quote}${maskSecretValue(value)}`,
    )
    .replace(/\bBearer\s+([A-Za-z0-9._~+/-]{12,})/g, (_match, value: string) => {
      return `Bearer ${maskSecretValue(value)}`;
    })
    .replace(/\b(sk|ak|pk|rk)-[A-Za-z0-9_-]{12,}/g, (value) => maskSecretValue(value));
}

function maskAuthorizationValue(value: string) {
  const scheme = value.match(/^([A-Za-z]+)\s+(.+)$/);
  if (scheme) {
    return `${scheme[1]} ${maskSecretValue(scheme[2])}`;
  }
  return maskSecretValue(value);
}

function maskSecretValue(value: string) {
  if (value.length <= 8) {
    return "****";
  }
  return `${value.slice(0, 4)}****${value.slice(-4)}`;
}

async function copyText(content: string) {
  if (navigator.clipboard?.writeText) {
    await navigator.clipboard.writeText(content);
    return;
  }

  const textarea = document.createElement("textarea");
  textarea.value = content;
  textarea.setAttribute("readonly", "true");
  textarea.style.position = "fixed";
  textarea.style.left = "-9999px";
  document.body.appendChild(textarea);
  textarea.select();
  const copied = document.execCommand("copy");
  document.body.removeChild(textarea);
  if (!copied) {
    throw new Error("copy failed");
  }
}

function CreateProjectModal({
  onClose,
  onCreate,
}: {
  onClose: () => void;
  onCreate: (form: CreateProjectForm) => Promise<void>;
}) {
  const [error, setError] = useState("");
  const [isSubmitting, setIsSubmitting] = useState(false);

  const handlePickDirectory = async () => {
    setError("");
    let pickedDirectory: PickedDirectory | null = null;
    try {
      pickedDirectory = await pickDirectoryFromDesktopBridge();
    } catch (pickError) {
      setError(pickError instanceof Error ? pickError.message : "本地目录选择失败");
      return;
    }
    if (!pickedDirectory) {
      setError("当前环境未提供本地目录路径桥接，无法记录真实文件夹路径");
      return;
    }
    setIsSubmitting(true);
    try {
      await onCreate({
        directoryName: pickedDirectory.name,
        rootPath: pickedDirectory.path,
      });
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "项目创建失败");
    } finally {
      setIsSubmitting(false);
    }
  };

  return (
    <div className="modal-backdrop" role="presentation">
      <section className="create-project-modal" role="dialog" aria-modal="true">
        <header>
          <h2>创建项目</h2>
          <button type="button" aria-label="关闭" onClick={onClose}>
            ×
          </button>
        </header>

        <div className="project-type-card">
          <span className="project-type-icon">▭</span>
          <div>
            <strong>本地</strong>
            <p>在你的电脑上编辑、运行和测试文件</p>
          </div>
          <span className="selected-dot" />
        </div>

        {error ? <p className="modal-error">{error}</p> : null}

        <div className="modal-actions">
          <button type="button" onClick={onClose}>
            取消
          </button>
          <button type="button" disabled={isSubmitting} onClick={handlePickDirectory}>
            {isSubmitting ? "导入中..." : "使用现有文件夹"}
          </button>
        </div>
      </section>
    </div>
  );
}

type PickedDirectory = {
  name: string;
  path: string;
};

type DirectoryBridge = {
  pickDirectory?: () => Promise<PickedDirectory | null>;
  selectDirectory?: () => Promise<PickedDirectory | null>;
};

type WindowWithDirectoryBridge = Window & {
  claudeSdk?: DirectoryBridge;
  codex?: DirectoryBridge;
  electronAPI?: DirectoryBridge;
};

async function pickDirectoryFromDesktopBridge() {
  const bridgeWindow = window as WindowWithDirectoryBridge;
  const pickers = [
    () => bridgeWindow.claudeSdk?.pickDirectory?.() ?? null,
    () => bridgeWindow.claudeSdk?.selectDirectory?.() ?? null,
    () => bridgeWindow.codex?.pickDirectory?.() ?? null,
    () => bridgeWindow.codex?.selectDirectory?.() ?? null,
    () => bridgeWindow.electronAPI?.pickDirectory?.() ?? null,
    () => bridgeWindow.electronAPI?.selectDirectory?.() ?? null,
  ];

  for (const picker of pickers) {
    const directory = await Promise.resolve(picker()).catch(() => null);
    if (directory?.path) {
      return {
        name: directory.name || getDirectoryNameFromPath(directory.path),
        path: directory.path,
      };
    }
  }
  const directory = await requestPickLocalDirectory();
  if (directory?.path) {
    return {
      name: directory.name || getDirectoryNameFromPath(directory.path),
      path: directory.path,
    };
  }
  return null;
}

function getDirectoryNameFromPath(path: string) {
  const parts = path.replace(/\/+$/, "").split("/").filter(Boolean);
  return parts[parts.length - 1] ?? "project";
}

function getInitials(name: string | null) {
  if (!name) {
    return "U";
  }
  return name
    .split(/\s|_/)
    .filter(Boolean)
    .slice(0, 2)
    .map((part) => part[0]?.toUpperCase())
    .join("");
}

function formatSessionTime(value: string | null) {
  if (!value) {
    return "刚刚";
  }
  return new Date(value).toLocaleString([], {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  });
}

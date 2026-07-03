import { ChangeEvent, FormEvent, useEffect, useMemo, useState } from "react";

type AuthMode = "login" | "register";

type ApiResponse<T> = {
  code: number;
  message: string;
  data: T | null;
  errno?: number;
};

type AuthUser = {
  id: number;
  user_name: string | null;
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
  default_session: ProjectSession;
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

type ToolStatus = {
  id: string;
  name: string;
  status: "running" | "done";
  partial: string;
};

type CreateProjectForm = {
  directoryName: string;
};

const initialForm: FormState = {
  userName: "",
  password: "",
};

const apiBaseUrl = import.meta.env.VITE_API_BASE_URL ?? "";

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

async function requestImportProject(
  userId: number,
  form: CreateProjectForm,
): Promise<ProjectImportData> {
  return requestJson<ProjectImportData>("/v1/projects/import-local-path", {
    method: "POST",
    body: JSON.stringify({
      user_id: userId,
      directory_name: form.directoryName.trim(),
    }),
  });
}

async function requestCreateSession(
  userId: number,
  projectId: number,
): Promise<ProjectSession> {
  return requestJson<ProjectSession>(`/v1/projects/${projectId}/sessions`, {
    method: "POST",
    body: JSON.stringify({ user_id: userId, title: "新会话" }),
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

async function requestSendMessageStream(
  userId: number,
  sessionId: number,
  content: string,
  onEvent: (event: StreamEventEnvelope) => void,
): Promise<void> {
  const response = await fetch(`${apiBaseUrl}/v1/sessions/${sessionId}/messages/stream`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
    },
    body: JSON.stringify({ user_id: userId, content }),
  });

  if (!response.ok) {
    const result = (await response.json().catch(() => null)) as ApiResponse<unknown> | null;
    throw new Error(result?.message || "消息发送失败");
  }
  if (!response.body) {
    throw new Error("当前浏览器不支持流式响应");
  }

  const reader = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";

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
      onEvent(event);
      if (event.type === "agent_error") {
        const message = event.data.message;
        throw new Error(typeof message === "string" ? message : "Claude Agent SDK 调用失败");
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
  const [currentUser, setCurrentUser] = useState<AuthUser | null>(null);
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
  const [streamingText, setStreamingText] = useState("");
  const [streamTools, setStreamTools] = useState<ToolStatus[]>([]);

  const activeProject = projects.find((project) => project.id === activeProjectId) ?? null;
  const activeSession =
    activeProject?.sessions.find((session) => session.id === activeSessionId) ?? null;

  const loadProjects = async (preferredSessionId?: number) => {
    setIsLoadingProjects(true);
    try {
      const data = await requestProjects(user.id);
      setProjects(data.items);
      const nextProject =
        data.items.find((project) =>
          project.sessions.some((session) => session.id === preferredSessionId),
        ) ?? data.items[0] ?? null;
      const nextSession =
        nextProject?.sessions.find((session) => session.id === preferredSessionId) ??
        nextProject?.sessions[0] ??
        null;
      setActiveProjectId(nextProject?.id ?? null);
      setActiveSessionId(nextSession?.id ?? null);
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
    if (!activeSessionId) {
      setMessages([]);
      return;
    }
    setStreamingText("");
    setStreamTools([]);
    const loadMessages = async () => {
      try {
        const data = await requestMessages(user.id, activeSessionId);
        setMessages(data.items);
      } catch (error) {
        setNotice(error instanceof Error ? error.message : "消息加载失败");
      }
    };
    void loadMessages();
  }, [activeSessionId, user.id]);

  const handleSelectSession = (projectId: number, sessionId: number) => {
    setActiveProjectId(projectId);
    setActiveSessionId(sessionId);
    setNotice("");
    setIsMobileSidebarOpen(false);
    setStreamingText("");
    setStreamTools([]);
  };

  const handleCreateProject = async (form: CreateProjectForm) => {
    const data = await requestImportProject(user.id, form);
    setIsCreateModalOpen(false);
    setNotice(`已导入 ${data.project.name}`);
    await loadProjects(data.default_session.id);
  };

  const handleCreateSession = async () => {
    if (!activeProjectId) {
      setIsCreateModalOpen(true);
      return;
    }
    try {
      const session = await requestCreateSession(user.id, activeProjectId);
      await loadProjects(session.id);
      setNotice("已创建新会话");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "会话创建失败");
    }
  };

  const handleSendMessage = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const nextMessage = composerText.trim();
    if (!nextMessage || !activeSessionId || isSending) {
      return;
    }

    setIsSending(true);
    setNotice("");
    setStreamingText("");
    setStreamTools([]);
    try {
      setComposerText("");
      const optimisticUserMessage: SessionMessage = {
        id: -Date.now(),
        session_id: activeSessionId,
        role: "user",
        content: nextMessage,
        status: "done",
        tool_summary: [],
        diff_summary: [],
        created_at: new Date().toISOString(),
      };
      setMessages((items) => [...items, optimisticUserMessage]);

      await requestSendMessageStream(user.id, activeSessionId, nextMessage, (event) => {
        if (event.type === "assistant_delta") {
          const content = event.data.content;
          if (typeof content === "string") {
            setStreamingText((value) => `${value}${content}`);
          }
        }
        if (event.type === "tool_start") {
          const id = String(event.data.id ?? `${event.sequence}`);
          const name = String(event.data.name ?? "tool");
          setStreamTools((items) => [
            ...items,
            { id, name, status: "running", partial: "", },
          ]);
        }
        if (event.type === "tool_delta") {
          const id = String(event.data.id ?? "");
          const partial = String(event.data.partial ?? "");
          setStreamTools((items) =>
            items.map((item) =>
              id && item.id === id
                ? { ...item, partial: `${item.partial}${partial}`.slice(-240) }
                : item,
            ),
          );
        }
        if (event.type === "tool_done") {
          const id = String(event.data.id ?? "");
          setStreamTools((items) =>
            items.map((item) => (id && item.id === id ? { ...item, status: "done" } : item)),
          );
        }
      });
      const data = await requestMessages(user.id, activeSessionId);
      setMessages(data.items);
      setStreamingText("");
      setStreamTools([]);
      await loadProjects(activeSessionId);
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "消息发送失败");
      setComposerText(nextMessage);
      try {
        const data = await requestMessages(user.id, activeSessionId);
        setMessages(data.items);
      } catch {
        setMessages((items) => items.filter((item) => item.id >= 0));
      }
    } finally {
      setIsSending(false);
      setStreamingText("");
      setStreamTools([]);
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

        <div className="project-list">
          <div className="project-list-heading">
            <p className="sidebar-label">项目</p>
            <button
              className="icon-button"
              type="button"
              aria-label="创建项目"
              onClick={() => setIsCreateModalOpen(true)}
            >
              ＋
            </button>
          </div>

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
                  setActiveProjectId(project.id);
                  setActiveSessionId(project.sessions[0]?.id ?? null);
                }}
              >
                <h2>{project.name}</h2>
                <small>{project.is_git_repo ? "Git" : "本地"}</small>
              </button>
              <div className="thread-list">
                {project.sessions.map((item) => (
                  <button
                    className={
                      item.id === activeSessionId ? "thread-item active" : "thread-item"
                    }
                    key={item.id}
                    type="button"
                    onClick={() => handleSelectSession(project.id, item.id)}
                  >
                    <span>{item.title}</span>
                    <small>{formatSessionTime(item.updated_at)}</small>
                  </button>
                ))}
              </div>
            </section>
          ))}
        </div>

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
            <h1>{activeSession?.title ?? activeProject?.name ?? "项目工作台"}</h1>
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
          <article className="assistant-message">
            {activeProject ? (
              <ProjectSummary project={activeProject} />
            ) : (
              <EmptyWorkspace onCreate={() => setIsCreateModalOpen(true)} />
            )}

            {notice ? <p className="mock-status">{notice}</p> : null}

            {messages.length > 0 ? (
              <div className="local-message-list">
                {messages.map((item) => (
                  <MessageBubble key={item.id} message={item} />
                ))}
                {isSending || streamingText || streamTools.length > 0 ? (
                  <StreamingMessage content={streamingText} tools={streamTools} />
                ) : null}
              </div>
            ) : activeProject ? (
              <>
                {isSending || streamingText || streamTools.length > 0 ? (
                  <div className="local-message-list">
                    <StreamingMessage content={streamingText} tools={streamTools} />
                  </div>
                ) : (
                  <p className="workspace-empty-message">当前会话还没有消息。</p>
                )}
              </>
            ) : null}
          </article>
        </div>

        <footer className="composer-wrap">
          <div className="message-actions" aria-hidden="true">
            <span>□</span>
            <span>♡</span>
            <span>↗</span>
            <span>{new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" })}</span>
          </div>
          <form className="composer" onSubmit={handleSendMessage}>
            <textarea
              placeholder={activeSession ? "要求后续变更" : "请先创建或选择项目会话"}
              rows={3}
              value={composerText}
              disabled={!activeSession || isSending}
              onChange={(event) => setComposerText(event.target.value)}
            />
            <div className="composer-toolbar">
              <button type="button" onClick={() => setComposerText((value) => `${value}+ `)}>
                ＋
              </button>
              <button type="button" onClick={() => setNotice("审批模式待接入")}>
                替我审批⌄
              </button>
              <span>Claude Code⌄</span>
              <button
                type="submit"
                aria-label="发送"
                disabled={!composerText.trim() || !activeSession || isSending}
              >
                {isSending ? "…" : "↑"}
              </button>
            </div>
          </form>
        </footer>
      </section>

      {isCreateModalOpen ? (
        <CreateProjectModal
          onClose={() => setIsCreateModalOpen(false)}
          onCreate={handleCreateProject}
        />
      ) : null}

      <button className="floating-help" type="button" aria-label="帮助">
        ●
      </button>
    </main>
  );
}

function ProjectSummary({ project }: { project: Project }) {
  return (
    <>
      <pre className="code-preview">{`{
  "project": "${project.name}",
  "source_type": "${project.source_type}",
  "sessions": ${project.sessions.length}
}`}</pre>
      <p>
        已导入本地项目 <code>{project.name}</code>。当前不会预扫描并保存文件列表；
        具体需求会在会话执行时再通过工具按需读取。
      </p>
      <div className="verification-block">
        <strong>项目摘要：</strong>
        <ul>
          <li>项目名称来自选择的本地目录名</li>
          <li>文件内容不入库，不在创建项目时扫描文件清单</li>
          <li>真实 cwd 绑定需要桌面壳或后端目录选择桥接提供绝对路径</li>
        </ul>
      </div>
    </>
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

function MessageBubble({ message }: { message: SessionMessage }) {
  const isAssistant = message.role === "assistant";
  return (
    <div className={isAssistant ? "message-bubble assistant" : "message-bubble user"}>
      <strong>{isAssistant ? "Claude" : "你"}</strong>
      <p>{message.content}</p>
      {message.tool_summary.length > 0 ? (
        <div className="diff-card compact">
          <div className="diff-card-header">
            <div className="file-icon">⊞</div>
            <div>
              <strong>工具调用</strong>
              <span>{message.tool_summary.length} 条记录</span>
            </div>
          </div>
        </div>
      ) : null}
    </div>
  );
}

function StreamingMessage({ content, tools }: { content: string; tools: ToolStatus[] }) {
  return (
    <div className="message-bubble assistant streaming">
      <strong>Claude</strong>
      {tools.length > 0 ? (
        <div className="stream-tool-list">
          {tools.map((tool) => (
            <div className="stream-tool-item" key={tool.id}>
              <span className={tool.status === "done" ? "tool-dot done" : "tool-dot"} />
              <div>
                <strong>{tool.name}</strong>
                {tool.partial ? <code>{tool.partial}</code> : null}
              </div>
            </div>
          ))}
        </div>
      ) : null}
      <p>{content || "正在思考..."}</p>
    </div>
  );
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

  const handleDirectoryName = async (directoryName: string) => {
    setError("");
    if (!directoryName.trim()) {
      setError("未识别到本地目录名");
      return;
    }
    setIsSubmitting(true);
    try {
      await onCreate({ directoryName });
    } catch (submitError) {
      setError(submitError instanceof Error ? submitError.message : "项目创建失败");
    } finally {
      setIsSubmitting(false);
    }
  };

  const handlePickDirectory = async () => {
    const picker = window as WindowWithDirectoryPicker;
    if (picker.showDirectoryPicker) {
      try {
        const handle = await picker.showDirectoryPicker();
        await handleDirectoryName(handle.name);
        return;
      } catch (pickError) {
        if (pickError instanceof DOMException && pickError.name === "AbortError") {
          return;
        }
        setError("当前浏览器无法完成目录选择");
      }
    }
    document.getElementById("project-directory-input")?.click();
  };

  const handleFallbackPick = async (event: ChangeEvent<HTMLInputElement>) => {
    const file = event.target.files?.[0] as FileWithRelativePath | undefined;
    const directoryName = file?.webkitRelativePath?.split("/")[0] ?? "";
    event.target.value = "";
    await handleDirectoryName(directoryName);
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

        <input
          id="project-directory-input"
          className="directory-input"
          type="file"
          multiple
          onChange={handleFallbackPick}
          {...{ webkitdirectory: "", directory: "" }}
        />

        {error ? <p className="modal-error">{error}</p> : null}

        <div className="modal-actions">
          <button type="button" onClick={onClose}>
            取消
          </button>
          <button type="button" disabled={isSubmitting} onClick={handlePickDirectory}>
            {isSubmitting ? "创建中..." : "使用现有文件夹"}
          </button>
        </div>
      </section>
    </div>
  );
}

type FileWithRelativePath = File & {
  webkitRelativePath?: string;
};

type DirectoryHandle = {
  name: string;
};

type WindowWithDirectoryPicker = Window & {
  showDirectoryPicker?: () => Promise<DirectoryHandle>;
};

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

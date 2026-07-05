export type AgentTaskStatus =
  | "created"
  | "queued"
  | "running"
  | "completed"
  | "failed"
  | "cancelling"
  | "cancelled";

export type AgentTaskRunningItem = {
  task_id: string;
  conversation_id: string | null;
  title: string | null;
  status: AgentTaskStatus;
  created_at: string | null;
  updated_at: string | null;
};

export type RunningTaskMarker = {
  taskId: string;
  status: AgentTaskStatus;
  title: string | null;
};

export type RunningTaskMarkers = Record<number, RunningTaskMarker>;

export function isActiveTaskStatus(status: AgentTaskStatus) {
  return (
    status === "created" ||
    status === "queued" ||
    status === "running" ||
    status === "cancelling"
  );
}

export function parseConversationSessionId(conversationId: string | null) {
  if (!conversationId) {
    return null;
  }
  const parsed = Number(conversationId);
  return Number.isInteger(parsed) && parsed > 0 ? parsed : null;
}

export function buildRunningTaskMarkers(items: AgentTaskRunningItem[]): RunningTaskMarkers {
  return items.reduce<RunningTaskMarkers>((markers, item) => {
    const sessionId = parseConversationSessionId(item.conversation_id);
    if (!sessionId || !isActiveTaskStatus(item.status)) {
      return markers;
    }
    return upsertRunningTaskMarker(markers, sessionId, {
      taskId: item.task_id,
      status: item.status,
      title: item.title,
    });
  }, {});
}

export function upsertRunningTaskMarker(
  markers: RunningTaskMarkers,
  sessionId: number,
  marker: RunningTaskMarker,
): RunningTaskMarkers {
  return {
    ...markers,
    [sessionId]: marker,
  };
}

export function removeRunningTaskMarker(
  markers: RunningTaskMarkers,
  sessionId: number | null,
  taskId?: string,
): RunningTaskMarkers {
  if (!sessionId || !markers[sessionId]) {
    return markers;
  }
  if (taskId && markers[sessionId].taskId !== taskId) {
    return markers;
  }
  const next = { ...markers };
  delete next[sessionId];
  return next;
}

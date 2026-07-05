"""Agent 后台任务接口模型。"""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

AgentTaskStatus = Literal[
    "created",
    "queued",
    "running",
    "completed",
    "failed",
    "cancelling",
    "cancelled",
]


class AgentTaskCreateIn(BaseModel):
    """创建 Agent 后台任务请求体。"""

    conversation_id: str | None = Field(None, max_length=64, description="会话 ID")
    title: str | None = Field(None, max_length=255, description="任务标题")
    prompt: str = Field(..., min_length=1, description="用户原始问题")


class AgentTaskCreateData(BaseModel):
    """创建任务成功数据体。"""

    task_id: str
    status: AgentTaskStatus


class AgentTaskOut(BaseModel):
    """任务详情响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    task_id: str
    conversation_id: str | None = None
    title: str | None = None
    prompt: str
    status: AgentTaskStatus
    result: str | None = None
    error_message: str | None = None
    cancel_requested: bool = False
    created_at: Any | None = None
    updated_at: Any | None = None
    started_at: Any | None = None
    finished_at: Any | None = None


class AgentTaskEventOut(BaseModel):
    """任务事件响应模型。"""

    seq: int
    event_type: str
    content: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: Any | None = None


class AgentTaskEventListData(BaseModel):
    """任务事件列表数据体。"""

    items: list[AgentTaskEventOut]


class AgentTaskRunningItem(BaseModel):
    """运行中任务列表项。"""

    task_id: str
    conversation_id: str | None = None
    title: str | None = None
    status: AgentTaskStatus
    created_at: Any | None = None
    updated_at: Any | None = None


class AgentTaskRunningListData(BaseModel):
    """运行中任务列表数据体。"""

    items: list[AgentTaskRunningItem]


class AgentTaskCancelData(BaseModel):
    """取消任务成功数据体。"""

    task_id: str
    status: AgentTaskStatus

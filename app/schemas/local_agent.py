"""本地工具中继接口模型。"""

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field

LocalAgentAction = Literal[
    "ping_path",
    "list_tree",
    "shell",
    "read_file",
    "write_file",
    "apply_patch",
]
LocalAgentTaskStatus = Literal["pending", "running", "succeeded", "failed"]
LocalAgentCompleteStatus = Literal["succeeded", "failed"]
LocalAgentStatus = Literal["idle", "running"]


class LocalAgentTaskCreateIn(BaseModel):
    """服务端创建本地执行任务请求体。"""

    root_path: str = Field(..., min_length=1, max_length=2048, description="用户本机项目根路径")
    action: LocalAgentAction = Field(..., description="本地脚本要执行的动作")
    payload: dict[str, Any] = Field(default_factory=dict, description="动作参数")
    timeout_seconds: int = Field(default=120, ge=1, le=3600, description="单任务超时秒数")


class ProjectLocalAgentTaskCreateIn(BaseModel):
    """基于已导入项目创建本地执行任务请求体。

    调用方只传用户与动作参数，``root_path`` 必须由服务端按 project_id
    从已有项目记录读取，避免让用户或前端重复指定本地路径。
    """

    user_id: int = Field(..., ge=1, description="当前用户 id")
    action: LocalAgentAction = Field(..., description="本地脚本要执行的动作")
    payload: dict[str, Any] = Field(default_factory=dict, description="动作参数")
    timeout_seconds: int = Field(default=120, ge=1, le=3600, description="单任务超时秒数")


class LocalAgentPollIn(BaseModel):
    """本地脚本轮询任务请求体。"""

    agent_name: str = Field("local-agent", min_length=1, max_length=128, description="本地脚本实例名")


class LocalAgentTaskCompleteIn(BaseModel):
    """本地脚本回传任务结果请求体。"""

    status: LocalAgentCompleteStatus
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = Field(None, max_length=4000)


class LocalAgentTaskOut(BaseModel):
    """本地执行任务响应模型。"""

    id: str
    root_path: str
    action: LocalAgentAction
    payload: dict[str, Any]
    timeout_seconds: int
    status: LocalAgentTaskStatus
    result: dict[str, Any] = Field(default_factory=dict)
    error: str | None = None
    agent_name: str | None = None
    created_at: datetime
    updated_at: datetime


class LocalAgentPollData(BaseModel):
    """本地脚本轮询响应数据。"""

    task: LocalAgentTaskOut | None


class LocalAgentInfoOut(BaseModel):
    """本地脚本实例在线状态。"""

    agent_name: str
    status: LocalAgentStatus
    poll_count: int
    current_task_id: str | None = None
    last_seen_at: datetime


class LocalAgentListData(BaseModel):
    """本地脚本实例列表。"""

    items: list[LocalAgentInfoOut]

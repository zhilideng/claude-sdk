"""项目与会话接口模型。"""
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class ProjectImportIn(BaseModel):
    """导入本地目录项目请求体。

    JSON 入口保留给受信任桌面桥接；必须传入真实本地绝对路径，禁止用
    服务端临时目录代替用户选择的文件夹。
    """

    user_id: int = Field(..., ge=1, description="当前用户 id")
    directory_name: str = Field(..., min_length=1, max_length=255, description="本地目录名")
    root_path: str | None = Field(None, min_length=1, max_length=2048, description="本地绝对路径")


class ProjectCreateIn(ProjectImportIn):
    """创建本地项目请求体。"""


class LocalDirectoryPickData(BaseModel):
    """本机目录选择结果。"""

    name: str
    path: str


class ProjectScanData(BaseModel):
    """项目目录路径摘要。"""

    root_path: str | None
    display_path: str | None
    is_git_repo: bool


class ProjectSessionOut(BaseModel):
    """项目会话响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    project_id: int
    title: str
    status: Literal["idle", "running", "failed"]
    last_message: str | None = None
    created_at: Any | None = None
    updated_at: Any | None = None


class ProjectOut(BaseModel):
    """项目响应模型。"""

    id: int
    user_id: int
    name: str
    root_path: str | None
    display_path: str | None
    source_type: str
    is_git_repo: bool
    sessions: list[ProjectSessionOut]
    created_at: Any | None = None
    updated_at: Any | None = None


class ProjectListData(BaseModel):
    """项目列表数据体。"""

    items: list[ProjectOut]


class ProjectImportData(BaseModel):
    """项目导入成功数据体。"""

    project: ProjectOut
    default_session: ProjectSessionOut | None = None


class ProjectSessionCreateIn(BaseModel):
    """创建会话请求体。"""

    user_id: int = Field(..., ge=1, description="当前用户 id")
    title: str = Field("新会话", min_length=1, max_length=255, description="会话标题")


class SessionMessageOut(BaseModel):
    """会话消息响应模型。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    session_id: int
    role: Literal["user", "assistant", "system"]
    content: str
    status: Literal["done", "failed"]
    tool_summary: list[dict[str, Any]]
    diff_summary: list[dict[str, Any]]
    created_at: Any | None = None


class SessionMessageListData(BaseModel):
    """会话消息列表数据体。"""

    items: list[SessionMessageOut]


class SessionMessageCreateIn(BaseModel):
    """发送会话消息请求体。"""

    user_id: int = Field(..., ge=1, description="当前用户 id")
    content: str = Field(..., min_length=1, description="用户输入内容")


class SessionMessageCreateData(BaseModel):
    """发送消息后的响应数据体。"""

    message: SessionMessageOut
    session: ProjectSessionOut

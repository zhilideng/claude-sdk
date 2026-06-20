"""skill 对外 API schema。"""
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class SkillMetaOut(BaseModel):
    """skill 元数据（GET 列表 / 详情响应项）。"""

    model_config = ConfigDict(from_attributes=True)

    name: str
    description: str = ""
    version: str = "0.1.0"
    tags: list[str] = Field(default_factory=list)
    enabled: bool = True


class SkillRunRequest(BaseModel):
    """执行 skill 的请求体。"""

    input: str = Field(
        ..., min_length=1, max_length=8000, description="用户输入，作为 LLM 的 user message"
    )
    provider: Optional[str] = Field(
        None, max_length=50, description="指定 LLM provider；None 使用 llm.default_provider"
    )


class SkillRunResponse(BaseModel):
    """执行 skill 的响应体（作为 ApiResponse.data）。"""

    skill: str
    provider: str
    model: str
    content: str

"""skill 注册中心的数据模型。"""
from pydantic import BaseModel, Field


class SkillMeta(BaseModel):
    """skill 元数据（启动期索引项，仅来自 frontmatter，轻量）。"""

    name: str  # 唯一键
    description: str = ""  # 给 LLM / agent 的检索描述
    version: str = "0.1.0"  # skill 版本
    tags: list[str] = Field(default_factory=list)  # 轻量标签，供列表展示 / 后续检索
    enabled: bool = True  # false 时拒绝运行
    dir_path: str  # skill 目录绝对路径，懒加载时定位 SKILL.md


class SkillBundle(BaseModel):
    """skill 完整包（懒加载产物）：元数据 + 正文。"""

    meta: SkillMeta
    body: str  # SKILL.md frontmatter 之后的 markdown，作为 LLM system 指令

"""SKILL.md 解析：YAML frontmatter + markdown 正文。"""
import re
from pathlib import Path

import yaml

from app.core.skills.models import SkillBundle, SkillMeta
from app.exceptions import BizException, SKILL_ERRNO_LOAD_FAILED

# frontmatter 匹配：首部 ``---`` 包裹 YAML，后面全部视为正文。
FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


def parse_skill_file(skill_md_path: Path) -> SkillBundle:
    """解析单个 SKILL.md，返回 SkillBundle。

    解析失败统一抛 ``BizException(SKILL_ERRNO_LOAD_FAILED)``，由 registry 扫描期
    决定跳过降级，或由运行期交给全局异常处理器转统一响应。
    """
    try:
        text = skill_md_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise BizException(
            f"SKILL.md 读取失败: {skill_md_path}", errno=SKILL_ERRNO_LOAD_FAILED
        ) from exc

    match = FRONTMATTER_RE.match(text)
    if not match:
        raise BizException(
            f"SKILL.md 缺少 frontmatter（需以 --- 包裹 YAML 头）: {skill_md_path}",
            errno=SKILL_ERRNO_LOAD_FAILED,
        )

    raw_meta, body = match.group(1), match.group(2).strip()
    try:
        data = yaml.safe_load(raw_meta) or {}
    except yaml.YAMLError as exc:
        raise BizException(
            f"SKILL.md frontmatter YAML 解析失败: {skill_md_path}",
            errno=SKILL_ERRNO_LOAD_FAILED,
        ) from exc

    name = str(data.get("name", "")).strip()
    if not name:
        raise BizException(
            f"SKILL.md 缺少必填字段 name: {skill_md_path}",
            errno=SKILL_ERRNO_LOAD_FAILED,
        )

    meta = SkillMeta(
        name=name,
        description=str(data.get("description", "")).strip(),
        version=str(data.get("version", "0.1.0")).strip(),
        tags=[str(tag) for tag in (data.get("tags", []) or [])],
        enabled=bool(data.get("enabled", True)),
        dir_path=str(skill_md_path.parent.resolve()),
    )
    return SkillBundle(meta=meta, body=body)

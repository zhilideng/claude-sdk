"""skill 注册中心：扫描建索引 + 懒加载 + 缓存。"""
from pathlib import Path

from app.core.logger import logger
from app.core.settings import SkillSettings
from app.core.skills.loader import parse_skill_file
from app.core.skills.models import SkillBundle, SkillMeta
from app.exceptions import (
    BizException,
    BizNotFoundError,
    SKILL_ERRNO_DISABLED,
    SKILL_ERRNO_NOT_FOUND,
    SKILL_ERRNO_NOT_INITIALIZED,
)

# 模块级「单例缓存」，与 LLM gateway 的公开缓存命名风格保持一致。
skill_index: dict[str, SkillMeta] = {}
skill_bundles: dict[str, SkillBundle] = {}
settings_cache: SkillSettings | None = None


def init_skills(settings: SkillSettings) -> None:
    """启动期扫描 base_dir，解析 frontmatter 建轻量索引。

    skill 属非核心依赖：总开关关闭、目录不存在、单个 skill 解析失败都只降级，
    不阻断应用启动。
    """
    global settings_cache
    skill_index.clear()
    skill_bundles.clear()
    settings_cache = settings

    if not settings.enabled:
        logger.info("skill 注册中心已关闭（enabled=false），空运行")
        return

    base_dir = resolve_base_dir(settings.base_dir)
    if not base_dir.is_dir():
        logger.warning("skill base_dir 不存在，空运行 | dir={}", base_dir)
        return

    for skill_dir in iter_skill_dirs(base_dir):
        skill_md = skill_dir / "SKILL.md"
        if not skill_md.is_file():
            logger.warning("skill 目录缺少 SKILL.md，跳过 | dir={}", skill_dir)
            continue
        try:
            bundle = parse_skill_file(skill_md)
        except BizException as exc:
            logger.warning("skill 解析失败，跳过 | dir={} | {}", skill_dir, exc)
            continue

        if bundle.meta.name != skill_dir.name:
            logger.warning(
                "skill name 与目录名不一致，以 frontmatter name 为准 | dir={} | name={}",
                skill_dir.name,
                bundle.meta.name,
            )
        skill_index[bundle.meta.name] = bundle.meta

    logger.info(
        "skill 注册中心初始化完成 | count={} | skills={}",
        len(skill_index),
        sorted(skill_index),
    )


def get_meta(name: str) -> SkillMeta:
    """按名取元数据；未初始化、不存在、disabled 均抛 BizException。"""
    if not skill_index:
        raise BizException(
            "skill 注册中心未初始化或为空（init_skills 未执行 / enabled=false / 无 skill）",
            errno=SKILL_ERRNO_NOT_INITIALIZED,
        )

    meta = skill_index.get(name)
    if meta is None:
        raise BizNotFoundError(
            f"未知 skill: {name}（已注册: {sorted(skill_index)}）",
            errno=SKILL_ERRNO_NOT_FOUND,
        )
    if not meta.enabled:
        raise BizException(f"skill 已禁用: {name}", errno=SKILL_ERRNO_DISABLED)
    return meta


def load(name: str) -> SkillBundle:
    """懒加载完整包：首次读盘解析 + 缓存，后续命中缓存。"""
    meta = get_meta(name)
    if settings_cache is not None and settings_cache.cache_loaded:
        cached = skill_bundles.get(name)
        if cached is not None:
            return cached

    bundle = parse_skill_file(Path(meta.dir_path) / "SKILL.md")
    if settings_cache is not None and settings_cache.cache_loaded:
        skill_bundles[name] = bundle
    return bundle


def list_metadatas() -> list[SkillMeta]:
    """列出全部已注册 skill 元数据（含 disabled，供 agent 发现能力）。"""
    return list(skill_index.values())


async def close_skills() -> None:
    """清空索引与缓存，供 lifespan shutdown 调用。"""
    global settings_cache
    skill_index.clear()
    skill_bundles.clear()
    settings_cache = None
    logger.info("skill 注册中心已关闭")


def resolve_base_dir(base_dir: str) -> Path:
    """解析 base_dir：绝对路径直接用，相对路径基于项目根。"""
    path = Path(base_dir).expanduser()
    if path.is_absolute():
        return path
    here = Path(__file__).resolve()
    for anc in (here, *here.parents):
        if (anc / ".git").exists() or (anc / "requirements.txt").exists():
            return anc / path
    return path


def iter_skill_dirs(base_dir: Path) -> list[Path]:
    """列出候选 skill 目录，忽略 Python/工具生成目录。

    ``app/skills`` 是数据目录，但包内存在 ``__init__.py`` 时运行测试或启动后可能
    生成 ``__pycache__``。这类目录不是 skill，静默忽略，避免启动日志噪音。
    """
    ignored_names = {"__pycache__"}
    return sorted(
        p
        for p in base_dir.iterdir()
        if p.is_dir() and p.name not in ignored_names and not p.name.startswith(".")
    )

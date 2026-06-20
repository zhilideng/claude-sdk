"""skill 编排：加载 skill + 驱动 LLM。"""
from typing import Any, Optional

from langchain_core.messages import HumanMessage, SystemMessage

from app.core.config import Settings, get_settings
from app.core.llm.gateway import get_langchain_llm, langchain_tracing_context
from app.core.skills.registry import get_meta, list_metadatas, load
from app.exceptions import BizException, SKILL_ERRNO_RUN_FAILED


class SkillService:
    """skill 编排服务。"""

    def __init__(self, settings: Optional[Settings] = None) -> None:
        self.settings = settings or get_settings()

    def list_skills(self) -> list[dict[str, Any]]:
        """列出全部 skill 元数据。"""
        return [meta.model_dump(exclude={"dir_path"}) for meta in list_metadatas()]

    def get_skill(self, name: str) -> dict[str, Any]:
        """取单个 skill 元数据。"""
        return get_meta(name).model_dump(exclude={"dir_path"})

    async def run_skill(
        self, name: str, user_input: str, provider: Optional[str] = None
    ) -> dict[str, Any]:
        """加载 skill 并把正文作为 system 指令调用 LLM。"""
        bundle = load(name)
        meta = bundle.meta
        provider_name = provider or self.settings.llm.default_provider
        cfg = self.settings.llm.providers.get(provider_name)
        if cfg is None:
            raise BizException(
                f"LLM Provider 未配置: {provider_name}",
                errno=SKILL_ERRNO_RUN_FAILED,
            )

        model = get_langchain_llm(provider_name)
        try:
            with langchain_tracing_context():
                response = await model.ainvoke(
                    [
                        SystemMessage(content=bundle.body),
                        HumanMessage(content=user_input),
                    ]
                )
        except Exception as exc:  # noqa: BLE001 —— LLM 调用失败统一转业务异常
            raise BizException(
                f"skill 执行失败（LLM 调用）: {name}",
                errno=SKILL_ERRNO_RUN_FAILED,
            ) from exc

        return {
            "skill": meta.name,
            "provider": provider_name,
            "model": cfg.default_model,
            "content": getattr(response, "content", str(response)),
        }

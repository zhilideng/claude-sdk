"""LLM 网关：统一管理原生 Provider 与 LangChain 模型实例。"""
from __future__ import annotations

import os
from typing import Any
from typing import Optional

from app.core.llm.base import BaseLLM
from app.core.llm.openai_provider import OpenAIProvider
from app.core.logger import logger
from app.core.settings import LlmProviderConfig, LlmSettings
from app.exceptions import (
    BizException,
    LLM_ERRNO_CALL_FAILED,
    LLM_ERRNO_NOT_INITIALIZED,
    LLM_ERRNO_PROVIDER_NOT_FOUND,
)

providers: dict[str, BaseLLM] = {}
langchain_models: dict[str, Any] = {}
provider_configs: dict[str, LlmProviderConfig] = {}
default_provider_name: str = ""


def init_llm(settings: LlmSettings) -> None:
    """按配置初始化原生 LLM Provider 与 LangChain ChatModel 实例。

    启动期一次性完成两类实例创建，把 LangChain 初始化成本放在应用启动阶段，
    避免首次业务请求因为模型初始化而增加耗时。
    """
    global default_provider_name
    providers.clear()
    langchain_models.clear()
    provider_configs.clear()
    default_provider_name = settings.default_provider

    for name, cfg in settings.providers.items():
        try:
            providers[name] = OpenAIProvider(name, cfg)
        except Exception as exc:  # noqa: BLE001 —— 构造失败不阻断启动
            logger.warning(
                "LLM Provider 构造失败，已跳过（降级运行）| name={} | {}",
                name,
                exc,
            )
            continue
        provider_configs[name] = cfg
        try:
            langchain_models[name] = build_langchain_llm(name, cfg)
        except BizException as exc:
            logger.warning(
                "LangChain LLM 构造失败，已跳过（降级运行）| name={} | {}",
                name,
                exc,
            )
        logger.info(
            "LLM Provider 已注册 | name={} | base_url={} | model={}",
            name,
            cfg.base_url,
            cfg.default_model,
        )
    if providers:
        logger.info(
            "LLM 网关初始化完成 | providers={} | default={}",
            sorted(providers),
            default_provider_name,
        )
    else:
        logger.warning("LLM 网关初始化完成但未注册任何 Provider（providers 配置为空，降级运行）")


def get_llm(name: Optional[str] = None) -> BaseLLM:
    """获取原生 LLM Provider 实例。

    ``name`` 为空时使用配置里的默认 Provider；未初始化或名称不存在时抛
    ``BizException``，避免业务静默拿到错误模型。
    """
    target = resolve_name(name)
    provider = providers.get(target)
    if provider is None:
        raise_provider_not_found(target)
    return provider


def get_provider(name: Optional[str] = None) -> BaseLLM:
    """获取原生 LLM Provider 实例的兼容入口。

    旧代码如果已经使用 ``get_provider`` 可以继续运行；新业务代码建议直接使用
    ``get_llm``，语义更明确。
    """
    return get_llm(name)


def get_langchain_llm(name: Optional[str] = None) -> Any:
    """获取 LangChain ChatModel 实例。

    LangChain 实例由 ``init_llm`` 在启动期创建；这里只读取缓存，避免业务请求
    承担初始化耗时。如果缓存不存在，说明启动期该实例初始化失败或名称配置错误。
    """
    target = resolve_name(name)
    if target in langchain_models:
        return langchain_models[target]

    raise BizException(
        f"LangChain LLM 未初始化: {target}（已初始化: {sorted(langchain_models)}）",
        errno=LLM_ERRNO_NOT_INITIALIZED,
    )


def build_langchain_llm(name: str, cfg: LlmProviderConfig) -> Any:
    """创建 LangChain ChatModel 实例。

    使用与原生 Provider 相同的模型名、base_url 和密钥来源调用
    ``init_chat_model``，保证原生调用和 LangChain 调用不会出现配置漂移。
    """

    try:
        from langchain.chat_models import init_chat_model
    except ImportError as exc:
        raise BizException(
            "LangChain 未安装，请先安装 langchain 相关依赖",
            errno=LLM_ERRNO_CALL_FAILED,
        ) from exc

    try:
        model = init_chat_model(
            model=cfg.default_model,
            model_provider="openai",
            api_key=resolve_api_key(name, cfg),
            base_url=cfg.base_url,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("LangChain LLM 初始化失败 | name={} | {}", name, exc)
        raise BizException(
            f"LangChain LLM 初始化失败: {name}",
            errno=LLM_ERRNO_CALL_FAILED,
        ) from exc

    logger.info("LangChain LLM 已初始化 | name={} | model={}", name, cfg.default_model)
    return model


def get_langchain_model(name: Optional[str] = None) -> Any:
    """获取 LangChain ChatModel 实例的别名入口。

    保留这个名字是为了让调用方可以选择更贴近 LangChain 习惯的命名；实现仍然
    复用 ``get_langchain_llm``。
    """
    return get_langchain_llm(name)


def resolve_name(name: Optional[str]) -> str:
    """解析最终使用的 Provider 名称。

    当调用方没有传入 ``name`` 时回退到 ``default_provider_name``；如果网关尚未
    初始化任何原生 Provider，则直接抛未初始化异常。
    """
    if not providers:
        raise BizException(
            "LLM 网关未初始化（providers 为空或 init_llm 未执行）",
            errno=LLM_ERRNO_NOT_INITIALIZED,
        )
    return name or default_provider_name


def resolve_api_key(name: str, cfg: LlmProviderConfig) -> str:
    """解析 Provider 的 API Key。

    优先使用配置对象里的密钥；配置为空时读取 ``LLM_API_KEY_<NAME>`` 环境变量，
    与 ``OpenAIProvider`` 的密钥注入约定保持一致。
    """
    api_key = cfg.api_key.get_secret_value()
    return api_key or os.environ.get(f"LLM_API_KEY_{name.upper()}", "")


def raise_provider_not_found(name: str) -> None:
    """抛出 Provider 不存在的业务异常。

    错误消息带上已注册名称，方便排查配置拼写、默认 Provider 与实际注册列表不一致
    等问题。
    """
    registered = sorted(provider_configs or providers)
    raise BizException(
        f"未知 LLM Provider: {name}（已注册: {registered}）",
        errno=LLM_ERRNO_PROVIDER_NOT_FOUND,
    )


async def close_llm() -> None:
    """关闭原生 Provider 连接池并清空全部网关缓存。

    单个 Provider 关闭失败不会影响其他 Provider 的释放；所有释放动作结束后再统一
    汇总抛错，保证 shutdown 阶段尽量回收资源。
    """
    global default_provider_name
    errors: list[tuple[str, Exception]] = []
    for name, provider in list(providers.items()):
        try:
            await provider.aclose()
        except Exception as exc:  # noqa: BLE001 —— shutdown 必须尽力释放全部 Provider
            errors.append((name, exc))
            logger.exception("LLM Provider 关闭失败 | name={} | {}", name, exc)
    providers.clear()
    langchain_models.clear()
    provider_configs.clear()
    default_provider_name = ""
    if errors:
        detail = "; ".join(f"{n}: {e}" for n, e in errors)
        raise RuntimeError(f"LLM Provider 关闭失败: {detail}")

"""Milvus 异步客户端生命周期管理。

本模块只负责进程级 ``AsyncMilvusClient`` 的构造、启动探测、获取与关闭。
collection 和数据操作统一放在 ``app.repositories.vector``，避免 core 层混入
Repository 职责。

Milvus 属可降级依赖：启动连接失败不阻断应用；真实业务调用 ``get_milvus`` 时
若客户端不可用则快速抛出统一业务异常。多 worker 模式下每个进程各持有一个客户端。
"""
from typing import Optional
from urllib.parse import urlsplit, urlunsplit

from pymilvus import AsyncMilvusClient

from app.core.logger import logger
from app.core.settings import MilvusSettings
from app.exceptions import (
    MILVUS_ERRNO_CONNECT_FAILED,
    MILVUS_ERRNO_NOT_INITIALIZED,
    MILVUS_ERRNO_OPERATION_FAILED,
    BizException,
)


_milvus_client: Optional[AsyncMilvusClient] = None
_milvus_settings: Optional[MilvusSettings] = None


def _safe_uri(uri: str) -> str:
    """移除 URI 中的用户信息与查询参数，仅供日志展示。"""
    try:
        parsed = urlsplit(uri)
        if not parsed.netloc:
            return uri.split("?", 1)[0]
        host = parsed.hostname or ""
        if ":" in host:
            host = f"[{host}]"
        netloc = f"{host}:{parsed.port}" if parsed.port is not None else host
        return urlunsplit((parsed.scheme, netloc, parsed.path, "", ""))
    except ValueError:
        return "<invalid-uri>"


def build_milvus_client(settings: MilvusSettings) -> AsyncMilvusClient:
    """按配置构造异步 Milvus 客户端，不执行网络请求。

    空 token 不传给 SDK，兼容本地未开启鉴权的 Milvus；非空 token 仅用于构造，
    不写入任何日志。
    """
    kwargs = {
        "uri": settings.uri,
        "db_name": settings.db_name,
        "timeout": settings.timeout,
    }
    token = settings.token.get_secret_value()
    if token:
        kwargs["token"] = token
    try:
        return AsyncMilvusClient(**kwargs)
    except Exception as exc:  # noqa: BLE001 —— SDK 构造可能抛参数或传输层异常
        raise BizException(
            message="Milvus 客户端构造失败",
            errno=MILVUS_ERRNO_CONNECT_FAILED,
        ) from exc


async def init_milvus(settings: MilvusSettings) -> None:
    """初始化客户端并执行只读连通性探测，失败时降级运行。

    只有 ``list_collections`` 探测成功后才发布全局单例，避免其他协程观察到
    半初始化客户端。构造或探测失败会尽力关闭临时客户端并清空状态。
    """
    global _milvus_client, _milvus_settings

    if not settings.enabled:
        logger.info("Milvus 已通过配置禁用，跳过初始化")
        return
    if _milvus_client is not None:
        logger.warning("Milvus 客户端已初始化，跳过重复初始化")
        return

    client: Optional[AsyncMilvusClient] = None
    try:
        client = build_milvus_client(settings)
        await client.list_collections(timeout=settings.timeout)
    except Exception as exc:  # noqa: BLE001 —— SDK 的构造/传输异常类型不统一
        if client is not None:
            try:
                await client.close()
            except Exception as close_exc:  # noqa: BLE001 —— 降级清理不得掩盖根因
                logger.warning(
                    "Milvus 初始化失败后的临时客户端关闭失败 | reason_type={}",
                    close_exc.__class__.__name__,
                )
        _milvus_client = None
        _milvus_settings = None
        logger.warning(
            "Milvus 连接失败，向量库降级运行 | uri={} | db={} | reason_type={}",
            _safe_uri(settings.uri),
            settings.db_name,
            exc.__class__.__name__,
        )
        return

    _milvus_client = client
    _milvus_settings = settings
    logger.info(
        "Milvus 客户端已初始化 | uri={} | db={}",
        _safe_uri(settings.uri),
        settings.db_name,
    )


def get_milvus() -> AsyncMilvusClient:
    """获取已完成探测的客户端；不可用时快速失败。"""
    if _milvus_client is None:
        raise BizException(
            message="Milvus 客户端未初始化或已降级",
            errno=MILVUS_ERRNO_NOT_INITIALIZED,
        )
    return _milvus_client


def get_milvus_optional() -> Optional[AsyncMilvusClient]:
    """获取客户端；未初始化、已禁用或降级时返回 ``None``。"""
    return _milvus_client


def get_milvus_settings() -> MilvusSettings:
    """获取当前客户端使用的配置；客户端不可用时快速失败。"""
    if _milvus_settings is None:
        raise BizException(
            message="Milvus 客户端未初始化或已降级",
            errno=MILVUS_ERRNO_NOT_INITIALIZED,
        )
    return _milvus_settings


async def close_milvus() -> None:
    """幂等关闭客户端并清空进程级状态。"""
    global _milvus_client, _milvus_settings

    client = _milvus_client
    if client is None:
        _milvus_settings = None
        return

    try:
        await client.close()
        logger.info("Milvus 客户端已关闭")
    except Exception as exc:  # noqa: BLE001 —— 统一转项目异常供清理器汇总
        logger.error("Milvus 客户端关闭失败 | reason_type={}", exc.__class__.__name__)
        raise BizException(
            message="Milvus 客户端关闭失败",
            errno=MILVUS_ERRNO_OPERATION_FAILED,
        ) from exc
    finally:
        _milvus_client = None
        _milvus_settings = None

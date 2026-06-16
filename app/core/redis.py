"""Redis 异步连接池（进程级单例）。

设计要点：
- **单例连接池**：进程级共享一个 ``redis.asyncio.Redis`` 实例，复用连接池。
  ``get_redis()`` 惰性创建单例，参考 ``app/utils/http_client.py`` 模式。
- **参数配置驱动**：连接 URL、数据库编号、连接池上限、解码响应等均来自
  ``RedisSettings`` 配置段。
- **失败转业务异常**：连接失败等异常统一抛 ``BizException``，由全局 handler
  转成统一响应；禁止裸 raise Exception。
- **lifespan 接入**：应用启动时调用 ``init_redis`` 建立连接，关闭时调用
  ``close_redis`` 释放连接池。

注意：需在应用关闭时调用 ``close_redis()`` 关闭单例（factory.py lifespan 已接入）。
"""
from typing import Optional

import redis.asyncio

from app.core.logger import logger
from app.core.settings import RedisSettings
from app.exceptions import BizException

# 进程级单例 Redis 客户端；None 表示尚未创建。多 worker 进程各自独立持有，
# asyncio 单线程内无并发竞争，故无需锁。
_redis_client: Optional[redis.asyncio.Redis] = None


def _build_client(settings: RedisSettings) -> redis.asyncio.Redis:
    """按 RedisSettings 构造一个异步 Redis 客户端（含连接池）。

    仅在首次 ``init_redis`` 调用时执行；后续直接复用单例。
    单独拆函数便于测试时显式构造验证参数与配置一致。

    Args:
        settings: Redis 配置段，含 url/db/max_connections/decode_responses/encoding。

    Returns:
        配置好的 ``redis.asyncio.Redis`` 实例。
    """
    # 连接池配置：max_connections 控制上限，防 Redis 被打爆
    pool = redis.ConnectionPool.from_url(
        settings.url,
        db=settings.db,
        max_connections=settings.max_connections,
        decode_responses=settings.decode_responses,
        encoding=settings.encoding,
    )
    return redis.asyncio.Redis(connection_pool=pool)


async def init_redis(settings: RedisSettings) -> None:
    """初始化 Redis 单例连接池（应用启动时调用）。

    建立连接并验证连通性（PING）；失败抛 BizException 导致启动失败（fail-fast）。

    Args:
        settings: Redis 配置段，来自 ``get_settings().redis``。

    Raises:
        BizException: 连接失败或 PING 不通。
    """
    global _redis_client
    if _redis_client is not None:
        logger.warning("Redis 客户端已初始化，跳过重复初始化")
        return

    try:
        _redis_client = _build_client(settings)
        # 验证连通性
        await _redis_client.ping()
        logger.info("Redis 连接池已初始化: {}", settings.url)
    except (redis.ConnectionError, redis.TimeoutError, OSError) as exc:
        raise BizException(
            f"Redis 连接失败: {settings.url}，原因: {exc.__class__.__name__}: {exc}"
        ) from exc


async def close_redis() -> None:
    """关闭 Redis 单例连接池（应用关闭时调用）。

    需在 factory.py lifespan shutdown 时调用，确保连接池优雅释放。
    """
    global _redis_client
    if _redis_client is not None:
        await _redis_client.close()
        _redis_client = None
        logger.info("Redis 连接池已关闭")


def get_redis() -> redis.asyncio.Redis:
    """获取进程级单例 Redis 客户端。

    多次调用返回同一实例，复用底层连接池。缓存层不应自行
    ``redis.asyncio.Redis()``。

    Returns:
        已初始化的 ``redis.asyncio.Redis`` 实例。

    Raises:
        RuntimeError: 若 ``init_redis`` 未被调用（客户端为 None）。
    """
    if _redis_client is None:
        raise RuntimeError("Redis 客户端未初始化，请先调用 init_redis()")
    return _redis_client

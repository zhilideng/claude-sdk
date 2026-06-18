"""全局异步 HTTP 客户端（基于 httpx.AsyncClient 的生产级封装）。

设计要点：
- **单例 client**：进程级共享一个 ``httpx.AsyncClient``，复用连接池，禁止
  每次请求 new client 造成连接泄漏。``get_client()`` 惰性创建单例。
- **参数写死**：超时（四阶段）、连接池上限、TLS 校验、默认 UA、重试策略全部以
  模块级常量写死，**不进配置文件**——现阶段无真实流量，按环境精细调优属过早
  优化；将来需要差异化（如 prod 放大连接池、test 收敛超时）再改为配置驱动。
- **重试**：仅对①网络类异常（``httpx.TransportError`` 及子类）②幂等方法
  （GET/HEAD/OPTIONS/PUT/DELETE）③响应状态码命中 ``_DEFAULT_RETRY_ON_STATUS``
  三者同时满足时重试。指数退避 ``factor * 2**n``（n 从 0 起），最多
  ``_DEFAULT_MAX_RETRIES`` 次。非幂等方法（POST/PATCH）一律不重试。
- **失败转业务异常**：重试用尽仍失败（网络异常或最终非 2xx），统一抛
  ``BizException``，由全局 handler 转成统一 ApiResponse；禁止裸 raise Exception。
- **统一日志**：每次请求记 method+url，响应记 status+耗时(ms)，重试记
  第几次+原因+等待秒。

注意：需在应用关闭时调用 ``close_client()`` 关闭单例（已接入 server.py
lifespan shutdown）。
"""
import asyncio
from typing import Optional

import httpx

from app.core.logger import logger
from app.exceptions import BizException

# —— HTTP 客户端默认参数（写死，不进配置文件）——
# 现阶段无真实流量，这些是合理的生产级默认。将来需要按环境调优
# （如 prod 放大 max_connections、test 收敛 timeout）再改为配置驱动。
_DEFAULT_TIMEOUT: float = 30.0  # 请求总超时秒
_DEFAULT_CONNECT_TIMEOUT: float = 5.0  # 建连超时秒（含 DNS + TCP 握手）
_DEFAULT_READ_TIMEOUT: float = 30.0  # 读取响应超时秒
_DEFAULT_WRITE_TIMEOUT: float = 30.0  # 发送请求超时秒
_DEFAULT_POOL_TIMEOUT: float = 5.0  # 连接池取连接等待秒（池满背压）
_DEFAULT_MAX_CONNECTIONS: int = 100  # 连接池上限（防下游被打爆）
_DEFAULT_MAX_KEEPALIVE_CONNECTIONS: int = 20  # 空闲 keepalive 连接上限
_DEFAULT_KEEPALIVE_EXPIRY: float = 30.0  # keepalive 空闲过期秒
_DEFAULT_MAX_RETRIES: int = 3  # 最大重试次数（仅网络错误 + 幂等方法 + 命中状态码）
_DEFAULT_RETRY_BACKOFF_FACTOR: float = 0.5  # 指数退避基数（第 n 次等待 ≈ factor * 2**n）
_DEFAULT_RETRY_ON_STATUS: tuple[int, ...] = (429, 500, 502, 503, 504)  # 触发重试的状态码
_DEFAULT_VERIFY: bool = True  # 是否校验 TLS 证书（生产保持 True）
_DEFAULT_USER_AGENT: str = "arch-fastapi-http-client/1.0"  # 默认 UA（可被请求级头覆盖）

# 幂等方法集合：这些方法对同一资源多次执行结果一致，可安全重试。
# POST/PATCH 等非幂等方法不在此列，即使失败也只执行一次（重试可能导致重复写入）。
_IDEMPOTENT_METHODS = frozenset({"GET", "HEAD", "OPTIONS", "PUT", "DELETE"})

# 进程级单例 client；None 表示尚未创建。多 worker 进程各自独立持有，
# asyncio 单线程内无并发竞争，故无需锁。
_client: Optional[httpx.AsyncClient] = None


def _build_client() -> httpx.AsyncClient:
    """按模块级默认参数构造一个 AsyncClient。

    仅在首次 ``get_client()`` 调用时执行；后续直接复用单例。
    单独拆函数便于测试时显式构造验证 timeout/limits 与默认常量一致。
    """
    # 五阶段超时：总 + 建连/读/写/池。pool=取连接等待上限，配合 Limits 做背压。
    timeout = httpx.Timeout(
        _DEFAULT_TIMEOUT,
        connect=_DEFAULT_CONNECT_TIMEOUT,
        read=_DEFAULT_READ_TIMEOUT,
        write=_DEFAULT_WRITE_TIMEOUT,
        pool=_DEFAULT_POOL_TIMEOUT,
    )
    # 连接池上限：max_connections 防下游被打爆；max_keepalive 控空闲复用。
    limits = httpx.Limits(
        max_connections=_DEFAULT_MAX_CONNECTIONS,
        max_keepalive_connections=_DEFAULT_MAX_KEEPALIVE_CONNECTIONS,
        keepalive_expiry=_DEFAULT_KEEPALIVE_EXPIRY,
    )
    # 默认头注入 UA；请求级 headers 仍可覆盖。
    headers = {"User-Agent": _DEFAULT_USER_AGENT}

    return httpx.AsyncClient(
        timeout=timeout,
        limits=limits,
        headers=headers,
        verify=_DEFAULT_VERIFY,
    )


def get_client() -> httpx.AsyncClient:
    """获取进程级单例 AsyncClient（惰性创建）。

    多次调用返回同一实例，复用底层连接池。请求层不应自行 ``httpx.AsyncClient()``。
    """
    global _client
    if _client is None:
        _client = _build_client()
    return _client


async def close_client() -> None:
    """关闭单例 client 并置空。

    需在应用关闭（lifespan shutdown）时调用，确保底层连接池优雅释放。
    已由 ``app.server.lifespan`` shutdown 统一调用。
    """
    global _client
    if _client is not None:
        await _client.aclose()
        _client = None


def _should_retry_status(status_code: int) -> bool:
    """判断响应状态码是否应触发重试（命中 _DEFAULT_RETRY_ON_STATUS）。"""
    return status_code in _DEFAULT_RETRY_ON_STATUS


async def request(method: str, url: str, **kwargs) -> httpx.Response:
    """执行带重试 / 日志 / 异常转换的 HTTP 请求。

    流程：
    1. 循环最多 ``_DEFAULT_MAX_RETRIES + 1`` 次（首次 + 重试次数）；
    2. 每次发请求记日志，响应记 status+耗时(ms)；
    3. 命中重试条件（幂等 + 网络异常或命中状态码）→ 退避后重试；
    4. 非幂等方法或重试用尽 → 转 ``BizException`` 抛出。

    Args:
        method: HTTP 方法（大小写不敏感，内部统一大写比较）。
        url: 目标 URL。
        **kwargs: 透传给 ``httpx.AsyncClient.request``（headers/params/json 等）。

    Returns:
        成功的 ``httpx.Response``（2xx）。

    Raises:
        BizException: 重试用尽仍失败（网络异常或最终非 2xx）。
    """
    method_upper = method.upper()
    is_idempotent = method_upper in _IDEMPOTENT_METHODS
    max_retries = _DEFAULT_MAX_RETRIES
    client = get_client()

    # attempt 从 0 计；当 attempt < max_retries 且判定可重试时进入退避。
    attempt = 0
    last_status: Optional[int] = None
    last_exc: Optional[BaseException] = None

    while True:
        started = asyncio.get_event_loop().time()
        try:
            logger.info("HTTP {} {} -> 发起请求", method_upper, url)
            resp = await client.request(method_upper, url, **kwargs)
        except httpx.TransportError as exc:
            # 网络类异常（ConnectError/ReadTimeout/PoolTimeout 等均是其子类）。
            elapsed_ms = int((asyncio.get_event_loop().time() - started) * 1000)
            logger.warning(
                "HTTP {} {} -> 异常 {} ({}ms)", method_upper, url, exc.__class__.__name__, elapsed_ms
            )
            last_status = None
            last_exc = exc
            # 非幂等方法不重试：直接转业务异常
            if not is_idempotent or attempt >= max_retries:
                raise BizException(
                    f"HTTP 请求异常: {method_upper} {url} 原因: {exc.__class__.__name__}: {exc}"
                ) from exc
            # 命中网络异常 + 幂等 + 未用尽重试 → 退避重试
        else:
            elapsed_ms = int((asyncio.get_event_loop().time() - started) * 1000)
            logger.info(
                "HTTP {} {} -> {} ({}ms)", method_upper, url, resp.status_code, elapsed_ms
            )
            last_status = resp.status_code
            last_exc = None
            # 2xx 成功直接返回
            if 200 <= resp.status_code < 300:
                return resp
            # 非 2xx：判断是否需重试（幂等 + 状态码命中 + 未用尽）
            if not is_idempotent or not _should_retry_status(resp.status_code) or attempt >= max_retries:
                # 不可重试或用尽：转业务异常
                raise BizException(
                    f"HTTP 请求失败: {method_upper} {url} -> {resp.status_code}",
                    errno=resp.status_code,
                )

        # 到这里说明需要重试（attempt < max_retries，且命中网络异常或 retry 状态码）
        wait = _DEFAULT_RETRY_BACKOFF_FACTOR * (2 ** attempt)
        reason = (
            f"异常 {last_exc.__class__.__name__}"
            if last_exc is not None
            else f"状态码 {last_status}"
        )
        logger.info(
            "HTTP {} {} -> 第 {} 次重试，原因: {}，等待 {:.3f}s",
            method_upper,
            url,
            attempt + 1,
            reason,
            wait,
        )
        await asyncio.sleep(wait)
        attempt += 1


async def get(url: str, **kwargs) -> httpx.Response:
    """GET 便捷封装。"""
    return await request("GET", url, **kwargs)


async def post(url: str, **kwargs) -> httpx.Response:
    """POST 便捷封装（非幂等，不重试）。"""
    return await request("POST", url, **kwargs)


async def put(url: str, **kwargs) -> httpx.Response:
    """PUT 便捷封装。"""
    return await request("PUT", url, **kwargs)


async def delete(url: str, **kwargs) -> httpx.Response:
    """DELETE 便捷封装。"""
    return await request("DELETE", url, **kwargs)


async def patch(url: str, **kwargs) -> httpx.Response:
    """PATCH 便捷封装（非幂等，不重试）。"""
    return await request("PATCH", url, **kwargs)

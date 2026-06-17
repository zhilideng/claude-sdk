"""访问日志（Access Log）中间件。

在请求生命周期内（request_id contextvar 活跃区间）自行打印访问日志，统一
接管「请求-响应」记录，故关闭 uvicorn 自带 access log
（``AppSettings.access_log = False``，见 ``app/core/server.py``）。

为何不用 uvicorn 自带 access log：
uvicorn 的 access log 在 ASGI app（含全部中间件）返回后才打印，而此刻
``RequestIDMiddleware`` 已在 ``finally`` 中把 request_id contextvar reset 掉，
导致 ``app/core/logger.py`` 的 patcher 注入的 request_id 恒为 ``-``，无法
用于全链路追踪。本中间件把访问日志的打印时机移到 ``call_next`` 返回后、
contextvar 仍活跃的区间，从而带上真实 request_id，并顺带记录请求耗时
（生产排障刚需）。

每条访问日志格式（仿 uvicorn + 耗时）：
    {client} - "{method} {path} HTTP/1.1" {status} {duration_ms:.1f}ms
request_id 由 ``app/core/logger.py`` 的 patcher 自动注入（dev 格式 ``[req_id=xxx]``，
prod JSON 的 ``request_id`` 字段）。

注册顺序（见 ``startup.register_middlewares``）：
必须在 ``RequestID`` 中间件**内层**——即 ``add_middleware`` 调用在
``setup_request_id`` **之前**。因 starlette 后注册的中间件位于更外层，RequestID
在最外层 set id 后，本中间件的 dispatch 才跑在「已 set id」的上下文副本里、
读得到 request_id。
"""
import time

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logger import logger


class AccessLogMiddleware(BaseHTTPMiddleware):
    """访问日志中间件。

    处理流程：
    1. 记录请求起点（``time.perf_counter`` 单调时钟，不受系统时间回拨影响）；
    2. ``call_next`` 执行后续中间件 / 路由；
    3. 无论成功或异常，在 ``finally`` 中打印一条访问日志（异常时 status 记 500），
       便于审计异常请求。
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        # 计时起点（单调时钟，性能稳定且不受 wall-clock 回拨干扰）
        start = time.perf_counter()
        # 客户端地址（IP:port；client 可能为 None，如 unix socket 场景）
        client = (
            f"{request.client.host}:{request.client.port}"
            if request.client
            else "-"
        )
        method = request.method
        path = request.url.path
        # 异常时记 500，正常响应取真实状态码（finally 兜底覆盖）
        status = 500
        try:
            response = await call_next(request)
            status = response.status_code
            return response
        finally:
            duration_ms = (time.perf_counter() - start) * 1000
            logger.info(
                '{client} - "{method} {path} HTTP/1.1" {status} {duration_ms:.1f}ms',
                client=client,
                method=method,
                path=path,
                status=status,
                duration_ms=duration_ms,
            )


def setup_access_log(app: FastAPI) -> None:
    """为 FastAPI 应用注册 AccessLog 中间件。

    必须在 ``setup_request_id`` **之前**调用（使其位于 RequestID 内层、能读到
    request_id），由 ``startup.register_middlewares`` 在「路由→异常→中间件」
    注册链调用。
    """
    app.add_middleware(AccessLogMiddleware)
    logger.info("AccessLog 中间件已注册 | 接管访问日志（关闭 uvicorn access_log）")

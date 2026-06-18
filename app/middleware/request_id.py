"""请求追踪（RequestID）中间件。

每个 HTTP 请求自动生成或透传唯一 request_id，贯穿日志与响应头，
便于全链路追踪与生产问题排查。

策略写死（各环境一致），不进配置：
- 入站：从请求头 ``X-Request-Id`` 读取；若无则用 ``uuid.uuid4().hex`` 生成
  （hex 格式无连字符，32 字符，便于日志解析与 HTTP 头传输）。
- 存入 ``contextvars.ContextVar``（请求级别上下文），供整个请求生命周期访问。
- 出站：响应头回写 ``X-Request-Id``（实际使用的 id，透传或新生成）。

使用方式：
- 中间件注册：由 ``app.server.register_middlewares`` 调用 ``setup_request_id(app)``。
- 读取当前请求 id：调用 ``get_request_id()``（异步安全，返回 str | None）。
"""
import contextvars
import uuid

from fastapi import FastAPI, Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.logger import logger

# ContextVar 存储当前请求的 request_id
# 使用 None 作为默认值，表示请求外无 id
_request_id_context: contextvars.ContextVar[str | None] = contextvars.ContextVar(
    "request_id", default=None
)


def get_request_id() -> str | None:
    """获取当前请求的 request_id。

    异步安全：从 ContextVar 读取，返回请求范围内唯一的 id（或 None）。
    可在任意业务代码、日志、异常处理器中调用，无需参数传递。

    Returns:
        str | None：当前请求的 request_id；若在请求上下文外则为 None。
    """
    return _request_id_context.get()


class RequestIDMiddleware(BaseHTTPMiddleware):
    """请求追踪中间件。

    处理流程：
    1. 入站：读请求头 ``X-Request-Id``；缺失则用 ``uuid.uuid4().hex`` 生成。
    2. 把 id 存入 ContextVar（请求级别上下文，线程/协程隔离）。
    3. 出站：响应头回写 ``X-Request-Id``（实际使用的 id）。
    """

    async def dispatch(self, request: Request, call_next) -> Response:
        """处理请求并注入 request_id。"""
        # 1. 入站：读请求头或生成新 id
        incoming_id = request.headers.get("X-Request-Id")
        if incoming_id:
            # 透传客户端传入的 id（信任其格式，不校验 hex uuid）
            request_id = incoming_id
        else:
            # 无入站头，生成新 id（hex 格式无连字符，32 字符）
            request_id = uuid.uuid4().hex

        # 2. 存入 ContextVar（请求生命周期内可访问）
        token = _request_id_context.set(request_id)

        try:
            # 3. 调用后续中间件/路由处理
            response = await call_next(request)
            # 4. 出站：响应头回写实际使用的 id
            response.headers["X-Request-Id"] = request_id
            return response
        finally:
            # 5. 清理 ContextVar（避免内存泄漏；虽请求结束会自动 GC，显式 reset 为好实践）
            _request_id_context.reset(token)


def setup_request_id(app: FastAPI) -> None:
    """为 FastAPI 应用注册 RequestID 中间件（策略写死，不进配置）。

    中间件顺序（在 ``app.server.register_middlewares`` 中）：
    - RequestID 在 CORS 之后注册（CORS 先处理预检，RequestID 再生成 id）。
    - RequestID 在业务中间件（如 JWT/限流）之前注册，确保日志尽早带 id。

    作为中间件，由 ``app.server.register_middlewares`` 在「路由→异常→中间件」
    注册链调用。
    """
    app.add_middleware(RequestIDMiddleware)
    logger.info("RequestID 中间件已注册 | 策略=写死 | 头=X-Request-Id")

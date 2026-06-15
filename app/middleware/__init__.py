"""中间件集合包。

集中收纳所有横向中间件（跨域 / JWT / TraceId / 限流 等），由
``app.startup.register_middlewares`` 统一注册。新增中间件建议在本 ``__init__``
导出对应 ``setup_xxx`` 函数，保持调用方 import 路径稳定。

当前已实现：
- ``cors.setup_cors`` —— CORS 中间件（基于 starlette CORSMiddleware，策略写死全放行）。
"""
from app.middleware.cors import setup_cors

__all__ = ["setup_cors"]

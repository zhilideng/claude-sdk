"""跨域资源共享（CORS）中间件封装。

基于 ``starlette.middleware.cors.CORSMiddleware``。当前阶段跨域策略统一
「全放行」（dev/test/prod 一致），无需配置驱动，故策略直接写死于本文件，
不进 configs yaml——避免为永不变化的值做配置抽象（YAGNI）。

写死的策略：
- ``allow_origins=["*"]`` —— 任意来源；
- ``allow_methods=["*"]`` / ``allow_headers=["*"]`` —— 全方法 / 全头；
- ``allow_credentials=False`` —— 不带凭证；
- ``max_age=600`` —— 预检缓存 10 分钟。

安全说明：``allow_origins=["*"]`` 与 ``allow_credentials=True`` 是浏览器拒绝的
非法组合，故 credentials 固定为 False。**将来上生产若需把来源收敛为具体域名
清单（安全合规）**，应把本中间件改回配置驱动（新增 ``CorsSettings`` + yaml 段），
届时若要放开 ``allow_credentials`` 也必须保证 origins 非通配。
"""
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from app.core.logger import logger


def setup_cors(app: FastAPI) -> None:
    """为 FastAPI 应用注册 CORS 中间件（全放行策略，写死）。

    作为中间件，由 ``startup.register_middlewares`` 在「路由→异常→中间件」
    注册链的最后阶段调用，确保异常 handler 优先级高于跨域处理。
    """
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_methods=["*"],
        allow_headers=["*"],
        allow_credentials=False,
        expose_headers=[],
        max_age=600,
    )
    logger.info("CORS 中间件已注册 | 策略=全放行 | credentials=False")

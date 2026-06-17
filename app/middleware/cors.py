"""跨域资源共享（CORS）中间件封装。

基于 ``starlette.middleware.cors.CORSMiddleware``。策略由 ``CorsSettings``
配置段驱动，各环境在 ``configs/{dev,test,prod}.yaml`` 的 ``cors`` 段按需收敛：
- dev/test：全放行（``allow_origins=["*"]``），开发友好；
- prod：收敛为明确域名 / 方法 / 头部白名单（安全合规）。

安全约束：``allow_origins=["*"]`` 与 ``allow_credentials=True`` 是浏览器拒绝的
非法组合——故 dev/test 全放行时 credentials 须固定 False；prod 收敛为具体域名后
若需放开 credentials，必须保证 origins 不含通配 ``*``。字段含义与环境变量覆盖
方式见 ``CorsSettings``（list 字段经环境变量注入须用 JSON 数组格式）。
"""
from fastapi import FastAPI
from starlette.middleware.cors import CORSMiddleware

from app.core.logger import logger
from app.core.settings import CorsSettings


def setup_cors(app: FastAPI, cors: CorsSettings) -> None:
    """为 FastAPI 应用注册 CORS 中间件（策略由 ``CorsSettings`` 驱动）。

    作为中间件，由 ``startup.register_middlewares`` 在「路由→异常→中间件」
    注册链的最后阶段调用，确保异常 handler 优先级高于跨域处理。

    各字段含义见 ``CorsSettings``：``allow_origins`` 决定来源白名单，
    ``allow_methods``/``allow_headers`` 收敛方法与请求头，``expose_headers``
    控制前端可读的响应头，``allow_credentials`` 控制是否带凭证，
    ``max_age`` 预检缓存秒数。
    """
    app.add_middleware(
        CORSMiddleware,
        allow_origins=cors.allow_origins,
        allow_methods=cors.allow_methods,
        allow_headers=cors.allow_headers,
        allow_credentials=cors.allow_credentials,
        expose_headers=cors.expose_headers,
        max_age=cors.max_age,
    )
    # origins 含通配即视为全放行，便于日志快速辨识当前策略
    all_open = "*" in cors.allow_origins
    logger.info(
        "CORS 中间件已注册 | origins={} | methods={} | headers={} | "
        "credentials={} | expose={} | max_age={} | all_open={}",
        cors.allow_origins, cors.allow_methods, cors.allow_headers,
        cors.allow_credentials, cors.expose_headers, cors.max_age, all_open,
    )

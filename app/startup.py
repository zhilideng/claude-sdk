"""启动注册：集中加载配置、注册路由与中间件。

新增模块的注册点统一放此处，保持 factory.create_app 简洁。
"""
from fastapi import FastAPI
from app.api.routes import register_routes
from app.core.config import Settings, get_settings
from app.core.logger import intercept_uvicorn_logs, logger, setup_logging
from app.exceptions import register_exception_handlers as register_exception
from app.middleware.access_log import setup_access_log
from app.middleware.cors import setup_cors
from app.middleware.request_id import setup_request_id

def load_config() -> Settings:
    """启动时加载配置（fail-fast）。

    - 触发 get_settings()：若 APP_ENV 非法 / yaml 缺失 / 字段校验失败，
      在此直接抛错，进程启动失败，而非拖到运行时第一次请求才暴雷；
    - 初始化日志（按 settings.app.log_level）；
    - 打印生效配置，便于启动期排查（当前 app 段无敏感字段，可直接打印）。
    """
    settings = get_settings()
    setup_logging(settings.logging)
    # 把 uvicorn 日志接入 loguru，应用日志与访问/错误日志格式统一
    intercept_uvicorn_logs(level=settings.app.log_level)
    app_cfg = settings.app
    logger.info(
        "配置加载完成 | env={} | name={} | host={} | port={} | debug={} | log_level={}",
        app_cfg.env, app_cfg.name, app_cfg.host, app_cfg.port,
        app_cfg.debug, app_cfg.log_level,
    )
    return settings


def register_routers(app: FastAPI) -> None:
    """注册 API 路由。

    薄封装：转调 ``app.api.routes.register_routes``，保持本文件作为
    「所有注册点单一清单」的风格，与 register_exception_handlers / register_middlewares 同形。
    实际路由清单（include_router 调用）集中在 ``app/api/routes.py``。
    """
    register_routes(app)


def register_exception_handlers(app: FastAPI) -> None:
    """注册全局异常处理器（统一响应格式 + 500 兜底脱敏）。

    薄封装：内部转调 app.exceptions 的实现，保持本文件作为「所有注册点单一清单」
    的风格，与 register_routers / register_middlewares 同形。
    """
    register_exception(app)


def register_middlewares(app: FastAPI) -> None:
    """注册中间件（作为「路由→异常→中间件」注册链的最后阶段）。

    注册顺序（starlette 语义：``add_middleware`` 后注册者位于更**外层**，
    故请求进入顺序 = 下面自下而上的逆序 → RequestID 最外、CORS 最内）：
    1. CORS（最先 add → 最内层）—— 预检 OPTIONS 在此处理并直接返回。
    2. AccessLog（中间层，须在 RequestID 内层）—— 在 request_id contextvar
       活跃时打访问日志（带 method/path/status/耗时），接管 uvicorn access log。
    3. RequestID（最后 add → 最外层）—— 尽早 set request_id，确保下游所有日志
       （含 AccessLog）都能带上 id；响应头回写 X-Request-Id。

    已接入：
    - CORS 跨域中间件（全放行策略，见 ``app/middleware/cors.py``）；
    - AccessLog 访问日志中间件（见 ``app/middleware/access_log.py``）；
    - RequestID 追踪中间件（见 ``app/middleware/request_id.py``）。

    待加：
    - JWT 认证 / 限流等业务中间件。
    """
    setup_cors(app)
    setup_access_log(app)
    setup_request_id(app)

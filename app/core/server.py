"""服务器运行层：把 AppSettings 翻译为 uvicorn 启动参数并运行。

与 ``main.py`` 的「入口」职责分离：本模块专注 uvicorn 进程级配置
（workers / 事件循环 / 并发上限 / keep-alive 等运维调优），main.py 只负责
触发启动，不承载运维参数解析。

职责边界：
- 开发（env=dev）：reload=True 单进程热重载，调优参数走默认；
- 生产（env=prod）：reload=False，按 AppSettings 起 multi-worker。
  容器化部署亦可改用 gunicorn + UvicornWorker 外置进程管理。

**factory 模式**：定位串指向工厂函数 ``app.factory:create_app`` + ``factory=True``，
由 uvicorn 自行调用工厂创建 app（而非 import 模块取 ``app`` 属性）。如此 ``main``
模块不含模块级 ``app = create_app()`` 副作用，避免 ``python main.py`` 入口下
``__main__`` / ``"main"`` 双重导入叠加 reload 多进程导致 ``create_app()`` 重复执行
（实测中间件注册 4 次）。
"""
import multiprocessing

import uvicorn

from app.core.config import get_settings

# ASGI app 工厂定位串（factory 模式）：reload 模式必须传字符串（不能传对象），
# 非 reload 亦可，统一用此常量最稳。指向 create_app 工厂函数，配合下方 factory=True，
# 由 uvicorn 按进程显式调用一次创建 app。
_APP_IMPORT_STRING = "app.factory:create_app"


def _resolve_workers(configured: int | None) -> int:
    """解析 worker 进程数。

    显式配置（>0）则用配置值；否则按经验取 min(cpu*2, 4)
    （IO 密集型 cpu*2，上限 4 防进程争抢）。
    """
    if configured and configured > 0:
        return configured
    return min(multiprocessing.cpu_count() * 2, 4)


def _resolve_loop(configured: str) -> str:
    """解析事件循环。

    auto：优先 uvloop（性能更好），未安装则回退 asyncio；
    显式 uvloop / asyncio 则按指定。
    """
    if configured == "auto":
        try:
            import uvloop  # noqa: F401
        except ImportError:
            return "asyncio"
        return "uvloop"
    return configured


def run() -> None:
    """按配置驱动启动 uvicorn 服务。"""
    app_cfg = get_settings().app
    # reload 仅 dev 开：与多 workers 互斥，生产必须关
    reload = app_cfg.env == "dev"
    uvicorn.run(
        app=_APP_IMPORT_STRING,
        factory=True,  # factory 模式：uvicorn 调 create_app 创建 app，避免模块级副作用致 create_app 重复执行
        host=app_cfg.host,
        port=app_cfg.port,
        reload=reload,
        # reload 模式下 workers 由 uvicorn 忽略（强制单进程），生产才解析
        workers=None if reload else _resolve_workers(app_cfg.workers),
        loop=_resolve_loop(app_cfg.loop),
        limit_concurrency=app_cfg.limit_concurrency,
        timeout_keep_alive=app_cfg.timeout_keep_alive,
        access_log=app_cfg.access_log,
        log_level=app_cfg.log_level.lower(),
    )

"""应用入口。

**factory 模式**：本模块不再模块级创建 app，仅导出 ``create_app`` 工厂函数，由
uvicorn 以 ``--factory`` 显式调用创建（定位串 ``app.factory:create_app``）。

为何不模块级 ``app = create_app()``：``create_app()`` 有副作用（注册路由/中间件/
异常 handler）。若模块级执行，以 ``python main.py`` 启动时 main 作为 ``__main__``
加载执行一次，随后 uvicorn ``import_from_string`` 又因 ``sys.modules["main"]`` 缺失
重新执行 main 模块一次，叠加 reload 多进程，会导致 ``create_app()`` 在导入期被多次
执行（实测中间件注册 4 次）。factory 模式下 import main 无副作用，app 仅由 uvicorn
按进程显式创建一次。

uvicorn 进程级启动逻辑（workers / loop / 并发等运维调优）收敛在
``app/core/server.py``，本文件只负责触发启动。
"""
from app.core.server import run
from app.factory import create_app

__all__ = ["create_app"]  # 供 uvicorn main:create_app --factory 加载


if __name__ == "__main__":
    run()

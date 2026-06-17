"""v1 版本业务路由聚合层。

集中把 ``app/api/v1/`` 下各业务路由模块挂到 app 上，统一加 ``/v1`` 前缀。
由 ``app/api/routes.py`` 的 ``register_routes`` 调用，保持「路由清单单一入口」约定。

新增业务路由约定：
- 路由模块放 ``app/api/vN/<biz>.py``，各自定义 ``router``（含自己的 ``/<biz>`` 前缀）；
- 在本函数内 ``app.include_router(<biz>.router, prefix="/v1")`` 挂载；
- 无需在 ``routes.py`` 改动，自动随版本聚合（符合 CLAUDE.md「版本化扩展点」设计）。
"""
from fastapi import FastAPI

from app.api.v1 import users


def register_v1_routes(app: FastAPI) -> None:
    """注册 v1 版本全部业务路由（统一 /v1 前缀）。"""
    app.include_router(users.router, prefix="/v1")

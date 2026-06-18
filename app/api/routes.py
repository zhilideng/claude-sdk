"""路由聚合层：集中注册所有 API 路由。

职责单一——只负责把各路由模块的 router 挂到 app 上（include_router 调用）。
由 ``app.server.create_app`` 调用，本文件专职维护路由清单。

新增路由约定：
- 基础设施端点（健康检查等，无版本前缀）直接在 ``register_routes`` 内 include；
- 业务路由模块放 ``app/api/vN/<biz>_router.py``（``vN`` 为 namespace package，
  无 ``__init__.py``），每个文件内定义 ``router = APIRouter(...)``；在 ``register_routes``
  内直接 ``from app.api.vN.<biz>_router import router as <biz>_router`` 后
  ``app.include_router(<biz>_router, prefix="/vN")`` 逐个挂载（不再用聚合函数）。
"""
from fastapi import FastAPI

from app.api.health import router as health_router
from app.api.v1.users_router import router as users_router


def register_routes(app: FastAPI) -> None:
    """注册全部 API 路由。

    - 基础设施路由（无版本前缀：探针/指标等固定路径）直接 include；
    - 业务路由：各业务在 ``app/api/vN/<biz>_router.py`` 定义 ``router``，此处逐个
      ``app.include_router(<biz>_router, prefix="/vN")`` 挂载（不再用 register_vN_routes 聚合）。
    """
    # 基础设施路由（无版本前缀：探针/指标等固定路径）
    app.include_router(health_router)
    app.include_router(users_router, prefix="/v1")


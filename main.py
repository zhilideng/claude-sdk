"""应用入口。

本模块保持无副作用：只导出 ``create_app`` 工厂函数，并在直接执行时调用
``run()``。应用组装、lifespan 与 uvicorn 启动参数统一收敛在 ``app.server``。
"""
from app.server import create_app, run

__all__ = ["create_app"]  # 供 uvicorn main:create_app --factory 加载


if __name__ == "__main__":
    run()

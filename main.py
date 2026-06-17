"""应用入口。

模块级 ``app`` 供 ``uvicorn main:app`` 加载；uvicorn 进程级启动逻辑
（workers / loop / 并发等运维调优）收敛在 ``app/core/server.py``，
本文件只负责暴露 app 与触发启动，不承载运维参数解析。
"""
from app.core.server import run
from app.factory import create_app

app = create_app()



if __name__ == "__main__":
    run()

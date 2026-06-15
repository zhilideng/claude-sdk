"""工具包入口。

统一导出全局异步 HTTP 客户端封装，业务层可：
    from app.utils import get_client, request, get, post
无需关心内部文件组织。
"""
from app.utils.http_client import (
    close_client,
    delete,
    get,
    get_client,
    patch,
    post,
    put,
    request,
)

__all__ = [
    "get_client",
    "close_client",
    "request",
    "get",
    "post",
    "put",
    "delete",
    "patch",
]

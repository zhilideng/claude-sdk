"""业务异常体系。

设计要点：
- ``BizException`` 为业务异常基类，``status_code``/``errno``/``message`` 均为类属性，
  子类只需覆盖这三个值即可定义一类业务异常，零样板；
- 构造时可传 ``message`` / ``errno`` 覆盖默认值——既支持「抛出即用默认消息」，
  也支持「调用方补充具体上下文」；
- errno 命名约定：「HTTP码前缀 + 0」便于记忆（404 -> 10404）；后续业务自定义码
  走 1xxxx 业务段，避免与 HTTP 类混淆。仅约定，不强制校验。

业务层统一 ``raise BizNotFoundError(...)``，由 ``handlers.py`` 的全局处理器转成
统一响应，业务代码不关心 HTTP 序列化细节。
"""


class BizException(Exception):
    """业务异常基类。

    Attributes:
        status_code: HTTP 状态码（响应 code 复用它），默认 400。
        errno: 业务错误细码（默认 0 = 未细分）。
        message: 默认人类可读消息。
    """

    status_code: int = 400
    errno: int = 0
    message: str = "业务异常"

    def __init__(self, message: str | None = None, *, errno: int | None = None) -> None:
        # message / errno 可在实例化时覆盖，便于调用方补充上下文；
        # 未传则沿用类属性默认值。
        if message is not None:
            self.message = message
        if errno is not None:
            self.errno = errno
        super().__init__(self.message)


class BizNotFoundError(BizException):
    """资源不存在（404）。"""

    status_code = 404
    errno = 10404
    message = "资源不存在"


class BizAuthError(BizException):
    """未授权 / 未认证（401）。"""

    status_code = 401
    errno = 10401
    message = "未授权"


class BizForbiddenError(BizException):
    """已认证但无权限（403）。"""

    status_code = 403
    errno = 10403
    message = "禁止访问"


class BizValidationError(BizException):
    """业务层参数校验失败（422）。"""

    status_code = 422
    errno = 10422
    message = "参数校验失败"

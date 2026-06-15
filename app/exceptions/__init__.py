"""全局异常体系包入口。

统一导出业务异常类（与异常处理器注册函数，后者在 handlers 实现后补导出），
业务层只需：
    from app.exceptions import BizNotFoundError
即可使用，无需关心内部文件组织。
"""
from app.exceptions.base import (
    BizAuthError,
    BizException,
    BizForbiddenError,
    BizNotFoundError,
    BizValidationError,
)
from app.exceptions.handlers import register_exception_handlers

__all__ = [
    "BizException",
    "BizNotFoundError",
    "BizAuthError",
    "BizForbiddenError",
    "BizValidationError",
    "register_exception_handlers",
]

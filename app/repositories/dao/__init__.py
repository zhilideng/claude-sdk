"""数据访问对象层（DAO）。

集中各业务实体的数据访问对象（Repository）。DAO 职责单一——封装对数据源的
增删改查，零业务逻辑：查询返回 ORM 对象或 None，把「是否存在」等业务判断交给
service 层；DB 异常统一转 ``BizException``。

组织约定：
- 一个实体一个模块文件（如 ``user.py``），类名 ``<Entity>Repository``；
- 各 DAO 在本 ``__init__`` 导出，便于 service 层 ``from app.repositories.dao import XxxRepository``；
- DAO 只依赖 ``app.repositories.models``（ORM 实体）与注入的 ``AsyncSession``，
  不反向 import service / api（分层单向依赖）。

与 ``models/`` 的关系：models 描述「表结构」（被访问的数据），dao 描述「如何访问」
（访问者），二者并列于 ``repositories`` 下、互不交叉。
"""
from app.repositories.dao.project import (
    ProjectRepository,
    ProjectSessionRepository,
    SessionMessageRepository,
)
from app.repositories.dao.user import UserRepository

__all__ = [
    "UserRepository",
    "ProjectRepository",
    "ProjectSessionRepository",
    "SessionMessageRepository",
]

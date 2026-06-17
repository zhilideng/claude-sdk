"""ORM 模型层：SQLAlchemy 2.0 声明式模型集中地。

每个数据表对应一个模型类，统一继承 ``app/repositories.base.Base``。
模型类只描述「表结构」，不承载业务逻辑（业务逻辑在 services 层）。

组织约定：
- 一张表一个模块文件（如 ``user.py``），避免单文件膨胀；
- 所有模型统一在 ``models.__init__`` 导出，便于 ``import`` 与未来的 ``create_all``；
- 模型字段必须与库内真实表结构一致（字段名 / 类型 / 可空性 / 默认值），
  以库 schema 为唯一事实来源，不在 ORM 层臆造或偏离。
"""
from app.repositories.base import Base
from app.repositories.models.user import User

__all__ = ["Base", "User"]

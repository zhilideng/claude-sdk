"""数据层基类与声明式基类。

提供 SQLAlchemy 2.0 风格的声明式基类 `Base`，供所有 model 继承。
未来可在此添加通用 DAO 基类（保持精简，YAGNI）。
"""
from sqlalchemy.orm import DeclarativeBase


class Base(DeclarativeBase):
    """SQLAlchemy 2.0 声明式基类。

    所有 ORM 模型类均继承此类，获得：
    - 自动生成表名（类名转 snake_case，如 `UserModel` → `user_model`）；
    - 通用的 id 主键（可选，子类可覆盖）；
    - 统一的 metadata 与 registry。

    用法：
        from app.repositories.base import Base

        class User(Base):
            __tablename__ = "user"  # 显式指定表名（可选，不指定则自动生成）

            id: Mapped[int] = mapped_column(primary_key=True)
            name: Mapped[str] = mapped_column(String(50))
    """
    pass


# 预留：通用 DAO 基类（待有复用需求时再加）
# class GenericDAO(Generic[T]):
#     """通用数据访问对象基类。
#
#     封装常用 CRUD 操作，减少重复代码。
#     待有多个 Repository 实现后，提取共性再加。
#     """
#     pass

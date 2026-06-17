"""user 表 ORM 模型。

字段以库内真实 schema 为唯一事实来源（经 information_schema 核对）：

    列名        类型                可空    默认    备注
    id          integer             NO      无      主键；**非自增**（库里非 serial，插入须显式给值）
    user_name   character varying   YES     无      长度 255

注意：
- 表名 ``user`` 是 PostgreSQL 保留字，原生 SQL 需引号包裹；
  SQLAlchemy 会自动处理，业务层无需关心。
- ``id`` 在库里不是 serial/bigserial，故此处 **不** 设 ``autoincrement=True``，
  保持与库一致，避免误以为能自增导致插入报错。
"""
from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.repositories.base import Base


class User(Base):
    """user 表 ORM 模型。"""

    __tablename__ = "user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    user_name: Mapped[str | None] = mapped_column(String(255), nullable=True)

    def __repr__(self) -> str:
        """调试友好输出（避免泄露敏感字段，本表仅 id/user_name）。"""
        return f"<User id={self.id} user_name={self.user_name!r}>"

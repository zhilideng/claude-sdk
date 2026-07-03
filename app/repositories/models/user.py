"""user 表 ORM 模型。

字段以库内真实 schema 为唯一事实来源（经 information_schema 核对）：

    列名        类型                可空    默认    备注
    id          integer             NO      identity 主键；数据库自增
    user_name   character varying   YES     无      长度 255
    password    character varying   YES     无      暂不加密，保存明文密码

注意：
- 表名 ``user`` 是 PostgreSQL 保留字，原生 SQL 需引号包裹；
  SQLAlchemy 会自动处理，业务层无需关心。
- ``id`` 由数据库自增生成，注册时业务侧不接收、不传入用户 id。
- 当前注册/登录流程为最小样例，``password`` 暂按需求明文保存；生产环境必须替换为
  哈希存储与安全认证流程。
"""
from sqlalchemy import Integer, String
from sqlalchemy.orm import Mapped, mapped_column

from app.repositories.base import Base


class User(Base):
    """user 表 ORM 模型。"""

    __tablename__ = "user"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_name: Mapped[str | None] = mapped_column(String(255), nullable=True)
    password: Mapped[str | None] = mapped_column(String(255), nullable=True)

    def __repr__(self) -> str:
        """调试友好输出（避免泄露密码字段）。"""
        return f"<User id={self.id} user_name={self.user_name!r}>"

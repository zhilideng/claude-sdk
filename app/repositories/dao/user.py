"""user 表数据访问层（DAO）。

职责单一——只封装对 ``user`` 表的读写，零业务逻辑。业务判断（如「查不到则报 404」）
在 service 层做，repository 只返回数据或 None。

设计要点：
- **session 由外部注入**：构造时传入 ``AsyncSession``，由 service 层（经 ``get_db`` 依赖）
  创建并管理其生命周期；repository 不负责 session 的开启/关闭，保持职责纯粹；
- **查询返回 ORM 对象或 None**：不在此抛 NotFound，把「是否存在」的判断权交给 service；
- **DB 异常转业务异常**：``SQLAlchemyError`` 等统一 ``raise BizException``，
  由全局 handler 转统一响应，业务层不接触底层异常；
- **分页返回 (rows, total)**：一次查询同时拿当前页数据与总数，避免 service 二次往返。
"""
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from loguru import logger

from app.exceptions import DB_ERRNO_QUERY_FAILED, BizException
from app.repositories.models import User


class UserRepository:
    """user 表的数据访问对象。

    Args:
        session: 由 service 层注入的异步会话；调用方负责其生命周期。
    """

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def get_by_id(self, user_id: int) -> Optional[User]:
        """按主键查单个用户。

        Args:
            user_id: 用户 id。

        Returns:
            ``User`` 对象；不存在返回 ``None``。

        Raises:
            BizException: 数据库查询失败。
        """
        try:
            result = await self._session.execute(
                select(User).where(User.id == user_id)
            )
            return result.scalar_one_or_none()
        except SQLAlchemyError as exc:
            logger.error("user 查询失败 | get_by_id | id={} | err={}", user_id, exc)
            raise BizException(
                message="用户查询失败",
                errno=DB_ERRNO_QUERY_FAILED,
            ) from exc

    async def get_by_username(self, user_name: str) -> Optional[User]:
        """按 user_name 查单个用户（用于登录/唯一性校验等场景）。

        Args:
            user_name: 用户名。

        Returns:
            ``User`` 对象；不存在返回 ``None``。

        Raises:
            BizException: 数据库查询失败。
        """
        try:
            result = await self._session.execute(
                select(User).where(User.user_name == user_name)
            )
            return result.scalar_one_or_none()
        except SQLAlchemyError as exc:
            logger.error(
                "user 查询失败 | get_by_username | name={} | err={}", user_name, exc
            )
            raise BizException(
                message="用户查询失败",
                errno=DB_ERRNO_QUERY_FAILED,
            ) from exc

    async def create_user(self, user_name: str, password: str) -> User:
        """创建用户账号。

        Args:
            user_name: 用户名。
            password: 明文密码；当前仅用于最小流程演示。

        Returns:
            已写入数据库的 ``User`` 对象。

        Raises:
            BizException: 数据库写入失败。
        """
        try:
            user = User(user_name=user_name, password=password)
            self._session.add(user)
            await self._session.commit()
            await self._session.refresh(user)
            return user
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.error(
                "user 创建失败 | name={} | err={}", user_name, exc
            )
            raise BizException(
                message="用户创建失败",
                errno=DB_ERRNO_QUERY_FAILED,
            ) from exc

    async def list_users(
        self, limit: int = 20, offset: int = 0
    ) -> tuple[list[User], int]:
        """分页查询用户列表（按 id 升序）。

        Args:
            limit: 每页条数（默认 20）。
            offset: 偏移量（默认 0）。

        Returns:
            元组 ``(rows, total)``：当前页 User 列表 + 符合条件的总条数。

        Raises:
            BizException: 数据库查询失败。
        """
        try:
            # 当前页数据
            rows_result = await self._session.execute(
                select(User).order_by(User.id.asc()).limit(limit).offset(offset)
            )
            rows = list(rows_result.scalars().all())
            # 总条数（分页元信息，独立一条 count 查询）
            total_result = await self._session.execute(
                select(func.count()).select_from(User)
            )
            total = total_result.scalar_one()
            return rows, total
        except SQLAlchemyError as exc:
            logger.error("user 查询失败 | list_users | err={}", exc)
            raise BizException(
                message="用户列表查询失败",
                errno=DB_ERRNO_QUERY_FAILED,
            ) from exc

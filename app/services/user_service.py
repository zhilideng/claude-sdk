"""用户业务编排服务。

职责——对 api 层提供用户相关的业务能力，对下编排 ``UserRepository`` 取数。
本层负责：
- 业务判断（如「用户不存在则报 404」），把 repository 返回的 None 转成业务异常；
- 数据形态转换：把 ORM ``User`` 对象转成接口层的 ``UserOut`` / ``UserListData``，
  使 api 层不接触 ORM；
- 分页元信息拼装。

不做的事（保持分层纯粹）：
- 不写 select 语句（在 repository）；
- 不关心 HTTP / 序列化（在 api 层与全局 handler）。
"""
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import BizAuthError, BizNotFoundError, BizValidationError
from app.repositories.dao import UserRepository
from app.schemas.user import (
    UserAuthData,
    UserListData,
    UserLoginIn,
    UserOut,
    UserRegisterIn,
)


class UserService:
    """用户业务服务。

    Args:
        session: 由 api 层经 ``get_db`` 依赖注入的异步会话；service 负责把它
            传给 repository，自身不管理 session 生命周期。
    """

    def __init__(self, session: AsyncSession) -> None:
        # service 持有 session，内部实例化对应的 repository
        self._repo = UserRepository(session)

    async def get_user(self, user_id: int) -> UserOut:
        """按 id 取单个用户。

        Args:
            user_id: 用户 id。

        Returns:
            ``UserOut`` 接口模型。

        Raises:
            BizNotFoundError: 用户不存在（404）。
        """
        user = await self._repo.get_by_id(user_id)
        if user is None:
            # 业务判断在 service：查不到 → 404，由全局 handler 转统一响应
            raise BizNotFoundError(f"用户不存在: id={user_id}")
        # ORM → 接口模型（from_attributes 已开启，直接 model_validate）
        return UserOut.model_validate(user)

    async def list_users(self, limit: int = 20, offset: int = 0) -> UserListData:
        """分页查询用户列表。

        Args:
            limit: 每页条数（默认 20）。
            offset: 偏移量（默认 0）。

        Returns:
            ``UserListData``：含当前页 items 与分页元信息（total/limit/offset）。
        """
        rows, total = await self._repo.list_users(limit=limit, offset=offset)
        return UserListData(
            items=[UserOut.model_validate(row) for row in rows],
            total=total,
            limit=limit,
            offset=offset,
        )

    async def register(self, payload: UserRegisterIn) -> UserAuthData:
        """注册用户账号。

        Args:
            payload: 注册请求数据，包含用户名与明文密码。

        Returns:
            注册成功后的用户信息。

        Raises:
            BizValidationError: 用户名已存在。
        """
        existing_name = await self._repo.get_by_username(payload.user_name)
        if existing_name is not None:
            raise BizValidationError("用户名已存在")

        user = await self._repo.create_user(
            user_name=payload.user_name,
            password=payload.password,
        )
        return UserAuthData(user=UserOut.model_validate(user))

    async def login(self, payload: UserLoginIn) -> UserAuthData:
        """用户登录。

        当前为最小流程：按用户名查用户，并直接比对明文密码。

        Args:
            payload: 登录请求数据。

        Returns:
            登录成功后的用户信息。

        Raises:
            BizAuthError: 用户不存在或密码不匹配。
        """
        user = await self._repo.get_by_username(payload.user_name)
        if user is None or user.password != payload.password:
            raise BizAuthError("用户名或密码错误")
        return UserAuthData(user=UserOut.model_validate(user))

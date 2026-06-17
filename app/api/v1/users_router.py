"""用户相关 API 路由（v1）。

Controller 层职责——只做：参数接收与校验、调用 service、按统一响应格式返回。
不写业务逻辑（在 service）、不写查询语句（在 repository）。

统一响应约定：
- 成功：``ApiResponse.ok(data).to_payload()``；
- 失败：service 抛 ``BizXxxError``，由全局 handler 统一转响应，路由无需 try/except。
"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.user import UserListData, UserOut
from app.services import UserService
from app.utils.common import ApiResponse

router = APIRouter(prefix="/users", tags=["users"])


@router.get("")
async def list_users(
    limit: int = Query(20, ge=1, le=100, description="每页条数，1-100"),
    offset: int = Query(0, ge=0, description="偏移量，从 0 开始"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """分页查询用户列表。

    返回 ``ApiResponse.data`` 为 ``UserListData``（items + total/limit/offset）。
    """
    service = UserService(db)
    data: UserListData = await service.list_users(limit=limit, offset=offset)
    return ApiResponse.ok(data).to_payload()


@router.get("/{user_id}")
async def get_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """按 id 查单个用户。

    用户不存在时由 service 抛 ``BizNotFoundError``，全局 handler 转 404 统一响应。
    """
    service = UserService(db)
    data: UserOut = await service.get_user(user_id)
    return ApiResponse.ok(data).to_payload()

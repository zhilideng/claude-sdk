"""user 业务相关的 Pydantic 模型（请求 / 响应）。

职责——只定义数据结构与校验，不含业务逻辑（业务逻辑在 services 层）。
与 ORM 模型 ``app.repositories.models.User`` 分离：ORM 描述「表」，本模块描述「接口」，
二者解耦，便于接口字段与表字段独立演进。

设计要点：
- ``from_attributes=True``：支持直接从 ORM 对象（``User``）构造，省去手写字段拷贝；
- 响应模型区分「单条」与「分页列表」，分页额外携带 total/limit/offset 元信息；
- 字段用 ``Optional`` / 默认值表达可空性，对齐库内 schema（user_name 可空）。
"""
from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class UserOut(BaseModel):
    """单个用户的响应模型（可从 ORM ``User`` 对象直接构造）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_name: Optional[str] = None


class UserListItem(BaseModel):
    """用户列表项（语义独立于单条详情，便于将来字段分叉）。"""

    model_config = ConfigDict(from_attributes=True)

    id: int
    user_name: Optional[str] = None


class UserListData(BaseModel):
    """用户分页列表的数据体（挂在 ApiResponse.data 下）。"""

    items: list[UserListItem]
    total: int  # 符合条件的总条数（分页元信息）
    limit: int  # 本次查询的每页条数
    offset: int  # 本次查询的偏移量


class UserRegisterIn(BaseModel):
    """用户注册请求体。"""

    user_name: str = Field(..., min_length=1, max_length=255, description="用户名")
    password: str = Field(..., min_length=1, max_length=255, description="密码")


class UserLoginIn(BaseModel):
    """用户登录请求体。"""

    user_name: str = Field(..., min_length=1, max_length=255, description="用户名")
    password: str = Field(..., min_length=1, max_length=255, description="密码")


class UserAuthData(BaseModel):
    """注册 / 登录成功后的数据体。"""

    user: UserOut

"""项目相关 API 路由（v1）。"""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.schemas.project import (
    ProjectCreateIn,
    ProjectImportIn,
    ProjectSessionCreateIn,
)
from app.services import ProjectService
from app.utils.common import ApiResponse

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("")
async def list_projects(
    user_id: int = Query(..., ge=1, description="当前用户 id"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查询当前用户的项目列表。"""
    service = ProjectService(db, get_settings().projects)
    data = await service.list_projects(user_id)
    return ApiResponse.ok(data).to_payload()


@router.post("")
async def create_project(
    payload: ProjectCreateIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建本地项目记录。"""
    service = ProjectService(db, get_settings().projects)
    data = await service.import_local_path(ProjectImportIn.model_validate(payload))
    return ApiResponse.ok(data).to_payload()


@router.post("/import-local-path")
async def import_local_path(
    payload: ProjectImportIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """导入浏览器选择的本地目录作为项目。"""
    service = ProjectService(db, get_settings().projects)
    data = await service.import_local_path(payload)
    return ApiResponse.ok(data).to_payload()


@router.get("/{project_id}/scan")
async def scan_project(
    project_id: int,
    user_id: int = Query(..., ge=1, description="当前用户 id"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """返回项目路径摘要。"""
    service = ProjectService(db, get_settings().projects)
    data = await service.scan_project(project_id, user_id)
    return ApiResponse.ok(data).to_payload()


@router.post("/{project_id}/sessions")
async def create_session(
    project_id: int,
    payload: ProjectSessionCreateIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """在项目下创建新会话。"""
    service = ProjectService(db, get_settings().projects)
    data = await service.create_session(project_id, payload)
    return ApiResponse.ok(data).to_payload()


@router.get("/{project_id}/sessions")
async def list_sessions(
    project_id: int,
    user_id: int = Query(..., ge=1, description="当前用户 id"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查询项目下会话列表。"""
    service = ProjectService(db, get_settings().projects)
    data = await service.list_sessions(project_id, user_id)
    return ApiResponse.ok({"items": data}).to_payload()

"""项目相关 API 路由（v1）。"""
import asyncio

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.exceptions import BizValidationError
from app.schemas.project import (
    ProjectCreateIn,
    ProjectImportIn,
    ProjectSessionCreateIn,
)
from app.schemas.local_agent import ProjectLocalAgentTaskCreateIn
from app.services import ProjectService
from app.utils.local_directory_picker import pick_local_directory
from app.utils.common import ApiResponse

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("")
async def list_projects(
    user_id: int = Query(..., ge=1, description="当前用户 id"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查询当前用户的项目列表。"""
    settings = get_settings()
    service = ProjectService(
        db,
        settings.projects,
        use_local_agent_relay=settings.claude_agent.use_local_agent_relay,
    )
    data = await service.list_projects(user_id)
    return ApiResponse.ok(data).to_payload()


@router.post("")
async def create_project(
    payload: ProjectCreateIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建本地项目记录。"""
    settings = get_settings()
    service = ProjectService(
        db,
        settings.projects,
        use_local_agent_relay=settings.claude_agent.use_local_agent_relay,
    )
    data = await service.import_local_path(ProjectImportIn.model_validate(payload))
    return ApiResponse.ok(data).to_payload()


@router.post("/import-local-path")
async def import_local_path(
    payload: ProjectImportIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """导入浏览器选择的本地目录作为项目。"""
    settings = get_settings()
    service = ProjectService(
        db,
        settings.projects,
        use_local_agent_relay=settings.claude_agent.use_local_agent_relay,
    )
    data = await service.import_local_path(payload)
    return ApiResponse.ok(data).to_payload()


@router.post("/import-folder")
async def import_folder(
) -> dict:
    """拒绝浏览器文件夹上传导入，避免把服务端临时目录误当项目 cwd。"""
    raise BizValidationError(
        "当前导入方式无法获取本地文件夹真实路径，请使用桌面目录选择桥接重新导入"
    )


@router.post("/pick-local-directory")
async def pick_local_directory_path() -> dict:
    """由后端本机弹出目录选择器，返回真实绝对路径。"""
    data = await asyncio.to_thread(pick_local_directory)
    return ApiResponse.ok(data).to_payload()


@router.get("/{project_id}/scan")
async def scan_project(
    project_id: int,
    user_id: int = Query(..., ge=1, description="当前用户 id"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """返回项目路径摘要。"""
    settings = get_settings()
    service = ProjectService(
        db,
        settings.projects,
        use_local_agent_relay=settings.claude_agent.use_local_agent_relay,
    )
    data = await service.scan_project(project_id, user_id)
    return ApiResponse.ok(data).to_payload()


@router.post("/{project_id}/local-agent/tasks")
async def create_project_local_agent_task(
    project_id: int,
    payload: ProjectLocalAgentTaskCreateIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """基于项目已保存 root_path 创建本地工具中继任务。"""
    settings = get_settings()
    service = ProjectService(
        db,
        settings.projects,
        use_local_agent_relay=settings.claude_agent.use_local_agent_relay,
    )
    data = await service.create_local_agent_task(project_id, payload)
    return ApiResponse.ok(data).to_payload()


@router.post("/{project_id}/sessions")
async def create_session(
    project_id: int,
    payload: ProjectSessionCreateIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """在项目下创建新会话。"""
    settings = get_settings()
    service = ProjectService(
        db,
        settings.projects,
        use_local_agent_relay=settings.claude_agent.use_local_agent_relay,
    )
    data = await service.create_session(project_id, payload)
    return ApiResponse.ok(data).to_payload()


@router.get("/{project_id}/sessions")
async def list_sessions(
    project_id: int,
    user_id: int = Query(..., ge=1, description="当前用户 id"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查询项目下会话列表。"""
    settings = get_settings()
    service = ProjectService(
        db,
        settings.projects,
        use_local_agent_relay=settings.claude_agent.use_local_agent_relay,
    )
    data = await service.list_sessions(project_id, user_id)
    return ApiResponse.ok({"items": data}).to_payload()

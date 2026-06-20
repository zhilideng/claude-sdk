"""skill 注册中心 API 路由（v1）。"""
from fastapi import APIRouter, Request

from app.schemas.skill import SkillRunRequest
from app.services.skill_service import SkillService
from app.utils.common import ApiResponse

router = APIRouter(prefix="/skills", tags=["skills"])


@router.get("")
async def list_skills() -> dict:
    """列出全部已注册 skill 元数据。"""
    return ApiResponse.ok({"items": SkillService().list_skills()}).to_payload()


@router.get("/{name}")
async def get_skill(name: str) -> dict:
    """取单个 skill 元数据。"""
    return ApiResponse.ok(SkillService().get_skill(name)).to_payload()


@router.post("/{name}/run")
async def run_skill(name: str, req: SkillRunRequest, request: Request) -> dict:
    """加载并执行 skill：正文作 LLM 指令，input 作 user 消息。"""
    service = SkillService(getattr(request.app.state, "settings", None))
    result = await service.run_skill(name, req.input, req.provider)
    return ApiResponse.ok(result).to_payload()

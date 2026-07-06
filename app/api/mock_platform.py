"""Mock 内部平台接口。"""
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import PlainTextResponse

router = APIRouter(tags=["mock-platform"])


def _mock_root() -> Path:
    """返回 mock 平台数据目录。"""
    return Path(__file__).resolve().parents[1] / "mock_platform"


@router.get("/mock/internal-agent-assets")
async def get_mock_internal_agent_assets(
    app_code: str = Query("codex-web", alias="appCode"),
    scene: str = Query("default"),
    user_id: str | None = Query(None, alias="userId"),
    project_id: str | None = Query(None, alias="projectId"),
) -> dict:
    """返回模拟内部平台下发的 Agent MCP/Skill 资产。"""
    path = _mock_root() / "mock-assets.json"
    data = json.loads(path.read_text("utf-8"))
    data["app_code"] = app_code
    data["scene"] = scene
    if user_id is not None:
        data["user_id"] = user_id
    if project_id is not None:
        data["project_id"] = project_id
    return {"code": 0, "message": "success", "data": data}


@router.get("/mock-platform/skills/{skill_name}")
async def get_mock_skill_markdown(skill_name: str) -> PlainTextResponse:
    """返回模拟平台中的 Skill Markdown 文件。"""
    if "/" in skill_name or "\\" in skill_name or not skill_name.endswith(".md"):
        raise HTTPException(status_code=404, detail="Skill not found")
    path = _mock_root() / "skills" / skill_name
    if not path.is_file():
        raise HTTPException(status_code=404, detail="Skill not found")
    return PlainTextResponse(
        path.read_text("utf-8"),
        media_type="text/markdown; charset=utf-8",
    )

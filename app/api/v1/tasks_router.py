"""Agent 后台任务 API 路由（v1）。"""
import json

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.schemas.agent_task import AgentTaskCreateIn
from app.services.agent_task_service import AgentTaskService
from app.utils.common import ApiResponse

router = APIRouter(prefix="/tasks", tags=["tasks"])


@router.post("")
async def create_task(
    payload: AgentTaskCreateIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """创建后台 Agent 任务。"""
    service = AgentTaskService(db)
    data = await service.create_task(payload)
    return ApiResponse.ok(data.model_dump(mode="json")).to_payload()


@router.get("/running")
async def list_running_tasks(db: AsyncSession = Depends(get_db)) -> dict:
    """查询当前未结束任务。"""
    service = AgentTaskService(db)
    data = await service.list_running_tasks()
    return ApiResponse.ok(data.model_dump(mode="json")).to_payload()


@router.get("/{task_id}")
async def get_task(task_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """查询任务详情。"""
    service = AgentTaskService(db)
    data = await service.get_task(task_id)
    return ApiResponse.ok(data.model_dump(mode="json")).to_payload()


@router.get("/{task_id}/events")
async def list_task_events(
    task_id: str,
    after_seq: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查询任务事件，支持刷新恢复。"""
    service = AgentTaskService(db)
    data = await service.list_events(task_id, after_seq=after_seq)
    return ApiResponse.ok(data.model_dump(mode="json")).to_payload()


@router.get("/{task_id}/stream")
async def stream_task_events(
    task_id: str,
    after_seq: int = Query(0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """通过 SSE 订阅任务事件；断开连接不取消任务。"""
    service = AgentTaskService(db)

    async def event_generator():
        """生成 SSE 文本帧。"""
        async for item in service.stream_events(task_id, after_seq=after_seq):
            data = json.dumps(item.model_dump(mode="json"), ensure_ascii=False)
            yield f"event: task_event\ndata: {data}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{task_id}/cancel")
async def cancel_task(task_id: str, db: AsyncSession = Depends(get_db)) -> dict:
    """请求取消后台任务。"""
    service = AgentTaskService(db)
    data = await service.cancel_task(task_id)
    return ApiResponse.ok(data.model_dump(mode="json")).to_payload()

"""会话消息相关 API 路由（v1）。"""
import json

from fastapi import APIRouter, Depends, Query
from fastapi.responses import StreamingResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_db
from app.schemas.project import SessionMessageCreateIn
from app.services import SessionService
from app.utils.common import ApiResponse

router = APIRouter(prefix="/sessions", tags=["sessions"])


@router.get("/{session_id}/messages")
async def list_messages(
    session_id: int,
    user_id: int = Query(..., ge=1, description="当前用户 id"),
    db: AsyncSession = Depends(get_db),
) -> dict:
    """查询会话消息列表。"""
    settings = get_settings()
    service = SessionService(db, settings.projects, settings.claude_agent)
    data = await service.list_messages(session_id, user_id)
    return ApiResponse.ok(data).to_payload()


@router.post("/{session_id}/messages")
async def send_message(
    session_id: int,
    payload: SessionMessageCreateIn,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """发送用户消息并触发 Claude Code SDK。"""
    settings = get_settings()
    service = SessionService(db, settings.projects, settings.claude_agent)
    data = await service.send_message(session_id, payload)
    return ApiResponse.ok(data).to_payload()


@router.post("/{session_id}/messages/stream")
async def stream_message(
    session_id: int,
    payload: SessionMessageCreateIn,
    db: AsyncSession = Depends(get_db),
) -> StreamingResponse:
    """发送用户消息并以 SSE 流式返回推理过程。"""
    settings = get_settings()
    service = SessionService(db, settings.projects, settings.claude_agent)

    async def event_generator():
        """生成 SSE 文本帧。"""
        async for item in service.stream_message(session_id, payload):
            event_type = item.get("type", "message")
            data = json.dumps(item, ensure_ascii=False)
            yield f"event: {event_type}\ndata: {data}\n\n"

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )

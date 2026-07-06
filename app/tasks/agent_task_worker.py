"""Agent 后台任务 worker。"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator, Callable
from dataclasses import dataclass, field
from typing import Any

from loguru import logger
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.core.database import get_session_maker
from app.exceptions import BizValidationError
from app.repositories.dao import (
    AgentTaskRepository,
    ProjectSessionRepository,
    SessionMessageRepository,
)
from app.repositories.dao.agent_task import TERMINAL_TASK_STATUSES
from app.repositories.models import AgentTask, ProjectSession, SessionMessage
from app.schemas.project import SessionMessageOut
from app.services.agent_asset_service import get_or_create_session_asset_snapshot
from app.services.claude_code_service import ClaudeCodeService
from app.services.project_service import (
    ProjectService,
    is_workspace_root_path,
    normalize_relay_root_path,
)
from app.utils.path_guard import ensure_allowed_root, resolve_project_path


@dataclass(frozen=True)
class AgentTaskOutput:
    """后台任务执行过程产物。"""

    event_type: str
    content: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    final_result: str | None = None


AgentTaskExecutor = Callable[[AgentTask, AsyncSession], AsyncIterator[AgentTaskOutput]]

_running_tasks: dict[str, asyncio.Task] = {}
_agent_task_executor: AgentTaskExecutor | None = None


def set_agent_task_executor(executor: AgentTaskExecutor | None) -> None:
    """替换任务执行器，供测试或未来扩展队列实现使用。"""
    global _agent_task_executor
    _agent_task_executor = executor


def get_agent_task_executor() -> AgentTaskExecutor:
    """获取当前任务执行器。"""
    return _agent_task_executor or execute_claude_agent_task


def enqueue_agent_task(task_id: str) -> None:
    """把任务投递到进程内后台执行。"""
    current = _running_tasks.get(task_id)
    if current is not None and not current.done():
        return

    task = asyncio.create_task(run_agent_task(task_id))
    _running_tasks[task_id] = task
    task.add_done_callback(lambda item: _finish_agent_task(task_id, item))


async def close_agent_task_worker() -> None:
    """关闭应用时取消仍在进程内执行的任务协程。"""
    tasks = [task for task in _running_tasks.values() if not task.done()]
    for task in tasks:
        task.cancel()
    if tasks:
        await asyncio.gather(*tasks, return_exceptions=True)
    _running_tasks.clear()


async def run_agent_task(task_id: str) -> None:
    """执行单个后台任务。"""
    session_maker = get_session_maker()
    if session_maker is None:
        logger.error("后台任务无法执行，数据库未初始化 | task_id={}", task_id)
        return

    async with session_maker() as session:
        repo = AgentTaskRepository(session)
        task = await repo.get_by_task_id(task_id)
        if task is None:
            logger.warning("后台任务不存在，跳过执行 | task_id={}", task_id)
            return
        if task.status in TERMINAL_TASK_STATUSES:
            logger.info("后台任务已结束，跳过执行 | task_id={} | status={}", task_id, task.status)
            return

        if task.cancel_requested or task.status == "cancelling":
            await _mark_task_cancelled(repo, task, session)
            return

        await repo.set_status(task, "running")
        await repo.append_event(
            task_id=task.task_id,
            event_type="task_started",
            content="任务开始执行",
        )
        await repo.commit()

        content_parts: list[str] = []
        final_result: str | None = None
        try:
            executor = get_agent_task_executor()
            async for output in executor(task, session):
                await session.refresh(task)
                if task.cancel_requested:
                    await _mark_task_cancelled(repo, task, session)
                    return
                await repo.append_event(
                    task_id=task.task_id,
                    event_type=output.event_type,
                    content=output.content,
                    metadata=output.metadata,
                )
                if output.event_type == "agent_message" and output.content:
                    content_parts.append(output.content)
                if output.final_result is not None:
                    final_result = output.final_result
                await repo.commit()

            await session.refresh(task)
            if task.cancel_requested:
                await _mark_task_cancelled(repo, task, session)
                return

            result = (final_result or "".join(content_parts)).strip()
            await repo.set_status(task, "completed", result=result or "任务执行完成")
            await repo.append_event(
                task_id=task.task_id,
                event_type="task_completed",
                content="任务执行完成",
            )
            await repo.commit()
        except asyncio.CancelledError:
            await repo.rollback()
            raise
        except Exception as exc:
            await repo.rollback()
            logger.exception("后台任务执行失败 | task_id={} | err={}", task_id, exc)
            task = await repo.get_by_task_id(task_id)
            if task is None:
                return
            error_message = _format_worker_error(exc)
            await _mark_conversation_failed(task, session, error_message)
            await repo.set_status(task, "failed", error_message=error_message)
            await repo.append_event(
                task_id=task.task_id,
                event_type="task_failed",
                content=error_message,
                metadata={"error_type": exc.__class__.__name__},
            )
            await repo.commit()


async def execute_claude_agent_task(
    task: AgentTask,
    session: AsyncSession,
) -> AsyncIterator[AgentTaskOutput]:
    """默认执行器：把已有项目会话任务交给 Claude Agent SDK。"""
    session_id = _resolve_conversation_session_id(task.conversation_id)
    project_session_repo = ProjectSessionRepository(session)
    message_repo = SessionMessageRepository(session)
    project_session = await project_session_repo.get_by_id(session_id)
    if project_session is None:
        raise BizValidationError("任务绑定的会话不存在")

    settings = get_settings()
    cwd = _resolve_session_project_root(project_session)
    user_message = await message_repo.create_message(
        session_id=session_id,
        role="user",
        content=task.prompt,
    )
    await project_session_repo.set_status(project_session, "running", last_message=task.prompt)
    yield AgentTaskOutput(
        event_type="agent_step",
        content="用户消息已保存",
        metadata={"message_id": user_message.id},
    )

    content_parts: list[str] = []
    tool_summary: list[dict[str, Any]] = []
    diff_summary: list[dict[str, Any]] = []
    history = await message_repo.list_by_session(session_id)
    history_out = [_to_message_out(item) for item in history]
    claude_code = ClaudeCodeService(settings.claude_agent, settings.agent_platform)
    snapshot = await get_or_create_session_asset_snapshot(
        session_id,
        settings.agent_platform,
    )

    try:
        async for sdk_event in claude_code.stream_session(
            cwd=cwd,
            prompt=task.prompt,
            session_history=history_out,
            platform_capabilities=snapshot.capabilities,
        ):
            if sdk_event.type == "assistant_delta":
                content = str(sdk_event.data.get("content", ""))
                content_parts.append(content)
                yield AgentTaskOutput(
                    event_type="agent_message",
                    content=content,
                    metadata={"sdk_event_type": sdk_event.type},
                )
                continue

            if sdk_event.type in {"tool_start", "tool_delta", "tool_done"}:
                item = {"type": sdk_event.type, **sdk_event.data}
                tool_summary.append(item)
                yield AgentTaskOutput(
                    event_type="tool_call",
                    content=_summarize_tool_event(item),
                    metadata=item,
                )
                continue

            if sdk_event.type == "sdk_result":
                diff_summary.append(sdk_event.data)
                yield AgentTaskOutput(
                    event_type="agent_step",
                    content="SDK 返回执行结果",
                    metadata=sdk_event.data,
                )
                continue

            yield AgentTaskOutput(
                event_type="agent_step",
                content=sdk_event.type,
                metadata=sdk_event.data,
            )

        assistant_content = "".join(content_parts).strip() or "推理完成，但没有返回文本内容。"
        assistant_message = await message_repo.create_message(
            session_id=session_id,
            role="assistant",
            content=assistant_content,
            status="done",
            tool_summary=json.dumps(tool_summary, ensure_ascii=False),
            diff_summary=json.dumps(diff_summary, ensure_ascii=False),
        )
        await project_session_repo.set_status(
            project_session,
            "idle",
            last_message=assistant_content,
        )
        yield AgentTaskOutput(
            event_type="agent_step",
            content="助手消息已保存",
            metadata={"message_id": assistant_message.id},
            final_result=assistant_content,
        )
    except Exception:
        failed_content = "推理失败，请稍后重试"
        await message_repo.create_message(
            session_id=session_id,
            role="assistant",
            content=failed_content,
            status="failed",
            tool_summary=json.dumps(tool_summary, ensure_ascii=False),
            diff_summary=json.dumps(diff_summary, ensure_ascii=False),
        )
        await project_session_repo.set_status(project_session, "failed", last_message=failed_content)
        raise


async def _mark_task_cancelled(
    repo: AgentTaskRepository,
    task: AgentTask,
    session: AsyncSession,
) -> None:
    """把任务标记为已取消并写取消事件。"""
    await _mark_conversation_failed(task, session, "任务已取消")
    await repo.set_status(task, "cancelled")
    await repo.append_event(
        task_id=task.task_id,
        event_type="task_cancelled",
        content="任务已取消",
    )
    await repo.commit()


async def _mark_conversation_failed(
    task: AgentTask,
    session: AsyncSession,
    message: str,
) -> None:
    """任务失败或取消时同步会话状态，避免会话长期停在 running。"""
    if not task.conversation_id or not task.conversation_id.isdigit():
        return
    session_id = int(task.conversation_id)
    project_session_repo = ProjectSessionRepository(session)
    message_repo = SessionMessageRepository(session)
    project_session = await project_session_repo.get_by_id(session_id)
    if project_session is None:
        return
    await message_repo.create_message(
        session_id=session_id,
        role="assistant",
        content=message,
        status="failed",
    )
    await project_session_repo.set_status(project_session, "failed", last_message=message)


def _finish_agent_task(task_id: str, task: asyncio.Task) -> None:
    """后台任务结束后的本地清理。"""
    _running_tasks.pop(task_id, None)
    try:
        task.result()
    except asyncio.CancelledError:
        logger.info("后台任务协程已取消 | task_id={}", task_id)
    except Exception as exc:
        logger.exception("后台任务协程异常 | task_id={} | err={}", task_id, exc)


def _resolve_conversation_session_id(conversation_id: str | None) -> int:
    """从 conversation_id 解析项目会话 id。"""
    if not conversation_id or not conversation_id.isdigit():
        raise BizValidationError("任务未绑定项目会话，无法执行 Agent")
    return int(conversation_id)


def _resolve_session_project_root(session: ProjectSession) -> str:
    """解析会话绑定的项目根目录。"""
    if not session.project.root_path:
        raise BizValidationError("项目未绑定本地绝对路径，请重新导入项目目录")
    settings = get_settings()
    if settings.claude_agent.use_local_agent_relay:
        return normalize_relay_root_path(session.project.root_path)
    path = resolve_project_path(session.project.root_path)
    if is_workspace_root_path(path, settings.projects):
        raise BizValidationError("项目绑定的是服务端临时目录，请重新选择真实项目目录")
    ensure_allowed_root(path, [*settings.projects.allowed_roots])
    return str(path)


def _to_message_out(message: SessionMessage) -> SessionMessageOut:
    """ORM 消息转接口模型。"""
    return SessionMessageOut(
        id=message.id,
        session_id=message.session_id,
        role=message.role,
        content=message.content,
        status=message.status,
        tool_summary=ProjectService._load_json_list(message.tool_summary),
        diff_summary=ProjectService._load_json_list(message.diff_summary),
        created_at=message.created_at,
    )


def _summarize_tool_event(item: dict[str, Any]) -> str:
    """生成工具调用事件摘要。"""
    name = str(item.get("name") or item.get("tool") or "tool")
    event_type = str(item.get("type") or "tool_call")
    return f"{name}: {event_type}"


def _format_worker_error(exc: Exception) -> str:
    """把 worker 异常转换为任务错误信息。"""
    if isinstance(exc, BizValidationError):
        return exc.message
    detail = str(exc).strip()
    return detail[:500] if detail else "任务执行失败"

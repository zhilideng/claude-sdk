"""Agent 后台任务数据访问层。"""
from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from loguru import logger
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import DB_ERRNO_QUERY_FAILED, BizException
from app.repositories.models import AgentTask, AgentTaskEvent

TERMINAL_TASK_STATUSES = {"completed", "failed", "cancelled"}
ACTIVE_TASK_STATUSES = {"created", "queued", "running", "cancelling"}


class AgentTaskRepository:
    """agent_task / agent_task_event 表数据访问对象。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create_task(
        self,
        *,
        task_id: str,
        prompt: str,
        conversation_id: str | None,
        title: str | None,
    ) -> AgentTask:
        """创建任务主记录。"""
        try:
            task = AgentTask(
                task_id=task_id,
                conversation_id=conversation_id,
                title=title,
                prompt=prompt,
                status="created",
            )
            self._session.add(task)
            await self._session.flush()
            await self._session.refresh(task)
            return task
        except SQLAlchemyError as exc:
            logger.error("agent_task 创建失败 | task_id={} | err={}", task_id, exc)
            raise BizException(message="任务创建失败", errno=DB_ERRNO_QUERY_FAILED) from exc

    async def get_by_task_id(self, task_id: str) -> AgentTask | None:
        """按 task_id 查询任务。"""
        try:
            result = await self._session.execute(
                select(AgentTask).where(AgentTask.task_id == task_id)
            )
            return result.scalar_one_or_none()
        except SQLAlchemyError as exc:
            logger.error("agent_task 查询失败 | task_id={} | err={}", task_id, exc)
            raise BizException(message="任务查询失败", errno=DB_ERRNO_QUERY_FAILED) from exc

    async def list_active_tasks(self) -> list[AgentTask]:
        """查询仍未结束的任务。"""
        try:
            result = await self._session.execute(
                select(AgentTask)
                .where(AgentTask.status.in_(ACTIVE_TASK_STATUSES))
                .order_by(AgentTask.updated_at.desc(), AgentTask.id.desc())
            )
            return list(result.scalars().all())
        except SQLAlchemyError as exc:
            logger.error("agent_task 运行中任务查询失败 | err={}", exc)
            raise BizException(message="运行中任务查询失败", errno=DB_ERRNO_QUERY_FAILED) from exc

    async def set_status(
        self,
        task: AgentTask,
        status: str,
        *,
        result: str | None = None,
        error_message: str | None = None,
    ) -> AgentTask:
        """更新任务状态与结果字段。"""
        try:
            now = datetime.now(UTC)
            task.status = status
            task.updated_at = now
            if status == "running" and task.started_at is None:
                task.started_at = now
            if status in TERMINAL_TASK_STATUSES:
                task.finished_at = now
            if result is not None:
                task.result = result
            if error_message is not None:
                task.error_message = error_message
            await self._session.flush()
            await self._session.refresh(task)
            return task
        except SQLAlchemyError as exc:
            logger.error("agent_task 状态更新失败 | task_id={} | err={}", task.task_id, exc)
            raise BizException(message="任务状态更新失败", errno=DB_ERRNO_QUERY_FAILED) from exc

    async def request_cancel(self, task: AgentTask) -> AgentTask:
        """标记任务请求取消。"""
        try:
            task.cancel_requested = True
            task.updated_at = datetime.now(UTC)
            await self._session.flush()
            await self._session.refresh(task)
            return task
        except SQLAlchemyError as exc:
            logger.error("agent_task 取消标记失败 | task_id={} | err={}", task.task_id, exc)
            raise BizException(message="任务取消失败", errno=DB_ERRNO_QUERY_FAILED) from exc

    async def append_event(
        self,
        *,
        task_id: str,
        event_type: str,
        content: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> AgentTaskEvent:
        """追加任务事件，并生成任务内递增 seq。"""
        try:
            seq = await self.next_seq(task_id)
            event = AgentTaskEvent(
                task_id=task_id,
                seq=seq,
                event_type=event_type,
                content=content,
                metadata_json=json.dumps(metadata or {}, ensure_ascii=False),
            )
            self._session.add(event)
            await self._session.flush()
            await self._session.refresh(event)
            return event
        except SQLAlchemyError as exc:
            logger.error("agent_task_event 写入失败 | task_id={} | err={}", task_id, exc)
            raise BizException(message="任务事件写入失败", errno=DB_ERRNO_QUERY_FAILED) from exc

    async def next_seq(self, task_id: str) -> int:
        """计算下一条任务事件序号。"""
        result = await self._session.execute(
            select(func.max(AgentTaskEvent.seq)).where(AgentTaskEvent.task_id == task_id)
        )
        current = result.scalar_one_or_none() or 0
        return int(current) + 1

    async def list_events(
        self,
        task_id: str,
        *,
        after_seq: int = 0,
        limit: int = 500,
    ) -> list[AgentTaskEvent]:
        """按 seq 升序查询指定任务的后续事件。"""
        try:
            result = await self._session.execute(
                select(AgentTaskEvent)
                .where(
                    AgentTaskEvent.task_id == task_id,
                    AgentTaskEvent.seq > after_seq,
                )
                .order_by(AgentTaskEvent.seq.asc())
                .limit(limit)
            )
            return list(result.scalars().all())
        except SQLAlchemyError as exc:
            logger.error("agent_task_event 查询失败 | task_id={} | err={}", task_id, exc)
            raise BizException(message="任务事件查询失败", errno=DB_ERRNO_QUERY_FAILED) from exc

    async def commit(self) -> None:
        """提交当前事务。"""
        try:
            await self._session.commit()
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.error("agent_task 事务提交失败 | err={}", exc)
            raise BizException(message="任务保存失败", errno=DB_ERRNO_QUERY_FAILED) from exc

    async def rollback(self) -> None:
        """回滚当前事务。"""
        await self._session.rollback()

"""Agent 后台任务业务服务。"""
from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from typing import Any
from uuid import uuid4

from sqlalchemy.ext.asyncio import AsyncSession

from app.exceptions import BizNotFoundError, BizValidationError
from app.repositories.dao import AgentTaskRepository
from app.repositories.dao.agent_task import ACTIVE_TASK_STATUSES, TERMINAL_TASK_STATUSES
from app.repositories.models import AgentTask, AgentTaskEvent
from app.schemas.agent_task import (
    AgentTaskCancelData,
    AgentTaskCreateData,
    AgentTaskCreateIn,
    AgentTaskEventListData,
    AgentTaskEventOut,
    AgentTaskOut,
    AgentTaskRunningItem,
    AgentTaskRunningListData,
)
from app.tasks.agent_task_worker import enqueue_agent_task


class AgentTaskService:
    """后台 Agent 任务业务编排。"""

    def __init__(self, session: AsyncSession) -> None:
        self._repo = AgentTaskRepository(session)

    async def create_task(self, payload: AgentTaskCreateIn) -> AgentTaskCreateData:
        """创建任务、写初始事件并投递后台执行。"""
        prompt = payload.prompt.strip()
        if not prompt:
            raise BizValidationError("任务内容不能为空")
        task_id = f"task_{uuid4().hex}"
        task = await self._repo.create_task(
            task_id=task_id,
            prompt=prompt,
            conversation_id=self._normalize_optional_text(payload.conversation_id),
            title=self._normalize_title(payload.title, prompt),
        )
        await self._repo.append_event(
            task_id=task.task_id,
            event_type="task_created",
            content="任务已创建",
        )
        await self._repo.set_status(task, "queued")
        await self._repo.append_event(
            task_id=task.task_id,
            event_type="task_queued",
            content="任务已进入队列",
        )
        await self._repo.commit()
        enqueue_agent_task(task.task_id)
        return AgentTaskCreateData(task_id=task.task_id, status=task.status)

    async def get_task(self, task_id: str) -> AgentTaskOut:
        """查询任务详情。"""
        task = await self._get_existing_task(task_id)
        return self._to_task_out(task)

    async def list_events(self, task_id: str, after_seq: int = 0) -> AgentTaskEventListData:
        """查询任务事件，支持刷新恢复。"""
        await self._get_existing_task(task_id)
        events = await self._repo.list_events(task_id, after_seq=after_seq)
        return AgentTaskEventListData(items=[self._to_event_out(item) for item in events])

    async def list_running_tasks(self) -> AgentTaskRunningListData:
        """查询未结束任务，供新开会话恢复入口使用。"""
        tasks = await self._repo.list_active_tasks()
        return AgentTaskRunningListData(
            items=[
                AgentTaskRunningItem(
                    task_id=task.task_id,
                    conversation_id=task.conversation_id,
                    title=task.title,
                    status=task.status,
                    created_at=task.created_at,
                    updated_at=task.updated_at,
                )
                for task in tasks
            ]
        )

    async def cancel_task(self, task_id: str) -> AgentTaskCancelData:
        """请求取消任务；真正停止由 worker 轮询 cancel_requested 完成。"""
        task = await self._get_existing_task(task_id)
        if task.status in TERMINAL_TASK_STATUSES:
            return AgentTaskCancelData(task_id=task.task_id, status=task.status)
        await self._repo.request_cancel(task)
        if task.status != "cancelling":
            await self._repo.set_status(task, "cancelling")
            await self._repo.append_event(
                task_id=task.task_id,
                event_type="task_cancelling",
                content="正在取消任务",
            )
        await self._repo.commit()
        return AgentTaskCancelData(task_id=task.task_id, status=task.status)

    async def stream_events(
        self,
        task_id: str,
        after_seq: int = 0,
        *,
        poll_interval: float = 0.5,
    ) -> AsyncIterator[AgentTaskEventOut]:
        """先补发历史事件，再轮询推送新增事件。"""
        last_seq = max(after_seq, 0)
        while True:
            task = await self._get_existing_task(task_id)
            events = await self._repo.list_events(task_id, after_seq=last_seq)
            for event in events:
                last_seq = event.seq
                yield self._to_event_out(event)

            if task.status in TERMINAL_TASK_STATUSES and not events:
                break

            await self._repo.rollback()
            await asyncio.sleep(poll_interval)

    async def _get_existing_task(self, task_id: str) -> AgentTask:
        """查询任务，不存在时抛业务 404。"""
        task = await self._repo.get_by_task_id(task_id)
        if task is None:
            raise BizNotFoundError("任务不存在")
        return task

    @staticmethod
    def _to_task_out(task: AgentTask) -> AgentTaskOut:
        """ORM 任务转接口模型。"""
        return AgentTaskOut(
            task_id=task.task_id,
            conversation_id=task.conversation_id,
            title=task.title,
            prompt=task.prompt,
            status=task.status,
            result=task.result,
            error_message=task.error_message,
            cancel_requested=task.cancel_requested,
            created_at=task.created_at,
            updated_at=task.updated_at,
            started_at=task.started_at,
            finished_at=task.finished_at,
        )

    @classmethod
    def _to_event_out(cls, event: AgentTaskEvent) -> AgentTaskEventOut:
        """ORM 事件转接口模型。"""
        return AgentTaskEventOut(
            seq=event.seq,
            event_type=event.event_type,
            content=event.content,
            metadata=cls._load_metadata(event.metadata_json),
            created_at=event.created_at,
        )

    @staticmethod
    def _load_metadata(value: str | None) -> dict[str, Any]:
        """从 JSON 文本恢复事件 metadata。"""
        if not value:
            return {}
        try:
            loaded = json.loads(value)
        except json.JSONDecodeError:
            return {}
        return loaded if isinstance(loaded, dict) else {}

    @staticmethod
    def _normalize_optional_text(value: str | None) -> str | None:
        """清理可选文本字段。"""
        if value is None:
            return None
        text = value.strip()
        return text or None

    @staticmethod
    def _normalize_title(value: str | None, prompt: str) -> str:
        """生成任务标题。"""
        title = value.strip() if value else prompt.strip().replace("\n", " ")
        return title[:255] or "后台任务"


def is_active_task_status(status: str) -> bool:
    """判断任务是否仍可恢复订阅。"""
    return status in ACTIVE_TASK_STATUSES

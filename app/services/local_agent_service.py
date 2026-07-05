"""本地工具中继任务服务。"""

import asyncio
from collections import deque
from datetime import UTC, datetime
from uuid import uuid4

from app.exceptions import BizValidationError
from app.schemas.local_agent import (
    LocalAgentInfoOut,
    LocalAgentListData,
    LocalAgentPollData,
    LocalAgentStatus,
    LocalAgentTaskCompleteIn,
    LocalAgentTaskCreateIn,
    LocalAgentTaskOut,
)


class LocalAgentTaskHub:
    """进程内本地执行任务队列。

    MVP 先使用内存态，便于快速验证远端服务与用户本机脚本之间的任务闭环。
    后续生产化再替换为 Redis Stream / DB 队列表，避免多 worker 内存不共享。
    """

    def __init__(self) -> None:
        self._tasks: dict[str, LocalAgentTaskOut] = {}
        self._pending_ids: deque[str] = deque()
        self._agents: dict[str, LocalAgentInfoOut] = {}
        self._lock = asyncio.Lock()

    async def create_task(self, payload: LocalAgentTaskCreateIn) -> LocalAgentTaskOut:
        """创建待本地脚本执行的任务。"""
        now = datetime.now(UTC)
        task = LocalAgentTaskOut(
            id=uuid4().hex,
            root_path=payload.root_path,
            action=payload.action,
            payload=payload.payload,
            timeout_seconds=payload.timeout_seconds,
            status="pending",
            created_at=now,
            updated_at=now,
        )
        async with self._lock:
            self._tasks[task.id] = task
            self._pending_ids.append(task.id)
        return task

    async def poll_task(self, agent_name: str) -> LocalAgentTaskOut | None:
        """取出一个待执行任务并标记为 running。"""
        async with self._lock:
            now = datetime.now(UTC)
            while self._pending_ids:
                task_id = self._pending_ids.popleft()
                task = self._tasks.get(task_id)
                if task is None or task.status != "pending":
                    continue
                task.status = "running"
                task.agent_name = agent_name
                task.updated_at = now
                self._touch_agent_locked(
                    agent_name,
                    status="running",
                    current_task_id=task.id,
                    now=now,
                )
                return task
            self._touch_agent_locked(
                agent_name,
                status="idle",
                current_task_id=None,
                now=now,
            )
        return None

    async def poll(self, agent_name: str) -> LocalAgentPollData:
        """返回本地脚本轮询数据。"""
        return LocalAgentPollData(task=await self.poll_task(agent_name))

    async def complete_task(
        self,
        task_id: str,
        payload: LocalAgentTaskCompleteIn,
    ) -> LocalAgentTaskOut:
        """写入本地脚本执行结果。"""
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise BizValidationError("本地执行任务不存在")
            if task.status in {"succeeded", "failed"}:
                raise BizValidationError("本地执行任务已完成，不能重复回传结果")

            task.status = payload.status
            task.result = payload.result
            task.error = payload.error
            task.updated_at = datetime.now(UTC)
            if task.agent_name:
                self._touch_agent_locked(
                    task.agent_name,
                    status="idle",
                    current_task_id=None,
                    now=task.updated_at,
                    increment_poll=False,
                )
            return task

    async def get_task(self, task_id: str) -> LocalAgentTaskOut:
        """按 id 查询任务。"""
        async with self._lock:
            task = self._tasks.get(task_id)
            if task is None:
                raise BizValidationError("本地执行任务不存在")
            return task

    async def wait_task(self, task_id: str, timeout_seconds: float) -> LocalAgentTaskOut:
        """等待任务进入终态，用于服务端 agent 同步调用工具。"""
        deadline = asyncio.get_running_loop().time() + timeout_seconds
        while True:
            task = await self.get_task(task_id)
            if task.status in {"succeeded", "failed"}:
                return task
            if asyncio.get_running_loop().time() >= deadline:
                raise BizValidationError("等待本地执行任务超时")
            await asyncio.sleep(0.1)

    async def list_agents(self) -> LocalAgentListData:
        """查询本地脚本实例最近心跳状态。"""
        async with self._lock:
            items = sorted(self._agents.values(), key=lambda item: item.agent_name)
            return LocalAgentListData(items=items)

    def _touch_agent_locked(
        self,
        agent_name: str,
        *,
        status: LocalAgentStatus,
        current_task_id: str | None,
        now: datetime,
        increment_poll: bool = True,
    ) -> None:
        """在持锁区间更新本地脚本心跳。"""
        previous = self._agents.get(agent_name)
        self._agents[agent_name] = LocalAgentInfoOut(
            agent_name=agent_name,
            status=status,
            poll_count=(previous.poll_count if previous else 0) + (1 if increment_poll else 0),
            current_task_id=current_task_id,
            last_seen_at=now,
        )


local_agent_hub = LocalAgentTaskHub()


def get_local_agent_hub() -> LocalAgentTaskHub:
    """获取进程级本地工具中继队列。"""
    return local_agent_hub


def reset_local_agent_hub() -> None:
    """重置进程级队列，仅供本地测试隔离状态使用。"""
    global local_agent_hub
    local_agent_hub = LocalAgentTaskHub()

"""Claude Agent SDK 调用封装。"""
from __future__ import annotations

import asyncio
import os
from collections.abc import AsyncIterator
from typing import Any

from pydantic import BaseModel, Field

from app.core.settings import ClaudeAgentSettings
from app.exceptions import BizValidationError
from app.schemas.project import SessionMessageOut


class ClaudeCodeStreamEvent(BaseModel):
    """Claude Agent SDK 流式事件。"""

    type: str
    data: dict[str, Any] = Field(default_factory=dict)


class ClaudeCodeRunResult(BaseModel):
    """Claude Agent SDK 单次运行结果。"""

    content: str
    tool_summary: list[dict[str, Any]] = Field(default_factory=list)
    changed_files: list[str] = Field(default_factory=list)
    diff_summary: list[dict[str, Any]] = Field(default_factory=list)


class ClaudeCodeService:
    """Claude Agent SDK 统一调用入口。"""

    def __init__(self, settings: ClaudeAgentSettings | None = None) -> None:
        self._settings = settings or ClaudeAgentSettings()

    async def stream_session(
        self,
        *,
        cwd: str | None,
        prompt: str,
        session_history: list[SessionMessageOut],
    ) -> AsyncIterator[ClaudeCodeStreamEvent]:
        """流式运行一次 agent 会话请求。"""
        if not self._settings.enabled:
            raise BizValidationError("推理服务已禁用")

        self._prepare_environment()
        resolved_cwd = self._resolve_cwd(cwd)
        formatted_prompt = self._format_prompt(prompt, session_history)

        try:
            from claude_agent_sdk import ClaudeAgentOptions, query
        except ImportError as exc:
            raise BizValidationError(
                "推理服务依赖未安装，请先安装依赖后再重试"
            ) from exc

        options = ClaudeAgentOptions(
            tools={"type": "preset", "preset": "claude_code"},
            permission_mode=self._settings.permission_mode,
            include_partial_messages=self._settings.include_partial_messages,
            include_hook_events=True,
            cwd=resolved_cwd,
            env=dict(os.environ),
            mcp_servers=self._settings.mcp_servers,
            strict_mcp_config=self._settings.strict_mcp_config,
        )

        current_tool: dict[str, Any] | None = None
        has_text_delta = False

        async def emit_sdk_message(message: Any) -> AsyncIterator[ClaudeCodeStreamEvent]:
            """转换单个 SDK 消息，并维护当前工具与文本状态。"""
            nonlocal current_tool, has_text_delta
            class_name = message.__class__.__name__
            if class_name == "StreamEvent":
                async for event in self._stream_event_to_sse(message, current_tool):
                    if event.type == "assistant_delta":
                        has_text_delta = True
                    if event.type == "tool_start":
                        current_tool = event.data
                    if event.type == "tool_done":
                        current_tool = None
                    yield event
                return

            if class_name == "AssistantMessage" and not has_text_delta:
                content = self._extract_assistant_text(message)
                if content:
                    yield ClaudeCodeStreamEvent(
                        type="assistant_delta",
                        data={"content": content},
                    )
                return

            if class_name == "ResultMessage":
                yield ClaudeCodeStreamEvent(
                    type="sdk_result",
                    data=self._result_message_to_data(message),
                )

        message_stream = aiter(query(prompt=formatted_prompt, options=options))
        async with asyncio.timeout(self._settings.command_timeout):
            try:
                first_message = await asyncio.wait_for(
                    anext(message_stream),
                    timeout=self._settings.startup_timeout,
                )
            except TimeoutError as exc:
                raise BizValidationError(
                    f"推理连接超时（{self._settings.startup_timeout} 秒内未收到首个事件），"
                    "请确认本地模型登录状态后重试。"
                ) from exc
            except StopAsyncIteration:
                return

            async for event in emit_sdk_message(first_message):
                yield event

            async for message in message_stream:
                async for event in emit_sdk_message(message):
                    yield event

    async def run_session(
        self,
        *,
        cwd: str | None,
        prompt: str,
        session_history: list[SessionMessageOut],
    ) -> ClaudeCodeRunResult:
        """运行一次会话请求，并聚合为兼容旧接口的完整结果。"""
        content_parts: list[str] = []
        tool_summary: list[dict[str, Any]] = []
        diff_summary: list[dict[str, Any]] = []

        async for event in self.stream_session(
            cwd=cwd,
            prompt=prompt,
            session_history=session_history,
        ):
            if event.type == "assistant_delta":
                content_parts.append(str(event.data.get("content", "")))
            elif event.type in {"tool_start", "tool_delta", "tool_done"}:
                tool_summary.append({"type": event.type, **event.data})
            elif event.type == "sdk_result":
                diff_summary.append(event.data)

        content = "".join(content_parts).strip() or "推理完成，但没有返回文本内容。"
        return ClaudeCodeRunResult(
            content=content,
            tool_summary=tool_summary,
            changed_files=[],
            diff_summary=diff_summary,
        )

    async def _stream_event_to_sse(
        self,
        event: Any,
        current_tool: dict[str, Any] | None,
    ) -> AsyncIterator[ClaudeCodeStreamEvent]:
        """将 SDK StreamEvent 转换为业务 SSE 事件。"""
        payload = getattr(event, "event", None)
        raw_event = payload if isinstance(payload, dict) else None
        event_type = self._read_value(raw_event, event, "type") or ""
        if event_type == "content_block_start":
            block = self._read_value(raw_event, event, "content_block")
            block_type = self._read_value(block, block, "type")
            if block_type == "tool_use":
                yield ClaudeCodeStreamEvent(
                    type="tool_start",
                    data={
                        "id": self._read_value(block, block, "id"),
                        "name": self._read_value(block, block, "name") or "tool",
                        "input": self._safe_dump(self._read_value(block, block, "input")),
                    },
                )
            return

        if event_type == "content_block_delta":
            delta = self._read_value(raw_event, event, "delta")
            delta_type = self._read_value(delta, delta, "type") or ""
            if delta_type == "text_delta":
                text = self._read_value(delta, delta, "text") or ""
                if text:
                    yield ClaudeCodeStreamEvent(
                        type="assistant_delta",
                        data={"content": text},
                    )
                return
            if delta_type == "input_json_delta":
                partial_json = self._read_value(delta, delta, "partial_json") or ""
                if partial_json:
                    yield ClaudeCodeStreamEvent(
                        type="tool_delta",
                        data={
                            "id": current_tool.get("id") if current_tool else None,
                            "name": current_tool.get("name") if current_tool else "tool",
                            "partial": partial_json,
                        },
                    )
                return

        if event_type == "content_block_stop" and current_tool:
            yield ClaudeCodeStreamEvent(
                type="tool_done",
                data={
                    "id": current_tool.get("id"),
                    "name": current_tool.get("name"),
                },
            )
            return

        if event_type == "message_delta":
            usage = self._safe_dump(self._read_value(raw_event, event, "usage"))
            if usage:
                yield ClaudeCodeStreamEvent(type="usage", data={"usage": usage})

    @staticmethod
    def _prepare_environment() -> None:
        """准备 SDK 所需环境变量。"""
        if not os.getenv("ANTHROPIC_API_KEY") and os.getenv("ZHIPU_API_KEY"):
            os.environ["ANTHROPIC_API_KEY"] = os.environ["ZHIPU_API_KEY"]

    def _resolve_cwd(self, cwd: str | None) -> str:
        """解析 SDK 工作目录。"""
        if not cwd:
            raise BizValidationError("项目未绑定本地目录，请重新选择真实项目目录")
        return cwd

    @staticmethod
    def _format_prompt(prompt: str, session_history: list[SessionMessageOut]) -> str:
        """把历史消息压缩进当前请求上下文。"""
        recent_history = session_history[-12:]
        history_text = "\n".join(
            f"{item.role}: {item.content}" for item in recent_history if item.content
        )
        if not history_text:
            return prompt
        return f"以下是当前会话最近历史，请结合上下文处理最新请求。\n\n{history_text}\n\n最新请求：{prompt}"

    @staticmethod
    def _extract_assistant_text(message: Any) -> str:
        """从完整 AssistantMessage 中提取文本内容。"""
        parts: list[str] = []
        for block in getattr(message, "content", []) or []:
            if block.__class__.__name__ == "TextBlock":
                text = getattr(block, "text", "")
                if text:
                    parts.append(text)
        return "".join(parts)

    @staticmethod
    def _read_value(mapping: dict[str, Any] | None, obj: Any, name: str) -> Any:
        """兼容 dict 事件与 SDK dataclass 对象取值。"""
        if mapping is not None:
            return mapping.get(name)
        return getattr(obj, name, None)

    @staticmethod
    def _result_message_to_data(message: Any) -> dict[str, Any]:
        """提取 SDK 结果消息的可展示字段。"""
        data: dict[str, Any] = {}
        for name in (
            "subtype",
            "duration_ms",
            "duration_api_ms",
            "is_error",
            "num_turns",
            "total_cost_usd",
        ):
            value = getattr(message, name, None)
            if value is not None:
                data[name] = value
        usage = ClaudeCodeService._safe_dump(getattr(message, "usage", None))
        if usage:
            data["usage"] = usage
        return data

    @staticmethod
    def _safe_dump(value: Any) -> Any:
        """把 SDK/Pydantic 对象转为可 JSON 序列化的数据。"""
        if value is None:
            return None
        if hasattr(value, "model_dump"):
            return value.model_dump()
        if isinstance(value, (str, int, float, bool, list, dict)):
            return value
        return str(value)

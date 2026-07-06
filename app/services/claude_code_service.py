"""Claude Agent SDK 调用封装。"""
from __future__ import annotations

import asyncio
import json
import os
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

from app.core.settings import AgentPlatformSettings, ClaudeAgentSettings
from app.exceptions import BizValidationError
from app.schemas.local_agent import LocalAgentTaskCreateIn
from app.schemas.project import SessionMessageOut
from app.services.agent_platform_service import AgentPlatformCapabilities
from app.services.agent_platform_service import load_agent_platform_capabilities
from app.services.local_agent_service import get_local_agent_hub


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

    def __init__(
        self,
        settings: ClaudeAgentSettings | None = None,
        agent_platform_settings: AgentPlatformSettings | None = None,
    ) -> None:
        self._settings = settings or ClaudeAgentSettings()
        self._agent_platform_settings = agent_platform_settings or AgentPlatformSettings()

    async def stream_session(
        self,
        *,
        cwd: str | None,
        prompt: str,
        session_history: list[SessionMessageOut],
        platform_capabilities: AgentPlatformCapabilities | None = None,
    ) -> AsyncIterator[ClaudeCodeStreamEvent]:
        """流式运行一次 agent 会话请求。"""
        if not self._settings.enabled:
            raise BizValidationError("推理服务已禁用")

        self._prepare_environment()
        project_root = self._resolve_cwd(cwd)
        formatted_prompt = self._format_prompt(prompt, session_history)

        try:
            from claude_agent_sdk import query
            options = await self._build_options(project_root, platform_capabilities)
        except ImportError as exc:
            raise BizValidationError(
                "推理服务依赖未安装，请先安装依赖后再重试"
            ) from exc

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
        platform_capabilities: AgentPlatformCapabilities | None = None,
    ) -> ClaudeCodeRunResult:
        """运行一次会话请求，并聚合为兼容旧接口的完整结果。"""
        content_parts: list[str] = []
        tool_summary: list[dict[str, Any]] = []
        diff_summary: list[dict[str, Any]] = []

        async with asyncio.timeout(self._settings.command_timeout):
            async for event in self.stream_session(
                cwd=cwd,
                prompt=prompt,
                session_history=session_history,
                platform_capabilities=platform_capabilities,
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

    async def _build_options(
        self,
        project_root: str,
        platform_capabilities: AgentPlatformCapabilities | None = None,
    ) -> Any:
        """构造 Claude Agent SDK options。"""
        from claude_agent_sdk import ClaudeAgentOptions

        capabilities = platform_capabilities or await load_agent_platform_capabilities(
            self._agent_platform_settings
        )
        platform_mcp_servers = self._capability_mcp_servers(capabilities)
        platform_allowed_tools = self._capability_allowed_tools(capabilities)
        platform_prompt = self._render_capabilities_system_prompt(capabilities)
        sdk_env = self._build_sdk_env()

        if self._settings.use_local_agent_relay:
            mcp_servers = {
                "local_agent": self._build_local_agent_mcp_server(project_root),
                **{
                    name: config
                    for name, config in platform_mcp_servers.items()
                    if name != "local_agent"
                },
            }
            return ClaudeAgentOptions(
                tools=[],
                allowed_tools=[
                    "local_tool",
                    "mcp__local_agent__local_tool",
                    *platform_allowed_tools,
                ],
                system_prompt=self._join_system_prompts(
                    self._build_local_agent_system_prompt(),
                    platform_prompt,
                ),
                permission_mode=self._settings.permission_mode,
                include_partial_messages=self._settings.include_partial_messages,
                include_hook_events=True,
                cwd=self._resolve_sdk_cwd(),
                env=sdk_env,
                mcp_servers=mcp_servers,
                strict_mcp_config=True,
                setting_sources=None,
                skills=None,
                extra_args={"disable-slash-commands": None},
            )

        return ClaudeAgentOptions(
            tools=[],
            allowed_tools=platform_allowed_tools,
            system_prompt=platform_prompt,
            permission_mode=self._settings.permission_mode,
            include_partial_messages=self._settings.include_partial_messages,
            include_hook_events=True,
            cwd=project_root,
            env=sdk_env,
            mcp_servers=platform_mcp_servers,
            strict_mcp_config=True,
            setting_sources=None,
            skills=None,
            extra_args={"disable-slash-commands": None},
        )

    @staticmethod
    def _capability_mcp_servers(capabilities: Any) -> dict[str, Any]:
        """读取平台 MCP Server 配置，兼容测试替身对象。"""
        value = getattr(capabilities, "mcp_servers", {})
        return value if isinstance(value, dict) else {}

    @staticmethod
    def _capability_allowed_tools(capabilities: Any) -> list[str]:
        """读取平台 allowed_tools，兼容测试替身对象。"""
        value = getattr(capabilities, "allowed_tools", [])
        return [str(item) for item in value] if isinstance(value, list) else []

    @staticmethod
    def _render_capabilities_system_prompt(capabilities: Any) -> str:
        """渲染平台能力提示词，兼容正式模型与测试替身对象。"""
        renderer = getattr(capabilities, "render_system_prompt", None)
        if callable(renderer):
            return str(renderer())

        parts: list[str] = []
        system_prompt = str(getattr(capabilities, "system_prompt", "") or "").strip()
        if system_prompt:
            parts.append(system_prompt)
        skill_prompts = getattr(capabilities, "skill_prompts", []) or []
        for skill in skill_prompts:
            if isinstance(skill, dict):
                name = str(skill.get("name") or "")
                description = str(skill.get("description") or "")
                content = str(skill.get("content") or skill.get("prompt") or "")
            else:
                name = str(getattr(skill, "name", "") or "")
                description = str(getattr(skill, "description", "") or "")
                content = str(getattr(skill, "content", "") or "")
            section = [f"【Skill: {name}】"]
            if description:
                section.append(f"描述：{description}")
            if content:
                section.append(content)
            parts.append("\n".join(item for item in section if item))
        return "\n\n".join(part for part in parts if part.strip())

    @staticmethod
    def _join_system_prompts(*parts: str) -> str:
        """拼接多个系统提示片段。"""
        return "\n\n".join(part.strip() for part in parts if part and part.strip())

    @staticmethod
    def _build_sdk_env() -> dict[str, str]:
        """构造 SDK 子进程环境变量，保留认证并移除桌面入口噪音。"""
        env = dict(os.environ)
        env.pop("CLAUDE_CODE_ENTRYPOINT", None)
        return env

    def _resolve_sdk_cwd(self) -> str:
        """返回远端 SDK 进程可用的工作目录。

        local-agent relay 模式下，用户项目路径可能只存在于用户本机，
        不能再作为远端 SDK 进程 cwd；此处仅选择服务端真实存在的目录启动 SDK。
        """
        configured = Path(self._settings.default_cwd).expanduser()
        candidates = [
            (
                configured.resolve()
                if configured.is_absolute()
                else Path.cwd().joinpath(configured).resolve()
            ),
            Path.cwd().resolve(),
        ]
        for candidate in candidates:
            if candidate.exists() and candidate.is_dir():
                return str(candidate)
        return str(Path.cwd().resolve())

    def _build_local_agent_mcp_server(self, project_root: str) -> dict[str, Any]:
        """创建只负责转发到本地连接器的 SDK MCP Server。"""
        from claude_agent_sdk import create_sdk_mcp_server, tool

        schema = {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "ping_path",
                        "list_tree",
                        "shell",
                        "read_file",
                        "write_file",
                        "apply_patch",
                    ],
                    "description": "要在用户本机项目目录下执行的动作",
                },
                "payload": {
                    "type": "object",
                    "description": "动作参数，例如 shell 使用 args 或 command，write_file 使用 path/content",
                },
                "timeout_seconds": {
                    "type": "integer",
                    "minimum": 1,
                    "maximum": 3600,
                    "description": "本次动作的超时秒数",
                },
            },
            "required": ["action"],
        }

        @tool(
            "local_tool",
            (
                "Execute file, patch, directory listing, or shell actions through "
                "the user's local claude-sdk agent. Always use this tool for project "
                "filesystem and command operations."
            ),
            schema,
        )
        async def local_tool(args: dict[str, Any]) -> dict[str, Any]:
            """把 Claude 工具调用转成本地连接器任务。"""
            return await self._call_local_agent_tool(project_root, args)

        return create_sdk_mcp_server("local_agent", tools=[local_tool])

    async def _call_local_agent_tool(
        self,
        project_root: str,
        args: dict[str, Any],
    ) -> dict[str, Any]:
        """创建 local-agent 任务并等待用户本机脚本执行完成。"""
        try:
            action = str(args.get("action") or "").strip()
            payload = args.get("payload") if isinstance(args.get("payload"), dict) else {}
            timeout_seconds = self._resolve_local_agent_timeout(args)
            task = await get_local_agent_hub().create_task(
                LocalAgentTaskCreateIn(
                    root_path=project_root,
                    action=action,
                    payload=payload,
                    timeout_seconds=timeout_seconds,
                )
            )
            completed = await get_local_agent_hub().wait_task(
                task.id,
                timeout_seconds + 5,
            )
            data = {
                "task_id": completed.id,
                "status": completed.status,
                "result": completed.result,
                "error": completed.error,
            }
            return self._local_agent_tool_result(data, is_error=completed.status == "failed")
        except Exception as exc:
            message = exc.message if isinstance(exc, BizValidationError) else str(exc)
            return self._local_agent_tool_result(
                {
                    "status": "failed",
                    "error": message or exc.__class__.__name__,
                },
                is_error=True,
            )

    def _resolve_local_agent_timeout(self, args: dict[str, Any]) -> int:
        """解析 local_tool 超时，非法值回落到配置默认值。"""
        raw_timeout = args.get("timeout_seconds")
        try:
            timeout_seconds = (
                int(raw_timeout)
                if raw_timeout is not None
                else self._settings.local_agent_task_timeout
            )
        except (TypeError, ValueError):
            timeout_seconds = self._settings.local_agent_task_timeout
        return min(max(timeout_seconds, 1), 3600)

    @staticmethod
    def _local_agent_tool_result(data: dict[str, Any], *, is_error: bool) -> dict[str, Any]:
        """把本地连接器结果转成 MCP tool result。"""
        return {
            "content": [
                {
                    "type": "text",
                    "text": json.dumps(data, ensure_ascii=False),
                }
            ],
            "is_error": is_error,
        }

    @staticmethod
    def _build_local_agent_system_prompt() -> str:
        """构造 relay 模式下的系统提示。"""
        return (
            "你在远端 claude-sdk 服务中运行，不能直接读写用户电脑上的项目文件。"
            "所有项目文件读取、写入、补丁应用、目录查看和 shell 命令执行，都必须调用 MCP 工具 local_tool。"
            "local_tool 会自动在当前项目 root_path 下由用户本机连接器执行，不要让用户再提供 root_path。"
            "可用 action 包括 ping_path、list_tree、shell、read_file、write_file、apply_patch。"
            "写文件使用 action=write_file 且 payload 包含 path/content；执行命令优先使用 shell 的 payload.args 列表。"
            "不要尝试使用服务器本机路径或内置 Bash/Read/Edit 工具。"
        )

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

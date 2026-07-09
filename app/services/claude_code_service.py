"""Claude Agent SDK 调用封装。"""
from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
from collections.abc import AsyncIterator
from contextlib import suppress
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

MCP_ENV_PLACEHOLDER_RE = re.compile(r"^\$\{([A-Za-z_][A-Za-z0-9_]*)\}$")
CLAUDE_AUTH_ENV_NAMES = {"CLAUDE_CODE_OAUTH_TOKEN"}
CLAUDE_AUTH_ENV_PREFIXES = ("ANTHROPIC_",)


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
            from claude_agent_sdk import ClaudeSDKClient
            capabilities = platform_capabilities or await load_agent_platform_capabilities(
                self._agent_platform_settings
            )
            options = await self._build_options(project_root, capabilities)
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

        async with ClaudeSDKClient(options) as client:
            await self._wait_for_platform_mcp_servers(
                client,
                self._platform_mcp_server_names_from_options(options),
            )
            await client.query(formatted_prompt)
            message_stream = aiter(client.receive_response())
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
        sdk_env = self._build_sdk_env()
        platform_mcp_servers, disabled_mcp_errors = self._resolve_platform_mcp_stdio_commands(
            self._capability_mcp_servers(capabilities),
            sdk_env,
        )
        enabled_mcp_names = set(platform_mcp_servers)
        platform_allowed_tools = self._filter_allowed_tools_by_mcp_servers(
            self._capability_allowed_tools(capabilities),
            enabled_mcp_names,
        )
        prompt_capabilities = self._capabilities_for_runtime_prompt(
            capabilities,
            enabled_mcp_names,
        )
        platform_prompt = self._append_disabled_mcp_prompt(
            self._render_capabilities_system_prompt(prompt_capabilities),
            disabled_mcp_errors,
        )

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
                tools=None,
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
                setting_sources=self._sdk_setting_sources(),
                skills=None,
                extra_args={"disable-slash-commands": None},
            )

        return ClaudeAgentOptions(
            tools=None,
            allowed_tools=platform_allowed_tools,
            system_prompt=platform_prompt,
            permission_mode=self._settings.permission_mode,
            include_partial_messages=self._settings.include_partial_messages,
            include_hook_events=True,
            cwd=project_root,
            env=sdk_env,
            mcp_servers=platform_mcp_servers,
            strict_mcp_config=True,
            setting_sources=self._sdk_setting_sources(),
            skills=None,
            extra_args={"disable-slash-commands": None},
        )

    async def _wait_for_platform_mcp_servers(
        self,
        client: Any,
        server_names: list[str],
    ) -> None:
        """等待平台 MCP 连接完成，确保工具 schema 进入模型上下文。"""
        if not server_names:
            return

        deadline = asyncio.get_running_loop().time() + self._settings.startup_timeout
        last_status: dict[str, Any] = {}
        while True:
            status_payload = await client.get_mcp_status()
            servers = status_payload.get("mcpServers", [])
            status_by_name = {
                str(server.get("name")): server
                for server in servers
                if isinstance(server, dict)
            }
            allowed_server_names = {*server_names, "local_agent"}
            unknown_server_names = sorted(
                name
                for name in status_by_name
                if name and name not in allowed_server_names
            )
            if unknown_server_names:
                raise BizValidationError(
                    "检测到非平台 MCP Server，已拒绝加载: "
                    f"{json.dumps(unknown_server_names, ensure_ascii=False)}"
                )
            last_status = status_by_name
            not_ready: list[str] = []
            failed: list[str] = []
            for name in server_names:
                server = status_by_name.get(name)
                status = str(server.get("status") if server else "missing")
                tools = server.get("tools") if server else None
                if status == "connected" and isinstance(tools, list) and tools:
                    continue
                if status in {"failed", "needs-auth", "disabled"}:
                    failed.append(name)
                else:
                    not_ready.append(name)

            if not not_ready and not failed:
                return

            if failed:
                details = {
                    name: status_by_name.get(name, {})
                    for name in failed
                }
                raise BizValidationError(
                    "平台 MCP 连接失败，工具 schema 未加载: "
                    f"{json.dumps(details, ensure_ascii=False)}"
                )

            if asyncio.get_running_loop().time() >= deadline:
                details = {
                    name: last_status.get(name, {"status": "missing"})
                    for name in not_ready
                }
                raise BizValidationError(
                    "平台 MCP 连接超时，工具 schema 未加载: "
                    f"{json.dumps(details, ensure_ascii=False)}"
                )

            await asyncio.sleep(0.5)

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
    def _filter_allowed_tools_by_mcp_servers(
        allowed_tools: list[str],
        enabled_mcp_names: set[str],
    ) -> list[str]:
        """过滤已禁用 MCP 的工具白名单，避免模型看到不可调用函数。"""
        filtered: list[str] = []
        for tool_name in allowed_tools:
            if not tool_name.startswith("mcp__"):
                filtered.append(tool_name)
                continue
            parts = tool_name.split("__", 2)
            if len(parts) < 3 or parts[1] in enabled_mcp_names:
                filtered.append(tool_name)
        return filtered

    @staticmethod
    def _capabilities_for_runtime_prompt(
        capabilities: Any,
        enabled_mcp_names: set[str],
    ) -> Any:
        """生成本轮运行时提示词使用的能力视图。"""
        loaded_servers = getattr(capabilities, "loaded_mcp_servers", None)
        if not isinstance(loaded_servers, list):
            return capabilities

        filtered_servers = [
            server
            for server in loaded_servers
            if str(getattr(server, "name", "") or "") in enabled_mcp_names
        ]
        if isinstance(capabilities, AgentPlatformCapabilities):
            return capabilities.model_copy(
                update={"loaded_mcp_servers": filtered_servers}
            )
        return capabilities

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
    def _append_disabled_mcp_prompt(
        platform_prompt: str,
        disabled_mcp_errors: dict[str, str],
    ) -> str:
        """追加本轮未启用 MCP 的原因，便于普通提问得到可解释回答。"""
        if not disabled_mcp_errors:
            return platform_prompt

        lines = ["平台 MCP 已配置但当前未启用，不能调用这些 MCP 工具："]
        for name, reason in sorted(disabled_mcp_errors.items()):
            lines.append(f"- {name}: {reason}")
        return ClaudeCodeService._join_system_prompts(
            platform_prompt,
            "\n".join(lines),
        )

    @staticmethod
    def _join_system_prompts(*parts: str) -> str:
        """拼接多个系统提示片段。"""
        return "\n\n".join(part.strip() for part in parts if part and part.strip())

    @staticmethod
    def _build_sdk_env() -> dict[str, str]:
        """构造 SDK 子进程环境变量，隔离用户/项目 Claude 配置来源。"""
        env = dict(os.environ)
        env.pop("CLAUDE_CODE_ENTRYPOINT", None)
        source_config_dir = ClaudeCodeService._source_claude_config_dir(env)
        ClaudeCodeService._inherit_claude_auth_env(env, source_config_dir)
        env["PATH"] = ClaudeCodeService._build_sdk_path(env)
        isolated_dirs = ClaudeCodeService._ensure_isolated_claude_runtime_dirs()
        ClaudeCodeService._copy_claude_auth_files(
            source_config_dir,
            isolated_dirs["claude_config"],
        )
        env["CLAUDE_CONFIG_DIR"] = str(isolated_dirs["claude_config"])
        env["HOME"] = str(isolated_dirs["home"])
        env["XDG_CONFIG_HOME"] = str(isolated_dirs["xdg_config"])
        return env

    @staticmethod
    def _sdk_setting_sources() -> list[str]:
        """限制 Claude CLI 只读取隔离后的 user 配置源。"""
        return ["user"]

    @staticmethod
    def _ensure_isolated_claude_runtime_dirs() -> dict[str, Path]:
        """创建服务私有 Claude 运行目录，避免读取真实用户或项目配置。"""
        base_dir = ClaudeCodeService._isolated_claude_runtime_base()
        dirs = {
            "home": base_dir / "home",
            "xdg_config": base_dir / "xdg-config",
            "claude_config": base_dir / "claude-config",
        }
        for path in dirs.values():
            path.mkdir(parents=True, exist_ok=True)
        return dirs

    @staticmethod
    def _source_claude_config_dir(env: dict[str, str]) -> Path:
        """解析真实 Claude 配置目录，仅用于迁移认证，不读取 MCP 配置。"""
        raw_config_dir = str(env.get("CLAUDE_CONFIG_DIR") or "").strip()
        if raw_config_dir:
            path = Path(raw_config_dir).expanduser()
            return path if path.is_absolute() else Path.cwd().joinpath(path).resolve()
        home = Path(str(env.get("HOME") or str(Path.home()))).expanduser()
        return home / ".claude"

    @staticmethod
    def _inherit_claude_auth_env(env: dict[str, str], source_config_dir: Path) -> None:
        """只从用户 settings.json 的 env 白名单继承认证变量，不继承 MCP 配置。"""
        settings_path = source_config_dir / "settings.json"
        try:
            payload = json.loads(settings_path.read_text("utf-8"))
        except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
            return
        raw_env = payload.get("env") if isinstance(payload, dict) else None
        if not isinstance(raw_env, dict):
            return
        for key, value in raw_env.items():
            name = str(key)
            if not ClaudeCodeService._is_claude_auth_env_name(name):
                continue
            if str(env.get(name) or "").strip():
                continue
            text_value = str(value).strip()
            if text_value:
                env[name] = text_value

    @staticmethod
    def _is_claude_auth_env_name(name: str) -> bool:
        """判断是否允许从用户 Claude settings env 继承。"""
        return name in CLAUDE_AUTH_ENV_NAMES or any(
            name.startswith(prefix)
            for prefix in CLAUDE_AUTH_ENV_PREFIXES
        )

    @staticmethod
    def _copy_claude_auth_files(source_config_dir: Path, target_config_dir: Path) -> None:
        """复制 OAuth 认证文件，不复制 settings/mcp 配置。"""
        source_credentials = source_config_dir / ".credentials.json"
        target_credentials = target_config_dir / ".credentials.json"
        with suppress(FileNotFoundError, OSError):
            shutil.copyfile(source_credentials, target_credentials)
            target_credentials.chmod(0o600)

    @staticmethod
    def _isolated_claude_runtime_base() -> Path:
        """解析隔离运行目录，默认落在项目 .runtime 下。"""
        raw = os.getenv("CLAUDE_SDK_AGENT_RUNTIME_DIR", "").strip()
        if raw:
            path = Path(raw).expanduser()
            return path if path.is_absolute() else Path.cwd().joinpath(path).resolve()
        return Path.cwd().joinpath(".runtime", "claude-agent-sdk").resolve()

    @staticmethod
    def _build_sdk_path(env: dict[str, str]) -> str:
        """补齐 SDK 子进程 PATH，避免非交互服务进程找不到 nvm/npm 工具。"""
        path_entries = [
            item
            for item in str(env.get("PATH") or "").split(os.pathsep)
            if item
        ]
        for candidate in ClaudeCodeService._sdk_path_candidates(env):
            if candidate and candidate not in path_entries:
                path_entries.append(candidate)
        return os.pathsep.join(path_entries)

    @staticmethod
    def _sdk_path_candidates(env: dict[str, str]) -> list[str]:
        """发现常见 Node/npm 安装目录，供平台 stdio MCP（如 npx）启动使用。"""
        candidates: list[str] = []
        for key in ("NVM_BIN", "PNPM_HOME"):
            value = str(env.get(key) or "").strip()
            if value:
                candidates.append(value)

        volta_home = str(env.get("VOLTA_HOME") or "").strip()
        if volta_home:
            candidates.append(str(Path(volta_home).expanduser() / "bin"))

        home = Path(str(env.get("HOME") or "")).expanduser()
        if str(home):
            candidates.extend(
                [
                    str(home / ".volta" / "bin"),
                    str(home / ".local" / "bin"),
                ]
            )
            nvm_versions_dir = home / ".nvm" / "versions" / "node"
            if nvm_versions_dir.exists():
                candidates.extend(
                    str(path)
                    for path in sorted(
                        nvm_versions_dir.glob("v*/bin"),
                        key=ClaudeCodeService._node_bin_sort_key,
                        reverse=True,
                    )
                )

        candidates.extend(
            [
                "/opt/homebrew/bin",
                "/usr/local/bin",
                "/usr/bin",
                "/bin",
                "/usr/sbin",
                "/sbin",
            ]
        )
        return [
            candidate
            for candidate in candidates
            if Path(candidate).expanduser().is_dir()
        ]

    @staticmethod
    def _node_bin_sort_key(path: Path) -> tuple[int, int, int, str]:
        """按 Node 版本排序 nvm bin 目录，优先选择较新的版本。"""
        version = path.parent.name.lstrip("v")
        parts = version.split(".")
        numbers: list[int] = []
        for part in parts[:3]:
            try:
                numbers.append(int(part))
            except ValueError:
                numbers.append(0)
        while len(numbers) < 3:
            numbers.append(0)
        return numbers[0], numbers[1], numbers[2], str(path)

    @staticmethod
    def _resolve_platform_mcp_stdio_commands(
        mcp_servers: dict[str, Any],
        env: dict[str, str],
    ) -> tuple[dict[str, Any], dict[str, str]]:
        """解析平台 MCP 运行配置，补齐命令路径与敏感环境变量。"""
        resolved_servers: dict[str, Any] = {}
        disabled_errors: dict[str, str] = {}
        for name, config in mcp_servers.items():
            if not isinstance(config, dict):
                resolved_servers[name] = config
                continue

            resolved_config = dict(config)
            try:
                resolved_config = ClaudeCodeService._resolve_platform_mcp_env(
                    name,
                    resolved_config,
                    env,
                )
            except BizValidationError as exc:
                disabled_errors[str(name)] = exc.message
                continue
            command = resolved_config.get("command")
            if (
                str(resolved_config.get("type") or "") == "stdio"
                and isinstance(command, str)
                and ClaudeCodeService._is_plain_executable_name(command)
            ):
                executable = shutil.which(command.strip(), path=str(env.get("PATH") or ""))
                if executable:
                    resolved_config["command"] = executable
            resolved_servers[name] = resolved_config
        return resolved_servers, disabled_errors

    @staticmethod
    def _platform_mcp_server_names_from_options(options: Any) -> list[str]:
        """从 SDK options 中读取本轮实际启用的平台 MCP 名称。"""
        mcp_servers = getattr(options, "mcp_servers", {}) or {}
        if not isinstance(mcp_servers, dict):
            return []
        return [
            str(name)
            for name in mcp_servers
            if str(name) != "local_agent"
        ]

    @staticmethod
    def _resolve_platform_mcp_env(
        server_name: str,
        config: dict[str, Any],
        service_env: dict[str, str],
    ) -> dict[str, Any]:
        """将平台 MCP env 占位符解析为服务进程环境变量。"""
        raw_env = config.get("env")
        if raw_env is None:
            return config
        if not isinstance(raw_env, dict):
            raise BizValidationError(f"平台 MCP env 配置必须是对象: {server_name}")

        resolved_env: dict[str, str] = {}
        for key, value in raw_env.items():
            target_key = str(key)
            if not target_key.strip():
                continue
            resolved_env[target_key] = ClaudeCodeService._resolve_platform_mcp_env_value(
                server_name,
                target_key,
                value,
                service_env,
            )

        resolved_config = dict(config)
        resolved_config["env"] = resolved_env
        return resolved_config

    @staticmethod
    def _resolve_platform_mcp_env_value(
        server_name: str,
        target_key: str,
        value: Any,
        service_env: dict[str, str],
    ) -> str:
        """解析单个平台 MCP env 值；${NAME} 表示从服务环境读取。"""
        raw_value = str(value)
        match = MCP_ENV_PLACEHOLDER_RE.match(raw_value.strip())
        if not match:
            return raw_value

        source_key = match.group(1)
        resolved = str(service_env.get(source_key) or "").strip()
        if not resolved:
            raise BizValidationError(
                "平台 MCP 环境变量未配置: "
                f"{server_name}.{target_key} <- {source_key}"
            )
        return resolved

    @staticmethod
    def _is_plain_executable_name(command: str) -> bool:
        """判断 command 是否是不带路径/参数的可执行文件名。"""
        value = command.strip()
        if not value or any(char.isspace() for char in value):
            return False
        return Path(value).name == value

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
            "公司平台 MCP 工具（例如 github）必须直接调用对应的 MCP 工具，不要通过 local_tool 转发。"
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

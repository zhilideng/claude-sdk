"""Agent 平台能力加载服务。

MVP 阶段支持两类来源：
- ``base_url`` 为空：读取仓库内 mock 平台数据，便于本地快速跑通；
- ``base_url`` 非空：调用公司内部平台接口，返回格式保持与 mock 一致。
"""
from __future__ import annotations

import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlparse

import yaml
from loguru import logger
from pydantic import BaseModel, Field

from app.core.settings import AgentPlatformSettings
from app.utils import http_client

FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n?(.*)$", re.DOTALL)


class AgentSkillPrompt(BaseModel):
    """注入 Agent system prompt 的平台 Skill。"""

    id: str = ""
    name: str
    version: str = "1.0.0"
    description: str = ""
    content: str
    source_url: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)
    status: str = "loaded"
    error_message: str | None = None


class AgentMcpTool(BaseModel):
    """平台 MCP 工具描述。"""

    server_name: str
    name: str
    full_name: str
    description: str = ""
    input_schema: dict[str, Any] = Field(default_factory=dict)


class AgentMcpServer(BaseModel):
    """平台 MCP Server 加载状态。"""

    name: str
    status: str = "connected"
    tools: list[AgentMcpTool] = Field(default_factory=list)
    error_message: str | None = None


class AgentPlatformCapabilities(BaseModel):
    """一次平台能力加载后的运行时资产。"""

    asset_version: str = "empty"
    app_code: str = "codex-web"
    scene: str = "default"
    raw_config: dict[str, Any] = Field(default_factory=dict)
    mcp_servers: dict[str, dict[str, Any]] = Field(default_factory=dict)
    allowed_tools: list[str] = Field(default_factory=list)
    system_prompt: str = ""
    skill_prompts: list[AgentSkillPrompt] = Field(default_factory=list)
    loaded_mcp_servers: list[AgentMcpServer] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)

    def render_system_prompt(self) -> str:
        """渲染平台下发的 Skill 与工具约束。"""
        parts: list[str] = []
        if self.system_prompt.strip():
            parts.append(self.system_prompt.strip())

        if self.skill_prompts:
            parts.append("以下是公司内部平台下发的 Skill，你必须优先遵循这些 Skill 的执行规则。")
            for skill in self.skill_prompts:
                section = [
                    f"【Skill: {skill.name}】",
                    f"版本：{skill.version}",
                ]
                if skill.description:
                    section.append(f"描述：{skill.description}")
                section.append(skill.content.strip())
                parts.append("\n".join(section))

        tools = [
            tool
            for server in self.loaded_mcp_servers
            for tool in server.tools
        ]
        if tools:
            parts.append("当前你可以使用以下 MCP 工具：")
            tool_lines = []
            for index, tool in enumerate(tools, start=1):
                item = f"{index}. {tool.full_name}"
                if tool.description:
                    item += f"\n   描述：{tool.description}"
                if tool.input_schema:
                    item += (
                        "\n   输入参数："
                        f"{json.dumps(tool.input_schema, ensure_ascii=False)}"
                    )
                tool_lines.append(item)
            parts.append("\n".join(tool_lines))

        if self.skill_prompts or tools:
            parts.append(
                "规则：\n"
                "1. 只能使用当前会话加载到的 MCP 工具。\n"
                "2. 不要假设存在未注册的 MCP 工具。\n"
                "3. 当用户任务与某个 Skill 匹配时，优先按照该 Skill 的步骤执行。\n"
                "4. 如果 Skill 与用户明确要求冲突，优先遵循用户当前明确要求。"
            )

        return "\n\n".join(part for part in parts if part.strip())


def empty_agent_platform_capabilities(
    settings: AgentPlatformSettings | None = None,
    *,
    error: str | None = None,
) -> AgentPlatformCapabilities:
    """返回空平台能力包。"""
    settings = settings or AgentPlatformSettings(enabled=False)
    errors = [error] if error else []
    return AgentPlatformCapabilities(
        asset_version=f"empty-{datetime.now(UTC):%Y%m%d%H%M%S}",
        app_code=settings.app_code,
        scene=settings.scene,
        errors=errors,
    )


async def load_agent_platform_capabilities(
    settings: AgentPlatformSettings,
) -> AgentPlatformCapabilities:
    """加载并归一化 Agent 平台 MCP/Skill 能力。"""
    if not settings.enabled:
        logger.info("agent 平台能力加载已关闭，返回空能力")
        return empty_agent_platform_capabilities(settings)

    try:
        payload = await _fetch_platform_payload(settings)
        data = _extract_payload_data(payload)
        capabilities = await _build_capabilities(data, settings)
        logger.info(
            "agent 平台能力加载完成 | version={} | mcp_count={} | skill_count={}",
            capabilities.asset_version,
            len(capabilities.mcp_servers),
            len(capabilities.skill_prompts),
        )
        return capabilities
    except Exception as exc:
        logger.warning("agent 平台能力加载失败，返回空能力 | err={}", exc)
        return empty_agent_platform_capabilities(settings, error=str(exc))


async def _fetch_platform_payload(settings: AgentPlatformSettings) -> dict[str, Any]:
    """获取平台原始响应。"""
    if not settings.base_url.strip():
        return _load_mock_payload()

    base = settings.base_url.rstrip("/") + "/"
    path = settings.capabilities_path.lstrip("/")
    url = urljoin(base, path)
    headers = _build_auth_headers()
    response = await http_client.get(url, headers=headers, timeout=settings.timeout)
    payload = response.json()
    if not isinstance(payload, dict):
        raise ValueError("平台能力接口返回值不是 JSON object")
    return payload


def _build_auth_headers() -> dict[str, str]:
    """构造平台接口认证头。"""
    token = os.getenv("AGENT_PLATFORM_TOKEN", "").strip()
    return {"Authorization": f"Bearer {token}"} if token else {}


def _load_mock_payload() -> dict[str, Any]:
    """读取本地 mock 平台资产。"""
    path = _repo_root() / "app" / "mock_platform" / "mock-assets.json"
    return {"code": 0, "message": "success", "data": json.loads(path.read_text("utf-8"))}


def _extract_payload_data(payload: dict[str, Any]) -> dict[str, Any]:
    """从平台响应中提取 data 段。"""
    code = payload.get("code", 0)
    if code not in (0, 200):
        raise ValueError(f"平台能力接口返回失败 code={code}")
    data = payload.get("data", payload)
    if not isinstance(data, dict):
        raise ValueError("平台能力接口 data 不是 JSON object")
    return data


async def _build_capabilities(
    data: dict[str, Any],
    settings: AgentPlatformSettings,
) -> AgentPlatformCapabilities:
    """归一化平台能力结构。"""
    raw_mcp_servers = _extract_mcp_servers(data)
    mcp_servers = _normalize_mcp_servers(raw_mcp_servers)
    loaded_mcp_servers = _describe_mcp_servers(raw_mcp_servers)
    allowed_tools = _normalize_allowed_tools(data, loaded_mcp_servers)
    skills = await _load_skills(data, settings)
    return AgentPlatformCapabilities(
        asset_version=str(data.get("asset_version") or _fallback_asset_version()),
        app_code=settings.app_code,
        scene=settings.scene,
        raw_config=data,
        mcp_servers=mcp_servers,
        allowed_tools=allowed_tools,
        system_prompt=str(data.get("system_prompt") or ""),
        skill_prompts=[skill for skill in skills if skill.status == "loaded"],
        loaded_mcp_servers=loaded_mcp_servers,
        errors=[skill.error_message for skill in skills if skill.error_message],
    )


def _extract_mcp_servers(data: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """提取平台原始 MCP 配置，保留工具元数据供调试展示使用。"""
    direct = data.get("mcp_servers")
    if isinstance(direct, dict):
        return {
            str(name): dict(config)
            for name, config in direct.items()
            if isinstance(config, dict)
        }

    mcp = data.get("mcp")
    mcp_servers = mcp.get("mcpServers") if isinstance(mcp, dict) else None
    if not isinstance(mcp_servers, dict):
        return {}
    return {
        str(name): dict(config)
        for name, config in mcp_servers.items()
        if isinstance(config, dict)
    }


def _normalize_mcp_servers(
    raw_mcp_servers: dict[str, dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """生成 Claude SDK 可接收的 MCP 运行配置。"""
    return {
        name: _normalize_single_mcp_config(config)
        for name, config in raw_mcp_servers.items()
    }


def _normalize_single_mcp_config(config: dict[str, Any]) -> dict[str, Any]:
    """转换单个 MCP Server 配置为 Claude SDK 可接收的结构。"""
    normalized = dict(config)
    transport = normalized.pop("transport", None)
    if transport and "type" not in normalized:
        normalized["type"] = transport
    if normalized.get("type") == "streamable_http":
        normalized["type"] = "http"
    if "command" in normalized and "type" not in normalized:
        normalized["type"] = "stdio"
    return _strip_mcp_runtime_metadata(normalized)


def _strip_mcp_runtime_metadata(config: dict[str, Any]) -> dict[str, Any]:
    """移除平台展示字段，避免 Claude SDK 收到非运行配置。"""
    kind = str(config.get("type") or "")
    allowed_keys_by_type = {
        "stdio": {"type", "command", "args", "env"},
        "http": {"type", "url", "headers"},
        "sse": {"type", "url", "headers"},
        "sdk": {"type", "name", "instance"},
    }
    allowed_keys = allowed_keys_by_type.get(kind)
    if allowed_keys is None:
        return {key: value for key, value in config.items() if key != "tools"}
    return {key: value for key, value in config.items() if key in allowed_keys}


def _normalize_mcp_transport_for_display(config: dict[str, Any]) -> dict[str, Any]:
    """归一化展示配置中的 transport/type，保持调试接口与运行配置一致。"""
    normalized = dict(config)
    transport = normalized.pop("transport", None)
    if transport and "type" not in normalized:
        normalized["type"] = transport
    if normalized.get("type") == "streamable_http":
        normalized["type"] = "http"
    if "command" in normalized and "type" not in normalized:
        normalized["type"] = "stdio"
    return normalized


def _describe_mcp_servers(
    mcp_servers: dict[str, dict[str, Any]],
) -> list[AgentMcpServer]:
    """生成调试接口可展示的 MCP Server/Tool 摘要。"""
    servers: list[AgentMcpServer] = []
    for name, config in mcp_servers.items():
        normalized = _normalize_mcp_transport_for_display(config)
        tools = _normalize_mcp_tools(name, normalized)
        servers.append(AgentMcpServer(name=name, status="connected", tools=tools))
    return servers


def _normalize_mcp_tools(name: str, config: dict[str, Any]) -> list[AgentMcpTool]:
    """从平台配置中提取工具描述；mock-tool 默认暴露 echo。"""
    raw_tools = config.get("tools")
    if isinstance(raw_tools, list):
        tools = []
        for item in raw_tools:
            if not isinstance(item, dict):
                continue
            tool_name = str(item.get("name") or "").strip()
            if not tool_name:
                continue
            tools.append(
                AgentMcpTool(
                    server_name=name,
                    name=tool_name,
                    full_name=f"{name}.{tool_name}",
                    description=str(item.get("description") or ""),
                    input_schema=item.get("input_schema") if isinstance(item.get("input_schema"), dict) else {},
                )
            )
        return tools

    if name == "mock-tool":
        return [
            AgentMcpTool(
                server_name=name,
                name="echo",
                full_name="mock-tool.echo",
                description="返回输入内容",
                input_schema={
                    "type": "object",
                    "properties": {"text": {"type": "string"}},
                    "required": ["text"],
                },
            )
        ]
    return []


def _normalize_allowed_tools(
    data: dict[str, Any],
    loaded_mcp_servers: list[AgentMcpServer],
) -> list[str]:
    """归一化 Claude SDK allowed_tools。"""
    raw = data.get("allowed_tools")
    if isinstance(raw, list):
        return [str(item) for item in raw if str(item).strip()]

    allowed: list[str] = []
    for server in loaded_mcp_servers:
        for tool in server.tools:
            allowed.append(f"mcp__{server.name}__{tool.name}")
    return allowed


async def _load_skills(
    data: dict[str, Any],
    settings: AgentPlatformSettings,
) -> list[AgentSkillPrompt]:
    """下载并解析平台 Skill。"""
    raw_skills = data.get("skills") or []
    if not isinstance(raw_skills, list):
        return []

    loaded: list[AgentSkillPrompt] = []
    for raw in raw_skills[: settings.max_skills]:
        if not isinstance(raw, dict) or raw.get("enabled", True) is False:
            continue
        try:
            loaded.append(await _load_single_skill(raw, settings))
        except Exception as exc:
            name = str(raw.get("name") or raw.get("id") or "unknown")
            message = f"Skill 加载失败: {name}: {exc}"
            logger.warning(message)
            loaded.append(
                AgentSkillPrompt(
                    id=str(raw.get("id") or ""),
                    name=name,
                    version=str(raw.get("version") or "1.0.0"),
                    description=str(raw.get("description") or ""),
                    content="",
                    source_url=str(raw.get("file_url") or ""),
                    status="failed",
                    error_message=message,
                )
            )
    return loaded


async def _load_single_skill(
    raw: dict[str, Any],
    settings: AgentPlatformSettings,
) -> AgentSkillPrompt:
    """加载单个 Skill 配置。"""
    prompt = raw.get("prompt")
    source_url = str(raw.get("file_url") or "")
    markdown = str(prompt) if prompt is not None else await _download_skill_markdown(source_url, settings)
    if len(markdown.encode("utf-8")) > settings.max_skill_size_bytes:
        raise ValueError("Skill 文件超过大小限制")

    parsed = parse_skill_markdown(markdown)
    content = parsed["content"].strip()
    if not content:
        raise ValueError("Skill Markdown 正文为空")

    meta = parsed["metadata"]
    return AgentSkillPrompt(
        id=str(raw.get("id") or meta.get("id") or ""),
        name=str(raw.get("name") or meta.get("name") or "unnamed-skill"),
        version=str(raw.get("version") or meta.get("version") or "1.0.0"),
        description=str(raw.get("description") or meta.get("description") or ""),
        content=content,
        source_url=source_url,
        metadata={key: value for key, value in meta.items() if key not in {"id", "name", "version", "description"}},
    )


async def _download_skill_markdown(
    file_url: str,
    settings: AgentPlatformSettings,
) -> str:
    """下载或读取 Skill Markdown。"""
    if not file_url.strip():
        raise ValueError("Skill file_url 为空")

    parsed = urlparse(file_url)
    if parsed.scheme in {"http", "https"}:
        response = await http_client.get(file_url, timeout=settings.timeout)
        return response.text

    return _read_local_skill_file(file_url)


def _read_local_skill_file(file_url: str) -> str:
    """读取本地 mock Skill 文件。"""
    name = Path(file_url).name
    if not name.endswith(".md"):
        raise ValueError("Skill 文件必须是 .md")
    path = _repo_root() / "app" / "mock_platform" / "skills" / name
    return path.read_text("utf-8")


def parse_skill_markdown(markdown: str) -> dict[str, Any]:
    """解析 Skill Markdown，YAML 错误不阻断正文使用。"""
    match = FRONTMATTER_RE.match(markdown)
    if not match:
        return {"metadata": {}, "content": markdown.strip()}

    raw_meta, body = match.group(1), match.group(2)
    try:
        metadata = yaml.safe_load(raw_meta) or {}
    except yaml.YAMLError:
        metadata = {}
    if not isinstance(metadata, dict):
        metadata = {}
    return {"metadata": metadata, "content": body.strip()}


def _fallback_asset_version() -> str:
    """生成缺省资产版本号。"""
    return f"generated-{datetime.now(UTC):%Y%m%d%H%M%S}"


def _repo_root() -> Path:
    """定位项目根目录。"""
    here = Path(__file__).resolve()
    for anc in (here, *here.parents):
        if (anc / ".git").exists() or (anc / "requirements.txt").exists():
            return anc
    return here.parents[2]

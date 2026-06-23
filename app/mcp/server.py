"""独立 Streamable HTTP MCP Server 入口。"""

import ipaddress

from mcp.server.fastmcp import FastMCP

from app.core.config import get_settings
from app.core.settings import McpServerSettings
from app.exceptions import BizException, MCP_ERRNO_CONFIG_INVALID
from app.mcp.tools import calculate


def _is_loopback(host: str) -> bool:
    """判断监听地址是否仅限本机。"""
    if host == "localhost":
        return True
    try:
        return ipaddress.ip_address(host).is_loopback
    except ValueError:
        return False


def create_mcp_server(settings: McpServerSettings) -> FastMCP:
    """创建独立 MCP Server，并执行运行环境安全校验。"""
    if not _is_loopback(settings.host):
        raise BizException(
            "未启用认证的 MCP Server 只能监听 loopback 地址",
            errno=MCP_ERRNO_CONFIG_INVALID,
        )

    server = FastMCP(
        name=settings.name,
        instructions="arch-fastapi MCP 能力服务",
        host=settings.host,
        port=settings.port,
        streamable_http_path=settings.path,
        stateless_http=settings.stateless_http,
        json_response=settings.json_response,
    )
    server.tool(description="执行受限的四则运算并返回结构化结果")(calculate)
    return server


def run() -> None:
    """按项目配置启动独立 Streamable HTTP MCP Server。"""
    settings = get_settings()
    if not settings.mcp.server.enabled:
        raise BizException("MCP Server 已禁用", errno=MCP_ERRNO_CONFIG_INVALID)

    server = create_mcp_server(settings.mcp.server)
    server.run(transport="streamable-http")


if __name__ == "__main__":
    run()

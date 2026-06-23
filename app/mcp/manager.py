"""进程级 MCP Client Manager。"""

from app.core.logger import logger
from app.core.settings import McpClientSettings
from app.exceptions import (
    BizException,
    MCP_ERRNO_NOT_INITIALIZED,
    MCP_ERRNO_SERVER_NOT_FOUND,
)
from app.mcp.client import McpClient

clients: dict[str, McpClient] = {}
default_server: str | None = None
initialized = False


def init_mcp_clients(settings: McpClientSettings, *, environment: str) -> None:
    """仅解析并注册 Client，不在应用启动期访问远端网络。"""
    global clients, default_server, initialized

    clients = {}
    default_server = settings.default_server
    initialized = settings.enabled
    if not settings.enabled:
        logger.info("MCP Client Manager 已禁用")
        return

    for name, remote in settings.servers.items():
        if not remote.enabled:
            continue
        if environment == "prod" and not remote.url.startswith("https://"):
            logger.warning("跳过不安全的生产 MCP Server 配置 | server={}", name)
            continue
        clients[name] = McpClient(name, remote, settings)

    logger.info("MCP Client Manager 初始化完成 | servers={}", len(clients))


def get_mcp_client(name: str | None = None) -> McpClient:
    """按名称获取 Client；未指定时返回默认 Server。"""
    if not initialized:
        raise BizException("MCP Client Manager 未初始化", errno=MCP_ERRNO_NOT_INITIALIZED)
    resolved_name = name or default_server
    if not resolved_name or resolved_name not in clients:
        raise BizException(
            f"MCP Server 不存在或未启用: {resolved_name or '-'}",
            errno=MCP_ERRNO_SERVER_NOT_FOUND,
        )
    return clients[resolved_name]


async def close_mcp_clients() -> None:
    """幂等关闭全部 Client，并清理进程级状态。"""
    global clients, default_server, initialized

    for client in clients.values():
        await client.close()
    clients = {}
    default_server = None
    initialized = False

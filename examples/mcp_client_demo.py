"""独立 Streamable HTTP MCP Server 调用示例。

先运行：
    conda run -n claude-sdk python -m app.mcp.server

再运行本文件：
    conda run -n claude-sdk python -m examples.mcp_client_demo
"""

import asyncio
import json

from app.core.config import get_settings
from app.mcp.client import McpClient


async def main() -> None:
    """发现 calculate 工具并完成一次结构化调用。"""
    settings = get_settings().mcp.client
    remote = settings.servers[settings.default_server]
    client = McpClient(settings.default_server, remote, settings)

    tools = await client.list_tools()
    print("可用工具:", [tool.name for tool in tools])

    result = await client.call_tool(
        "calculate",
        {"a": 12, "b": 3, "operator": "divide"},
    )
    print("调用结果:", json.dumps(result.structuredContent, ensure_ascii=False))


if __name__ == "__main__":
    asyncio.run(main())

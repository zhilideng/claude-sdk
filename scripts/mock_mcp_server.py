"""Mock MCP Server：用于验证平台下发 MCP 配置的最小 echo 工具。"""

from mcp.server.fastmcp import FastMCP


server = FastMCP(name="mock-tool", instructions="mock 平台 MCP 工具")


@server.tool(description="返回输入内容")
def echo(text: str) -> str:
    """返回调用方传入的文本。"""
    return text


if __name__ == "__main__":
    server.run(transport="stdio")

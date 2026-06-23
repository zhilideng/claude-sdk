"""配置驱动的 Streamable HTTP MCP Client。"""

from collections.abc import AsyncIterator, Awaitable, Callable
from contextlib import asynccontextmanager
from datetime import timedelta
import time
from typing import TypeVar

import anyio
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from mcp.types import CallToolResult, Tool

from app.core.logger import logger
from app.core.settings import McpClientSettings, McpRemoteServerSettings
from app.exceptions import (
    BizException,
    MCP_ERRNO_CALL_FAILED,
    MCP_ERRNO_CONNECT_FAILED,
)

ResultT = TypeVar("ResultT")


class McpClient:
    """访问单个静态配置 MCP Server 的异步客户端。"""

    def __init__(
        self,
        name: str,
        remote: McpRemoteServerSettings,
        settings: McpClientSettings,
    ) -> None:
        self.name = name
        self.remote = remote
        self.settings = settings
        self.semaphore = anyio.Semaphore(settings.max_concurrency)

    @asynccontextmanager
    async def open_session(self) -> AsyncIterator[ClientSession]:
        """建立并初始化一次短生命周期协议会话。"""
        initialized = False
        try:
            timeout = httpx.Timeout(
                self.settings.call_timeout,
                connect=self.settings.connect_timeout,
            )
            async with httpx.AsyncClient(timeout=timeout) as http_client:
                async with streamable_http_client(
                    self.remote.url,
                    http_client=http_client,
                ) as (read_stream, write_stream, _):
                    async with ClientSession(
                        read_stream,
                        write_stream,
                        read_timeout_seconds=timedelta(seconds=self.settings.call_timeout),
                    ) as session:
                        await session.initialize()
                        initialized = True
                        yield session
        except BizException:
            raise
        except Exception as exc:
            # yield 之后的异常来自具体协议操作，交由 execute 归类为调用失败；
            # 初始化完成前的异常才属于连接或握手失败。
            if initialized:
                raise
            raise BizException(
                f"MCP Server {self.name} 连接失败",
                errno=MCP_ERRNO_CONNECT_FAILED,
            ) from exc

    async def execute(
        self,
        action: str,
        operation: Callable[[ClientSession], Awaitable[ResultT]],
    ) -> ResultT:
        """在并发与超时边界内执行一次协议操作。"""
        started = time.perf_counter()
        try:
            async with self.semaphore:
                async with self.open_session() as session:
                    result = await operation(session)
        except BizException:
            raise
        except Exception as exc:
            logger.warning("MCP 调用失败 | server={} | action={}", self.name, action)
            raise BizException(
                f"MCP Server {self.name} 调用失败",
                errno=MCP_ERRNO_CALL_FAILED,
            ) from exc

        duration_ms = (time.perf_counter() - started) * 1000
        logger.info(
            "MCP 调用完成 | server={} | action={} | duration_ms={:.1f}",
            self.name,
            action,
            duration_ms,
        )
        return result

    async def list_tools(self) -> list[Tool]:
        """发现 Server 对外暴露的工具。"""
        result = await self.execute("tools/list", lambda session: session.list_tools())
        return result.tools

    async def call_tool(
        self,
        name: str,
        arguments: dict[str, object] | None = None,
    ) -> CallToolResult:
        """调用工具；为避免重复副作用，本方法不自动重试。"""

        async def invoke(session: ClientSession) -> CallToolResult:
            return await session.call_tool(name, arguments or {})

        return await self.execute(f"tools/call:{name}", invoke)

    async def ping(self) -> None:
        """显式检查 Server 协议连通性。"""
        await self.execute("ping", lambda session: session.send_ping())

    async def close(self) -> None:
        """保留统一生命周期接口；短会话模式无常驻资源。"""

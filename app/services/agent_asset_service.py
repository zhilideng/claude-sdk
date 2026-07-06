"""Agent 资产快照服务。"""
from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field

from app.core.settings import AgentPlatformSettings
from app.services.agent_platform_service import (
    AgentPlatformCapabilities,
    load_agent_platform_capabilities,
)


class AgentAssetSkillOut(BaseModel):
    """调试接口返回的 Skill 摘要。"""

    id: str
    name: str
    version: str
    status: str
    description: str = ""
    error_message: str | None = None


class AgentAssetToolOut(BaseModel):
    """调试接口返回的 MCP 工具摘要。"""

    name: str
    full_name: str
    description: str = ""


class AgentAssetMcpServerOut(BaseModel):
    """调试接口返回的 MCP Server 摘要。"""

    name: str
    status: str
    tools: list[AgentAssetToolOut] = Field(default_factory=list)
    error_message: str | None = None


class AgentAssetSnapshotOut(BaseModel):
    """调试接口返回的会话资产快照。"""

    session_id: int
    asset_snapshot_id: str
    asset_version: str
    app_code: str
    scene: str
    mcp_servers: list[AgentAssetMcpServerOut] = Field(default_factory=list)
    skills: list[AgentAssetSkillOut] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    created_at: str


class AgentAssetSnapshot(BaseModel):
    """进程内资产快照。"""

    session_id: int
    asset_snapshot_id: str
    capabilities: AgentPlatformCapabilities
    created_at: datetime

    def to_out(self) -> AgentAssetSnapshotOut:
        """转换为接口响应模型。"""
        return AgentAssetSnapshotOut(
            session_id=self.session_id,
            asset_snapshot_id=self.asset_snapshot_id,
            asset_version=self.capabilities.asset_version,
            app_code=self.capabilities.app_code,
            scene=self.capabilities.scene,
            mcp_servers=[
                AgentAssetMcpServerOut(
                    name=server.name,
                    status=server.status,
                    tools=[
                        AgentAssetToolOut(
                            name=tool.name,
                            full_name=tool.full_name,
                            description=tool.description,
                        )
                        for tool in server.tools
                    ],
                    error_message=server.error_message,
                )
                for server in self.capabilities.loaded_mcp_servers
            ],
            skills=[
                AgentAssetSkillOut(
                    id=skill.id,
                    name=skill.name,
                    version=skill.version,
                    status=skill.status,
                    description=skill.description,
                    error_message=skill.error_message,
                )
                for skill in self.capabilities.skill_prompts
            ],
            errors=self.capabilities.errors,
            created_at=self.created_at.isoformat(),
        )


_session_asset_snapshots: dict[int, AgentAssetSnapshot] = {}


async def create_session_asset_snapshot(
    session_id: int,
    settings: AgentPlatformSettings,
) -> AgentAssetSnapshot:
    """为新会话创建并绑定平台资产快照。"""
    capabilities = await load_agent_platform_capabilities(settings)
    snapshot = AgentAssetSnapshot(
        session_id=session_id,
        asset_snapshot_id=f"asset_{datetime.now(UTC):%Y%m%d%H%M%S}_{uuid4().hex[:8]}",
        capabilities=capabilities,
        created_at=datetime.now(UTC),
    )
    _session_asset_snapshots[session_id] = snapshot
    return snapshot


async def get_or_create_session_asset_snapshot(
    session_id: int,
    settings: AgentPlatformSettings,
) -> AgentAssetSnapshot:
    """查询会话快照，不存在时为历史会话补建。"""
    snapshot = _session_asset_snapshots.get(session_id)
    if snapshot is not None:
        return snapshot
    return await create_session_asset_snapshot(session_id, settings)


def get_session_asset_snapshot(session_id: int) -> AgentAssetSnapshot | None:
    """按会话 id 查询进程内资产快照。"""
    return _session_asset_snapshots.get(session_id)


def reset_session_asset_snapshots() -> None:
    """清空进程内快照，供测试使用。"""
    _session_asset_snapshots.clear()

import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.settings import ClaudeAgentSettings, ProjectSettings
from app.exceptions import BizAuthError, BizNotFoundError, BizValidationError
from app.repositories.dao import (
    ProjectRepository,
    ProjectSessionRepository,
    SessionMessageRepository,
    UserRepository,
)
from app.repositories.models import Project, ProjectSession, SessionMessage
from app.schemas.project import (
    ProjectImportData,
    ProjectImportIn,
    ProjectListData,
    ProjectOut,
    ProjectScanData,
    ProjectSessionCreateIn,
    ProjectSessionOut,
    SessionMessageCreateData,
    SessionMessageCreateIn,
    SessionMessageListData,
    SessionMessageOut,
)
from app.services.claude_code_service import ClaudeCodeService
from app.utils.path_guard import ensure_allowed_root, resolve_project_path


class ProjectService:
    """项目业务服务。"""

    def __init__(self, session: AsyncSession, settings: ProjectSettings) -> None:
        self._project_repo = ProjectRepository(session)
        self._session_repo = ProjectSessionRepository(session)
        self._message_repo = SessionMessageRepository(session)
        self._user_repo = UserRepository(session)
        self._settings = settings

    async def list_projects(self, user_id: int) -> ProjectListData:
        """查询用户项目列表。"""
        await self._ensure_user(user_id)
        projects = await self._project_repo.list_by_user(user_id)
        return ProjectListData(items=[self._to_project_out(project) for project in projects])

    async def import_local_path(self, payload: ProjectImportIn) -> ProjectImportData:
        """导入浏览器选择的本地目录，并创建默认会话。"""
        await self._ensure_user(payload.user_id)
        project_name = payload.directory_name.strip()

        try:
            project = await self._project_repo.create_project(
                user_id=payload.user_id,
                name=project_name,
                root_path=None,
                source_type="browser_directory",
            )
            default_session = await self._session_repo.create_session(
                project_id=project.id,
                title=f"导入 {project_name}",
            )
            await self._project_repo.commit()
            reloaded = await self._project_repo.get_by_id(project.id)
            return ProjectImportData(
                project=self._to_project_out(reloaded or project),
                default_session=ProjectSessionOut.model_validate(default_session),
            )
        except Exception:
            await self._project_repo.rollback()
            raise

    async def scan_project(self, project_id: int, user_id: int) -> ProjectScanData:
        """返回项目路径摘要。

        Web 目录选择不暴露绝对路径，因此这里不扫描文件列表；真实文件读取应在
        具体会话需求里由 Claude Code SDK / 命令行工具按需完成。
        """
        project = await self._get_owned_project(project_id, user_id)
        return ProjectScanData(
            root_path=project.root_path,
            display_path=self._display_path(project.root_path),
            is_git_repo=project.is_git_repo,
        )

    async def create_session(
        self,
        project_id: int,
        payload: ProjectSessionCreateIn,
    ) -> ProjectSessionOut:
        """创建项目会话。"""
        await self._get_owned_project(project_id, payload.user_id)
        session = await self._session_repo.create_session(
            project_id=project_id,
            title=payload.title.strip(),
        )
        await self._session_repo.commit()
        return ProjectSessionOut.model_validate(session)

    async def list_sessions(self, project_id: int, user_id: int) -> list[ProjectSessionOut]:
        """查询项目下会话列表。"""
        await self._get_owned_project(project_id, user_id)
        sessions = await self._session_repo.list_by_project(project_id)
        return [ProjectSessionOut.model_validate(item) for item in sessions]

    async def _ensure_user(self, user_id: int) -> None:
        """确认用户存在。"""
        user = await self._user_repo.get_by_id(user_id)
        if user is None:
            raise BizAuthError("当前用户不存在")

    async def _get_owned_project(self, project_id: int, user_id: int) -> Project:
        """查询并校验项目归属。"""
        await self._ensure_user(user_id)
        project = await self._project_repo.get_by_id(project_id)
        if project is None:
            raise BizNotFoundError("项目不存在")
        if project.user_id != user_id:
            raise BizAuthError("无权访问该项目")
        return project

    def _to_project_out(self, project: Project) -> ProjectOut:
        """ORM 项目转接口模型。"""
        return ProjectOut(
            id=project.id,
            user_id=project.user_id,
            name=project.name,
            root_path=project.root_path,
            display_path=self._display_path(project.root_path),
            source_type=project.source_type,
            is_git_repo=project.is_git_repo,
            sessions=[
                ProjectSessionOut.model_validate(item)
                for item in sorted(project.sessions, key=lambda value: value.id, reverse=True)
            ],
            created_at=project.created_at,
            updated_at=project.updated_at,
        )

    @staticmethod
    def _display_path(root_path: str | None) -> str | None:
        """生成适合前端显示的路径。"""
        if not root_path:
            return None
        return str(Path(root_path).expanduser())

    @staticmethod
    def _load_json_list(value: str | None) -> list:
        """从 JSON 文本恢复列表。"""
        if not value:
            return []
        loaded = json.loads(value)
        return loaded if isinstance(loaded, list) else []


class SessionService:
    """会话消息业务服务。"""

    def __init__(
        self,
        session: AsyncSession,
        settings: ProjectSettings,
        claude_agent_settings: ClaudeAgentSettings | None = None,
    ) -> None:
        self._session_repo = ProjectSessionRepository(session)
        self._message_repo = SessionMessageRepository(session)
        self._user_repo = UserRepository(session)
        self._settings = settings
        self._claude_code = ClaudeCodeService(claude_agent_settings)

    async def list_messages(self, session_id: int, user_id: int) -> SessionMessageListData:
        """查询会话消息列表。"""
        await self._get_owned_session(session_id, user_id)
        messages = await self._message_repo.list_by_session(session_id)
        return SessionMessageListData(items=[self._to_message_out(item) for item in messages])

    async def send_message(
        self,
        session_id: int,
        payload: SessionMessageCreateIn,
    ) -> SessionMessageCreateData:
        """发送用户消息并调用 Claude Code SDK。"""
        session = await self._get_owned_session(session_id, payload.user_id)
        if session.status == "running":
            raise BizValidationError("会话正在运行")

        project_root_path = session.project.root_path
        user_message = await self._message_repo.create_message(
            session_id=session_id,
            role="user",
            content=payload.content.strip(),
        )
        await self._session_repo.set_status(session, "running", last_message=payload.content.strip())
        await self._session_repo.commit()

        history = await self._message_repo.list_by_session(session_id)
        history_out = [self._to_message_out(item) for item in history]
        try:
            result = await self._claude_code.run_session(
                cwd=project_root_path,
                prompt=payload.content.strip(),
                session_history=history_out,
            )
            assistant_message = await self._message_repo.create_message(
                session_id=session_id,
                role="assistant",
                content=result.content,
                status="done",
                tool_summary=json.dumps(result.tool_summary, ensure_ascii=False),
                diff_summary=json.dumps(result.diff_summary, ensure_ascii=False),
            )
            await self._session_repo.set_status(session, "idle", last_message=result.content)
            await self._session_repo.commit()
            return SessionMessageCreateData(
                message=self._to_message_out(assistant_message),
                session=ProjectSessionOut.model_validate(session),
            )
        except Exception:
            failed_message = await self._message_repo.create_message(
                session_id=session_id,
                role="assistant",
                content="Claude Code SDK 调用失败",
                status="failed",
            )
            await self._session_repo.set_status(session, "failed", last_message=failed_message.content)
            await self._session_repo.commit()
            raise

    async def stream_message(
        self,
        session_id: int,
        payload: SessionMessageCreateIn,
    ) -> AsyncIterator[dict]:
        """发送用户消息，并以 SSE 事件流式返回 Claude Agent SDK 推理过程。"""
        sequence = 0
        prompt = payload.content.strip()
        session = await self._get_owned_session(session_id, payload.user_id)
        if session.status == "running":
            yield self._to_stream_event(
                sequence=sequence,
                event_type="agent_error",
                session_id=session_id,
                message_id=None,
                data={"message": "会话正在运行"},
            )
            return

        project_root_path = session.project.root_path
        user_message = await self._message_repo.create_message(
            session_id=session_id,
            role="user",
            content=prompt,
        )
        await self._session_repo.set_status(session, "running", last_message=prompt)
        await self._session_repo.commit()

        yield self._to_stream_event(
            sequence=sequence,
            event_type="user_message_saved",
            session_id=session_id,
            message_id=user_message.id,
            data={"message": self._to_message_out(user_message).model_dump(mode="json")},
        )
        sequence += 1
        yield self._to_stream_event(
            sequence=sequence,
            event_type="agent_started",
            session_id=session_id,
            message_id=None,
            data={"cwd": project_root_path},
        )
        sequence += 1

        content_parts: list[str] = []
        tool_summary: list[dict] = []
        diff_summary: list[dict] = []

        history = await self._message_repo.list_by_session(session_id)
        history_out = [self._to_message_out(item) for item in history]
        try:
            async for sdk_event in self._claude_code.stream_session(
                cwd=project_root_path,
                prompt=prompt,
                session_history=history_out,
            ):
                if sdk_event.type == "assistant_delta":
                    content_parts.append(str(sdk_event.data.get("content", "")))
                elif sdk_event.type in {"tool_start", "tool_delta", "tool_done"}:
                    tool_summary.append({"type": sdk_event.type, **sdk_event.data})
                elif sdk_event.type == "sdk_result":
                    diff_summary.append(sdk_event.data)

                yield self._to_stream_event(
                    sequence=sequence,
                    event_type=sdk_event.type,
                    session_id=session_id,
                    message_id=None,
                    data=sdk_event.data,
                )
                sequence += 1

            assistant_content = (
                "".join(content_parts).strip() or "Claude Agent SDK 执行完成，但没有返回文本内容。"
            )
            assistant_message = await self._message_repo.create_message(
                session_id=session_id,
                role="assistant",
                content=assistant_content,
                status="done",
                tool_summary=json.dumps(tool_summary, ensure_ascii=False),
                diff_summary=json.dumps(diff_summary, ensure_ascii=False),
            )
            await self._session_repo.set_status(session, "idle", last_message=assistant_content)
            await self._session_repo.commit()

            yield self._to_stream_event(
                sequence=sequence,
                event_type="assistant_message_saved",
                session_id=session_id,
                message_id=assistant_message.id,
                data={"message": self._to_message_out(assistant_message).model_dump(mode="json")},
            )
            sequence += 1
            yield self._to_stream_event(
                sequence=sequence,
                event_type="agent_done",
                session_id=session_id,
                message_id=assistant_message.id,
                data={"status": "done"},
            )
        except Exception as exc:
            failed_content = "Claude Agent SDK 调用失败，请检查 SDK 依赖、密钥与网络配置"
            failed_message = await self._message_repo.create_message(
                session_id=session_id,
                role="assistant",
                content=failed_content,
                status="failed",
                tool_summary=json.dumps(tool_summary, ensure_ascii=False),
                diff_summary=json.dumps(diff_summary, ensure_ascii=False),
            )
            await self._session_repo.set_status(session, "failed", last_message=failed_content)
            await self._session_repo.commit()
            yield self._to_stream_event(
                sequence=sequence,
                event_type="agent_error",
                session_id=session_id,
                message_id=failed_message.id,
                data={
                    "message": failed_content,
                    "detail": exc.__class__.__name__,
                    "message_record": self._to_message_out(failed_message).model_dump(mode="json"),
                },
            )

    async def _get_owned_session(self, session_id: int, user_id: int) -> ProjectSession:
        """查询并校验会话归属。"""
        user = await self._user_repo.get_by_id(user_id)
        if user is None:
            raise BizAuthError("当前用户不存在")
        session = await self._session_repo.get_by_id(session_id)
        if session is None:
            raise BizNotFoundError("会话不存在")
        if session.project.user_id != user_id:
            raise BizAuthError("无权访问该会话")

        if session.project.root_path:
            path = resolve_project_path(session.project.root_path)
            ensure_allowed_root(path, self._settings.allowed_roots)
        return session

    def _to_message_out(self, message: SessionMessage) -> SessionMessageOut:
        """ORM 消息转接口模型。"""
        return SessionMessageOut(
            id=message.id,
            session_id=message.session_id,
            role=message.role,
            content=message.content,
            status=message.status,
            tool_summary=ProjectService._load_json_list(message.tool_summary),
            diff_summary=ProjectService._load_json_list(message.diff_summary),
            created_at=message.created_at,
        )

    @staticmethod
    def _to_stream_event(
        *,
        sequence: int,
        event_type: str,
        session_id: int,
        message_id: int | None,
        data: dict,
    ) -> dict:
        """生成 SSE 事件载荷。"""
        return {
            "type": event_type,
            "sequence": sequence,
            "session_id": session_id,
            "message_id": message_id,
            "data": data,
            "created_at": datetime.now(UTC).isoformat(),
        }

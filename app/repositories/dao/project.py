"""项目与会话数据访问层。"""
from typing import Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.exceptions import DB_ERRNO_QUERY_FAILED, BizException
from app.repositories.models import Project, ProjectSession, SessionMessage


class ProjectRepository:
    """project 表数据访问对象。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_by_user(self, user_id: int) -> list[Project]:
        """查询用户下的项目，并预加载会话列表。"""
        try:
            result = await self._session.execute(
                select(Project)
                .options(selectinload(Project.sessions))
                .where(Project.user_id == user_id)
                .order_by(Project.updated_at.desc(), Project.id.desc())
            )
            return list(result.scalars().unique().all())
        except SQLAlchemyError as exc:
            logger.error("project 查询失败 | user_id={} | err={}", user_id, exc)
            raise BizException(message="项目列表查询失败", errno=DB_ERRNO_QUERY_FAILED) from exc

    async def get_by_id(self, project_id: int) -> Optional[Project]:
        """按 id 查询项目，并预加载会话列表。"""
        try:
            result = await self._session.execute(
                select(Project)
                .options(selectinload(Project.sessions))
                .where(Project.id == project_id)
            )
            return result.scalar_one_or_none()
        except SQLAlchemyError as exc:
            logger.error("project 查询失败 | id={} | err={}", project_id, exc)
            raise BizException(message="项目查询失败", errno=DB_ERRNO_QUERY_FAILED) from exc

    async def get_by_user_and_path(self, user_id: int, root_path: str) -> Optional[Project]:
        """按用户与归一化路径查询项目。"""
        try:
            result = await self._session.execute(
                select(Project).where(
                    Project.user_id == user_id,
                    Project.root_path == root_path,
                )
            )
            return result.scalar_one_or_none()
        except SQLAlchemyError as exc:
            logger.error("project 路径查询失败 | user_id={} | err={}", user_id, exc)
            raise BizException(message="项目查询失败", errno=DB_ERRNO_QUERY_FAILED) from exc

    async def create_project(
        self,
        *,
        user_id: int,
        name: str,
        root_path: str | None = None,
        source_type: str = "browser_directory",
        is_git_repo: bool = False,
    ) -> Project:
        """创建项目记录。"""
        try:
            project = Project(
                user_id=user_id,
                name=name,
                root_path=root_path,
                source_type=source_type,
                is_git_repo=is_git_repo,
                file_count=0,
                dir_count=0,
                file_samples="[]",
            )
            self._session.add(project)
            await self._session.flush()
            await self._session.refresh(project)
            return project
        except SQLAlchemyError as exc:
            logger.error("project 创建失败 | user_id={} | root={} | err={}", user_id, root_path, exc)
            raise BizException(message="项目创建失败", errno=DB_ERRNO_QUERY_FAILED) from exc

    async def commit(self) -> None:
        """提交当前事务。"""
        try:
            await self._session.commit()
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.error("project 事务提交失败 | err={}", exc)
            raise BizException(message="项目保存失败", errno=DB_ERRNO_QUERY_FAILED) from exc

    async def rollback(self) -> None:
        """回滚当前事务。"""
        await self._session.rollback()


class ProjectSessionRepository:
    """project_session 表数据访问对象。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_by_project(self, project_id: int) -> list[ProjectSession]:
        """查询项目下会话列表。"""
        try:
            result = await self._session.execute(
                select(ProjectSession)
                .where(ProjectSession.project_id == project_id)
                .order_by(ProjectSession.updated_at.desc(), ProjectSession.id.desc())
            )
            return list(result.scalars().all())
        except SQLAlchemyError as exc:
            logger.error("session 查询失败 | project_id={} | err={}", project_id, exc)
            raise BizException(message="会话列表查询失败", errno=DB_ERRNO_QUERY_FAILED) from exc

    async def get_by_id(self, session_id: int) -> Optional[ProjectSession]:
        """按 id 查询会话。"""
        try:
            result = await self._session.execute(
                select(ProjectSession)
                .options(selectinload(ProjectSession.project))
                .where(ProjectSession.id == session_id)
            )
            return result.scalar_one_or_none()
        except SQLAlchemyError as exc:
            logger.error("session 查询失败 | id={} | err={}", session_id, exc)
            raise BizException(message="会话查询失败", errno=DB_ERRNO_QUERY_FAILED) from exc

    async def create_session(self, *, project_id: int, title: str) -> ProjectSession:
        """创建项目会话。"""
        try:
            item = ProjectSession(project_id=project_id, title=title, status="idle")
            self._session.add(item)
            await self._session.flush()
            await self._session.refresh(item)
            return item
        except SQLAlchemyError as exc:
            logger.error("session 创建失败 | project_id={} | err={}", project_id, exc)
            raise BizException(message="会话创建失败", errno=DB_ERRNO_QUERY_FAILED) from exc

    async def set_status(
        self,
        session: ProjectSession,
        status: str,
        *,
        last_message: str | None = None,
    ) -> ProjectSession:
        """更新会话状态与最近消息。"""
        try:
            session.status = status
            if last_message is not None:
                session.last_message = last_message[:500]
            await self._session.flush()
            await self._session.refresh(session)
            return session
        except SQLAlchemyError as exc:
            logger.error("session 更新失败 | id={} | err={}", session.id, exc)
            raise BizException(message="会话更新失败", errno=DB_ERRNO_QUERY_FAILED) from exc

    async def commit(self) -> None:
        """提交当前事务。"""
        try:
            await self._session.commit()
        except SQLAlchemyError as exc:
            await self._session.rollback()
            logger.error("session 事务提交失败 | err={}", exc)
            raise BizException(message="会话保存失败", errno=DB_ERRNO_QUERY_FAILED) from exc

    async def rollback(self) -> None:
        """回滚当前事务。"""
        await self._session.rollback()


class SessionMessageRepository:
    """session_message 表数据访问对象。"""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def list_by_session(self, session_id: int) -> list[SessionMessage]:
        """查询会话消息列表。"""
        try:
            result = await self._session.execute(
                select(SessionMessage)
                .where(SessionMessage.session_id == session_id)
                .order_by(SessionMessage.id.asc())
            )
            return list(result.scalars().all())
        except SQLAlchemyError as exc:
            logger.error("message 查询失败 | session_id={} | err={}", session_id, exc)
            raise BizException(message="消息列表查询失败", errno=DB_ERRNO_QUERY_FAILED) from exc

    async def create_message(
        self,
        *,
        session_id: int,
        role: str,
        content: str,
        status: str = "done",
        tool_summary: str = "[]",
        diff_summary: str = "[]",
    ) -> SessionMessage:
        """创建会话消息。"""
        try:
            item = SessionMessage(
                session_id=session_id,
                role=role,
                content=content,
                status=status,
                tool_summary=tool_summary,
                diff_summary=diff_summary,
            )
            self._session.add(item)
            await self._session.flush()
            await self._session.refresh(item)
            return item
        except SQLAlchemyError as exc:
            logger.error("message 创建失败 | session_id={} | err={}", session_id, exc)
            raise BizException(message="消息保存失败", errno=DB_ERRNO_QUERY_FAILED) from exc

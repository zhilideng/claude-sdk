"""project 表 ORM 模型。"""
from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.repositories.base import Base


class Project(Base):
    """本地项目 ORM 模型。

    Web 选择文件夹时浏览器不会暴露绝对路径，因此 ``root_path`` 只作为未来
    桌面壳或后端桥接目录选择后的可选字段；不在项目表保存文件清单。
    """

    __tablename__ = "project"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    user_id: Mapped[int] = mapped_column(Integer, ForeignKey("user.id"), nullable=False)
    name: Mapped[str] = mapped_column(String(255), nullable=False)
    root_path: Mapped[str | None] = mapped_column(String(2048), nullable=True)
    source_type: Mapped[str] = mapped_column(String(32), nullable=False, default="browser_directory")
    is_git_repo: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    file_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    dir_count: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    file_samples: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    sessions: Mapped[list["ProjectSession"]] = relationship(
        back_populates="project",
        cascade="all, delete-orphan",
    )


class ProjectSession(Base):
    """项目下的会话 ORM 模型。"""

    __tablename__ = "project_session"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    project_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("project.id", ondelete="CASCADE"),
        nullable=False,
    )
    title: Mapped[str] = mapped_column(String(255), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="idle")
    last_message: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())
    updated_at: Mapped[object] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
    )

    project: Mapped[Project] = relationship(back_populates="sessions")
    messages: Mapped[list["SessionMessage"]] = relationship(
        back_populates="session",
        cascade="all, delete-orphan",
    )


class SessionMessage(Base):
    """会话消息 ORM 模型。"""

    __tablename__ = "session_message"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    session_id: Mapped[int] = mapped_column(
        Integer,
        ForeignKey("project_session.id", ondelete="CASCADE"),
        nullable=False,
    )
    role: Mapped[str] = mapped_column(String(32), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="done")
    tool_summary: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    diff_summary: Mapped[str] = mapped_column(Text, nullable=False, default="[]")
    created_at: Mapped[object] = mapped_column(DateTime(timezone=True), server_default=func.now())

    session: Mapped[ProjectSession] = relationship(back_populates="messages")

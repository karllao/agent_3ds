"""
Job ORM 模型 —— 代表一次后台生成任务（与 Celery task 对应）。
"""

from __future__ import annotations

import enum
from datetime import datetime

from app.database import Base
from sqlalchemy import DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship


class JobStatus(str, enum.Enum):
    PENDING = "pending"  # 等待 Worker 拾取
    RUNNING = "running"  # 正在执行
    SUCCESS = "success"  # 执行成功
    FAILED = "failed"  # 执行失败
    REVOKED = "revoked"  # 被手动撤销


class JobStep(str, enum.Enum):
    CAD_PARSE = "cad_parse"  # 解析 CAD 文件
    SCENE_GENERATE = "scene_generate"  # AI 生成场景数据
    MAX_EXPORT = "max_export"  # 导出 3ds Max 文件
    RENDER_PREVIEW = "render_preview"  # 渲染预览图


class Job(Base):
    __tablename__ = "jobs"

    # ── 主键 ─────────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # ── 外键 ─────────────────────────────────────────────────────────────
    project_id: Mapped[int] = mapped_column(
        ForeignKey("projects.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )

    # ── Celery Task ID ────────────────────────────────────────────────────
    celery_task_id: Mapped[str | None] = mapped_column(
        String(255),
        nullable=True,
        unique=True,
        index=True,
        comment="Celery 异步任务 ID",
    )

    # ── 状态 ──────────────────────────────────────────────────────────────
    status: Mapped[JobStatus] = mapped_column(
        Enum(JobStatus, name="job_status"),
        nullable=False,
        default=JobStatus.PENDING,
        index=True,
    )
    step: Mapped[JobStep | None] = mapped_column(
        Enum(JobStep, name="job_step"),
        nullable=True,
        comment="当前或最后执行的步骤",
    )
    progress: Mapped[int] = mapped_column(
        Integer,
        nullable=False,
        default=0,
        comment="任务进度 0-100",
    )

    # ── 错误信息 ──────────────────────────────────────────────────────────
    error_message: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="失败时的错误详情",
    )

    # ── 时间戳 ────────────────────────────────────────────────────────────
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        nullable=False,
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
    )

    # ── 关联 ──────────────────────────────────────────────────────────────
    project: Mapped["Project"] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Project",
        back_populates="jobs",
    )

    def __repr__(self) -> str:
        return (
            f"<Job id={self.id} project_id={self.project_id} "
            f"step={self.step} status={self.status} progress={self.progress}%>"
        )

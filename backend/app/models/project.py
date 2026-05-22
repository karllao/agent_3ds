"""
Project ORM 模型 —— 代表一个从 CAD 到 3ds Max 的完整转换项目。
"""

from __future__ import annotations

import enum
from datetime import datetime

from app.database import Base
from sqlalchemy import DateTime, Enum, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column, relationship


class ProjectStatus(str, enum.Enum):
    CREATED = "created"  # 项目已创建，尚未上传 CAD
    CAD_UPLOADED = "cad_uploaded"  # CAD 文件已上传
    PARSING = "parsing"  # 正在解析 CAD
    PARSED = "parsed"  # CAD 解析完成
    GENERATING = "generating"  # AI 正在生成场景数据
    GENERATED = "generated"  # 场景数据生成完成
    EXPORTING = "exporting"  # 正在导出到 3ds Max
    COMPLETED = "completed"  # 全部完成
    FAILED = "failed"  # 任意步骤失败


class Project(Base):
    __tablename__ = "projects"

    # ── 主键 ─────────────────────────────────────────────────────────────
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)

    # ── 基础信息 ──────────────────────────────────────────────────────────
    name: Mapped[str] = mapped_column(String(255), nullable=False, index=True)
    status: Mapped[ProjectStatus] = mapped_column(
        Enum(ProjectStatus, name="project_status"),
        nullable=False,
        default=ProjectStatus.CREATED,
        index=True,
    )

    # ── 用户输入 ──────────────────────────────────────────────────────────
    user_description: Mapped[str | None] = mapped_column(
        Text,
        nullable=True,
        comment="用户对空间风格、用途的文字描述，用于指导 AI 生成",
    )

    # ── 文件路径 ──────────────────────────────────────────────────────────
    cad_file_path: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
        comment="上传的 CAD 文件（DWG/DXF）存储路径",
    )
    scene_json_path: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
        comment="AI 生成的场景 JSON 文件路径",
    )
    max_file_path: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
        comment="生成的 3ds Max (.max) 文件路径",
    )
    preview_image_path: Mapped[str | None] = mapped_column(
        String(1024),
        nullable=True,
        comment="场景预览图路径",
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
    jobs: Mapped[list["Job"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Job",
        back_populates="project",
        cascade="all, delete-orphan",
        lazy="selectin",
    )
    conversations: Mapped[list["Conversation"]] = relationship(  # type: ignore[name-defined]  # noqa: F821
        "Conversation",
        back_populates="project",
        cascade="all, delete-orphan",
        lazy="selectin",
    )

    def __repr__(self) -> str:
        return f"<Project id={self.id} name={self.name!r} status={self.status}>"

"""
Project 相关的 Pydantic 请求 / 响应 Schema。
"""

from __future__ import annotations

from datetime import datetime

from app.models.project import ProjectStatus
from pydantic import BaseModel, Field

# ── 请求体 ────────────────────────────────────────────────────────────────────


class ProjectCreate(BaseModel):
    """创建项目请求体"""

    name: str = Field(..., min_length=1, max_length=255, description="项目名称")
    user_description: str | None = Field(
        default=None,
        max_length=4096,
        description="用户对室内风格、功能需求的文字描述",
    )


class ProjectUpdate(BaseModel):
    """更新项目请求体（所有字段可选）"""

    name: str | None = Field(default=None, min_length=1, max_length=255)
    user_description: str | None = Field(default=None, max_length=4096)
    status: ProjectStatus | None = None


# ── 响应体 ────────────────────────────────────────────────────────────────────


class ProjectRead(BaseModel):
    """项目详情响应"""

    id: int
    name: str
    status: ProjectStatus
    user_description: str | None
    cad_file_path: str | None
    scene_json_path: str | None
    max_file_path: str | None
    preview_image_path: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectListItem(BaseModel):
    """项目列表条目（精简版）"""

    id: int
    name: str
    status: ProjectStatus
    preview_image_path: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class ProjectListResponse(BaseModel):
    """项目列表响应（带分页信息）"""

    total: int = Field(..., description="总项目数")
    page: int = Field(..., description="当前页码（从 1 开始）")
    page_size: int = Field(..., description="每页条数")
    items: list[ProjectListItem]


class ProjectStartGenerationRequest(BaseModel):
    """启动场景生成任务的请求体"""

    user_description: str | None = Field(
        default=None,
        max_length=4096,
        description="本次生成的补充描述（可覆盖项目默认描述）",
    )
    style_override: str | None = Field(
        default=None,
        description="风格覆盖：modern / nordic / chinese / industrial 等",
    )
    force_reparse: bool = Field(
        default=False,
        description="是否强制重新解析 CAD（即使已有解析结果）",
    )

"""
Job 相关的 Pydantic 请求 / 响应 Schema。
"""

from __future__ import annotations

from datetime import datetime

from app.models.job import JobStatus, JobStep
from pydantic import BaseModel, Field


class JobCreate(BaseModel):
    """创建任务（内部使用）"""

    project_id: int
    step: JobStep
    celery_task_id: str | None = None


class JobStatusUpdate(BaseModel):
    """更新任务状态（Worker 回调使用）"""

    status: JobStatus
    step: JobStep | None = None
    progress: int = Field(default=0, ge=0, le=100)
    error_message: str | None = None


class JobRead(BaseModel):
    """任务详情响应"""

    id: int
    project_id: int
    celery_task_id: str | None
    status: JobStatus
    step: JobStep | None
    progress: int
    error_message: str | None
    created_at: datetime
    updated_at: datetime

    model_config = {"from_attributes": True}


class JobListResponse(BaseModel):
    """项目关联的任务列表"""

    project_id: int
    total: int
    items: list[JobRead]

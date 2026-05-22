"""
项目管理 API（完整版）。

端点：
  GET    /api/projects                          项目列表（分页）
  POST   /api/projects                          创建项目
  GET    /api/projects/{project_id}             项目详情（含最新 Job 状态）
  DELETE /api/projects/{project_id}             删除项目

  POST   /api/projects/{project_id}/generate    触发完整生成流程
  POST   /api/projects/{project_id}/answer      用户回答 AI 追问

  GET    /api/projects/{project_id}/scene_json  返回生成的场景 JSON
  GET    /api/projects/{project_id}/download    下载 .max 文件
  GET    /api/projects/{project_id}/preview     返回预览图

  GET    /api/projects/{project_id}/jobs        项目的所有任务列表
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import FileResponse, JSONResponse
from loguru import logger
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import DbSession
from app.models.job import Job, JobStatus
from app.models.project import Project, ProjectStatus
from app.schemas.job import JobListResponse, JobRead
from app.schemas.project import (
    ProjectCreate,
    ProjectListItem,
    ProjectListResponse,
    ProjectRead,
)
from app.services.job_service import job_service
from app.services.project_service import project_service

router = APIRouter()


# ── 请求体 ────────────────────────────────────────────────────────────────────


class GenerateRequest(BaseModel):
    """触发生成任务的请求体。"""

    user_description: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        description="用户对室内风格、功能需求的文字描述",
    )


class AnswerRequest(BaseModel):
    """用户回答 AI 追问的请求体。"""

    answer: str = Field(
        ...,
        min_length=1,
        max_length=4096,
        description="用户对 AI 追问的回答文本",
    )


# ── 响应体扩展 ────────────────────────────────────────────────────────────────


class ProjectDetailResponse(ProjectRead):
    """项目详情响应（包含最新 Job 状态）。"""

    latest_job: Optional[JobRead] = None
    pending_question: Optional[str] = None


class GenerateResponse(BaseModel):
    """触发生成后的响应。"""

    job_id: int
    celery_task_id: str
    message: str = "任务已提交，请通过 job_id 轮询进度"


class AnswerResponse(BaseModel):
    """用户回答后的响应。"""

    job_id: int
    celery_task_id: str
    message: str = "已接收回答，继续生成中"


# ── 工具函数 ──────────────────────────────────────────────────────────────────


async def _get_project_or_404(project_id: int, db: AsyncSession) -> Project:
    """根据 ID 查找项目，不存在则返回 404。"""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"项目 {project_id} 不存在",
        )
    return project


async def _get_latest_job(project_id: int, db: AsyncSession) -> Optional[Job]:
    """获取项目最新 Job。"""
    return await job_service.get_latest_job(db, project_id)


def _get_redis_store():
    from app.config import get_settings
    from app.tasks.redis_state_store import RedisStateStore

    return RedisStateStore(get_settings().redis_url)


# ── GET /api/projects ─────────────────────────────────────────────────────────


@router.get(
    "",
    response_model=ProjectListResponse,
    summary="获取项目列表（分页）",
)
async def list_projects(
    db: DbSession,
    page: int = Query(default=1, ge=1, description="页码（从 1 开始）"),
    page_size: int = Query(default=20, ge=1, le=100, description="每页条数"),
    status_filter: Optional[ProjectStatus] = Query(
        default=None, alias="status", description="按状态过滤"
    ),
) -> ProjectListResponse:
    stmt = select(Project)
    count_stmt = select(func.count(Project.id))

    if status_filter is not None:
        stmt = stmt.where(Project.status == status_filter)
        count_stmt = count_stmt.where(Project.status == status_filter)

    total = (await db.execute(count_stmt)).scalar_one()

    stmt = stmt.order_by(Project.created_at.desc())
    stmt = stmt.offset((page - 1) * page_size).limit(page_size)
    projects = (await db.execute(stmt)).scalars().all()

    return ProjectListResponse(
        total=total,
        page=page,
        page_size=page_size,
        items=[ProjectListItem.model_validate(p) for p in projects],
    )


# ── POST /api/projects ────────────────────────────────────────────────────────


@router.post(
    "",
    response_model=ProjectRead,
    status_code=status.HTTP_201_CREATED,
    summary="创建项目（仅创建记录，不上传文件）",
)
async def create_project(
    payload: ProjectCreate,
    db: DbSession,
) -> ProjectRead:
    project = await project_service.create_project(
        session=db,
        name=payload.name,
        user_description=payload.user_description or "",
    )
    await db.commit()
    await db.refresh(project)
    logger.info(
        "[Projects API] Created project id={} name={!r}", project.id, project.name
    )
    return ProjectRead.model_validate(project)


# ── GET /api/projects/{project_id} ────────────────────────────────────────────


@router.get(
    "/{project_id}",
    response_model=ProjectDetailResponse,
    summary="获取项目详情（含最新 Job 状态）",
)
async def get_project(project_id: int, db: DbSession) -> ProjectDetailResponse:
    project = await _get_project_or_404(project_id, db)
    latest_job = await _get_latest_job(project_id, db)

    # 如果处于等待用户状态，附带追问内容
    pending_question: Optional[str] = None
    if latest_job and latest_job.status == JobStatus.RUNNING:
        from app.models.job import JobStep as OrmJobStep

        if latest_job.step == OrmJobStep.SCENE_GENERATE:
            try:
                store = _get_redis_store()
                pending_question = store.load_pending_question(project_id)
            except Exception:
                pass

    data = ProjectDetailResponse(
        **ProjectRead.model_validate(project).model_dump(),
        latest_job=JobRead.model_validate(latest_job) if latest_job else None,
        pending_question=pending_question,
    )
    return data


# ── DELETE /api/projects/{project_id} ────────────────────────────────────────


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除项目（级联删除任务和对话）",
)
async def delete_project(project_id: int, db: DbSession):
    proj = await _get_project_or_404(project_id, db)
    await db.delete(proj)
    await db.commit()
    # 清理 Redis 中间状态
    try:
        store = _get_redis_store()
        store.cleanup_project(project_id)
    except Exception as exc:
        logger.warning(
            "[Projects API] Failed to cleanup Redis for project {}: {}", project_id, exc
        )
    logger.info("[Projects API] Deleted project id={}", project_id)


# ── POST /api/projects/{project_id}/generate ─────────────────────────────────


@router.post(
    "/{project_id}/generate",
    response_model=GenerateResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="触发完整生成流程（启动 Celery 任务）",
)
async def start_generation(
    project_id: int,
    payload: GenerateRequest,
    db: DbSession,
) -> GenerateResponse:
    from app.celery_app import celery_app

    project = await _get_project_or_404(project_id, db)

    # 校验：必须有 CAD 文件
    if not project.cad_file_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="项目尚未上传 CAD 文件，请先通过 /upload_cad 上传",
        )

    # 校验：不能重复触发
    if project.status in (
        ProjectStatus.PARSING,
        ProjectStatus.GENERATING,
        ProjectStatus.EXPORTING,
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"项目当前状态为 {project.status.value}，请等待当前任务完成后再触发",
        )

    # 若有描述则更新项目描述
    if payload.user_description:
        project.user_description = payload.user_description

    # 创建 Job 记录（先创建，后填入 celery_task_id）
    new_job = await job_service.create_job(session=db, project_id=project_id)
    await db.flush()

    # 提交 Celery 任务
    task = celery_app.send_task(
        "tasks.run_full_pipeline",
        kwargs={
            "project_id": project_id,
            "cad_file_path": project.cad_file_path,
            "user_description": payload.user_description,
            "job_id": new_job.id,
        },
        queue="cad",
    )

    # 回填 Celery task ID
    await job_service.update_celery_task_id(db, new_job.id, task.id)
    await db.commit()

    logger.info(
        "[Projects API] Generation started: project_id={} job_id={} task_id={}",
        project_id,
        new_job.id,
        task.id,
    )
    return GenerateResponse(
        job_id=new_job.id,
        celery_task_id=task.id,
    )


# ── POST /api/projects/{project_id}/answer ────────────────────────────────────


@router.post(
    "/{project_id}/answer",
    response_model=AnswerResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="用户回答 AI 追问，继续生成流程",
)
async def answer_question(
    project_id: int,
    payload: AnswerRequest,
    db: DbSession,
) -> AnswerResponse:
    from app.celery_app import celery_app

    # 校验项目存在（raises 404 if not found）
    await _get_project_or_404(project_id, db)

    # 校验：Redis 中是否有待回答问题
    try:
        store = _get_redis_store()
        pending_question = store.load_pending_question(project_id)
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"Redis 服务不可用: {exc}",
        )

    if pending_question is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="该项目当前没有待回答的问题，无需调用此接口",
        )

    # 获取关联 Job
    latest_job = await _get_latest_job(project_id, db)
    if latest_job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="找不到该项目的生成任务记录",
        )

    # 清除旧追问（任务接管后会存新的）
    store.delete_pending_question(project_id)

    # 提交 continue_pipeline 任务
    task = celery_app.send_task(
        "tasks.continue_pipeline",
        kwargs={
            "project_id": project_id,
            "user_answer": payload.answer,
        },
        queue="ai",
    )

    # 更新 Job 的 celery_task_id（指向新的继续任务）
    await job_service.update_celery_task_id(db, latest_job.id, task.id)
    await db.commit()

    logger.info(
        "[Projects API] User answered: project_id={} task_id={} answer={}",
        project_id,
        task.id,
        payload.answer[:80],
    )
    return AnswerResponse(
        job_id=latest_job.id,
        celery_task_id=task.id,
    )


# ── GET /api/projects/{project_id}/scene_json ────────────────────────────────


@router.get(
    "/{project_id}/scene_json",
    summary="返回生成的场景 JSON 数据",
)
async def get_scene_json(project_id: int, db: DbSession) -> JSONResponse:
    project = await _get_project_or_404(project_id, db)

    if not project.scene_json_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="该项目尚未生成场景 JSON，请先触发生成流程",
        )

    scene_path = Path(project.scene_json_path)
    if not scene_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"场景 JSON 文件不存在: {project.scene_json_path}",
        )

    try:
        with open(scene_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        return JSONResponse(content=data)
    except Exception as exc:
        logger.error(
            "[Projects API] Failed to read scene JSON: project_id={} error={}",
            project_id,
            exc,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"读取场景 JSON 失败: {exc}",
        )


# ── GET /api/projects/{project_id}/download ──────────────────────────────────


@router.get(
    "/{project_id}/download",
    summary="下载生成的 .max 文件",
)
async def download_max_file(project_id: int, db: DbSession) -> FileResponse:
    project = await _get_project_or_404(project_id, db)

    if not project.max_file_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="该项目尚未生成 .max 文件，请先触发生成流程",
        )

    max_path = Path(project.max_file_path)
    if not max_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f".max 文件不存在: {project.max_file_path}",
        )

    filename = f"project_{project_id}_{project.name}.max"
    return FileResponse(
        path=str(max_path),
        filename=filename,
        media_type="application/octet-stream",
    )


# ── GET /api/projects/{project_id}/preview ───────────────────────────────────


@router.get(
    "/{project_id}/preview",
    summary="获取场景预览图",
)
async def get_preview_image(project_id: int, db: DbSession) -> FileResponse:
    project = await _get_project_or_404(project_id, db)

    if not project.preview_image_path:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="该项目尚未生成预览图",
        )

    preview_path = Path(project.preview_image_path)
    if not preview_path.exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"预览图文件不存在: {project.preview_image_path}",
        )

    # 根据后缀推断 MIME 类型
    suffix = preview_path.suffix.lower()
    media_type_map = {
        ".jpg": "image/jpeg",
        ".jpeg": "image/jpeg",
        ".png": "image/png",
        ".webp": "image/webp",
        ".gif": "image/gif",
    }
    media_type = media_type_map.get(suffix, "image/jpeg")

    return FileResponse(
        path=str(preview_path),
        media_type=media_type,
    )


# ── GET /api/projects/{project_id}/jobs ──────────────────────────────────────


@router.get(
    "/{project_id}/jobs",
    response_model=JobListResponse,
    summary="获取项目的所有生成任务列表",
)
async def list_project_jobs(
    project_id: int,
    db: DbSession,
    limit: int = Query(default=50, ge=1, le=200, description="最大返回条数"),
) -> JobListResponse:
    await _get_project_or_404(project_id, db)
    jobs = await job_service.get_jobs_by_project(db, project_id)
    jobs = jobs[:limit]
    return JobListResponse(
        project_id=project_id,
        total=len(jobs),
        items=[JobRead.model_validate(j) for j in jobs],
    )

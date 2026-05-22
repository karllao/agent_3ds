"""
CAD 文件上传 API（完整版）。

端点：
  POST /api/projects/{project_id}/upload_cad
      接收 multipart/form-data 文件（.dxf 或 .dwg）
      保存到 STORAGE_PATH/{project_id}/cad/
      更新 project.cad_file_path

  POST /api/projects/{project_id}/parse_cad
      触发 cad_parse_only Celery 任务（快速预览识别结果）
      返回 { task_id, message }

  GET  /api/projects/{project_id}/cad_preview
      返回 CAD 解析摘要（墙数、房间数、识别层名等）
      优先读取 Redis 缓存，其次读取已落地的 JSON 文件
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, UploadFile, status
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import select

from app.config import get_settings
from app.database import DbSession
from app.models.project import Project, ProjectStatus
from app.utils.file_utils import save_upload_file

router = APIRouter()
settings = get_settings()

# ── 常量 ──────────────────────────────────────────────────────────────────────

ALLOWED_EXTENSIONS = {".dxf", ".dwg"}
MAX_FILE_SIZE_MB = 200
MAX_FILE_SIZE_BYTES = MAX_FILE_SIZE_MB * 1024 * 1024


# ── 响应体 ────────────────────────────────────────────────────────────────────


class UploadCadResponse(BaseModel):
    """CAD 文件上传成功的响应。"""

    project_id: int
    cad_file_path: str
    file_size_kb: float
    filename: str
    message: str = "CAD 文件上传成功"


class ParseCadResponse(BaseModel):
    """触发 CAD 解析任务的响应。"""

    project_id: int
    task_id: str
    message: str = "CAD 解析任务已提交"


class CadPreviewResponse(BaseModel):
    """CAD 解析结果摘要响应。"""

    project_id: int
    wall_count: int
    room_count: int
    door_count: int
    window_count: int
    layer_names: list[str]
    bounding_box: Optional[dict] = None
    parse_warnings: list[str]
    parse_time_ms: float
    cached: bool = False


# ── 工具函数 ──────────────────────────────────────────────────────────────────


async def _get_project_or_404(project_id: int, db) -> Project:
    """根据 ID 查找项目，不存在则返回 404。"""
    result = await db.execute(select(Project).where(Project.id == project_id))
    project = result.scalar_one_or_none()
    if project is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"项目 {project_id} 不存在",
        )
    return project


def _get_redis_store():
    from app.tasks.redis_state_store import RedisStateStore

    return RedisStateStore(settings.redis_url)


# ── POST /api/projects/{project_id}/upload_cad ───────────────────────────────


@router.post(
    "/{project_id}/upload_cad",
    response_model=UploadCadResponse,
    status_code=status.HTTP_200_OK,
    summary="上传 CAD 文件（DXF / DWG）",
    description=(
        f"为指定项目上传 CAD 平面图文件。\n\n"
        f"- 支持格式：DXF、DWG\n"
        f"- 最大文件大小：{MAX_FILE_SIZE_MB} MB\n"
        f"- 重复上传将覆盖旧文件（以新 UUID 文件名保存）"
    ),
)
async def upload_cad_file(
    project_id: int,
    file: UploadFile,
    db: DbSession,
) -> UploadCadResponse:
    # ── 查找项目 ──────────────────────────────────────────────────────────────
    project = await _get_project_or_404(project_id, db)

    # ── 校验文件名与格式 ───────────────────────────────────────────────────────
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="上传文件名不能为空",
        )

    suffix = Path(file.filename).suffix.lower()
    if suffix not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail=f"不支持的文件格式 {suffix!r}，仅支持 DXF / DWG",
        )

    # ── 读取并校验文件大小 ─────────────────────────────────────────────────────
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="上传文件内容为空",
        )
    if len(content) > MAX_FILE_SIZE_BYTES:
        raise HTTPException(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"文件大小超过限制 {MAX_FILE_SIZE_MB} MB",
        )

    # ── 保存文件 ───────────────────────────────────────────────────────────────
    cad_save_dir = settings.storage_path / str(project_id) / "cad"
    dest_path = await save_upload_file(
        content=content,
        original_filename=file.filename,
        sub_dir=cad_save_dir,
        preserve_name=False,  # 使用 UUID 文件名，防止并发覆盖
    )

    # ── 更新项目 ───────────────────────────────────────────────────────────────
    project.cad_file_path = str(dest_path)
    project.status = ProjectStatus.CAD_UPLOADED
    await db.flush()
    await db.commit()
    await db.refresh(project)

    # 清除旧的 CAD 解析缓存（文件已更新，缓存失效）
    try:
        store = _get_redis_store()
        store.delete_cad_result(project_id)
    except Exception as exc:
        logger.warning(
            "[CAD Upload] Failed to clear CAD cache for project {}: {}", project_id, exc
        )

    file_size_kb = len(content) / 1024
    logger.info(
        "[CAD Upload] File uploaded: project_id={} path={} size={:.1f}KB",
        project_id,
        dest_path,
        file_size_kb,
    )
    return UploadCadResponse(
        project_id=project_id,
        cad_file_path=str(dest_path),
        file_size_kb=round(file_size_kb, 2),
        filename=file.filename,
    )


# ── POST /api/projects/{project_id}/parse_cad ────────────────────────────────


@router.post(
    "/{project_id}/parse_cad",
    response_model=ParseCadResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="触发 CAD 解析任务（异步，用于预览识别结果）",
)
async def trigger_parse_cad(
    project_id: int,
    db: DbSession,
) -> ParseCadResponse:
    from app.celery_app import celery_app

    project = await _get_project_or_404(project_id, db)

    if not project.cad_file_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="项目尚未上传 CAD 文件，请先调用 /upload_cad",
        )

    if not Path(project.cad_file_path).exists():
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"CAD 文件不存在: {project.cad_file_path}，请重新上传",
        )

    task = celery_app.send_task(
        "tasks.cad_parse_only",
        kwargs={
            "project_id": project_id,
            "cad_file_path": project.cad_file_path,
        },
        queue="cad",
    )

    logger.info(
        "[CAD Upload] Parse task submitted: project_id={} task_id={}",
        project_id,
        task.id,
    )
    return ParseCadResponse(
        project_id=project_id,
        task_id=task.id,
    )


# ── GET /api/projects/{project_id}/cad_preview ───────────────────────────────


@router.get(
    "/{project_id}/cad_preview",
    response_model=CadPreviewResponse,
    summary="获取 CAD 解析结果摘要",
    description=(
        "返回 CAD 文件的解析摘要（墙数量、房间数量、识别层名等）。\n\n"
        "优先从 Redis 缓存读取，其次从磁盘 JSON 文件读取。\n"
        "若尚未解析，请先调用 /parse_cad 并等待任务完成。"
    ),
)
async def get_cad_preview(
    project_id: int,
    db: DbSession,
) -> CadPreviewResponse:
    project = await _get_project_or_404(project_id, db)

    if not project.cad_file_path:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="项目尚未上传 CAD 文件",
        )

    # 1. 尝试从 Redis 缓存读取
    cad_data: Optional[dict] = None
    cached = False
    try:
        store = _get_redis_store()
        cad_data = store.load_cad_result(project_id)
        if cad_data is not None:
            cached = True
    except Exception as exc:
        logger.warning(
            "[CAD Upload] Redis unavailable for project {}: {}", project_id, exc
        )

    # 2. 尝试从磁盘 JSON 文件读取
    if cad_data is None:
        cad_json_path = (
            settings.storage_path / str(project_id) / "cad" / "cad_result.json"
        )
        if cad_json_path.exists():
            try:
                with open(cad_json_path, "r", encoding="utf-8") as f:
                    cad_data = json.load(f)
                logger.info(
                    "[CAD Upload] Loaded CAD result from disk: {}", cad_json_path
                )
            except Exception as exc:
                logger.error(
                    "[CAD Upload] Failed to read cad_result.json: project_id={} error={}",
                    project_id,
                    exc,
                )

    if cad_data is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=(
                "尚无 CAD 解析结果。请先调用 POST /parse_cad 触发解析，"
                "等待任务完成后再查询。"
            ),
        )

    # 提取摘要字段
    summary: dict = cad_data.get("summary", {})
    return CadPreviewResponse(
        project_id=project_id,
        wall_count=summary.get("wall_count", len(cad_data.get("walls", []))),
        room_count=summary.get("room_count", len(cad_data.get("rooms", []))),
        door_count=summary.get("door_count", len(cad_data.get("doors", []))),
        window_count=summary.get("window_count", len(cad_data.get("windows", []))),
        layer_names=cad_data.get("layer_names", []),
        bounding_box=cad_data.get("bounding_box"),
        parse_warnings=cad_data.get("parse_warnings", []),
        parse_time_ms=cad_data.get("parse_time_ms", 0.0),
        cached=cached,
    )


# ── DELETE /api/projects/{project_id}/cad ────────────────────────────────────


@router.delete(
    "/{project_id}/cad",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="删除已上传的 CAD 文件",
)
async def delete_cad_file(project_id: int, db: DbSession):
    import aiofiles.os

    project = await _get_project_or_404(project_id, db)

    if project.cad_file_path is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="该项目没有已上传的 CAD 文件",
        )

    cad_path = Path(project.cad_file_path)
    if cad_path.exists():
        await aiofiles.os.remove(cad_path)
        logger.info("[CAD Upload] CAD file removed: {}", cad_path)
    else:
        logger.warning(
            "[CAD Upload] CAD file not found on disk, clearing DB path: {}", cad_path
        )

    project.cad_file_path = None
    project.status = ProjectStatus.CREATED
    await db.flush()
    await db.commit()

    # 清除 Redis 缓存
    try:
        store = _get_redis_store()
        store.delete_cad_result(project_id)
    except Exception as exc:
        logger.warning(
            "[CAD Upload] Failed to clear CAD cache on delete: project_id={} error={}",
            project_id,
            exc,
        )

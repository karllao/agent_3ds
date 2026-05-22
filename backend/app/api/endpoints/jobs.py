"""
生成任务 API（完整版）。

端点：
  GET  /api/jobs/{job_id}          查询任务详情与进度
  GET  /api/jobs/{job_id}/log      获取任务日志（从文件读取）
  POST /api/jobs/{job_id}/cancel   撤销 / 取消正在运行的任务
"""

from __future__ import annotations

import glob
import os
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import PlainTextResponse
from loguru import logger
from pydantic import BaseModel
from sqlalchemy import select

from app.config import get_settings
from app.database import DbSession
from app.models.job import Job, JobStatus
from app.schemas.job import JobRead

router = APIRouter()
settings = get_settings()


# ── 响应体 ────────────────────────────────────────────────────────────────────


class CancelJobResponse(BaseModel):
    """取消任务的响应。"""

    job_id: int
    celery_task_id: Optional[str]
    message: str = "任务已撤销"


# ── 工具函数 ──────────────────────────────────────────────────────────────────


async def _get_job_or_404(job_id: int, db) -> Job:
    """根据 ID 查找任务，不存在则返回 404。"""
    result = await db.execute(select(Job).where(Job.id == job_id))
    job = result.scalar_one_or_none()
    if job is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"任务 {job_id} 不存在",
        )
    return job


def _find_log_content(job: Job) -> Optional[str]:
    """
    尝试从日志文件中提取与该 Job 相关的日志内容。

    查找策略：
    1. 如果 Job 有 celery_task_id，在 loguru 日志文件中搜索该 ID
    2. 搜索 STORAGE_PATH/{project_id}/logs/ 目录（若存在）
    3. 返回最近一个日志文件的相关片段

    Returns:
        日志字符串，未找到则返回 None。
    """
    lines: list[str] = []

    # 尝试从存储路径下的项目日志目录读取
    project_log_dir = settings.storage_path / str(job.project_id) / "logs"
    if project_log_dir.exists():
        log_files = sorted(
            project_log_dir.glob("*.log"),
            key=os.path.getmtime,
            reverse=True,
        )
        for log_file in log_files[:3]:  # 最多检查 3 个日志文件
            try:
                with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                    log_lines = f.readlines()
                # 过滤与该 job 相关的行
                relevant = [
                    line
                    for line in log_lines
                    if (
                        f"job_id={job.id}" in line
                        or f"Job {job.id}" in line
                        or (job.celery_task_id and job.celery_task_id in line)
                    )
                ]
                lines.extend(relevant)
            except Exception as exc:
                logger.debug("[Jobs API] Failed to read log file {}: {}", log_file, exc)

    # 也可以尝试从全局 loguru 日志文件中提取
    if not lines and job.celery_task_id:
        global_log_patterns = [
            "/var/log/app/*.log",
            "/tmp/app*.log",
            str(settings.storage_path / "logs" / "*.log"),
        ]
        for pattern in global_log_patterns:
            for log_file_str in glob.glob(pattern):
                log_file = Path(log_file_str)
                if not log_file.exists():
                    continue
                try:
                    with open(log_file, "r", encoding="utf-8", errors="replace") as f:
                        for line in f:
                            if job.celery_task_id in line or f"Job {job.id}" in line:
                                lines.append(line)
                    if lines:
                        break
                except Exception:
                    pass

    return "".join(lines) if lines else None


# ── GET /api/jobs/{job_id} ────────────────────────────────────────────────────


@router.get(
    "/{job_id}",
    response_model=JobRead,
    summary="查询任务详情与进度",
)
async def get_job(job_id: int, db: DbSession) -> JobRead:
    job = await _get_job_or_404(job_id, db)
    return JobRead.model_validate(job)


# ── GET /api/jobs/{job_id}/log ────────────────────────────────────────────────


@router.get(
    "/{job_id}/log",
    response_class=PlainTextResponse,
    summary="获取任务日志（从文件读取，纯文本格式）",
)
async def get_job_log(
    job_id: int,
    db: DbSession,
    tail: int = Query(
        default=200,
        ge=1,
        le=5000,
        description="返回最后 N 行日志，默认 200",
    ),
) -> str:
    job = await _get_job_or_404(job_id, db)

    log_content = _find_log_content(job)

    if log_content is None:
        # 生成摘要信息作为日志替代
        log_content = (
            f"# Job {job_id} 日志\n"
            f"project_id : {job.project_id}\n"
            f"celery_id  : {job.celery_task_id or 'N/A'}\n"
            f"status     : {job.status.value}\n"
            f"step       : {job.step.value if job.step else 'N/A'}\n"
            f"progress   : {job.progress}%\n"
            f"created_at : {job.created_at}\n"
            f"updated_at : {job.updated_at}\n"
        )
        if job.error_message:
            log_content += f"\n[ERROR]\n{job.error_message}\n"
        log_content += "\n（未找到详细日志文件，以上为任务元数据摘要）\n"
    else:
        # 只返回最后 tail 行
        all_lines = log_content.splitlines(keepends=True)
        if len(all_lines) > tail:
            log_content = "".join(all_lines[-tail:])

    logger.debug(
        "[Jobs API] Log retrieved: job_id={} content_len={}", job_id, len(log_content)
    )
    return log_content


# ── POST /api/jobs/{job_id}/cancel ────────────────────────────────────────────


@router.post(
    "/{job_id}/cancel",
    response_model=CancelJobResponse,
    summary="撤销 / 取消正在运行的任务",
)
async def cancel_job(job_id: int, db: DbSession) -> CancelJobResponse:
    from app.celery_app import celery_app
    from app.models.project import ProjectStatus
    from app.services.project_service import project_service

    job = await _get_job_or_404(job_id, db)

    # 只有 PENDING / RUNNING 的任务可以取消
    if job.status not in (JobStatus.PENDING, JobStatus.RUNNING):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=f"任务当前状态为 {job.status.value}，无法取消",
        )

    celery_task_id = job.celery_task_id

    # 撤销 Celery 任务
    if celery_task_id:
        try:
            celery_app.control.revoke(
                celery_task_id,
                terminate=True,
                signal="SIGTERM",
            )
            logger.info(
                "[Jobs API] Celery task revoked: task_id={} job_id={}",
                celery_task_id,
                job_id,
            )
        except Exception as exc:
            logger.warning(
                "[Jobs API] Failed to revoke Celery task {}: {}", celery_task_id, exc
            )
            # 非致命：即使撤销失败，也更新 DB 状态

    # 更新 Job 状态（DB ENUM 无 REVOKED，用 FAILED + 错误消息表示"被取消"）
    job.status = JobStatus.FAILED
    job.error_message = "任务被手动取消"
    await db.flush()

    # 同步更新项目状态为 FAILED（取消 = 失败）
    try:
        await project_service.update_project_status(
            session=db,
            project_id=job.project_id,
            status=ProjectStatus.FAILED.value,
        )
    except Exception as exc:
        logger.warning(
            "[Jobs API] Failed to update project status after cancel: project_id={} error={}",
            job.project_id,
            exc,
        )

    await db.commit()

    # 清理 Redis 中间状态
    try:
        from app.tasks.redis_state_store import RedisStateStore

        store = RedisStateStore(settings.redis_url)
        store.cleanup_project(job.project_id)
    except Exception as exc:
        logger.warning(
            "[Jobs API] Failed to cleanup Redis after cancel: project_id={} error={}",
            job.project_id,
            exc,
        )

    logger.info(
        "[Jobs API] Job cancelled: job_id={} celery_task_id={}", job_id, celery_task_id
    )
    return CancelJobResponse(
        job_id=job_id,
        celery_task_id=celery_task_id,
        message="任务已撤销",
    )

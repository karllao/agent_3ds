"""
Job 状态管理服务。

提供任务的创建、状态更新、查询等操作，基于 SQLAlchemy async session。
内部维护细粒度的步骤标签（中文），并映射到 ORM JobStep 枚举。
"""

from __future__ import annotations

from typing import List, Optional

from loguru import logger
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.job import Job, JobStatus
from app.models.job import JobStep as OrmJobStep

# ── 步骤标签常量 ───────────────────────────────────────────────────────────────


class JobStep:
    """流水线各阶段的中文显示标签（用于前端进度展示）。"""

    INIT = "初始化"
    CAD_PARSING = "解析CAD图纸"
    AI_ANALYSIS = "AI分析需求"
    WAITING_USER = "等待用户确认"
    SCENE_PLANNING = "生成设计方案"
    SCRIPT_GENERATION = "生成3ds Max脚本"
    MAX_EXECUTION = "执行3ds Max建模"
    COMPLETED = "完成"
    FAILED = "失败"


# 将服务层标签映射到 ORM JobStep 枚举值
_STEP_TO_ORM: dict[str, OrmJobStep] = {
    JobStep.INIT: OrmJobStep.CAD_PARSE,
    JobStep.CAD_PARSING: OrmJobStep.CAD_PARSE,
    JobStep.AI_ANALYSIS: OrmJobStep.SCENE_GENERATE,
    JobStep.WAITING_USER: OrmJobStep.SCENE_GENERATE,
    JobStep.SCENE_PLANNING: OrmJobStep.SCENE_GENERATE,
    JobStep.SCRIPT_GENERATION: OrmJobStep.SCENE_GENERATE,
    JobStep.MAX_EXECUTION: OrmJobStep.MAX_EXPORT,
    JobStep.COMPLETED: OrmJobStep.MAX_EXPORT,
    JobStep.FAILED: OrmJobStep.MAX_EXPORT,
}


# ── Service ────────────────────────────────────────────────────────────────────


class JobService:
    """
    Job CRUD 服务。

    所有方法接收外部传入的 AsyncSession，
    不自行提交事务（由调用方决定提交时机）。
    """

    # ── 创建 ──────────────────────────────────────────────────────────────────

    async def create_job(
        self,
        session: AsyncSession,
        project_id: int,
        celery_task_id: Optional[str] = None,
    ) -> Job:
        """
        创建新的 Job 记录（初始状态 PENDING）。

        Args:
            session:        数据库会话。
            project_id:     关联项目 ID。
            celery_task_id: 可选，Celery 任务 ID（启动后再更新也可以）。

        Returns:
            创建后的 Job 对象。
        """
        job = Job(
            project_id=project_id,
            status=JobStatus.PENDING,
            step=OrmJobStep.CAD_PARSE,
            progress=0,
            celery_task_id=celery_task_id,
        )
        session.add(job)
        await session.flush()
        await session.refresh(job)
        logger.info(
            "[JobService] Job created: id={} project_id={} celery_task_id={}",
            job.id,
            project_id,
            celery_task_id,
        )
        return job

    # ── 更新步骤 ──────────────────────────────────────────────────────────────

    async def update_job_step(
        self,
        session: AsyncSession,
        job_id: int,
        step: str,
        progress: int,
        message: str = "",
    ) -> None:
        """
        更新任务当前步骤与进度，自动将状态置为 RUNNING。

        Args:
            session:  数据库会话。
            job_id:   任务 ID。
            step:     步骤标签（使用 JobStep 中的常量）。
            progress: 进度百分比 0-100。
            message:  可选的进度说明（仅记录日志，不入库）。
        """
        job = await self._get_job(session, job_id)
        if job is None:
            logger.warning("[JobService] update_job_step: Job {} not found", job_id)
            return

        job.status = JobStatus.RUNNING
        job.step = _STEP_TO_ORM.get(step, OrmJobStep.CAD_PARSE)
        job.progress = max(0, min(100, progress))

        log_msg = f"[Job {job_id}] {step} ({job.progress}%)"
        if message:
            log_msg += f" — {message}"
        logger.info(log_msg)

        await session.flush()

    # ── 标记失败 ──────────────────────────────────────────────────────────────

    async def mark_job_failed(
        self,
        session: AsyncSession,
        job_id: int,
        error: str,
    ) -> None:
        """
        将任务标记为 FAILED 并记录错误信息。

        Args:
            session: 数据库会话。
            job_id:  任务 ID。
            error:   错误描述文本。
        """
        job = await self._get_job(session, job_id)
        if job is None:
            logger.warning("[JobService] mark_job_failed: Job {} not found", job_id)
            return

        job.status = JobStatus.FAILED
        job.error_message = error[:4096] if error else "未知错误"  # 防止超长文本
        logger.error("[Job {}] FAILED: {}", job_id, error)

        await session.flush()

    # ── 标记完成 ──────────────────────────────────────────────────────────────

    async def mark_job_completed(
        self,
        session: AsyncSession,
        job_id: int,
    ) -> None:
        """
        将任务标记为 SUCCESS，进度设为 100。

        Args:
            session: 数据库会话。
            job_id:  任务 ID。
        """
        job = await self._get_job(session, job_id)
        if job is None:
            logger.warning("[JobService] mark_job_completed: Job {} not found", job_id)
            return

        job.status = JobStatus.SUCCESS
        job.step = OrmJobStep.MAX_EXPORT
        job.progress = 100
        job.error_message = None
        logger.success("[Job {}] COMPLETED", job_id)

        await session.flush()

    # ── 查询 ──────────────────────────────────────────────────────────────────

    async def get_job(
        self,
        session: AsyncSession,
        job_id: int,
    ) -> Optional[Job]:
        """
        根据 ID 获取任务，不存在时返回 None。

        Args:
            session: 数据库会话。
            job_id:  任务 ID。

        Returns:
            Job 对象或 None。
        """
        return await self._get_job(session, job_id)

    async def get_jobs_by_project(
        self,
        session: AsyncSession,
        project_id: int,
    ) -> List[Job]:
        """
        获取某个项目的所有任务，按创建时间倒序。

        Args:
            session:    数据库会话。
            project_id: 项目 ID。

        Returns:
            Job 列表。
        """
        result = await session.execute(
            select(Job)
            .where(Job.project_id == project_id)
            .order_by(Job.created_at.desc())
        )
        return list(result.scalars().all())

    async def get_latest_job(
        self,
        session: AsyncSession,
        project_id: int,
    ) -> Optional[Job]:
        """获取项目最新一条任务记录。"""
        result = await session.execute(
            select(Job)
            .where(Job.project_id == project_id)
            .order_by(Job.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def update_celery_task_id(
        self,
        session: AsyncSession,
        job_id: int,
        celery_task_id: str,
    ) -> None:
        """更新任务的 Celery Task ID（在任务提交后回填）。"""
        job = await self._get_job(session, job_id)
        if job is None:
            logger.warning(
                "[JobService] update_celery_task_id: Job {} not found", job_id
            )
            return
        job.celery_task_id = celery_task_id
        await session.flush()

    # ── 内部工具 ──────────────────────────────────────────────────────────────

    @staticmethod
    async def _get_job(session: AsyncSession, job_id: int) -> Optional[Job]:
        result = await session.execute(select(Job).where(Job.id == job_id))
        return result.scalar_one_or_none()


# 全局单例（Celery 任务中直接 import 使用）
job_service = JobService()

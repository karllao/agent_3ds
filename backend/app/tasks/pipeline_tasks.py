"""
Celery 流水线任务。

将 CAD 解析 → Agent → 脚本生成 → 3ds Max 执行 串联为完整的 Celery 任务流。

任务列表：
  tasks.run_full_pipeline            完整生成流程（queue: cad）
  tasks.continue_pipeline            用户回答追问后继续（queue: ai）
  tasks.cad_parse_only               仅 CAD 解析，用于预览（queue: cad）

Celery 内部运行 async 代码：
  每个 Celery 任务函数是同步的，通过 asyncio.run() 包装异步逻辑。
  数据库会话使用 app.database.AsyncSessionLocal，在 asyncio.run() 中创建。
"""

from __future__ import annotations

import asyncio
import json
import traceback
from pathlib import Path
from typing import Optional

from celery.exceptions import MaxRetriesExceededError
from loguru import logger

from app.celery_app import celery_app
from app.config import get_settings

# ── 延迟导入辅助（避免 Celery beat 启动时触发 DB 连接）──────────────────────


def _get_settings():
    return get_settings()


def _get_state_store():
    from app.tasks.redis_state_store import RedisStateStore

    settings = _get_settings()
    return RedisStateStore(settings.redis_url)


def _get_max_client():
    from app.services.max_worker_client import MaxWorkerClient

    settings = _get_settings()
    return MaxWorkerClient(base_url=settings.max_worker_url)


# ── DB 上下文管理器（在 asyncio.run() 内使用）────────────────────────────────


async def _db_session():
    """返回 AsyncSessionLocal 上下文管理器，给 async with 使用。"""
    from app.database import AsyncSessionLocal

    return AsyncSessionLocal()


# ═══════════════════════════════════════════════════════════════════════════════
# 任务一：完整流水线
# ═══════════════════════════════════════════════════════════════════════════════


@celery_app.task(
    bind=True,
    name="tasks.run_full_pipeline",
    queue="cad",
    max_retries=2,
    default_retry_delay=30,
    acks_late=True,
)
def run_full_pipeline(
    self,
    project_id: int,
    cad_file_path: str,
    user_description: str,
    job_id: Optional[int] = None,
):
    """
    完整生成流水线 Celery 任务。

    步骤：
      1. 更新 Job 状态 → CAD_PARSING
      2. 运行 CADPipeline.process(cad_file_path)
      3. 序列化并缓存 CAD 结果到 Redis 和 JSON 文件
      4. 更新 Job 状态 → AI_ANALYSIS
      5. 运行 run_agent_pipeline(project_id, cad_result, user_description, [])
      6a. 若 needs_user_input=True：
            更新 Job → WAITING_USER，存 state 到 Redis，返回（等待用户）
      6b. 否则：继续流程
      7. 更新 Job → SCRIPT_GENERATION
      8. 运行 SceneScriptGenerator.generate()
      9. 更新 Job → MAX_EXECUTION
     10. MaxWorkerClient.execute_script()，轮询完成
     11. 更新 Project 路径，更新 Job → COMPLETED

    Args:
        project_id:       项目 ID（整数）。
        cad_file_path:    CAD 文件绝对路径。
        user_description: 用户描述文本。
        job_id:           关联的 Job ID；若为 None 则自动查找该项目最新 pending job。
    """
    logger.info(
        "[Pipeline] run_full_pipeline started: project_id={} job_id={} cad={}",
        project_id,
        job_id,
        cad_file_path,
    )

    try:
        asyncio.run(
            _run_full_pipeline_async(
                task_self=self,
                project_id=project_id,
                cad_file_path=cad_file_path,
                user_description=user_description,
                job_id=job_id,
            )
        )
    except Exception as exc:
        logger.error(
            "[Pipeline] run_full_pipeline unhandled error: project_id={} error={}",
            project_id,
            exc,
        )
        # 尝试重试，超出次数则标记失败
        try:
            raise self.retry(exc=exc, countdown=30)
        except MaxRetriesExceededError:
            # 最后一次重试也失败，在 DB 中标记
            asyncio.run(_mark_failed_in_db(project_id, job_id, str(exc)))
            raise


async def _run_full_pipeline_async(
    task_self,
    project_id: int,
    cad_file_path: str,
    user_description: str,
    job_id: Optional[int],
) -> None:
    """完整流水线的 async 实现体。"""
    from app.agents.graph import run_agent_pipeline
    from app.database import AsyncSessionLocal
    from app.models.project import ProjectStatus
    from app.services.cad_parser.cad_pipeline import CADPipeline
    from app.services.job_service import JobStep, job_service
    from app.services.max_script_generator.scene_script_generator import (
        SceneScriptGenerator,
    )
    from app.services.project_service import project_service

    settings = _get_settings()
    state_store = _get_state_store()
    max_client = _get_max_client()

    # ── 解析 job_id ───────────────────────────────────────────────────────────
    effective_job_id: Optional[int] = job_id
    async with AsyncSessionLocal() as session:
        if effective_job_id is None:
            latest_job = await job_service.get_latest_job(session, project_id)
            if latest_job is not None:
                effective_job_id = latest_job.id
            else:
                new_job = await job_service.create_job(session, project_id)
                effective_job_id = new_job.id
                await session.commit()

    if effective_job_id is None:
        logger.error("[Pipeline] Could not resolve job_id for project {}", project_id)
        raise RuntimeError(f"无法找到项目 {project_id} 的 Job 记录")

    # 将 job_id 存入 Redis，便于 continue_pipeline 查找
    state_store.save_job_id(project_id, effective_job_id)

    # ── 步骤 1: CAD 解析 ───────────────────────────────────────────────────────
    async with AsyncSessionLocal() as session:
        await job_service.update_job_step(
            session, effective_job_id, JobStep.CAD_PARSING, 10, "开始解析 CAD 文件"
        )
        await project_service.update_project_status(
            session, project_id, ProjectStatus.PARSING.value
        )
        await session.commit()

    cad_result_dict: dict
    try:
        pipeline = CADPipeline()
        cad_result = await pipeline.process(cad_file_path)
        cad_result_dict = cad_result.to_dict()
        logger.info(
            "[Pipeline] CAD parsing done: walls={} rooms={} doors={} windows={}",
            len(cad_result.walls),
            len(cad_result.rooms),
            len(cad_result.doors),
            len(cad_result.windows),
        )
    except Exception as exc:
        error_msg = f"CAD 解析失败: {exc}"
        logger.error("[Pipeline] {}", error_msg)
        logger.debug(traceback.format_exc())
        async with AsyncSessionLocal() as session:
            await job_service.mark_job_failed(session, effective_job_id, error_msg)
            await project_service.update_project_status(
                session, project_id, ProjectStatus.FAILED.value
            )
            await session.commit()
        raise RuntimeError(error_msg) from exc

    # 序列化 CAD 结果到文件 + Redis 缓存
    cad_json_dir = settings.storage_path / str(project_id) / "cad"
    cad_json_dir.mkdir(parents=True, exist_ok=True)
    cad_json_path = cad_json_dir / "cad_result.json"
    try:
        with open(cad_json_path, "w", encoding="utf-8") as f:
            json.dump(cad_result_dict, f, ensure_ascii=False, indent=2)
        state_store.save_cad_result(project_id, cad_result_dict)
    except Exception as exc:
        logger.warning("[Pipeline] Failed to cache CAD result: {}", exc)
        # 非致命错误，继续执行

    async with AsyncSessionLocal() as session:
        await job_service.update_job_step(
            session,
            effective_job_id,
            JobStep.AI_ANALYSIS,
            25,
            "CAD 解析完成，启动 AI 分析",
        )
        await project_service.update_project_status(
            session, project_id, ProjectStatus.GENERATING.value
        )
        await session.commit()

    # ── 步骤 2: Agent 流水线 ───────────────────────────────────────────────────
    try:
        agent_result = await run_agent_pipeline(
            project_id=str(project_id),
            cad_result_dict=cad_result_dict,
            user_description=user_description,
            conversation_history=[],
        )
    except Exception as exc:
        error_msg = f"AI 分析失败: {exc}"
        logger.error("[Pipeline] {}", error_msg)
        logger.debug(traceback.format_exc())
        async with AsyncSessionLocal() as session:
            await job_service.mark_job_failed(session, effective_job_id, error_msg)
            await project_service.update_project_status(
                session, project_id, ProjectStatus.FAILED.value
            )
            await session.commit()
        raise RuntimeError(error_msg) from exc

    agent_status = agent_result.get("status", "error")

    # ── 步骤 3: 判断是否需要用户输入 ─────────────────────────────────────────
    if agent_status == "needs_user_input":
        pending_question = agent_result.get("pending_question", "请提供更多信息")
        state_snapshot = agent_result.get("state_snapshot", {})

        # 持久化到 Redis
        state_store.save_agent_state(project_id, state_snapshot)
        state_store.save_pending_question(project_id, pending_question)

        async with AsyncSessionLocal() as session:
            await job_service.update_job_step(
                session,
                effective_job_id,
                JobStep.WAITING_USER,
                40,
                f"AI 追问：{pending_question[:80]}",
            )
            await session.commit()

        logger.info(
            "[Pipeline] Waiting for user input: project_id={} question={}",
            project_id,
            pending_question[:100],
        )
        # 任务正常返回，等待用户通过 /answer 接口恢复
        return

    if agent_status == "error":
        error_msg = f"AI 生成失败: {agent_result.get('error', '未知错误')}"
        async with AsyncSessionLocal() as session:
            await job_service.mark_job_failed(session, effective_job_id, error_msg)
            await project_service.update_project_status(
                session, project_id, ProjectStatus.FAILED.value
            )
            await session.commit()
        raise RuntimeError(error_msg)

    # ── 步骤 4: 脚本生成 ───────────────────────────────────────────────────────
    full_scene_data: dict = agent_result.get("full_scene_data") or {}

    async with AsyncSessionLocal() as session:
        await job_service.update_job_step(
            session,
            effective_job_id,
            JobStep.SCRIPT_GENERATION,
            60,
            "开始生成 MAXScript",
        )
        await project_service.update_project_status(
            session, project_id, ProjectStatus.GENERATING.value
        )
        await session.commit()

    # 准备输出路径
    script_dir = settings.storage_path / str(project_id) / "scripts"
    script_dir.mkdir(parents=True, exist_ok=True)
    max_dir = settings.storage_path / str(project_id) / "max"
    max_dir.mkdir(parents=True, exist_ok=True)

    scene_json_path = settings.storage_path / str(project_id) / "scene.json"
    script_path = str(script_dir / "scene.ms")
    output_max_path = str(max_dir / "scene.max")

    # 保存 scene JSON
    try:
        with open(scene_json_path, "w", encoding="utf-8") as f:
            json.dump(full_scene_data, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.warning("[Pipeline] Failed to save scene JSON: {}", exc)

    # 生成 MAXScript
    try:
        generator = SceneScriptGenerator()
        generator.generate(
            scene_data=full_scene_data,
            output_script_path=script_path,
            output_max_path=output_max_path,
        )
        logger.info("[Pipeline] MAXScript generated: {}", script_path)
    except Exception as exc:
        error_msg = f"脚本生成失败: {exc}"
        logger.error("[Pipeline] {}", error_msg)
        logger.debug(traceback.format_exc())
        async with AsyncSessionLocal() as session:
            await job_service.mark_job_failed(session, effective_job_id, error_msg)
            await project_service.update_project_status(
                session, project_id, ProjectStatus.FAILED.value
            )
            await session.commit()
        raise RuntimeError(error_msg) from exc

    # ── 步骤 5: 调用 max_worker 执行建模 ──────────────────────────────────────
    async with AsyncSessionLocal() as session:
        await job_service.update_job_step(
            session,
            effective_job_id,
            JobStep.MAX_EXECUTION,
            75,
            "提交脚本到 3ds Max Worker",
        )
        await project_service.update_project_status(
            session, project_id, ProjectStatus.EXPORTING.value
        )
        await session.commit()

    try:
        submit_result = await max_client.execute_script(
            script_path=script_path,
            output_max_path=output_max_path,
            timeout=settings.celery_task_soft_time_limit,
        )
        max_task_id: str = submit_result["task_id"]
        logger.info("[Pipeline] max_worker task submitted: task_id={}", max_task_id)

        # 轮询等待完成
        final_status = await max_client.wait_for_completion(
            task_id=max_task_id,
            poll_interval=5.0,
            timeout=float(settings.celery_task_soft_time_limit),
        )

        if final_status.get("status") != "completed":
            err_text = (
                final_status.get("error_message")
                or final_status.get("error")
                or "未知错误"
            )
            stderr_tail = (final_status.get("stderr") or "")[-800:]
            rc = final_status.get("return_code")
            detail = f"{err_text} (rc={rc})" if rc is not None else err_text
            if stderr_tail:
                detail = f"{detail} | stderr: {stderr_tail}"
            raise RuntimeError(f"max_worker 执行失败: {detail}")

        actual_max_path = final_status.get("output_max_path") or output_max_path
        logger.success("[Pipeline] max_worker completed: output={}", actual_max_path)

        # worker 把 .max 写在它自己的 Windows 磁盘上（如 F:\cad_agent_work\<task>\scene.max），
        # backend 在 Linux 容器里看不到这个路径，必须主动拉回本地，否则后续
        # /download 端点会 404。落地到 backend 本地 storage 后用 Linux 路径写库。
        try:
            local_artifact = await max_client.download_artifact(
                task_id=max_task_id,
                dest_path=output_max_path,
            )
            actual_max_path = str(local_artifact)
            logger.info(
                "[Pipeline] Artifact saved locally: {}", actual_max_path
            )
        except Exception as exc:
            error_msg = f"拉取 .max 产物失败: {exc}"
            logger.error("[Pipeline] {}", error_msg)
            logger.debug(traceback.format_exc())
            async with AsyncSessionLocal() as session:
                await job_service.mark_job_failed(
                    session, effective_job_id, error_msg
                )
                await project_service.update_project_status(
                    session, project_id, ProjectStatus.FAILED.value
                )
                await session.commit()
            raise RuntimeError(error_msg) from exc

    except Exception as exc:
        error_msg = f"3ds Max 执行失败: {exc}"
        logger.error("[Pipeline] {}", error_msg)
        logger.debug(traceback.format_exc())
        async with AsyncSessionLocal() as session:
            await job_service.mark_job_failed(session, effective_job_id, error_msg)
            await project_service.update_project_status(
                session, project_id, ProjectStatus.FAILED.value
            )
            await session.commit()
        raise RuntimeError(error_msg) from exc

    # ── 步骤 6: 完成，更新项目路径 ────────────────────────────────────────────
    async with AsyncSessionLocal() as session:
        await project_service.update_project_paths(
            session,
            project_id,
            scene_json_path=str(scene_json_path),
            max_file_path=actual_max_path,
        )
        await project_service.update_project_status(
            session, project_id, ProjectStatus.COMPLETED.value
        )
        await job_service.mark_job_completed(session, effective_job_id)
        await session.commit()

    # 清理 Redis 中间状态
    state_store.cleanup_project(project_id)

    logger.success(
        "[Pipeline] run_full_pipeline COMPLETED: project_id={} job_id={}",
        project_id,
        effective_job_id,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 任务二：用户回答后继续流水线
# ═══════════════════════════════════════════════════════════════════════════════


@celery_app.task(
    bind=True,
    name="tasks.continue_pipeline",
    queue="ai",
    max_retries=2,
    default_retry_delay=30,
    acks_late=True,
)
def continue_pipeline_after_user_answer(
    self,
    project_id: int,
    user_answer: str,
):
    """
    用户回答追问后继续执行流水线。

    步骤：
      1. 从 Redis 读取 project:{project_id}:agent_state
      2. 调用 continue_with_user_answer(state, user_answer)
      3. 若仍需用户输入：更新状态 WAITING_USER，存回 Redis
      4. 否则：SCRIPT_GENERATION → MAX_EXECUTION → COMPLETED

    Args:
        project_id:  项目 ID。
        user_answer: 用户回答文本。
    """
    logger.info(
        "[Pipeline] continue_pipeline_after_user_answer: project_id={} answer={}",
        project_id,
        user_answer[:80],
    )

    try:
        asyncio.run(
            _continue_pipeline_async(
                task_self=self,
                project_id=project_id,
                user_answer=user_answer,
            )
        )
    except Exception as exc:
        logger.error(
            "[Pipeline] continue_pipeline unhandled error: project_id={} error={}",
            project_id,
            exc,
        )
        try:
            raise self.retry(exc=exc, countdown=30)
        except MaxRetriesExceededError:
            state_store = _get_state_store()
            job_id = state_store.load_job_id(project_id)
            asyncio.run(_mark_failed_in_db(project_id, job_id, str(exc)))
            raise


async def _continue_pipeline_async(
    task_self,
    project_id: int,
    user_answer: str,
) -> None:
    """continue_pipeline 的 async 实现体。"""
    from app.agents.graph import continue_with_user_answer
    from app.database import AsyncSessionLocal
    from app.models.project import ProjectStatus
    from app.services.job_service import JobStep, job_service
    from app.services.max_script_generator.scene_script_generator import (
        SceneScriptGenerator,
    )
    from app.services.project_service import project_service

    settings = _get_settings()
    state_store = _get_state_store()
    max_client = _get_max_client()

    # 加载中间状态
    state_snapshot = state_store.load_agent_state(project_id)
    if state_snapshot is None:
        raise RuntimeError(f"Redis 中找不到项目 {project_id} 的 Agent 状态，无法继续")

    job_id = state_store.load_job_id(project_id)
    if job_id is None:
        logger.warning(
            "[Pipeline] job_id not found in Redis for project {}, looking up DB",
            project_id,
        )
        async with AsyncSessionLocal() as session:
            latest = await job_service.get_latest_job(session, project_id)
            job_id = latest.id if latest else None

    if job_id is None:
        raise RuntimeError(f"无法找到项目 {project_id} 的 Job ID")

    # 更新状态：AI 分析中
    async with AsyncSessionLocal() as session:
        await job_service.update_job_step(
            session, job_id, JobStep.AI_ANALYSIS, 45, "处理用户回答，继续 AI 分析"
        )
        await session.commit()

    # 继续 Agent
    try:
        agent_result = await continue_with_user_answer(
            state_snapshot=state_snapshot,
            user_answer=user_answer,
        )
    except Exception as exc:
        error_msg = f"AI 继续分析失败: {exc}"
        logger.error("[Pipeline] {}", error_msg)
        async with AsyncSessionLocal() as session:
            await job_service.mark_job_failed(session, job_id, error_msg)
            await project_service.update_project_status(
                session, project_id, ProjectStatus.FAILED.value
            )
            await session.commit()
        raise RuntimeError(error_msg) from exc

    agent_status = agent_result.get("status", "error")

    # 仍需用户输入 → 再次等待
    if agent_status == "needs_user_input":
        pending_question = agent_result.get("pending_question", "请提供更多信息")
        new_state_snapshot = agent_result.get("state_snapshot", {})

        state_store.save_agent_state(project_id, new_state_snapshot)
        state_store.save_pending_question(project_id, pending_question)

        async with AsyncSessionLocal() as session:
            await job_service.update_job_step(
                session,
                job_id,
                JobStep.WAITING_USER,
                50,
                f"AI 继续追问：{pending_question[:80]}",
            )
            await session.commit()

        logger.info(
            "[Pipeline] Still waiting for user: project_id={} question={}",
            project_id,
            pending_question[:100],
        )
        return

    if agent_status == "error":
        error_msg = f"AI 生成失败: {agent_result.get('error', '未知错误')}"
        async with AsyncSessionLocal() as session:
            await job_service.mark_job_failed(session, job_id, error_msg)
            await project_service.update_project_status(
                session, project_id, ProjectStatus.FAILED.value
            )
            await session.commit()
        raise RuntimeError(error_msg)

    # 信息完整，进入后续步骤
    full_scene_data: dict = agent_result.get("full_scene_data") or {}

    # ── 脚本生成 ──────────────────────────────────────────────────────────────
    async with AsyncSessionLocal() as session:
        await job_service.update_job_step(
            session, job_id, JobStep.SCRIPT_GENERATION, 60, "开始生成 MAXScript"
        )
        await project_service.update_project_status(
            session, project_id, ProjectStatus.GENERATING.value
        )
        await session.commit()

    script_dir = settings.storage_path / str(project_id) / "scripts"
    script_dir.mkdir(parents=True, exist_ok=True)
    max_dir = settings.storage_path / str(project_id) / "max"
    max_dir.mkdir(parents=True, exist_ok=True)

    scene_json_path = settings.storage_path / str(project_id) / "scene.json"
    script_path = str(script_dir / "scene.ms")
    output_max_path = str(max_dir / "scene.max")

    try:
        with open(scene_json_path, "w", encoding="utf-8") as f:
            json.dump(full_scene_data, f, ensure_ascii=False, indent=2)
    except Exception as exc:
        logger.warning("[Pipeline] Failed to save scene JSON: {}", exc)

    try:
        generator = SceneScriptGenerator()
        generator.generate(
            scene_data=full_scene_data,
            output_script_path=script_path,
            output_max_path=output_max_path,
        )
        logger.info("[Pipeline] MAXScript generated: {}", script_path)
    except Exception as exc:
        error_msg = f"脚本生成失败: {exc}"
        async with AsyncSessionLocal() as session:
            await job_service.mark_job_failed(session, job_id, error_msg)
            await project_service.update_project_status(
                session, project_id, ProjectStatus.FAILED.value
            )
            await session.commit()
        raise RuntimeError(error_msg) from exc

    # ── max_worker 执行 ────────────────────────────────────────────────────────
    async with AsyncSessionLocal() as session:
        await job_service.update_job_step(
            session, job_id, JobStep.MAX_EXECUTION, 75, "提交脚本到 3ds Max Worker"
        )
        await project_service.update_project_status(
            session, project_id, ProjectStatus.EXPORTING.value
        )
        await session.commit()

    try:
        submit_result = await max_client.execute_script(
            script_path=script_path,
            output_max_path=output_max_path,
            timeout=settings.celery_task_soft_time_limit,
        )
        max_task_id: str = submit_result["task_id"]

        final_status = await max_client.wait_for_completion(
            task_id=max_task_id,
            poll_interval=5.0,
            timeout=float(settings.celery_task_soft_time_limit),
        )

        if final_status.get("status") != "completed":
            err_text = (
                final_status.get("error_message")
                or final_status.get("error")
                or "未知错误"
            )
            stderr_tail = (final_status.get("stderr") or "")[-800:]
            rc = final_status.get("return_code")
            detail = f"{err_text} (rc={rc})" if rc is not None else err_text
            if stderr_tail:
                detail = f"{detail} | stderr: {stderr_tail}"
            raise RuntimeError(f"max_worker 执行失败: {detail}")

        actual_max_path = final_status.get("output_max_path") or output_max_path

        # 同 run_full_pipeline：worker 写到 Windows 本地磁盘，必须拉回 backend 本地
        try:
            local_artifact = await max_client.download_artifact(
                task_id=max_task_id,
                dest_path=output_max_path,
            )
            actual_max_path = str(local_artifact)
            logger.info(
                "[Pipeline] Artifact saved locally: {}", actual_max_path
            )
        except Exception as exc:
            error_msg = f"拉取 .max 产物失败: {exc}"
            logger.error("[Pipeline] {}", error_msg)
            async with AsyncSessionLocal() as session:
                await job_service.mark_job_failed(session, job_id, error_msg)
                await project_service.update_project_status(
                    session, project_id, ProjectStatus.FAILED.value
                )
                await session.commit()
            raise RuntimeError(error_msg) from exc

    except Exception as exc:
        error_msg = f"3ds Max 执行失败: {exc}"
        async with AsyncSessionLocal() as session:
            await job_service.mark_job_failed(session, job_id, error_msg)
            await project_service.update_project_status(
                session, project_id, ProjectStatus.FAILED.value
            )
            await session.commit()
        raise RuntimeError(error_msg) from exc

    # ── 完成 ──────────────────────────────────────────────────────────────────
    async with AsyncSessionLocal() as session:
        await project_service.update_project_paths(
            session,
            project_id,
            scene_json_path=str(scene_json_path),
            max_file_path=actual_max_path,
        )
        await project_service.update_project_status(
            session, project_id, ProjectStatus.COMPLETED.value
        )
        await job_service.mark_job_completed(session, job_id)
        await session.commit()

    state_store.cleanup_project(project_id)

    logger.success(
        "[Pipeline] continue_pipeline COMPLETED: project_id={} job_id={}",
        project_id,
        job_id,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# 任务三：仅 CAD 解析（用于预览）
# ═══════════════════════════════════════════════════════════════════════════════


@celery_app.task(
    name="tasks.cad_parse_only",
    queue="cad",
    acks_late=True,
)
def cad_parse_only(project_id: int, cad_file_path: str) -> dict:
    """
    仅做 CAD 解析，不运行 Agent，用于前端预览识别结果。

    Args:
        project_id:    项目 ID（用于缓存结果到 Redis）。
        cad_file_path: CAD 文件路径。

    Returns:
        CADParseResult.to_dict() 的输出，包含 summary。
    """
    logger.info(
        "[Pipeline] cad_parse_only: project_id={} file={}", project_id, cad_file_path
    )
    try:
        result = asyncio.run(_cad_parse_only_async(project_id, cad_file_path))
        return result
    except Exception as exc:
        logger.error(
            "[Pipeline] cad_parse_only failed: project_id={} error={}", project_id, exc
        )
        raise


async def _cad_parse_only_async(project_id: int, cad_file_path: str) -> dict:
    """cad_parse_only 的 async 实现体。"""
    from app.services.cad_parser.cad_pipeline import CADPipeline

    state_store = _get_state_store()

    # 检查 Redis 缓存
    cached = state_store.load_cad_result(project_id)
    if cached is not None:
        logger.info(
            "[Pipeline] cad_parse_only: using cached result for project {}", project_id
        )
        return cached

    # 执行解析
    pipeline = CADPipeline()
    cad_result = await pipeline.process(cad_file_path)
    result_dict = cad_result.to_dict()

    # 写入缓存
    try:
        state_store.save_cad_result(project_id, result_dict)
    except Exception as exc:
        logger.warning("[Pipeline] Failed to cache CAD result: {}", exc)

    logger.info(
        "[Pipeline] cad_parse_only done: walls={} rooms={}",
        result_dict.get("summary", {}).get("wall_count", 0),
        result_dict.get("summary", {}).get("room_count", 0),
    )
    return result_dict


# ── 内部辅助：安全标记失败 ────────────────────────────────────────────────────


async def _mark_failed_in_db(
    project_id: int,
    job_id: Optional[int],
    error: str,
) -> None:
    """在 Celery 重试耗尽时，尝试将 DB 中的 job/project 标记为失败。"""
    try:
        from app.database import AsyncSessionLocal
        from app.models.project import ProjectStatus
        from app.services.job_service import job_service
        from app.services.project_service import project_service

        async with AsyncSessionLocal() as session:
            if job_id is not None:
                await job_service.mark_job_failed(session, job_id, error)
            await project_service.update_project_status(
                session, project_id, ProjectStatus.FAILED.value
            )
            await session.commit()
    except Exception as exc:
        logger.error(
            "[Pipeline] Failed to mark job as failed in DB: project_id={} error={}",
            project_id,
            exc,
        )

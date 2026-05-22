"""
Celery 初始化模块。

使用 Redis 作为 broker 和 result backend。
任务模块在此集中注册，Worker 启动时自动发现。
"""

from __future__ import annotations

from celery import Celery
from celery.signals import worker_ready
from kombu import Queue

from app.config import get_settings

settings = get_settings()

# ── 创建 Celery 实例 ──────────────────────────────────────────────────────────
celery_app = Celery(
    "cad_agent",
    broker=settings.redis_url,
    backend=settings.redis_url,
    include=[
        "app.tasks.pipeline_tasks",
    ],
)

# ── 配置 ─────────────────────────────────────────────────────────────────────
celery_app.conf.update(
    # 序列化
    task_serializer="json",
    result_serializer="json",
    accept_content=["json"],
    # 时区
    timezone="Asia/Shanghai",
    enable_utc=True,
    # 结果存活时间：24 小时
    result_expires=86400,
    # 软 / 硬超时
    task_soft_time_limit=settings.celery_task_soft_time_limit,
    task_time_limit=settings.celery_task_time_limit,
    # 重试策略
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    worker_prefetch_multiplier=1,
    # 队列定义
    task_queues=(
        Queue("default"),
        Queue("cad"),  # CAD 解析专用队列
        Queue("ai"),  # AI 推理专用队列
        Queue("max_export"),  # 3ds Max 导出专用队列
    ),
    task_default_queue="default",
    task_routes={
        "tasks.run_full_pipeline": {"queue": "cad"},
        "tasks.cad_parse_only": {"queue": "cad"},
        "tasks.continue_pipeline": {"queue": "ai"},
    },
    # Flower 监控需要
    worker_send_task_events=True,
    task_send_sent_event=True,
)


@worker_ready.connect
def on_worker_ready(sender, **kwargs):  # type: ignore[no-untyped-def]
    """Worker 就绪时打印日志"""
    from app.utils.logger import get_logger

    logger = get_logger(__name__)
    logger.info("Celery worker is ready. Queues: cad / ai / max_export / default")

"""
日志配置模块 —— 基于 loguru，提供结构化日志与文件轮转。
"""

from __future__ import annotations

import sys
from pathlib import Path

from loguru import logger


def setup_logging(
    debug: bool = False,
    log_dir: Path | None = None,
    rotation: str = "100 MB",
    retention: str = "30 days",
    compression: str = "zip",
) -> None:
    """
    初始化全局 loguru 日志配置。

    Args:
        debug:       True 时输出 DEBUG 级别；否则 INFO。
        log_dir:     日志文件目录。None 时仅输出到 stderr。
        rotation:    日志文件轮转触发条件（大小或时间）。
        retention:   旧日志保留时长。
        compression: 压缩格式。
    """
    # 移除默认 handler
    logger.remove()

    level = "DEBUG" if debug else "INFO"

    # ── stderr 输出（带颜色） ─────────────────────────────────────────────
    logger.add(
        sys.stderr,
        level=level,
        colorize=True,
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{name}</cyan>:<cyan>{function}</cyan>:<cyan>{line}</cyan> | "
            "<level>{message}</level>"
        ),
        backtrace=debug,
        diagnose=debug,
    )

    # ── 文件输出（JSON 格式，便于日志收集系统解析） ─────────────────────
    if log_dir is not None:
        log_dir = Path(log_dir)
        log_dir.mkdir(parents=True, exist_ok=True)

        # 普通日志
        logger.add(
            log_dir / "app_{time:YYYY-MM-DD}.log",
            level=level,
            rotation=rotation,
            retention=retention,
            compression=compression,
            encoding="utf-8",
            serialize=True,  # JSON 格式
            backtrace=True,
            diagnose=False,  # 生产环境关闭变量值打印
        )

        # 仅错误日志单独存储
        logger.add(
            log_dir / "error_{time:YYYY-MM-DD}.log",
            level="ERROR",
            rotation=rotation,
            retention=retention,
            compression=compression,
            encoding="utf-8",
            serialize=True,
            backtrace=True,
            diagnose=False,
        )

    logger.info(
        "Logging initialized | level={} | file_output={}",
        level,
        str(log_dir) if log_dir else "disabled",
    )


def get_logger(name: str):  # type: ignore[return]
    """
    获取带模块名绑定的 logger 实例。

    Usage::

        logger = get_logger(__name__)
        logger.info("Hello from {}", __name__)
    """
    return logger.bind(module=name)

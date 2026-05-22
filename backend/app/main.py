"""
FastAPI 应用主入口。

职责：
  - 创建 FastAPI 实例
  - 配置 CORS
  - 挂载所有 API 路由
  - 注册全局异常处理器
  - 管理应用生命周期（startup / shutdown）
"""

from __future__ import annotations

import time
import traceback
from contextlib import asynccontextmanager
from typing import Any

from app.api.router import api_router
from app.config import get_settings
from app.utils.logger import setup_logging
from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from loguru import logger

settings = get_settings()


# ── 生命周期管理 ──────────────────────────────────────────────────────────────
@asynccontextmanager
async def lifespan(app: FastAPI):  # type: ignore[type-arg]
    """应用启动 / 关闭时执行的逻辑"""
    # ── Startup ──────────────────────────────────────────
    setup_logging(debug=settings.debug)
    settings.ensure_storage_dirs()
    logger.info("Storage directories initialized at: {}", settings.storage_path)
    logger.info(
        "CAD-to-MAX Agent backend starting up | debug={} | model={}",
        settings.debug,
        settings.default_model,
    )
    yield
    # ── Shutdown ─────────────────────────────────────────
    logger.info("CAD-to-MAX Agent backend shutting down.")


# ── 应用实例 ──────────────────────────────────────────────────────────────────
app = FastAPI(
    title="CAD-to-MAX Agent API",
    description=(
        "将建筑 CAD 图纸自动转换为 3ds Max 三维场景的智能体后端服务。\n\n"
        "支持 DWG/DXF 解析 → AI 理解 → 场景生成 → 3ds Max 自动化建模全流程。"
    ),
    version="0.1.0",
    docs_url="/docs" if settings.debug else None,
    redoc_url="/redoc" if settings.debug else None,
    lifespan=lifespan,
)


# ── CORS ──────────────────────────────────────────────────────────────────────
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# ── 请求耗时中间件 ────────────────────────────────────────────────────────────
@app.middleware("http")
async def add_process_time_header(request: Request, call_next: Any) -> Any:
    start = time.perf_counter()
    response = await call_next(request)
    elapsed = (time.perf_counter() - start) * 1000
    response.headers["X-Process-Time-Ms"] = f"{elapsed:.2f}"
    return response


# ── 全局异常处理 ──────────────────────────────────────────────────────────────
@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    """将 Pydantic 验证错误格式化为统一 JSON 响应"""
    logger.warning(
        "Validation error on {} {}: {}", request.method, request.url, exc.errors()
    )
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "code": 422,
            "message": "请求参数验证失败",
            "errors": exc.errors(),
        },
    )


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    """捕获所有未处理异常，避免堆栈暴露给客户端"""
    logger.error(
        "Unhandled exception on {} {}\n{}",
        request.method,
        request.url,
        traceback.format_exc(),
    )
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "code": 500,
            "message": "服务器内部错误，请稍后重试",
            "detail": str(exc) if settings.debug else None,
        },
    )


# ── 路由挂载 ──────────────────────────────────────────────────────────────────
app.include_router(api_router, prefix="/api/v1")


# ── 健康检查 ──────────────────────────────────────────────────────────────────
@app.get("/health", tags=["系统"], summary="健康检查")
async def health_check() -> dict[str, str]:
    return {"status": "ok", "version": app.version}

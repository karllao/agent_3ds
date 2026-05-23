"""
max_worker/worker_service.py
-----------------------------
运行在安装了 3ds Max 的 Windows 机器上的 FastAPI 微服务。

功能：
  POST /execute        接收 MAXScript 文件路径，异步启动 3dsmaxbatch.exe 执行
  GET  /status/{id}    查询任务执行状态
  GET  /health         健康检查

启动方式：
  python -m uvicorn max_worker.worker_service:app --host 0.0.0.0 --port 8765

  或直接运行：
  python max_worker/worker_service.py
"""

from __future__ import annotations

import asyncio
import os
import shutil
import sys
import time
import uuid
from enum import Enum
from pathlib import Path
from typing import Any

import config as cfg
import uvicorn
from fastapi import Depends, FastAPI, HTTPException, Security, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from loguru import logger
from pydantic import BaseModel, Field

# ---------------------------------------------------------------------------
# 日志配置
# ---------------------------------------------------------------------------

logger.remove()
logger.add(
    sys.stderr,
    level=cfg.LOG_LEVEL,
    format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | "
    "<level>{level: <8}</level> | "
    "<cyan>{name}</cyan>:<cyan>{line}</cyan> - <level>{message}</level>",
)
logger.add(
    Path(cfg.WORK_DIR) / "worker.log",
    level="DEBUG",
    rotation="10 MB",
    retention="7 days",
    encoding="utf-8",
)

# ---------------------------------------------------------------------------
# 任务状态枚举
# ---------------------------------------------------------------------------


class TaskStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    TIMEOUT = "timeout"


# ---------------------------------------------------------------------------
# Pydantic 模型
# ---------------------------------------------------------------------------


class ExecuteRequest(BaseModel):
    """POST /execute 请求体。"""

    script_content: str = Field(
        default="",
        description=(
            "MAXScript 文本内容。若提供则 worker 会写到本地 WORK_DIR 再执行，"
            "这是跨机器部署（backend 在 Linux 容器、worker 在 Windows）的推荐方式。"
        ),
    )
    script_basename: str = Field(
        default="scene.ms",
        description="落地的脚本文件名（仅 basename，不含路径）",
    )
    script_path: str = Field(
        default="",
        description=(
            "兼容字段：本机已存在的 MAXScript 路径。仅当 script_content 为空时使用。"
        ),
        examples=[r"C:\output\scene.ms"],
    )
    output_max_path: str = Field(
        default="",
        description=(
            "3ds Max 输出 .max 文件路径或文件名。若为相对/无路径，则落地到 WORK_DIR 下"
        ),
        examples=[r"C:\output\scene.max", "scene.max"],
    )
    embedded_output_max_path: str = Field(
        default="",
        description=(
            "脚本内 saveMaxFile 嵌入的原始路径（通常是 backend 侧的 Linux 路径）。"
            "worker 写入脚本前会把它字符串替换成本机的实际输出路径。"
        ),
    )
    timeout_seconds: int = Field(
        default=cfg.TIMEOUT_SECONDS,
        ge=10,
        le=3600,
        description="本次任务超时时间（秒），覆盖全局配置",
    )
    extra_args: list[str] = Field(
        default_factory=list,
        description="传递给 3dsmaxbatch.exe 的额外命令行参数",
    )


class ExecuteResponse(BaseModel):
    """POST /execute 响应体。"""

    task_id: str
    status: TaskStatus
    message: str


class TaskInfo(BaseModel):
    """GET /status/{task_id} 响应体。"""

    task_id: str
    status: TaskStatus
    script_path: str
    output_max_path: str
    start_time: float
    end_time: float | None
    elapsed_seconds: float | None
    return_code: int | None
    stdout: str
    stderr: str
    error_message: str


class HealthResponse(BaseModel):
    """GET /health 响应体。"""

    status: str
    max_exe_exists: bool
    max_exe_path: str
    work_dir: str
    active_tasks: int
    total_tasks: int
    version: str = "1.0.0"


# ---------------------------------------------------------------------------
# 任务存储（内存）
# ---------------------------------------------------------------------------

# task_id -> TaskInfo dict（运行时状态，重启后丢失）
_task_store: dict[str, dict[str, Any]] = {}

# 当前活跃进程计数（信号量）
_semaphore: asyncio.Semaphore | None = None


def get_semaphore() -> asyncio.Semaphore:
    global _semaphore
    if _semaphore is None:
        _semaphore = asyncio.Semaphore(cfg.MAX_CONCURRENT_TASKS)
    return _semaphore


# ---------------------------------------------------------------------------
# FastAPI 应用
# ---------------------------------------------------------------------------

app = FastAPI(
    title="3ds Max Worker Service",
    description="在 Windows 机器上异步执行 MAXScript 的微服务",
    version="1.0.0",
    docs_url="/docs",
    redoc_url="/redoc",
)

_bearer_scheme = HTTPBearer(auto_error=False)


def verify_token(
    credentials: HTTPAuthorizationCredentials | None = Security(_bearer_scheme),
) -> None:
    """验证 Bearer Token（若配置为空则跳过）。"""
    if not cfg.SECRET_TOKEN:
        return  # 开发模式：跳过认证
    if credentials is None or credentials.credentials != cfg.SECRET_TOKEN:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or missing Bearer token",
            headers={"WWW-Authenticate": "Bearer"},
        )


# ---------------------------------------------------------------------------
# 路由
# ---------------------------------------------------------------------------


@app.get("/health", response_model=HealthResponse, tags=["System"])
async def health_check() -> HealthResponse:
    """健康检查端点，无需认证。"""
    max_exe_exists = Path(cfg.MAX_EXE_PATH).exists()
    active_tasks = sum(
        1
        for t in _task_store.values()
        if t["status"] in (TaskStatus.PENDING, TaskStatus.RUNNING)
    )
    return HealthResponse(
        status="ok" if max_exe_exists else "degraded",
        max_exe_exists=max_exe_exists,
        max_exe_path=cfg.MAX_EXE_PATH,
        work_dir=cfg.WORK_DIR,
        active_tasks=active_tasks,
        total_tasks=len(_task_store),
    )


@app.post(
    "/execute",
    response_model=ExecuteResponse,
    status_code=status.HTTP_202_ACCEPTED,
    tags=["Tasks"],
)
async def execute_maxscript(
    request: ExecuteRequest,
    _: None = Depends(verify_token),
) -> ExecuteResponse:
    """
    接收 MAXScript（文本内容或本机路径），在后台异步启动 3dsmaxbatch.exe 执行。

    - 立即返回 task_id
    - 通过 GET /status/{task_id} 轮询结果
    """
    # 检查 3dsmaxbatch.exe 是否存在
    if not Path(cfg.MAX_EXE_PATH).exists():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail=f"3dsmaxbatch.exe not found at: {cfg.MAX_EXE_PATH}",
        )

    # 提前生成 task_id，方便用作工作子目录名
    task_id = str(uuid.uuid4())
    task_workdir = Path(cfg.WORK_DIR) / task_id
    task_workdir.mkdir(parents=True, exist_ok=True)

    # ── 先解析输出路径（写脚本时需要做路径替换）──────────────────
    # 如果 output_max_path 是绝对路径且其所在目录在本机存在 → 用它
    # 否则取 basename 落到 task_workdir 下
    raw_out = (request.output_max_path or "scene.max").strip()
    out_path_obj = Path(raw_out)
    if out_path_obj.is_absolute() and out_path_obj.parent.exists():
        output_max_path = str(out_path_obj.resolve())
    else:
        out_name = out_path_obj.name or "scene.max"
        if not out_name.lower().endswith(".max"):
            out_name += ".max"
        output_max_path = str(task_workdir / out_name)

    # ── 解析脚本来源 ────────────────────────────────────────────
    if request.script_content:
        # 跨机器场景：内容已在请求里，落地到本地
        basename = request.script_basename or "scene.ms"
        if not basename.lower().endswith((".ms", ".mse", ".mcr")):
            basename += ".ms"
        script_path = task_workdir / basename

        # 脚本里 backend 嵌入的 Linux 路径替换成本机 Windows 路径
        # （MAXScript 用 @"..." 字面字符串，所以单一引号字符串替换就够）
        content = request.script_content
        if request.embedded_output_max_path:
            old = request.embedded_output_max_path
            new = output_max_path
            if old in content:
                content = content.replace(old, new)
                logger.info(
                    f"Rewrote embedded output path: {old!r} → {new!r}"
                )
            else:
                logger.warning(
                    f"Embedded output path not found in script "
                    f"(maybe already replaced): {old!r}"
                )

        try:
            script_path.write_text(content, encoding="utf-8")
        except OSError as exc:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail=f"Failed to write script to {script_path}: {exc}",
            )
        logger.info(
            f"Script written to local workdir: {script_path} "
            f"({len(content)} chars)"
        )
    elif request.script_path:
        # 兼容模式：本机已有脚本文件
        script_path = Path(request.script_path)
        if not script_path.exists():
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Script file not found: {request.script_path}",
            )
        if script_path.suffix.lower() not in (".ms", ".mse", ".mcr"):
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Script file must have extension .ms, .mse, or .mcr",
            )
    else:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Either 'script_content' or 'script_path' must be provided",
        )

    # 创建任务
    task: dict[str, Any] = {
        "task_id": task_id,
        "status": TaskStatus.PENDING,
        "script_path": str(script_path.resolve()),
        "output_max_path": output_max_path,
        "start_time": time.time(),
        "end_time": None,
        "elapsed_seconds": None,
        "return_code": None,
        "stdout": "",
        "stderr": "",
        "error_message": "",
        "timeout_seconds": request.timeout_seconds,
        "extra_args": request.extra_args,
    }
    _task_store[task_id] = task
    logger.info(
        f"Task created: {task_id} | script={script_path} | out={output_max_path}"
    )

    # 异步后台执行
    asyncio.create_task(_run_maxscript_task(task_id))

    return ExecuteResponse(
        task_id=task_id,
        status=TaskStatus.PENDING,
        message=f"Task accepted. Poll /status/{task_id} for result.",
    )


@app.get(
    "/status/{task_id}",
    response_model=TaskInfo,
    tags=["Tasks"],
)
async def get_task_status(
    task_id: str,
    _: None = Depends(verify_token),
) -> TaskInfo:
    """查询任务状态。"""
    if task_id not in _task_store:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Task not found: {task_id}",
        )
    task = _task_store[task_id]
    elapsed = None
    if task["start_time"]:
        end = task["end_time"] or time.time()
        elapsed = round(end - task["start_time"], 2)

    return TaskInfo(
        task_id=task_id,
        status=task["status"],
        script_path=task["script_path"],
        output_max_path=task["output_max_path"],
        start_time=task["start_time"],
        end_time=task["end_time"],
        elapsed_seconds=elapsed,
        return_code=task["return_code"],
        stdout=task["stdout"][-4000:],  # 最多返回 4000 字符
        stderr=task["stderr"][-4000:],
        error_message=task["error_message"],
    )


@app.get("/tasks", tags=["Tasks"])
async def list_tasks(
    limit: int = 20,
    _: None = Depends(verify_token),
) -> list[dict[str, Any]]:
    """列出最近的任务（按开始时间倒序）。"""
    tasks = sorted(
        _task_store.values(),
        key=lambda t: t["start_time"],
        reverse=True,
    )
    return [
        {
            "task_id": t["task_id"],
            "status": t["status"],
            "script_path": t["script_path"],
            "start_time": t["start_time"],
            "elapsed_seconds": (
                round((t["end_time"] or time.time()) - t["start_time"], 2)
                if t["start_time"]
                else None
            ),
        }
        for t in tasks[:limit]
    ]


# ---------------------------------------------------------------------------
# 后台执行逻辑
# ---------------------------------------------------------------------------


async def _run_maxscript_task(task_id: str) -> None:
    """
    后台协程：
    1. 获取信号量（限制并发数）
    2. 调用 3dsmaxbatch.exe
    3. 等待完成或超时
    4. 更新任务状态
    """
    task = _task_store[task_id]
    sem = get_semaphore()

    async with sem:
        task["status"] = TaskStatus.RUNNING
        task["start_time"] = time.time()
        logger.info(f"Task started: {task_id}")

        cmd = _build_command(task)
        logger.debug(f"Command: {' '.join(cmd)}")

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                # 在 Windows 上创建新进程组，以便超时时可以整体终止
                creationflags=(
                    0x00000200  # CREATE_NEW_PROCESS_GROUP
                    if sys.platform == "win32"
                    else 0
                ),
            )

            timeout = task["timeout_seconds"]
            try:
                stdout_bytes, stderr_bytes = await asyncio.wait_for(
                    proc.communicate(),
                    timeout=float(timeout),
                )
                return_code = proc.returncode
                task["return_code"] = return_code
                task["stdout"] = stdout_bytes.decode("utf-8", errors="replace")
                task["stderr"] = stderr_bytes.decode("utf-8", errors="replace")

                if return_code == 0:
                    task["status"] = TaskStatus.COMPLETED
                    logger.success(f"Task completed: {task_id} | rc={return_code}")
                else:
                    task["status"] = TaskStatus.FAILED
                    task["error_message"] = (
                        f"3dsmaxbatch exited with code {return_code}"
                    )
                    logger.error(
                        f"Task failed: {task_id} | rc={return_code} | "
                        f"stderr={task['stderr'][:500]}"
                    )

            except asyncio.TimeoutError:
                logger.warning(f"Task timeout: {task_id} | limit={timeout}s")
                # 强制终止进程树
                try:
                    if sys.platform == "win32":
                        # Windows: 用 taskkill 终止整个进程组
                        os.system(f"taskkill /F /T /PID {proc.pid}")
                    else:
                        proc.kill()
                    await proc.wait()
                except Exception as kill_err:
                    logger.error(f"Failed to kill process: {kill_err}")

                task["status"] = TaskStatus.TIMEOUT
                task["error_message"] = f"Task timed out after {timeout}s"

        except FileNotFoundError:
            task["status"] = TaskStatus.FAILED
            task["error_message"] = f"3dsmaxbatch.exe not found: {cfg.MAX_EXE_PATH}"
            logger.error(task["error_message"])

        except Exception as exc:
            task["status"] = TaskStatus.FAILED
            task["error_message"] = f"Unexpected error: {exc}"
            logger.exception(f"Task exception: {task_id}")

        finally:
            task["end_time"] = time.time()
            elapsed = round(task["end_time"] - task["start_time"], 2)
            task["elapsed_seconds"] = elapsed
            logger.info(
                f"Task finished: {task_id} | "
                f"status={task['status']} | elapsed={elapsed}s"
            )


def _build_command(task: dict[str, Any]) -> list[str]:
    """
    构造 3dsmaxbatch.exe 命令行参数。

    3dsmaxbatch.exe 用法要点：
      - 直接执行 MAXScript 文件用 `-mxsString "fileIn @path"`
        （`-sceneFile` 是给 .max 场景文件用的，不能用来执行 .ms 脚本，
         否则 3dsmaxbatch 会立即以 rc=-100 退出）
      - `-mip`        以批处理模式启动，不弹任何 UI
      - `-v <level>`  日志详细级别 (0-5)
      - `-outputName` 仅在用 `-sceneFile` 加载场景时有意义；本场景中脚本
                      自己调用 saveMaxFile，不需要这个参数
    """
    script_path = task["script_path"]
    # MAXScript 字符串字面量 @"..." 里反斜杠不需要转义，唯一要转的是 "
    # 我们用 @"..." 包裹路径
    mxs_path = script_path.replace('"', '\\"')
    mxs_string = f'fileIn @"{mxs_path}"'

    cmd: list[str] = [
        cfg.MAX_EXE_PATH,
        "-mip",
        "-v",
        "5",
        "-mxsString",
        mxs_string,
    ]

    # 追加用户自定义参数
    cmd += task.get("extra_args", [])

    return cmd


# ---------------------------------------------------------------------------
# 启动入口
# ---------------------------------------------------------------------------


@app.on_event("startup")
async def on_startup() -> None:
    cfg.print_config()
    logger.info(f"max_worker started. Listening on {cfg.HOST}:{cfg.PORT}")

    # 检查 3dsmaxbatch.exe
    if not Path(cfg.MAX_EXE_PATH).exists():
        logger.warning(
            f"3dsmaxbatch.exe NOT FOUND at: {cfg.MAX_EXE_PATH}\n"
            "  Update MAX_EXE_PATH in .env before submitting tasks."
        )
    else:
        logger.info(f"3dsmaxbatch.exe found: {cfg.MAX_EXE_PATH}")


@app.on_event("shutdown")
async def on_shutdown() -> None:
    logger.info("max_worker shutting down.")


if __name__ == "__main__":
    uvicorn.run(
        "worker_service:app",
        host=cfg.HOST,
        port=cfg.PORT,
        reload=False,  # 生产环境不使用 reload
        log_level=cfg.LOG_LEVEL.lower(),
        access_log=True,
    )

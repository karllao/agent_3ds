"""
max_worker/config.py
--------------------
从环境变量（或 .env 文件）读取 max_worker 运行时配置。

使用 python-dotenv 自动加载同目录下的 .env 文件。
"""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

# 加载 .env 文件（相对于本文件的目录）
_env_path = Path(__file__).parent / ".env"
load_dotenv(dotenv_path=_env_path, override=False)


# ---------------------------------------------------------------------------
# 3ds Max 可执行文件路径
# ---------------------------------------------------------------------------

MAX_EXE_PATH: str = os.getenv(
    "MAX_EXE_PATH",
    r"C:\Program Files\Autodesk\3ds Max 2024\3dsmaxbatch.exe",
)
"""
3dsmaxbatch.exe 的完整路径。
若安装了多个版本，指向需要使用的版本。
常见路径：
  - 2024: C:\\Program Files\\Autodesk\\3ds Max 2024\\3dsmaxbatch.exe
  - 2023: C:\\Program Files\\Autodesk\\3ds Max 2023\\3dsmaxbatch.exe
  - 2022: C:\\Program Files\\Autodesk\\3ds Max 2022\\3dsmaxbatch.exe
"""

# ---------------------------------------------------------------------------
# 工作目录（脚本输入 / 输出临时文件存放位置）
# ---------------------------------------------------------------------------

WORK_DIR: str = os.getenv(
    "WORK_DIR",
    str(Path(__file__).parent / "workdir"),
)
"""
max_worker 的工作目录：
  - 接收到的 .ms 脚本文件缓存于此
  - 3ds Max 输出的 .max 文件也存放于此（可通过脚本中的 output_max_path 覆盖）
"""

# 确保工作目录存在
Path(WORK_DIR).mkdir(parents=True, exist_ok=True)

# ---------------------------------------------------------------------------
# 执行超时（秒）
# ---------------------------------------------------------------------------

TIMEOUT_SECONDS: int = int(os.getenv("TIMEOUT", "300"))
"""
单个 MAXScript 任务的最大执行时间（秒）。
超时后 worker 会强制终止 3dsmaxbatch.exe 进程，任务状态标记为 "failed"。
默认 300 秒（5 分钟）。
"""

# ---------------------------------------------------------------------------
# 服务监听配置
# ---------------------------------------------------------------------------

HOST: str = os.getenv("HOST", "0.0.0.0")
PORT: int = int(os.getenv("PORT", "8765"))
"""
max_worker FastAPI 服务的监听地址和端口。
建议仅在局域网内暴露，不要直接对公网开放。
"""

# ---------------------------------------------------------------------------
# API 认证 Token
# ---------------------------------------------------------------------------

SECRET_TOKEN: str = os.getenv("SECRET_TOKEN", "")
"""
简单的 Bearer Token 认证。
若为空字符串，则跳过认证（仅用于开发/测试环境）。
生产环境必须设置非空值。
"""

# ---------------------------------------------------------------------------
# 并发任务限制
# ---------------------------------------------------------------------------

MAX_CONCURRENT_TASKS: int = int(os.getenv("MAX_CONCURRENT_TASKS", "2"))
"""
同时运行的 3ds Max 任务数量上限。
3ds Max 是重量级进程，建议不超过机器 CPU 核心数 / 4。
"""

# ---------------------------------------------------------------------------
# 日志级别
# ---------------------------------------------------------------------------

LOG_LEVEL: str = os.getenv("LOG_LEVEL", "INFO").upper()
"""
日志级别：DEBUG | INFO | WARNING | ERROR | CRITICAL
"""

# ---------------------------------------------------------------------------
# 汇总打印（启动时显示）
# ---------------------------------------------------------------------------


def print_config() -> None:
    """在服务启动时打印当前配置摘要（隐藏 SECRET_TOKEN 实际值）。"""
    token_display = "*** (set)" if SECRET_TOKEN else "(empty - auth disabled)"
    print(
        f"\n{'=' * 60}\n"
        f"  max_worker Configuration\n"
        f"{'=' * 60}\n"
        f"  MAX_EXE_PATH         : {MAX_EXE_PATH}\n"
        f"  WORK_DIR             : {WORK_DIR}\n"
        f"  TIMEOUT_SECONDS      : {TIMEOUT_SECONDS}s\n"
        f"  HOST                 : {HOST}\n"
        f"  PORT                 : {PORT}\n"
        f"  SECRET_TOKEN         : {token_display}\n"
        f"  MAX_CONCURRENT_TASKS : {MAX_CONCURRENT_TASKS}\n"
        f"  LOG_LEVEL            : {LOG_LEVEL}\n"
        f"{'=' * 60}\n"
    )

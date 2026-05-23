"""
3ds Max Worker HTTP 客户端。

负责与独立运行的 max_worker 服务通信，提交脚本执行任务、
轮询任务状态、健康检查。

max_worker 接口约定：
  POST /execute      → { task_id, status }
  GET  /status/{id}  → { task_id, status, output_max_path, error, started_at, completed_at }
  GET  /health       → { status: "ok" }
"""

from __future__ import annotations

import asyncio
import time
from pathlib import Path
from typing import Optional

import httpx
from loguru import logger

# max_worker 任务最终状态
# 注意：必须与 max_worker/worker_service.py::TaskStatus 枚举的终态保持一致。
# max_worker 用 "timeout" 表示 3dsmaxbatch 超过执行时限后被强制终止，
# 也是终态——漏掉它会让 backend 一直 polling，前端误显示"运行中"。
_TERMINAL_STATUSES = {"completed", "failed", "error", "cancelled", "timeout"}


class MaxWorkerError(Exception):
    """max_worker 交互中发生的通用错误。"""


class MaxWorkerClient:
    """
    HTTP 客户端，调用 max_worker 服务。

    使用 httpx.AsyncClient 发送异步 HTTP 请求。
    所有网络异常均转换为 MaxWorkerError，便于上层统一处理。

    Args:
        base_url:     max_worker 服务基础 URL（如 http://localhost:8765）。
        secret_token: 请求鉴权 Token（Bearer），为空时不附加 Authorization 头。
        timeout:      单次 HTTP 请求超时（秒），默认 30。
    """

    def __init__(
        self,
        base_url: str,
        secret_token: str = "",
        timeout: float = 30.0,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._secret_token = secret_token
        self._timeout = timeout

    # ── 内部工具 ──────────────────────────────────────────────────────────────

    def _build_headers(self) -> dict[str, str]:
        headers: dict[str, str] = {"Content-Type": "application/json"}
        if self._secret_token:
            headers["Authorization"] = f"Bearer {self._secret_token}"
        return headers

    def _get_client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(
            base_url=self._base_url,
            headers=self._build_headers(),
            timeout=self._timeout,
        )

    # ── 公开接口 ──────────────────────────────────────────────────────────────

    async def execute_script(
        self,
        script_path: str,
        output_max_path: str,
        timeout: int = 600,
    ) -> dict:
        """
        提交脚本执行任务到 max_worker。

        backend 与 max_worker 通常运行在不同机器（前者 Linux 容器，后者 Windows），
        没有共享文件系统。因此：
          - 把脚本 **文本内容** 一并发过去，让 worker 写到它自己的 WORK_DIR 再执行
          - script_path 仅作为调试/日志用的源路径，worker 不会拿它去打开文件
          - output_max_path 同理：传过去的是 basename，worker 会把 .max 写到它本地

        Args:
            script_path:     backend 侧 .ms 文件的绝对路径（用于读取内容）。
            output_max_path: 期望的 .max 文件路径（worker 端会取其 basename）。
            timeout:         max_worker 端的执行超时（秒）。

        Returns:
            包含 ``task_id`` 和 ``status`` 的字典。

        Raises:
            MaxWorkerError: 读取脚本失败、请求失败或返回非 2xx 状态码。
        """
        # 读取脚本内容（backend 本地路径）
        try:
            with open(script_path, "r", encoding="utf-8") as f:
                script_content = f.read()
        except OSError as exc:
            raise MaxWorkerError(
                f"读取 MAXScript 失败: {script_path} ({exc})"
            ) from exc

        # output 只发文件名，worker 自己决定落地目录
        from pathlib import PurePosixPath, PureWindowsPath

        out_basename = (
            PureWindowsPath(output_max_path).name
            if "\\" in output_max_path
            else PurePosixPath(output_max_path).name
        ) or "scene.max"

        payload = {
            # 新字段：脚本文本（worker 落地到本地后再执行）
            "script_content": script_content,
            "script_basename": (
                PurePosixPath(script_path).name or "scene.ms"
            ),
            # 兼容字段：仍保留路径用于日志
            "script_path": script_path,
            # 期望的输出文件名（worker 自决定落地目录）
            "output_max_path": out_basename,
            # 脚本里 saveMaxFile 嵌入的原始路径（Linux 路径），
            # 让 worker 在写入前把它替换成本机 Windows 路径
            "embedded_output_max_path": output_max_path,
            "timeout_seconds": timeout,
        }
        logger.info(
            "[MaxWorkerClient] Submitting script: src={} ({} chars) → out={}",
            script_path,
            len(script_content),
            out_basename,
        )
        try:
            async with self._get_client() as client:
                response = await client.post("/execute", json=payload)
                response.raise_for_status()
                data: dict = response.json()
                logger.info(
                    "[MaxWorkerClient] Task submitted: task_id={} status={}",
                    data.get("task_id"),
                    data.get("status"),
                )
                return data
        except httpx.HTTPStatusError as exc:
            msg = (
                f"max_worker /execute 返回错误 {exc.response.status_code}: "
                f"{exc.response.text[:500]}"
            )
            logger.error("[MaxWorkerClient] {}", msg)
            raise MaxWorkerError(msg) from exc
        except httpx.RequestError as exc:
            msg = f"max_worker 连接失败: {exc}"
            logger.error("[MaxWorkerClient] {}", msg)
            raise MaxWorkerError(msg) from exc

    async def get_status(self, task_id: str) -> dict:
        """
        查询任务执行状态。

        Args:
            task_id: max_worker 返回的任务 ID。

        Returns:
            包含 task_id、status、output_max_path、error、
            started_at、completed_at 的字典。

        Raises:
            MaxWorkerError: 请求失败。
        """
        try:
            async with self._get_client() as client:
                response = await client.get(f"/status/{task_id}")
                response.raise_for_status()
                return response.json()
        except httpx.HTTPStatusError as exc:
            msg = (
                f"max_worker /status/{task_id} 返回错误 {exc.response.status_code}: "
                f"{exc.response.text[:500]}"
            )
            logger.error("[MaxWorkerClient] {}", msg)
            raise MaxWorkerError(msg) from exc
        except httpx.RequestError as exc:
            msg = f"max_worker 连接失败（get_status）: {exc}"
            logger.error("[MaxWorkerClient] {}", msg)
            raise MaxWorkerError(msg) from exc

    async def wait_for_completion(
        self,
        task_id: str,
        poll_interval: float = 5.0,
        timeout: float = 600.0,
    ) -> dict:
        """
        轮询直到任务变为终态（completed / failed）或超时。

        Args:
            task_id:       max_worker 任务 ID。
            poll_interval: 轮询间隔（秒）。
            timeout:       最大等待时间（秒）。

        Returns:
            最终状态字典（与 get_status 返回格式相同）。

        Raises:
            MaxWorkerError:  查询过程中发生网络错误。
            TimeoutError:    超过 ``timeout`` 仍未完成。
        """
        deadline = time.monotonic() + timeout
        logger.info(
            "[MaxWorkerClient] Waiting for task_id={} (timeout={}s, poll={}s)",
            task_id,
            timeout,
            poll_interval,
        )

        while True:
            status_data = await self.get_status(task_id)
            current_status: str = status_data.get("status", "unknown")

            logger.debug(
                "[MaxWorkerClient] task_id={} status={}", task_id, current_status
            )

            if current_status in _TERMINAL_STATUSES:
                if current_status == "completed":
                    logger.success(
                        "[MaxWorkerClient] Task {} completed: output={}",
                        task_id,
                        status_data.get("output_max_path"),
                    )
                else:
                    # max_worker /status 返回的字段是 error_message；保留旧 "error"
                    # 作为回退，避免 worker 版本不一致时丢失错误信息
                    err = (
                        status_data.get("error_message")
                        or status_data.get("error")
                        or ""
                    )
                    stderr_tail = (status_data.get("stderr") or "")[-1000:]
                    stdout_tail = (status_data.get("stdout") or "")[-500:]
                    logger.error(
                        "[MaxWorkerClient] Task {} ended with status={}: "
                        "error={!r} | stderr_tail={!r} | stdout_tail={!r}",
                        task_id,
                        current_status,
                        err,
                        stderr_tail,
                        stdout_tail,
                    )
                    # 暴露给上层的 dict 也补一份 "error" 别名
                    status_data.setdefault("error", err)
                return status_data

            remaining = deadline - time.monotonic()
            if remaining <= 0:
                msg = (
                    f"max_worker 任务 {task_id} 在 {timeout}s 内未完成，"
                    f"最后状态: {current_status}"
                )
                logger.error("[MaxWorkerClient] Timeout: {}", msg)
                raise TimeoutError(msg)

            await asyncio.sleep(min(poll_interval, remaining))

    async def download_artifact(
        self,
        task_id: str,
        dest_path: str | Path,
        chunk_size: int = 1024 * 1024,
    ) -> Path:
        """
        从 worker 拉取某个已完成任务的 .max 产物并落地到 backend 本地。

        backend 与 worker 不共享文件系统，所以必须通过 HTTP 拉回；
        拿到后存到 ``dest_path``，DB 里再保存这个 Linux 路径供 /download 用。

        Args:
            task_id:    worker 返回的任务 ID。
            dest_path:  backend 本地保存路径（含文件名）；父目录会自动创建。
            chunk_size: 流式写入的块大小（字节），默认 1 MiB。

        Returns:
            实际写入的本地路径（Path 对象）。

        Raises:
            MaxWorkerError: 拉取或写入失败。
        """
        dest = Path(dest_path)
        dest.parent.mkdir(parents=True, exist_ok=True)
        # 写到临时文件再 rename，避免下载中断留下半截文件被当成产物
        tmp = dest.with_suffix(dest.suffix + ".part")

        logger.info(
            "[MaxWorkerClient] Fetching artifact: task_id={} → {}",
            task_id,
            dest,
        )
        try:
            async with self._get_client() as client:
                async with client.stream("GET", f"/file/{task_id}") as response:
                    response.raise_for_status()
                    total = 0
                    with open(tmp, "wb") as f:
                        async for chunk in response.aiter_bytes(chunk_size):
                            if chunk:
                                f.write(chunk)
                                total += len(chunk)
                    logger.success(
                        "[MaxWorkerClient] Artifact fetched: {} bytes → {}",
                        total,
                        dest,
                    )
        except httpx.HTTPStatusError as exc:
            # 读完响应体以拿到 detail（stream 模式下需要显式 aread）
            body = ""
            try:
                body = (await exc.response.aread()).decode(
                    "utf-8", errors="replace"
                )
            except Exception:
                pass
            msg = (
                f"max_worker /file/{task_id} 返回错误 "
                f"{exc.response.status_code}: {body[:500]}"
            )
            logger.error("[MaxWorkerClient] {}", msg)
            tmp.unlink(missing_ok=True)
            raise MaxWorkerError(msg) from exc
        except httpx.RequestError as exc:
            msg = f"max_worker 下载产物失败: {exc}"
            logger.error("[MaxWorkerClient] {}", msg)
            tmp.unlink(missing_ok=True)
            raise MaxWorkerError(msg) from exc
        except OSError as exc:
            msg = f"写入本地文件失败: {dest} ({exc})"
            logger.error("[MaxWorkerClient] {}", msg)
            tmp.unlink(missing_ok=True)
            raise MaxWorkerError(msg) from exc

        tmp.replace(dest)
        return dest

    async def health_check(self) -> bool:
        """
        检查 max_worker 服务是否健康。

        Returns:
            True 表示服务正常，False 表示不可用。
        """
        try:
            async with self._get_client() as client:
                response = await client.get("/health", timeout=5.0)
                ok = response.status_code == 200
                if ok:
                    logger.debug("[MaxWorkerClient] Health check OK")
                else:
                    logger.warning(
                        "[MaxWorkerClient] Health check returned {}",
                        response.status_code,
                    )
                return ok
        except Exception as exc:
            logger.warning("[MaxWorkerClient] Health check failed: {}", exc)
            return False

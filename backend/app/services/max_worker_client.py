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
from typing import Optional

import httpx
from loguru import logger

# max_worker 任务最终状态
_TERMINAL_STATUSES = {"completed", "failed", "error", "cancelled"}


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

        Args:
            script_path:     服务器上 .ms 脚本文件的绝对路径。
            output_max_path: 脚本执行完毕后 .max 文件的保存路径。
            timeout:         max_worker 端的执行超时（秒）。

        Returns:
            包含 ``task_id`` 和 ``status`` 的字典。

        Raises:
            MaxWorkerError: 请求失败或返回非 2xx 状态码。
        """
        payload = {
            "script_path": script_path,
            "output_max_path": output_max_path,
            "timeout": timeout,
        }
        logger.info(
            "[MaxWorkerClient] Submitting script: {} → {}", script_path, output_max_path
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
                    logger.error(
                        "[MaxWorkerClient] Task {} ended with status={}: error={}",
                        task_id,
                        current_status,
                        status_data.get("error"),
                    )
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

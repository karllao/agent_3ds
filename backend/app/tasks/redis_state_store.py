"""
Redis 状态存储。

Agent 流水线在"等待用户输入"时需要中断并将中间状态持久化，
以便 continue_pipeline 任务恢复执行。

所有 key 格式：
  project:{project_id}:agent_state    → Agent 完整 state 快照（JSON）
  project:{project_id}:cad_result     → CAD 解析结果（JSON）
  project:{project_id}:pending_question → 当前待回答的问题文本
  project:{project_id}:job_id         → 关联的 Job ID
"""

from __future__ import annotations

import json
from typing import Optional

import redis as redis_lib
from loguru import logger


class RedisStateStore:
    """
    基于 Redis 的 Agent 状态存储。

    使用同步 redis-py 客户端（适配 Celery 同步任务环境）。
    所有数据以 JSON 格式序列化存储，支持 TTL 自动过期。

    Args:
        redis_url: Redis 连接 URL，例如 ``redis://localhost:6379/0``。
    """

    def __init__(self, redis_url: str) -> None:
        self._client: redis_lib.Redis[str] = redis_lib.from_url(  # type: ignore[assignment]
            redis_url,
            decode_responses=True,  # 字符串模式，省去手动 decode
        )
        logger.debug("[RedisStateStore] Connected to Redis: {}", redis_url)

    # ── 键名构造 ──────────────────────────────────────────────────────────────

    @staticmethod
    def _agent_state_key(project_id: int) -> str:
        return f"project:{project_id}:agent_state"

    @staticmethod
    def _cad_result_key(project_id: int) -> str:
        return f"project:{project_id}:cad_result"

    @staticmethod
    def _pending_question_key(project_id: int) -> str:
        return f"project:{project_id}:pending_question"

    @staticmethod
    def _job_id_key(project_id: int) -> str:
        return f"project:{project_id}:job_id"

    # ── Agent State ───────────────────────────────────────────────────────────

    def save_agent_state(
        self,
        project_id: int,
        state: dict,
        ttl: int = 3600,
    ) -> None:
        """
        持久化 Agent state 快照到 Redis。

        Args:
            project_id: 项目 ID。
            state:      Agent state 字典（来自 run_agent_pipeline 的 state_snapshot）。
            ttl:        过期时间（秒），默认 1 小时。
        """
        key = self._agent_state_key(project_id)
        try:
            serialized = json.dumps(state, ensure_ascii=False)
            self._client.setex(key, ttl, serialized)
            logger.info(
                "[RedisStateStore] Agent state saved: project_id={} key={} ttl={}s size={}B",
                project_id,
                key,
                ttl,
                len(serialized),
            )
        except Exception as exc:
            logger.error(
                "[RedisStateStore] Failed to save agent state: project_id={} error={}",
                project_id,
                exc,
            )
            raise

    def load_agent_state(self, project_id: int) -> Optional[dict]:
        """
        从 Redis 加载 Agent state 快照。

        Args:
            project_id: 项目 ID。

        Returns:
            Agent state 字典，Key 不存在时返回 None。
        """
        key = self._agent_state_key(project_id)
        try:
            raw: Optional[str] = self._client.get(key)  # type: ignore[assignment]
            if raw is None:
                logger.warning(
                    "[RedisStateStore] Agent state not found: project_id={}", project_id
                )
                return None
            state: dict = json.loads(raw)
            logger.info(
                "[RedisStateStore] Agent state loaded: project_id={} size={}B",
                project_id,
                len(raw),
            )
            return state
        except Exception as exc:
            logger.error(
                "[RedisStateStore] Failed to load agent state: project_id={} error={}",
                project_id,
                exc,
            )
            return None

    def delete_agent_state(self, project_id: int) -> None:
        """清除 Agent state（任务完成或放弃时调用）。"""
        key = self._agent_state_key(project_id)
        self._client.delete(key)
        logger.debug("[RedisStateStore] Agent state deleted: project_id={}", project_id)

    # ── CAD Result ────────────────────────────────────────────────────────────

    def save_cad_result(
        self,
        project_id: int,
        cad_result: dict,
        ttl: int = 86400,
    ) -> None:
        """
        缓存 CAD 解析结果，避免重复解析。

        Args:
            project_id: 项目 ID。
            cad_result: CADParseResult.to_dict() 的输出。
            ttl:        过期时间（秒），默认 24 小时。
        """
        key = self._cad_result_key(project_id)
        try:
            serialized = json.dumps(cad_result, ensure_ascii=False)
            self._client.setex(key, ttl, serialized)
            logger.info(
                "[RedisStateStore] CAD result cached: project_id={} size={}B ttl={}s",
                project_id,
                len(serialized),
                ttl,
            )
        except Exception as exc:
            logger.error(
                "[RedisStateStore] Failed to save CAD result: project_id={} error={}",
                project_id,
                exc,
            )
            raise

    def load_cad_result(self, project_id: int) -> Optional[dict]:
        """
        从缓存加载 CAD 解析结果。

        Args:
            project_id: 项目 ID。

        Returns:
            CAD 解析结果字典，Key 不存在时返回 None。
        """
        key = self._cad_result_key(project_id)
        try:
            raw: Optional[str] = self._client.get(key)  # type: ignore[assignment]
            if raw is None:
                return None
            return json.loads(raw)
        except Exception as exc:
            logger.error(
                "[RedisStateStore] Failed to load CAD result: project_id={} error={}",
                project_id,
                exc,
            )
            return None

    def delete_cad_result(self, project_id: int) -> None:
        """清除 CAD 解析缓存。"""
        self._client.delete(self._cad_result_key(project_id))

    # ── Pending Question ──────────────────────────────────────────────────────

    def save_pending_question(
        self,
        project_id: int,
        question: str,
        ttl: int = 3600,
    ) -> None:
        """
        保存 Agent 向用户提出的追问问题。

        Args:
            project_id: 项目 ID。
            question:   追问文本。
            ttl:        过期时间（秒），默认 1 小时。
        """
        key = self._pending_question_key(project_id)
        self._client.setex(key, ttl, question)
        logger.info(
            "[RedisStateStore] Pending question saved: project_id={} question={}",
            project_id,
            question[:80],
        )

    def load_pending_question(self, project_id: int) -> Optional[str]:
        """
        加载当前待回答问题。

        Args:
            project_id: 项目 ID。

        Returns:
            问题文本，Key 不存在时返回 None。
        """
        key = self._pending_question_key(project_id)
        result: Optional[str] = self._client.get(key)  # type: ignore[assignment]
        if result is None:
            logger.warning(
                "[RedisStateStore] Pending question not found: project_id={}",
                project_id,
            )
        return result

    def delete_pending_question(self, project_id: int) -> None:
        """清除待回答问题。"""
        self._client.delete(self._pending_question_key(project_id))

    # ── Job ID ────────────────────────────────────────────────────────────────

    def save_job_id(self, project_id: int, job_id: int, ttl: int = 3600) -> None:
        """将 job_id 关联到 project，供 continue_pipeline 使用。"""
        key = self._job_id_key(project_id)
        self._client.setex(key, ttl, str(job_id))
        logger.debug(
            "[RedisStateStore] job_id saved: project_id={} job_id={}",
            project_id,
            job_id,
        )

    def load_job_id(self, project_id: int) -> Optional[int]:
        """加载关联的 job_id。"""
        key = self._job_id_key(project_id)
        raw: Optional[str] = self._client.get(key)  # type: ignore[assignment]
        if raw is None:
            return None
        try:
            return int(raw)
        except ValueError:
            logger.error(
                "[RedisStateStore] Invalid job_id in Redis: project_id={} raw={}",
                project_id,
                raw,
            )
            return None

    def delete_job_id(self, project_id: int) -> None:
        """清除 job_id 关联。"""
        self._client.delete(self._job_id_key(project_id))

    # ── 批量清理 ──────────────────────────────────────────────────────────────

    def cleanup_project(self, project_id: int) -> None:
        """
        清除某项目在 Redis 中的所有中间状态（任务完成或失败后调用）。

        Args:
            project_id: 项目 ID。
        """
        keys = [
            self._agent_state_key(project_id),
            self._cad_result_key(project_id),
            self._pending_question_key(project_id),
            self._job_id_key(project_id),
        ]
        deleted = self._client.delete(*keys)
        logger.info(
            "[RedisStateStore] Cleaned up project {}: {} keys deleted",
            project_id,
            deleted,
        )

    # ── 健康检查 ──────────────────────────────────────────────────────────────

    def ping(self) -> bool:
        """检查 Redis 连通性。"""
        try:
            return bool(self._client.ping())  # type: ignore[arg-type]
        except Exception:
            return False

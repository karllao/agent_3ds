"""
全局配置模块 —— 通过 pydantic-settings 从环境变量 / .env 文件读取配置。
"""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import AnyUrl, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # ── 基础 ────────────────────────────────────────────────────────────
    debug: bool = Field(default=False, description="是否开启调试模式")
    secret_key: str = Field(
        default="insecure-default-secret-key",
        description="JWT / Cookie 签名密钥",
    )

    # ── 数据库 ──────────────────────────────────────────────────────────
    database_url: str = Field(
        default="postgresql+asyncpg://postgres:password@localhost:5432/cad_agent",
        description="SQLAlchemy 异步数据库 URL",
    )

    @field_validator("database_url")
    @classmethod
    def _validate_db_url(cls, v: str) -> str:
        if not v.startswith("postgresql"):
            raise ValueError("DATABASE_URL 必须是 PostgreSQL 连接字符串")
        return v

    # ── Redis ───────────────────────────────────────────────────────────
    redis_url: str = Field(
        default="redis://localhost:6379/0",
        description="Redis 连接 URL，用作 Celery broker 与 result backend",
    )

    # ── AI 服务 Keys ────────────────────────────────────────────────────
    openai_api_key: str = Field(default="", description="OpenAI API Key")
    anthropic_api_key: str = Field(default="", description="Anthropic API Key")

    # ── AI 服务 Base URL（可选；留空则使用官方默认地址）─────────────────
    openai_base_url: str = Field(
        default="",
        description="OpenAI / OpenAI 兼容接口的 Base URL，如 https://api.openai.com/v1 或自建代理地址",
    )
    anthropic_base_url: str = Field(
        default="",
        description="Anthropic / Anthropic 兼容接口的 Base URL，如 https://api.anthropic.com",
    )

    # ── 3ds Max Worker ──────────────────────────────────────────────────
    max_worker_url: str = Field(
        default="http://localhost:8765",
        description="3ds Max Worker HTTP 服务地址",
    )

    # ── 文件存储 ────────────────────────────────────────────────────────
    storage_path: Path = Field(
        default=Path("/data/storage"),
        description="文件存储根路径",
    )

    @field_validator("storage_path", mode="before")
    @classmethod
    def _coerce_storage_path(cls, v: str | Path) -> Path:
        return Path(v)

    # ── CORS ────────────────────────────────────────────────────────────
    cors_origins: list[str] = Field(
        default=["http://localhost:3000", "http://localhost:5173"],
        description="允许跨域的前端地址列表",
    )

    # ── Celery ──────────────────────────────────────────────────────────
    celery_task_soft_time_limit: int = Field(
        default=600, description="Celery 任务软超时（秒）"
    )
    celery_task_time_limit: int = Field(
        default=900, description="Celery 任务硬超时（秒）"
    )

    # ── LLM 默认设置 ────────────────────────────────────────────────────
    default_llm_provider: str = Field(
        default="openai",
        description="默认 LLM 提供商: openai | anthropic",
    )
    default_model: str = Field(
        default="gpt-4o",
        description="默认使用的模型名称",
    )
    llm_temperature: float = Field(default=0.2, ge=0.0, le=2.0)

    @property
    def cad_upload_dir(self) -> Path:
        """CAD 原始文件目录"""
        return self.storage_path / "cad_uploads"

    @property
    def scene_json_dir(self) -> Path:
        """场景 JSON 目录"""
        return self.storage_path / "scene_json"

    @property
    def max_file_dir(self) -> Path:
        """3ds Max 导出文件目录"""
        return self.storage_path / "max_files"

    @property
    def preview_image_dir(self) -> Path:
        """预览图目录"""
        return self.storage_path / "previews"

    def ensure_storage_dirs(self) -> None:
        """在应用启动时创建所有存储目录"""
        for d in [
            self.storage_path,
            self.cad_upload_dir,
            self.scene_json_dir,
            self.max_file_dir,
            self.preview_image_dir,
        ]:
            d.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """返回全局单例 Settings，使用 lru_cache 保证只实例化一次。"""
    return Settings()

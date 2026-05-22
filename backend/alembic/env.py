"""
Alembic 迁移环境配置。

支持异步 SQLAlchemy（asyncpg）并从 pydantic-settings 读取数据库 URL。
运行方式：
    alembic revision --autogenerate -m "描述"
    alembic upgrade head
    alembic downgrade -1
"""

from __future__ import annotations

import asyncio
from logging.config import fileConfig

from alembic import context
from sqlalchemy import pool
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_engine_from_config

# ── 加载 Alembic 配置 ─────────────────────────────────────────────────────────
config = context.config

# 配置 Python 日志
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# ── 导入所有 ORM 模型（autogenerate 需要） ────────────────────────────────────
# 必须在 import Base 之前确保所有模型都被导入，否则 autogenerate 会漏掉表
from app.database import Base  # noqa: E402
from app.models import Conversation, Job, Message, Project  # noqa: E402, F401

target_metadata = Base.metadata

# ── 从应用配置动态获取数据库 URL ──────────────────────────────────────────────
from app.config import get_settings  # noqa: E402

_settings = get_settings()

# 将 asyncpg URL 替换为 psycopg2 URL 用于 Alembic（offline 模式需要同步驱动）
_sync_db_url = _settings.database_url.replace(
    "postgresql+asyncpg://", "postgresql+psycopg2://"
)

config.set_main_option("sqlalchemy.url", _sync_db_url)


# ── Offline 迁移（不连接数据库，只生成 SQL 脚本） ────────────────────────────
def run_migrations_offline() -> None:
    """
    在 'offline' 模式下运行迁移。
    仅生成 SQL 脚本，不需要真正的数据库连接。
    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
        compare_server_default=True,
    )

    with context.begin_transaction():
        context.run_migrations()


# ── Online 迁移（连接数据库执行） ─────────────────────────────────────────────
def do_run_migrations(connection: Connection) -> None:
    context.configure(
        connection=connection,
        target_metadata=target_metadata,
        compare_type=True,
        compare_server_default=True,
        # 支持枚举类型变更
        include_schemas=False,
    )
    with context.begin_transaction():
        context.run_migrations()


async def run_async_migrations() -> None:
    """使用异步引擎连接数据库并执行迁移"""
    # 使用 asyncpg URL（异步）
    async_url = _settings.database_url  # postgresql+asyncpg://...

    connectable = async_engine_from_config(
        {"sqlalchemy.url": async_url},
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,  # 迁移时不使用连接池
    )

    async with connectable.connect() as connection:
        await connection.run_sync(do_run_migrations)

    await connectable.dispose()


def run_migrations_online() -> None:
    """在 'online' 模式下运行迁移（标准入口）"""
    asyncio.run(run_async_migrations())


# ── 入口 ──────────────────────────────────────────────────────────────────────
if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()

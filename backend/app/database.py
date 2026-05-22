"""
数据库模块 —— 创建异步 SQLAlchemy engine / session，提供 FastAPI 依赖 get_db。
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from typing import Annotated

from app.config import get_settings
from fastapi import Depends
from sqlalchemy.ext.asyncio import (
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

settings = get_settings()

# ── Engine ───────────────────────────────────────────────────────────────────
engine = create_async_engine(
    settings.database_url,
    echo=settings.debug,  # debug 模式下打印 SQL
    pool_size=10,
    max_overflow=20,
    pool_pre_ping=True,  # 自动检测断开的连接
    pool_recycle=3600,  # 1 小时回收连接
)

# ── Session factory ──────────────────────────────────────────────────────────
AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,  # commit 后不需要再次 refresh
    autoflush=False,
    autocommit=False,
)


# ── Base model ───────────────────────────────────────────────────────────────
class Base(DeclarativeBase):
    """所有 ORM 模型的基类"""

    pass


# ── FastAPI 依赖 ─────────────────────────────────────────────────────────────
async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI 依赖注入：提供一个请求级别的数据库会话。
    请求结束（或发生异常）后自动关闭会话。
    """
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


# 便于在其他地方直接注入
DbSession = Annotated[AsyncSession, Depends(get_db)]


async def create_all_tables() -> None:
    """
    开发用：直接通过 SQLAlchemy 创建所有表（生产请用 Alembic）。
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


async def drop_all_tables() -> None:
    """危险：删除所有表，仅用于测试"""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)

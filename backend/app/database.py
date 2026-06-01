# ============================================================
# Yuno Agent Platform — Database Connection & Session Management
# Uses SQLAlchemy async engine with asyncpg driver.
#
# Design decisions:
# - Async engine for non-blocking DB operations in FastAPI
# - Single session factory, sessions per request via dependency
# - No repository pattern - services use session directly
# - Connection pooling configured for production load
# ============================================================
from __future__ import annotations

from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Any

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase
from sqlalchemy.pool import NullPool

from app.config import settings
from app.logger import get_logger

logger = get_logger(__name__)


class Base(DeclarativeBase):
    """
    SQLAlchemy declarative base for all models.
    All ORM models inherit from this class.
    """
    pass


def create_engine() -> AsyncEngine:
    """
    Create the async SQLAlchemy engine.

    Pool configuration:
    - pool_size=10: Keep 10 connections open (handles concurrent requests)
    - max_overflow=20: Allow 20 additional connections under load
    - pool_pre_ping=True: Detect dead connections before use
    - echo=False in production, True in debug mode
    """
    engine_kwargs: dict[str, Any] = {
        "echo": settings.log_sql_queries,
        "pool_pre_ping": True,
    }

    # NullPool for test environments (no connection reuse between tests)
    if settings.app_env == "test":
        engine_kwargs["poolclass"] = NullPool
    else:
        engine_kwargs["pool_size"] = settings.database_pool_size
        engine_kwargs["max_overflow"] = settings.database_max_overflow
        engine_kwargs["pool_timeout"] = settings.database_pool_timeout
        engine_kwargs["pool_recycle"] = 3600  # Recycle connections hourly

    return create_async_engine(settings.database_url, **engine_kwargs)


# Module-level engine (created once per process)
engine: AsyncEngine = create_engine()

# Session factory — all sessions created from this
AsyncSessionFactory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,  # Prevent lazy loading errors after commit
    autocommit=False,
    autoflush=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """
    FastAPI dependency that provides a database session per request.

    Usage in router:
        @router.get("/agents")
        async def list_agents(db: AsyncSession = Depends(get_db)):
            ...

    Guarantees:
    - Session is closed after request regardless of errors
    - Rollback on exception
    - Commit is explicit in service layer
    """
    async with AsyncSessionFactory() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


@asynccontextmanager
async def get_db_context() -> AsyncGenerator[AsyncSession, None]:
    """
    Context manager for use outside FastAPI dependency injection.
    Used in RQ workers and background tasks.

    Usage:
        async with get_db_context() as db:
            result = await db.execute(...)
    """
    async with AsyncSessionFactory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
        finally:
            await session.close()


async def check_database_connection() -> bool:
    """
    Verify database connectivity.
    Called during health check endpoint.
    """
    try:
        async with AsyncSessionFactory() as session:
            await session.execute(text("SELECT 1"))
        return True
    except Exception as e:
        logger.error("database_connection_failed", error=str(e))
        return False


async def create_all_tables() -> None:
    """
    Create all tables defined in SQLAlchemy models.
    Called during application startup.

    Note: In production, prefer Alembic migrations over create_all().
    For demo purposes, create_all() is acceptable.
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    logger.info("database_tables_created")


async def dispose_engine() -> None:
    """
    Dispose the engine connection pool.
    Called during application shutdown.
    """
    await engine.dispose()
    logger.info("database_engine_disposed")

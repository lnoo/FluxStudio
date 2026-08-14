"""Async SQLAlchemy engine + session factory, and table auto-creation."""
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings
from app.models.base import Base

engine = create_async_engine(
    settings.DATABASE_URL,
    echo=False,
    pool_pre_ping=True,
    pool_size=10,
    max_overflow=20,
)
async_session_factory = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)


async def init_db() -> None:
    """Create all tables if missing. Called on app startup."""
    # importing model modules registers their tables on Base.metadata
    from app.models import task, image  # noqa: F401

    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        # create_all only adds missing tables; add new columns to existing ones
        # with idempotent ALTERs (Postgres 16 supports IF NOT EXISTS).
        for col in ("width", "height"):
            await conn.execute(text(
                f"ALTER TABLE tasks ADD COLUMN IF NOT EXISTS {col} INTEGER"
            ))


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    async with async_session_factory() as session:
        yield session


async def get_db() -> AsyncGenerator[AsyncSession, None]:
    """FastAPI dependency: yields a per-request async session."""
    async with async_session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise

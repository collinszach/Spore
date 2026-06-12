"""Async database session management (Story 1.2).

Builds an async SQLAlchemy engine + session factory from settings.DATABASE_URL
(or DATABASE_URL env var, used by tests). The configured URL uses the plain
`postgresql://` scheme (matches docker-compose / psql conventions); we
normalize it to `postgresql+asyncpg://` for SQLAlchemy's async driver.
"""

import os

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.config import settings


def _to_async_dsn(url: str) -> str:
    """Normalize a postgres URL to use the asyncpg driver."""
    if url.startswith("postgresql+asyncpg://"):
        return url
    if url.startswith("postgresql://"):
        return "postgresql+asyncpg://" + url[len("postgresql://"):]
    if url.startswith("postgres://"):
        return "postgresql+asyncpg://" + url[len("postgres://"):]
    return url


def get_database_url() -> str:
    """Resolve the database URL, preferring the DATABASE_URL env var (tests)."""
    return os.environ.get("DATABASE_URL", settings.database_url)


def _build_engine():
    return create_async_engine(_to_async_dsn(get_database_url()), future=True)


engine = _build_engine()
async_session_factory = async_sessionmaker(engine, expire_on_commit=False)


async def get_session() -> AsyncSession:
    """FastAPI dependency yielding an AsyncSession."""
    async with async_session_factory() as session:
        yield session

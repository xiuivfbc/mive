from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.config import settings

engine = create_async_engine(
    settings.database_url,
    echo=False,
    pool_size=10,
    max_overflow=5,
    pool_pre_ping=True,
)
async_session = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Per-request shared session dependency. FastAPI caches this within a single request,
    so all Depends(get_session) calls share the same session.

    Commits on normal exit (persisting repo flushes), rolls back on exception.
    Issue 11 fix: call expire_all() after rollback so that ORM objects loaded
    with expire_on_commit=False don't carry stale state from the rolled-back
    transaction.
    """
    async with async_session() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            # Issue 11: expire all objects to prevent stale state after rollback
            session.expire_all()
            raise

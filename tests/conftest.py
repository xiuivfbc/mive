import os

import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db.models import Base

TEST_DATABASE_URL = os.getenv(
    "TEST_DATABASE_URL",
    "postgresql+asyncpg://mive:mive@localhost:5432/mive_test",
)

engine = create_async_engine(TEST_DATABASE_URL, echo=False)
TestSession = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


async def _reset_schema(conn) -> None:
    # CASCADE handles circular FK dependencies that confuse SQLAlchemy's topological sort
    await conn.execute(text("DROP SCHEMA public CASCADE"))
    await conn.execute(text("CREATE SCHEMA public"))
    await conn.run_sync(Base.metadata.create_all)


@pytest_asyncio.fixture(scope="session", autouse=True)
async def setup_db():
    async with engine.begin() as conn:
        await _reset_schema(conn)
    yield
    async with engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))

"""UserRepository 数据库集成测试。"""

import uuid

import pytest_asyncio
from sqlalchemy import text

from src.db.repositories.user_repo import UserRepository
from tests.conftest import TestSession


@pytest_asyncio.fixture(autouse=True)
async def cleanup():
    async with TestSession() as session:
        await session.execute(text("TRUNCATE m9_users CASCADE"))
        await session.commit()
    yield
    async with TestSession() as session:
        await session.execute(text("TRUNCATE m9_users CASCADE"))
        await session.commit()


async def _create_user(username="alice", email="alice@test.com"):
    async with TestSession() as session:
        repo = UserRepository(session)
        user = await repo.create(username=username, email=email, hashed_password="hashed")
        await session.commit()
        return user


class TestUserRepoCreate:
    async def test_create_returns_user(self):
        user = await _create_user()
        assert user.id is not None
        assert user.username == "alice"
        assert user.email == "alice@test.com"

    async def test_create_sets_defaults(self):
        user = await _create_user()
        assert user.preferred_language == "zh-CN"
        assert user.avatar_url is None
        assert user.is_admin is False
        assert user.must_change_password is False


class TestUserRepoGetById:
    async def test_get_existing_user(self):
        user = await _create_user()

        async with TestSession() as session:
            repo = UserRepository(session)
            result = await repo.get_by_id(user.id)

        assert result is not None
        assert result.username == "alice"

    async def test_get_nonexistent_returns_none(self):
        async with TestSession() as session:
            repo = UserRepository(session)
            result = await repo.get_by_id(uuid.uuid4())

        assert result is None


class TestUserRepoGetByUsername:
    async def test_get_by_username(self):
        await _create_user("bob", "bob@test.com")

        async with TestSession() as session:
            repo = UserRepository(session)
            result = await repo.get_by_username("bob")

        assert result is not None
        assert result.email == "bob@test.com"

    async def test_get_unknown_username_returns_none(self):
        async with TestSession() as session:
            repo = UserRepository(session)
            result = await repo.get_by_username("nobody")

        assert result is None


class TestUserRepoGetByEmail:
    async def test_get_by_email(self):
        await _create_user("carol", "carol@test.com")

        async with TestSession() as session:
            repo = UserRepository(session)
            result = await repo.get_by_email("carol@test.com")

        assert result is not None
        assert result.username == "carol"

    async def test_get_unknown_email_returns_none(self):
        async with TestSession() as session:
            repo = UserRepository(session)
            result = await repo.get_by_email("nobody@test.com")

        assert result is None


class TestUserRepoUpdateLanguage:
    async def test_update_language(self):
        user = await _create_user()

        async with TestSession() as session:
            repo = UserRepository(session)
            updated = await repo.update_language(user.id, "ja")
            await session.commit()

        assert updated is not None
        assert updated.preferred_language == "ja"

    async def test_update_language_nonexistent_returns_none(self):
        async with TestSession() as session:
            repo = UserRepository(session)
            result = await repo.update_language(uuid.uuid4(), "en")

        assert result is None

    async def test_update_language_persists(self):
        user = await _create_user()
        async with TestSession() as session:
            repo = UserRepository(session)
            await repo.update_language(user.id, "en")
            await session.commit()

        async with TestSession() as session:
            repo = UserRepository(session)
            found = await repo.get_by_id(user.id)

        assert found.preferred_language == "en"


class TestUserRepoUpdateAvatar:
    async def test_update_avatar(self):
        user = await _create_user()

        async with TestSession() as session:
            repo = UserRepository(session)
            updated = await repo.update_avatar(user.id, "data:image/png;base64,abc")
            await session.commit()

        assert updated.avatar_url == "data:image/png;base64,abc"

    async def test_update_avatar_nonexistent_returns_none(self):
        async with TestSession() as session:
            repo = UserRepository(session)
            result = await repo.update_avatar(uuid.uuid4(), "url")

        assert result is None


class TestUserRepoUpdateEmail:
    async def test_update_email(self):
        user = await _create_user("dave", "dave@test.com")

        async with TestSession() as session:
            repo = UserRepository(session)
            updated = await repo.update_email(user.id, "dave_new@test.com")
            await session.commit()

        assert updated.email == "dave_new@test.com"

    async def test_update_email_persists(self):
        user = await _create_user("eve", "eve@test.com")
        async with TestSession() as session:
            repo = UserRepository(session)
            await repo.update_email(user.id, "eve2@test.com")
            await session.commit()

        async with TestSession() as session:
            repo = UserRepository(session)
            found = await repo.get_by_email("eve2@test.com")

        assert found is not None
        assert found.username == "eve"

    async def test_update_email_nonexistent_returns_none(self):
        async with TestSession() as session:
            repo = UserRepository(session)
            result = await repo.update_email(uuid.uuid4(), "new@test.com")

        assert result is None

"""Tests for admin config API endpoints."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db.models import Base, M9User
from tests.conftest import TEST_DATABASE_URL

_test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)
_TestSession = async_sessionmaker(_test_engine, class_=AsyncSession, expire_on_commit=False)

ADMIN_ID = uuid.UUID("00000000-0000-0000-0000-000000000040")


@pytest_asyncio.fixture(scope="module")
async def client():
    """ASGI test client with admin user for admin config tests."""
    import src.db.session as db_session_mod
    from src.services.extraction_service import ExtractionService

    original_engine = db_session_mod.engine
    original_async_session = db_session_mod.async_session

    db_session_mod.engine = _test_engine
    db_session_mod.async_session = _TestSession

    async with _test_engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

    # Seed admin user
    from sqlalchemy import select

    async with _TestSession() as session:
        exists = await session.execute(select(M9User).where(M9User.id == ADMIN_ID))
        if exists.scalar_one_or_none() is None:
            session.add(
                M9User(
                    id=ADMIN_ID,
                    username="admin_user",
                    email="admin@test.com",
                    hashed_password="x",
                    is_admin=True,
                )
            )
        await session.commit()

    from src.main import app

    mock_llm = AsyncMock()
    mock_llm.complete_json.return_value = {"messages": []}
    mock_extraction = ExtractionService(llm=mock_llm)

    saved = {}
    for attr in ("llm", "extraction_service", "search_service"):
        saved[attr] = getattr(app.state, attr, None)
    app.state.llm = mock_llm
    app.state.extraction_service = mock_extraction
    app.state.search_service = None

    # Override get_current_user to return admin user
    from src.api.deps import get_current_user

    _admin = MagicMock(spec=M9User)
    _admin.id = ADMIN_ID
    _admin.username = "admin_user"
    _admin.email = "admin@test.com"
    _admin.is_admin = True
    _admin.avatar_url = None

    _prev_cu = app.dependency_overrides.get(get_current_user)
    app.dependency_overrides[get_current_user] = lambda: _admin

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c

    if _prev_cu is None:
        app.dependency_overrides.pop(get_current_user, None)
    else:
        app.dependency_overrides[get_current_user] = _prev_cu
    for attr, val in saved.items():
        setattr(app.state, attr, val)
    db_session_mod.engine = original_engine
    db_session_mod.async_session = original_async_session


@pytest_asyncio.fixture(scope="module")
async def admin_headers():
    """Empty headers dict — auth is bypassed via dependency override."""
    return {}


class TestAdminConfigAPI:
    async def test_get_config_group_requires_auth(self, client: httpx.AsyncClient):
        """Non-admin access should be rejected."""
        from src.api.deps import get_current_user
        from src.main import app

        # Temporarily switch to a non-admin user
        _non_admin = MagicMock(spec=M9User)
        _non_admin.id = uuid.uuid4()
        _non_admin.username = "regular_user"
        _non_admin.email = "regular@test.com"
        _non_admin.is_admin = False
        _non_admin.avatar_url = None

        app.dependency_overrides[get_current_user] = lambda: _non_admin
        try:
            response = await client.get("/api/admin/config/llm")
            assert response.status_code in (401, 403)
        finally:
            # Restore admin user
            _admin = MagicMock(spec=M9User)
            _admin.id = ADMIN_ID
            _admin.username = "admin_user"
            _admin.email = "admin@test.com"
            _admin.is_admin = True
            _admin.avatar_url = None
            app.dependency_overrides[get_current_user] = lambda: _admin

    async def test_get_config_group_invalid_group(self, client: httpx.AsyncClient, admin_headers):
        response = await client.get("/api/admin/config/invalid", headers=admin_headers)
        assert response.status_code == 400

    async def test_get_config_group_llm(self, client: httpx.AsyncClient, admin_headers):
        response = await client.get("/api/admin/config/llm", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        assert data["group"] == "llm"
        assert len(data["items"]) > 0
        assert all("key" in item and "value" in item and "source" in item for item in data["items"])

    async def test_update_and_reset_config(self, client: httpx.AsyncClient, admin_headers):
        # Update
        response = await client.put(
            "/api/admin/config/llm",
            json={"values": {"model": "test-model"}},
            headers=admin_headers,
        )
        assert response.status_code == 200
        data = response.json()
        model_item = next(item for item in data["items"] if item["key"] == "model")
        assert model_item["source"] == "override"
        assert model_item["value"] == "test-model"

        # Reset
        response = await client.delete("/api/admin/config/llm", headers=admin_headers)
        assert response.status_code == 200
        data = response.json()
        model_item = next(item for item in data["items"] if item["key"] == "model")
        assert model_item["source"] == "env_default"

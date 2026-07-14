"""API integration test fixtures — real FastAPI app + real DB + mocked LLM."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest_asyncio
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from src.db.models import Base, M9User
from tests.conftest import TEST_DATABASE_URL

_DROP_CIRCULAR_FK = text(
    "ALTER TABLE IF EXISTS m1_worlds DROP CONSTRAINT IF EXISTS fk_m1worlds_user_character_id"
)


@pytest_asyncio.fixture(scope="session")
async def api_client():
    """ASGI test client with real DB and mocked LLM.

    Uses httpx transport to call the FastAPI app directly (no real server).
    Patches src.db.session so the app connects to mive_test, not the dev DB.

    Creates a fresh engine inside the fixture to avoid event-loop contamination
    from TestClient (which runs in a background thread with its own loop).
    """
    import src.db.session as db_session_mod
    from src.services.extraction_service import ExtractionService

    # 1. Create a fresh engine in THIS event loop (not module-level)
    _test_engine = create_async_engine(TEST_DATABASE_URL, echo=False)

    # 2. Swap the global engine + session factory to point at the test DB
    original_engine = db_session_mod.engine
    original_async_session = db_session_mod.async_session

    test_session_factory = async_sessionmaker(
        _test_engine, class_=AsyncSession, expire_on_commit=False
    )
    db_session_mod.engine = _test_engine
    db_session_mod.async_session = test_session_factory

    # 3. Build DB schema in test DB
    async with _test_engine.begin() as conn:
        await conn.execute(text("DROP SCHEMA public CASCADE"))
        await conn.execute(text("CREATE SCHEMA public"))
        await conn.run_sync(Base.metadata.create_all)

    # Seed test user
    _test_user_id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    async with test_session_factory() as _seed_session:
        _seed_session.add(
            M9User(
                id=_test_user_id,
                username="testuser",
                email="testuser@test.com",
                hashed_password="x",
            )
        )
        await _seed_session.commit()

    # 3. Import app
    # 4. Mock LLM + extraction and inject into app.state
    from src.llm.base import LLMResponse
    from src.main import app

    mock_llm = AsyncMock()
    mock_llm.complete.return_value = LLMResponse(
        content="模拟世界观概述文本", model="test", input_tokens=0, output_tokens=0
    )
    mock_llm.complete_json.return_value = {
        "messages": [
            {
                "type": "narration",
                "sender_type": "narrator",
                "sender_name": "旁白",
                "content": "（模拟回复）",
                "virtual_time_offset_minutes": 0,
            }
        ]
    }
    mock_extraction = ExtractionService(llm=mock_llm)

    # Override get_current_user so integration tests don't need real tokens
    from src.api.deps import get_current_user
    from src.services.material_service import MaterialService

    _test_user = MagicMock(spec=M9User)
    _test_user.id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    _test_user.username = "testuser"
    _test_user.avatar_url = None
    app.dependency_overrides[get_current_user] = lambda: _test_user

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    ) as client:
        # Store originals AFTER lifespan startup (lifespan overwrites app.state.llm etc.)
        saved = {}
        for attr in ("llm", "extraction_service", "search_service", "material_service"):
            saved[attr] = getattr(app.state, attr, None)

        # Re-apply mocks after lifespan startup
        app.state.llm = mock_llm
        app.state.extraction_service = mock_extraction
        app.state.search_service = None  # disable search in tests
        app.state.redis = AsyncMock()
        app.state.material_service = MaterialService()
        yield client

    # 5. Restore
    app.dependency_overrides.pop(get_current_user, None)
    for attr, val in saved.items():
        if val is None:
            if hasattr(app.state, attr):
                delattr(app.state, attr)
        else:
            setattr(app.state, attr, val)

    db_session_mod.engine = original_engine
    db_session_mod.async_session = original_async_session
    # Don't drop the schema here — setup_db (autouse session fixture) handles final teardown.
    # Dropping here would destroy tables before later test modules (e.g. test_db) can run.
    await _test_engine.dispose()

"""Shared test helpers for building test clients, mock sessions, and fixtures."""

from contextlib import asynccontextmanager
from unittest.mock import AsyncMock, MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient


def build_test_client(router, **state_overrides) -> TestClient:
    """Create a TestClient with the given router and app.state overrides.

    Usage:
        client = build_test_client(characters.router, character_service=mock_svc)
    """
    app = FastAPI()
    app.include_router(router)
    for key, value in state_overrides.items():
        setattr(app.state, key, value)
    return TestClient(app)


def make_mock_session() -> AsyncMock:
    """Create a mock AsyncSession with working begin() and begin_nested() context managers."""
    mock_session = AsyncMock()

    @asynccontextmanager
    async def _begin():
        yield mock_session

    @asynccontextmanager
    async def _begin_nested():
        yield mock_session

    mock_session.begin = MagicMock(side_effect=_begin)
    mock_session.begin_nested = MagicMock(side_effect=_begin_nested)
    return mock_session

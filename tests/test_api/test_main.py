"""Smoke tests for the FastAPI app."""

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app_client():
    """Create a test client with mocked services."""
    from src.main import app

    mocked_attrs = {
        "world_service": AsyncMock(),
        "material_service": MagicMock(),
        "character_service": AsyncMock(),
        "relation_service": AsyncMock(),
        "version_service": AsyncMock(),
        "generation_service": AsyncMock(),
    }
    originals = {k: getattr(app.state, k, None) for k in mocked_attrs}
    for k, v in mocked_attrs.items():
        setattr(app.state, k, v)

    yield TestClient(app)

    for k, v in originals.items():
        if v is None:
            try:
                delattr(app.state, k)
            except AttributeError:
                pass
        else:
            setattr(app.state, k, v)


def test_health_endpoint(app_client):
    """GET /health 应返回 ok。"""
    resp = app_client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_all_routes_registered(app_client):
    """确认所有核心 API 路由已注册。"""
    routes = {r.path for r in app_client.app.routes if hasattr(r, "methods")}

    # Core world routes
    assert "/api/worlds" in routes
    assert "/api/worlds/{world_id}" in routes
    assert "/api/worlds/{world_id}/elements/{element_id}" in routes
    assert "/api/worlds/{world_id}/character-material" in routes
    assert "/health" in routes

    # Characters & relations
    assert "/api/worlds/{world_id}/characters" in routes
    assert "/api/worlds/{world_id}/characters/{character_id}" in routes
    assert "/api/worlds/{world_id}/characters/generate" in routes
    assert "/api/worlds/{world_id}/relations" in routes

    # Versions
    assert "/api/worlds/{world_id}/versions" in routes

    # Graph
    assert "/api/worlds/{world_id}/graph/data" in routes

    # Chat & memories
    assert "/api/worlds/{world_id}/chat-sessions" in routes
    assert "/api/worlds/{world_id}/characters/{character_id}/memories" in routes

    # Auth (open-source single-admin deployment: no login, just an identity echo)
    assert "/api/auth/me" in routes

    # Admin
    assert "/api/admin/guide" in routes
    assert "/api/admin/config/{group}" in routes

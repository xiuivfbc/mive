"""Integration tests for world template endpoints."""

import pytest

from src.models.templates import TEMPLATES

pytestmark = pytest.mark.usefixtures("api_client")


class TestListTemplates:
    """GET /api/worlds/templates"""

    async def test_returns_all_templates(self, api_client):
        r = await api_client.get("/api/worlds/templates")
        assert r.status_code == 200
        data = r.json()
        assert len(data) == len(TEMPLATES)

    async def test_each_template_has_required_fields(self, api_client):
        r = await api_client.get("/api/worlds/templates")
        data = r.json()
        required = {"id", "title", "category", "description", "element_count"}
        for tpl in data:
            assert required.issubset(tpl.keys()), f"Missing fields in template {tpl.get('id')}"

    async def test_template_ids_match_registry(self, api_client):
        r = await api_client.get("/api/worlds/templates")
        ids = {t["id"] for t in r.json()}
        assert ids == set(TEMPLATES.keys())

    async def test_element_counts_positive(self, api_client):
        r = await api_client.get("/api/worlds/templates")
        for tpl in r.json():
            assert tpl["element_count"] > 0


class TestCreateFromTemplate:
    """POST /api/worlds/create-from-template"""

    async def test_create_with_valid_template(self, api_client):
        r = await api_client.post(
            "/api/worlds/create-from-template",
            json={"template_id": "fantasy-kingdom"},
        )
        assert r.status_code == 201
        world = r.json()
        assert world["source"]["title"] == "星辉王国"
        assert world["source"]["type"] == "template"
        assert len(world["elements"]) > 0
        assert world["user_character_id"] is not None

    async def test_create_invalid_template_returns_404(self, api_client):
        r = await api_client.post(
            "/api/worlds/create-from-template",
            json={"template_id": "nonexistent-template"},
        )
        assert r.status_code == 404

    async def test_create_with_scale(self, api_client):
        for scale in ("standard", "detailed", "deep"):
            r = await api_client.post(
                "/api/worlds/create-from-template",
                json={"template_id": "cyberpunk-city", "scale": scale},
            )
            assert r.status_code == 201, f"scale={scale} failed"
            assert r.json()["source"]["title"] == "霓虹深渊"


class TestCreateFromTemplateAuth:
    """POST /api/worlds/create-from-template without auth."""

    async def test_unauthenticated_returns_401(self, api_client):
        """Without dependency override, endpoint should reject unauthenticated requests."""
        from src.api.deps import get_current_user
        from src.main import app

        # Temporarily remove the auth override
        original = app.dependency_overrides.pop(get_current_user, None)
        try:
            r = await api_client.post(
                "/api/worlds/create-from-template",
                json={"template_id": "fantasy-kingdom"},
            )
            assert r.status_code == 401
        finally:
            if original is not None:
                app.dependency_overrides[get_current_user] = original

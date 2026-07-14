"""API integration tests for /api/worlds endpoints."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from src.db.models import M9User
from src.models.world import Element, WorldDoc, WorldMeta, WorldSource


def _mock_current_user():
    user = MagicMock(spec=M9User)
    user.id = uuid.UUID("00000000-0000-0000-0000-000000000001")
    user.username = "testuser"
    user.avatar_url = None
    return user


@pytest.fixture
def mock_world_service():
    return AsyncMock()


@pytest.fixture
def mock_material_service():
    svc = MagicMock()
    return svc


@pytest.fixture
def client(mock_world_service, mock_material_service):
    """创建注入 mock 服务的 TestClient。"""
    from unittest.mock import AsyncMock

    from fastapi import FastAPI

    from src.api.character_material import router as material_router
    from src.api.elements import router as elements_router
    from src.api.worlds import router as worlds_router

    app = FastAPI()
    app.include_router(worlds_router)
    app.include_router(elements_router)
    app.include_router(material_router)

    from src.api.deps import get_current_user

    app.state.world_service = mock_world_service
    app.state.material_service = mock_material_service
    app.state.extraction_service = AsyncMock()
    app.state.search_service = AsyncMock()
    app.state.llm = AsyncMock()
    app.state.redis = AsyncMock()
    app.state.llm.complete_json.return_value = {"elements": []}
    app.dependency_overrides[get_current_user] = _mock_current_user

    # Bypass DB session in unit tests (no real DB)
    from src.db.session import get_session

    # Provide a mock session so WorldRepository.list_by_user doesn't hit a real DB
    mock_result = MagicMock()
    mock_result.all.return_value = []
    mock_session = AsyncMock()
    mock_session.execute.return_value = mock_result

    # M14: world creation calls character_repo.create() → session.refresh(row).
    # Populate DB-side default fields so _to_model() passes Pydantic validation.
    async def _mock_refresh(row):
        if not getattr(row, "created_at", None):
            row.created_at = datetime.utcnow()
        if not getattr(row, "updated_at", None):
            row.updated_at = datetime.utcnow()
        if not getattr(row, "id", None):
            row.id = uuid.uuid4()

    mock_session.refresh.side_effect = _mock_refresh

    async def _mock_get_session():
        yield mock_session

    app.dependency_overrides[get_session] = _mock_get_session

    return TestClient(app)


class TestCreateWorld:
    def test_create_world_success(self, client, mock_world_service):
        """POST /api/worlds 成功创建世界观应返回 202 + world_id。"""
        resp = client.post(
            "/api/worlds",
            json={
                "title": "三体",
                "author": "刘慈欣",
                "description": "硬科幻经典",
            },
        )

        assert resp.status_code == 202
        data = resp.json()
        assert "world_id" in data

    def test_create_world_calls_service(self, client, mock_world_service):
        """POST /api/worlds 应调用 world_service.check_llm_available。"""
        client.post("/api/worlds", json={"title": "三体"})

        mock_world_service.check_llm_available.assert_called_once()


class TestGetWorld:
    def test_get_world_success(self, client, mock_world_service):
        """GET /api/worlds/{id} 存在时应返回 200 + 世界观文档。"""
        world = WorldDoc(
            world_id="w-001",
            version="1.0",
            source=WorldSource(title="三体"),
            meta=WorldMeta(),
            elements=[Element(id="e1", category="势力阵营", name="ETO", brief="...", detail="...")],
        )
        mock_world_service.get_world_with_updated_at.return_value = (world, datetime.now(UTC))

        resp = client.get("/api/worlds/w-001")

        assert resp.status_code == 200
        assert resp.json()["world_id"] == "w-001"

    def test_get_world_not_found(self, client, mock_world_service):
        """GET /api/worlds/{id} 不存在时应返回 404。"""
        mock_world_service.get_world_with_updated_at.return_value = None

        resp = client.get("/api/worlds/nonexistent")

        assert resp.status_code == 404


class TestWikiPreview:
    def test_wiki_preview_success(self, client, mock_world_service):
        """POST /api/worlds/wiki-preview 成功应返回全文预览内容。"""
        mock_world_service.fetch_wiki_full_preview.return_value = ("正文内容", False)

        resp = client.post(
            "/api/worlds/wiki-preview",
            json={"url": "https://zh.wikipedia.org/wiki/三体"},
        )

        assert resp.status_code == 200
        assert resp.json() == {"content": "正文内容", "truncated": False}
        mock_world_service.fetch_wiki_full_preview.assert_called_once_with(
            "https://zh.wikipedia.org/wiki/三体"
        )

    def test_wiki_preview_fetch_failure_returns_404(self, client, mock_world_service):
        """抓取失败（fetch_wiki_full_preview 返回 None）应返回 404。"""
        mock_world_service.fetch_wiki_full_preview.return_value = None

        resp = client.post(
            "/api/worlds/wiki-preview",
            json={"url": "https://zh.wikipedia.org/wiki/未知作品"},
        )

        assert resp.status_code == 404


class TestCopyWorld:
    def test_copy_world_success(self, client, mock_world_service):
        """POST /api/worlds/{id}/copy 成功应返回 201 + 新世界。"""
        copied = WorldDoc(
            world_id="w-new",
            world_base_id="w-original",
            version="1.0",
            source=WorldSource(title="三体"),
            meta=WorldMeta(),
            elements=[Element(id="e1", category="势力阵营", name="ETO", brief="...", detail="...")],
        )
        mock_world_service.copy_world.return_value = copied

        resp = client.post("/api/worlds/w-original/copy")

        assert resp.status_code == 201
        assert resp.json()["world_base_id"] == "w-original"

    def test_copy_world_not_found(self, client, mock_world_service):
        """复制不存在的世界应返回 404。"""
        mock_world_service.copy_world.side_effect = ValueError("not found")

        resp = client.post("/api/worlds/bad/copy")

        assert resp.status_code == 404


class TestUpdateElement:
    def test_update_element_success(self, client, mock_world_service):
        """PUT /api/worlds/{id}/elements/{elem_id} 成功应返回 200。"""
        mock_world_service.update_element.return_value = Element(
            id="e1",
            category="势力阵营",
            name="ETO",
            brief="新简介",
            detail="新详情",
        )

        resp = client.put(
            "/api/worlds/w-001/elements/e1",
            json={"brief": "新简介", "detail": "新详情"},
        )

        assert resp.status_code == 200
        assert resp.json()["brief"] == "新简介"

    def test_update_element_not_found(self, client, mock_world_service):
        """更新不存在的元素应返回 404。"""
        mock_world_service.update_element.return_value = None

        resp = client.put(
            "/api/worlds/w-001/elements/bad-id",
            json={"brief": "x", "detail": "y"},
        )

        assert resp.status_code == 404


class TestAddElement:
    def test_add_element_success(self, client, mock_world_service):
        """POST /api/worlds/{id}/elements 成功应返回 201。"""
        mock_world_service.add_element.return_value = Element(
            id="e-new",
            category="历史背景",
            name="大低谷",
            brief="人口骤降期",
            detail="详细...",
        )

        resp = client.post(
            "/api/worlds/w-001/elements",
            json={
                "category": "历史背景",
                "name": "大低谷",
                "brief": "人口骤降期",
                "detail": "详细...",
            },
        )

        assert resp.status_code == 201
        assert resp.json()["name"] == "大低谷"

    def test_add_element_world_not_found(self, client, mock_world_service):
        """世界不存在时应返回 404。"""
        mock_world_service.add_element.return_value = None

        resp = client.post(
            "/api/worlds/bad/elements",
            json={"category": "x", "name": "y", "brief": "z", "detail": "z"},
        )

        assert resp.status_code == 404


class TestDeleteElement:
    def test_delete_element_success(self, client, mock_world_service):
        """DELETE /api/worlds/{id}/elements/{elem_id} 成功应返回 200。"""
        mock_world_service.delete_element.return_value = True

        resp = client.delete("/api/worlds/w-001/elements/e1")

        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

    def test_delete_element_not_found(self, client, mock_world_service):
        """删除不存在的元素应返回 404。"""
        mock_world_service.delete_element.return_value = False

        resp = client.delete("/api/worlds/w-001/elements/bad")

        assert resp.status_code == 404


class TestCharacterMaterial:
    def test_get_character_material(self, client, mock_world_service, mock_material_service):
        """GET /api/worlds/{id}/character-material 应返回素材包。"""
        world = WorldDoc(
            world_id="w-001",
            version="1.0",
            source=WorldSource(title="三体"),
            meta=WorldMeta(),
            elements=[],
        )
        mock_world_service.get_world.return_value = world

        from datetime import datetime

        from src.models.material import CharacterMaterial, MaterialElement

        material = CharacterMaterial(
            world_id="w-001",
            world_version="1.0",
            world_elements=[
                MaterialElement(
                    id="e1", category="势力阵营", name="ETO", brief="...", detail="..."
                ),
            ],
            world_rules_summary="规则摘要",
            generated_at=datetime.now(),
        )
        mock_material_service.generate.return_value = material

        resp = client.get("/api/worlds/w-001/character-material")

        assert resp.status_code == 200
        assert len(resp.json()["world_elements"]) == 1

    def test_get_character_material_world_not_found(self, client, mock_world_service):
        """世界不存在时应返回 404。"""
        mock_world_service.get_world.return_value = None

        resp = client.get("/api/worlds/bad-id/character-material")

        assert resp.status_code == 404


class TestUpdateCommonSense:
    def test_update_common_sense_success(self, client, mock_world_service):
        """PATCH /api/worlds/{id}/common-sense 成功应返回 204。"""
        mock_world_service.update_common_sense = AsyncMock(return_value=True)

        resp = client.patch(
            "/api/worlds/w-001/common-sense",
            json={"common_sense": "这个世界存在魔法体系"},
        )

        assert resp.status_code == 204

    def test_update_common_sense_empty_string(self, client, mock_world_service):
        """PATCH 空字符串应返回 204。"""
        mock_world_service.update_common_sense = AsyncMock(return_value=True)

        resp = client.patch(
            "/api/worlds/w-001/common-sense",
            json={"common_sense": ""},
        )

        assert resp.status_code == 204

    def test_update_common_sense_world_not_found(self, client, mock_world_service):
        """不存在的 world_id 应返回 404。"""
        mock_world_service.update_common_sense = AsyncMock(return_value=False)

        resp = client.patch(
            "/api/worlds/nonexistent/common-sense",
            json={"common_sense": "这个世界存在魔法"},
        )

        assert resp.status_code == 404

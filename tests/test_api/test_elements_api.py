"""API 集成测试：元素端点 POST/PUT/DELETE /worlds/{id}/elements。"""

import uuid
from unittest.mock import AsyncMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.models.world import Element


def _make_element(eid: str | None = None) -> Element:
    return Element(
        id=eid or f"elem_{uuid.uuid4().hex[:8]}",
        category="地点",
        name="长安城",
        brief="唐朝都城",
        detail="繁华都市",
    )


def _build_client(world_service=None):
    from unittest.mock import MagicMock

    from src.api.deps import get_element_retrieval_service, get_session, get_world_service
    from src.api.elements import router

    app = FastAPI()
    app.include_router(router)

    svc = world_service or AsyncMock()
    app.dependency_overrides[get_world_service] = lambda: svc
    app.dependency_overrides[get_session] = lambda: AsyncMock()
    app.dependency_overrides[get_element_retrieval_service] = lambda: MagicMock()
    app.state.redis = AsyncMock()

    client = TestClient(app, raise_server_exceptions=False)
    return client, svc


WORLD_ID = str(uuid.uuid4())
ELEM_ID = "elem_abcdef12"


class TestAddElement:
    def test_add_element_returns_201(self):
        elem = _make_element(ELEM_ID)
        svc = AsyncMock()
        svc.add_element = AsyncMock(return_value=elem)
        client, _ = _build_client(svc)

        resp = client.post(
            f"/api/worlds/{WORLD_ID}/elements",
            json={"category": "地点", "name": "长安城", "brief": "唐朝都城", "detail": "繁华都市"},
        )

        assert resp.status_code == 201

    def test_add_element_returns_element_data(self):
        elem = _make_element(ELEM_ID)
        svc = AsyncMock()
        svc.add_element = AsyncMock(return_value=elem)
        client, _ = _build_client(svc)

        resp = client.post(
            f"/api/worlds/{WORLD_ID}/elements",
            json={"category": "地点", "name": "长安城", "brief": "唐朝都城", "detail": "繁华都市"},
        )

        body = resp.json()
        assert body["name"] == "长安城"
        assert body["category"] == "地点"

    def test_add_element_world_not_found_returns_404(self):
        svc = AsyncMock()
        svc.add_element = AsyncMock(return_value=None)
        client, _ = _build_client(svc)

        resp = client.post(
            f"/api/worlds/{WORLD_ID}/elements",
            json={"category": "地点", "name": "X", "brief": "b", "detail": "d"},
        )

        assert resp.status_code == 404

    def test_add_element_calls_service_with_correct_args(self):
        elem = _make_element()
        svc = AsyncMock()
        svc.add_element = AsyncMock(return_value=elem)
        client, _ = _build_client(svc)

        client.post(
            f"/api/worlds/{WORLD_ID}/elements",
            json={"category": "势力", "name": "朝廷", "brief": "皇权", "detail": "中央集权"},
        )

        svc.add_element.assert_called_once_with(
            WORLD_ID, category="势力", name="朝廷", brief="皇权", detail="中央集权"
        )

    def test_add_element_missing_field_returns_422(self):
        client, _ = _build_client()

        resp = client.post(
            f"/api/worlds/{WORLD_ID}/elements",
            json={"category": "地点", "name": "X"},  # missing brief and detail
        )

        assert resp.status_code == 422


class TestUpdateElement:
    def test_update_element_returns_200(self):
        elem = _make_element(ELEM_ID)
        svc = AsyncMock()
        svc.update_element = AsyncMock(return_value=elem)
        client, _ = _build_client(svc)

        resp = client.put(
            f"/api/worlds/{WORLD_ID}/elements/{ELEM_ID}",
            json={"brief": "新简介", "detail": "新详情"},
        )

        assert resp.status_code == 200

    def test_update_element_not_found_returns_404(self):
        svc = AsyncMock()
        svc.update_element = AsyncMock(return_value=None)
        client, _ = _build_client(svc)

        resp = client.put(
            f"/api/worlds/{WORLD_ID}/elements/{ELEM_ID}",
            json={"brief": "b", "detail": "d"},
        )

        assert resp.status_code == 404

    def test_update_element_calls_service(self):
        elem = _make_element(ELEM_ID)
        svc = AsyncMock()
        svc.update_element = AsyncMock(return_value=elem)
        client, _ = _build_client(svc)

        client.put(
            f"/api/worlds/{WORLD_ID}/elements/{ELEM_ID}",
            json={"brief": "新简介", "detail": "新详情", "name": "新名字", "category": "事件"},
        )

        svc.update_element.assert_called_once_with(
            WORLD_ID,
            ELEM_ID,
            brief="新简介",
            detail="新详情",
            name="新名字",
            category="事件",
        )

    def test_update_element_partial_update(self):
        elem = _make_element(ELEM_ID)
        svc = AsyncMock()
        svc.update_element = AsyncMock(return_value=elem)
        client, _ = _build_client(svc)

        resp = client.put(
            f"/api/worlds/{WORLD_ID}/elements/{ELEM_ID}",
            json={"brief": "只改简介", "detail": ""},
        )

        assert resp.status_code == 200


class TestDeleteElement:
    def test_delete_element_returns_200(self):
        svc = AsyncMock()
        svc.delete_element = AsyncMock(return_value=True)
        client, _ = _build_client(svc)

        resp = client.delete(f"/api/worlds/{WORLD_ID}/elements/{ELEM_ID}")

        assert resp.status_code == 200
        assert resp.json()["deleted"] is True

    def test_delete_element_not_found_returns_404(self):
        svc = AsyncMock()
        svc.delete_element = AsyncMock(return_value=False)
        client, _ = _build_client(svc)

        resp = client.delete(f"/api/worlds/{WORLD_ID}/elements/{ELEM_ID}")

        assert resp.status_code == 404

    def test_delete_element_calls_service(self):
        svc = AsyncMock()
        svc.delete_element = AsyncMock(return_value=True)
        client, _ = _build_client(svc)

        client.delete(f"/api/worlds/{WORLD_ID}/elements/{ELEM_ID}")

        svc.delete_element.assert_called_once_with(WORLD_ID, ELEM_ID)

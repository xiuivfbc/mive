import uuid
from datetime import datetime
from unittest.mock import AsyncMock

import pytest

from src.models.character import Character
from src.models.relation import CreateRelationRequest, Relation, UpdateRelationRequest
from src.services.relation_service import RelationService


def _make_relation(
    char_a: str = "a-001", char_b: str = "b-001", rel_type: str = "同事"
) -> Relation:
    return Relation(
        id=str(uuid.uuid4()),
        world_id=str(uuid.uuid4()),
        character_a=char_a,
        character_b=char_b,
        type=rel_type,
        direction="bidirectional",
        status="active",
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


def _make_character(char_id: str = "a-001", name: str = "叶文洁") -> Character:
    return Character(
        id=char_id,
        world_id="w-001",
        name=name,
        created_at=datetime.now(),
        updated_at=datetime.now(),
    )


class TestRelationServiceCreate:
    async def test_create_returns_relation(self):
        mock_repo = AsyncMock()
        mock_repo.create.return_value = _make_relation()
        mock_char_repo = AsyncMock()
        mock_char_repo.get_by_id.return_value = _make_character()
        service = RelationService(mock_repo, mock_char_repo)

        result = await service.create(
            "w-001",
            CreateRelationRequest(character_a="a-001", character_b="b-001", type="同事"),
        )
        assert result.type == "同事"

    async def test_create_validates_characters_exist(self):
        mock_repo = AsyncMock()
        mock_char_repo = AsyncMock()
        mock_char_repo.get_by_id.return_value = None
        service = RelationService(mock_repo, mock_char_repo)

        with pytest.raises(ValueError, match="Character not found"):
            await service.create(
                "w-001",
                CreateRelationRequest(character_a="nonexistent", character_b="b-001"),
            )


class TestRelationServiceGet:
    async def test_get_returns_relation(self):
        mock_repo = AsyncMock()
        mock_repo.get_by_id.return_value = _make_relation()
        service = RelationService(mock_repo)

        result = await service.get("rel-001")
        assert result is not None

    async def test_get_not_found(self):
        mock_repo = AsyncMock()
        mock_repo.get_by_id.return_value = None
        service = RelationService(mock_repo)

        result = await service.get("nonexistent")
        assert result is None


class TestRelationServiceList:
    async def test_list_all(self):
        mock_repo = AsyncMock()
        mock_repo.list_by_world.return_value = [_make_relation()]
        service = RelationService(mock_repo)

        result = await service.list_by_world("w-001")
        assert len(result) == 1

    async def test_list_filter_by_character(self):
        mock_repo = AsyncMock()
        mock_repo.list_by_world.return_value = [_make_relation()]
        service = RelationService(mock_repo)

        result = await service.list_by_world("w-001", character_id="a-001")
        assert len(result) == 1
        mock_repo.list_by_world.assert_called_once_with("w-001", "a-001")


class TestRelationServiceUpdate:
    async def test_update_returns_updated(self):
        mock_repo = AsyncMock()
        mock_repo.update.return_value = _make_relation(rel_type="上下级")
        service = RelationService(mock_repo)

        result = await service.update("rel-001", UpdateRelationRequest(type="上下级"))
        assert result is not None

    async def test_update_not_found(self):
        mock_repo = AsyncMock()
        mock_repo.update.return_value = None
        service = RelationService(mock_repo)

        result = await service.update("nonexistent", UpdateRelationRequest(type="x"))
        assert result is None

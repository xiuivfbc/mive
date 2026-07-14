"""Tests for CharacterService Redis cache integration."""

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock

from src.models.character import Character, CreateCharacterRequest, UpdateCharacterRequest
from src.services.character_service import CharacterService


def _make_character(char_id: str | None = None, name: str = "叶文洁") -> Character:
    return Character(
        id=char_id or str(uuid.uuid4()),
        world_id=str(uuid.uuid4()),
        name=name,
        profile={"basic": {"name": name}, "brief": "", "detail": ""},
        created_at=datetime.now(UTC),
        updated_at=datetime.now(UTC),
    )


class TestCharacterServiceCacheOnCreate:
    async def test_create_populates_cache(self):
        """Creating a character should populate the Redis name cache."""
        redis = AsyncMock()
        redis.set.return_value = True
        mock_repo = AsyncMock()
        char = _make_character()
        mock_repo.create.return_value = char
        service = CharacterService(mock_repo, redis=redis)

        result = await service.create(str(uuid.uuid4()), CreateCharacterRequest(name="叶文洁"))

        assert result.name == "叶文洁"
        redis.set.assert_called_once()
        call_args = redis.set.call_args
        assert call_args[0][0] == f"char_name:{char.id}"
        assert call_args[0][1] == "叶文洁"

    async def test_create_no_redis_noop(self):
        """Creating without Redis should not fail."""
        mock_repo = AsyncMock()
        mock_repo.create.return_value = _make_character()
        service = CharacterService(mock_repo, redis=None)

        result = await service.create(str(uuid.uuid4()), CreateCharacterRequest(name="叶文洁"))

        assert result.name == "叶文洁"


class TestCharacterServiceCacheOnUpdate:
    async def test_update_name_updates_cache(self):
        """Updating name should update the cache with the new name."""
        redis = AsyncMock()
        redis.set.return_value = True
        mock_repo = AsyncMock()
        char = _make_character(name="新名字")
        mock_repo.update.return_value = char
        service = CharacterService(mock_repo, redis=redis)

        result = await service.update(
            char.id,
            UpdateCharacterRequest(name="新名字"),
            fields_set={"name"},
        )

        assert result.name == "新名字"
        redis.set.assert_called_once()
        call_args = redis.set.call_args
        assert call_args[0][0] == f"char_name:{char.id}"
        assert call_args[0][1] == "新名字"

    async def test_update_without_name_change_no_cache_write(self):
        """Updating profile without name change should not write to cache."""
        redis = AsyncMock()
        mock_repo = AsyncMock()
        char = _make_character()
        mock_repo.update.return_value = char
        service = CharacterService(mock_repo, redis=redis)

        await service.update(
            char.id,
            UpdateCharacterRequest(profile={"brief": "new"}),
            fields_set={"profile"},
        )

        redis.set.assert_not_called()

    async def test_update_name_legacy_mode_updates_cache(self):
        """Legacy mode (no fields_set) with name should update cache."""
        redis = AsyncMock()
        redis.set.return_value = True
        mock_repo = AsyncMock()
        char = _make_character(name="新名字")
        mock_repo.update.return_value = char
        service = CharacterService(mock_repo, redis=redis)

        await service.update(char.id, UpdateCharacterRequest(name="新名字"))

        redis.set.assert_called_once()


class TestCharacterServiceCacheOnDelete:
    async def test_delete_invalidates_cache(self):
        """Deleting a character should invalidate the cache."""
        redis = AsyncMock()
        redis.delete.return_value = 1
        mock_repo = AsyncMock()
        char = _make_character()
        mock_repo.get_by_id.return_value = char
        mock_repo.delete.return_value = True

        # Mock session that returns empty result for event reference check
        mock_session = AsyncMock()
        mock_result = MagicMock()
        mock_result.all.return_value = []
        mock_session.execute = AsyncMock(return_value=mock_result)

        service = CharacterService(mock_repo, session=mock_session, redis=redis)

        result = await service.delete(char.id)

        assert result is True
        redis.delete.assert_called_once_with(f"char_name:{char.id}")

    async def test_delete_all_by_world_invalidates_cache(self):
        """Deleting all characters in a world should invalidate their caches."""
        redis = AsyncMock()
        redis.delete.return_value = 2
        mock_repo = AsyncMock()
        chars = [_make_character(name="A"), _make_character(name="B")]
        mock_repo.list_by_world.return_value = chars
        mock_repo.delete_all_by_world.return_value = 2
        session = AsyncMock()
        session.execute = AsyncMock(return_value=MagicMock(all=MagicMock(return_value=[])))
        service = CharacterService(mock_repo, session=session, redis=redis)

        result = await service.delete_all_by_world(str(uuid.uuid4()))

        assert result == 2
        redis.delete.assert_called_once()
        # Verify all char IDs were passed
        call_args = redis.delete.call_args[0]
        assert len(call_args) == 2

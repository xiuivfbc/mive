"""Tests for character_name_cache utility."""

from unittest.mock import AsyncMock, MagicMock

from src.utils.character_name_cache import (
    _CACHE_PREFIX,
    _CACHE_TTL,
    get_character_name,
    get_character_names,
    invalidate_character_name,
    invalidate_character_names,
    set_character_name,
)


def _mock_redis() -> AsyncMock:
    """Create a mock Redis client with common defaults."""
    redis = AsyncMock()
    redis.get.return_value = None
    redis.mget.return_value = []
    redis.set.return_value = True
    redis.delete.return_value = 1
    return redis


def _mock_character(char_id: str, name: str) -> MagicMock:
    """Create a mock Character object."""
    char = MagicMock()
    char.id = char_id
    char.name = name
    return char


class TestGetCharacterName:
    async def test_cache_hit(self):
        """Returns name from Redis when cached."""
        redis = _mock_redis()
        redis.get.return_value = "叶文洁"

        result = await get_character_name("char-123", redis=redis)

        assert result == "叶文洁"
        redis.get.assert_called_once_with(f"{_CACHE_PREFIX}char-123")

    async def test_cache_hit_bytes(self):
        """Handles bytes returned from Redis."""
        redis = _mock_redis()
        redis.get.return_value = "罗辑".encode()

        result = await get_character_name("char-456", redis=redis)

        assert result == "罗辑"

    async def test_cache_miss_db_hit(self):
        """Falls back to DB on cache miss and populates cache."""
        redis = _mock_redis()
        redis.get.return_value = None
        char_repo = AsyncMock()
        char_repo.get_by_id.return_value = _mock_character("char-789", "程心")

        result = await get_character_name("char-789", redis=redis, character_repo=char_repo)

        assert result == "程心"
        char_repo.get_by_id.assert_called_once_with("char-789")
        redis.set.assert_called_once_with(f"{_CACHE_PREFIX}char-789", "程心", ex=_CACHE_TTL)

    async def test_cache_miss_db_miss(self):
        """Returns None when both cache and DB miss."""
        redis = _mock_redis()
        redis.get.return_value = None
        char_repo = AsyncMock()
        char_repo.get_by_id.return_value = None

        result = await get_character_name("char-unknown", redis=redis, character_repo=char_repo)

        assert result is None
        redis.set.assert_not_called()

    async def test_no_redis_db_hit(self):
        """Works without Redis, using DB directly."""
        char_repo = AsyncMock()
        char_repo.get_by_id.return_value = _mock_character("char-111", "云天明")

        result = await get_character_name("char-111", redis=None, character_repo=char_repo)

        assert result == "云天明"

    async def test_no_redis_no_repo(self):
        """Returns None when neither Redis nor repo available."""
        result = await get_character_name("char-999", redis=None, character_repo=None)

        assert result is None

    async def test_redis_error_falls_back_to_db(self):
        """Gracefully falls back to DB when Redis throws."""
        redis = _mock_redis()
        redis.get.side_effect = Exception("connection refused")
        char_repo = AsyncMock()
        char_repo.get_by_id.return_value = _mock_character("char-err", "章北海")

        result = await get_character_name("char-err", redis=redis, character_repo=char_repo)

        assert result == "章北海"


class TestGetCharacterNames:
    async def test_all_cache_hits(self):
        """Returns all names from Redis mget."""
        redis = _mock_redis()
        redis.mget.return_value = ["叶文洁".encode(), "罗辑".encode(), None]

        char_repo = AsyncMock()
        char_repo.get_by_id.return_value = _mock_character("c3", "程心")

        result = await get_character_names(
            ["c1", "c2", "c3"], redis=redis, character_repo=char_repo
        )

        assert result == {"c1": "叶文洁", "c2": "罗辑", "c3": "程心"}
        redis.mget.assert_called_once()
        char_repo.get_by_id.assert_called_once_with("c3")

    async def test_empty_ids(self):
        """Returns empty dict for empty input."""
        redis = _mock_redis()

        result = await get_character_names([], redis=redis)

        assert result == {}
        redis.mget.assert_not_called()

    async def test_no_redis(self):
        """Works without Redis, using DB for all."""
        char_repo = AsyncMock()
        char_repo.get_by_id.side_effect = [
            _mock_character("c1", "叶文洁"),
            _mock_character("c2", "罗辑"),
        ]

        result = await get_character_names(["c1", "c2"], redis=None, character_repo=char_repo)

        assert result == {"c1": "叶文洁", "c2": "罗辑"}
        assert char_repo.get_by_id.call_count == 2

    async def test_redis_error_falls_back(self):
        """Gracefully falls back to DB when Redis mget throws."""
        redis = _mock_redis()
        redis.mget.side_effect = Exception("timeout")
        char_repo = AsyncMock()
        char_repo.get_by_id.return_value = _mock_character("c1", "叶文洁")

        result = await get_character_names(["c1"], redis=redis, character_repo=char_repo)

        assert result == {"c1": "叶文洁"}

    async def test_db_miss_for_some(self):
        """Handles partial DB misses gracefully."""
        redis = _mock_redis()
        redis.mget.return_value = [None, None]
        char_repo = AsyncMock()
        char_repo.get_by_id.side_effect = [
            _mock_character("c1", "叶文洁"),
            None,  # c2 not found
        ]

        result = await get_character_names(["c1", "c2"], redis=redis, character_repo=char_repo)

        assert result == {"c1": "叶文洁"}


class TestSetCharacterName:
    async def test_sets_cache(self):
        """Sets name in Redis with TTL."""
        redis = _mock_redis()

        await set_character_name("char-123", "叶文洁", redis=redis)

        redis.set.assert_called_once_with(f"{_CACHE_PREFIX}char-123", "叶文洁", ex=_CACHE_TTL)

    async def test_no_redis_noop(self):
        """No-op when Redis is None."""
        await set_character_name("char-123", "叶文洁", redis=None)

    async def test_redis_error_noop(self):
        """No-op when Redis throws."""
        redis = _mock_redis()
        redis.set.side_effect = Exception("write failed")

        # Should not raise
        await set_character_name("char-123", "叶文洁", redis=redis)


class TestInvalidateCharacterName:
    async def test_deletes_key(self):
        """Deletes the cache key."""
        redis = _mock_redis()

        await invalidate_character_name("char-123", redis=redis)

        redis.delete.assert_called_once_with(f"{_CACHE_PREFIX}char-123")

    async def test_no_redis_noop(self):
        """No-op when Redis is None."""
        await invalidate_character_name("char-123", redis=None)

    async def test_redis_error_noop(self):
        """No-op when Redis throws."""
        redis = _mock_redis()
        redis.delete.side_effect = Exception("delete failed")

        # Should not raise
        await invalidate_character_name("char-123", redis=redis)


class TestInvalidateCharacterNames:
    async def test_deletes_multiple_keys(self):
        """Deletes multiple cache keys."""
        redis = _mock_redis()

        await invalidate_character_names(["c1", "c2", "c3"], redis=redis)

        redis.delete.assert_called_once_with(
            f"{_CACHE_PREFIX}c1", f"{_CACHE_PREFIX}c2", f"{_CACHE_PREFIX}c3"
        )

    async def test_empty_ids_noop(self):
        """No-op for empty list."""
        redis = _mock_redis()

        await invalidate_character_names([], redis=redis)

        redis.delete.assert_not_called()

    async def test_no_redis_noop(self):
        """No-op when Redis is None."""
        await invalidate_character_names(["c1"], redis=None)

    async def test_redis_error_noop(self):
        """No-op when Redis throws."""
        redis = _mock_redis()
        redis.delete.side_effect = Exception("delete failed")

        # Should not raise
        await invalidate_character_names(["c1", "c2"], redis=redis)

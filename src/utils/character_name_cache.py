"""Redis-backed cache for character names.

Reduces DB lookups when resolving sender names in messages, dialogues, and events.
Falls back to direct DB queries if Redis is unavailable.

Key format: ``char_name:{character_id}``
TTL: 3600 seconds (1 hour)
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from src.db.repositories.character_repo import CharacterRepository

logger = logging.getLogger(__name__)

_CACHE_PREFIX = "char_name:"
_CACHE_TTL = 3600  # 1 hour


async def get_character_name(
    character_id: str,
    *,
    redis: Redis | None,
    character_repo: CharacterRepository | None = None,
) -> str | None:
    """Return character name from cache, falling back to DB on miss.

    Parameters
    ----------
    character_id:
        The character UUID string.
    redis:
        Async Redis client.  If ``None``, falls through to DB.
    character_repo:
        Repository used on cache miss.  If ``None`` and cache misses, returns ``None``.
    """
    if redis is not None:
        try:
            cached = await redis.get(f"{_CACHE_PREFIX}{character_id}")
            if cached is not None:
                return cached.decode("utf-8") if isinstance(cached, bytes) else cached
        except Exception:
            logger.debug("Redis get failed for char_name:%s, falling back to DB", character_id)

    # Cache miss or no Redis — try DB
    if character_repo is not None:
        try:
            char = await character_repo.get_by_id(character_id)
            if char:
                # Best-effort populate cache
                if redis is not None:
                    try:
                        await redis.set(
                            f"{_CACHE_PREFIX}{character_id}",
                            char.name,
                            ex=_CACHE_TTL,
                        )
                    except Exception:
                        pass
                return char.name
        except Exception:
            logger.debug("DB lookup failed for character %s", character_id)

    return None


async def get_character_names(
    character_ids: list[str],
    *,
    redis: Redis | None,
    character_repo: CharacterRepository | None = None,
) -> dict[str, str]:
    """Batch-fetch character names.  Returns ``{id: name}`` for all found IDs.

    Uses ``MGET`` for the Redis leg, then falls back to DB for any misses.
    """
    if not character_ids:
        return {}

    result: dict[str, str] = {}
    ids_to_fetch: list[str] = list(character_ids)

    if redis is not None:
        try:
            keys = [f"{_CACHE_PREFIX}{cid}" for cid in ids_to_fetch]
            values = await redis.mget(keys)
            still_missed: list[str] = []
            for cid, val in zip(ids_to_fetch, values, strict=False):
                if val is not None:
                    result[cid] = val.decode("utf-8") if isinstance(val, bytes) else val
                else:
                    still_missed.append(cid)
            ids_to_fetch = still_missed
        except Exception:
            logger.debug("Redis mget failed for char_name batch, falling back to DB")

    # DB fallback for cache misses
    if ids_to_fetch and character_repo is not None:
        for cid in ids_to_fetch:
            try:
                char = await character_repo.get_by_id(cid)
                if char:
                    result[cid] = char.name
                    # Best-effort populate
                    if redis is not None:
                        try:
                            await redis.set(f"{_CACHE_PREFIX}{cid}", char.name, ex=_CACHE_TTL)
                        except Exception:
                            pass
            except Exception:
                logger.debug("DB lookup failed for character %s", cid)

    return result


async def set_character_name(
    character_id: str,
    name: str,
    *,
    redis: Redis | None,
) -> None:
    """Store a character name in cache."""
    if redis is None:
        return
    try:
        await redis.set(f"{_CACHE_PREFIX}{character_id}", name, ex=_CACHE_TTL)
    except Exception:
        logger.debug("Redis set failed for char_name:%s", character_id)


async def invalidate_character_name(
    character_id: str,
    *,
    redis: Redis | None,
) -> None:
    """Remove a character name from cache."""
    if redis is None:
        return
    try:
        await redis.delete(f"{_CACHE_PREFIX}{character_id}")
    except Exception:
        logger.debug("Redis delete failed for char_name:%s", character_id)


async def resolve_message_sender_names(
    messages: list,
    redis: Redis | None = None,
    character_repo: CharacterRepository | None = None,
) -> None:
    """Resolve sender_name for character-type messages in-place.

    Mutates messages list directly. Uses character_name_cache for lookup.
    """
    sender_ids = {m.sender_id for m in messages if m.sender_id and m.sender_type == "character"}
    if not sender_ids or character_repo is None:
        return
    name_map = await get_character_names(
        list(sender_ids), redis=redis, character_repo=character_repo
    )
    for m in messages:
        if m.sender_id and m.sender_type == "character":
            resolved = name_map.get(m.sender_id)
            if resolved:
                m.sender_name = resolved


async def invalidate_character_names(
    character_ids: list[str],
    *,
    redis: Redis | None,
) -> None:
    """Batch-remove character names from cache."""
    if redis is None or not character_ids:
        return
    try:
        keys = [f"{_CACHE_PREFIX}{cid}" for cid in character_ids]
        await redis.delete(*keys)
    except Exception:
        logger.debug("Redis batch delete failed for char_name keys")

from __future__ import annotations

import logging
from datetime import datetime
from typing import TYPE_CHECKING

from sqlalchemy.ext.asyncio import AsyncSession

from src.db.repositories.character_repo import CharacterRepository
from src.models.character import Character, CreateCharacterRequest, UpdateCharacterRequest

if TYPE_CHECKING:
    from redis.asyncio import Redis

logger = logging.getLogger(__name__)


def _strip_name_tier_from_profile(profile: dict | None) -> dict | None:
    """Remove name and tier from profile.basic to avoid duplication with row-level columns."""
    if profile is None:
        return None
    basic = profile.get("basic")
    if basic is None:
        return profile
    # Work on a shallow copy to avoid mutating the caller's dict
    new_basic = {k: v for k, v in basic.items() if k not in ("name", "tier")}
    return {**profile, "basic": new_basic}


class CharacterService:
    def __init__(
        self,
        repo: CharacterRepository,
        session: AsyncSession | None = None,
        redis: Redis | None = None,
    ):
        self.repo = repo
        self._session = session
        self._redis = redis

    async def create(self, world_id: str, req: CreateCharacterRequest) -> Character:
        if req.profile is not None:
            req = CreateCharacterRequest(
                name=req.name,
                portrait_url=req.portrait_url,
                profile=_strip_name_tier_from_profile(req.profile),
            )
        char = await self.repo.create(world_id, req)
        # Populate name cache for newly created character
        if self._redis is not None:
            try:
                from src.utils.character_name_cache import set_character_name

                await set_character_name(char.id, char.name, redis=self._redis)
            except Exception:
                pass
        return char

    async def get(self, character_id: str) -> Character | None:
        return await self.repo.get_by_id(character_id)

    async def list_by_world(self, world_id: str) -> list[Character]:
        return await self.repo.list_by_world(world_id)

    async def max_updated_at(self, world_id: str) -> datetime | None:
        return await self.repo.max_updated_at(world_id)

    async def update(
        self,
        character_id: str,
        req: UpdateCharacterRequest,
        fields_set: set[str] | None = None,
    ) -> Character | None:
        if req.profile is not None:
            req = UpdateCharacterRequest(
                name=req.name,
                portrait_url=req.portrait_url,
                profile=_strip_name_tier_from_profile(req.profile),
                tier=req.tier,
            )
        # Invalidate cache if name is being changed
        name_changing = (
            fields_set is not None and "name" in fields_set and req.name is not None
        ) or (fields_set is None and req.name is not None)
        result = await self.repo.update(character_id, req, fields_set)
        if result and name_changing and self._redis is not None:
            try:
                from src.utils.character_name_cache import set_character_name

                await set_character_name(character_id, result.name, redis=self._redis)
            except Exception:
                pass
        return result

    async def delete(self, character_id: str) -> bool:
        char = await self.repo.get_by_id(character_id)
        if char is None:
            return False

        result = await self.repo.delete(character_id)
        if result and self._redis is not None:
            try:
                from src.utils.character_name_cache import invalidate_character_name

                await invalidate_character_name(character_id, redis=self._redis)
            except Exception:
                pass
        return result

    async def delete_non_user_characters(self, world_id: str, exclude_id: str) -> int:
        """Delete all non-user characters in a world."""
        all_chars = await self.repo.list_by_world(world_id)
        to_delete_ids = [c.id for c in all_chars if c.id != exclude_id]

        if not to_delete_ids:
            return 0

        result = await self.repo.delete_non_user_characters(world_id, exclude_id)
        # Invalidate cache for deleted characters
        if result > 0 and self._redis is not None:
            try:
                from src.utils.character_name_cache import invalidate_character_names

                await invalidate_character_names(to_delete_ids, redis=self._redis)
            except Exception:
                pass
        return result

    async def delete_all_by_world(self, world_id: str) -> int:
        """Delete all characters in a world."""
        all_chars = await self.repo.list_by_world(world_id)
        all_ids = [c.id for c in all_chars]

        result = await self.repo.delete_all_by_world(world_id)
        # Invalidate cache for all deleted characters
        if result > 0 and self._redis is not None:
            try:
                from src.utils.character_name_cache import invalidate_character_names

                await invalidate_character_names(all_ids, redis=self._redis)
            except Exception:
                pass
        return result

    async def force_delete_non_user_characters(self, world_id: str, exclude_id: str) -> int:
        """Force-delete non-user characters in a world.

        This is the safe path for generation_service and version_service:
        delegates directly to the repo for deletion.
        """
        all_chars = await self.repo.list_by_world(world_id)
        to_delete_ids = [c.id for c in all_chars if c.id != exclude_id]
        result = await self.repo.delete_non_user_characters(world_id, exclude_id)
        # Invalidate cache for deleted characters
        if result > 0 and self._redis is not None:
            try:
                from src.utils.character_name_cache import invalidate_character_names

                await invalidate_character_names(to_delete_ids, redis=self._redis)
            except Exception:
                pass
        return result

    async def force_delete_all_by_world(self, world_id: str) -> int:
        """Force-delete all characters in a world.

        This is the safe path for generation_service and version_service:
        delegates directly to the repo for deletion.
        """
        all_chars = await self.repo.list_by_world(world_id)
        all_ids = [c.id for c in all_chars]
        result = await self.repo.delete_all_by_world(world_id)
        # Invalidate cache for all deleted characters
        if result > 0 and self._redis is not None:
            try:
                from src.utils.character_name_cache import invalidate_character_names

                await invalidate_character_names(all_ids, redis=self._redis)
            except Exception:
                pass
        return result

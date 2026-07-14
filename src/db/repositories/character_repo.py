import uuid
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import M2Character
from src.models.character import Character, CreateCharacterRequest, UpdateCharacterRequest


class CharacterRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, world_id: str, req: CreateCharacterRequest) -> Character:
        profile = req.profile or {}
        # Extract tier from profile.basic for the row-level column (backward compat)
        tier = profile.get("basic", {}).get("tier")
        # Strip name and tier from profile.basic to avoid duplication with row-level columns
        basic = profile.get("basic")
        if basic is not None:
            cleaned_basic = {k: v for k, v in basic.items() if k not in ("name", "tier")}
            profile = {**profile, "basic": cleaned_basic}
        row = M2Character(
            world_id=uuid.UUID(world_id),
            name=req.name,
            portrait_url=req.portrait_url,
            profile=profile,
            tier=tier,
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return self._to_model(row)

    async def get_by_id(self, character_id: str) -> Character | None:
        row = await self.session.get(M2Character, uuid.UUID(character_id))
        if row is None:
            return None
        return self._to_model(row)

    async def list_by_world(self, world_id: str, *, include_extra: bool = True) -> list[Character]:
        stmt = (
            select(M2Character)
            .where(M2Character.world_id == uuid.UUID(world_id))
            .order_by(M2Character.created_at)
        )
        if not include_extra:
            stmt = stmt.where(M2Character.tier.isnot(None)).where(
                func.lower(M2Character.tier) != "extra"
            )
        result = await self.session.execute(stmt)
        return [self._to_model(row) for row in result.scalars().all()]

    async def max_updated_at(self, world_id: str) -> datetime | None:
        """Return MAX(updated_at) for all characters in a world (for conditional caching)."""
        stmt = select(func.max(M2Character.updated_at)).where(
            M2Character.world_id == uuid.UUID(world_id)
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def update(
        self,
        character_id: str,
        req: UpdateCharacterRequest,
        fields_set: set[str] | None = None,
    ) -> Character | None:
        row = await self.session.get(M2Character, uuid.UUID(character_id))
        if row is None:
            return None
        if fields_set is not None:
            # Explicit fields tracking: only update fields the caller actually provided
            if "name" in fields_set:
                if req.name is None:
                    raise ValueError("name 不能为空")
                row.name = req.name
            if "portrait_url" in fields_set:
                row.portrait_url = req.portrait_url
            if "profile" in fields_set:
                if req.profile is None:
                    raise ValueError("profile 不能为空")
                row.profile = req.profile
            if "tier" in fields_set:
                row.tier = req.tier
        else:
            # Legacy fallback: update all non-None fields
            if req.name is not None:
                row.name = req.name
            if req.portrait_url is not None:
                row.portrait_url = req.portrait_url
            if req.profile is not None:
                row.profile = req.profile
            if req.tier is not None:
                row.tier = req.tier
        await self.session.flush()
        await self.session.refresh(row)
        return self._to_model(row)

    async def delete(self, character_id: str) -> bool:
        row = await self.session.get(M2Character, uuid.UUID(character_id))
        if row is None:
            return False
        await self.session.delete(row)
        await self.session.flush()
        return True

    async def delete_all_by_world(self, world_id: str) -> int:
        """删除某个世界的所有角色，返回删除数量"""
        from sqlalchemy import delete

        stmt = delete(M2Character).where(M2Character.world_id == uuid.UUID(world_id))
        result = await self.session.execute(stmt)
        await self.session.flush()
        return cast(CursorResult, result).rowcount

    async def bulk_create(self, world_id: str, characters: list[dict]) -> list[Character]:
        """批量创建角色，返回创建的角色列表"""
        rows = []
        for char_data in characters:
            profile = char_data.get("profile", {})
            tier = char_data.get("tier") or profile.get("basic", {}).get("tier")
            # Strip name and tier from profile.basic to avoid duplication with row-level columns
            basic = profile.get("basic")
            if basic is not None:
                cleaned_basic = {k: v for k, v in basic.items() if k not in ("name", "tier")}
                profile = {**profile, "basic": cleaned_basic}
            row = M2Character(
                id=uuid.UUID(char_data["id"]) if "id" in char_data else uuid.uuid4(),
                world_id=uuid.UUID(world_id),
                name=char_data["name"],
                portrait_url=char_data.get("portrait_url"),
                profile=profile,
                tier=tier,
                entity_type=char_data.get("entity_type", "character"),
                graph_node_uuid=char_data.get("graph_node_uuid"),
            )
            self.session.add(row)
            rows.append(row)
        await self.session.flush()
        for row in rows:
            await self.session.refresh(row)
        return [self._to_model(row) for row in rows]

    async def delete_non_user_characters(self, world_id: str, exclude_id: str) -> int:
        """删除世界内除 exclude_id 之外的所有角色（保留用户角色），返回删除数量。"""
        from sqlalchemy import delete

        stmt = (
            delete(M2Character)
            .where(M2Character.world_id == uuid.UUID(world_id))
            .where(M2Character.id != uuid.UUID(exclude_id))
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return cast(CursorResult, result).rowcount

    async def delete_graph_entities_by_world(self, world_id: str) -> int:
        """删除该世界所有从 Zep 图谱导入的角色（graph_node_uuid 非空）。"""
        from sqlalchemy import delete

        stmt = (
            delete(M2Character)
            .where(M2Character.world_id == uuid.UUID(world_id))
            .where(M2Character.graph_node_uuid.isnot(None))
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return cast(CursorResult, result).rowcount

    async def find_by_name(self, world_id: str, name: str) -> Character | None:
        result = await self.session.execute(
            select(M2Character).where(
                M2Character.world_id == uuid.UUID(world_id),
                M2Character.name == name,
            )
        )
        row = result.scalar_one_or_none()
        return self._to_model(row) if row else None

    async def update_profile(self, character_id: str, profile: dict) -> None:
        def _utcnow() -> datetime:
            return datetime.now(UTC).replace(tzinfo=None)

        await self.session.execute(
            update(M2Character)
            .where(M2Character.id == uuid.UUID(character_id))
            .values(profile=profile, updated_at=_utcnow())
        )

    def _to_model(self, row: M2Character) -> Character:
        return Character(
            id=str(row.id),
            world_id=str(row.world_id),
            name=row.name,
            portrait_url=row.portrait_url,
            profile=row.profile,
            graph_node_uuid=row.graph_node_uuid,
            entity_type=row.entity_type or "character",
            tier=row.tier,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

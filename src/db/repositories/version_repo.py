import uuid
from typing import cast

from sqlalchemy import delete, func, select, text, update
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import M2WorldVersion
from src.models.proposal import WorldVersion


class VersionRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        world_id: str,
        snapshot: dict,
        created_by: str | None = None,
        summary: str | None = None,
        parent_version_id: str | None = None,
    ) -> WorldVersion:
        row = M2WorldVersion(
            world_id=uuid.UUID(world_id),
            parent_version_id=uuid.UUID(parent_version_id) if parent_version_id else None,
            created_by=created_by,
            summary=summary,
            snapshot=snapshot,
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return self._to_model(row)

    async def get_by_id(self, version_id: str) -> WorldVersion | None:
        row = await self.session.get(M2WorldVersion, uuid.UUID(version_id))
        if row is None:
            return None
        return self._to_model(row)

    async def get_latest(self, world_id: str) -> WorldVersion | None:
        stmt = (
            select(M2WorldVersion)
            .where(M2WorldVersion.world_id == uuid.UUID(world_id))
            .order_by(M2WorldVersion.created_at.desc())
            .limit(1)
        )
        result = await self.session.execute(stmt)
        row = result.scalar_one_or_none()
        if row is None:
            return None
        return self._to_model(row)

    async def list_by_world(self, world_id: str) -> list[WorldVersion]:
        stmt = (
            select(M2WorldVersion)
            .where(M2WorldVersion.world_id == uuid.UUID(world_id))
            .order_by(M2WorldVersion.created_at)
        )
        result = await self.session.execute(stmt)
        return [self._to_model(row) for row in result.scalars().all()]

    async def update_summary(self, version_id: str, summary: str | None) -> WorldVersion | None:
        row = await self.session.get(M2WorldVersion, uuid.UUID(version_id))
        if row is None:
            return None
        row.summary = summary
        await self.session.flush()
        await self.session.refresh(row)
        return self._to_model(row)

    async def is_latest(self, version_id: str, world_id: str) -> bool:
        """Check if version_id is the latest version for the world."""
        latest = await self.get_latest(world_id)
        return latest is not None and latest.id == version_id

    async def delete(self, version_id: str) -> bool:
        """Delete a version row. Returns True if deleted."""
        row = await self.session.get(M2WorldVersion, uuid.UUID(version_id))
        if row is None:
            return False
        await self.session.delete(row)
        await self.session.flush()
        return True

    def _to_model(self, row: M2WorldVersion) -> WorldVersion:
        return WorldVersion(
            id=str(row.id),
            world_id=str(row.world_id),
            parent_version_id=str(row.parent_version_id) if row.parent_version_id else None,
            created_by=row.created_by,
            summary=row.summary,
            snapshot=row.snapshot,
            created_at=row.created_at,
        )

    # ── Snapshot helpers (moved from VersionService) ────────────────────

    async def get_dialogue_metadata(self, world_id: str) -> list[dict]:
        """Build dialogue session metadata for snapshot (session-level, no message bodies).

        Moved from VersionService.create_snapshot.
        """
        from src.db.models import M4ChatSession, M4Message

        stmt = (
            select(
                M4ChatSession.id,
                M4ChatSession.type,
                M4ChatSession.title,
                M4ChatSession.created_at,
            )
            .where(M4ChatSession.world_id == uuid.UUID(world_id))
            .order_by(M4ChatSession.created_at)
        )
        session_rows = (await self.session.execute(stmt)).all()
        dialogues: list[dict] = []
        for row in session_rows:
            msg_count_result = await self.session.execute(
                select(func.count()).where(M4Message.session_id == row.id)
            )
            msg_count = msg_count_result.scalar_one()

            last_msg_result = await self.session.execute(
                select(M4Message.real_time)
                .where(M4Message.session_id == row.id)
                .order_by(M4Message.real_time.desc())
                .limit(1)
            )
            last_msg_at = last_msg_result.scalar_one_or_none()

            dialogues.append(
                {
                    "session_id": str(row.id),
                    "type": row.type,
                    "title": row.title,
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "message_count": msg_count,
                    "last_message_at": last_msg_at.isoformat() if last_msg_at else None,
                }
            )
        return dialogues

    async def update_synced_generation(self, version_id: str, generation: int) -> None:
        """Write synced_generation into a version row."""
        await self.session.execute(
            text("UPDATE m2_world_versions SET synced_generation = :gen WHERE id = :vid"),
            {"gen": generation, "vid": str(version_id)},
        )

    async def count_active_characters(self, world_id: str) -> int:
        from src.db.models import M2Character

        result = await self.session.execute(
            select(func.count()).where(M2Character.world_id == uuid.UUID(world_id))
        )
        return result.scalar_one()

    async def count_memories(self, world_id: str) -> int:
        from src.db.models import M2CharacterMemory

        result = await self.session.execute(
            select(func.count()).where(M2CharacterMemory.world_id == uuid.UUID(world_id))
        )
        return result.scalar_one()

    async def count_sessions(self, world_id: str) -> int:
        from src.db.models import M4ChatSession

        result = await self.session.execute(
            select(func.count()).where(M4ChatSession.world_id == uuid.UUID(world_id))
        )
        return result.scalar_one()

    async def count_messages(self, world_id: str) -> int:
        from src.db.models import M4Message

        result = await self.session.execute(
            select(func.count()).where(M4Message.world_id == uuid.UUID(world_id))
        )
        return result.scalar_one()

    async def delete_memories_by_character_ids(self, char_ids: list[str]) -> int:
        from src.db.models import M2CharacterMemory

        if not char_ids:
            return 0
        uuids = [uuid.UUID(cid) for cid in char_ids]
        stmt = delete(M2CharacterMemory).where(M2CharacterMemory.character_id.in_(uuids))
        result = await self.session.execute(stmt)
        await self.session.flush()
        return cast(CursorResult, result).rowcount

    async def update_characters_tier(self, char_tier_map: dict[str, str]) -> None:
        from src.db.models import M2Character

        for char_id, tier in char_tier_map.items():
            await self.session.execute(
                update(M2Character).where(M2Character.id == uuid.UUID(char_id)).values(tier=tier)
            )
        await self.session.flush()

    async def delete_characters_by_ids(self, char_ids: list[str]) -> int:
        from src.db.models import M2Character

        if not char_ids:
            return 0
        uuids = [uuid.UUID(cid) for cid in char_ids]
        stmt = delete(M2Character).where(M2Character.id.in_(uuids))
        result = await self.session.execute(stmt)
        await self.session.flush()
        return cast(CursorResult, result).rowcount

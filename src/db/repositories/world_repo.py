import uuid
from datetime import datetime

from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import M1World
from src.models.world import WorldDoc


class WorldRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def save(self, world: WorldDoc, user_id: str | None) -> str:
        world_dict = world.model_dump(mode="json")
        element_summary = {
            "count": len(world.elements),
            "briefs": [
                {"id": e.id, "category": e.category, "name": e.name, "brief": e.brief}
                for e in world.elements[:3]
            ],
        }
        row = M1World(
            id=uuid.UUID(world.world_id),
            user_id=(
                uuid.UUID(user_id) if user_id else uuid.UUID("00000000-0000-0000-0000-000000000000")
            ),
            title=world.source.title or "",
            source_info={
                "title": world.source.title,
                "author": world.source.author,
                "type": world.source.type,
                "references": world.source.references,
            },
            world_doc=world_dict,
            element_summary=element_summary,
            world_base_id=uuid.UUID(world.world_base_id) if world.world_base_id else None,
            status="active",
            scale=world.scale,
        )

        existing = await self.session.get(M1World, row.id)
        if existing:
            existing.world_doc = world_dict
            existing.title = world.source.title or ""
            existing.source_info = row.source_info
            existing.element_summary = element_summary
            existing.scale = world.scale
        else:
            self.session.add(row)

        await self.session.flush()
        return world.world_id

    async def count_by_user(self, user_id: uuid.UUID) -> int:
        """Return the number of active worlds for the given user."""
        from sqlalchemy import func, select

        stmt = (
            select(func.count())
            .select_from(M1World)
            .where(
                M1World.user_id == user_id,
                M1World.status == "active",
            )
        )
        result = await self.session.execute(stmt)
        return result.scalar() or 0

    async def list_by_user(self, user_id: str) -> list[dict]:
        """Return lightweight dicts for list view (no world_doc deserialization)."""
        from sqlalchemy import select

        stmt = (
            select(
                M1World.id,
                M1World.title,
                M1World.source_info,
                M1World.world_doc,
                M1World.element_summary,
                M1World.character_summary,
                M1World.relationship_summary,
                M1World.world_base_id,
                M1World.created_at,
                M1World.updated_at,
                M1World.scale,
            )
            .where(M1World.user_id == uuid.UUID(user_id))
            .order_by(M1World.created_at.desc())
        )
        result = await self.session.execute(stmt)
        rows = result.all()
        return [
            {
                "world_id": str(row.id),
                "world_base_id": str(row.world_base_id) if row.world_base_id else None,
                "version": "1.0",
                "source": {
                    "title": row.source_info.get("title") if row.source_info else row.title,
                    "author": row.source_info.get("author") if row.source_info else None,
                    "type": row.source_info.get("type") if row.source_info else None,
                    "references": row.source_info.get("references", []) if row.source_info else [],
                    "input_text": None,
                    "common_sense": (row.world_doc or {}).get("source", {}).get("common_sense"),
                    "plot_summary": (row.world_doc or {}).get("source", {}).get("plot_summary"),
                    "core_conflict": (row.world_doc or {}).get("source", {}).get("core_conflict"),
                    "tone_and_atmosphere": (row.world_doc or {})
                    .get("source", {})
                    .get("tone_and_atmosphere"),
                },
                "meta": {
                    "created_at": row.created_at.isoformat() if row.created_at else None,
                    "updated_at": row.updated_at.isoformat() if row.updated_at else None,
                    "last_analyzed_at": None,
                },
                "elements": [
                    {**b, "detail": ""}
                    for b in (row.element_summary.get("briefs", []) if row.element_summary else [])
                ],
                "element_count": row.element_summary.get("count", 0) if row.element_summary else 0,
                "character_count": row.character_summary.get("count", 0)
                if row.character_summary
                else 0,
                "relationship_count": row.relationship_summary.get("count", 0)
                if row.relationship_summary
                else 0,
                "scale": row.scale or "standard",
            }
            for row in rows
        ]

    async def get(self, world_id: str) -> WorldDoc | None:
        row = await self.session.get(M1World, uuid.UUID(world_id))
        if row is None:
            return None
        return self._to_world_doc(row)

    async def get_with_updated_at(self, world_id: str) -> tuple[WorldDoc, datetime] | None:
        """返回 (WorldDoc, row-level updated_at) 或 None。避免二次查询。"""
        row = await self.session.get(M1World, uuid.UUID(world_id))
        if row is None:
            return None
        return self._to_world_doc(row), row.updated_at

    async def get_by_id(self, world_id: str) -> M1World | None:
        try:
            return await self.session.get(M1World, uuid.UUID(world_id))
        except (ValueError, AttributeError):
            return None

    async def delete(self, world_id: str) -> bool:
        from sqlalchemy import delete as sa_delete

        from src.db.models import (
            M2Character,
            M2Relation,
            M2WorldVersion,
            M3Event,
            M4ChatSession,
            M4Message,
            M8CharacterWebhook,
            M8DiscordBinding,
        )

        try:
            world_uuid = uuid.UUID(world_id)
        except ValueError:
            return False

        row = await self.session.get(M1World, world_uuid)
        if row is None:
            return False

        # 按依赖顺序删除子表
        # Discord 相关表（无 CASCADE，必须显式删除）
        # 表可能不存在（迁移分支问题），静默忽略
        try:
            async with self.session.begin_nested():  # savepoint
                await self.session.execute(
                    sa_delete(M8CharacterWebhook).where(M8CharacterWebhook.world_id == world_uuid)
                )
                await self.session.execute(
                    sa_delete(M8DiscordBinding).where(M8DiscordBinding.world_id == world_uuid)
                )
        except Exception:
            pass  # 表不存在时忽略
        # 其余 RESTRICT 子表
        for model in (
            M4Message,
            M4ChatSession,
            M3Event,
            M2Relation,
            M2WorldVersion,
            M2Character,
        ):
            await self.session.execute(sa_delete(model).where(model.world_id == world_uuid))

        await self.session.delete(row)
        await self.session.flush()
        return True

    async def update_graph_fields(
        self,
        world_id: str,
        graph_id: str | None = None,
        graph_status: str | None = None,
    ) -> None:
        from datetime import UTC, datetime

        from sqlalchemy import update

        values: dict = {"graph_updated_at": datetime.now(UTC)}
        if graph_id is not None:
            values["graph_id"] = graph_id
        if graph_status is not None:
            values["graph_status"] = graph_status

        stmt = update(M1World).where(M1World.id == uuid.UUID(world_id)).values(**values)
        await self.session.execute(stmt)
        await self.session.flush()

    async def set_user_character(self, world_id: str, character_id: str) -> None:
        from sqlalchemy import update

        stmt = (
            update(M1World)
            .where(M1World.id == uuid.UUID(world_id))
            .values(user_character_id=uuid.UUID(character_id))
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def get_owner_id(self, world_id: str) -> str | None:
        from sqlalchemy import select

        try:
            stmt = select(M1World.user_id).where(M1World.id == uuid.UUID(world_id))
            result = await self.session.execute(stmt)
            row = result.scalar_one_or_none()
            return str(row) if row else None
        except ValueError:
            return None

    def _to_world_doc(self, row: M1World) -> WorldDoc:
        data = row.world_doc
        doc = WorldDoc.model_validate(data)
        # M6: populate graph fields from row-level columns
        doc.graph_id = row.graph_id
        doc.graph_ontology = row.graph_ontology
        doc.graph_status = row.graph_status or "idle"
        doc.graph_updated_at = row.graph_updated_at
        # M15: populate user_character_id from row-level column
        doc.user_character_id = str(row.user_character_id) if row.user_character_id else None
        # M17: populate is_banned from row-level column
        doc.is_banned = bool(row.is_banned)
        # M41: populate scale from row-level column
        doc.scale = row.scale or "standard"
        return doc

    async def create_stub(
        self,
        world_id: str,
        user_id: str,
        title: str,
        source_info: dict,
        scale: str = "standard",
    ) -> None:
        """创建状态为 creating 的空世界存根，供异步创建流程使用。"""
        from datetime import datetime

        now = datetime.utcnow()
        stub_doc = {
            "world_id": world_id,
            "version": "1.0",
            "source": source_info,
            "meta": {
                "created_at": now.isoformat(),
                "updated_at": now.isoformat(),
                "last_analyzed_at": None,
            },
            "elements": [],
        }
        row = M1World(
            id=uuid.UUID(world_id),
            user_id=uuid.UUID(user_id),
            title=title,
            source_info=source_info,
            world_doc=stub_doc,
            element_summary={"count": 0, "briefs": []},
            character_summary={"count": 0},
            relationship_summary={"count": 0},
            status="creating",
            scale=scale,
        )
        self.session.add(row)
        await self.session.flush()

    async def set_status(self, world_id: str, status: str) -> None:
        from sqlalchemy import update

        stmt = update(M1World).where(M1World.id == uuid.UUID(world_id)).values(status=status)
        await self.session.execute(stmt)
        await self.session.flush()

    async def update_counts(self, world_id: str, char_count: int, rel_count: int) -> None:
        """Update character_summary and relationship_summary for a world."""
        from sqlalchemy import update

        stmt = (
            update(M1World)
            .where(M1World.id == uuid.UUID(world_id))
            .values(
                character_summary={"count": char_count},
                relationship_summary={"count": rel_count},
            )
        )
        await self.session.execute(stmt)
        await self.session.flush()

    async def get_status(self, world_id: str) -> str | None:
        try:
            row = await self.session.get(M1World, uuid.UUID(world_id))
        except ValueError:
            return None
        return row.status if row else None

import uuid
from typing import cast

from sqlalchemy import or_, select
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import M2Relation
from src.models.enums import RelationStatus
from src.models.relation import CreateRelationRequest, Relation, UpdateRelationRequest


class RelationRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(self, world_id: str, req: CreateRelationRequest) -> Relation:
        row = M2Relation(
            world_id=uuid.UUID(world_id),
            character_a=uuid.UUID(req.character_a),
            character_b=uuid.UUID(req.character_b),
            type=req.type,
            direction=req.direction,
            description=req.description,
        )
        self.session.add(row)
        await self.session.flush()
        await self.session.refresh(row)
        return self._to_model(row)

    async def get_by_id(self, relation_id: str) -> Relation | None:
        row = await self.session.get(M2Relation, uuid.UUID(relation_id))
        if row is None:
            return None
        return self._to_model(row)

    async def list_by_world(self, world_id: str, character_id: str | None = None) -> list[Relation]:
        stmt = select(M2Relation).where(M2Relation.world_id == uuid.UUID(world_id))
        if character_id:
            char_uuid = uuid.UUID(character_id)
            stmt = stmt.where(
                or_(M2Relation.character_a == char_uuid, M2Relation.character_b == char_uuid)
            )
        stmt = stmt.order_by(M2Relation.created_at)
        result = await self.session.execute(stmt)
        return [self._to_model(row) for row in result.scalars().all()]

    async def update(self, relation_id: str, req: UpdateRelationRequest) -> Relation | None:
        row = await self.session.get(M2Relation, uuid.UUID(relation_id))
        if row is None:
            return None
        update_data = req.model_dump(exclude_none=True)
        for key, value in update_data.items():
            setattr(row, key, value)
        await self.session.flush()
        await self.session.refresh(row)
        return self._to_model(row)

    async def delete(self, relation_id: str) -> bool:
        from sqlalchemy import delete

        stmt = delete(M2Relation).where(M2Relation.id == uuid.UUID(relation_id))
        result = await self.session.execute(stmt)
        await self.session.flush()
        return cast(CursorResult, result).rowcount > 0

    async def delete_by_character(self, character_id: str) -> int:
        from sqlalchemy import delete

        char_uuid = uuid.UUID(character_id)
        stmt = delete(M2Relation).where(
            or_(M2Relation.character_a == char_uuid, M2Relation.character_b == char_uuid)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return cast(CursorResult, result).rowcount

    async def delete_non_user_relations(self, world_id: str, exclude_character_id: str) -> int:
        """删除世界内所有关系（全删），后续由 generation_service 重建用户角色关系。

        注意：exclude_character_id 参数目前未用于过滤查询——全删所有关系再统一重连，
        语义上等同于删非用户角色间的关系（因为用户角色关系会在生成完成后重新写入）。
        该参数保留以记录调用方意图，实现不做过滤。
        """
        from sqlalchemy import delete

        stmt = delete(M2Relation).where(M2Relation.world_id == uuid.UUID(world_id))
        result = await self.session.execute(stmt)
        await self.session.flush()
        return cast(CursorResult, result).rowcount

    async def delete_all_by_world(self, world_id: str) -> int:
        from sqlalchemy import delete

        stmt = delete(M2Relation).where(M2Relation.world_id == uuid.UUID(world_id))
        result = await self.session.execute(stmt)
        await self.session.flush()
        return cast(CursorResult, result).rowcount

    async def bulk_create(self, world_id: str, relations: list[dict]) -> list[Relation]:
        rows = []
        for rel_data in relations:
            row = M2Relation(
                id=uuid.UUID(rel_data["id"]) if "id" in rel_data else uuid.uuid4(),
                world_id=uuid.UUID(world_id),
                character_a=uuid.UUID(rel_data["character_a"]),
                character_b=uuid.UUID(rel_data["character_b"]),
                type=rel_data.get("type"),
                direction=rel_data.get("direction", "bidirectional"),
                description=rel_data.get("description"),
                status=rel_data.get("status", RelationStatus.ACTIVE),
                graph_edge_uuid=rel_data.get("graph_edge_uuid"),
            )
            self.session.add(row)
            rows.append(row)
        await self.session.flush()
        for row in rows:
            await self.session.refresh(row)
        return [self._to_model(row) for row in rows]

    async def delete_graph_edges_by_world(self, world_id: str) -> int:
        """删除该世界所有从 Zep 图谱导入的关系（graph_edge_uuid 非空）。"""
        from sqlalchemy import delete

        stmt = (
            delete(M2Relation)
            .where(M2Relation.world_id == uuid.UUID(world_id))
            .where(M2Relation.graph_edge_uuid.isnot(None))
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return cast(CursorResult, result).rowcount

    def _to_model(self, row: M2Relation) -> Relation:
        return Relation(
            id=str(row.id),
            world_id=str(row.world_id),
            character_a=str(row.character_a),
            character_b=str(row.character_b),
            type=row.type,
            direction=row.direction,
            description=row.description,
            status=row.status,
            historical_changes=row.historical_changes,
            graph_edge_uuid=row.graph_edge_uuid,
            created_at=row.created_at,
            updated_at=row.updated_at,
        )

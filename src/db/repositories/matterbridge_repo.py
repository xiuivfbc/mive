from __future__ import annotations

import uuid
from typing import cast

from sqlalchemy import select, update
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import M20MatterbridgeBinding


class MatterbridgeBridgeRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_binding(self, world_id: str) -> M20MatterbridgeBinding | None:
        result = await self.session.execute(
            select(M20MatterbridgeBinding).where(
                M20MatterbridgeBinding.world_id == uuid.UUID(world_id)
            )
        )
        return result.scalar_one_or_none()

    async def upsert_binding(
        self,
        world_id: str,
        api_url: str,
        api_token_encrypted: str,
        api_token_iv: str,
        enabled: bool = True,
        config_json: dict | None = None,
    ) -> M20MatterbridgeBinding:
        stmt = (
            insert(M20MatterbridgeBinding)
            .values(
                id=uuid.uuid4(),
                world_id=uuid.UUID(world_id),
                api_url=api_url,
                api_token_encrypted=api_token_encrypted,
                api_token_iv=api_token_iv,
                enabled=enabled,
                config_json=config_json,
            )
            .on_conflict_do_update(
                index_elements=["world_id"],
                set_={
                    "api_url": api_url,
                    "api_token_encrypted": api_token_encrypted,
                    "api_token_iv": api_token_iv,
                    "enabled": enabled,
                    "config_json": config_json,
                },
            )
            .returning(M20MatterbridgeBinding)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.scalar_one()

    async def update_binding(
        self,
        world_id: str,
        **fields,
    ) -> M20MatterbridgeBinding | None:
        if not fields:
            return await self.get_binding(world_id)
        stmt = (
            update(M20MatterbridgeBinding)
            .where(M20MatterbridgeBinding.world_id == uuid.UUID(world_id))
            .values(**fields)
            .returning(M20MatterbridgeBinding)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.scalar_one_or_none()

    async def delete_binding(self, world_id: str) -> bool:
        from sqlalchemy import delete

        result = await self.session.execute(
            delete(M20MatterbridgeBinding).where(
                M20MatterbridgeBinding.world_id == uuid.UUID(world_id)
            )
        )
        await self.session.flush()
        return cast(CursorResult, result).rowcount > 0

    async def list_enabled(self) -> list[M20MatterbridgeBinding]:
        result = await self.session.execute(
            select(M20MatterbridgeBinding).where(M20MatterbridgeBinding.enabled.is_(True))
        )
        return list(result.scalars().all())

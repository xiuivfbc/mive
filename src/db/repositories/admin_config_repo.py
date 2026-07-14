"""Repository for m21_admin_config — admin settings persistence."""

from __future__ import annotations

from typing import cast

from sqlalchemy import delete, func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.engine import CursorResult
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import M21AdminConfig


class AdminConfigRepository:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def list_by_group(self, group_name: str) -> list[M21AdminConfig]:
        result = await self.session.execute(
            select(M21AdminConfig).where(M21AdminConfig.group_name == group_name)
        )
        return list(result.scalars().all())

    async def get_one(self, group_name: str, key: str) -> M21AdminConfig | None:
        result = await self.session.execute(
            select(M21AdminConfig).where(
                M21AdminConfig.group_name == group_name,
                M21AdminConfig.key == key,
            )
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        group_name: str,
        key: str,
        encrypted_value: str | None,
        plain_value: str | None,
        iv: str | None,
    ) -> M21AdminConfig:
        stmt = (
            insert(M21AdminConfig)
            .values(
                group_name=group_name,
                key=key,
                encrypted_value=encrypted_value,
                plain_value=plain_value,
                iv=iv,
            )
            .on_conflict_do_update(
                index_elements=["group_name", "key"],
                set_={
                    "encrypted_value": encrypted_value,
                    "plain_value": plain_value,
                    "iv": iv,
                    "updated_at": func.now(),
                },
            )
            .returning(M21AdminConfig)
        )
        result = await self.session.execute(stmt)
        await self.session.flush()
        return result.scalar_one()

    async def delete_by_group(self, group_name: str) -> int:
        result = await self.session.execute(
            delete(M21AdminConfig).where(M21AdminConfig.group_name == group_name)
        )
        await self.session.flush()
        return cast(CursorResult, result).rowcount

"""API key repository for BYOK (Bring Your Own Key) functionality."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import M10ApiKey


class ApiKeyRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_user(self, user_id: uuid.UUID) -> M10ApiKey | None:
        result = await self.session.execute(
            select(M10ApiKey).where(M10ApiKey.user_id == user_id)
        )
        return result.scalar_one_or_none()

    async def upsert(
        self,
        user_id: uuid.UUID,
        provider: str,
        encrypted_key: str,
        iv: str,
        model: str | None = None,
        base_url: str | None = None,
        rpm: int | None = None,
        api_format: str | None = None,
    ) -> M10ApiKey:
        existing = await self.get_by_user(user_id)
        if existing:
            existing.provider = provider
            existing.encrypted_key = encrypted_key
            existing.iv = iv
            existing.model = model
            existing.base_url = base_url
            existing.rpm = rpm
            existing.api_format = api_format
            existing.updated_at = datetime.now(UTC).replace(tzinfo=None)
            return existing
        else:
            api_key = M10ApiKey(
                user_id=user_id,
                provider=provider,
                encrypted_key=encrypted_key,
                iv=iv,
                model=model,
                base_url=base_url,
                rpm=rpm,
                api_format=api_format,
            )
            self.session.add(api_key)
            return api_key

    async def delete_by_user(self, user_id: uuid.UUID) -> bool:
        api_key = await self.get_by_user(user_id)
        if api_key:
            await self.session.delete(api_key)
            return True
        return False

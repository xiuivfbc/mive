from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import M16WelcomeQuote


class WelcomeQuoteRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        user_id: uuid.UUID,
        content: str,
        status: str = "pending",
        ai_verdict: str | None = None,
        ai_reason: str | None = None,
    ) -> M16WelcomeQuote:
        obj = M16WelcomeQuote(
            user_id=user_id,
            content=content,
            status=status,
            ai_verdict=ai_verdict,
            ai_reason=ai_reason,
        )
        self.session.add(obj)
        await self.session.flush()
        return obj

    async def list_approved(self, limit: int = 20) -> list[M16WelcomeQuote]:
        result = await self.session.execute(
            select(M16WelcomeQuote)
            .where(M16WelcomeQuote.status == "approved")
            .order_by(func.random())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def max_approved_updated_at(self) -> datetime | None:
        """Return MAX(updated_at) of approved quotes (for conditional caching)."""
        stmt = select(func.max(M16WelcomeQuote.updated_at)).where(
            M16WelcomeQuote.status == "approved"
        )
        result = await self.session.execute(stmt)
        return result.scalar_one_or_none()

    async def list_by_user(self, user_id: uuid.UUID) -> list[M16WelcomeQuote]:
        result = await self.session.execute(
            select(M16WelcomeQuote)
            .where(M16WelcomeQuote.user_id == user_id)
            .order_by(M16WelcomeQuote.created_at.desc())
        )
        return list(result.scalars().all())

    async def list_all(self, status: str | None = None, limit: int = 50) -> list[M16WelcomeQuote]:
        query = select(M16WelcomeQuote).order_by(M16WelcomeQuote.created_at.desc()).limit(limit)
        if status:
            query = query.where(M16WelcomeQuote.status == status)
        result = await self.session.execute(query)
        return list(result.scalars().all())

    async def get_by_id(self, quote_id: uuid.UUID) -> M16WelcomeQuote | None:
        result = await self.session.execute(
            select(M16WelcomeQuote).where(M16WelcomeQuote.id == quote_id)
        )
        return result.scalar_one_or_none()

    async def update_status(
        self,
        quote_id: uuid.UUID,
        status: str,
        ai_verdict: str | None = None,
        ai_reason: str | None = None,
    ) -> None:
        obj = await self.get_by_id(quote_id)
        if obj is None:
            return
        obj.status = status
        if ai_verdict is not None:
            obj.ai_verdict = ai_verdict
        if ai_reason is not None:
            obj.ai_reason = ai_reason
        await self.session.flush()

    async def delete(self, quote_id: uuid.UUID) -> None:
        await self.session.execute(delete(M16WelcomeQuote).where(M16WelcomeQuote.id == quote_id))

    async def count_recent_by_user(self, user_id: uuid.UUID, hours: int = 1) -> int:
        since = datetime.now(UTC).replace(tzinfo=None) - timedelta(hours=hours)
        result = await self.session.execute(
            select(func.count()).where(
                M16WelcomeQuote.user_id == user_id,
                M16WelcomeQuote.created_at >= since,
            )
        )
        return result.scalar_one()

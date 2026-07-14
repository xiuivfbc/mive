import uuid

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from src.db.models import M9User


class UserRepository:
    def __init__(self, session: AsyncSession):
        self.session = session

    async def get_by_id(self, user_id: uuid.UUID) -> M9User | None:
        result = await self.session.execute(select(M9User).where(M9User.id == user_id))
        return result.scalar_one_or_none()

    async def get_by_username(self, username: str) -> M9User | None:
        result = await self.session.execute(select(M9User).where(M9User.username == username))
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> M9User | None:
        result = await self.session.execute(select(M9User).where(M9User.email == email))
        return result.scalar_one_or_none()

    async def create(self, username: str, email: str, hashed_password: str) -> M9User:
        user = M9User(username=username, email=email, hashed_password=hashed_password)
        self.session.add(user)
        await self.session.flush()
        return user

    async def update_language(self, user_id: uuid.UUID, language: str) -> M9User | None:
        user = await self.get_by_id(user_id)
        if user is None:
            return None
        user.preferred_language = language
        await self.session.flush()
        return user

    async def update_avatar(self, user_id: uuid.UUID, avatar_url: str | None) -> M9User | None:
        user = await self.get_by_id(user_id)
        if user is None:
            return None
        user.avatar_url = avatar_url
        await self.session.flush()
        return user

    async def update_email(self, user_id: uuid.UUID, email: str) -> M9User | None:
        user = await self.get_by_id(user_id)
        if user is None:
            return None
        user.email = email
        await self.session.flush()
        return user

    async def search(self, query: str, limit: int = 20) -> list[M9User]:
        escaped = query.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
        result = await self.session.execute(
            select(M9User)
            .where(
                or_(
                    M9User.username.ilike(f"%{escaped}%", escape="\\"),
                    M9User.email.ilike(f"%{escaped}%", escape="\\"),
                )
            )
            .limit(limit)
        )
        return list(result.scalars().all())

    async def update_password(
        self, user_id: uuid.UUID, hashed_password: str
    ) -> M9User | None:
        user = await self.get_by_id(user_id)
        if user is None:
            return None
        user.hashed_password = hashed_password
        await self.session.flush()
        return user

    async def set_staff(self, user_id: uuid.UUID, is_staff: bool) -> M9User | None:
        user = await self.get_by_id(user_id)
        if user is None:
            return None
        user.is_staff = is_staff
        await self.session.flush()
        return user

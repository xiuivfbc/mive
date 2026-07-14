from __future__ import annotations

from typing import TYPE_CHECKING

from src.db.repositories.chat_session_repo import ChatSessionRepository
from src.db.repositories.message_repo import MessageRepository
from src.models.chat_session import ChatSessionListResponse
from src.models.message import Message

if TYPE_CHECKING:
    from redis.asyncio import Redis

    from src.db.repositories.character_repo import CharacterRepository


class ChatSessionService:
    def __init__(
        self,
        chat_session_repo: ChatSessionRepository,
        message_repo: MessageRepository,
        character_repo: CharacterRepository | None = None,
        redis: Redis | None = None,
    ):
        self.chat_session_repo = chat_session_repo
        self.message_repo = message_repo
        self._character_repo = character_repo
        self._redis = redis

    async def list_sessions(self, world_id: str) -> ChatSessionListResponse:
        sessions = await self.chat_session_repo.list_by_world(world_id)
        return ChatSessionListResponse(sessions=sessions)

    async def get_session_messages(self, session_id: str) -> list[Message]:
        messages = await self.message_repo.list_by_session(session_id)
        # Resolve sender_name for character messages
        from src.utils.character_name_cache import resolve_message_sender_names

        await resolve_message_sender_names(
            messages, redis=self._redis, character_repo=self._character_repo
        )
        return messages

    async def delete_session(self, world_id: str, session_id: str) -> bool:
        return await self.chat_session_repo.delete(session_id)

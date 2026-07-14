"""Memory Orchestrator — single entry point for the memory lifecycle.

Collapses short-term generation, long-term promotion, and propagation dispatch
into one facade. Consumers (EventDialogueService, MessageService) call the
orchestrator instead of duplicating inline fallback logic.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from src.models.character import Character

if TYPE_CHECKING:
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.db.repositories.character_memory_repo import CharacterMemoryRepository
    from src.db.repositories.character_repo import CharacterRepository
    from src.db.repositories.relation_repo import RelationRepository
    from src.db.repositories.world_repo import WorldRepository
    from src.llm.embedding_provider import EmbeddingProvider
    from src.services.memory_module import MemoryModule
    from src.services.memory_propagation_service import MemoryPropagationService

logger = logging.getLogger(__name__)


class MemoryOrchestrator:
    """Facade that unifies the memory lifecycle for both event and chat paths.

    Handles the case where memory_module is None by returning empty/no-op results.
    """

    def __init__(
        self,
        memory_module: MemoryModule | None,
        memory_propagation_service: MemoryPropagationService | None = None,
    ):
        self.memory_module = memory_module
        self.memory_propagation_service = memory_propagation_service

    # ── Generation ───────────────────────────────────────────────────────────

    async def generate_short_term_memories(
        self,
        session: AsyncSession,
        world_id: str,
        char_map: dict[str, Character],
        dialogue_text: str,
        event_description: str,
        memory_repo: CharacterMemoryRepository,
        session_id: uuid.UUID | None = None,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> list:
        """Delegate short-term memory generation to MemoryModule.

        Returns list of newly written memory objects (empty if memory_module is None
        or if generation fails).
        """
        if self.memory_module is None:
            return []
        try:
            return await self.memory_module.generate_short_term_memories(
                session=session,
                world_id=world_id,
                char_map=char_map,
                dialogue_text=dialogue_text,
                event_description=event_description,
                memory_repo=memory_repo,
                session_id=session_id,
                embedding_provider=embedding_provider,
            )
        except Exception:
            logger.exception("generate_short_term_memories failed")
            return []

    # ── Promotion ────────────────────────────────────────────────────────────

    async def check_and_promote(
        self,
        session: AsyncSession,
        world_id: str,
        char_map: dict[str, Character],
        memory_repo: CharacterMemoryRepository,
        world_repo: WorldRepository,
        relation_repo: RelationRepository,
        char_repo: CharacterRepository,
    ) -> None:
        """Check promotion threshold and promote long-term memories.

        No-op if memory_module is None.
        """
        if self.memory_module is None:
            logger.debug("check_and_promote: memory_module is None, skipping")
            return

        char_ids = [uuid.UUID(c.id) for c in char_map.values()]
        logger.info(
            "check_and_promote: checking %d characters: %s",
            len(char_ids),
            list(char_map.keys()),
        )
        ids_needing_promotion = await memory_repo.list_characters_needing_promotion(
            char_ids, threshold=40, exclude_categories=["trivial"]
        )
        logger.info(
            "check_and_promote: %d characters need promotion out of %d checked",
            len(ids_needing_promotion),
            len(char_ids),
        )
        for character in char_map.values():
            if uuid.UUID(character.id) in ids_needing_promotion:
                await self.memory_module.promote_long_term_memories_for_character(
                    session=session,
                    world_id=world_id,
                    character=character,
                    memory_repo=memory_repo,
                    world_repo=world_repo,
                    relation_repo=relation_repo,
                    char_repo=char_repo,
                )

    # ── Propagation dispatch ─────────────────────────────────────────────────

    async def dispatch_event_propagation(
        self,
        world_id: str,
        event_id: str,
        participant_names: list[str],
        newly_written_memories: list,
        virtual_time,
        event_impacts: list[dict] | None = None,
    ) -> None:
        """Dispatch hearsay propagation after event memories are written.

        No-op if memory_propagation_service is None.
        """
        if self.memory_propagation_service is None or not newly_written_memories:
            return
        try:
            await self.memory_propagation_service.propagate_after_event_memories(
                world_id=world_id,
                event_id=event_id,
                participant_names=participant_names,
                newly_written_memories=newly_written_memories,
                virtual_time=virtual_time,
                event_impacts=event_impacts or [],
            )
        except Exception:
            logger.debug("Memory propagation dispatch failed, skipping")

    async def dispatch_chat_propagation(
        self,
        world_id: str,
        session_id: str,
        participant_names: list[str],
        newly_written_memories: list,
        virtual_time,
    ) -> None:
        """Dispatch hearsay propagation after chat memories are flushed.

        No-op if memory_propagation_service is None.
        """
        if self.memory_propagation_service is None or not newly_written_memories:
            return
        try:
            await self.memory_propagation_service.propagate_after_chat_flush(
                world_id=world_id,
                session_id=session_id,
                participant_names=participant_names,
                newly_written_memories=newly_written_memories,
                virtual_time=virtual_time,
            )
        except Exception:
            logger.debug("Memory propagation dispatch failed, skipping")

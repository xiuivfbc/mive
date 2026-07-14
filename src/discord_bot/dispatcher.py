"""Routes a ParsedCommand to the appropriate Service and returns an SSE generator."""

from __future__ import annotations

import logging
from collections.abc import AsyncGenerator

from src.discord_bot.parser import ParsedCommand

logger = logging.getLogger(__name__)

# Display name mapping for non-character sender types
_SENDER_TYPE_DISPLAY_NAMES = {"system": "系统", "narrator": "旁白", "user": "用户"}


class _NeverDisconnected:
    """Stub for FastAPI Request that EventDialogueService uses to detect HTTP disconnect."""

    async def is_disconnected(self) -> bool:
        return False


async def dispatch_event(
    command: ParsedCommand,
    world_id: str,
    event_dialogue_service,
) -> AsyncGenerator[str, None]:
    """Dispatch an event-mode command via EventDialogueService. Returns SSE generator."""
    return event_dialogue_service.stream_dialogue(
        world_id=world_id,
        raw_input=command.content,
        request=_NeverDisconnected(),
    )


async def _build_sender_name_map(
    world_id: str,
    session,
    redis=None,
) -> dict[str, str]:
    """Build a sender_id -> character_name map for all characters in a world.

    Uses Redis character name cache when available to avoid repeated DB lookups.
    """
    from src.db.repositories.character_repo import CharacterRepository

    char_repo = CharacterRepository(session)
    characters = await char_repo.list_by_world(world_id)
    result = {str(c.id): c.name for c in characters}

    # Populate cache for future lookups
    if redis is not None:
        from src.utils.character_name_cache import set_character_name

        for c in characters:
            try:
                await set_character_name(c.id, c.name, redis=redis)
            except Exception:
                pass

    return result


async def dispatch_chat(
    command: ParsedCommand,
    world_id: str,
    message_service,
    session_id: str | None = None,
) -> tuple[str, str | None]:
    """Dispatch a chat-mode command via MessageService.

    Returns (response_content, session_id).
    """
    result = await message_service.send_message(
        world_id=world_id,
        content=command.content,
        session_id=session_id,
    )

    # Build sender_id -> name map for resolving character names
    sender_name_map: dict[str, str] = {}
    try:
        sender_name_map = await _build_sender_name_map(
            world_id, message_service.message_repo.session
        )
    except Exception:
        logger.warning("Failed to build sender name map for world %s", world_id)

    # Aggregate all character responses into one reply string
    parts = []
    for resp in result.responses:
        if resp.content:
            # Resolve sender name: try sender_id lookup, then sender_type fallback
            display_name: str | None = None
            if resp.sender_id and resp.sender_id in sender_name_map:
                display_name = sender_name_map[resp.sender_id]
            elif resp.sender_type in _SENDER_TYPE_DISPLAY_NAMES:
                display_name = _SENDER_TYPE_DISPLAY_NAMES[resp.sender_type]
            display_name = display_name or resp.sender_type or "未知"
            parts.append(f"**{display_name}**: {resp.content}")

    combined = "\n\n".join(parts) if parts else "（没有角色回应）"
    return combined, str(result.session_id) if result.session_id else None

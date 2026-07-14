"""Discord Bot entry point.

Run with:
    python -m src.discord_bot

Requires DISCORD_BOT_TOKEN in environment / .env
"""

from __future__ import annotations

import logging
from typing import cast

import discord
from fastapi import Request

from src.config import settings
from src.discord_bot.dispatcher import dispatch_chat
from src.discord_bot.parser import parse_command
from src.discord_bot.sender import stream_to_thread

logger = logging.getLogger(__name__)

# ── Session factory (independent from main FastAPI loop) ─────────────────────


def _make_session_factory():
    from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

    engine = create_async_engine(settings.database_url, pool_size=3, max_overflow=2)
    return async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)


_session_factory = _make_session_factory()


# ── Build services ────────────────────────────────────────────────────────────


async def _build_event_service(session):
    from src.db.repositories.character_repo import CharacterRepository
    from src.db.repositories.event_repo import EventRepository
    from src.db.repositories.message_repo import MessageRepository
    from src.db.repositories.world_repo import WorldRepository
    from src.llm.factory import create_llm_auto
    from src.services.event_dialogue_service import EventDialogueService

    llm = await create_llm_auto(
        settings.llm_provider,
        settings.llm_api_key,
        settings.llm_model or None,
        settings.llm_base_url or None,
        api_format=settings.llm_api_format or None,
    )
    return EventDialogueService(
        llm=llm,
        character_repo=CharacterRepository(session),
        message_repo=MessageRepository(session),
        event_repo=EventRepository(session),
        world_repo=WorldRepository(session),
        session_factory=_session_factory,
    )


async def _build_message_service(session):
    from src.db.repositories.character_repo import CharacterRepository
    from src.db.repositories.message_repo import MessageRepository
    from src.db.repositories.relation_repo import RelationRepository
    from src.db.repositories.world_repo import WorldRepository
    from src.llm.factory import create_llm_auto
    from src.services.dialogue_generation_service import DialogueGenerationService
    from src.services.message_service import MessageService

    llm = await create_llm_auto(
        settings.llm_provider,
        settings.llm_api_key,
        settings.llm_model or None,
        settings.llm_base_url or None,
        api_format=settings.llm_api_format or None,
    )
    dialogue_svc = DialogueGenerationService(
        llm=llm,
        character_repo=CharacterRepository(session),
        message_repo=MessageRepository(session),
        world_repo=WorldRepository(session),
        relation_repo=RelationRepository(session),
    )
    return MessageService(
        message_repo=MessageRepository(session),
        dialogue_service=dialogue_svc,
        llm=llm,
        session_factory=_session_factory,
    )


async def _get_binding(world_id: str):
    """Fetch Discord binding for a world from DB."""
    from src.db.repositories.discord_bridge_repo import DiscordBridgeRepository

    async with _session_factory() as session:
        repo = DiscordBridgeRepository(session)
        return await repo.get_binding(world_id)


async def _get_character_webhooks(world_id: str) -> dict[str, str]:
    """Return {character_id: webhook_url} mapping for a world."""
    from src.db.repositories.discord_bridge_repo import DiscordBridgeRepository

    async with _session_factory() as session:
        repo = DiscordBridgeRepository(session)
        rows = await repo.list_character_webhooks(world_id)
        return {str(r.character_id): r.webhook_url for r in rows}


# ── Resolve channel_id → world_id ─────────────────────────────────────────────


async def _find_world_for_channel(channel_id: int) -> tuple[str | None, str]:
    """Given a Discord channel ID, find the world_id and mode ('event' | 'chat').

    Returns (world_id, mode) or (None, '') if not found.
    """
    from sqlalchemy import select

    from src.db.models import M8DiscordBinding

    ch = str(channel_id)
    async with _session_factory() as session:
        result = await session.execute(
            select(M8DiscordBinding).where(
                (M8DiscordBinding.channel_event == ch) | (M8DiscordBinding.channel_chat == ch)
            )
        )
        row = result.scalar_one_or_none()
        if row is None:
            return None, ""
        mode = "event" if str(row.channel_event) == ch else "chat"
        return str(row.world_id), mode


# ── Bot setup ─────────────────────────────────────────────────────────────────

intents = discord.Intents.default()
intents.message_content = True

client = discord.Client(intents=intents)

# Track active chat session IDs per user per world: {(world_id, user_id): session_id}
_chat_sessions: dict[tuple[str, int], str] = {}


@client.event
async def on_ready():
    # on_ready 触发时 discord.py 保证 client.user 已就绪（非 None）
    assert client.user is not None
    logger.info("Discord Bot ready as %s (id=%s)", client.user, client.user.id)
    print(f"[Discord Bot] Logged in as {client.user}")


@client.event
async def on_message(message: discord.Message):
    if message.author == client.user or message.author.bot:
        return
    if not isinstance(message.channel, discord.TextChannel):
        return

    world_id, mode = await _find_world_for_channel(message.channel.id)
    if world_id is None:
        return  # Channel not bound to any world

    text = message.content.strip()
    if not text:
        return

    # Force mode based on channel: #事件 channel always treats as event, #角色聊天 as chat
    # But user can override with ! prefix in #角色聊天
    if mode == "event" and not text.startswith("!"):
        text = "!" + text  # Auto-prefix for #事件 channel

    try:
        cmd = parse_command(text)
    except ValueError as e:
        await message.channel.send(f"⚠️ 命令解析失败：{e}")
        return

    # Create a Thread for this interaction
    session_title = cmd.content[:30] if cmd.content else "对话"
    try:
        thread = await message.create_thread(name=session_title)
    except discord.HTTPException as e:
        await message.channel.send(f"⚠️ 无法创建 Thread：{e}")
        return

    # Fetch binding info for webhook URLs
    binding = await _get_binding(world_id)
    webhook_map = await _get_character_webhooks(world_id)
    narrator_wh = binding.narrator_webhook_url if binding else None

    if cmd.mode == "event":
        async with _session_factory() as session:
            event_svc = await _build_event_service(session)
            try:
                sse_gen = event_svc.stream_dialogue(
                    world_id=world_id,
                    raw_input=cmd.content,
                    request=cast(Request, _NeverDisconnected()),
                )
                await stream_to_thread(thread, sse_gen, webhook_map, narrator_wh)
                await session.commit()
            except Exception as e:
                logger.exception("Event dialogue failed")
                await thread.send(f"⚠️ 事件推演出错：{e}")
    else:
        # Chat mode
        session_key = (world_id, message.author.id)
        existing_session_id = _chat_sessions.get(session_key)

        async with _session_factory() as session:
            msg_svc = await _build_message_service(session)
            try:
                reply, new_session_id = await dispatch_chat(
                    cmd, world_id, msg_svc, session_id=existing_session_id
                )
                if new_session_id:
                    _chat_sessions[session_key] = new_session_id
                await thread.send(reply)
                await session.commit()
            except Exception as e:
                logger.exception("Chat dispatch failed")
                await thread.send(f"⚠️ 对话出错：{e}")


class _NeverDisconnected:
    async def is_disconnected(self) -> bool:
        return False


def main():
    if not settings.discord_bot_token:
        raise SystemExit("DISCORD_BOT_TOKEN not set in environment")
    client.run(settings.discord_bot_token)


if __name__ == "__main__":
    main()

"""Tests for discord_bot/dispatcher.py — dispatch_chat sender name resolution."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from unittest.mock import AsyncMock, MagicMock, patch

from src.discord_bot.dispatcher import dispatch_chat
from src.discord_bot.parser import ParsedCommand
from src.models.message import Message, SendMessageResponse


def _make_parsed_command(content: str = "你好") -> ParsedCommand:
    return ParsedCommand(mode="chat", content=content, inclusions=[], exclusive=False)


def _make_char_response(
    sender_id: str | None = None,
    sender_type: str = "character",
    content: str = "你好啊",
) -> Message:
    return Message(
        id=str(uuid.uuid4()),
        world_id="world-001",
        type="dialogue",
        sender_type=sender_type,
        sender_id=sender_id,
        content=content,
        virtual_time=datetime(2026, 1, 1, tzinfo=UTC),
        session_id="session-001",
    )


def _make_character_model(char_id: str, name: str):
    from src.models.character import Character

    return Character(
        id=char_id,
        world_id="world-001",
        name=name,
        profile={"brief": "简介"},
    )


class TestDispatchChatSenderName:
    """Verify dispatch_chat resolves sender_id to character name."""

    async def test_resolves_character_name_from_sender_id(self):
        """Character messages should display the character's name, not sender_id."""
        char_id = str(uuid.uuid4())

        resp_msg = _make_char_response(sender_id=char_id, content="你好啊")
        result_mock = SendMessageResponse(
            user_message=_make_char_response(sender_type="user", content="你好"),
            responses=[resp_msg],
            session_id="session-001",
        )

        message_service = AsyncMock()
        message_service.send_message = AsyncMock(return_value=result_mock)
        message_service.message_repo = MagicMock()
        message_service.message_repo.session = AsyncMock()

        with patch(
            "src.discord_bot.dispatcher._build_sender_name_map",
            return_value={char_id: "叶文洁"},
        ):
            combined, session_id = await dispatch_chat(
                _make_parsed_command("你好"),
                "world-001",
                message_service,
            )

        assert "叶文洁" in combined
        assert "你好啊" in combined
        assert session_id == "session-001"

    async def test_falls_back_to_sender_type_for_unknown_id(self):
        """Unknown sender_id should fall back to sender_type display name."""
        resp_msg = _make_char_response(
            sender_id=str(uuid.uuid4()),
            sender_type="narrator",
            content="旁白内容",
        )
        result_mock = SendMessageResponse(
            user_message=_make_char_response(sender_type="user", content="你好"),
            responses=[resp_msg],
            session_id="session-001",
        )

        message_service = AsyncMock()
        message_service.send_message = AsyncMock(return_value=result_mock)
        message_service.message_repo = MagicMock()
        message_service.message_repo.session = AsyncMock()

        with patch(
            "src.discord_bot.dispatcher._build_sender_name_map",
            return_value={},
        ):
            combined, session_id = await dispatch_chat(
                _make_parsed_command("你好"),
                "world-001",
                message_service,
            )

        assert "旁白" in combined

    async def test_empty_responses_returns_no_response_message(self):
        """No character responses → fallback message."""
        result_mock = SendMessageResponse(
            user_message=_make_char_response(sender_type="user", content="你好"),
            responses=[],
            session_id="session-001",
        )

        message_service = AsyncMock()
        message_service.send_message = AsyncMock(return_value=result_mock)
        message_service.message_repo = MagicMock()
        message_service.message_repo.session = AsyncMock()

        with patch(
            "src.discord_bot.dispatcher._build_sender_name_map",
            return_value={},
        ):
            combined, _ = await dispatch_chat(
                _make_parsed_command("你好"),
                "world-001",
                message_service,
            )

        assert combined == "（没有角色回应）"

    async def test_sender_name_map_failure_graceful(self):
        """If building name map fails, still return responses with fallback names."""
        char_id = str(uuid.uuid4())
        resp_msg = _make_char_response(sender_id=char_id, content="你好啊")
        result_mock = SendMessageResponse(
            user_message=_make_char_response(sender_type="user", content="你好"),
            responses=[resp_msg],
            session_id="session-001",
        )

        message_service = AsyncMock()
        message_service.send_message = AsyncMock(return_value=result_mock)
        message_service.message_repo = MagicMock()
        message_service.message_repo.session = AsyncMock()

        # _build_sender_name_map raises
        with patch(
            "src.discord_bot.dispatcher._build_sender_name_map",
            side_effect=RuntimeError("DB error"),
        ):
            combined, _ = await dispatch_chat(
                _make_parsed_command("你好"),
                "world-001",
                message_service,
            )

        # Should still have the response content (with fallback name)
        assert "你好啊" in combined

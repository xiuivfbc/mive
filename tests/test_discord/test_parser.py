"""Tests for discord_bot/parser.py — command parsing behavior."""

import pytest

from src.discord_bot.parser import parse_command


class TestParseMode:
    def test_exclamation_prefix_is_event_mode(self):
        result = parse_command("!城市爆发了危机")
        assert result.mode == "event"
        assert result.content == "城市爆发了危机"

    def test_no_prefix_is_chat_mode(self):
        result = parse_command("你好，最近怎么样？")
        assert result.mode == "chat"
        assert result.content == "你好，最近怎么样？"

    def test_event_strips_exclamation(self):
        result = parse_command("!发生了地震")
        assert "!" not in result.content


class TestInclusionModifiers:
    def test_plus_modifier_adds_inclusion(self):
        result = parse_command("+爱丽丝 你好")
        assert "爱丽丝" in result.inclusions
        assert result.content == "你好"
        assert result.exclusive is False

    def test_equals_modifier_adds_inclusion_and_sets_exclusive(self):
        result = parse_command("=贝克 你好")
        assert "贝克" in result.inclusions
        assert result.exclusive is True

    def test_event_with_plus_modifier(self):
        result = parse_command("!+爱丽丝 城市爆发了危机")
        assert result.mode == "event"
        assert "爱丽丝" in result.inclusions
        assert result.exclusive is False
        assert result.content == "城市爆发了危机"

    def test_event_with_exclusive_modifier(self):
        result = parse_command("!=爱丽丝 城市爆发了危机")
        assert result.mode == "event"
        assert "爱丽丝" in result.inclusions
        assert result.exclusive is True
        assert result.content == "城市爆发了危机"

    def test_multiple_exclusive_modifiers(self):
        result = parse_command("!=爱丽丝 =贝克 事件描述")
        assert result.mode == "event"
        assert "爱丽丝" in result.inclusions
        assert "贝克" in result.inclusions
        assert result.exclusive is True
        assert result.content == "事件描述"

    def test_mixed_plus_and_equals_modifiers(self):
        result = parse_command("+爱丽丝 =贝克 聊天内容")
        assert "爱丽丝" in result.inclusions
        assert "贝克" in result.inclusions
        assert result.exclusive is True  # any = makes it exclusive
        assert result.content == "聊天内容"

    def test_no_modifier_empty_inclusions(self):
        result = parse_command("!无修饰符的事件")
        assert result.inclusions == []
        assert result.exclusive is False


class TestEdgeCases:
    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="Empty command"):
            parse_command("")

    def test_whitespace_only_raises(self):
        with pytest.raises(ValueError, match="Empty command"):
            parse_command("   ")

    def test_exclamation_only_no_content(self):
        result = parse_command("!+爱丽丝")
        assert result.mode == "event"
        assert "爱丽丝" in result.inclusions
        assert result.content == ""

    def test_leading_trailing_whitespace_stripped(self):
        result = parse_command("  !城市危机  ")
        assert result.content == "城市危机"

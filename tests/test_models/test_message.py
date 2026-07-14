"""Tests for M4 message models."""

import uuid
from datetime import datetime

import pytest
from pydantic import ValidationError

from src.models.message import (
    Message,
    MessageListResponse,
    SendMessageRequest,
    SendMessageResponse,
)


class TestMessage:
    def test_create_message_with_required_fields(self):
        msg = Message(
            id=str(uuid.uuid4()),
            world_id=str(uuid.uuid4()),
            type="dialogue",
            sender_type="character",
            sender_id=str(uuid.uuid4()),
            sender_name="叶文洁",
            content="常将军，您找我？",
            virtual_time=datetime(1971, 9, 7, 9, 30, 0),
        )
        assert msg.sender_name == "叶文洁"
        assert msg.type == "dialogue"
        assert msg.is_key_message is False
        assert msg.user_participated is False

    def test_message_type_must_be_valid(self):
        with pytest.raises(ValidationError):
            Message(
                id=str(uuid.uuid4()),
                world_id=str(uuid.uuid4()),
                type="invalid_type",
                sender_type="character",
                content="test",
                virtual_time=datetime(2024, 1, 1),
            )

    def test_sender_type_must_be_valid(self):
        with pytest.raises(ValidationError):
            Message(
                id=str(uuid.uuid4()),
                world_id=str(uuid.uuid4()),
                type="dialogue",
                sender_type="invalid_sender",
                content="test",
                virtual_time=datetime(2024, 1, 1),
            )


class TestSendMessageRequest:
    def test_valid_request(self):
        req = SendMessageRequest(content="叶文洁，你觉得昨晚的观测数据正常吗？")
        assert req.content == "叶文洁，你觉得昨晚的观测数据正常吗？"

    def test_content_cannot_be_empty(self):
        with pytest.raises(ValidationError):
            SendMessageRequest(content="")

    def test_content_cannot_be_whitespace_only(self):
        with pytest.raises(ValidationError):
            SendMessageRequest(content="   ")


class TestSendMessageResponse:
    def test_success_response(self):
        user_msg = Message(
            id=str(uuid.uuid4()),
            world_id=str(uuid.uuid4()),
            type="user",
            sender_type="user",
            content="你好",
            virtual_time=datetime(2024, 1, 1),
        )
        response = SendMessageResponse(user_message=user_msg, responses=[])
        assert response.user_message.content == "你好"
        assert response.responses == []
        assert response.error is None

    def test_partial_failure_response(self):
        user_msg = Message(
            id=str(uuid.uuid4()),
            world_id=str(uuid.uuid4()),
            type="user",
            sender_type="user",
            content="你好",
            virtual_time=datetime(2024, 1, 1),
        )
        response = SendMessageResponse(
            user_message=user_msg,
            responses=[],
            error="dialogue_generation_failed",
        )
        assert response.error == "dialogue_generation_failed"


class TestMessageEventType:
    def test_event_type_accepted(self):
        import json

        msg = Message(
            id=str(uuid.uuid4()),
            world_id=str(uuid.uuid4()),
            type="event",
            sender_type="system",
            sender_name="系统",
            content=json.dumps({"title": "暴风雪", "description": "...", "participants": []}),
            virtual_time=datetime(2024, 1, 1),
        )
        assert msg.type == "event"
        assert msg.sender_type == "system"

    def test_all_valid_types_accepted(self):
        for t in ("dialogue", "narration", "system", "user", "event"):
            msg = Message(
                id=str(uuid.uuid4()),
                world_id=str(uuid.uuid4()),
                type=t,
                sender_type="system",
                content="x",
                virtual_time=datetime(2024, 1, 1),
            )
            assert msg.type == t


class TestMessageListResponse:
    def test_list_response(self):
        messages = [
            Message(
                id=str(uuid.uuid4()),
                world_id=str(uuid.uuid4()),
                type="dialogue",
                sender_type="character",
                sender_name="叶文洁",
                content="测试消息",
                virtual_time=datetime(2024, 1, 1),
            )
        ]
        response = MessageListResponse(messages=messages, has_more=False)
        assert len(response.messages) == 1
        assert response.has_more is False

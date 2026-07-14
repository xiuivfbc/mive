import uuid

import pytest
from pydantic import ValidationError

from src.db.models import M3Event
from src.models.event import (
    Event,
    EventDiscardRequest,
    EventMarkRequest,
    EventStreamRequest,
)


class TestEventPydantic:
    """Event Pydantic 响应模型测试"""

    def test_event_fields(self):
        evt = Event(
            id=str(uuid.uuid4()),
            world_id=str(uuid.uuid4()),
            name="瘟疫爆发",
            event_type="user_injected",
        )
        assert evt.name == "瘟疫爆发"
        assert evt.status == "scheduled"
        assert evt.priority == "medium"
        assert evt.is_key_event is False

    def test_event_with_full_data(self):
        evt = Event(
            id=str(uuid.uuid4()),
            world_id=str(uuid.uuid4()),
            name="瘟疫爆发",
            description="一场严重的瘟疫席卷北方大陆",
            event_type="user_injected",
            priority="high",
            is_key_event=True,
        )
        assert evt.priority == "high"
        assert evt.is_key_event is True


class TestEventMarkRequest:
    """EventMarkRequest 请求模型测试"""

    def test_mark_as_key(self):
        req = EventMarkRequest(is_key_event=True)
        assert req.is_key_event is True

    def test_unmark(self):
        req = EventMarkRequest(is_key_event=False)
        assert req.is_key_event is False


class TestEventStreamRequest:
    def test_minimal_request(self):
        req = EventStreamRequest(raw_input="一场暴风雪突然袭来")
        assert req.raw_input == "一场暴风雪突然袭来"

    def test_empty_raw_input_rejected(self):
        with pytest.raises(ValidationError):
            EventStreamRequest(raw_input="")

    def test_raw_input_too_long_rejected(self):
        with pytest.raises(ValidationError):
            EventStreamRequest(raw_input="x" * 2001)


class TestEventDiscardRequest:
    def test_with_message_ids(self):
        ids = [str(uuid.uuid4()), str(uuid.uuid4())]
        req = EventDiscardRequest(message_ids=ids)
        assert req.message_ids == ids

    def test_empty_message_ids_allowed(self):
        req = EventDiscardRequest(message_ids=[])
        assert req.message_ids == []


class TestM3EventORM:
    """M3Event ORM 模型结构测试"""

    def test_table_name(self):
        assert M3Event.__tablename__ == "m3_events"

    def test_columns_exist(self):
        evt = M3Event(
            world_id=uuid.uuid4(),
            event_type="user_injected",
            name="瘟疫爆发",
        )
        assert evt.id is None  # DB 生成
        assert evt.world_id is not None
        assert evt.name == "瘟疫爆发"
        assert evt.status in ("scheduled", None)  # DB default
        assert evt.priority in ("medium", None)  # DB default
        assert evt.is_key_event in (False, None)  # DB default

    def test_remaining_fields(self):
        evt = M3Event(
            world_id=uuid.uuid4(),
            name="测试事件",
            priority="high",
            is_key_event=True,
        )
        assert evt.name == "测试事件"
        assert evt.priority == "high"
        assert evt.is_key_event is True

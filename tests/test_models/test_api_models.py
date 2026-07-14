"""Tests for API request/response Pydantic models."""

import pytest
from pydantic import ValidationError


class TestCreateWorldRequest:
    def test_minimal_create_request(self):
        """创建世界观最少只需要 title。"""
        from src.models.world import CreateWorldRequest

        req = CreateWorldRequest(title="三体")
        assert req.title == "三体"
        assert req.author is None
        assert req.urls == []

    def test_full_create_request(self):
        """完整创建请求。"""
        from src.models.world import CreateWorldRequest

        req = CreateWorldRequest(
            title="三体",
            author="刘慈欣",
            description="硬科幻经典",
            urls=["https://example.com/wiki"],
        )
        assert req.author == "刘慈欣"
        assert len(req.urls) == 1


class TestUpdateElementRequest:
    def test_update_element_partial(self):
        """更新元素时 brief 和 detail 都是必填。"""
        from src.models.world import UpdateElementRequest

        req = UpdateElementRequest(brief="新简介", detail="新详情")
        assert req.brief == "新简介"
        assert req.detail == "新详情"


class TestAskRequest:
    def test_ask_request(self):
        """追问请求必须包含 question。"""
        from src.models.world import AskRequest

        req = AskRequest(question="请描述三体世界的物理法则")
        assert req.question == "请描述三体世界的物理法则"

    def test_ask_request_rejects_empty(self):
        """question 不能为空。"""
        from src.models.world import AskRequest

        with pytest.raises(ValidationError):
            AskRequest(question="")

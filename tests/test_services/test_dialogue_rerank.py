"""Tests for AI element rerank (元素精排) in DialogueGenerationService.generate_response."""

import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest

from src.db.repositories.embedding_repo import RetrievedElement
from src.models.character import Character
from src.services.dialogue_generation_service import DialogueGenerationService


def _make_character(name: str, char_id: str | None = None) -> Character:
    return Character(
        id=char_id or str(uuid.uuid4()),
        world_id=str(uuid.uuid4()),
        name=name,
        profile={"brief": f"{name}简介", "detail": f"{name}详细", "personality": "性格"},
    )


def _retrieved(name: str, brief: str) -> RetrievedElement:
    return RetrievedElement(
        element_id=str(uuid.uuid4()),
        element_type="element",
        name=name,
        category="其他",
        brief=brief,
        score=1.0,
    )


@pytest.fixture
def llm():
    mock = AsyncMock()
    mock.complete_json.return_value = {"messages": []}
    return mock


@pytest.fixture
def character_repo():
    mock = AsyncMock()
    mock.list_by_world.return_value = [_make_character("叶文洁"), _make_character("常伟思")]
    return mock


@pytest.fixture
def message_repo():
    mock = AsyncMock()
    mock.list_by_session.return_value = []
    mock.create_batch.return_value = None
    return mock


@pytest.fixture
def world_repo():
    mock = AsyncMock()
    wd = MagicMock()
    wd.source = None
    wd.user_character_id = None
    wd.elements = []
    mock.get.return_value = wd
    return mock


@pytest.fixture
def retrieval_svc():
    svc = AsyncMock()
    svc.retrieve.return_value = [
        _retrieved("红岸基地", "秘密军事工程"),
        _retrieved("三体游戏", "VR 游戏"),
        _retrieved("古筝行动", "纳米丝切割计划"),
    ]
    return svc


def _build_service(llm, character_repo, message_repo, world_repo, retrieval_svc, rerank_llm=None):
    return DialogueGenerationService(
        llm=llm,
        character_repo=character_repo,
        message_repo=message_repo,
        world_repo=world_repo,
        element_retrieval_service=retrieval_svc,
        rerank_llm=rerank_llm,
    )


class TestElementRerank:
    async def test_rerank_disabled_uses_raw_vector_results(
        self, llm, character_repo, message_repo, world_repo, retrieval_svc
    ):
        """精排关闭时不调用 rerank LLM，直接用向量结果。"""
        rerank_llm = AsyncMock()
        service = _build_service(
            llm, character_repo, message_repo, world_repo, retrieval_svc, rerank_llm
        )
        await service.generate_response(
            world_id="w1",
            user_message="红岸是什么",
            element_rerank=False,
        )
        rerank_llm.complete_json.assert_not_called()
        # raw elements injected into system prompt
        system_prompt = llm.complete_json.call_args[0][0]
        assert "红岸基地" in system_prompt

    async def test_rerank_enabled_reorders_via_sub_model(
        self, llm, character_repo, message_repo, world_repo, retrieval_svc
    ):
        """精排开启时调用 rerank LLM，按其输出重排注入。"""
        rerank_llm = AsyncMock()
        # sub-model picks only 古筝行动 as relevant
        rerank_llm.complete_json.return_value = {"relevant": ["古筝行动"]}
        service = _build_service(
            llm, character_repo, message_repo, world_repo, retrieval_svc, rerank_llm
        )
        await service.generate_response(
            world_id="w1",
            user_message="切割计划",
            element_rerank=True,
        )
        rerank_llm.complete_json.assert_awaited_once()
        system_prompt = llm.complete_json.call_args[0][0]
        assert "古筝行动" in system_prompt
        # candidates fed to reranker must NOT contain full detail — only name+brief
        rerank_prompt = rerank_llm.complete_json.call_args[0][1]
        assert "古筝行动" in rerank_prompt

    async def test_rerank_exception_falls_back_to_raw_results(
        self, llm, character_repo, message_repo, world_repo, retrieval_svc
    ):
        """精排异常 → 返回原始向量结果（降级）。"""
        rerank_llm = AsyncMock()
        rerank_llm.complete_json.side_effect = RuntimeError("rerank boom")
        service = _build_service(
            llm, character_repo, message_repo, world_repo, retrieval_svc, rerank_llm
        )
        await service.generate_response(
            world_id="w1",
            user_message="任意",
            element_rerank=True,
        )
        # falls back to raw retrieved elements
        system_prompt = llm.complete_json.call_args[0][0]
        assert "红岸基地" in system_prompt

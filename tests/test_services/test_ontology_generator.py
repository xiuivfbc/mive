"""Tests for M6 OntologyGenerator."""

from unittest.mock import AsyncMock

import pytest

from src.services.ontology_generator import OntologyGenerator


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.fixture
def ontology_gen(mock_llm):
    return OntologyGenerator(llm=mock_llm)


MOCK_LLM_RESPONSE = {
    "entity_types": ["character", "organization", "location", "faction", "concept"],
    "relation_types": ["family", "enemy", "ally", "member_of", "located_in"],
    "constraints": {
        "min_entity_types": 2,
        "max_entity_types": 10,
        "fallback_types": ["character", "concept"],
    },
}


class TestOntologyGenerator:
    async def test_generate_returns_ontology(self, ontology_gen, mock_llm):
        mock_llm.complete_json.return_value = MOCK_LLM_RESPONSE

        result = await ontology_gen.generate(world_doc="一个武侠世界，有各大门派和江湖人物。")

        assert "entity_types" in result
        assert "relation_types" in result
        assert "constraints" in result
        assert "character" in result["entity_types"]
        assert len(result["entity_types"]) >= 2

    async def test_generate_passes_world_doc_to_llm(self, ontology_gen, mock_llm):
        mock_llm.complete_json.return_value = MOCK_LLM_RESPONSE

        await ontology_gen.generate(world_doc="科幻世界设定")

        call_args = mock_llm.complete_json.call_args
        assert "科幻世界设定" in call_args[1]["prompt"] or "科幻世界设定" in call_args[0][1]

    async def test_generate_enforces_character_fallback(self, ontology_gen, mock_llm):
        """即使 LLM 没返回 character，也应自动添加"""
        mock_llm.complete_json.return_value = {
            "entity_types": ["organization", "location"],
            "relation_types": ["ally"],
        }

        result = await ontology_gen.generate(world_doc="test")
        assert "character" in result["entity_types"]

    async def test_generate_caps_entity_types_at_10(self, ontology_gen, mock_llm):
        mock_llm.complete_json.return_value = {
            "entity_types": [f"type_{i}" for i in range(15)],
            "relation_types": ["ally"],
        }

        result = await ontology_gen.generate(world_doc="test")
        assert len(result["entity_types"]) <= 10

    async def test_generate_with_user_preference(self, ontology_gen, mock_llm):
        mock_llm.complete_json.return_value = MOCK_LLM_RESPONSE

        _result = await ontology_gen.generate(
            world_doc="test",
            entity_types_preference=["character", "deity", "artifact"],
        )

        call_args = mock_llm.complete_json.call_args
        prompt = call_args[1]["prompt"] if "prompt" in call_args[1] else call_args[0][1]
        assert "deity" in prompt

    async def test_generate_fills_default_constraints(self, ontology_gen, mock_llm):
        """没有 constraints 时自动填充"""
        mock_llm.complete_json.return_value = {
            "entity_types": ["character", "organization"],
            "relation_types": ["ally"],
        }

        result = await ontology_gen.generate(world_doc="test")
        assert result["constraints"]["min_entity_types"] >= 2
        assert "character" in result["constraints"]["fallback_types"]

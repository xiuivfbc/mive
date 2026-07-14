"""Tests for MaterialService - M1→M2 character material generation."""

import pytest

from src.models.world import Element, WorldDoc, WorldMeta, WorldSource


class TestMaterialService:
    @pytest.fixture
    def service(self):
        from src.services.material_service import MaterialService

        return MaterialService()

    @pytest.fixture
    def sample_world(self):
        """包含角色相关和无关元素的世界观。"""
        return WorldDoc(
            world_id="w-001",
            version="1.0",
            source=WorldSource(title="三体"),
            meta=WorldMeta(),
            elements=[
                Element(
                    id="e1", category="地理环境", name="三体世界", brief="三恒星系统", detail="..."
                ),
                Element(
                    id="e2", category="势力阵营", name="ETO", brief="地球三体组织", detail="..."
                ),
                Element(
                    id="e3", category="社会制度", name="PDC", brief="行星防御理事会", detail="..."
                ),
                Element(
                    id="e4", category="科技/魔法体系", name="智子", brief="质子级设备", detail="..."
                ),
            ],
        )

    def test_generate_returns_character_material(self, service, sample_world):
        """generate() 应返回 CharacterMaterial。"""
        from src.models.material import CharacterMaterial

        material = service.generate(sample_world)

        assert isinstance(material, CharacterMaterial)
        assert material.world_id == "w-001"
        assert material.world_version == "1.0"

    def test_generate_filters_geography_elements(self, service, sample_world):
        """generate() 应过滤掉纯地理环境类元素。"""
        material = service.generate(sample_world)

        names = {e.name for e in material.world_elements}
        assert "三体世界" not in names  # 地理环境被过滤
        assert "ETO" in names
        assert "PDC" in names
        assert "智子" in names

    def test_generate_includes_rules_summary(self, service, sample_world):
        """generate() 应生成世界规则摘要。"""
        material = service.generate(sample_world)

        assert len(material.world_rules_summary) > 0

    def test_generate_empty_world(self, service):
        """空世界观应返回空素材包。"""
        world = WorldDoc(
            world_id="w-empty",
            version="1.0",
            source=WorldSource(),
            meta=WorldMeta(),
            elements=[],
        )

        material = service.generate(world)
        assert material.world_elements == []

    def test_material_not_contain_character_elements(self, service):
        """world_elements 不应包含角色类型元素（category 含 characters/人物/角色）。"""
        world = WorldDoc(
            world_id="w-chars",
            version="1.0",
            source=WorldSource(title="测试"),
            meta=WorldMeta(),
            elements=[
                Element(id="e1", category="characters", name="主角", brief="b", detail="d"),
                Element(id="e2", category="人物角色", name="配角", brief="b", detail="d"),
                Element(id="e3", category="场所", name="学校", brief="b", detail="d"),
                Element(id="e4", category="势力", name="组织", brief="b", detail="d"),
                Element(id="e5", category="角色", name="路人", brief="b", detail="d"),
            ],
        )

        material = service.generate(world)

        names = {e.name for e in material.world_elements}
        # 角色类型元素应被过滤掉
        assert "主角" not in names
        assert "配角" not in names
        assert "路人" not in names
        # 非角色元素应保留
        assert "学校" in names
        assert "组织" in names

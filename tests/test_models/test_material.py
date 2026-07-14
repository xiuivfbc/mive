"""Tests for CharacterMaterial (M1→M2 handoff) model."""

from datetime import datetime


class TestCharacterMaterial:
    def test_material_contains_world_elements(self):
        """素材包应包含筛选后的世界观元素。"""
        from src.models.material import CharacterMaterial, MaterialElement

        mat = CharacterMaterial(
            world_id="w-001",
            world_version="1.0",
            world_elements=[
                MaterialElement(
                    id="e1",
                    category="势力阵营",
                    name="ETO",
                    brief="地球三体组织",
                    detail="详细描述...",
                ),
            ],
            world_rules_summary="三体世界基本规则摘要",
            generated_at=datetime.now(),
        )
        assert len(mat.world_elements) == 1
        assert mat.world_elements[0].category == "势力阵营"

    def test_material_has_rules_summary(self):
        """素材包必须包含世界规则摘要字符串。"""
        from src.models.material import CharacterMaterial

        mat = CharacterMaterial(
            world_id="w-001",
            world_version="1.0",
            world_elements=[],
            world_rules_summary="规则摘要",
            generated_at=datetime.now(),
        )
        assert isinstance(mat.world_rules_summary, str)
        assert len(mat.world_rules_summary) > 0

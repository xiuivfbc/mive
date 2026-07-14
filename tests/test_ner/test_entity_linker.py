"""Tests for NER entity linker - dedup and standardization."""

from src.models.world import Element
from src.ner.entity_linker import levenshtein_distance, link_entities


class TestLevenshteinDistance:
    def test_identical_strings(self):
        assert levenshtein_distance("abc", "abc") == 0

    def test_single_insert(self):
        assert levenshtein_distance("abc", "abcd") == 1

    def test_single_delete(self):
        assert levenshtein_distance("abc", "ab") == 1

    def test_single_substitute(self):
        assert levenshtein_distance("abc", "axc") == 1

    def test_two_edits(self):
        assert levenshtein_distance("abc", "axy") == 2

    def test_empty_string(self):
        assert levenshtein_distance("", "abc") == 3
        assert levenshtein_distance("", "") == 0


class TestLinkEntities:
    def test_empty_list(self):
        assert link_entities([]) == []

    def test_no_duplicates_kept_separate(self):
        elements = [
            Element(id="e1", category="势力阵营", name="ETO", brief="...", detail="..."),
            Element(id="e2", category="势力阵营", name="PDC", brief="...", detail="..."),
        ]
        result = link_entities(elements)
        assert len(result) == 2

    def test_exact_duplicate_merged(self):
        elements = [
            Element(
                id="e1", category="势力阵营", name="ETO", brief="地球三体组织", detail="短描述"
            ),
            Element(
                id="e2",
                category="势力阵营",
                name="ETO",
                brief="地球三体组织",
                detail="这是一个详细的地球三体组织描述，包含更多内容",
            ),
        ]
        result = link_entities(elements)
        assert len(result) == 1
        assert result[0].detail == "这是一个详细的地球三体组织描述，包含更多内容"

    def test_edit_distance_one_merged(self):
        """编辑距离为1的名称应合并。"""
        elements = [
            Element(id="e1", category="势力阵营", name="地球防卫组织", brief="...", detail="短"),
            Element(
                id="e2", category="势力阵营", name="地球防务组织", brief="...", detail="更长的描述"
            ),
        ]
        result = link_entities(elements)
        assert len(result) == 1
        assert result[0].detail == "更长的描述"

    def test_edit_distance_two_kept_separate(self):
        """编辑距离>=2的名称不应合并。"""
        elements = [
            Element(id="e1", category="势力阵营", name="ETO", brief="...", detail="..."),
            Element(id="e2", category="势力阵营", name="PDC", brief="...", detail="..."),
        ]
        result = link_entities(elements)
        assert len(result) == 2

    def test_substring_match_merged(self):
        """一个名称是另一个的子串时应合并（标准化）。"""
        elements = [
            Element(
                id="e1", category="势力阵营", name="地球防卫组织", brief="...", detail="完整描述"
            ),
            Element(id="e2", category="势力阵营", name="防卫组织", brief="...", detail="短"),
        ]
        result = link_entities(elements)
        assert len(result) == 1

    def test_different_categories_not_merged(self):
        """不同分类的同名元素不应合并。"""
        elements = [
            Element(id="e1", category="势力阵营", name="水星", brief="...", detail="..."),
            Element(id="e2", category="地理环境", name="水星", brief="...", detail="..."),
        ]
        result = link_entities(elements)
        assert len(result) == 2

    def test_merged_element_keeps_longer_brief(self):
        """合并时保留更长的 brief。"""
        elements = [
            Element(id="e1", category="势力阵营", name="ETO", brief="短", detail="短"),
            Element(
                id="e2",
                category="势力阵营",
                name="ETO",
                brief="这是更长的一句话简介",
                detail="长描述",
            ),
        ]
        result = link_entities(elements)
        assert result[0].brief == "这是更长的一句话简介"

    def test_preserves_first_id(self):
        """合并后保留第一个元素的 id。"""
        elements = [
            Element(id="e1", category="势力阵营", name="ETO", brief="...", detail="..."),
            Element(id="e2", category="势力阵营", name="ETO", brief="...", detail="..."),
        ]
        result = link_entities(elements)
        assert result[0].id == "e1"

    def test_multiple_groups(self):
        """多个分组各自独立去重。"""
        elements = [
            Element(id="e1", category="势力阵营", name="ETO", brief="...", detail="短"),
            Element(id="e2", category="势力阵营", name="ETO", brief="...", detail="长"),
            Element(id="e3", category="地理环境", name="北方基地", brief="...", detail="..."),
            Element(id="e4", category="地理环境", name="南方堡垒", brief="...", detail="..."),
        ]
        result = link_entities(elements)
        assert len(result) == 3

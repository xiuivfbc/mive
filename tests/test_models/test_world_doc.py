"""Tests for WorldDoc Pydantic model."""

from datetime import datetime


class TestWorldSource:
    def test_source_accepts_optional_fields(self):
        """WorldSource 各字段都是可选的，最少可以什么都不传。"""
        from src.models.world import WorldSource

        source = WorldSource()
        assert source.title is None
        assert source.author is None
        assert source.references == []

    def test_source_with_full_data(self):
        """WorldSource 可以完整填充。"""
        from src.models.world import WorldSource

        source = WorldSource(
            title="三体",
            author="刘慈欣",
            type="小说",
            references=["https://example.com/wiki"],
            input_text="硬科幻经典",
        )
        assert source.title == "三体"
        assert len(source.references) == 1


class TestWorldMeta:
    def test_meta_auto_generates_timestamps(self):
        """WorldMeta 的 created_at 和 updated_at 应自动填充。"""
        from src.models.world import WorldMeta

        meta = WorldMeta()
        assert meta.created_at is not None
        assert meta.updated_at is not None
        assert isinstance(meta.created_at, datetime)


class TestWorldDoc:
    def test_world_doc_requires_elements_list(self):
        """WorldDoc 必须包含 elements 列表，即使为空。"""
        from src.models.world import WorldDoc, WorldMeta, WorldSource

        doc = WorldDoc(
            world_id="w-001",
            version="1.0",
            source=WorldSource(title="三体"),
            meta=WorldMeta(),
            elements=[],
        )
        assert doc.world_id == "w-001"
        assert doc.elements == []

    def test_world_doc_contains_elements(self):
        """WorldDoc 可以包含多个 Element。"""
        from src.models.world import Element, WorldDoc, WorldMeta, WorldSource

        doc = WorldDoc(
            world_id="w-001",
            version="1.0",
            source=WorldSource(title="三体"),
            meta=WorldMeta(),
            elements=[
                Element(
                    id="e1",
                    category="地理环境",
                    name="三体世界",
                    brief="三恒星系统",
                    detail="详细描述...",
                ),
                Element(
                    id="e2",
                    category="势力阵营",
                    name="ETO",
                    brief="地球三体组织",
                    detail="详细描述...",
                ),
            ],
        )
        assert len(doc.elements) == 2
        assert doc.elements[0].name == "三体世界"

    def test_world_doc_defaults(self):
        """WorldDoc 的 world_base_id 默认为 None，version 默认 1.0。"""
        from src.models.world import WorldDoc, WorldMeta, WorldSource

        doc = WorldDoc(
            world_id="w-001",
            source=WorldSource(),
            meta=WorldMeta(),
            elements=[],
        )
        assert doc.world_base_id is None
        assert doc.version == "1.0"

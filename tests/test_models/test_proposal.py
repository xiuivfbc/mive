"""WorldVersion 模型测试（ChangeProposal 已删除，仅测试 WorldVersion）。"""

from src.models.proposal import WorldVersion


class TestWorldVersion:
    def test_defaults(self):
        v = WorldVersion(id="v-001", world_id="w-001")
        assert v.snapshot == {}
        assert v.parent_version_id is None

    def test_with_snapshot(self):
        snapshot = {"characters": [{"id": "c-1", "name": "叶文洁"}], "relations": []}
        v = WorldVersion(
            id="v-002",
            world_id="w-001",
            snapshot=snapshot,
            summary="初始版本",
            created_by="user",
        )
        assert len(v.snapshot["characters"]) == 1
        assert v.summary == "初始版本"

    def test_optional_parent(self):
        v = WorldVersion(id="v-child", world_id="w-001", parent_version_id="v-parent")
        assert v.parent_version_id == "v-parent"

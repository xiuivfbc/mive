import uuid

from src.db.models import M2Relation


class TestM2RelationORM:
    """M2Relation ORM 模型结构测试"""

    def test_table_name_is_m2_relations(self):
        assert M2Relation.__tablename__ == "m2_relations"

    def test_columns_exist(self):
        rel = M2Relation(
            world_id=uuid.uuid4(),
            character_a=uuid.uuid4(),
            character_b=uuid.uuid4(),
            type="父女",
        )
        assert rel.id is None
        assert rel.world_id is not None
        assert rel.character_a is not None
        assert rel.character_b is not None
        assert rel.type == "父女"

    def test_default_values(self):
        rel = M2Relation(
            world_id=uuid.uuid4(),
            character_a=uuid.uuid4(),
            character_b=uuid.uuid4(),
        )
        # DB default applies on INSERT, Python side may be None
        assert rel.direction in ("bidirectional", None)
        assert rel.status in ("active", None)

    def test_historical_changes_accepts_list(self):
        changes = [{"time": "1967年", "event": "父亲被迫害"}]
        rel = M2Relation(
            world_id=uuid.uuid4(),
            character_a=uuid.uuid4(),
            character_b=uuid.uuid4(),
            historical_changes=changes,
        )
        assert rel.historical_changes == changes

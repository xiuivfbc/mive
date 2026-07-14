import uuid
from datetime import datetime

import pytest
from pydantic import ValidationError

from src.db.models import M2Character
from src.models.character import Character, CreateCharacterRequest, UpdateCharacterRequest


class TestCharacterPydantic:
    """Character Pydantic 响应模型测试"""

    def test_character_fields(self):
        char = Character(
            id=str(uuid.uuid4()),
            world_id=str(uuid.uuid4()),
            name="叶文洁",
            profile={"basic": {"name": "叶文洁"}, "brief": "", "detail": ""},
        )
        assert char.name == "叶文洁"
        assert char.portrait_url is None
        assert isinstance(char.created_at, datetime)

    def test_character_with_full_profile(self):
        char = Character(
            id=str(uuid.uuid4()),
            world_id=str(uuid.uuid4()),
            name="叶文洁",
            profile={
                "basic": {"name": "叶文洁", "gender": "female", "age": 45},
                "brief": "天体物理学家",
                "detail": "详细描述",
            },
        )
        assert char.profile["basic"]["age"] == 45


class TestCreateCharacterRequest:
    """创建角色请求模型测试"""

    def test_name_required(self):
        with pytest.raises(ValidationError):
            CreateCharacterRequest()

    def test_name_must_not_be_empty(self):
        with pytest.raises(ValidationError):
            CreateCharacterRequest(name="")

    def test_create_with_name_only(self):
        req = CreateCharacterRequest(name="叶文洁")
        assert req.name == "叶文洁"
        assert req.portrait_url is None
        assert req.profile is None

    def test_create_with_full_data(self):
        req = CreateCharacterRequest(
            name="叶文洁",
            portrait_url="http://example.com/portrait.jpg",
            profile={
                "basic": {"name": "叶文洁"},
                "brief": "科学家",
                "detail": "",
            },
        )
        assert req.portrait_url == "http://example.com/portrait.jpg"
        assert req.profile["brief"] == "科学家"


class TestUpdateCharacterRequest:
    """更新角色请求模型测试"""

    def test_all_fields_optional(self):
        req = UpdateCharacterRequest()
        assert req.name is None
        assert req.portrait_url is None
        assert req.profile is None

    def test_update_name_only(self):
        req = UpdateCharacterRequest(name="汪淼")
        assert req.name == "汪淼"
        assert req.profile is None

    def test_update_profile_only(self):
        req = UpdateCharacterRequest(profile={"brief": "纳米材料科学家"})
        assert req.profile == {"brief": "纳米材料科学家"}


class TestM2CharacterORM:
    """M2Character ORM 模型结构测试"""

    def test_table_name_is_m2_characters(self):
        assert M2Character.__tablename__ == "m2_characters"

    def test_columns_exist(self):
        char = M2Character(
            world_id=uuid.uuid4(),
            name="叶文洁",
            profile={"basic": {"name": "叶文洁"}},
        )
        assert char.id is None  # DB 生成
        assert char.world_id is not None
        assert char.name == "叶文洁"
        assert char.portrait_url is None
        assert char.profile == {"basic": {"name": "叶文洁"}}
        assert char.created_at is None  # DB 默认
        assert char.updated_at is None

    def test_profile_accepts_dict(self):
        profile = {
            "basic": {"name": "叶文洁", "gender": "female", "age": 45},
            "brief": "天体物理学家",
            "detail": "详细描述",
        }
        char = M2Character(
            world_id=uuid.uuid4(),
            name="叶文洁",
            profile=profile,
        )
        assert char.profile == profile

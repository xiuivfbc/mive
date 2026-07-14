"""Tests for Element Pydantic model."""

import pytest
from pydantic import ValidationError


class TestElementCreation:
    def test_element_requires_all_fields(self):
        """Element 必须包含 id, category, name, brief, detail 五个字段。"""
        from src.models.world import Element

        elem = Element(
            id="elem_001",
            category="地理环境",
            name="三体世界",
            brief="半人马座α星系的行星系统，拥有三颗恒星",
            detail="由于三体运动的混沌性，该行星经历恒纪元与乱纪元的交替。",
        )
        assert elem.id == "elem_001"
        assert elem.category == "地理环境"
        assert elem.name == "三体世界"
        assert "恒纪元" in elem.detail

    def test_element_rejects_missing_fields(self):
        """缺少必填字段时应抛出 ValidationError。"""
        from src.models.world import Element

        with pytest.raises(ValidationError):
            Element(id="elem_001", category="地理环境")

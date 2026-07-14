from datetime import datetime

from src.domain.material import _CHAR_CATEGORY_KEYWORDS, EXCLUDED_CATEGORIES
from src.models.material import CharacterMaterial
from src.models.world import Element, WorldDoc


class MaterialService:
    def generate(self, world: WorldDoc) -> CharacterMaterial:
        elements = [
            Element(
                id=e.id,
                category=e.category,
                name=e.name,
                brief=e.brief,
                detail=e.detail,
            )
            for e in world.elements
            if e.category not in EXCLUDED_CATEGORIES
            and not any(kw in e.category for kw in _CHAR_CATEGORY_KEYWORDS)
        ]

        rules_summary = self._build_rules_summary(world)

        return CharacterMaterial(
            world_id=world.world_id,
            world_version=world.version,
            world_elements=elements,
            world_rules_summary=rules_summary,
            generated_at=datetime.now(),
        )

    def _build_rules_summary(self, world: WorldDoc) -> str:
        if not world.elements:
            return ""
        title = world.source.title or "未知作品"
        author = world.source.author or ""
        categories = sorted({e.category for e in world.elements})
        # 取非人物类的核心设定元素作为世界规则说明
        setting_elements = [
            e for e in world.elements if "人物" not in e.category and "角色" not in e.category
        ][:6]
        parts = [f"作品：《{title}》" + (f"（{author}）" if author else "")]
        parts.append(f"元素总数：{len(world.elements)}，分类：{', '.join(categories)}")
        if setting_elements:
            parts.append("核心设定：")
            for e in setting_elements:
                parts.append(f"  [{e.category}] {e.name}: {e.brief}")
        return "\n".join(parts)

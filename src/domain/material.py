"""素材包领域规则：过滤与生成。"""

# 从素材包中排除的元素分类（这些分类不参与角色生成）
EXCLUDED_CATEGORIES = {"地理环境"}

# 角色相关的分类关键词（匹配到则排除）
_CHAR_CATEGORY_KEYWORDS = ("人物", "角色", "characters")

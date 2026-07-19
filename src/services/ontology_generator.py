"""M6 OntologyGenerator — 从世界文档中推断实体/关系类型定义。"""

from src.llm.base import LLMProvider, llm_operation

SYSTEM_PROMPT = (
    "你是一个知识图谱本体设计专家。根据给定的世界观文档，设计适合虚拟世界角色关系图谱的实体类型和关系类型。\n"
    "输出严格 JSON，不要多余文本。\n\n"
    "## 输出格式\n"
    "```json\n"
    "{\n"
    '  "entity_types": ["character", "organization", "location", ...],\n'
    '  "relation_types": ["family", "enemy", "ally", ...],\n'
    '  "constraints": {\n'
    '    "min_entity_types": 2,\n'
    '    "max_entity_types": 10,\n'
    '    "fallback_types": ["character", "concept"]\n'
    "  }\n"
    "}\n"
    "```\n\n"
    "## 规则\n"
    "1. entity_types 数量在 2-10 之间。\n"
    "2. 必须包含 'character' 作为核心实体类型。\n"
    "3. relation_types 数量在 3-15 之间。\n"
    "4. 类型名称使用英文小写 snake_case。\n"
    "5. 保持简洁，不要过度细分。"
)

MAX_ENTITY_TYPES = 10


class OntologyGenerator:
    def __init__(self, llm: LLMProvider):
        self.llm = llm

    async def generate(
        self,
        world_doc: str,
        entity_types_preference: list[str] | None = None,
    ) -> dict:
        llm_operation.set("本体生成")
        prompt = f"世界观文档:\n{world_doc}\n"

        if entity_types_preference:
            prompt += (
                f"\n用户指定的实体类型偏好（请尽量包含）: {', '.join(entity_types_preference)}\n"
            )

        result = await self.llm.complete_json(
            system=SYSTEM_PROMPT,
            prompt=prompt,
            temperature=0.3,
            max_tokens=2048,
        )

        if not isinstance(result, dict):
            result = {}

        return self._validate(result)

    def _validate(self, result: dict) -> dict:
        if "entity_types" not in result:
            result["entity_types"] = []
        if "relation_types" not in result:
            result["relation_types"] = []
        if "constraints" not in result:
            result["constraints"] = {}

        # 去重保留顺序
        seen = set()
        deduped = []
        for t in result["entity_types"]:
            if t not in seen:
                seen.add(t)
                deduped.append(t)
        result["entity_types"] = deduped

        # 确保 character 存在
        if "character" not in result["entity_types"]:
            result["entity_types"].insert(0, "character")

        # 截断到 MAX_ENTITY_TYPES
        result["entity_types"] = result["entity_types"][:MAX_ENTITY_TYPES]

        # 填充 constraints 默认值
        c = result["constraints"]
        c.setdefault("min_entity_types", 2)
        c.setdefault("max_entity_types", MAX_ENTITY_TYPES)
        fallback = c.get("fallback_types", [])
        if "character" not in fallback:
            fallback.insert(0, "character")
        c["fallback_types"] = fallback

        return result

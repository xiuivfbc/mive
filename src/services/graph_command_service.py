import logging
import re

from src.db.repositories.character_repo import CharacterRepository
from src.db.repositories.relation_repo import RelationRepository
from src.llm.base import LLMPriority, LLMProvider, get_lang_hint, llm_operation
from src.services.character_service import CharacterService
from src.services.relation_service import RelationService

logger = logging.getLogger(__name__)


def _clean_command(command: str) -> str:
    """去除 @ 标记，压缩连续空白，合并重复标点。"""
    cmd = command.replace("@", "")
    cmd = re.sub(r"[，,]{2,}", "，", cmd)
    cmd = re.sub(r"[。.]{2,}", "。", cmd)
    cmd = re.sub(r"\s+", " ", cmd).strip()
    return cmd


_PARSE_SYSTEM = """你是图谱编辑助手。根据用户的自然语言指令，输出需要执行的操作列表。

## 规则
- 只做用户要求的事，不添加额外操作
- 不评价合理性，用户说什么就做什么
- 角色名称必须与现有角色列表完全匹配（如有）
- 新增角色时，若用户未指定属性则合理推断

只输出严格 JSON，不要 Markdown。格式：
```json
{
  "operations": [
    {"op": "add_character", "name": "...",
     "tier": "core|supporting|extra",
     "gender": "male|female|unknown", "age": null,
     "occupation": "...", "brief": "..."},
    {"op": "add_relation", "character_a": "姓名",
     "character_b": "姓名", "type": "关系类型(2-8字)",
     "description": "简短描述",
     "direction": "bidirectional|a_to_b|b_to_a"},
    {"op": "delete_relation", "character_a": "姓名",
     "character_b": "姓名"},
    {"op": "update_relation", "character_a": "姓名",
     "character_b": "姓名",
     "changes": {"type": "...", "description": "..."}},
    {"op": "delete_character", "name": "姓名"},
    {"op": "update_character", "name": "姓名", "changes": {"brief": "...", "tier": "..."}}
  ],
  "summary": "..."
}
```"""


class GraphCommandService:
    def __init__(
        self,
        llm: LLMProvider,
        char_repo: CharacterRepository,
        rel_repo: RelationRepository,
    ):
        self.llm = llm
        self._session = char_repo.session
        self.char_service = CharacterService(repo=char_repo)
        self.rel_service = RelationService(repo=rel_repo)

    async def parse(self, world_id: str, command: str) -> dict:
        """将自然语言指令解析为操作列表（预览用，不写库）。"""
        llm_operation.set("图谱解析")
        chars = await self.char_service.list_by_world(world_id)
        rels = await self.rel_service.list_by_world(world_id)

        id_to_name = {c.id: c.name for c in chars}
        char_names = [c.name for c in chars]

        # 用 @name 精确匹配提到的角色，过滤相关关系线
        mentioned = {name for name in char_names if f"@{name}" in command}
        if mentioned:
            name_to_id = {c.name: c.id for c in chars}
            mentioned_ids = {name_to_id[n] for n in mentioned}
            relevant_rels = [
                r for r in rels if r.character_a in mentioned_ids or r.character_b in mentioned_ids
            ]
        else:
            relevant_rels = []

        rel_desc = [
            f"{id_to_name.get(r.character_a, r.character_a)}"
            f"↔{id_to_name.get(r.character_b, r.character_b)}"
            f":{r.type}"
            for r in relevant_rels
        ]

        clean_cmd = _clean_command(command)
        prompt = f"角色:{char_names}\n关系:{rel_desc}\n指令:{clean_cmd}"

        result = await self.llm.complete_json(
            _PARSE_SYSTEM + get_lang_hint(), prompt, priority=LLMPriority.EVENT
        )
        if not isinstance(result, dict):
            return {"operations": [], "summary": "解析失败"}

        ops = result.get("operations", [])
        if not isinstance(ops, list):
            ops = []

        return {
            "operations": ops,
            "summary": result.get("summary", ""),
        }

    async def apply(self, world_id: str, operations: list[dict]) -> dict:
        """执行操作列表，直接写库，返回变更摘要。"""
        session = self._session
        chars = await self.char_service.list_by_world(world_id)
        rels = await self.rel_service.list_by_world(world_id)

        name_to_char = {c.name: c for c in chars}

        added_chars, added_rels, deleted_rels, updated_rels = [], [], [], []
        errors = []

        for op in operations:
            kind = op.get("op")
            try:
                async with session.begin_nested():
                    if kind == "add_character":
                        from src.models.character import CreateCharacterRequest

                        req = CreateCharacterRequest(
                            name=op["name"],
                            profile={
                                "basic": {
                                    "name": op["name"],
                                    "gender": op.get("gender", "未知"),
                                    "age": op.get("age"),
                                    "occupation": op.get("occupation", ""),
                                    "race": "人类",
                                    "tier": op.get("tier", "supporting"),
                                },
                                "brief": op.get("brief", ""),
                                "detail": "",
                            },
                        )
                        char = await self.char_service.create(world_id, req)
                        name_to_char[char.name] = char
                        added_chars.append(char.name)

                    elif kind == "add_relation":
                        ca = name_to_char.get(op["character_a"])
                        cb = name_to_char.get(op["character_b"])
                        if not ca or not cb:
                            errors.append(
                                f"找不到角色: {op.get('character_a')} 或 {op.get('character_b')}"
                            )
                        else:
                            from src.models.relation import CreateRelationRequest

                            req = CreateRelationRequest(
                                character_a=ca.id,
                                character_b=cb.id,
                                type=op.get("type", "关联"),
                                description=op.get("description", ""),
                                direction=op.get("direction", "bidirectional"),
                            )
                            await self.rel_service.create(world_id, req)
                            added_rels.append(
                                f"{op['character_a']} ↔ {op['character_b']}: {op.get('type', '')}"
                            )

                    elif kind == "delete_relation":
                        ca = name_to_char.get(op["character_a"])
                        cb = name_to_char.get(op["character_b"])
                        if not ca or not cb:
                            errors.append(
                                f"找不到角色: {op.get('character_a')} 或 {op.get('character_b')}"
                            )
                        else:
                            target = next(
                                (
                                    r
                                    for r in rels
                                    if (r.character_a == ca.id and r.character_b == cb.id)
                                    or (r.character_a == cb.id and r.character_b == ca.id)
                                ),
                                None,
                            )
                            if target:
                                await self.rel_service.delete(target.id)
                                deleted_rels.append(f"{op['character_a']} ↔ {op['character_b']}")
                            else:
                                errors.append(
                                    f"关系不存在: {op.get('character_a')} ↔ {op.get('character_b')}"
                                )

                    elif kind == "update_relation":
                        ca = name_to_char.get(op["character_a"])
                        cb = name_to_char.get(op["character_b"])
                        if not ca or not cb:
                            errors.append(
                                f"找不到角色: {op.get('character_a')} 或 {op.get('character_b')}"
                            )
                        else:
                            target = next(
                                (
                                    r
                                    for r in rels
                                    if (r.character_a == ca.id and r.character_b == cb.id)
                                    or (r.character_a == cb.id and r.character_b == ca.id)
                                ),
                                None,
                            )
                            if target:
                                from src.models.relation import UpdateRelationRequest

                                changes = op.get("changes", {})
                                req = UpdateRelationRequest(
                                    type=changes.get("type", target.type),
                                    description=changes.get("description", target.description),
                                    direction=changes.get("direction", target.direction),
                                )
                                await self.rel_service.update(target.id, req)
                                updated_rels.append(f"{op['character_a']} ↔ {op['character_b']}")
                            else:
                                errors.append(
                                    f"关系不存在: {op.get('character_a')} ↔ {op.get('character_b')}"
                                )

                    elif kind == "delete_character":
                        char = name_to_char.get(op["name"])
                        if char:
                            await self.rel_service.delete_by_character(char.id)
                            await self.char_service.delete(char.id)
                        else:
                            errors.append(f"角色不存在: {op.get('name')}")

                    elif kind == "update_character":
                        char = name_to_char.get(op["name"])
                        if char:
                            from src.models.character import UpdateCharacterRequest

                            changes = op.get("changes", {})
                            profile = dict(char.profile or {})
                            if "brief" in changes:
                                profile["brief"] = changes["brief"]
                            tier = changes.get("tier")
                            req = UpdateCharacterRequest(profile=profile, tier=tier)
                            await self.char_service.update(char.id, req)
                        else:
                            errors.append(f"角色不存在: {op.get('name')}")

            except Exception as e:
                logger.warning("operation %s failed: %s", kind, e)
                errors.append(f"{kind} 执行失败: {e}")

        # 更新角色/关系计数
        if added_chars or added_rels or deleted_rels:
            import uuid

            from sqlalchemy import func, select

            from src.db.models import M1World, M2Character, M2Relation

            char_cnt = (
                await session.execute(
                    select(func.count())
                    .select_from(M2Character)
                    .where(M2Character.world_id == uuid.UUID(world_id))
                )
            ).scalar() or 0
            rel_cnt = (
                await session.execute(
                    select(func.count())
                    .select_from(M2Relation)
                    .where(M2Relation.world_id == uuid.UUID(world_id))
                )
            ).scalar() or 0
            world_row = await session.get(M1World, uuid.UUID(world_id))
            if world_row:
                world_row.character_summary = {"count": char_cnt}
                world_row.relationship_summary = {"count": rel_cnt}

        return {
            "added_chars": added_chars,
            "added_rels": added_rels,
            "deleted_rels": deleted_rels,
            "updated_rels": updated_rels,
            "errors": errors,
        }

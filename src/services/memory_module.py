"""Unified memory module — consolidates short-term generation, long-term promotion,
and memory propagation logic previously scattered across EventDialogueService and MessageService.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

from src.llm.base import LLMPriority, get_lang_hint
from src.models.character import Character
from src.utils.llm_utils import unwrap_list as _unwrap_list

if TYPE_CHECKING:
    from redis.asyncio import Redis
    from sqlalchemy.ext.asyncio import AsyncSession

    from src.db.repositories.character_memory_repo import CharacterMemoryRepository
    from src.db.repositories.character_repo import CharacterRepository
    from src.db.repositories.relation_repo import RelationRepository
    from src.db.repositories.world_repo import WorldRepository
    from src.llm.base import LLMProvider
    from src.llm.embedding_provider import EmbeddingProvider

logger = logging.getLogger(__name__)


# ── Prompt: batch short-term memory generation ─────────────────────────────
BATCH_SHORT_TERM_MEMORY_PROMPT = """\
你是角色状态记录器。根据刚发生的事件和对话，为每个参与角色各写一条近期记忆。

## 要求

- 每个角色最多 1 条，没有值得记录的体验则 content 填 null
- 第一人称（"我..."）
- 100字以内
- 记录角色在此次事件中做了什么、经历了什么、做了什么决定
- 事件描述需要包含核心要素：谁、做了什么、关键结果
- 不得虚构对话中没有的内容
- 时间词用"刚才"/"今天"（短期记忆是新鲜的）

## 分类标签（必填）

为每条记忆打上分类标签：
- "trivial"：日常琐碎，无持续影响（吃了碗面、路过集市）
- "private"：少数人之间的事，不宜公开（两人密谈、私下交易）
- "major"：影响范围大，值得被世界记住（战斗、政变、重大发现）

## 感悟（可选）

角色对该事件的内心反应。有则写，没有就不写或填 null。
不是每个事件都会引发感悟，不要强求。

参与角色档案：
{characters_brief}

刚发生的事件：{event_description}

本次对话：
{dialogue_text}

## 输出格式

```json
[{{"character": "角色名", "content": "我..." 或 null,
  "category": "trivial"/"private"/"major",
  "reflection": "感悟" 或 null}}]
```
"""


# ── Prompt: long-term promotion — phase 1 (select relevant elements) ──────
LONG_TERM_SELECT_ELEMENTS_PROMPT = """\
你是角色长期记忆提炼器。根据以下角色信息和近期记忆，从元素列表中选出与这批记忆最相关的 5 个元素。

## 要求

只返回元素名称列表，不要解释。

## 输出格式

```json
["元素名1", "元素名2", ...]
```
"""


# ── Prompt: long-term promotion — phase 2 (decide promotion) ──────────────
LONG_TERM_PROMOTE_PROMPT = """\
你是角色长期记忆提炼器。你的任务是模拟人类长期记忆的形成机制，从一批短期记忆中筛选出真正值得沉淀为长期记忆的条目。

## 输入说明

你会收到以下信息：
- 角色的完整档案（简介、详细背景、关系网络）
- 该角色的近期短期记忆（按时间正序排列，琐事已被过滤）
- 与这批记忆最相关的世界元素详细信息
- 已有事件索引（E001, E002, ... 格式，每条含事件简介）
- 已有事件名列表（用于命名一致性参考）
- 参与角色代号映射（C1, C2, ... 对应角色名）
- 短期记忆中的感悟素材（如有）

## 晋升标准

只有满足以下至少一条维度的记忆才值得晋升为长期记忆：

1. **重大人生转折**：角色的生死关头、身份转变、命运分叉点
2. **关系质变事件**：从信任到怀疑、从敌对到和解、背叛、结盟——关系发生了不可逆的根本变化
3. **认知颠覆经历**：角色的世界观、信念体系、对某个重要事物的理解被彻底改变
4. **强烈情绪烙印**：伴随极端情绪的事件——深刻的恐惧、狂喜、
绝望、感动、愤怒、哀伤。这种情绪即使事后回想仍会涌上心头

## 反例（以下内容绝不晋升）

- 日常问候、例行寒暄、普通闲聊
- 例行任务执行、重复性事务（如每天的工作汇报、巡逻、训练）
- 没有任何情感波动的中性对话
- 信息交换型对话（讨论天气、分享情报但未引发决策或冲突）
- 角色只是在场但未被实质影响的事件

## 事件匹配规则

对每条值得晋升的记忆，判断其对应的事件：

1. **匹配已有事件**：参考事件索引（E001, E002, ...），如果该记忆的
经历与某个已有事件是同一件事，输出对应的事件代码（如 "E001"）。
2. **新事件**：如果没有匹配的已有事件，标记为 "new"，并提供事件名和
简介（brief，一句话概括核心内容，包含谁、做了什么、关键结果）。

事件名必须简洁（2-8字），如"王城之变"、"黑森林事件"。

## 参与角色代号

用代号（C1, C2, ...）指代角色，避免名字拼写歧义。代号映射已在输入中提供。

## 模糊化规则

对值得晋升的记忆，必须进行模糊化处理，模拟人类长期记忆的自然褪色：

- **时间词替换**："刚才" → "某次"/"很久以前"/"那个冬天"/"在一次……中"
- **细节褪去**：只保留核心事实（谁做了什么、结果如何）和情绪烙印，丢弃具体措辞、顺序、数量等细节
- **视角统一**：第一人称（"我……"）

## 感悟处理

- 如果短期记忆有感悟素材，在此基础上深化为长期记忆的感悟。保持角色一致性，可以扩展但不要矛盾。
- 如果短期记忆没有感悟且事件是大事（影响范围大、对角色有明显影响），
倾向生成感悟——大事通常会对角色产生影响。
- 如果事件是私事且无感悟，感悟可以留 null。

## 输出格式

```json
{{"promote": [
  {{"event_name": "事件名",
    "event_code": "E001" 或 "new",
    "event_brief": "事件简介（仅新事件需要）",
    "perspective_detail":
      "角色视角下的事件详情（模糊化，第一人称）",
    "reflection": "角色的感悟/内心反应" 或 null,
    "involved_characters": ["C1", "C2"]}}
]}}
```

如果没有条目值得晋升为长期记忆，返回 `{{"promote": []}}`

## 重要提醒

- 宁可全部丢弃也不要晋升不值得的记忆。长期记忆是稀缺资源，平庸的记忆会稀释真正重要记忆的价值。
- 同时也不要遗漏真正震撼的事件——如果某条记忆确实满足上述标准，务必晋升。
- perspective_detail 必须是角色的主观视角，不是客观叙述。
- reflection 是角色的内心感悟，驱动后续行为决策。
"""


class MemoryModule:
    """Unified memory module consolidating short-term generation and long-term promotion."""

    def __init__(
        self,
        llm: LLMProvider,
        session_factory,
        redis: Redis | None = None,
    ):
        self.llm = llm
        self.session_factory = session_factory
        self._redis = redis

    async def generate_short_term_memories(
        self,
        session: AsyncSession,
        world_id: str,
        char_map: dict[str, Character],
        dialogue_text: str,
        event_description: str,
        memory_repo: CharacterMemoryRepository,
        session_id: uuid.UUID | None = None,
        embedding_provider: EmbeddingProvider | None = None,
    ) -> list:
        """Unified short-term memory generation (batch LLM with classification).

        Returns list of newly written memory objects.
        """
        lang_hint = get_lang_hint()

        characters_info = "\n".join(
            f'<character name="{name}">'
            f"<brief>{(c.profile or {}).get('brief', '暂无')}</brief>"
            f"<detail>{(c.profile or {}).get('detail', '暂无')}</detail>"
            f"</character>"
            for name, c in char_map.items()
        )

        system_prompt = BATCH_SHORT_TERM_MEMORY_PROMPT + lang_hint
        user_prompt = (
            f"参与角色档案：\n{characters_info}\n\n"
            f"刚发生的事件：{event_description}\n\n"
            f"本次对话：\n{dialogue_text}"
        )

        try:
            result = await self.llm.complete_json(
                system_prompt,
                user_prompt,
                prefill="[",
                priority=LLMPriority.BACKGROUND,
            )
        except Exception:
            result = None

        newly_written: list = []
        if result is not None:
            items = _unwrap_list(result)
            for item in items:
                if not isinstance(item, dict):
                    continue
                char_name = item.get("character", "")
                content = item.get("content")
                if not content or not char_name:
                    continue
                character = char_map.get(char_name)
                if not character:
                    continue
                category = item.get("category")
                if category not in ("trivial", "private", "major"):
                    category = None
                reflection = item.get("reflection")
                if not isinstance(reflection, str) or not reflection.strip():
                    reflection = None
                mem_obj = await memory_repo.add(
                    character_id=uuid.UUID(character.id),
                    world_id=uuid.UUID(world_id),
                    session_id=session_id,
                    memory_type="short_term",
                    content=content,
                    memory_category=category,
                    short_term_reflection=reflection,
                )
                newly_written.append(mem_obj)

        # Compute and store embeddings for newly written memories
        if newly_written and embedding_provider is not None:
            try:
                texts = [m.content for m in newly_written]
                embeddings = await embedding_provider.embed(texts)
                for mem_obj, emb in zip(newly_written, embeddings, strict=True):
                    await memory_repo.set_embedding(mem_obj.id, emb)
            except Exception:
                logger.warning("Failed to compute embeddings for short-term memories, skipping")

        return newly_written

    async def promote_long_term_memories_for_character(
        self,
        session: AsyncSession,
        world_id: str,
        character: Character,
        memory_repo: CharacterMemoryRepository,
        world_repo: WorldRepository,
        relation_repo: RelationRepository,
        char_repo: CharacterRepository,
    ) -> None:
        """Two-phase long-term memory promotion for a single character.

        Phase 1: select relevant elements via LLM.
        Phase 2: judge which short-term memories deserve promotion.
        """
        lang_hint = get_lang_hint()

        # V2: exclude trivial memories from promotion candidates
        # 注意：这里故意不转换为 uuid.UUID——SQLAlchemy 绑定层面转 str 也没问题，
        # 但测试对 get_oldest_short_term 的调用参数做了精确断言（期望 str），
        # 转换会导致既有测试回归，故保留 str 传参（见 pyright 报错，已确认可接受）。
        oldest = await memory_repo.get_oldest_short_term(
            character.id,  # type: ignore[arg-type]
            limit=30,
            exclude_categories=["trivial"],
        )
        if not oldest:
            return

        # ── Load world data ─────────────────────────────────────────────
        world_doc = await world_repo.get(world_id)
        if not world_doc:
            return

        profile = character.profile or {}
        relations = await relation_repo.list_by_world(world_id, str(character.id))
        elements = world_doc.elements or []

        # ── V2: load event index ────────────────────────────────────────
        from src.db.repositories.event_index_repo import EventIndexRepository
        from src.utils.memory_format import format_event_index_for_injection

        event_index_repo = EventIndexRepository(session)
        event_index_list = await event_index_repo.list_by_world(world_id)
        event_index_text = format_event_index_for_injection(event_index_list)
        # Map: E001 -> event UUID string, for matching LLM output
        e_code_to_id: dict[str, str] = {}
        for i, e in enumerate(event_index_list, start=1):
            e_code_to_id[f"E{i:03d}"] = str(e.id)

        # ── V2: collect short-term memory reflections ───────────────────
        reflections_text = ""
        reflection_lines = []
        for m in oldest:
            ref = getattr(m, "short_term_reflection", None)
            if ref:
                reflection_lines.append(f"- {m.content[:30]}... → 感悟：{ref}")
        if reflection_lines:
            reflections_text = "\n短期记忆中的感悟素材：\n" + "\n".join(reflection_lines)

        # ── Build cacheable_system_prefix (shared by both phases) ───────
        title = ""
        author = ""
        if world_doc.source:
            title = getattr(world_doc.source, "title", "") or ""
            author = getattr(world_doc.source, "author", "") or ""

        work_info = f"作品：{title}\n作者：{author}" if title else ""

        char_info = (
            f'<character name="{character.name}">'
            f"<brief>{profile.get('brief', '暂无')}</brief>"
            f"<detail>{profile.get('detail', '暂无')}</detail>"
            f"</character>"
        )

        relations_text = ""
        if relations:
            from src.utils.character_name_cache import get_character_names

            other_ids: set[str] = set()
            for r in relations:
                other_id = (
                    r.character_b if str(r.character_a) == str(character.id) else r.character_a
                )
                other_ids.add(str(other_id))
            id_to_name = await get_character_names(
                list(other_ids), redis=self._redis, character_repo=char_repo
            )

            rel_lines = []
            for r in relations:
                other_id = (
                    r.character_b if str(r.character_a) == str(character.id) else r.character_a
                )
                other_name = id_to_name.get(str(other_id), str(other_id))
                rel_lines.append(f"- 与 {other_name}：{r.description or '未知'}")
            relations_text = "关系：\n" + "\n".join(rel_lines)

        memories_text = "\n".join(
            f'<memory type="short_term">{m.content}</memory>' for m in reversed(oldest)
        )

        elements_brief = "\n".join(f"- {e.name}：{e.brief}" for e in elements if hasattr(e, "name"))

        # Common sense (worldview cognitive differences)
        common_sense_text = ""
        common_sense = getattr(getattr(world_doc, "source", None), "common_sense", None)
        if common_sense:
            common_sense_text = f"\n<world_setting>{common_sense}</world_setting>"

        plot_development_text = ""
        plot_development = getattr(getattr(world_doc, "source", None), "plot_development", None)
        if plot_development:
            plot_development_text = f"\n<plot_development>{plot_development}</plot_development>"

        core_conflict_text = ""
        core_conflict = getattr(getattr(world_doc, "source", None), "core_conflict", None)
        if core_conflict:
            core_conflict_text = f"\n<core_conflict>{core_conflict}</core_conflict>"

        tone_and_atmosphere_text = ""
        tone_and_atmosphere = getattr(
            getattr(world_doc, "source", None), "tone_and_atmosphere", None
        )
        if tone_and_atmosphere:
            tone_and_atmosphere_text = (
                f"\n<tone_and_atmosphere>{tone_and_atmosphere}</tone_and_atmosphere>"
            )

        # Two calls share the same prefix variable (Prompt Cache requirement)
        cacheable_system_prefix = (
            f"{work_info}\n\n"
            f"{char_info}\n\n"
            f"{relations_text}\n\n"
            f"近期记忆（共 {len(oldest)} 条）：\n{memories_text}\n\n"
            f"世界元素概览：\n{elements_brief}"
            f"{common_sense_text}"
            f"{plot_development_text}"
            f"{core_conflict_text}"
            f"{tone_and_atmosphere_text}"
        ).strip()

        # ── Phase 1: select relevant elements ───────────────────────────
        phase1_system = (
            cacheable_system_prefix + "\n\n" + LONG_TERM_SELECT_ELEMENTS_PROMPT + lang_hint
        )
        try:
            phase1_result = await self.llm.complete_json(
                phase1_system,
                "请从元素列表中选出与这批记忆最相关的 5 个元素名称。",
                prefill="[",
                priority=LLMPriority.BACKGROUND,
            )
        except Exception:
            return

        selected_names = _unwrap_list(phase1_result)

        # ── Element name matching (exact first, fuzzy fallback) ─────────
        matched_elements = []
        for llm_name in selected_names:
            if not isinstance(llm_name, str):
                continue
            found = next((e for e in elements if hasattr(e, "name") and e.name == llm_name), None)
            if not found:
                found = next(
                    (
                        e
                        for e in elements
                        if hasattr(e, "name") and (llm_name in e.name or e.name in llm_name)
                    ),
                    None,
                )
            if found:
                matched_elements.append(found)

        elements_detailed = "\n".join(
            f"- {e.name}：{getattr(e, 'detailed', '') or e.brief}" for e in matched_elements
        )

        # ── Build character code mapping ────────────────────────────────
        all_characters_in_world = await char_repo.list_by_world(world_id)
        code_to_id: dict[str, uuid.UUID] = {}
        if all_characters_in_world:
            for idx, c in enumerate(all_characters_in_world):
                code = f"C{idx + 1}"
                # 注意：这里故意保留 str（不转换为 uuid.UUID）——下游
                # add_structured_long_term(involved_characters=...) 在测试里按 str
                # 精确断言，转换会导致既有测试回归（见 pyright 报错，已确认可接受）。
                code_to_id[code] = c.id  # type: ignore[assignment]

        code_mapping_text = ""
        if code_to_id:
            code_lines = [
                f"- {code} = {c.name}"
                for code, c in zip(code_to_id.keys(), all_characters_in_world, strict=False)
            ]
            code_mapping_text = "\n参与角色代号映射：\n" + "\n".join(code_lines)

        # Collect existing event names (for naming consistency reference)
        existing_structured = await memory_repo.list_long_term_structured(uuid.UUID(character.id))
        id_to_name = {str(e.id): e.event_name for e in event_index_list}
        existing_event_names = [
            id_to_name.get(m.event_name, m.event_name) for m in existing_structured if m.event_name
        ]
        event_names_text = ""
        if existing_event_names:
            event_names_text = "\n已有事件名：" + "、".join(existing_event_names)

        # ── V2: build event index injection text ────────────────────────
        event_index_injection = f"\n\n{event_index_text}"

        # ── Phase 2: judge promotion (prefix hits cache) ────────────────
        phase2_system = (
            cacheable_system_prefix
            + "\n\n"
            + f"相关元素详细信息：\n{elements_detailed}\n\n"
            + event_names_text
            + code_mapping_text
            + event_index_injection
            + reflections_text
            + "\n\n"
            + LONG_TERM_PROMOTE_PROMPT
            + lang_hint
        )
        try:
            promote_result = await self.llm.complete_json(
                phase2_system,
                "请判断哪些短期记忆值得晋升为长期记忆，输出结构化的四字段内容。",
                priority=LLMPriority.BACKGROUND,
            )
        except Exception:
            return

        if isinstance(promote_result, list):
            return

        # ── Write long-term memories (structured four fields, V2: event index) ──
        promoted = promote_result.get("promote", [])
        wrote_any = False
        for item in promoted:
            if not isinstance(item, dict):
                continue
            event_name = item.get("event_name", "")
            perspective_detail = item.get("perspective_detail", "")
            reflection = item.get("reflection")
            involved_codes = item.get("involved_characters", [])
            event_code = item.get("event_code", "")

            if not event_name or not perspective_detail:
                continue

            # Translate codes to UUIDs
            involved_ids: list[uuid.UUID] = []
            for code in involved_codes:
                if isinstance(code, str) and code in code_to_id:
                    involved_ids.append(code_to_id[code])

            # V2: Resolve event ID from event index
            event_id_str: str | None = None
            if event_code and event_code in e_code_to_id:
                event_id_str = e_code_to_id[event_code]
            else:
                brief = item.get("event_brief", event_name)
                new_entry = await event_index_repo.add(
                    world_id=uuid.UUID(world_id),
                    event_name=event_name,
                    brief=brief,
                    dissemination=0.5,
                    core_participants=involved_ids or None,
                )
                event_id_str = str(new_entry.id)

            store_event_name = event_id_str

            await memory_repo.add_structured_long_term(
                # 同上：保留 str，测试对 character_id 精确断言，转换会破坏既有测试。
                character_id=character.id,  # type: ignore[arg-type]
                world_id=uuid.UUID(world_id),
                event_name=store_event_name,
                perspective_detail=perspective_detail,
                reflection=reflection,
                involved_characters=involved_ids or None,
            )
            wrote_any = True

        # Only delete short-term memories when at least one was actually promoted
        if wrote_any:
            await memory_repo.delete_by_ids([m.id for m in oldest])
